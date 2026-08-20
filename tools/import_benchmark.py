"""Import a verified benchmark CSV with provenance and explicit alias semantics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_platform.contracts import PriceAdjustment
from data_platform.service import ingest_raw_provider_dataset
from main import apply_env_overrides, load_yaml
from storage import DuckDBManager
from trading_stack.universe import UniverseResearchService
from utils import LoggerSetup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--canonical-symbol", default="NIFTY")
    parser.add_argument("--provider-symbol", required=True)
    parser.add_argument("--provider-name", required=True)
    parser.add_argument("--relationship", choices=["EXACT", "PROXY"], default="EXACT")
    parser.add_argument("--source", required=True)
    parser.add_argument("--timeframe", default="1d", choices=["1d", "1m"])
    parser.add_argument("--adjustment", choices=[value.value for value in PriceAdjustment], default="UNADJUSTED")
    parser.add_argument("--approve-for-research", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = apply_env_overrides(load_yaml(str(PROJECT_ROOT / "config" / "config.yaml")))
    config["logging"]["path"] = str(PROJECT_ROOT / config["logging"]["path"])
    logger = LoggerSetup.setup(config, component="data-import", command="benchmark-import")
    frame = pd.read_csv(args.csv).rename(columns={"date": "timestamp", "Date": "timestamp"})
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Benchmark CSV is missing columns: {sorted(missing)}")
    db = DuckDBManager(str(PROJECT_ROOT / config["database"]["path"]))
    try:
        res = ingest_raw_provider_dataset(
            bars=frame[list(required)],
            symbol=args.provider_symbol,
            exchange="NSE",
            timeframe=args.timeframe,
            provider_name=args.provider_name,
            provider_symbol=args.provider_symbol,
            declared_adjustment=PriceAdjustment(args.adjustment),
            timezone_name="Asia/Kolkata",
            db=db,
            target_adjustment=PriceAdjustment(args.adjustment),
        )

        if res.raw_status == "QUARANTINED" or res.bars is None:
            raise ValueError(f"Benchmark dataset quarantined: {res.quarantine_reasons}")

        UniverseResearchService(db).register_benchmark(
            args.canonical_symbol,
            args.provider_symbol,
            relationship=args.relationship,
            source=args.source,
            approved_for_research=args.approve_for_research,
            notes=f"Imported dataset {res.canonical_dataset_id}; adjustment={args.adjustment}",
        )
        logger.info(
            "benchmark_imported dataset_id={} rows={} relationship={} approved={}",
            res.canonical_dataset_id,
            len(res.bars),
            args.relationship,
            args.approve_for_research,
        )
        print(f"Imported {len(res.bars)} rows as dataset {res.canonical_dataset_id}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
