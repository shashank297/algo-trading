"""Regression test for migration atomicity and transactional integrity."""

import duckdb
import pytest
import storage.migrations.runner as runner_mod
from storage.migrations.runner import MigrationRunner


def test_failed_migration_rolls_back_atomically(tmp_path, monkeypatch):
    """If a migration fails midway through multiple statements,
    all DDL changes in that migration must roll back atomically.
    """
    db_path = str(tmp_path / "test_migrations.duckdb")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    # Valid initial migration
    (migrations_dir / "001_initial.sql").write_text(
        "CREATE TABLE base_table (id INT);", encoding="utf-8"
    )

    # Multi-statement migration with runtime execution error on second statement
    (migrations_dir / "002_partial_failure.sql").write_text(
        "CREATE TABLE atomic_table (id INT);\nINSERT INTO atomic_table VALUES (1/0);",
        encoding="utf-8",
    )

    monkeypatch.setattr(runner_mod, "MIGRATIONS_DIR", migrations_dir)
    runner = MigrationRunner(db_path)
    with pytest.raises(RuntimeError, match="Failed to apply migration 002_partial_failure"):
        runner.run_migrations()

    # Connect to verify whether atomic_table was rolled back
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
        assert "base_table" in tables, "001_initial should have succeeded"
        assert "atomic_table" not in tables, (
            "atomic_table should have been rolled back when migration 002 failed!"
        )
    finally:
        con.close()


def test_history_insert_failure_rolls_back_atomically(tmp_path):
    """If recording into schema_migrations fails, the migration's DDL must roll back."""
    db_path = str(tmp_path / "test_history_fail.duckdb")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    (migrations_dir / "001_good.sql").write_text(
        "CREATE TABLE good_table (id INT);", encoding="utf-8"
    )
    (migrations_dir / "002_history_fail.sql").write_text(
        "CREATE TABLE rollback_table (id INT);", encoding="utf-8"
    )

    runner = MigrationRunner(db_path, migrations_dir=migrations_dir)

    class ConnectionProxy:
        def __init__(self, target):
            self._target = target

        def execute(self, sql, *args, **kwargs):
            if "INSERT INTO schema_migrations" in sql and len(args) > 0 and "002_history_fail" in str(args[0]):
                raise duckdb.ConstraintException("Simulated history recording failure")
            return self._target.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._target, name)

    runner.conn = ConnectionProxy(runner.conn)

    with pytest.raises(RuntimeError, match="Failed to apply migration 002_history_fail"):
        runner.run_migrations()


    # Verify rollback_table was rolled back
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
        assert "good_table" in tables
        assert "rollback_table" not in tables, "rollback_table must be rolled back on history insert error"
    finally:
        con.close()

