"""Tool to archive historical candles older than X months to Parquet files."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import duckdb
from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Add project root to sys.path so we can import from main
sys.path.insert(0, str(PROJECT_ROOT))
from main import load_yaml


def archive_data(months_old: int, *, delete_after_verify: bool = False) -> None:
    """Export old data, retaining canonical rows unless deletion is explicit."""
    
    config_path = PROJECT_ROOT / "config" / "config.yaml"
    config = load_yaml(str(config_path))
    
    db_path_str = config["database"]["path"]
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path_str).resolve()
        
    archive_dir = PROJECT_ROOT / "data" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    cutoff_date = datetime.now() - relativedelta(months=months_old)
    cutoff_iso = cutoff_date.strftime("%Y-%m-%d %H:%M:%S")
    
    logger.info("📦 Archiving data older than {} months (cutoff: {})", months_old, cutoff_iso)
    logger.info("🗄️ Database: {}", db_path)
    logger.info("📂 Archive directory: {}", archive_dir)
    
    conn = duckdb.connect(str(db_path))
    try:
        # Check how many rows to archive
        count_query = f"SELECT COUNT(*) FROM historical_candles WHERE timestamp < '{cutoff_iso}'"
        count_row = conn.execute(count_query).fetchone()
        if count_row is None:
            raise RuntimeError("DuckDB returned no archive row count.")
        rows_to_archive = count_row[0]
        
        if rows_to_archive == 0:
            logger.info("✅ No data to archive.")
            return
            
        logger.info("⏳ Found {:,} rows to archive. Exporting to Parquet...", rows_to_archive)
        
        # We use a partitioned export so DuckDB creates folders like symbol=NIFTY/timeframe=1m/
        # However, PARTITION_BY creates many small files.
        # Simple approach: a single parquet file or folder per archive run.
        export_path = archive_dir / f"archive_before_{cutoff_date.strftime('%Y%m%d')}.parquet"
        
        # DuckDB requires forward slashes in file paths, even on Windows.
        export_path_str = str(export_path).replace("\\", "/")
        
        copy_query = f"""
            COPY (
                SELECT * FROM historical_candles 
                WHERE timestamp < '{cutoff_iso}'
            ) TO '{export_path_str}' (FORMAT PARQUET, CODEC SNAPPY)
        """
        conn.execute(copy_query)
        logger.info("✅ Export successful. Output: {}", export_path)

        verify_conn = duckdb.connect()
        try:
            archived_row = verify_conn.execute(
                "SELECT COUNT(*) FROM read_parquet(?)",
                [export_path_str],
            ).fetchone()
            if archived_row is None:
                raise RuntimeError("DuckDB returned no Parquet verification row count.")
            archived_rows = archived_row[0]
        finally:
            verify_conn.close()
        if archived_rows != rows_to_archive:
            raise RuntimeError(
                f"Archive verification failed: expected {rows_to_archive} rows, found {archived_rows}."
            )
        logger.info("✅ Archive verified: {:,} rows.", archived_rows)
        if not delete_after_verify:
            logger.info("✅ Canonical DuckDB rows retained. Use --delete-after-verify for an explicit purge.")
            return
        
        logger.info("🗑️ Deleting archived rows from active database...")
        conn.execute(
            "DELETE FROM historical_candles WHERE timestamp < ?", 
            [cutoff_iso]
        )
        
        logger.info("🗑️ Purging old audit logs (download_log and quality_report)...")
        conn.execute(
            "DELETE FROM download_log WHERE run_at < ?",
            [cutoff_iso]
        )
        conn.execute(
            "DELETE FROM quality_report WHERE checked_at < ?",
            [cutoff_iso]
        )
        
        logger.info("🧹 Vacuuming database to reclaim space (this may take a while)...")
        conn.execute("VACUUM")
        
        logger.info("🏁 Archival complete!")
        
    except Exception as exc:
        logger.exception("❌ Archival failed: {}", exc)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Archive historical candles to Parquet.")
    parser.add_argument(
        "--months", 
        type=int, 
        default=6,
        help="Archive data older than this many months (default: 6)."
    )
    parser.add_argument(
        "--delete-after-verify",
        action="store_true",
        help="Delete exported rows only after Parquet row-count verification.",
    )
    args = parser.parse_args()

    archive_data(args.months, delete_after_verify=args.delete_after_verify)
