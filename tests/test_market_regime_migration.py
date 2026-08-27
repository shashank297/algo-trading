"""Test schema migration 017 for market regime snapshots."""

from __future__ import annotations

import duckdb

from storage.migrations.runner import MigrationRunner


def test_clean_migration_017(tmp_path):
    """Test applying all migrations up to 017 on a clean DuckDB database."""
    db_path = str(tmp_path / "clean_017.duckdb")
    conn = duckdb.connect(db_path)
    runner = MigrationRunner(conn)
    runner.run_migrations()

    # Check table existence
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    assert "market_regime_snapshots" in tables

    # Check columns
    columns = [row[0] for row in conn.execute("DESCRIBE market_regime_snapshots").fetchall()]
    expected_cols = [
        "regime_id",
        "market",
        "benchmark",
        "context_type",
        "as_of",
        "decision_time",
        "raw_regime",
        "confidence",
        "trend_score",
        "volatility_score",
        "breadth_score",
        "dispersion_score",
        "liquidity_score",
        "stress_score",
        "input_evidence_json",
        "input_evidence_hash",
        "model_version",
        "policy_version",
        "policy_hash",
        "calendar_version",
        "missing_evidence_json",
        "created_at",
    ]
    for col in expected_cols:
        assert col in columns, f"Missing column: {col}"

    conn.close()


def test_idempotent_migration_017(tmp_path):
    """Test re-running migrations does not fail or duplicate tables."""
    db_path = str(tmp_path / "idempotent_017.duckdb")
    conn = duckdb.connect(db_path)
    runner = MigrationRunner(conn)
    runner.run_migrations()
    # Second run
    runner.run_migrations()

    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    assert "market_regime_snapshots" in tables
    conn.close()
