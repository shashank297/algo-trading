"""Fail-closed end-to-end research pipeline orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from main import apply_env_overrides, load_yaml, validate_config
from risk import build_risk_engine
from storage.integrity import DatabaseIntegrityValidator
from trading_stack.costs import DEFAULT_COST_SCHEDULES, get_cost_schedule
from trading_stack.economic import economic_contract_hash
from trading_stack.datasets import pit_evidence_hash
from trading_stack.universe import UniverseResearchService
from trading_stack.strategies import StrategyRegistry


PROJECT_ROOT = Path(__file__).resolve().parent
CAMPAIGN_STARTING_CAPITAL = 100_000.0
CAMPAIGN_ID = "campaign-1-2d653914799e"
CAMPAIGN_BENCHMARK = "NIFTY200"
CAMPAIGN_ECONOMIC_SEMANTICS_VERSION = "current_mark_to_market_equity_v1/floor_whole_share_v1"
CAMPAIGN_FROZEN_RESEARCH_CONFIG_HASH = "ec50bff064bed0d2b4ff59a97961467d2225a4e3511ac8155f8555b8f66a1357"
CAMPAIGN_FROZEN_RISK_POLICY_HASH = "8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c"
CAMPAIGN_FROZEN_COST_POLICY_IDENTITY = "31dc1cec5ba3e715b1ec5e657cfa5c85199fe1cad87567420ad090bb749d9dd6"
CAMPAIGN_FROZEN_STRATEGY_LIBRARY_HASH = "ef5e1492b81c4e76f4f1e9c6fae4d54de4597b8eabb1af223fc4eee8174742d8"
REQUIRED_RESEARCH_TABLES = frozenset({
    "historical_candles",
    "market_datasets",
    "universe_snapshots",
    "universe_snapshot_members",
    "index_constituents_pit",
})


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _manifest_values(items: Any) -> set[str]:
    if not isinstance(items, list):
        raise ValueError("manifest membership change list is malformed")
    values: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            value = item.get("symbol") or item.get("instrument_id")
        else:
            value = item
        if value is None or not str(value).strip():
            raise ValueError("manifest membership change item is malformed")
        values.add(str(value).strip().upper())
    return values


def _validate_pit_manifest(
    conn: duckdb.DuckDBPyConnection,
    universe_name: str,
    manifest: dict[str, Any],
    *,
    requested_start: date,
) -> None:
    required = {
        "manifest_version", "universe_name", "source_name", "source_certification_id",
        "source_hash", "coverage_start", "coverage_end", "periods", "additions",
        "removals", "former_constituents", "delistings", "pit_evidence_hash",
    }
    if not required.issubset(manifest):
        raise ValueError("manifest is missing required fields")
    if str(manifest["universe_name"]).replace(" ", "").upper() != universe_name.replace(" ", "").upper():
        raise ValueError("manifest universe does not match selected universe")
    certification = conn.execute(
        "SELECT dataset_id, checks_json FROM data_quality_certifications WHERE certification_id = ? AND status = 'CERTIFIED' AND issue_count = 0",
        [manifest["source_certification_id"]],
    ).fetchone()
    if certification is None:
        raise ValueError("manifest source certification is not authoritative")
    try:
        source_checks = json.loads(str(certification[1] or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError("manifest source certification payload is malformed") from exc
    if source_checks.get("dataset_content_hash") != manifest["source_hash"]:
        raise ValueError("manifest source hash does not match source certification")

    coverage_start = _as_date(manifest["coverage_start"])
    coverage_end = _as_date(manifest["coverage_end"])
    if coverage_start is None or coverage_end is None:
        raise ValueError("manifest coverage dates are malformed")
    if coverage_start > coverage_end or coverage_start > requested_start:
        raise ValueError("manifest coverage does not contain the requested start date")
    data_bounds = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM historical_candles WHERE timeframe = '1d'").fetchone()
    data_end = _as_date(data_bounds[1]) if data_bounds else None
    if data_end is not None and coverage_end < data_end:
        raise ValueError("manifest coverage does not contain the available historical period")

    periods = manifest["periods"]
    if not isinstance(periods, list) or not periods:
        raise ValueError("manifest periods are malformed")
    period_dates: list[date] = []
    for period in periods:
        if not isinstance(period, dict) or "effective_from" not in period or "expected_member_count" not in period:
            raise ValueError("manifest period is malformed")
        boundary = _as_date(period["effective_from"])
        if boundary is None or boundary < coverage_start or boundary > coverage_end or boundary in period_dates:
            raise ValueError("manifest period boundaries are invalid")
        period_dates.append(boundary)
        count_row = conn.execute(
            """
            SELECT COUNT(DISTINCT instrument_id)
            FROM index_constituents_pit
            WHERE REPLACE(UPPER(universe_name), ' ', '') = REPLACE(UPPER(?), ' ', '')
              AND effective_from <= ?
              AND (effective_until IS NULL OR effective_until > ?)
            """,
            [universe_name, boundary, boundary],
        ).fetchone()
        if int(count_row[0] if count_row else 0) != int(period["expected_member_count"]):
            raise ValueError(f"manifest member count mismatch at {boundary}")
    if sorted(period_dates) != period_dates:
        raise ValueError("manifest periods are not ordered")
    if period_dates[0] != coverage_start:
        raise ValueError("manifest periods do not start at coverage start")

    pit_rows = conn.execute(
        """
        SELECT symbol, effective_from, effective_until, exclusion_reason
        FROM index_constituents_pit
        WHERE REPLACE(UPPER(universe_name), ' ', '') = REPLACE(UPPER(?), ' ', '')
        ORDER BY symbol, effective_from
        """,
        [universe_name],
    ).fetchall()
    db_boundaries = {
        boundary
        for row in pit_rows
        for boundary in (_as_date(row[1]), _as_date(row[2]))
        if boundary is not None and coverage_start <= boundary <= coverage_end
    }
    manifest_boundaries = set(period_dates)
    if not db_boundaries.issubset(manifest_boundaries):
        raise ValueError("manifest does not reconcile all PIT membership-change boundaries")
    additions: set[str] = set()
    for row in pit_rows:
        effective_from = _as_date(row[1])
        if effective_from is not None and effective_from > coverage_start:
            additions.add(str(row[0]).upper())
    removals = {str(row[0]).upper() for row in pit_rows if _as_date(row[2]) is not None}
    delistings = {
        str(row[0]).upper() for row in pit_rows
        if row[3] and "DELIST" in str(row[3]).upper()
    }
    if _manifest_values(manifest["additions"]) != additions:
        raise ValueError("manifest additions do not reconcile to PIT evidence")
    if _manifest_values(manifest["removals"]) != removals:
        raise ValueError("manifest removals do not reconcile to PIT evidence")
    if _manifest_values(manifest["former_constituents"]) != removals:
        raise ValueError("manifest former constituents do not reconcile to PIT evidence")
    if _manifest_values(manifest["delistings"]) != delistings:
        raise ValueError("manifest delistings do not reconcile to PIT evidence")

    previous_by_symbol: dict[str, date | None] = {}
    for symbol, effective_from, effective_until, _reason in pit_rows:
        start = _as_date(effective_from)
        end = _as_date(effective_until)
        previous_end = previous_by_symbol.get(str(symbol).upper())
        if previous_end is not None and start is not None and start < previous_end:
            raise ValueError("PIT membership intervals overlap")
        previous_by_symbol[str(symbol).upper()] = end


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
    manifest_path: str | None = None,
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

        if not manifest_path:
            blockers.append("PIT_COMPLETENESS_MANIFEST_REQUIRED")
        else:
            manifest = Path(manifest_path)
            if not manifest.is_absolute():
                manifest = PROJECT_ROOT / manifest
            if not manifest.is_file():
                blockers.append("PIT_COMPLETENESS_MANIFEST_REQUIRED")
            else:
                try:
                    manifest_data = load_yaml(str(manifest))
                    if not isinstance(manifest_data, dict):
                        raise ValueError("manifest is malformed")
                    supplied_hash = manifest_data.get("manifest_hash")
                    if supplied_hash:
                        content = {k: v for k, v in manifest_data.items() if k != "manifest_hash"}
                        actual_hash = economic_contract_hash(content)
                        if str(supplied_hash) != actual_hash:
                            raise ValueError("manifest content hash mismatch")
                    actual_pit_hash = pit_evidence_hash(_ReadOnlyDatabase(conn), universe_name)  # type: ignore[arg-type]
                    if str(manifest_data["pit_evidence_hash"]) != actual_pit_hash:
                        raise ValueError("manifest PIT evidence hash mismatch")
                    _validate_pit_manifest(conn, universe_name, manifest_data, requested_start=requested_start)
                    details["pit_manifest"] = manifest_data
                except Exception as exc:
                    details["pit_manifest_error"] = str(exc)
                    blockers.append("PIT_COMPLETENESS_MANIFEST_INVALID")

        pit_rows = conn.execute(
            """
            SELECT pit.symbol, pit.effective_from, pit.effective_until,
                   pit.known_from, knowledge.known_at
            FROM index_constituents_pit pit
            LEFT JOIN index_constituent_knowledge knowledge
              ON knowledge.universe_name = pit.universe_name
             AND knowledge.instrument_id = pit.instrument_id
             AND knowledge.effective_from = pit.effective_from
            WHERE REPLACE(UPPER(pit.universe_name), ' ', '') =
                  REPLACE(UPPER(?), ' ', '')
            ORDER BY pit.symbol, pit.effective_from
            """,
            [universe_name],
        ).fetchall()
        pit_count = len(pit_rows)
        pit_dates = [normalized for row in pit_rows if (normalized := _as_date(row[1])) is not None]
        pit_start = min(pit_dates) if pit_dates else None
        details["pit_membership_rows"] = int(pit_count or 0)
        details["pit_coverage_start"] = pit_start
        if not pit_count:
            blockers.extend(("PIT_UNIVERSE_NOT_READY", "PIT_COVERAGE_UNAVAILABLE"))
        elif pit_start is None or pit_start > requested_start:
            blockers.append("PIT_REQUESTED_HISTORY_PRECEDES_COVERAGE")

        missing_knowledge = sum(1 for row in pit_rows if row[3] is None or row[4] is None)
        details["pit_rows_missing_knowledge_evidence"] = missing_knowledge
        if missing_knowledge:
            blockers.append("PIT_KNOWLEDGE_TIME_INCOMPLETE")

        interval_errors = 0
        symbols = sorted({str(row[0]) for row in pit_rows})
        for symbol in symbols:
            intervals = [row for row in pit_rows if str(row[0]) == symbol]
            previous_end = None
            for _, effective_from, effective_until, *_ in intervals:
                effective_from = _as_date(effective_from)
                effective_until = _as_date(effective_until)
                if effective_from is None:
                    interval_errors += 1
                    continue
                if effective_until is not None and effective_from >= effective_until:
                    interval_errors += 1
                if previous_end is not None and effective_from < previous_end:
                    interval_errors += 1
                previous_end = effective_until
        details["pit_interval_errors"] = interval_errors
        if interval_errors:
            blockers.append("PIT_INTERVAL_INTEGRITY_FAILED")

        if pit_rows:
            data_bounds = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM historical_candles WHERE timeframe = '1d'",
            ).fetchone() or (None, None)
            details["market_data_period"] = {
                "start": data_bounds[0] if data_bounds else None,
                "end": data_bounds[1] if data_bounds else None,
            }
            if data_bounds and _as_date(data_bounds[0]) is not None and (_as_date(data_bounds[0]) or date.max) < requested_start:
                for symbol in symbols:
                    covered = [row for row in pit_rows if str(row[0]) == symbol]
                    if not any(
                        (_as_date(row[1]) or date.max) <= requested_start
                        and (_as_date(row[2]) is None or (_as_date(row[2]) or date.min) > requested_start)
                        for row in covered
                    ):
                        blockers.append("PIT_SYMBOL_COVERAGE_INCOMPLETE")

        readiness = UniverseResearchService(_ReadOnlyDatabase(conn)).readiness(  # type: ignore[arg-type]
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


def _certification_preflight(
    db_path: Path,
    *,
    universe_snapshot: str | None = None,
    benchmark_symbol: str = CAMPAIGN_BENCHMARK,
    timeframe: str = "1d",
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Require persisted authoritative data-quality evidence before research."""

    details: dict[str, Any] = {}
    conn: duckdb.DuckDBPyConnection | None = None
    try:
        conn = duckdb.connect(database=str(db_path), read_only=True)
        certification_row = conn.execute(
            "SELECT COUNT(*) FROM data_quality_certifications WHERE UPPER(status) = 'CERTIFIED'",
        ).fetchone()
        certified = int(certification_row[0]) if certification_row else 0
        details["certified_dataset_count"] = certified
        if certified == 0:
            return details, ("DATA_QUALITY_NOT_CERTIFIED",)
        if universe_snapshot:
            snapshot_row = conn.execute(
                "SELECT name FROM universe_snapshots WHERE snapshot_id = ?",
                [universe_snapshot],
            ).fetchone()
            expected_pit_hash = (
                pit_evidence_hash(_ReadOnlyDatabase(conn), str(snapshot_row[0]))  # type: ignore[arg-type]
                if snapshot_row else None
            )
            frame_row = conn.execute(
                """
                SELECT frame_certification_id, research_frame_hash,
                       contributing_dataset_ids_json, timeframe,
                       dataset_evidence_json, dq_certification_ids_json,
                       pit_evidence_hash
                FROM research_frame_certifications
                WHERE UPPER(status) = 'CERTIFIED'
                  AND timeframe = ?
                  AND symbol = ?
                  AND pit_evidence_hash = ?
                ORDER BY verified_at DESC
                LIMIT 1
                """,
                [timeframe, f"PORTFOLIO:{universe_snapshot}", expected_pit_hash],
            ).fetchone()
            details["selected_universe_frame_certification_count"] = 1 if frame_row else 0
            if frame_row is None:
                return details, ("DATA_QUALITY_NOT_CERTIFIED_FOR_SELECTED_UNIVERSE",)
            frame_id, frame_hash, dataset_ids_json, frame_timeframe, dataset_json, dq_json, frame_pit_hash = frame_row
            try:
                dataset_ids = json.loads(str(dataset_ids_json or "[]"))
                dataset_evidence = json.loads(str(dataset_json or "{}"))
                dq_ids = json.loads(str(dq_json or "[]"))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("selected frame certification lineage is malformed") from exc
            if not frame_id or not frame_hash or frame_timeframe != timeframe or not dataset_ids or not dq_ids:
                raise ValueError("selected frame certification lineage is incomplete")
            if set(dataset_ids) != set(dataset_evidence):
                raise ValueError("selected frame dataset evidence does not match contributing datasets")
            for dataset_id in dataset_ids:
                dataset_row = conn.execute(
                    "SELECT transformation_hash, raw_hash FROM market_datasets WHERE dataset_id = ?",
                    [dataset_id],
                ).fetchone()
                if dataset_row is None or str(dataset_evidence[dataset_id]) not in {str(value) for value in dataset_row if value}:
                    raise ValueError("selected frame dataset content hash mismatch")
            for certification_id in dq_ids:
                dq_row = conn.execute(
                    "SELECT dataset_id, checks_json FROM data_quality_certifications WHERE certification_id = ? AND status = 'CERTIFIED' AND issue_count = 0",
                    [certification_id],
                ).fetchone()
                if dq_row is None or str(dq_row[0]) not in {str(value) for value in dataset_ids}:
                    raise ValueError("selected frame DQ certification lineage is incomplete")
                try:
                    dq_checks = json.loads(str(dq_row[1] or "{}"))
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("selected frame DQ certification payload is malformed") from exc
                expected_hash = dataset_evidence.get(str(dq_row[0]))
                if not expected_hash or dq_checks.get("dataset_content_hash") != expected_hash:
                    raise ValueError("selected frame DQ certification content hash mismatch")
            details["selected_frame_certification_id"] = str(frame_id)
            details["selected_frame_pit_hash"] = str(frame_pit_hash)
    except Exception as exc:
        details["certification_error"] = str(exc)
        return details, ("DATA_QUALITY_NOT_CERTIFIED",)
    finally:
        if conn is not None:
            conn.close()
    return details, ()


def _campaign_strategy_names() -> tuple[str, ...]:
    """Return the registered paper-eligible strategies for Campaign 1."""

    return tuple(
        name for name in StrategyRegistry.available()
        if StrategyRegistry.metadata(name).paper_eligible
    )


def _baseline_preflight(config: dict[str, Any], *, mode: str) -> tuple[dict[str, Any], tuple[str, ...]]:
    details: dict[str, Any] = {
        "execution_mode": mode,
        "starting_capital": CAMPAIGN_STARTING_CAPITAL,
        "campaign_id": CAMPAIGN_ID,
        "benchmark_symbol": CAMPAIGN_BENCHMARK,
        "feature_version": "features-v1",
        "economic_semantics_version": CAMPAIGN_ECONOMIC_SEMANTICS_VERSION,
        "live_trading": config.get("research", {}).get("live_trading") if isinstance(config.get("research"), dict) else None,
        "research_config_hash": economic_contract_hash(config.get("research", {})),
        "strategy_library": [
            {"name": name, "version": StrategyRegistry.metadata(name).version}
            for name in _campaign_strategy_names()
        ],
    }
    details["strategy_library_hash"] = economic_contract_hash(details["strategy_library"])
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
        schedule_identity = [
            {
                "effective_from": item.effective_from.isoformat(),
                "version": item.version,
                "hash": economic_contract_hash(dict(item.__dict__)),
            }
            for item in DEFAULT_COST_SCHEDULES
        ]
        details["cost_policy_identity"] = economic_contract_hash({"schedules": schedule_identity})
        details["cost_schedule_version"] = schedule.version
        details["cost_schedule_sequence"] = schedule_identity
    except Exception as exc:
        details["cost_error"] = str(exc)
        blockers.append("INDIAN_COST_POLICY_NOT_READY")
    frozen_values = {
        "research_config_hash": CAMPAIGN_FROZEN_RESEARCH_CONFIG_HASH,
        "risk_policy_hash": CAMPAIGN_FROZEN_RISK_POLICY_HASH,
        "cost_policy_identity": CAMPAIGN_FROZEN_COST_POLICY_IDENTITY,
        "strategy_library_hash": CAMPAIGN_FROZEN_STRATEGY_LIBRARY_HASH,
        "feature_version": "features-v1",
        "economic_semantics_version": CAMPAIGN_ECONOMIC_SEMANTICS_VERSION,
        "execution_mode": "event-driven",
        "starting_capital": CAMPAIGN_STARTING_CAPITAL,
        "benchmark_symbol": CAMPAIGN_BENCHMARK,
        "live_trading": False,
    }
    for field_name, expected in frozen_values.items():
        if details.get(field_name) != expected:
            blockers.append(f"CAMPAIGN_BASELINE_{field_name.upper()}_MISMATCH")
    return details, tuple(dict.fromkeys(blockers))


def run_preflight(
    config: dict[str, Any],
    *,
    universe_snapshot: str | None,
    database_path: str | None,
    mode: str = "event-driven",
    benchmark_symbol: str = CAMPAIGN_BENCHMARK,
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
            manifest_path=(
                research_config.get("campaign_1", {}).get("pit_completeness_manifest")
                if isinstance(research_config, dict) and isinstance(research_config.get("campaign_1"), dict)
                else None
            ),
        )
        details.update(pit_details)
        blockers.extend(pit_blockers)
        if require_certification:
            certification_details, certification_blockers = _certification_preflight(
                db_path,
                universe_snapshot=universe_snapshot,
                benchmark_symbol=benchmark_symbol,
            )
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
    db_path = _database_path(config, args.database_path)
    snapshot_args = ["--universe-snapshot", str(args.universe_snapshot)]
    database_args = ["--database-path", str(db_path)]
    if not args.skip_backfill:
        result = run_step(
            [python_exe, "tools/backfill_market_history.py", *snapshot_args, "--benchmark", CAMPAIGN_BENCHMARK, *database_args],
            "Incremental Market Data Backfill",
        )
        if result:
            return result
        result = run_step(
            [python_exe, "tools/refresh_session_quality.py", *snapshot_args, "--timeframe", "1d", "--benchmark", CAMPAIGN_BENCHMARK, "--database", str(db_path)],
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
        [
            python_exe, "research.py", "--command", "mass-research",
            *snapshot_args, *database_args, "--benchmark", CAMPAIGN_BENCHMARK,
            "--mode", "event-driven", "--capital", str(CAMPAIGN_STARTING_CAPITAL),
            "--strategies", ",".join(_campaign_strategy_names()),
            "--experiment-family-id", CAMPAIGN_ID,
        ],
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
