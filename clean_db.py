"""Research-state reset utility for the local DuckDB database.

Clears research-run tables (strategy_runs, strategy_metrics, orders/fills/attribution,
equity curves) from the research database. This is a DESTRUCTIVE operation and must
never be run against a database you want to keep.

Usage:
    python clean_db.py --database research.duckdb --permit-target --confirm
    python clean_db.py --database research.duckdb --permit-target --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

_PRODUCTION_PATHS: frozenset[str] = frozenset({
    "market_data.duckdb",
    "production.duckdb",
    "prod.duckdb",
    "live.duckdb",
    "live_data.duckdb",
})

RESEARCH_TABLES = (
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
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Destructively clear research-run tables from the local DuckDB database."
    )
    parser.add_argument(
        "--database",
        required=True,
        help="Explicit path to the disposable/research DuckDB database file.",
    )
    parser.add_argument(
        "--permit-target",
        action="store_true",
        help="Explicitly acknowledge that this exact resolved path is an approved research target.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Explicit operator confirmation required to perform deletions. Without this flag the script exits without changing any data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be deleted without making any changes (overrides --confirm).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requested_path = Path(args.database)
    if requested_path.is_symlink():
        print(f"[FATAL] Refusing symlink database target: {requested_path}", file=sys.stderr)
        return 2
    db_path = requested_path.resolve()

    # Fail hard if pointed at a known production database name
    if db_path.name.lower() in _PRODUCTION_PATHS:
        print(
            f"[FATAL] Refusing to clear production database: {db_path}\n"
            "clean_db.py is only permitted on local research databases.",
            file=sys.stderr,
        )
        return 2

    wal_path = Path(str(db_path) + ".wal")
    if not args.permit_target:
        print("clean_db.py: --permit-target is required for the exact database path.", file=sys.stderr)
        return 2
    if wal_path.exists():
        print(f"[FATAL] Refusing database with active WAL/sidecar: {wal_path}", file=sys.stderr)
        return 2
    if db_path.exists():
        try:
            production_database = Path(__file__).resolve().parent / "market_data.duckdb"
            if production_database.exists() and os.path.samefile(db_path, production_database):
                print(f"[FATAL] Target aliases the production database: {db_path}", file=sys.stderr)
                return 2
        except (FileNotFoundError, OSError):
            pass

    dry_run = args.dry_run
    confirmed = args.confirm

    if not dry_run and not confirmed:
        print(
            "clean_db.py: no action taken.\n"
            "To delete research data, re-run with --confirm.\n"
            "To preview what would be deleted, use --dry-run.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"[DRY-RUN] Would clear research tables from: {db_path}")
        for table in RESEARCH_TABLES:
            print(f"  DELETE FROM {table}")
        print("[DRY-RUN] No changes made.")
        return 0

    print(f"Clearing research-run tables from: {db_path}")
    conn = duckdb.connect(str(db_path), read_only=False)
    try:
        existing = {
            str(row[0]) for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        tables = [table for table in RESEARCH_TABLES if table in existing]
        conn.execute("BEGIN TRANSACTION")
        counts: list[tuple[str, int]] = []
        for table in tables:
            row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            counts.append((table, int(row[0]) if row else 0))
            conn.execute(f'DELETE FROM "{table}"')
        conn.execute("COMMIT")
        for table, deleted in counts:
            print(f"  Cleared {table} ({deleted} rows)")
        cleared = [table for table, _ in counts]
        skipped: list[tuple[str, str]] = []
    finally:
        if 'conn' in locals():
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        conn.close()

    print(f"\nDone: {len(cleared)} tables cleared, {len(skipped)} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
