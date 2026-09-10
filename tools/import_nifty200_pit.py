"""Dry-run and guarded import of certified NIFTY-200 PIT intervals."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from storage import DuckDBManager
from tools.nifty200_pit.manifest import read_table
from tools.nifty200_pit.source_catalogue import sha256_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="constituent_intervals.parquet")
    parser.add_argument("--manifest", required=True, help="evidence_manifest.json")
    parser.add_argument("--database", default=str(PROJECT_ROOT / "market_data.duckdb"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def verify_manifest(manifest_path: str | Path, input_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("validation_status") != "PASS":
        raise ValueError("Manifest validation is not PASS; import refused")
    if manifest.get("campaign_readiness") != "PASS":
        raise ValueError("Manifest campaign readiness is not PASS; import refused")
    if not manifest.get("approved_for_import", False):
        raise ValueError("Manifest lacks explicit approval_for_import; import refused")
    expected = manifest.get("artifact_hashes", {}).get(Path(input_path).name)
    if not expected or sha256_file(Path(input_path)) != expected:
        raise ValueError("Canonical interval artifact hash mismatch; import refused")
    if int(manifest.get("unresolved_conflict_count", 1)) != 0:
        raise ValueError("Manifest contains unresolved conflicts; import refused")
    return manifest


def _optional_date(value: object) -> date | None:
    if value is None or str(value) in {"", "NaT", "nan", "None"}:
        return None
    return date.fromisoformat(str(value)[:10])


def load_constituents(input_path: str | Path) -> list[PointInTimeConstituent]:
    frame = read_table(input_path)
    required = {"index_id", "instrument_id", "symbol_at_entry", "effective_from", "effective_until", "known_from", "known_at"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Canonical interval artifact is missing columns: {sorted(missing)}")
    constituents = []
    for row in frame.to_dict(orient="records"):
        if str(row.get("confidence")) != "CERTIFIED" or bool(row.get("synthetic", False)):
            raise ValueError("Only certified, non-synthetic intervals may be imported")
        constituents.append(PointInTimeConstituent(
            universe_name=str(row["index_id"]), symbol=str(row["symbol_at_entry"]), instrument_id=str(row["instrument_id"]),
            token=str(row.get("token") or ""), exchange="NSE", effective_from=_optional_date(row["effective_from"]),
            effective_until=_optional_date(row.get("effective_until")), known_from=_optional_date(row["known_from"]),
            known_at=datetime.fromisoformat(str(row["known_at"])), inclusion_reason=str(row.get("reason") or "CERTIFIED_PIT"),
            is_authoritative=True,
        ))
    return constituents


def import_intervals(input_path: str | Path, manifest_path: str | Path, *, database: str, dry_run: bool) -> int:
    verify_manifest(manifest_path, input_path)
    constituents = load_constituents(input_path)
    if dry_run:
        return len(constituents)
    db = DuckDBManager(database)
    try:
        return PointInTimeUniverseManager.bulk_insert_constituents(db, constituents, require_authoritative_identity=True)
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    count = import_intervals(args.input, args.manifest, database=args.database, dry_run=args.dry_run)
    print(f"Validated {count} NIFTY-200 PIT intervals" + (" (dry-run; no database write)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
