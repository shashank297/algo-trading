"""Persist experiment inputs before running deterministic research code."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from experiments.models import ExperimentSpec
from experiments.trials import (
    ResearchLineageError,
    ResearchTrial,
    TrialStatus,
    canonical_hash,
)
from storage.duckdb_manager import DuckDBManager
from risk.engine import RiskEngine
from trading_stack.costs import explicit_fixed_cost_schedule
from trading_stack.calendars import MarketCalendar
from trading_stack.datasets import SynchronizedPanelBuilder
from trading_stack.domain import StrategyScope
from trading_stack.pipeline import StrategyPipeline
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.strategies import StrategyRegistry


class ExperimentManager:
    """Run a single-symbol experiment and preserve all reproducibility inputs."""

    def __init__(
        self,
        db: DuckDBManager,
        project_root: Path | None = None,
        india_calendar: MarketCalendar | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.db = db
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.india_calendar = india_calendar
        self.risk_engine = risk_engine

    def run(self, spec: ExperimentSpec, starting_capital: float = 100_000.0) -> dict[str, Any]:
        """Persist, execute, and finalize one experiment against stored data."""

        metadata = StrategyRegistry.metadata(spec.strategy_name)
        if metadata.scope == StrategyScope.SINGLE_ASSET and len(spec.universe) != 1:
            raise ValueError("Single-asset experiments require exactly one symbol; use the mass runner for a universe.")
        if metadata.scope == StrategyScope.CROSS_SECTIONAL and spec.universe_snapshot_id:
            snap_row = self.db.conn.execute(
                "SELECT snapshot_id, name, content_hash FROM universe_snapshots WHERE snapshot_id = ?",
                [spec.universe_snapshot_id],
            ).fetchone()
            if not snap_row:
                raise ValueError(f"Universe snapshot '{spec.universe_snapshot_id}' not found in database. Failing closed.")
            member_rows = self.db.conn.execute(
                "SELECT symbol, provider_symbol FROM universe_snapshot_members WHERE snapshot_id = ?",
                [spec.universe_snapshot_id],
            ).fetchall()
            if not member_rows:
                raise ValueError(f"Universe snapshot '{spec.universe_snapshot_id}' has 0 members in universe_snapshot_members. Failing closed.")
            valid_symbols = set()
            for r in member_rows:
                if r[0]:
                    valid_symbols.add(str(r[0]))
                if r[1]:
                    valid_symbols.add(str(r[1]))
            if spec.universe:
                invalid_members = [s for s in spec.universe if s not in valid_symbols]
                if invalid_members:
                    raise ValueError(
                        f"Experiment universe specification contains symbols {invalid_members} not present in snapshot '{spec.universe_snapshot_id}'."
                    )

        revision = source_revision(self.project_root)
        trial_id: str | None = None
        governed = spec.experiment_family_id is not None

        # Resolve authoritative market-data evidence before trial reservation
        data_hash: str | None = None
        frame_cert_id: str | None = None
        train_start: datetime | None = None
        train_end: datetime | None = None
        resolved_dataset: Any = None
        lineage_error: ResearchLineageError | None = None
        authoritative_certification = governed or spec.require_authoritative_certification
        if authoritative_certification and self.risk_engine is None:
            raise ValueError(
                "Authoritative experiments require an explicitly injected configured RiskEngine."
            )

        if metadata.scope == StrategyScope.CROSS_SECTIONAL:
            try:
                resolved_dataset = SynchronizedPanelBuilder(
                    self.db,
                    calendar=self.india_calendar,
                    strict_calendar=self.india_calendar is not None,
                    require_authoritative_certification=authoritative_certification,
                ).build(
                    spec.universe,
                    spec.timeframe,
                    universe_snapshot_id=spec.universe_snapshot_id,
                    benchmark_symbol=spec.benchmark_symbol,
                    minimum_lookback=metadata.required_lookback,
                )
                data_hash = resolved_dataset.data_hash
                frame_cert_id = resolved_dataset.frame_certification_id
                if not resolved_dataset.panel.empty:
                    train_start = pd.to_datetime(resolved_dataset.panel["timestamp"], utc=True).min().to_pydatetime()
                    train_end = pd.to_datetime(resolved_dataset.panel["timestamp"], utc=True).max().to_pydatetime()
            except Exception as exc:
                data_hash = f"unresolved:{hashlib.sha256(json.dumps(spec.universe, sort_keys=True).encode()).hexdigest()[:16]}"
                lineage_error = ResearchLineageError(
                    f"Authoritative lineage resolution failed for {spec.strategy_name}: {exc}"
                )
        else:
            try:
                pipeline_loader = StrategyPipeline(
                    self.db,
                    india_calendar=self.india_calendar,
                    require_authoritative_certification=authoritative_certification,
                )
                resolved_frame = pipeline_loader.load_candles(
                    spec.universe[0],
                    spec.timeframe,
                    require_authoritative_certification=authoritative_certification,
                    universe_snapshot_id=spec.universe_snapshot_id,
                )
                hash_columns = [
                    c for c in ("timestamp", "open", "high", "low", "close", "volume", "adjustment", "provider_name", "dataset_id")
                    if c in resolved_frame.columns
                ]
                data_hash = hashlib.sha256(
                    pd.util.hash_pandas_object(resolved_frame[hash_columns], index=True).values.tobytes()
                ).hexdigest()
                frame_cert_id = pipeline_loader._last_frame_certification_id
                if not resolved_frame.empty:
                    train_start = pd.to_datetime(resolved_frame["timestamp"], utc=True).min().to_pydatetime()
                    train_end = pd.to_datetime(resolved_frame["timestamp"], utc=True).max().to_pydatetime()
            except Exception as exc:
                data_hash = f"unresolved:{hashlib.sha256(json.dumps(spec.universe, sort_keys=True).encode()).hexdigest()[:16]}"
                lineage_error = ResearchLineageError(
                    f"Authoritative lineage resolution failed for {spec.strategy_name}: {exc}"
                )

        if governed and (lineage_error is not None or not data_hash or data_hash.startswith("unresolved:") or not frame_cert_id):
            failure = lineage_error or ResearchLineageError(
                f"Governed research requires a resolved dataset hash and frame certification for {spec.strategy_name}."
            )
            self._record_lineage_failure(
                spec=spec,
                metadata=metadata,
                revision=revision,
                data_hash=data_hash or f"unresolved:{hashlib.sha256(json.dumps(spec.universe, sort_keys=True).encode()).hexdigest()[:16]}",
                error=failure,
                train_start=train_start,
                train_end=train_end,
            )
            raise failure

        if spec.experiment_family_id:
            trial = ResearchTrial(
                experiment_family_id=spec.experiment_family_id,
                strategy_name=spec.strategy_name,
                strategy_version=metadata.version,
                scope=metadata.scope.value,
                symbol=spec.universe[0] if metadata.scope == StrategyScope.SINGLE_ASSET else None,
                universe_snapshot_id=spec.universe_snapshot_id,
                timeframe=spec.timeframe,
                parameters=spec.parameters,
                source_revision=revision,
                data_hash=data_hash or hashlib.sha256(json.dumps(spec.universe, sort_keys=True).encode()).hexdigest(),
                cost_model_hash=canonical_hash(spec.cost_model),
                cost_model_version=spec.cost_model_version,
                feature_version=spec.feature_version,
                frame_certification_id=frame_cert_id,
                train_start=train_start,
                train_end=train_end,
                fold_id=spec.fold_id,
                parent_trial_id=spec.parent_trial_id,
                status=TrialStatus.PLANNED,
            )
            trial_id = self.db.create_research_trial(trial)
            self.db.transition_research_trial(trial_id, "RUNNING")

        started_at = datetime.now(timezone.utc)
        self.db.log_experiment(
            {
                "experiment_id": spec.experiment_id,
                "strategy_name": spec.strategy_name,
                "strategy_version": metadata.version,
                "universe_json": json.dumps(spec.universe),
                "timeframe": spec.timeframe,
                "mode": spec.mode,
                "parameters_json": json.dumps(spec.parameters, sort_keys=True),
                "feature_version": spec.feature_version,
                "cost_model_json": json.dumps(spec.cost_model, sort_keys=True),
                "benchmark_symbol": spec.benchmark_symbol,
                "source_revision": revision,
                "llm_config_json": json.dumps(spec.llm_config, sort_keys=True),
                "status": "RUNNING",
                "started_at": started_at,
                "notes": spec.notes,
            },
        )
        try:
            outcome: dict[str, Any]
            result: Any
            dataset_id: str | None
            if metadata.scope == StrategyScope.CROSS_SECTIONAL:
                dataset = resolved_dataset if resolved_dataset is not None else SynchronizedPanelBuilder(
                    self.db,
                    calendar=self.india_calendar,
                    strict_calendar=self.india_calendar is not None,
                    require_authoritative_certification=authoritative_certification,
                ).build(
                    spec.universe,
                    spec.timeframe,
                    universe_snapshot_id=spec.universe_snapshot_id,
                    benchmark_symbol=spec.benchmark_symbol,
                    minimum_lookback=metadata.required_lookback,
                )
                schedule = explicit_fixed_cost_schedule(spec.cost_model)
                portfolio_result = PortfolioEventBacktester(schedule, risk_engine=self.risk_engine).run(
                    StrategyRegistry.create(spec.strategy_name, **spec.parameters),
                    dataset,
                    starting_capital=starting_capital,
                    timeframe=spec.timeframe,
                    parameters=spec.parameters,
                    mode=spec.mode,
                )
                self.db.log_portfolio_result(portfolio_result)
                outcome = {"result": portfolio_result.run, "portfolio_result": portfolio_result, "dataset": dataset}
                result = portfolio_result.run
                dataset_id = self._record_dataset_group(dataset, spec.timeframe)
            else:
                outcome = StrategyPipeline(
                    self.db,
                    risk_engine=self.risk_engine,
                    india_calendar=self.india_calendar,
                    require_authoritative_certification=authoritative_certification,
                ).run(
                    strategy_name=spec.strategy_name,
                    symbol=spec.universe[0],
                    timeframe=spec.timeframe,
                    mode=spec.mode,
                    parameters=spec.parameters,
                    starting_capital=starting_capital,
                    cost_model=spec.cost_model,
                    universe_snapshot_id=spec.universe_snapshot_id,
                )
                result = outcome["result"]
                dataset_id = self._latest_dataset_id(spec.universe[0], spec.timeframe)
            self.db.link_experiment_run(spec.experiment_id, result.run_id, dataset_id)
            self.db.log_experiment(
                {
                    "experiment_id": spec.experiment_id,
                    "strategy_name": spec.strategy_name,
                    "strategy_version": metadata.version,
                    "universe_json": json.dumps(spec.universe),
                    "timeframe": spec.timeframe,
                    "mode": spec.mode,
                    "parameters_json": json.dumps(spec.parameters, sort_keys=True),
                    "feature_version": spec.feature_version,
                    "cost_model_json": json.dumps(spec.cost_model, sort_keys=True),
                    "benchmark_symbol": spec.benchmark_symbol,
                    "data_hash": result.data_hash,
                    "source_revision": revision,
                    "llm_config_json": json.dumps(spec.llm_config, sort_keys=True),
                    "status": "SUCCEEDED",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "notes": spec.notes,
                },
            )
            if trial_id:
                metrics_dict = None
                if hasattr(result, "metrics") and result.metrics is not None:
                    metrics_dict = {
                        "sharpe": float(result.metrics.sharpe) if getattr(result.metrics, "sharpe", None) is not None else None,
                        "max_drawdown": float(result.metrics.max_drawdown) if getattr(result.metrics, "max_drawdown", None) is not None else None,
                        "cagr": float(result.metrics.cagr) if getattr(result.metrics, "cagr", None) is not None else None,
                        "total_return": float(result.metrics.total_return) if getattr(result.metrics, "total_return", None) is not None else None,
                        "run_id": result.run_id,
                    }
                self.db.transition_research_trial(trial_id, "SUCCEEDED", metrics=metrics_dict)
            return {"experiment_id": spec.experiment_id, "outcome": outcome}
        except Exception as exc:
            if trial_id:
                self.db.transition_research_trial(trial_id, "FAILED", error_message=str(exc))
            self.db.log_experiment(
                {
                    "experiment_id": spec.experiment_id,
                    "strategy_name": spec.strategy_name,
                    "strategy_version": metadata.version,
                    "universe_json": json.dumps(spec.universe),
                    "timeframe": spec.timeframe,
                    "mode": spec.mode,
                    "parameters_json": json.dumps(spec.parameters, sort_keys=True),
                    "feature_version": spec.feature_version,
                    "cost_model_json": json.dumps(spec.cost_model, sort_keys=True),
                    "benchmark_symbol": spec.benchmark_symbol,
                    "source_revision": revision,
                    "llm_config_json": json.dumps(spec.llm_config, sort_keys=True),
                    "status": "FAILED",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "notes": str(exc),
                },
            )
            raise

    def _record_lineage_failure(
        self,
        *,
        spec: ExperimentSpec,
        metadata: Any,
        revision: str,
        data_hash: str,
        error: ResearchLineageError,
        train_start: datetime | None,
        train_end: datetime | None,
    ) -> None:
        """Retain a governed failed attempt without allowing execution to start."""

        trial = ResearchTrial(
            experiment_family_id=str(spec.experiment_family_id),
            strategy_name=spec.strategy_name,
            strategy_version=metadata.version,
            scope=metadata.scope.value,
            symbol=spec.universe[0] if metadata.scope == StrategyScope.SINGLE_ASSET else None,
            universe_snapshot_id=spec.universe_snapshot_id,
            timeframe=spec.timeframe,
            parameters=spec.parameters,
            source_revision=revision,
            data_hash=data_hash,
            cost_model_hash=canonical_hash(spec.cost_model),
            cost_model_version=spec.cost_model_version,
            feature_version=spec.feature_version,
            train_start=train_start,
            train_end=train_end,
            fold_id=spec.fold_id,
            parent_trial_id=spec.parent_trial_id,
            status=TrialStatus.PLANNED,
        )
        trial_id = self.db.create_research_trial(trial)
        self.db.transition_research_trial(trial_id, "RUNNING")
        self.db.transition_research_trial(trial_id, "FAILED", error_message=str(error))
        now = datetime.now(timezone.utc)
        self.db.log_experiment(
            {
                "experiment_id": spec.experiment_id,
                "strategy_name": spec.strategy_name,
                "strategy_version": metadata.version,
                "universe_json": json.dumps(spec.universe),
                "timeframe": spec.timeframe,
                "mode": spec.mode,
                "parameters_json": json.dumps(spec.parameters, sort_keys=True),
                "feature_version": spec.feature_version,
                "cost_model_json": json.dumps(spec.cost_model, sort_keys=True),
                "benchmark_symbol": spec.benchmark_symbol,
                "data_hash": data_hash,
                "source_revision": revision,
                "llm_config_json": json.dumps(spec.llm_config, sort_keys=True),
                "status": "FAILED",
                "started_at": now,
                "finished_at": now,
                "notes": str(error),
            },
        )

    def _latest_dataset_id(self, symbol: str, timeframe: str) -> str | None:
        row = self.db.conn.execute(
            """
            SELECT dataset_id FROM market_datasets
            WHERE canonical_symbol = ? AND timeframe = ?
              AND lifecycle_status = 'CANONICAL_PROMOTED'
              AND status = 'VERIFIED'
            ORDER BY retrieved_at DESC LIMIT 1
            """,
            [symbol, timeframe],
        ).fetchone()
        return str(row[0]) if row else None

    def _record_dataset_group(self, dataset: Any, timeframe: str) -> str:
        group_id = f"{dataset.universe_snapshot_id}:{timeframe}:{dataset.data_hash[:16]}"
        self.db._replace_rows(
            "dataset_snapshot_groups",
            [{
                "group_id": group_id, "universe_snapshot_id": dataset.universe_snapshot_id,
                "timeframe": timeframe, "benchmark_symbol": dataset.benchmark_symbol,
                "data_hash": dataset.data_hash, "created_at": datetime.now(timezone.utc),
            }],
        )
        exclusions = {} if dataset.exclusions.empty else dict(zip(dataset.exclusions["symbol"], dataset.exclusions["reason"]))
        self.db._replace_rows(
            "dataset_snapshot_group_members",
            [{"group_id": group_id, "symbol": symbol, "dataset_id": dataset_id, "exclusion_reason": exclusions.get(symbol)}
             for symbol, dataset_id in dataset.dataset_snapshot_ids.items()],
        )
        return group_id


def source_revision(project_root: Path) -> str:
    """Use Git when available; otherwise hash local Python sources deterministically."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        revision = result.stdout.strip()
        if revision:
            return revision
    except (OSError, subprocess.SubprocessError):
        pass
    digest = hashlib.sha256()
    tracked_suffixes = {".py", ".sql", ".yaml", ".yml"}
    tracked_names = {"requirements.txt", "pytest.ini"}
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if any(part in {"venv", ".git", "__pycache__", "logs", "reports", "data"} for part in relative.parts):
            continue
        if relative.as_posix() == "config/config.yaml":
            continue
        if path.suffix.lower() not in tracked_suffixes and path.name not in tracked_names:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(path.read_bytes())
    return f"source-tree:{digest.hexdigest()}"
