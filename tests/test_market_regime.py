"""Unit tests for Market Context and Deterministic Regime Engine."""

from __future__ import annotations

import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import pytest

from storage.duckdb_manager import DuckDBManager
from trading_stack.market_regime import (
    MarketContextType,
    MarketRegimeEngine,
    RawMarketRegime,
)

IST = ZoneInfo("Asia/Kolkata")


def _generate_synthetic_daily_bars(
    num_days: int = 250,
    start_price: float = 100.0,
    daily_return_mean: float = 0.0005,
    daily_vol: float = 0.01,
    start_date: datetime.date = datetime.date(2025, 1, 1),
) -> pd.DataFrame:
    """Generate synthetic daily OHLCV bars."""
    dates = []
    curr = start_date
    while len(dates) < num_days:
        if curr.weekday() < 5:  # Monday to Friday
            dates.append(curr)
        curr += datetime.timedelta(days=1)

    np.random.seed(42)
    returns = np.random.normal(daily_return_mean, daily_vol, num_days)
    prices = [start_price]
    for r in returns:
        prices.append(prices[-1] * (1.0 + r))
    prices = prices[1:]

    records = []
    for d, p in zip(dates, prices):
        records.append({
            "date": d,
            "timestamp": datetime.datetime.combine(d, datetime.time(15, 30), tzinfo=IST).isoformat(),
            "open": p * 0.998,
            "high": p * 1.005,
            "low": p * 0.995,
            "close": p,
            "volume": 100_000,
        })
    return pd.DataFrame(records)


def _generate_synthetic_universe_bars(
    pit_members: list[str],
    num_days: int = 250,
    bias: float = 0.0005,
    vol: float = 0.015,
) -> dict[str, pd.DataFrame]:
    """Generate synthetic universe bars for breadth testing."""
    res = {}
    for i, sym in enumerate(pit_members):
        res[sym] = _generate_synthetic_daily_bars(
            num_days=num_days,
            start_price=50.0 + i * 5,
            daily_return_mean=bias + (i % 3 - 1) * 0.0002,
            daily_vol=vol,
        )
    return res


def test_regime_engine_determinism():
    """Test identical evidence and policy deterministically produces identical output."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=200, daily_return_mean=0.001, daily_vol=0.008)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap1 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
    )
    snap2 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
    )

    assert snap1.raw_regime == snap2.raw_regime
    assert snap1.confidence == snap2.confidence
    assert snap1.input_evidence_hash == snap2.input_evidence_hash
    assert snap1.regime_id == snap2.regime_id
    assert snap1.component_scores.trend_score == snap2.component_scores.trend_score
    assert snap1.component_scores.volatility_score == snap2.component_scores.volatility_score


def test_synthetic_bull_low_vol():
    """Test steady upward trend with low volatility classifies as BULL_LOW_VOL."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250, daily_return_mean=0.0015, daily_vol=0.005)
    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = _generate_synthetic_universe_bars(pit_members, num_days=250, bias=0.0015, vol=0.006)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
    )
    assert snap.raw_regime == RawMarketRegime.BULL_LOW_VOL
    assert snap.component_scores.trend_score > 0.25
    assert snap.component_scores.breadth_score > 0.15
    assert snap.component_scores.volatility_score <= 0.15


def test_synthetic_bull_high_vol():
    """Test strong upward trend with elevated volatility classifies as BULL_HIGH_VOL."""
    engine = MarketRegimeEngine()
    # High return but with high volatility
    bars = _generate_synthetic_daily_bars(num_days=250, daily_return_mean=0.002, daily_vol=0.025)
    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = _generate_synthetic_universe_bars(pit_members, num_days=250, bias=0.002, vol=0.025)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    # Inject elevated VIX
    vix_df = pd.DataFrame([{"date": as_of, "close": 26.0}])

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
        vix_bars=vix_df,
    )
    assert snap.raw_regime == RawMarketRegime.BULL_HIGH_VOL
    assert snap.component_scores.trend_score > 0.15
    assert snap.component_scores.volatility_score > 0.15


def test_synthetic_sideways_low_vol():
    """Test flat market with low volatility classifies as SIDEWAYS_LOW_VOL."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250, daily_return_mean=0.0000, daily_vol=0.004)
    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = _generate_synthetic_universe_bars(pit_members, num_days=250, bias=0.0000, vol=0.004)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
    )
    assert snap.raw_regime == RawMarketRegime.SIDEWAYS_LOW_VOL
    assert abs(snap.component_scores.trend_score) < 0.25


def test_synthetic_sideways_high_vol():
    """Test rangebound/flat market with elevated volatility classifies as SIDEWAYS_HIGH_VOL."""
    engine = MarketRegimeEngine()
    dates = []
    curr = datetime.date(2025, 1, 1)
    while len(dates) < 250:
        if curr.weekday() < 5:
            dates.append(curr)
        curr += datetime.timedelta(days=1)

    np.random.seed(123)
    t = np.arange(250)
    prices = 100.0 + 3.0 * np.sin(2 * np.pi * t / 25.0) + np.random.normal(0, 1.5, 250)
    records = []
    for d, p in zip(dates, prices):
        records.append({
            "date": d,
            "timestamp": datetime.datetime.combine(d, datetime.time(15, 30), tzinfo=IST).isoformat(),
            "open": p * 0.995,
            "high": p * 1.015,
            "low": p * 0.985,
            "close": p,
            "volume": 100_000,
        })
    bars = pd.DataFrame(records)
    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = {sym: bars.copy() for sym in pit_members}
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
    )
    assert snap.raw_regime == RawMarketRegime.SIDEWAYS_HIGH_VOL
    assert snap.component_scores.volatility_score > 0.10


def test_synthetic_bear_high_vol():
    """Test sharp downtrend with elevated volatility and stress classifies as BEAR_HIGH_VOL."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250, daily_return_mean=-0.002, daily_vol=0.02)
    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = _generate_synthetic_universe_bars(pit_members, num_days=250, bias=-0.002, vol=0.02)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
    )
    assert snap.raw_regime == RawMarketRegime.BEAR_HIGH_VOL
    assert snap.component_scores.trend_score <= -0.20


def test_synthetic_recovery():
    """Test prior drawdown followed by positive momentum and improving breadth classifies as RECOVERY."""
    engine = MarketRegimeEngine()
    # 200 days downtrend followed by 50 days sharp uptrend
    bars1 = _generate_synthetic_daily_bars(num_days=200, start_price=100.0, daily_return_mean=-0.0015, daily_vol=0.012)
    last_d = bars1["date"].iloc[-1]
    last_p = bars1["close"].iloc[-1]
    bars2 = _generate_synthetic_daily_bars(
        num_days=50,
        start_price=last_p,
        daily_return_mean=0.003,
        daily_vol=0.008,
        start_date=last_d + datetime.timedelta(days=1),
    )
    bars = pd.concat([bars1, bars2], ignore_index=True)

    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = _generate_synthetic_universe_bars(pit_members, num_days=250, bias=0.001, vol=0.01)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
    )
    assert snap.raw_regime == RawMarketRegime.RECOVERY
    assert snap.features.current_drawdown_252 <= -0.10


def test_insufficient_benchmark_data():
    """Test insufficient benchmark history returns INSUFFICIENT_CONTEXT."""
    engine = MarketRegimeEngine()
    # Only 50 days when 120 are required
    bars = _generate_synthetic_daily_bars(num_days=50)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
    )
    assert snap.raw_regime == RawMarketRegime.INSUFFICIENT_CONTEXT
    assert snap.confidence == 0.0
    assert any("Insufficient benchmark history" in msg for msg in snap.missing_evidence)


def test_optional_vix_confidence_penalty():
    """Test missing optional VIX deterministically lowers confidence without guessing."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250)
    pit_members = [f"SYM{i}" for i in range(10)]
    univ_bars = _generate_synthetic_universe_bars(pit_members, num_days=250)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap_no_vix = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
        vix_bars=None,
    )
    snap_with_vix = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
        vix_bars=pd.DataFrame([{"date": as_of, "close": 14.5}]),
    )

    assert snap_no_vix.features.india_vix is None
    assert snap_with_vix.features.india_vix == 14.5
    assert snap_no_vix.confidence < snap_with_vix.confidence


def test_no_strategy_selection_in_market_regime():
    """Regression test proving MarketRegimeEngine output does not perform strategy selection/allocation."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
    )
    snapshot_dict = snap.to_dict()

    # Verify no strategy names, weights, allocations, orders exist in the snapshot
    forbidden_keys = ["strategy", "strategies", "allocation", "weight", "order", "orders", "size", "position"]
    for k in snapshot_dict.keys():
        for forbidden in forbidden_keys:
            assert forbidden not in k.lower(), f"Forbidden key found in regime snapshot: {k}"


def test_duckdb_persistence_roundtrip(tmp_path):
    """Test persisting, retrieving, and listing MarketRegimeSnapshot in DuckDB."""
    db_path = str(tmp_path / "regime_test.duckdb")
    db = DuckDBManager(db_path)

    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snapshot = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
    )

    db.persist_market_regime_snapshot(snapshot)

    fetched = db.get_market_regime_snapshot(snapshot.regime_id)
    assert fetched is not None
    assert fetched["regime_id"] == snapshot.regime_id
    assert fetched["market"] == "NSE"
    assert fetched["raw_regime"] == snapshot.raw_regime.value
    assert fetched["confidence"] == pytest.approx(snapshot.confidence, abs=1e-4)
    assert fetched["input_evidence_hash"] == snapshot.input_evidence_hash

    listed = db.list_market_regime_snapshots(market="NSE", context_type="EOD")
    assert len(listed) == 1
    assert listed[0]["regime_id"] == snapshot.regime_id

    db.close()


# ---------------------------------------------------------------------------
# Phase 2.3 Enforcement Tests
# ---------------------------------------------------------------------------


def test_regime_bars_require_certified_datasets(tmp_path: Path) -> None:
    """Violation 6 — load_regime_bars must reject uncertified (non-CANONICAL_PROMOTED) bars.

    Bars inserted with a non-certified dataset (lifecycle_status != CANONICAL_PROMOTED)
    must not be returned by load_regime_bars; the result must be an empty DataFrame.
    """
    db_path = str(tmp_path / "regime_cert_test.duckdb")
    db = DuckDBManager(db_path)

    # Insert an uncertified dataset (RAW_RECORDED, not CANONICAL_PROMOTED)
    db.conn.execute(
        """
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, exchange, timeframe,
            provider_name, raw_hash, status, lifecycle_status
        ) VALUES (
            'ds_uncert', 'NIFTY200', 'NIFTY200', 'NSE', '1d',
            'TEST', 'raw_h1', 'UNVERIFIED', 'RAW_RECORDED'
        )
        """
    )
    # Insert bars linked to the uncertified dataset
    db.conn.execute(
        """
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, dataset_id)
        VALUES ('NIFTY200', 'T1', 'NSE', '1d', '2025-01-02 15:30:00+05:30', 100, 105, 98, 102, 1000000, 'ds_uncert')
        """
    )

    result = db.load_regime_bars("NIFTY200", "1d", "2025-01-02T15:30:00+05:30", exchange="NSE")

    assert result["bars"].empty, (
        "load_regime_bars must return empty DataFrame when no VERIFIED+CANONICAL_PROMOTED dataset exists"
    )
    assert result["dataset_id"] is None
    assert result["content_hash"] is None

    db.close()


def test_regime_bars_returns_certified_dataset(tmp_path: Path) -> None:
    """Companion to Violation 6 — load_regime_bars returns bars for a certified dataset.

    Bars whose dataset IS VERIFIED + CANONICAL_PROMOTED must be returned.
    """
    db_path = str(tmp_path / "regime_cert_pass.duckdb")
    db = DuckDBManager(db_path)

    db.conn.execute(
        """
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, exchange, timeframe,
            provider_name, raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES (
            'ds_cert', 'NIFTY200', 'NIFTY200', 'NSE', '1d',
            'TEST', 'raw_h1', 'trans_h1', 'VERIFIED', 'CANONICAL_PROMOTED'
        )
        """
    )
    db.conn.execute(
        """
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, dataset_id)
        VALUES ('NIFTY200', 'T1', 'NSE', '1d', '2025-01-02 15:30:00+05:30', 100, 105, 98, 102, 1000000, 'ds_cert')
        """
    )
    db.conn.execute("INSERT INTO market_dataset_availability VALUES ('ds_cert', '2025-01-02 15:30:00+05:30')")
    db.conn.execute("""INSERT INTO historical_candle_availability
        VALUES ('ds_cert', 'NIFTY200', 'NSE', '1d', '2025-01-02 15:30:00+05:30', '2025-01-02 15:30:00+05:30')""")
    db.conn.execute(
        """INSERT INTO data_quality_certifications
           (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
           VALUES ('dq_cert', 'ds_cert', 'test', 6, 0, '{"dataset_content_hash":"trans_h1"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
    )
    for check in ("schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"):
        db.conn.execute(
            """INSERT INTO quality_report (symbol, timeframe, dataset_id, certification_id, check_type, issue_count, details, checked_at)
               VALUES ('NIFTY200', '1d', 'ds_cert', 'dq_cert', ?, 0, '{}', CURRENT_TIMESTAMP)""",
            [check],
        )

    result = db.load_regime_bars("NIFTY200", "1d", "2025-01-02T15:30:00+05:30", exchange="NSE")

    assert not result["bars"].empty, "load_regime_bars must return bars for a certified dataset"
    assert result["dataset_id"] == "ds_cert"
    assert result["content_hash"] == "trans_h1"  # transformation_hash takes priority

    db.close()


def test_evidence_hash_binds_to_cutoff_timestamp() -> None:
    """Violation 7 — input_evidence_hash must differ when cutoff_timestamp differs.

    Two evaluate_market_regime calls with identical bar data but different decision_times
    (meaning different cutoff_timestamps in evidence_metadata) must produce different
    input_evidence_hash values.
    """
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]

    decision_time_a = f"{as_of.isoformat()}T09:15:00+05:30"
    decision_time_b = f"{as_of.isoformat()}T15:30:00+05:30"

    evidence_meta_a = {
        "benchmark_dataset_id": "ds_bench",
        "benchmark_content_hash": "hash_bench",
        "cutoff_timestamp": decision_time_a,
    }
    evidence_meta_b = {
        "benchmark_dataset_id": "ds_bench",
        "benchmark_content_hash": "hash_bench",
        "cutoff_timestamp": decision_time_b,
    }

    snap_a = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time_a,
        benchmark_daily_bars=bars,
        evidence_metadata=evidence_meta_a,
    )
    snap_b = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time_b,
        benchmark_daily_bars=bars,
        evidence_metadata=evidence_meta_b,
    )

    # cutoff_timestamp differs → evidence dict differs → hash must differ
    assert snap_a.input_evidence_hash != snap_b.input_evidence_hash, (
        "input_evidence_hash must change when cutoff_timestamp changes"
    )


def test_universe_not_silently_truncated() -> None:
    """Violation 8 — All PIT universe members must be used in breadth calculation.

    With 60 members (> the old :50 cap), the engine must process all 60 members.
    We verify this by checking that advance_decline_ratio reflects the full universe
    size, not just a sub-50 truncation artifact.
    """
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250, daily_return_mean=0.0005, daily_vol=0.008)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    # 60 members: all with strong positive bias → all should show advances
    n_members = 60
    pit_members = [f"LARGE{i}" for i in range(n_members)]
    univ_bars = _generate_synthetic_universe_bars(
        pit_members, num_days=250, bias=0.002, vol=0.005
    )

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members,
    )

    # All 60 members have positive bias → ad_ratio should be clearly positive
    # If truncated to 50, the ratio would still be positive but the universe_member_count
    # in evidence would be wrong.
    assert snap.input_evidence.universe_member_count == n_members, (
        f"Expected {n_members} universe members in evidence, "
        f"got {snap.input_evidence.universe_member_count}"
    )
    assert snap.component_scores.breadth_score > 0.0, (
        "Breadth score should be positive with a fully bullish 60-member universe"
    )


def test_insufficient_context_snapshot_identity():
    """Verify INSUFFICIENT_CONTEXT snapshots are version-bound and contain full manifest."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=50)  # Insufficient (< 220)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    snap = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
    )

    assert snap.raw_regime == RawMarketRegime.INSUFFICIENT_CONTEXT
    assert snap.policy_version == engine.policy.policy_version
    assert snap.policy_hash == engine.policy.compute_hash()
    assert snap.calendar_version == getattr(engine.calendar, "version", "1.0.0")
    assert "benchmark_daily" in snap.input_evidence.evidence_manifest
    assert snap.input_evidence_hash == snap.input_evidence.compute_hash()
    assert snap.regime_id is not None and len(snap.regime_id) > 0


def test_authoritative_dq_certification_check(tmp_path: Path):
    """Verify load_regime_bars rejects datasets with mismatched or missing DQ certifications."""
    db_path = str(tmp_path / "regime_dq_check.duckdb")
    db = DuckDBManager(db_path)

    # 1. Dataset with no DQ cert
    db.conn.execute(
        """
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, exchange, timeframe,
            provider_name, raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES (
            'ds_no_dq', 'NIFTY200', 'NIFTY200', 'NSE', '1d',
            'TEST', 'raw_h1', 'trans_h1', 'VERIFIED', 'CANONICAL_PROMOTED'
        )
        """
    )
    db.conn.execute("INSERT INTO market_dataset_availability VALUES ('ds_no_dq', '2025-01-02 15:30:00+05:30')")
    db.conn.execute(
        """
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, dataset_id)
        VALUES ('NIFTY200', 'T1', 'NSE', '1d', '2025-01-02 15:30:00+05:30', 100, 105, 98, 102, 1000000, 'ds_no_dq')
        """
    )
    db.conn.execute("""INSERT INTO historical_candle_availability
        VALUES ('ds_no_dq', 'NIFTY200', 'NSE', '1d', '2025-01-02 15:30:00+05:30', '2025-01-02 15:30:00+05:30')""")

    result = db.load_regime_bars("NIFTY200", "1d", "2025-01-02T15:30:00+05:30", exchange="NSE")
    assert result["bars"].empty, "Dataset without DQ certification must be rejected."

    # 2. Dataset with mismatched hash in DQ cert
    db.conn.execute(
        """
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, exchange, timeframe,
            provider_name, raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES (
            'ds_bad_hash', 'INFY', 'INFY', 'NSE', '1d',
            'TEST', 'raw_h1', 'trans_actual', 'VERIFIED', 'CANONICAL_PROMOTED'
        )
        """
    )
    db.conn.execute("INSERT INTO market_dataset_availability VALUES ('ds_bad_hash', '2025-01-02 15:30:00+05:30')")
    db.conn.execute(
        """
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, dataset_id)
        VALUES ('INFY', 'T2', 'NSE', '1d', '2025-01-02 15:30:00+05:30', 100, 105, 98, 102, 1000000, 'ds_bad_hash')
        """
    )
    db.conn.execute("""INSERT INTO historical_candle_availability
        VALUES ('ds_bad_hash', 'INFY', 'NSE', '1d', '2025-01-02 15:30:00+05:30', '2025-01-02 15:30:00+05:30')""")
    db.conn.execute(
        """INSERT INTO data_quality_certifications
           (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
           VALUES ('dq_bad', 'ds_bad_hash', 'test', 6, 0, '{"dataset_content_hash":"trans_DIFFERENT"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
    )

    result_bad = db.load_regime_bars("INFY", "1d", "2025-01-02T15:30:00+05:30", exchange="NSE")
    assert result_bad["bars"].empty, "Dataset with mismatched hash in DQ cert must be rejected."

    db.close()


def test_complete_evidence_manifest_binding():
    """Verify changing universe manifest or benchmark certification changes input_evidence_hash."""
    engine = MarketRegimeEngine()
    bars = _generate_synthetic_daily_bars(num_days=250)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    meta_1 = {
        "benchmark_dataset_id": "ds1",
        "benchmark_content_hash": "hash1",
        "universe_manifest": {"members": [{"symbol": "SBIN", "dataset_id": "ds_sbi", "content_hash": "h_sbi"}]},
    }
    meta_2 = {
        "benchmark_dataset_id": "ds1",
        "benchmark_content_hash": "hash1",
        "universe_manifest": {"members": [{"symbol": "SBIN", "dataset_id": "ds_sbi", "content_hash": "h_sbi_MUTATED"}]},
    }

    snap_1 = engine.evaluate_market_regime(
        market="NSE", benchmark="NIFTY", context_type=MarketContextType.EOD,
        as_of=as_of, decision_time=decision_time, benchmark_daily_bars=bars,
        evidence_metadata=meta_1,
    )
    snap_2 = engine.evaluate_market_regime(
        market="NSE", benchmark="NIFTY", context_type=MarketContextType.EOD,
        as_of=as_of, decision_time=decision_time, benchmark_daily_bars=bars,
        evidence_metadata=meta_2,
    )

    assert snap_1.input_evidence_hash != snap_2.input_evidence_hash
    assert snap_1.regime_id != snap_2.regime_id

