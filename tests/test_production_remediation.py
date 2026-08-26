"""Regression coverage for durable stream recovery and strict lineage bindings."""

from datetime import datetime, timezone

import pytest

from storage.duckdb_manager import DuckDBManager
from trading_stack.live_aggregator import RealtimeBarAggregator


def test_canonical_gap_lifecycle_survives_reanchor_and_repair(tmp_path):
    db = DuckDBManager(str(tmp_path / "gaps.duckdb"))
    detected = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)
    reanchored = datetime(2026, 1, 5, 4, 5, tzinfo=timezone.utc)
    db.record_stream_gap(
        gap_id="gap-1", exchange="NSE", token="1", symbol="TEST",
        expected_sequence=101, received_sequence=105, gap_size=4, stream_epoch=2, detected_at=detected,
    )
    aggregator = RealtimeBarAggregator()
    aggregator.load_unresolved_gaps(db)
    assert aggregator._untrusted_windows["TEST"][0][0] == "gap-1"
    assert aggregator._untrusted_windows["TEST"][0][2] is None
    db.reanchor_stream_gap(
        exchange="NSE", token="1", stream_epoch=2, reanchored_at=reanchored, evidence={"baseline": 200},
    )
    restarted = RealtimeBarAggregator()
    restarted.load_unresolved_gaps(db)
    assert restarted._untrusted_windows["TEST"][0][0] == "gap-1"
    assert restarted._untrusted_windows["TEST"][0][2] == reanchored
    gap_id, _, _, _ = db.repair_stream_gap(
        gap_id="gap-1", repaired_at=reanchored, evidence={"backfill": "verified"},
    )
    restarted.repair_gap(gap_id)
    assert "TEST" not in restarted._untrusted_windows
    assert db.load_unrepaired_stream_gaps() == []


def test_gap_reload_failure_is_not_silenced(tmp_path, monkeypatch):
    db = DuckDBManager(str(tmp_path / "gap-failure.duckdb"))
    aggregator = RealtimeBarAggregator()
    monkeypatch.setattr(db, "load_unrepaired_stream_gaps", lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    with pytest.raises(RuntimeError, match="database unavailable"):
        aggregator.load_unresolved_gaps(db)


def test_reanchor_closes_only_the_matching_gap_id():
    detected = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)
    aggregator = RealtimeBarAggregator()
    aggregator.mark_untrusted("gap-a", "TEST", detected)
    aggregator.mark_untrusted("gap-b", "TEST", detected)
    aggregator.close_degraded_interval("gap-b", detected)
    windows = {gap_id: end for gap_id, _, end in aggregator._untrusted_windows["TEST"]}
    assert windows["gap-a"] is None
    assert windows["gap-b"] == detected


def test_certification_requires_direct_run_frame_binding(tmp_path):
    from trading_stack.certification import RunCertificationService

    db = DuckDBManager(str(tmp_path / "lineage.duckdb"))
    db.conn.execute(
        """INSERT INTO strategy_runs (
               run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json,
               data_hash, status, started_at, notes
           ) VALUES ('run-1', 'trend_following', 'INDIA_EQUITY', 'TEST', '1d', 'event-driven',
                     '{}', 'hash', 'COMPLETED', CURRENT_TIMESTAMP, '{\"frame_certification_id\":\"legacy\"}')"""
    )
    bundle_id = RunCertificationService(db).certify("run-1")
    statuses = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]).fetchall())
    assert statuses["DATA_LINEAGE"] == "FAIL"
