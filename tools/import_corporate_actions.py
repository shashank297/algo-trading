"""CLI tool to import and sync corporate action records into DuckDB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import apply_env_overrides, load_yaml, validate_config
from storage import DuckDBManager
from utils import LoggerSetup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-file",
        default="data/corporate_actions_nifty200.json",
        help="Path to JSON seed file with historical corporate actions.",
    )
    return parser


def normalize_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Validate and compute canonical share_multiplier for corporate action record."""
    action_type = str(rec.get("action_type", "")).upper()
    if action_type == "BONUS":

        new_sh = rec.get("bonus_new_shares")
        exist_sh = rec.get("bonus_existing_shares")
        if new_sh is not None and exist_sh is not None and float(exist_sh) > 0:
            rec["share_multiplier"] = float(exist_sh + new_sh) / float(exist_sh)
        elif "share_multiplier" not in rec:
            raise ValueError(f"Missing bonus terms (bonus_new_shares, bonus_existing_shares, or share_multiplier) in corporate action record: {rec}")



    elif action_type == "SPLIT":
        old_fv = rec.get("old_face_value")
        new_fv = rec.get("new_face_value")
        if old_fv is not None and new_fv is not None and float(new_fv) > 0:
            rec["share_multiplier"] = float(old_fv) / float(new_fv)

    elif action_type == "CONSOLIDATION":
        old_fv = rec.get("old_face_value")
        new_fv = rec.get("new_face_value")
        if old_fv is not None and new_fv is not None and float(new_fv) > 0:
            rec["share_multiplier"] = float(old_fv) / float(new_fv)

    elif action_type == "DIVIDEND":
        rec["share_multiplier"] = 1.0

    if "share_multiplier" not in rec or rec["share_multiplier"] <= 0:
        raise ValueError(f"Invalid non-positive share_multiplier for record: {rec}")

    return rec


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seed_path = Path(args.seed_file)
    if not seed_path.is_absolute():
        seed_path = (PROJECT_ROOT / seed_path).resolve()

    if not seed_path.exists():
        raise FileNotFoundError(f"Corporate actions seed file not found: {seed_path}")

    config = apply_env_overrides(load_yaml(str(PROJECT_ROOT / "config" / "config.yaml")))
    validate_config(config)
    config["database"]["path"] = str((PROJECT_ROOT / config["database"]["path"]).resolve())
    logger = LoggerSetup.setup(config, component="ingestion", command="import-corporate-actions")

    raw_records: list[dict[str, Any]] = json.loads(seed_path.read_text(encoding="utf-8"))
    records = [normalize_record(r) for r in raw_records]
    logger.info("Loaded and validated {} corporate action records from {}", len(records), seed_path.name)

    db = DuckDBManager(config["database"]["path"])
    try:
        inserted = db.upsert_corporate_actions(records)
        logger.info("Successfully upserted {} corporate actions into DuckDB.", inserted)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
