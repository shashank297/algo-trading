"""Schedule ingestion, forward-only paper sessions, and safe archival."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from main import apply_env_overrides, configured_nse_calendar, load_yaml, main, validate_config
from storage import DuckDBManager
from risk import build_risk_engine
from trading_stack.pipeline import StrategyPipeline
from utils import LoggerSetup
from utils.timezone import IST


PROJECT_ROOT = Path(__file__).resolve().parent


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def load_runtime_config() -> dict[str, Any]:
    config = apply_env_overrides(load_yaml(str(PROJECT_ROOT / "config" / "config.yaml")))
    validate_config(config)
    return config


def advance_active_paper_sessions(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Advance approved ACTIVE sessions after ingestion closes its DB connection."""

    database = Path(str(config["database"]["path"]))
    if not database.is_absolute():
        database = PROJECT_ROOT / database
    db = DuckDBManager(str(database.resolve()))
    results: list[dict[str, Any]] = []
    try:
        sessions = db.conn.execute(
            """SELECT 'SINGLE' AS session_scope, session_id, approved_run_id, strategy_name, symbol,
                      timeframe, parameters_json, starting_capital,
                      NULL universe_snapshot_id, NULL benchmark_symbol
               FROM paper_sessions
               WHERE status = 'ACTIVE' AND approved_run_id IS NOT NULL
               UNION ALL
               SELECT 'PORTFOLIO' AS session_scope, session_id, approved_run_id, strategy_name,
                      NULL symbol, timeframe, parameters_json, starting_capital,
                      universe_snapshot_id, benchmark_symbol
               FROM paper_portfolio_sessions
               WHERE status = 'ACTIVE' AND approved_run_id IS NOT NULL
               ORDER BY session_id"""
        ).fetchall()
        for (
            scope, session_id, approved_run_id, strategy_name, symbol, timeframe,
            parameters_json, capital, universe_snapshot_id, benchmark_symbol,
        ) in sessions:
            operation_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc)
            try:
                universe: list[str] | None = None
                if str(scope) == "PORTFOLIO":
                    universe = [str(row[0]) for row in db.conn.execute(
                        """SELECT provider_symbol FROM universe_snapshot_members
                           WHERE snapshot_id = ? AND active_to IS NULL
                             AND liquidity_eligible AND data_eligible AND paper_eligible
                             AND provider_symbol IS NOT NULL ORDER BY symbol""",
                        [universe_snapshot_id],
                    ).fetchall()]
                    if not universe:
                        raise ValueError(f"No eligible symbols for paper snapshot {universe_snapshot_id}.")
                outcome = StrategyPipeline(
                    db,
                    risk_engine=build_risk_engine(config),
                    india_calendar=configured_nse_calendar(config),
                ).run_paper_session(
                    strategy_name=str(strategy_name),
                    approved_run_id=str(approved_run_id),
                    symbol=str(symbol or "PORTFOLIO"),
                    timeframe=str(timeframe),
                    universe=universe,
                    universe_snapshot_id=str(universe_snapshot_id or "CONFIGURED_UNIVERSE"),
                    benchmark_symbol=str(benchmark_symbol or "NIFTY200"),
                    parameters=json.loads(str(parameters_json)),
                    starting_capital=float(capital),
                    cost_model=dict(config.get("research", {}).get("indian_delivery_costs", {})),
                )
                forward = outcome.get("forward_result") or outcome["forward_portfolio_result"]
                result = {
                    "session_id": str(session_id),
                    "status": str(forward.status),
                    "processed_bars": int(
                        getattr(forward, "processed_bars", getattr(forward, "processed_sessions", 0))
                    ),
                }
                db._replace_rows("scheduled_operations", [{
                    "operation_id": operation_id,
                    "operation_type": "PAPER_ADVANCE",
                    "subject_id": str(session_id),
                    "status": "SUCCEEDED",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "details_json": json.dumps(result, sort_keys=True),
                    "error_message": None,
                }])
                results.append(result)
            except Exception as exc:
                db._replace_rows("scheduled_operations", [{
                    "operation_id": operation_id,
                    "operation_type": "PAPER_ADVANCE",
                    "subject_id": str(session_id),
                    "status": "FAILED",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "details_json": "{}",
                    "error_message": str(exc),
                }])
                logger.exception("Scheduled paper session {} failed: {}", session_id, exc)
                results.append({"session_id": str(session_id), "status": "FAILED", "error": str(exc)})
        return results
    finally:
        db.close()


def run_job() -> None:
    """Run ingestion, then advance approved paper sessions only on success."""

    operation_logger = logger.bind(
        component="scheduler", command="daily_ingestion_and_paper", operation_id=str(uuid.uuid4()),
    )
    operation_logger.info("Scheduled ingestion starting at {}", datetime.now(IST))
    try:
        config = load_runtime_config()
        operations = config.get("operations", {})
        arguments: list[str] = []
        snapshot = operations.get("ingestion_universe_snapshot")
        if snapshot:
            arguments.extend(["--universe-snapshot", str(snapshot)])
            benchmark = operations.get("benchmark", "NIFTY200")
            arguments.extend(["--benchmark", str(benchmark)])
        exit_code = main(arguments)
        if exit_code != 0:
            operation_logger.error("Scheduled ingestion finished with exit code {}; paper sessions were not advanced.", exit_code)
            return
        operation_logger.info("Scheduled ingestion completed successfully.")
        if bool(operations.get("paper_after_ingestion", False)):
            results = advance_active_paper_sessions(config)
            failures = sum(result.get("status") == "FAILED" for result in results)
            operation_logger.info("Scheduled paper advancement completed sessions={} failures={}", len(results), failures)
    except Exception as exc:
        operation_logger.exception("Scheduled operation failed unexpectedly: {}", exc)


class ProcessLock:
    """Cross-platform single-process advisory lock."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._file: Any | None = None

    def acquire(self) -> bool:
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.lock_path, "a+")
            if sys.platform == "win32":
                import msvcrt

                locking_fn = getattr(msvcrt, "locking")
                mode = getattr(msvcrt, "LK_NBLCK")
                locking_fn(self._file.fileno(), mode, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            return False

    def release(self) -> None:
        if self._file is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    locking_fn = getattr(msvcrt, "locking")
                    mode = getattr(msvcrt, "LK_UNLCK")
                    locking_fn(self._file.fileno(), mode, 1)
                else:
                    import fcntl

                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
            except Exception:
                pass


def start_scheduler() -> None:
    """Start daily ingestion/paper advancement and weekly safe archival."""

    lock = ProcessLock(PROJECT_ROOT / "logs" / "scheduler.lock")
    if not lock.acquire():
        logger.error("Another scheduler process is already running. Exiting to prevent concurrent writers.")
        raise RuntimeError("Another scheduler process is already running.")

    config = load_runtime_config()
    logging_path = Path(str(config["logging"]["path"]))
    if not logging_path.is_absolute():
        config["logging"]["path"] = str((PROJECT_ROOT / logging_path).resolve())
    LoggerSetup.setup(config, component="scheduler", command="scheduler-service")
    scheduler = BackgroundScheduler(timezone=IST)
    trigger = CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=IST)
    scheduler.add_job(
        func=run_job,
        trigger=trigger,
        id="daily_ingestion_and_paper",
        name="Daily ingestion and approved forward paper advancement",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    archive_trigger = CronTrigger(day_of_week="sat", hour=2, minute=0, timezone=IST)
    from tools.archive_to_parquet import archive_data

    scheduler.add_job(
        func=lambda: archive_data(months_old=6),
        trigger=archive_trigger,
        id="weekly_archival",
        name="Weekly DuckDB to Parquet archival",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduler starting; next ingestion is {}", trigger.get_next_fire_time(None, datetime.now(IST)))
    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler")
        scheduler.shutdown()


if __name__ == "__main__":
    start_scheduler()
