"""Test suite for DuckDB migration 014 (research trial registry)."""

from __future__ import annotations

from pathlib import Path
import duckdb
import pytest

from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner


class _FakeMigrationConnection:
    def __init__(self, *, fail_migration: bool = False, fail_checkpoint: bool = False, fail_rollback: bool = False):
        self.fail_migration = fail_migration
        self.fail_checkpoint = fail_checkpoint
        self.fail_rollback = fail_rollback
        self.executed: list[str] = []

    def execute(self, statement: str, parameters=None):
        self.executed.append(statement.strip())
        if statement.strip().startswith("SELECT version"):
            return self
        if statement.strip() == "CHECKPOINT;" and self.fail_checkpoint:
            raise RuntimeError("checkpoint unavailable")
        if statement.strip() == "ROLLBACK;" and self.fail_rollback:
            raise RuntimeError("rollback unavailable")
        if self.fail_migration and statement.strip().startswith("CREATE TABLE broken"):
            raise RuntimeError("migration failed")
        return self

    def fetchall(self):
        return []


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


def test_migration_runner_tolerates_checkpoint_failure(tmp_path: Path) -> None:
    migration = tmp_path / "001_checkpoint.sql"
    migration.write_text("CREATE TABLE checkpoint_ok (id INTEGER);", encoding="utf-8")
    conn = _FakeMigrationConnection(fail_checkpoint=True)

    assert MigrationRunner(conn, tmp_path).run_migrations() == ["001_checkpoint"]
    assert "CHECKPOINT;" in conn.executed


def test_migration_runner_surfaces_failure_when_rollback_also_fails(tmp_path: Path) -> None:
    migration = tmp_path / "001_broken.sql"
    migration.write_text("CREATE TABLE broken (id INTEGER);", encoding="utf-8")
    conn = _FakeMigrationConnection(fail_migration=True, fail_rollback=True)

    with pytest.raises(RuntimeError, match="Failed to apply migration 001_broken"):
        MigrationRunner(conn, tmp_path).run_migrations()
    assert "ROLLBACK;" in conn.executed
