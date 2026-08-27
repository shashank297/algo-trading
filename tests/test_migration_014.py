"""Test suite for DuckDB migration 014 (research trial registry)."""

from __future__ import annotations

from pathlib import Path
import duckdb

from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner


def test_fresh_database_applies_migration_014(tmp_path: Path) -> None:
    db_file = str(tmp_path / "fresh_014.duckdb")
    runner = MigrationRunner(db_file)
    applied = runner.run_migrations()
    assert "014_research_trials" in applied

    # Verify tables exist
    conn = duckdb.connect(db_file)
    families_table = conn.execute("SELECT COUNT(*) FROM experiment_families").fetchone()
    assert families_table is not None
    trials_table = conn.execute("SELECT COUNT(*) FROM research_trials_log").fetchone()
    assert trials_table is not None
    conn.close()


def test_incremental_upgrade_014_with_checksum_validation(tmp_path: Path) -> None:
    db_file = str(tmp_path / "incremental_014.duckdb")
    
    # 1. Apply initial migrations
    runner = MigrationRunner(db_file)
    runner.run_migrations()

    # 2. Running again should detect all migrations applied and validate checksums
    runner_again = MigrationRunner(db_file)
    applied_second = runner_again.run_migrations()
    assert applied_second == []

    # 3. Verify DuckDBManager interacts cleanly
    db = DuckDBManager(db_file)
    assert db.list_experiment_families() == []
    db.close()
