"""Persist experiment inputs before running deterministic research code."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.models import ExperimentSpec
from storage.duckdb_manager import DuckDBManager
from trading_stack.costs import IndianDeliveryCostSchedule
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
    ) -> None:
        self.db = db
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.india_calendar = india_calendar

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
                "source_revision": source_revision(self.project_root),
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
                dataset = SynchronizedPanelBuilder(
                    self.db,
                    calendar=self.india_calendar,
                    strict_calendar=self.india_calendar is not None,
                    require_authoritative_certification=spec.require_authoritative_certification,
                ).build(
                    spec.universe,
                    spec.timeframe,
                    universe_snapshot_id=spec.universe_snapshot_id,
                    benchmark_symbol=spec.benchmark_symbol,
                    minimum_lookback=metadata.required_lookback,
                )
                allowed = set(IndianDeliveryCostSchedule.__dataclass_fields__)
                schedule_values: dict[str, Any] = {
                    key: value for key, value in spec.cost_model.items() if key in allowed
                }
                schedule = IndianDeliveryCostSchedule(**schedule_values)
                portfolio_result = PortfolioEventBacktester(schedule).run(
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
                    india_calendar=self.india_calendar,
                    require_authoritative_certification=spec.require_authoritative_certification,
                ).run(
                    strategy_name=spec.strategy_name,
                    symbol=spec.universe[0],
                    timeframe=spec.timeframe,
                    mode=spec.mode,
                    parameters=spec.parameters,
                    starting_capital=starting_capital,
                    cost_model=spec.cost_model,
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
                    "source_revision": source_revision(self.project_root),
                    "llm_config_json": json.dumps(spec.llm_config, sort_keys=True),
                    "status": "SUCCEEDED",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "notes": spec.notes,
                },
            )
            return {"experiment_id": spec.experiment_id, "outcome": outcome}
        except Exception as exc:
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
                    "source_revision": source_revision(self.project_root),
                    "llm_config_json": json.dumps(spec.llm_config, sort_keys=True),
                    "status": "FAILED",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "notes": str(exc),
                },
            )
            raise

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
