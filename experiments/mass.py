"""Resumable single-asset matrix and cross-sectional portfolio experiments."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any
from tqdm import tqdm

from experiments.manager import ExperimentManager, source_revision
from experiments.models import ExperimentSpec, MassExperimentSpec
from experiments.walk_forward import WalkForwardEvaluator
from storage.duckdb_manager import DuckDBManager
from trading_stack.domain import StrategyScope
from trading_stack.calendars import MarketCalendar
from trading_stack.strategies import StrategyRegistry


class MassExperimentManager:
    """Expand a research request into deterministic, resumable jobs."""

    def __init__(self, db: DuckDBManager, india_calendar: MarketCalendar | None = None) -> None:
        self.db = db
        self.india_calendar = india_calendar

    def run(self, spec: MassExperimentSpec, starting_capital: float = 100_000.0) -> dict[str, Any]:
        jobs: list[dict[str, Any]] = []
        self.db.recover_stale_research_work(
            datetime.now(timezone.utc) - timedelta(seconds=spec.stale_job_seconds)
        )
        revision = source_revision(ExperimentManager(self.db).project_root)
        data_revision = self.db.market_data_revision()
        self.db.cancel_superseded_experiment_jobs(revision, data_revision)
        for strategy_name in spec.strategy_names:
            metadata = StrategyRegistry.metadata(strategy_name)
            targets: list[list[str]] = [spec.universe] if metadata.scope == StrategyScope.CROSS_SECTIONAL else [[symbol] for symbol in spec.universe]
            for universe in targets:
                parameters = spec.parameters.get(strategy_name, {})
                key = self._job_key(
                    strategy_name, metadata.version, metadata.scope.value, universe,
                    spec.universe_snapshot_id, parameters, spec.cost_model_version, revision,
                    spec.walk_forward_train_size, spec.walk_forward_test_size,
                    spec.timeframe, spec.mode, data_revision,
                )
                existing = self.db.get_experiment_job(key)
                if existing and existing["state"] == "SUCCEEDED":
                    jobs.append({"job_key": key, "state": "SUCCEEDED", "run_id": existing.get("run_id"), "resumed": True})
                    continue
                if existing and existing["state"] == "RUNNING":
                    started_at = existing.get("started_at")
                    if started_at and started_at > datetime.now(timezone.utc) - timedelta(seconds=spec.stale_job_seconds):
                        jobs.append({"job_key": key, "state": "RUNNING", "run_id": existing.get("run_id"), "resumed": True})
                        continue
                payload = {
                    "job_key": key, "experiment_id": spec.experiment_id, "strategy_name": strategy_name,
                    "strategy_version": metadata.version, "strategy_scope": metadata.scope.value,
                    "symbol": universe[0] if metadata.scope == StrategyScope.SINGLE_ASSET else None,
                    "universe_snapshot_id": spec.universe_snapshot_id, "fold_id": None,
                    "parameters_hash": hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest(),
                    "cost_model_version": spec.cost_model_version,
                    "data_revision": data_revision,
                    "source_revision": revision,
                    "state": "RETRYING" if existing else "PENDING",
                    "retry_count": min(int(existing.get("retry_count") or 0) + 1, spec.max_retries) if existing else 0,
                    "max_retries": spec.max_retries,
                }
                # Attach per-symbol data coverage so the dashboard can display it.
                if metadata.scope != StrategyScope.CROSS_SECTIONAL:
                    coverage = self._candle_coverage(universe[0], spec.timeframe)
                    payload.update(coverage)
                self.db.log_experiment_job(payload)
                jobs.append({**payload, "universe": universe, "parameters": parameters})
        pending = [job for job in jobs if job.get("state") not in {"SUCCEEDED", "RUNNING"}]
        
        # Display progress bar for pending jobs
        if not pending:
            pass
        elif spec.max_workers == 1:
            completed = []
            for job in tqdm(pending, desc="Mass Research (Serial)", total=len(pending)):
                completed.append(self._execute(job, spec, starting_capital))
        else:
            completed = []
            with ThreadPoolExecutor(max_workers=spec.max_workers) as executor:
                futures = {executor.submit(self._execute_isolated, job, spec, starting_capital): job for job in pending}
                for future in tqdm(as_completed(futures), desc=f"Mass Research (Workers: {spec.max_workers})", total=len(futures)):
                    completed.append(future.result())
        resumed = [job for job in jobs if job.get("resumed")]
        return {"experiment_id": spec.experiment_id, "jobs": [*resumed, *completed]}

    def _execute_isolated(self, job: dict[str, Any], spec: MassExperimentSpec, capital: float) -> dict[str, Any]:
        db = DuckDBManager(self.db.db_path)
        try:
            return MassExperimentManager(db, self.india_calendar)._execute(job, spec, capital)
        finally:
            db.close()

    def _execute(self, job: dict[str, Any], spec: MassExperimentSpec, capital: float) -> dict[str, Any]:
        base = {key: value for key, value in job.items() if key not in {"universe", "parameters", "resumed"}}
        first_attempt = int(job.get("retry_count") or 0)
        for attempt in range(first_attempt, spec.max_retries + 1):
            now = datetime.now(timezone.utc)
            self.db.log_experiment_job({
                **base, "state": "RUNNING", "retry_count": attempt,
                "error_message": None, "started_at": now, "finished_at": None,
            })
            try:
                experiment_spec = ExperimentSpec(
                    experiment_id=f"{spec.experiment_id}:{job['job_key'][:12]}", strategy_name=job["strategy_name"],
                    strategy_version=job["strategy_version"], universe=job["universe"], timeframe=spec.timeframe,
                    mode=spec.mode, parameters=job["parameters"], benchmark_symbol=spec.benchmark_symbol,
                    universe_snapshot_id=spec.universe_snapshot_id, cost_model=spec.cost_model,
                    cost_model_version=spec.cost_model_version,
                    require_authoritative_certification=spec.require_authoritative_certification,
                    experiment_family_id=spec.experiment_family_id,
                )
                result = ExperimentManager(self.db, india_calendar=self.india_calendar).run(
                    experiment_spec, starting_capital=capital,
                )
                run_id = result["outcome"]["result"].run_id
                folds = WalkForwardEvaluator(self.db, india_calendar=self.india_calendar).evaluate(
                    run_id, experiment_spec, train_size=spec.walk_forward_train_size,
                    test_size=spec.walk_forward_test_size, starting_capital=capital,
                )
                self.db.log_experiment_job({
                    **base, "state": "SUCCEEDED", "retry_count": attempt, "run_id": run_id,
                    "started_at": now, "finished_at": datetime.now(timezone.utc),
                })
                return {"job_key": job["job_key"], "state": "SUCCEEDED", "run_id": run_id, "folds": folds, "resumed": attempt > 0}
            except Exception as exc:
                terminal = attempt >= spec.max_retries
                self.db.log_experiment_job({
                    **base, "state": "FAILED" if terminal else "RETRYING",
                    "retry_count": attempt, "error_message": str(exc),
                    "started_at": now, "finished_at": datetime.now(timezone.utc) if terminal else None,
                })
                if terminal:
                    return {"job_key": job["job_key"], "state": "FAILED", "error": str(exc), "resumed": attempt > 0}
        raise RuntimeError("Mass experiment retry loop ended unexpectedly.")

    @staticmethod
    def _job_key(strategy: str, version: str, scope: str, universe: list[str], snapshot: str, parameters: dict[str, Any], cost_version: str, revision: str, train_size: int, test_size: int, timeframe: str, mode: str, data_revision: int = 0) -> str:
        payload = json.dumps({
            "strategy": strategy, "version": version, "scope": scope, "universe": sorted(universe),
            "snapshot": snapshot, "parameters": parameters, "cost_version": cost_version, "revision": revision,
            "walk_forward_train_size": train_size, "walk_forward_test_size": test_size,
            "timeframe": timeframe, "mode": mode, "data_revision": data_revision,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _candle_coverage(self, symbol: str, timeframe: str) -> dict[str, Any]:
        """Query the actual data coverage for a symbol and return data_from, data_to, bar_count."""
        row = self.db.conn.execute(
            """
            SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
            FROM historical_candles
            WHERE symbol = ? AND timeframe = ?
            """,
            [symbol, timeframe],
        ).fetchone()
        if row and row[2]:
            return {"data_from": row[0], "data_to": row[1], "bar_count": int(row[2])}
        return {"data_from": None, "data_to": None, "bar_count": 0}
