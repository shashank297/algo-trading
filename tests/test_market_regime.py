"""Unit tests for Market Context and Deterministic Regime Engine."""

from __future__ import annotations

import datetime
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
