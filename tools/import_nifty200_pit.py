"""Dry-run and guarded import of certified NIFTY-200 PIT intervals."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from storage import DuckDBManager
from tools.nifty200_pit.manifest import read_table
from tools.nifty200_pit.instrument_resolver import validate_alias_intervals
from tools.nifty200_pit.source_catalogue import sha256_file


_MISSING_VALUES = {"", "none", "nan", "nat", "null"}


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip()
    if text.lower() in _MISSING_VALUES:
        raise ValueError(f"Canonical interval artifact has missing {field_name}")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="constituent_intervals.parquet")
    parser.add_argument("--manifest", required=True, help="evidence_manifest.json")
    parser.add_argument(
        "--aliases",
        help="Certified instrument_aliases.parquet; defaults to the interval artifact directory sibling.",
    )
    parser.add_argument("--database", default=str(PROJECT_ROOT / "market_data.duckdb"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--validate-structure-only",
        action="store_true",
        help="Validate the canonical artifact schema/hash without requiring governance approval or writing to a database.",
    )
    return parser


def verify_manifest(
    manifest_path: str | Path,
    input_path: str | Path,
    *,
    structure_only: bool = False,
) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = manifest.get("artifact_hashes", {}).get(Path(input_path).name)
    if not expected or sha256_file(Path(input_path)) != expected:
        raise ValueError("Canonical interval artifact hash mismatch; import refused")
    if not structure_only:
        if manifest.get("validation_status") != "PASS":
            raise ValueError("Manifest validation is not PASS; import refused")
        if manifest.get("campaign_readiness") != "PASS":
            raise ValueError("Manifest campaign readiness is not PASS; import refused")
        if not manifest.get("approved_for_import", False):
            raise ValueError("Manifest lacks explicit approval_for_import; import refused")
        if int(manifest.get("unresolved_conflict_count", 1)) != 0:
            raise ValueError("Manifest contains unresolved conflicts; import refused")
    return manifest


def load_aliases(alias_path: str | Path) -> list[dict[str, Any]]:
    """Load and validate only certified, evidence-backed alias rows."""
    path = Path(alias_path)
    if not path.is_file():
        return []
    frame = read_table(path)
    required = {
        "alias_id", "instrument_id", "alias_symbol", "exchange", "valid_from", "valid_until",
        "source_url", "source_sha256", "confidence", "resolution_status",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Alias artifact is missing columns: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        if str(row.get("confidence", "")).upper() != "CERTIFIED" or str(row.get("resolution_status", "")).upper() != "ACCEPTED":
            continue
        for field in ("alias_id", "instrument_id", "alias_symbol", "exchange", "source_url", "source_sha256"):
            _required_text(row.get(field), f"alias.{field}")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(row["source_sha256"])):
            raise ValueError(f"Alias {row['alias_id']} has an invalid source SHA-256")
        _optional_date(row.get("valid_from"))
        _optional_date(row.get("valid_until"))
        rows.append(row)
    validation_errors = validate_alias_intervals(rows)
    if validation_errors:
        raise ValueError("Alias artifact has invalid certified intervals: " + "; ".join(validation_errors))
    if len({str(row["alias_id"]) for row in rows}) != len(rows):
        raise ValueError("Alias artifact contains duplicate alias_id values")
    return rows


def insert_aliases(connection: Any, aliases: list[dict[str, Any]]) -> int:
    """Insert certified alias history within the caller's transaction."""
    if not aliases:
        return 0
    connection.execute(
        """CREATE TABLE IF NOT EXISTS instrument_alias_history (
            alias_id VARCHAR NOT NULL PRIMARY KEY,
            instrument_id VARCHAR NOT NULL,
            alias_symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL DEFAULT 'NSE',
            valid_from DATE,
            valid_until DATE,
            source_url VARCHAR,
            source_sha256 VARCHAR,
            confidence VARCHAR NOT NULL DEFAULT 'MANUAL_REVIEW',
            resolution_status VARCHAR NOT NULL DEFAULT 'UNRESOLVED',
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    for row in aliases:
        connection.execute(
            """INSERT OR REPLACE INTO instrument_alias_history (
                alias_id, instrument_id, alias_symbol, exchange, valid_from, valid_until,
                source_url, source_sha256, confidence, resolution_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(row["alias_id"]), str(row["instrument_id"]).upper(), str(row["alias_symbol"]).upper(),
                str(row.get("exchange") or "NSE").upper(), _optional_date(row.get("valid_from")),
                _optional_date(row.get("valid_until")), str(row["source_url"]), str(row["source_sha256"]).lower(),
                "CERTIFIED", "ACCEPTED",
            ],
        )
    return len(aliases)


def _optional_date(value: object) -> date | None:
    if value is None or str(value) in {"", "NaT", "nan", "None"}:
        return None
    return date.fromisoformat(str(value)[:10])


def _required_date(value: object, field_name: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError(f"Canonical interval artifact is missing required {field_name}")
    return parsed


def load_constituents(input_path: str | Path) -> list[PointInTimeConstituent]:
    frame = read_table(input_path)
    required = {
        "interval_id", "index_id", "instrument_id", "symbol_at_entry", "effective_from",
        "effective_until", "known_from", "known_at", "entry_event_hash", "confidence", "synthetic",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Canonical interval artifact is missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("Canonical interval artifact contains no rows")

    interval_ids: set[str] = set()
    interval_rows: list[tuple[str, str, str, date, date | None]] = []
    constituents = []
    for row in frame.to_dict(orient="records"):
        interval_id = _required_text(row.get("interval_id"), "interval_id")
        if interval_id in interval_ids:
            raise ValueError(f"Canonical interval artifact contains duplicate interval_id: {interval_id}")
        interval_ids.add(interval_id)
        index_id = _required_text(row.get("index_id"), "index_id")
        instrument_id = _required_text(row.get("instrument_id"), "instrument_id")
        symbol = _required_text(row.get("symbol_at_entry"), "symbol_at_entry")
        _required_text(row.get("entry_event_hash"), "entry_event_hash")
        if str(row.get("confidence")) != "CERTIFIED" or bool(row.get("synthetic", False)):
            raise ValueError("Only certified, non-synthetic intervals may be imported")
        effective_from = _required_date(row["effective_from"], "effective_from")
        effective_until = _optional_date(row.get("effective_until"))
        known_from = _required_date(row["known_from"], "known_from")
        known_at = datetime.fromisoformat(str(row["known_at"]))
        if effective_until is not None and effective_until <= effective_from:
            raise ValueError(f"Interval {interval_id} has inverted or zero-length validity")
        if known_from > effective_from or known_at.date() > effective_from:
            raise ValueError(f"Interval {interval_id} violates temporal causality")
        interval_rows.append((index_id, instrument_id, interval_id, effective_from, effective_until))
        constituents.append(PointInTimeConstituent(
            universe_name=index_id, symbol=symbol, instrument_id=instrument_id,
            token=str(row.get("token") or ""), exchange="NSE", effective_from=effective_from,
            effective_until=effective_until, known_from=known_from,
            known_at=known_at, inclusion_reason=str(row.get("reason") or "CERTIFIED_PIT"),
            is_authoritative=True,
        ))
    grouped: dict[tuple[str, str], list[tuple[str, str, str, date, date | None]]] = {}
    for interval in interval_rows:
        grouped.setdefault((interval[0], interval[1]), []).append(interval)
    for key, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item[3])
        for previous, current in zip(ordered, ordered[1:]):
            if previous[4] is None or current[3] < previous[4]:
                raise ValueError(f"Canonical interval artifact contains overlapping intervals for {key[1]}")
    return constituents


def import_intervals(
    input_path: str | Path,
    manifest_path: str | Path,
    *,
    database: str,
    dry_run: bool,
    structure_only: bool = False,
    aliases_path: str | Path | None = None,
) -> int:
    manifest = verify_manifest(manifest_path, input_path, structure_only=structure_only)
    constituents = load_constituents(input_path)
    alias_path = Path(aliases_path) if aliases_path else Path(input_path).with_name("instrument_aliases.parquet")
    if alias_path.is_file():
        alias_hash = manifest.get("artifact_hashes", {}).get(alias_path.name)
        if not alias_hash or sha256_file(alias_path) != alias_hash:
            raise ValueError("Instrument alias artifact hash mismatch; import refused")
    aliases = load_aliases(alias_path)
    if dry_run or structure_only:
        return len(constituents)
    db = DuckDBManager(database)
    try:
        db.conn.execute("BEGIN TRANSACTION")
        count = PointInTimeUniverseManager.bulk_insert_constituents(db, constituents, require_authoritative_identity=True)
        insert_aliases(db.conn, aliases)
        db.conn.execute("COMMIT")
        return count
    except Exception:
        try:
            db.conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    count = import_intervals(
        args.input,
        args.manifest,
        database=args.database,
        dry_run=args.dry_run,
        structure_only=args.validate_structure_only,
        aliases_path=args.aliases,
    )
    if args.validate_structure_only:
        suffix = " (structure-only; no database write)"
    elif args.dry_run:
        suffix = " (dry-run; no database write)"
    else:
        suffix = ""
    print(f"Validated {count} NIFTY-200 PIT intervals{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
