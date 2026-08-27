"""Test suite for DuckDB migration 016 (derived datasets and cross-provider reconciliations)."""

from __future__ import annotations

from pathlib import Path
import duckdb

from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner


def test_fresh_database_applies_migration_016(tmp_path: Path) -> None:
    """T035: Fresh database applies migration 016 and creates tables with expected columns."""
    db_file = str(tmp_path / "fresh_016.duckdb")
    runner = MigrationRunner(db_file)
    applied = runner.run_migrations()
    assert "016_derived_datasets" in applied

    # Verify tables exist
    conn = duckdb.connect(db_file)
    dd_table = conn.execute("SELECT COUNT(*) FROM derived_datasets").fetchone()
    assert dd_table is not None
    cpr_table = conn.execute("SELECT COUNT(*) FROM cross_provider_reconciliations").fetchone()
    assert cpr_table is not None

    # Verify column structures
    cols_dd = [r[0] for r in conn.execute("DESCRIBE derived_datasets").fetchall()]
    assert "derived_dataset_id" in cols_dd
    assert "source_dataset_ids" in cols_dd
    assert "source_content_hashes" in cols_dd
    assert "timeframe" in cols_dd
    assert "adjustment_basis" in cols_dd
    assert "resampler_version" in cols_dd
    assert "calendar_version" in cols_dd
    assert "content_hash" in cols_dd
    assert "dq_status" in cols_dd

    cols_cpr = [r[0] for r in conn.execute("DESCRIBE cross_provider_reconciliations").fetchall()]
    assert "reconciliation_id" in cols_cpr
    assert "primary_provider" in cols_cpr
    assert "secondary_provider" in cols_cpr
    assert "comparison_version" in cols_cpr
    assert "overall_status" in cols_cpr
    conn.close()


def test_incremental_upgrade_016_with_checksum_validation(tmp_path: Path) -> None:
    """T036: Incremental migration runs idempotently, validates checksums, and works with DuckDBManager."""
    db_file = str(tmp_path / "incremental_016.duckdb")

    # 1. Apply initial migrations
    runner = MigrationRunner(db_file)
    runner.run_migrations()

    # 2. Running again should detect all migrations applied and validate checksums
    runner_again = MigrationRunner(db_file)
    applied_second = runner_again.run_migrations()
    assert applied_second == []

    # 3. Verify DuckDBManager methods work cleanly
    db = DuckDBManager(db_file)
    assert db.get_derived_datasets(symbol="RELIANCE", timeframe="5m") == []
    assert db.get_reconciliations(symbol="RELIANCE", timeframe="5m") == []
    db.close()
