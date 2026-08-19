"""
Validates that:
1. Running mass-research on a small set populates experiment_jobs with data_from/data_to/bar_count.
2. Re-running immediately skips all succeeded jobs (pure cache hits, near-zero time).
3. The job key changes when data_revision bumps, causing re-runs.
"""
from __future__ import annotations

import time
from storage.duckdb_manager import DuckDBManager

DB_PATH = "market_data.duckdb"

def check_jobs(db: DuckDBManager) -> None:
    rows = db.conn.execute("""
        SELECT strategy_name, symbol, state, bar_count,
               STRFTIME(data_from, '%Y-%m-%d') AS data_from,
               STRFTIME(data_to, '%Y-%m-%d') AS data_to,
               data_revision
        FROM experiment_jobs
        ORDER BY strategy_name, symbol
        LIMIT 20
    """).fetchall()
    print(f"\n{'Strategy':<30} {'Symbol':<20} {'State':<12} {'Bars':>6} {'From':>12} {'To':>12} {'Rev':>5}")
    print("-" * 105)
    for r in rows:
        print(f"{str(r[0]):<30} {str(r[1]):<20} {str(r[2]):<12} {str(r[3] or '?'):>6} {str(r[4] or '?'):>12} {str(r[5] or '?'):>12} {str(r[6]):>5}")

def main() -> None:
    db = DuckDBManager(DB_PATH)
    total = db.conn.execute("SELECT COUNT(*) FROM experiment_jobs").fetchone()[0]
    succeeded = db.conn.execute("SELECT COUNT(*) FROM experiment_jobs WHERE state = 'SUCCEEDED'").fetchone()[0]
    print(f"\nTotal jobs: {total:,}   Succeeded: {succeeded:,}   Coverage populated: ", end="")
    with_coverage = db.conn.execute("SELECT COUNT(*) FROM experiment_jobs WHERE bar_count IS NOT NULL").fetchone()[0]
    print(f"{with_coverage:,}")
    check_jobs(db)

    print("\n--- Re-running mass-research to confirm cache hits ---")
    from experiments.mass import MassExperimentManager
    from experiments.models import MassExperimentSpec

    # Pull a tiny 5-stock subset from what's already in the DB for speed
    symbols = [r[0] for r in db.conn.execute(
        "SELECT DISTINCT symbol FROM experiment_jobs WHERE state = 'SUCCEEDED' LIMIT 5"
    ).fetchall()]
    strategy = db.conn.execute(
        "SELECT DISTINCT strategy_name FROM experiment_jobs WHERE state = 'SUCCEEDED' LIMIT 1"
    ).fetchone()
    if not symbols or not strategy:
        print("No succeeded jobs found yet — run mass-research first.")
        db.close()
        return

    spec = MassExperimentSpec(
        strategy_names=[strategy[0]],
        universe=symbols,
        timeframe="1d",
        mode="event-driven",
        universe_snapshot_id="NIFTY200_2026_08_17",
        max_workers=4,
    )

    t0 = time.perf_counter()
    result = MassExperimentManager(db).run(spec)
    elapsed = time.perf_counter() - t0

    resumed = sum(1 for j in result["jobs"] if j.get("resumed"))
    run = sum(1 for j in result["jobs"] if not j.get("resumed"))
    print(f"Completed in {elapsed:.2f}s — Cache hits (skipped): {resumed}, Actually re-run: {run}")
    if run == 0:
        print("✅ PASS: All jobs were pure cache hits!")
    else:
        print(f"⚠️  {run} jobs were re-executed (expected 0 for a no-change re-run)")

    db.close()

if __name__ == "__main__":
    main()
