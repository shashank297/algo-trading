"""Expanding walk-forward evaluation with fold-local parameter selection."""

from __future__ import annotations

import itertools
import json
import hashlib
from dataclasses import asdict
from typing import Any

import pandas as pd

from experiments.models import ExperimentSpec
from storage import DuckDBManager
from trading_stack.backtest import EventDrivenBacktester, ExecutionModel, _compute_metrics
from trading_stack.calendars import MarketCalendar
from trading_stack.costs import IndianDeliveryCostSchedule
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
    ) -> None:
        self.db = db
        self.maximum_candidates = maximum_candidates
        self.india_calendar = india_calendar

    def evaluate(
        self,
        parent_run_id: str,
        spec: ExperimentSpec,
        *,
        train_size: int = 252,
        test_size: int = 63,
        starting_capital: float = 100_000.0,
    ) -> list[str]:
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
                    JOIN experiment_jobs j ON f.run_id = j.job_key
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
                spec, metadata.scope, train_source, candidates, starting_capital,
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
                self.db, calendar=self.india_calendar, strict_calendar=self.india_calendar is not None,
            ).build(
                spec.universe,
                spec.timeframe,
                universe_snapshot_id=spec.universe_snapshot_id,
                benchmark_symbol=spec.benchmark_symbol,
                minimum_lookback=lookback,
            )
        bars = self.db.conn.execute(
            """SELECT symbol, exchange, timeframe, timestamp, open, high, low, close, volume,
                      adjustment, provider_name, dataset_id
               FROM historical_candles WHERE symbol = ? AND timeframe = ? ORDER BY timestamp""",
            [spec.universe[0], spec.timeframe],
        ).df()
        if bars.empty:
            raise ValueError(f"No candles found for {spec.universe[0]} {spec.timeframe}.")
        if self.india_calendar is not None:
            validation = self.india_calendar.validate_bars(bars["timestamp"], spec.timeframe)
            if validation.out_of_session_count:
                raise ValueError("Walk-forward source contains bars outside the verified NSE calendar.")
        panel = FeatureFactory().build(bars, timezone_name="Asia/Kolkata")
        panel["symbol"] = spec.universe[0]
        return ResearchDataset(spec.universe_snapshot_id, {spec.universe[0]: None}, panel)

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
    ) -> tuple[dict[str, Any], float]:
        ranked: list[tuple[float, float, str, dict[str, Any]]] = []
        for parameters in candidates:
            replay = self._run(spec, scope, source, parameters, capital)
            result = replay.run if hasattr(replay, "run") else replay
            ranked.append((
                float(result.metrics.sharpe),
                float(result.metrics.max_drawdown),
                json.dumps(parameters, sort_keys=True, default=str),
                parameters,
            ))
        best = max(ranked, key=lambda value: (value[0], value[1], value[2]))
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
            allowed = set(IndianDeliveryCostSchedule.__dataclass_fields__)
            schedule_values: dict[str, Any] = {
                key: value for key, value in spec.cost_model.items() if key in allowed
            }
            schedule = IndianDeliveryCostSchedule(**schedule_values)
            return PortfolioEventBacktester(schedule).run(
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
        return EventDrivenBacktester(ExecutionModel(**execution_values)).run(
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
