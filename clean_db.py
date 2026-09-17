"""Safe, atomic cleanup utility for local research-run tables in DuckDB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

TABLES_TO_CLEAR = [
    "strategy_runs",
    "strategy_metrics",
    "strategy_orders",
    "strategy_fills",
    "trade_attribution",
    "trade_round_trips",
    "fill_cost_components",
    "portfolio_positions",
    "portfolio_rebalances",
    "strategy_equity_curve",
    "experiment_jobs",
    "walk_forward_folds",
    "strategy_correlations",
    "promotion_reviews",
]


def clean_database(
    db_path: str | Path,
    *,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, int]:
    target = Path(db_path).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Target database does not exist: {target}")

    if not dry_run and not confirm:
        raise ValueError("Confirmation required for destructive clean_db operation. Use --confirm flag.")

    conn = duckdb.connect(str(target), read_only=dry_run)
    try:
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }

        matched_tables = [tbl for tbl in TABLES_TO_CLEAR if tbl in existing_tables]
        table_counts: dict[str, int] = {}
        for tbl in matched_tables:
            count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
            table_counts[tbl] = int(count)

        if dry_run:
            print(f"[DRY-RUN] Target database: {target}")
            print(f"[DRY-RUN] Found {len(matched_tables)} research tables:")
            for tbl, count in table_counts.items():
                print(f"  - {tbl}: {count} rows would be deleted")
            return table_counts

        # Perform atomic transactional cleanup
        conn.execute("BEGIN TRANSACTION;")
        try:
            for tbl in matched_tables:
                conn.execute(f'DELETE FROM "{tbl}";')
                print(f"Cleared {table_counts[tbl]} rows from {tbl}")
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        return table_counts
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clean research run artifacts and strategy execution tables from DuckDB."
    )
    parser.add_argument(
        "--target-db",
        required=True,
        help="Path to the target DuckDB file (e.g. market_data.duckdb or a research db).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Display tables and row counts that would be deleted without modifying data.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit confirmation to proceed with destructive deletions.",
    )

    args = parser.parse_args(argv)

    try:
        counts = clean_database(args.target_db, dry_run=args.dry_run, confirm=args.confirm)
        total_rows = sum(counts.values())
        action = "Dry run completed for" if args.dry_run else "Successfully cleaned"
        print(f"{action} {total_rows} total rows across {len(counts)} tables.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
