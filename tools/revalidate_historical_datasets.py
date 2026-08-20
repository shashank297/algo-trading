"""One-time historical dataset semantics admission revalidation script.

Inspects all historical datasets stored in DuckDB and establishes their source-semantics
admission status (VERIFIED, OVERRIDDEN, AMBIGUOUS, MIXED_BASIS, INSUFFICIENT_EVIDENCE).
Writes a summary report to reports/historical_revalidation_<date>.csv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_platform.contracts import PriceAdjustment
from data_platform.source_semantics import SourceSemanticsAdapter, SourceSemanticsPolicy
from storage.duckdb_manager import DuckDBManager
from utils import get_ist_now


def revalidate_datasets(db_or_path: DuckDBManager | str = "market_data.duckdb") -> pd.DataFrame:
    db = db_or_path if isinstance(db_or_path, DuckDBManager) else DuckDBManager(str(db_or_path))
    policy = SourceSemanticsPolicy(fail_closed=False)

    # Query distinct datasets
    try:
        datasets_df = db.conn.execute(
            """
            SELECT DISTINCT dataset_id, canonical_symbol, exchange, timeframe, adjustment, provider_name
            FROM market_datasets
            ORDER BY canonical_symbol, timeframe
            """
        ).df()
    except Exception as exc:
        print(f"Could not read market_datasets table: {exc}")
        datasets_df = pd.DataFrame()

    results: list[dict[str, object]] = []

    if datasets_df.empty:
        # Fallback: discover datasets from historical_candles
        try:
            datasets_df = db.conn.execute(
                """
                SELECT DISTINCT dataset_id, symbol AS canonical_symbol, exchange, timeframe, adjustment, provider_name
                FROM historical_candles
                WHERE dataset_id IS NOT NULL
                ORDER BY symbol, timeframe
                """
            ).df()
        except Exception as exc:
            print(f"Could not read historical_candles table: {exc}")
            datasets_df = pd.DataFrame()

    print(f"Found {len(datasets_df)} datasets to revalidate.")

    for _, row in datasets_df.iterrows():
        dataset_id = str(row["dataset_id"])
        symbol = str(row["canonical_symbol"])
        timeframe = str(row["timeframe"])
        raw_adj = str(row["adjustment"]).upper()
        provider_name = str(row.get("provider_name", "angel_one"))

        try:
            declared_adj = PriceAdjustment(raw_adj)
        except ValueError:
            declared_adj = PriceAdjustment.UNADJUSTED

        # Load bars
        bars = db.conn.execute(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM historical_candles
            WHERE dataset_id = ?
            ORDER BY timestamp
            """,
            [dataset_id],
        ).df()

        if bars.empty:
            bars = db.conn.execute(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp
                """,
                [symbol, timeframe],
            ).df()

        if bars.empty:
            results.append({
                "dataset_id": dataset_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "bar_count": 0,
                "validation_status": "EMPTY",
                "is_admitted": False,
                "semantics_hash": "",
                "reasons": "No bars found",
            })
            continue

        # Load corporate actions
        try:
            ca_df = db.conn.execute(
                """
                SELECT action_type, ex_date, share_multiplier, symbol, exchange, dividend_amount
                FROM corporate_actions
                WHERE symbol = ?
                """,
                [symbol],
            ).df()
        except Exception:
            ca_df = pd.DataFrame()

        # Run inference
        try:
            semantics = SourceSemanticsAdapter.infer_semantics(
                bars=bars,
                corporate_actions=ca_df,
                provider_name=provider_name,
                declared_adjustment=declared_adj,
                policy=policy,
            )

            SourceSemanticsAdapter.persist_detections(db, dataset_id, semantics)

            reasons_list = [r for rep in semantics.evidence_reports for r in rep.reasons]
            results.append({
                "dataset_id": dataset_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "bar_count": len(bars),
                "validation_status": semantics.validation_status.value,
                "is_admitted": semantics.is_admitted,
                "semantics_hash": semantics.semantics_hash,
                "reasons": "; ".join(reasons_list) if reasons_list else "Declared adjustment verified",
            })
        except Exception as exc:
            results.append({
                "dataset_id": dataset_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "bar_count": len(bars),
                "validation_status": "AMBIGUOUS",
                "is_admitted": False,
                "semantics_hash": "",
                "reasons": f"Inference exception: {exc}",
            })

    report_columns = [
        "dataset_id", "symbol", "timeframe", "bar_count",
        "validation_status", "is_admitted", "semantics_hash", "reasons"
    ]
    report_df = pd.DataFrame(results, columns=report_columns if not results else None)

    # Write report
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_date = get_ist_now().strftime("%Y_%m_%d")
    report_path = reports_dir / f"historical_revalidation_{report_date}.csv"
    report_df.to_csv(report_path, index=False)
    print(f"Historical revalidation report written to {report_path}")

    return report_df


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="market_data.duckdb", help="Path to DuckDB database")
    args = parser.parse_args()

    revalidate_datasets(args.db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
