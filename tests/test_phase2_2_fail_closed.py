from __future__ import annotations

import json
import pandas as pd
import pytest

from data_platform.resampling import ResamplingError, SessionBarResampler
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import MarketCalendar
from trading_stack.domain import infer_market_spec
from trading_stack.pipeline import StrategyPipeline


_CHECKS = ("schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity")


def _seed_certified_source(db: DuckDBManager, dataset_id: str, bars: pd.DataFrame) -> None:
    source_hash = f"hash-{dataset_id}"
    db.upsert_candles(bars, "RELIANCE", "2885", "NSE", "1m", adjustment="SPLIT_ADJUSTED", provider_name="test", dataset_id=dataset_id)
    db.conn.execute(
        """INSERT INTO market_datasets
           (dataset_id, dataset_stage, symbol, canonical_symbol, exchange, timeframe, provider_name,
            provider_token, declared_adjustment, adjustment, lifecycle_status, status, raw_hash,
            transformation_hash, row_count)
           VALUES (?, 'CANONICAL', 'RELIANCE', 'RELIANCE', 'NSE', '1m', 'test', '2885',
                   'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED', 'CANONICAL_PROMOTED', 'VERIFIED', ?, ?, ?)""",
        [dataset_id, source_hash, source_hash, len(bars)],
    )
    cert_id = f"cert-{dataset_id}"
    db.conn.execute(
        """INSERT INTO data_quality_certifications
           (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
           VALUES (?, ?, 'validator-v1', 6, 0, ?, 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        [cert_id, dataset_id, json.dumps({"dataset_content_hash": source_hash})],
    )
    for check in _CHECKS:
        db.conn.execute(
            """INSERT INTO quality_report
               (symbol, timeframe, dataset_id, certification_id, check_type, issue_count, details, checked_at)
               VALUES ('RELIANCE', '1m', ?, ?, ?, 0, '{}', CURRENT_TIMESTAMP)""",
            [dataset_id, cert_id, check],
        )


def _bars(count: int) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-02 03:45:00+00:00", periods=count, freq="min")
    return pd.DataFrame({
        "timestamp": timestamps, "open": [100.0] * count, "high": [101.0] * count,
        "low": [99.0] * count, "close": [100.5] * count, "volume": [100] * count,
    })


def test_incomplete_source_retains_failed_attempt_without_authoritative_bars(tmp_path) -> None:
    db = DuckDBManager(str(tmp_path / "phase22.duckdb"))
    _seed_certified_source(db, "source-gap", _bars(4))
    calendar = MarketCalendar(infer_market_spec("RELIANCE", "NSE", "EQUITY"))
    with pytest.raises(ResamplingError, match="Incomplete or misaligned"):
        SessionBarResampler().derive_and_certify(
            source_dataset_id="source-gap", target_timeframe="5m", calendar=calendar, db=db,
            symbol="RELIANCE", exchange="NSE",
        )
    failed = db.conn.execute("SELECT derived_dataset_id FROM derived_datasets WHERE dq_status = 'DQ_FAILED'").fetchone()
    assert failed is not None
    assert db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE dataset_id = ?", [failed[0]]).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM market_datasets WHERE dataset_id = ?", [failed[0]]).fetchone()[0] == 0
    db.close()


def test_certified_derivation_is_admitted_with_bound_dq_evidence(tmp_path) -> None:
    db = DuckDBManager(str(tmp_path / "phase22-success.duckdb"))
    _seed_certified_source(db, "source-ok", _bars(375))
    calendar = MarketCalendar(infer_market_spec("RELIANCE", "NSE", "EQUITY"))
    cert = SessionBarResampler().derive_and_certify(
        source_dataset_id="source-ok", target_timeframe="15m", calendar=calendar, db=db,
        symbol="RELIANCE", exchange="NSE",
    )
    row = db.conn.execute(
        "SELECT status, lifecycle_status, transformation_hash, parent_dataset_id FROM market_datasets WHERE dataset_id = ?",
        [cert.derived_dataset_id],
    ).fetchone()
    assert row == ("VERIFIED", "CANONICAL_PROMOTED", cert.content_hash, "source-ok")
    assert db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE dataset_id = ?", [cert.derived_dataset_id]).fetchone()[0] == 25
    assert db.conn.execute("SELECT COUNT(*) FROM data_quality_certifications WHERE dataset_id = ? AND status = 'CERTIFIED'", [cert.derived_dataset_id]).fetchone()[0] == 1
    pipeline = StrategyPipeline(db, india_calendar=calendar, require_authoritative_certification=True)
    loaded = pipeline.load_candles("RELIANCE", "15m", require_authoritative_certification=True)
    assert len(loaded) == 25
    assert pipeline._last_frame_certification_id is not None
    db.close()
