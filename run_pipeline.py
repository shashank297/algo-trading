"""Fail-closed end-to-end research pipeline orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from main import apply_env_overrides, load_yaml, validate_config
from risk import build_risk_engine
from storage.integrity import DatabaseIntegrityValidator
from trading_stack.costs import get_cost_schedule
from trading_stack.economic import economic_contract_hash
from trading_stack.universe import UniverseResearchService


PROJECT_ROOT = Path(__file__).resolve().parent
CAMPAIGN_STARTING_CAPITAL = 100_000.0
REQUIRED_RESEARCH_TABLES = frozenset({
    "historical_candles",
    "market_datasets",
    "universe_snapshots",
    "universe_snapshot_members",
    "index_constituents_pit",
})


@dataclass(frozen=True)
class PreflightResult:
    """Machine-readable result for the read-only campaign readiness gate."""

    ready: bool
    details: dict[str, Any] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()

    def print(self) -> None:
        print(json.dumps({**self.details, "blockers": list(self.blockers)}, indent=2, default=str))
        print("PIPELINE PREFLIGHT VERIFIED" if self.ready else "PIPELINE PREFLIGHT BLOCKED")


class _ReadOnlyDatabase:
    """Adapter allowing the existing universe service to use a read-only connection."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self.conn = conn


def _config_path() -> Path:
    configured = PROJECT_ROOT / "config" / "config.yaml"
    return configured if configured.is_file() else PROJECT_ROOT / "config" / "config.example.yaml"


def _database_path(config: dict[str, Any], explicit_path: str | None) -> Path:
    value = explicit_path or str(config.get("database", {}).get("path", ""))
    if not value:
        raise ValueError("DATABASE_RECOVERY_REQUIRED: database.path is missing")
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _database_preflight(db_path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    details: dict[str, Any] = {"database_path": str(db_path), "database_open": False}
    blockers: list[str] = []
    conn: duckdb.DuckDBPyConnection | None = None
    try:
        # Read-only prevents preflight from checkpointing or otherwise mutating the database/WAL.
        conn = duckdb.connect(database=str(db_path), read_only=True)
        details["database_open"] = True
        details["database_size"] = conn.execute("PRAGMA database_size").fetchall()
        tables = {str(row[0]) for row in conn.execute("SHOW TABLES").fetchall()}
        details["required_tables"] = sorted(REQUIRED_RESEARCH_TABLES & tables)
        missing_tables = sorted(REQUIRED_RESEARCH_TABLES - tables)
        if missing_tables:
            blockers.append("DATABASE_REQUIRED_TABLES_MISSING:" + ",".join(missing_tables))
        integrity = DatabaseIntegrityValidator(conn).run_all_checks()
        details["integrity"] = {
            item.check_name: {"passed": item.passed, "violations": item.violation_count, "details": item.details}
            for item in integrity
        }
        if any(not item.passed for item in integrity):
            blockers.append("DATABASE_INTEGRITY_FAILED")
    except Exception as exc:
        details["database_error"] = str(exc)
        blockers.append("DATABASE_RECOVERY_REQUIRED")
    finally:
        if conn is not None:
            conn.close()
    return details, tuple(blockers)


def _pit_preflight(
    db_path: Path,
    snapshot_id: str | None,
    *,
    benchmark_symbol: str,
    requested_start: date,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    details: dict[str, Any] = {"selected_universe": snapshot_id}
    blockers: list[str] = []
    if not snapshot_id:
        return details, ("PIT_UNIVERSE_NOT_READY", "UNIVERSE_SNAPSHOT_REQUIRED")

    conn: duckdb.DuckDBPyConnection | None = None
    try:
        conn = duckdb.connect(database=str(db_path), read_only=True)
        snapshot = conn.execute(
            "SELECT name, survivorship_bias FROM universe_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        if snapshot is None:
            return details, ("PIT_UNIVERSE_NOT_READY", "SNAPSHOT_NOT_FOUND")
        universe_name, survivorship_bias = str(snapshot[0]), bool(snapshot[1])
        details["universe_name"] = universe_name
        details["survivorship_bias"] = survivorship_bias
        if survivorship_bias:
            blockers.extend(("PIT_UNIVERSE_NOT_READY", "SURVIVORSHIP_BIASED_UNIVERSE"))

        pit_count, pit_start = conn.execute(
            "SELECT COUNT(*), MIN(effective_from) FROM index_constituents_pit WHERE universe_name = ?",
            [universe_name],
        ).fetchone()
        details["pit_membership_rows"] = int(pit_count or 0)
        details["pit_coverage_start"] = pit_start
        if not pit_count:
            blockers.extend(("PIT_UNIVERSE_NOT_READY", "PIT_COVERAGE_UNAVAILABLE"))
        elif pit_start is None or pit_start > requested_start:
            blockers.append("PIT_REQUESTED_HISTORY_PRECEDES_COVERAGE")

        readiness = UniverseResearchService(_ReadOnlyDatabase(conn)).readiness(
            snapshot_id,
            timeframe="1d",
            benchmark_symbol=benchmark_symbol,
        )
        details["universe_readiness"] = readiness.as_dict()
        details["market_data_coverage"] = {
            "symbols_with_data": readiness.symbols_with_data,
            "symbols_with_lookback": readiness.symbols_with_lookback,
            "member_count": readiness.member_count,
        }
        blockers.extend(readiness.blockers)
    except Exception as exc:
        details["pit_error"] = str(exc)
        blockers.extend(("PIT_UNIVERSE_NOT_READY", "PIT_READINESS_CHECK_FAILED"))
    finally:
        if conn is not None:
            conn.close()
    return details, tuple(dict.fromkeys(blockers))


def _certification_preflight(db_path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Require persisted authoritative data-quality evidence before research."""

    details: dict[str, Any] = {}
    conn: duckdb.DuckDBPyConnection | None = None
    try:
        conn = duckdb.connect(database=str(db_path), read_only=True)
        certified = int(conn.execute(
            "SELECT COUNT(*) FROM data_quality_certifications WHERE UPPER(status) = 'CERTIFIED'",
        ).fetchone()[0])
        details["certified_dataset_count"] = certified
        if certified == 0:
            return details, ("DATA_QUALITY_NOT_CERTIFIED",)
    except Exception as exc:
        details["certification_error"] = str(exc)
        return details, ("DATA_QUALITY_NOT_CERTIFIED",)
    finally:
        if conn is not None:
            conn.close()
    return details, ()


def _baseline_preflight(config: dict[str, Any], *, mode: str) -> tuple[dict[str, Any], tuple[str, ...]]:
    details: dict[str, Any] = {"execution_mode": mode, "starting_capital": CAMPAIGN_STARTING_CAPITAL}
    blockers: list[str] = []
    research = config.get("research")
    if not isinstance(research, dict):
        return details, ("CAMPAIGN_BASELINE_NOT_READY", "RESEARCH_CONFIG_MISSING")
    if research.get("live_trading") is not False:
        blockers.append("LIVE_TRADING_MUST_BE_FALSE")
    if mode != "event-driven":
        blockers.append("CAMPAIGN_EXECUTION_MODE_MUST_BE_EVENT_DRIVEN")
    try:
        risk_engine = build_risk_engine(config)
        details["risk_policy_hash"] = economic_contract_hash(risk_engine.policy.model_dump())
        details["risk_policy"] = risk_engine.policy.model_dump()
    except Exception as exc:
        details["risk_error"] = str(exc)
        blockers.append("CAMPAIGN_RISK_POLICY_NOT_READY")
    costs = research.get("indian_delivery_costs")
    if not isinstance(costs, dict):
        blockers.append("INDIAN_COST_POLICY_NOT_READY")
    try:
        schedule = get_cost_schedule()
        details["cost_policy_identity"] = economic_contract_hash(dict(schedule.__dict__))
        details["cost_schedule_version"] = schedule.version
    except Exception as exc:
        details["cost_error"] = str(exc)
        blockers.append("INDIAN_COST_POLICY_NOT_READY")
    return details, tuple(dict.fromkeys(blockers))


def run_preflight(
    config: dict[str, Any],
    *,
    universe_snapshot: str | None,
    database_path: str | None,
    mode: str = "event-driven",
    benchmark_symbol: str = "NIFTY",
    require_certification: bool = True,
) -> PreflightResult:
    """Run all non-mutating database, PIT, and Campaign 1 baseline checks."""

    research_config = config.get("research")
    details: dict[str, Any] = {
        "live_trading": research_config.get("live_trading") if isinstance(research_config, dict) else None,
    }
    blockers: list[str] = []
    try:
        db_path = _database_path(config, database_path)
    except Exception as exc:
        details["database_error"] = str(exc)
        return PreflightResult(False, details, ("DATABASE_RECOVERY_REQUIRED",))
    db_details, db_blockers = _database_preflight(db_path)
    details.update(db_details)
    blockers.extend(db_blockers)
    try:
        requested_start = date.fromisoformat(str(config["data"]["start_date"]))
    except Exception:
        requested_start = date.min
    if not db_blockers:
        pit_details, pit_blockers = _pit_preflight(
            db_path,
            universe_snapshot,
            benchmark_symbol=benchmark_symbol,
            requested_start=requested_start,
        )
        details.update(pit_details)
        blockers.extend(pit_blockers)
        if require_certification:
            certification_details, certification_blockers = _certification_preflight(db_path)
            details.update(certification_details)
            blockers.extend(certification_blockers)
    else:
        blockers.append("PIT_UNIVERSE_NOT_READY")
    baseline_details, baseline_blockers = _baseline_preflight(config, mode=mode)
    details.update(baseline_details)
    blockers.extend(baseline_blockers)
    return PreflightResult(not blockers, details, tuple(dict.fromkeys(blockers)))


def run_step(command: list[str], description: str) -> int:
    """Run one subprocess stage and return its exit code without bypassing failures."""

    print(f"\n{'=' * 60}\n>> STAGE: {description}\n{'=' * 60}")
    result = subprocess.run(command, env=os.environ.copy())
    if result.returncode != 0:
        print(f"\n[FATAL ERROR] Stage failed: {description}\nPipeline aborted.")
        return result.returncode
    print(f"\n[OK] {description} completed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed Campaign 1 research orchestrator")
    parser.add_argument("--universe-snapshot", default=None, help="Required PIT-safe universe snapshot ID")
    parser.add_argument("--database-path", default=None, help="Optional database path override")
    parser.add_argument("--preflight-only", action="store_true", help="Run readiness checks without mutation or research")
    parser.add_argument("--skip-backfill", action="store_true", help="Skip incremental backfill after preflight; readiness is still required")
    parser.add_argument("--skip-api", action="store_true", help="Complete after research without launching the dashboard API")
    return parser


def _load_config() -> dict[str, Any]:
    return apply_env_overrides(load_yaml(str(_config_path())))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _load_config()
        validate_config(config)
    except Exception as exc:
        print(f"PIPELINE PREFLIGHT BLOCKED\nCONFIGURATION_INVALID: {exc}")
        return 2

    preflight = run_preflight(
        config,
        universe_snapshot=args.universe_snapshot,
        database_path=args.database_path,
        require_certification=args.preflight_only,
    )
    if args.preflight_only:
        preflight.print()
        return 0 if preflight.ready else 2
    if not preflight.ready:
        preflight.print()
        return 2

    python_exe = sys.executable
    snapshot_args = ["--universe-snapshot", str(args.universe_snapshot)]
    if not args.skip_backfill:
        result = run_step(
            [python_exe, "tools/backfill_market_history.py", *snapshot_args],
            "Incremental Market Data Backfill",
        )
        if result:
            return result
        result = run_step(
            [python_exe, "tools/refresh_session_quality.py", *snapshot_args, "--timeframe", "1d"],
            "Data Quality & Session Guardrails",
        )
        if result:
            return result

    post_ingestion = run_preflight(
        config,
        universe_snapshot=args.universe_snapshot,
        database_path=args.database_path,
    )
    if not post_ingestion.ready:
        print("POST-INGESTION READINESS BLOCKED")
        post_ingestion.print()
        return 2

    result = run_step(
        [python_exe, "research.py", "--command", "mass-research", *snapshot_args],
        "Mass Strategy Backtesting & Evaluation",
    )
    if result:
        return result
    if args.skip_api:
        print("PIPELINE COMPLETED SUCCESSFULLY")
        return 0

    print("Starting Dashboard API on http://127.0.0.1:8000 ... (Press Ctrl+C to quit)")
    try:
        return subprocess.run(
            [python_exe, "-m", "uvicorn", "tools.dashboard.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
            env=os.environ.copy(),
        ).returncode
    except KeyboardInterrupt:
        print("\nShutting down API server. Goodbye!")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
