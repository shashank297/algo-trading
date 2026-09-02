"""Expanding walk-forward evaluation with fold-local parameter selection."""

from __future__ import annotations

import itertools
import json
import hashlib
from dataclasses import asdict
from typing import Any

import pandas as pd
from loguru import logger
from risk.engine import RiskEngine

from experiments.manager import source_revision
from experiments.models import ExperimentSpec
from experiments.trials import (
    ResearchIntegrityError,
    ResearchLineageError,
    ResearchTrial,
    TrialStatus,
    canonical_hash,
    is_research_governance_error,
)
from storage import DuckDBManager
from trading_stack.backtest import EventDrivenBacktester, ExecutionModel, _compute_metrics
from trading_stack.calendars import MarketCalendar
from trading_stack.costs import IndianDeliveryCostSchedule, explicit_fixed_cost_schedule, get_cost_schedule
from trading_stack.datasets import ResearchDataset, SynchronizedPanelBuilder
from trading_stack.domain import AssetClass, StrategyScope
from trading_stack.features import FeatureFactory
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.pipeline import StrategyPipeline
from trading_stack.strategies import StrategyRegistry


class WalkForwardEvaluator:
    """Select parameters on each expanding train fold and replay its test fold."""

    def __init__(
        self,
        db: DuckDBManager,
        *,
        maximum_candidates: int = 32,
        india_calendar: MarketCalendar | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.db = db
        self.maximum_candidates = maximum_candidates
        self.india_calendar = india_calendar
        self.risk_engine = risk_engine

    def evaluate(
        self,
        parent_run_id: str,
        spec: ExperimentSpec,
        *,
        train_size: int = 252,
        test_size: int = 63,
        starting_capital: float = 100_000.0,
    ) -> list[str]:
        if (spec.require_authoritative_certification or spec.experiment_family_id) and self.risk_engine is None:
            raise ValueError(
                "Authoritative walk-forward evaluation requires an explicitly injected configured RiskEngine."
            )
        metadata = StrategyRegistry.metadata(spec.strategy_name)
        source = self._source(spec, metadata.scope, metadata.required_lookback)
        dates = pd.DatetimeIndex(
            pd.to_datetime(source.panel["timestamp"], utc=True).drop_duplicates().sort_values()
        )
        candidates = self._candidates(spec.parameters, metadata.parameter_grid)
        fold_ids: list[str] = []
        cursor = max(train_size, metadata.required_lookback)
        while cursor + test_size <= len(dates):
            train_dates = dates[:cursor]
            test_dates = dates[cursor:cursor + test_size]
            fold_id = f"wf-{len(fold_ids) + 1:03d}"
            
            train_source = self._slice(source, train_dates[0], train_dates[-1])
            test_source = self._slice(source, test_dates[0], test_dates[-1])
            
            try:
                parameters_hash = hashlib.sha256(json.dumps(spec.parameters, sort_keys=True).encode()).hexdigest()
                existing = self.db.conn.execute(
                    """
                    SELECT f.selected_parameters_json 
                    FROM walk_forward_folds f
                    JOIN experiment_jobs j ON f.run_id = j.run_id
                    WHERE j.strategy_name = ?
                      AND j.strategy_version = ?
                      AND j.parameters_hash = ?
                      AND f.fold_id = ? 
                      AND f.train_data_hash = ? 
                      AND f.test_data_hash = ?
                    ORDER BY f.created_at DESC LIMIT 1
                    """,
                    [spec.strategy_name, metadata.version, parameters_hash, fold_id, train_source.data_hash, test_source.data_hash]
                ).fetchone()
                if existing:
                    fold_ids.append(fold_id)
                    cursor += test_size
                    continue
            except Exception:
                pass  # Table might not exist yet

            selected, training_score = self._select(
                spec, metadata.scope, train_source, candidates, starting_capital, fold_id=fold_id,
            )
            replay_source = self._slice(source, train_dates[0], test_dates[-1])
            replay = self._run(spec, metadata.scope, replay_source, selected, starting_capital)
            self._persist_fold(
                parent_run_id=parent_run_id,
                fold_id=fold_id,
                replay=replay,
                train_dates=train_dates,
                test_dates=test_dates,
                selected=selected,
                candidate_count=len(candidates),
                training_score=training_score,
                train_hash=train_source.data_hash,
                test_hash=test_source.data_hash,
                timeframe=spec.timeframe,
                starting_capital=starting_capital,
                cost_model=spec.cost_model,
            )
            fold_ids.append(fold_id)
            cursor += test_size
        return fold_ids

    def _source(self, spec: ExperimentSpec, scope: StrategyScope, lookback: int) -> ResearchDataset:
        if scope == StrategyScope.CROSS_SECTIONAL:
            return SynchronizedPanelBuilder(
                self.db,
                calendar=self.india_calendar,
                strict_calendar=self.india_calendar is not None,
                require_authoritative_certification=spec.require_authoritative_certification,
            ).build(
                spec.universe,
                spec.timeframe,
                universe_snapshot_id=spec.universe_snapshot_id,
                benchmark_symbol=spec.benchmark_symbol,
                minimum_lookback=lookback,
            )
        from trading_stack.pipeline import StrategyPipeline
        pipeline = StrategyPipeline(
            self.db,
            require_authoritative_certification=spec.require_authoritative_certification,
            strict_calendar=self.india_calendar is not None,
        )
        symbol = spec.universe[0]
        if spec.universe_snapshot_id:
            bars = pipeline.load_candles(
                symbol,
                spec.timeframe,
                universe_snapshot_id=spec.universe_snapshot_id,
            )
        else:
            bars = pipeline.load_candles(symbol, spec.timeframe)
        if bars.empty:
            raise ValueError(f"No candles found for {symbol} {spec.timeframe}.")
        if self.india_calendar is not None:
            validation = self.india_calendar.validate_bars(bars["timestamp"], spec.timeframe)
            if validation.out_of_session_count:
                raise ValueError("Walk-forward source contains bars outside the verified NSE calendar.")
        panel = FeatureFactory().build(bars, timezone_name="Asia/Kolkata")
        panel["symbol"] = symbol
        frame_cert_id = getattr(pipeline, "_last_frame_certification_id", None)
        contributing_dataset_ids = tuple(
            str(x).strip() for x in bars["dataset_id"].dropna().unique() if str(x).strip()
        ) if "dataset_id" in bars.columns else ()
        dq_certs: list[str] = []
        dataset_hashes: dict[str, str] = {}
        pit_hash: str | None = None
        if frame_cert_id:
            row = self.db.conn.execute(
                "SELECT dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash FROM research_frame_certifications WHERE frame_certification_id = ?",
                [frame_cert_id],
            ).fetchone()
            if row:
                if row[0]:
                    try:
                        dataset_hashes = json.loads(str(row[0]))
                    except Exception:
                        pass
                if row[1]:
                    try:
                        dq_certs = json.loads(str(row[1]))
                    except Exception:
                        pass
                pit_hash = str(row[2]) if row[2] else None
        return ResearchDataset(
            universe_snapshot_id=spec.universe_snapshot_id,
            dataset_snapshot_ids={symbol: contributing_dataset_ids[0] if contributing_dataset_ids else None},
            panel=panel,
            frame_certification_id=frame_cert_id,
            contributing_dataset_ids=contributing_dataset_ids,
            dq_certification_ids=tuple(dq_certs),
            dataset_content_hashes=dataset_hashes,
            pit_evidence_hash=pit_hash,
        )

    def _candidates(
        self,
        explicit: dict[str, Any],
        parameter_grid: dict[str, tuple[Any, ...]],
    ) -> list[dict[str, Any]]:
        variable = {key: values for key, values in parameter_grid.items() if key not in explicit}
        if not variable:
            return [dict(explicit)]
        keys = sorted(variable)
        combinations = itertools.product(*(variable[key] for key in keys))
        candidates = [
            {**explicit, **dict(zip(keys, values))}
            for values in itertools.islice(combinations, self.maximum_candidates)
        ]
        return candidates or [dict(explicit)]

    def _select(
        self,
        spec: ExperimentSpec,
        scope: StrategyScope,
        source: ResearchDataset,
        candidates: list[dict[str, Any]],
        capital: float,
        fold_id: str | None = None,
    ) -> tuple[dict[str, Any], float]:
        from pathlib import Path
        metadata = StrategyRegistry.metadata(spec.strategy_name)
        revision = source_revision(Path(__file__).resolve().parent.parent)
        train_start = pd.to_datetime(source.panel["timestamp"], utc=True).min() if not source.panel.empty else None
        train_end = pd.to_datetime(source.panel["timestamp"], utc=True).max() if not source.panel.empty else None
        candidate_trial_ids: dict[str, str] = {}
        ranked: list[tuple[float, float, str, dict[str, Any]]] = []

        if spec.experiment_family_id:
            data_hash = str(getattr(source, "data_hash", "") or "").strip()
            frame_certification_id = str(getattr(source, "frame_certification_id", "") or "").strip()
            if not data_hash or data_hash.startswith("unresolved:") or not frame_certification_id:
                raise ResearchLineageError(
                    "Walk-forward candidate selection requires resolved data and frame lineage."
                )

        for parameters in candidates:
            trial_id: str | None = None
            if spec.experiment_family_id:
                trial = ResearchTrial(
                    experiment_family_id=spec.experiment_family_id,
                    strategy_name=spec.strategy_name,
                    strategy_version=metadata.version,
                    scope=scope.value,
                    symbol=spec.universe[0] if scope == StrategyScope.SINGLE_ASSET else None,
                    universe_snapshot_id=spec.universe_snapshot_id,
                    timeframe=spec.timeframe,
                    parameters=parameters,
                    source_revision=revision,
                    data_hash=source.data_hash,
                    cost_model_hash=canonical_hash(spec.cost_model),
                    cost_model_version=spec.cost_model_version,
                    feature_version=spec.feature_version,
                    frame_certification_id=source.frame_certification_id,
                    fold_id=fold_id,
                    parent_trial_id=spec.parent_trial_id,
                    train_start=train_start.to_pydatetime() if train_start is not None and hasattr(train_start, "to_pydatetime") else None,
                    train_end=train_end.to_pydatetime() if train_end is not None and hasattr(train_end, "to_pydatetime") else None,
                    status=TrialStatus.PLANNED,
                )
                # Atomically reserve budget BEFORE candidate execution
                trial_id = self.db.create_research_trial(trial)
                self.db.transition_research_trial(trial_id, "RUNNING")

            try:
                replay = self._run(spec, scope, source, parameters, capital)
                result = getattr(replay, "run") if hasattr(replay, "run") and hasattr(getattr(replay, "run"), "metrics") else replay
                param_key = json.dumps(parameters, sort_keys=True, default=str)
                if trial_id:
                    metrics_dict = {
                        "sharpe": float(result.metrics.sharpe) if getattr(result.metrics, "sharpe", None) is not None else None,
                        "max_drawdown": float(result.metrics.max_drawdown) if getattr(result.metrics, "max_drawdown", None) is not None else None,
                        "cagr": float(result.metrics.cagr) if getattr(result.metrics, "cagr", None) is not None else None,
                        "total_return": float(result.metrics.total_return) if getattr(result.metrics, "total_return", None) is not None else None,
                        "run_id": str(getattr(result, "run_id", "")) if getattr(result, "run_id", None) is not None else None,
                    }
                    self.db.transition_research_trial(trial_id, "SUCCEEDED", metrics=metrics_dict)
                    candidate_trial_ids[param_key] = trial_id
                ranked.append((
                    float(result.metrics.sharpe),
                    float(result.metrics.max_drawdown),
                    param_key,
                    parameters,
                ))
            except Exception as exc:
                if trial_id:
                    self.db.transition_research_trial(trial_id, "FAILED", error_message=str(exc))
                if is_research_governance_error(exc):
                    raise ResearchIntegrityError(
                        f"Governed walk-forward candidate {parameters} failed; aborting search."
                    ) from exc
                logger.warning(f"Candidate {parameters} evaluation failed: {exc}. Retaining FAILED trial and continuing search.")

        if not ranked:
            raise RuntimeError("No candidate evaluations succeeded during walk-forward parameter selection.")
        best = max(ranked, key=lambda value: (value[0], value[1], value[2]))
        best_key = json.dumps(best[3], sort_keys=True, default=str)
        if spec.experiment_family_id and best_key in candidate_trial_ids:
            self.db.mark_trial_selected(candidate_trial_ids[best_key], True)
        return dict(best[3]), best[0]

    def _run(
        self,
        spec: ExperimentSpec,
        scope: StrategyScope,
        source: ResearchDataset,
        parameters: dict[str, Any],
        capital: float,
    ) -> Any:
        strategy = StrategyRegistry.create(spec.strategy_name, **parameters)
        if scope == StrategyScope.CROSS_SECTIONAL:
            schedule = explicit_fixed_cost_schedule(spec.cost_model)
            return PortfolioEventBacktester(schedule, risk_engine=self.risk_engine).run(
                strategy,
                source,
                starting_capital=capital,
                timeframe=spec.timeframe,
                parameters=parameters,
                mode="event-driven",
            )
        allowed = set(ExecutionModel.__dataclass_fields__)
        execution_values: dict[str, Any] = {
            key: value for key, value in spec.cost_model.items() if key in allowed
        }
        indian = {
            key: value for key, value in spec.cost_model.items()
            if key in IndianDeliveryCostSchedule.__dataclass_fields__
        }
        if indian:
            execution_values["indian_delivery_costs"] = indian
        else:
            execution_values["indian_delivery_costs"] = asdict(get_cost_schedule())
        return EventDrivenBacktester(
            ExecutionModel(**execution_values), risk_engine=self.risk_engine,
        ).run(
            strategy,
            source.panel,
            starting_capital=capital,
            market_asset_class=AssetClass.INDIA_EQUITY,
            symbol=spec.universe[0],
            timeframe=spec.timeframe,
            parameters=parameters,
        )

    @staticmethod
    def _slice(source: ResearchDataset, start: pd.Timestamp, end: pd.Timestamp) -> ResearchDataset:
        timestamps = pd.to_datetime(source.panel["timestamp"], utc=True)
        panel = source.panel.loc[(timestamps >= start) & (timestamps <= end)].copy()
        return ResearchDataset(
            universe_snapshot_id=source.universe_snapshot_id,
            dataset_snapshot_ids=dict(source.dataset_snapshot_ids),
            panel=panel,
            benchmark_symbol=source.benchmark_symbol,
            benchmark_provider_symbol=source.benchmark_provider_symbol,
            benchmark_relationship=source.benchmark_relationship,
            exclusions=source.exclusions.copy(),
            survivorship_bias=source.survivorship_bias,
            universe_name=source.universe_name,
            source_basis=source.source_basis,
            canonical_basis=source.canonical_basis,
            research_basis=source.research_basis,
            corporate_action_version=source.corporate_action_version,
            frame_certification_id=source.frame_certification_id,
            contributing_dataset_ids=source.contributing_dataset_ids,
            dq_certification_ids=source.dq_certification_ids,
            dataset_content_hashes=dict(source.dataset_content_hashes),
            pit_evidence_hash=source.pit_evidence_hash,
        )

    def _persist_fold(
        self,
        *,
        parent_run_id: str,
        fold_id: str,
        replay: Any,
        train_dates: pd.DatetimeIndex,
        test_dates: pd.DatetimeIndex,
        selected: dict[str, Any],
        candidate_count: int,
        training_score: float,
        train_hash: str,
        test_hash: str,
        timeframe: str,
        starting_capital: float,
        cost_model: dict[str, Any],
    ) -> None:
        strategy_run = replay.run if hasattr(replay, "run") else replay
        curve = strategy_run.equity_curve.copy()
        timestamps = pd.to_datetime(curve["timestamp"], utc=True)
        test_curve = curve.loc[(timestamps >= test_dates[0]) & (timestamps <= test_dates[-1])].copy()
        if test_curve.empty:
            raise ValueError(f"Walk-forward fold {fold_id} produced no test equity rows.")
        test_returns = test_curve["net_return"].fillna(0.0)
        test_curve["equity"] = starting_capital * (1 + test_returns).cumprod()
        test_curve["drawdown"] = test_curve["equity"] / test_curve["equity"].cummax() - 1.0
        fills = strategy_run.fills
        if not fills.empty:
            fill_time = pd.to_datetime(fills["timestamp"], utc=True)
            fills = fills.loc[(fill_time >= test_dates[0]) & (fill_time <= test_dates[-1])]
        metrics = _compute_metrics(
            equity_curve=test_curve,
            net_returns=test_returns,
            fills=fills,
            execution_model=ExecutionModel(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        if hasattr(replay, "attribution"):
            attribution = replay.attribution.copy()
            round_trips = replay.round_trips.copy()
        else:
            allowed = set(ExecutionModel.__dataclass_fields__)
            execution_values = {key: value for key, value in cost_model.items() if key in allowed}
            indian = {
                key: value for key, value in cost_model.items()
                if key in IndianDeliveryCostSchedule.__dataclass_fields__
            }
            if indian:
                execution_values["indian_delivery_costs"] = indian
            attribution, round_trips, _ = StrategyPipeline(
                self.db, india_calendar=self.india_calendar,
            )._persist_single_asset_attribution(
                strategy_run, ExecutionModel(**execution_values), persist=False,
            )
        with self.db.transaction():
            self.db.conn.execute(
                "DELETE FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE' AND fold_id = ?",
                [parent_run_id, fold_id],
            )
            self.db.conn.execute(
                "DELETE FROM walk_forward_trade_attribution WHERE run_id = ? AND fold_id = ?",
                [parent_run_id, fold_id],
            )
            self.db.conn.execute(
                "DELETE FROM walk_forward_round_trips WHERE run_id = ? AND fold_id = ?",
                [parent_run_id, fold_id],
            )
            self.db.log_equity_curve(
                parent_run_id, test_curve, evidence_level="OUT_OF_SAMPLE", fold_id=fold_id,
            )
            self.db._replace_rows("walk_forward_folds", [{
                "run_id": parent_run_id,
                "fold_id": fold_id,
                "train_start": train_dates[0],
                "train_end": train_dates[-1],
                "test_start": test_dates[0],
                "test_end": test_dates[-1],
                "selected_parameters_json": json.dumps(selected, sort_keys=True, default=str),
                "candidate_count": candidate_count,
                "training_score": training_score,
                "train_data_hash": train_hash,
                "test_data_hash": test_hash,
            }])
            self.db._replace_rows("walk_forward_metrics", [{
                "run_id": parent_run_id,
                "fold_id": fold_id,
                "train_end": train_dates[-1],
                "test_start": test_dates[0],
                "test_end": test_dates[-1],
                "metric_name": name,
                "metric_value": float(value),
            } for name, value in asdict(metrics).items()])
            if not attribution.empty:
                attribution_timestamps = pd.to_datetime(attribution["timestamp"], utc=True)
                attribution = attribution.loc[
                    (attribution_timestamps >= test_dates[0])
                    & (attribution_timestamps <= test_dates[-1])
                ].copy()
                if not attribution.empty:
                    attribution["run_id"] = parent_run_id
                    attribution["fold_id"] = fold_id
                    columns = [
                        "run_id", "fold_id", "timestamp", "symbol", "side", "reason",
                        "realized_pnl", "cost", "target_weight", "quantity", "gross_pnl",
                        "holding_period_days", "exit_classification",
                    ]
                    self.db._replace_frame("walk_forward_trade_attribution", attribution[columns])
            if not round_trips.empty:
                exit_timestamps = pd.to_datetime(round_trips["exit_timestamp"], utc=True)
                round_trips = round_trips.loc[
                    (exit_timestamps >= test_dates[0]) & (exit_timestamps <= test_dates[-1])
                ].copy()
            if not round_trips.empty:
                round_trips["run_id"] = parent_run_id
                round_trips["fold_id"] = fold_id
                columns = [
                    "trade_id", "run_id", "fold_id", "symbol", "entry_timestamp",
                    "exit_timestamp", "quantity", "entry_price", "exit_price",
                    "entry_cost", "exit_cost", "gross_pnl", "net_pnl",
                    "holding_period_days", "entry_reason", "exit_reason",
                    "exit_classification",
                ]
                self.db._replace_frame("walk_forward_round_trips", round_trips[columns])


class WalkForwardRecorder:
    """Deprecated guard against mislabeling slices of a completed run as OOS."""

    def __init__(self, db: DuckDBManager) -> None:
        self.db = db

    def record(self, *_: Any, **__: Any) -> list[str]:
        raise RuntimeError(
            "Completed-curve slicing is not walk-forward validation; use WalkForwardEvaluator.evaluate()."
        )
