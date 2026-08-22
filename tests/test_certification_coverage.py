from datetime import datetime, timezone

import pytest

from storage.duckdb_manager import DuckDBManager
from trading_stack.certification import RunCertificationService


def seed_run(db, run_id: str, symbol: str = "TEST", notes: str | None = None) -> None:
    db.conn.execute(
        """INSERT INTO strategy_runs
           (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes)
           VALUES (?, 'trend_following', 'INDIA_EQUITY', ?, '1d', 'event-driven', '{}', 'hash', 'COMPLETED', ?, ?)""",
        [run_id, symbol, datetime.now(timezone.utc), notes],
    )


def test_certification_rejects_unknown_and_unbound_runs(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert-fail.duckdb"))
    try:
        service = RunCertificationService(db)
        with pytest.raises(ValueError, match="unknown run_id"):
            service.certify("missing")
        seed_run(db, "run-no-frame")
        bundle_id = service.certify("run-no-frame")
        rows = dict(db.conn.execute(
            "SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]
        ).fetchall())
        assert rows["DATA_LINEAGE"] == "FAIL"
        assert rows["DATA_QUALITY"] == "FAIL"
        assert rows["OOS_WALK_FORWARD"] == "FAIL"
    finally:
        db.close()


def test_portfolio_certification_fails_without_snapshot_evidence(tmp_path):
    db = DuckDBManager(str(tmp_path / "portfolio-cert-fail.duckdb"))
    try:
        seed_run(db, "portfolio-run", "PORTFOLIO:missing-snapshot")
        bundle_id = RunCertificationService(db).certify("portfolio-run")
        rows = dict(db.conn.execute(
            "SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]
        ).fetchall())
        assert rows["DATA_LINEAGE"] == "FAIL"
        assert rows["DATA_QUALITY"] == "FAIL"
        assert rows["PIT_SURVIVORSHIP"] == "FAIL"
    finally:
        db.close()


def test_portfolio_certification_checks_members_dq_and_pit(tmp_path):
    db = DuckDBManager(str(tmp_path / "portfolio-cert-checks.duckdb"))
    try:
        seed_run(db, "portfolio-run", "PORTFOLIO:SNAP", '{"frame_certification_id":"frame"}')
        db.conn.execute(
            "INSERT INTO universe_snapshots VALUES ('SNAP', 'TEST', 'source', '2026-01-01', 'hash', false, CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO universe_snapshot_members VALUES ('SNAP', 'TEST', 'TEST', '1', 'Test', 'IT', 'NSE', '2020-01-01', '2030-01-01', true, true, true)"
        )
        db.conn.execute(
            "INSERT INTO index_constituents_pit VALUES ('TEST', '1', 'TEST', '1', 'NSE', '2020-01-01', '2030-01-01', '2020-01-01', 1.0, 'IN', null, CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds', 'TEST', 'TEST', 'NSE', '1d', 'ANGEL', 'raw', 'VERIFIED', 'CANONICAL_PROMOTED')"
        )
        db.conn.execute(
            "INSERT INTO data_quality_certifications VALUES ('cert', 'ds', 'validator-v1', 6, 0, '{}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at) VALUES ('frame', 'hash', '[\"ds\"]', 'PORTFOLIO:SNAP', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP)"
        )
        bundle_id = RunCertificationService(db).certify("portfolio-run")
        statuses = dict(db.conn.execute(
            "SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]
        ).fetchall())
        assert statuses["DATA_LINEAGE"] == "PASS"
        assert statuses["DATA_QUALITY"] == "PASS"
        assert statuses["PIT_SURVIVORSHIP"] == "PASS"
    finally:
        db.close()


def test_certification_rejects_member_without_canonical_dataset(tmp_path):
    db = DuckDBManager(str(tmp_path / "portfolio-cert-missing-dataset.duckdb"))
    try:
        seed_run(db, "portfolio-run", "PORTFOLIO:SNAP")
        db.conn.execute(
            "INSERT INTO universe_snapshots VALUES ('SNAP', 'TEST', 'source', '2026-01-01', 'hash', false, CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO universe_snapshot_members VALUES ('SNAP', 'TEST', 'TEST', '1', 'Test', 'IT', 'NSE', '2020-01-01', '2030-01-01', true, true, true)"
        )
        bundle_id = RunCertificationService(db).certify("portfolio-run")
        status = db.conn.execute(
            "SELECT status FROM run_certifications WHERE bundle_id = ? AND category = 'DATA_LINEAGE'", [bundle_id]
        ).fetchone()[0]
        assert status == "FAIL"
    finally:
        db.close()


def test_certification_detects_invalid_fill_and_incomplete_quality(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert-invalid-fill.duckdb"))
    try:
        seed_run(db, "run-invalid", "TEST")
        db.conn.execute(
            "INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds', 'TEST', 'TEST', 'NSE', '1d', 'ANGEL', 'raw', 'BROKEN', 'RAW_RECORDED')"
        )
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('TEST', '1', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 1, 2, 1, 2, 1, 'UNADJUSTED', 'ANGEL', 'ds', CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO strategy_orders VALUES ('order', 'run-invalid', 'TEST', 'BUY', 1, 'MARKET', 'DAY', 'FILLED', '2026-01-02', '2026-01-02', 1, 0, 1, 0, 0, '{}', CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO strategy_fills VALUES ('fill', 'order', 'run-invalid', 'TEST', '2026-01-01', 1, 1, 'BUY', 'PAPER', 0, 0, '{}', CURRENT_TIMESTAMP)"
        )
        bundle_id = RunCertificationService(db).certify("run-invalid")
        statuses = dict(db.conn.execute(
            "SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]
        ).fetchall())
        assert statuses["DATA_LINEAGE"] == "FAIL"
        assert statuses["DATA_QUALITY"] == "FAIL"
        assert statuses["CAUSALITY"] == "FAIL"
    finally:
        db.close()


def test_certification_rejects_mismatched_frame_certificate(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert-frame-mismatch.duckdb"))
    try:
        seed_run(db, "run-frame", "TEST", '{"frame_certification_id":"frame"}')
        db.conn.execute(
            "INSERT INTO research_frame_certifications VALUES ('frame', 'different-hash', '[]', 'TEST', '1d', 0, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP)"
        )
        bundle_id = RunCertificationService(db).certify("run-frame")
        status = db.conn.execute(
            "SELECT status FROM run_certifications WHERE bundle_id = ? AND category = 'DATA_LINEAGE'", [bundle_id]
        ).fetchone()[0]
        assert status == "FAIL"
    finally:
        db.close()


def test_certification_covers_dataset_fallback_and_noncertified_frame(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert-fallback.duckdb"))
    try:
        seed_run(db, "run-fallback", "TEST", '{"frame_certification_id":"frame"}')
        db.conn.execute(
            "INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('fallback', 'TEST', 'TEST', 'NSE', '1d', 'ANGEL', 'raw', 'VERIFIED', 'CANONICAL_PROMOTED')"
        )
        db.conn.execute(
            """INSERT INTO research_frame_certifications
               (frame_certification_id, research_frame_hash, contributing_dataset_ids_json,
                symbol, timeframe, row_count, basis, validator_version, status, verified_at)
               VALUES ('frame', 'hash', '[]', 'TEST', '1d', 0, 'SPLIT_ADJUSTED', 'v1', 'PENDING', CURRENT_TIMESTAMP)"""
        )
        bundle_id = RunCertificationService(db).certify("run-fallback")
        statuses = dict(db.conn.execute(
            "SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]
        ).fetchall())
        assert statuses["DATA_LINEAGE"] == "FAIL"
        assert statuses["DATA_QUALITY"] == "FAIL"
    finally:
        db.close()


def test_certification_records_failed_dq_batch(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert-failed-dq.duckdb"))
    try:
        seed_run(db, "run-failed-dq", "TEST")
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('TEST', '1', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 1, 2, 1, 2, 1, 'UNADJUSTED', 'ANGEL', 'bad', CURRENT_TIMESTAMP)"
        )
        db.conn.execute(
            "INSERT INTO data_quality_certifications VALUES ('bad-cert', 'bad', 'validator-v1', 6, 1, '{}', 'FAILED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        bundle_id = RunCertificationService(db).certify("run-failed-dq")
        status = db.conn.execute(
            "SELECT status FROM run_certifications WHERE bundle_id = ? AND category = 'DATA_QUALITY'", [bundle_id]
        ).fetchone()[0]
        assert status == "FAIL"
    finally:
        db.close()
