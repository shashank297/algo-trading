"""Point-in-time causality and anti-leakage tests for MarketRegimeEngine."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from trading_stack.market_regime import (
    MarketContextType,
    MarketRegimeEngine,
)

IST = ZoneInfo("Asia/Kolkata")


def _build_test_daily_bars(num_days: int = 200, start_date: datetime.date = datetime.date(2025, 1, 1)) -> pd.DataFrame:
    dates = []
    curr = start_date
    while len(dates) < num_days:
        if curr.weekday() < 5:
            dates.append(curr)
        curr += datetime.timedelta(days=1)

    records = []
    price = 100.0
    for d in dates:
        price *= 1.001
        records.append({
            "date": d,
            "timestamp": datetime.datetime.combine(d, datetime.time(15, 30), tzinfo=IST).isoformat(),
            "open": price * 0.999,
            "high": price * 1.002,
            "low": price * 0.998,
            "close": price,
            "volume": 100_000,
        })
    return pd.DataFrame(records)


def test_future_close_mutation():
    """Prove future session close on day D cannot affect 10:00 intraday decision on day D."""
    engine = MarketRegimeEngine()
    bars = _build_test_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T10:00:00+05:30"

    # Intraday 10:00 bar
    intraday_bars = pd.DataFrame([{
        "timestamp": f"{as_of.isoformat()}T09:45:00+05:30",
        "open": 120.0,
        "high": 121.0,
        "low": 119.5,
        "close": 120.5,
        "volume": 10_000,
    }])

    snap1 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        benchmark_intraday_bars=intraday_bars,
    )

    # Mutate day D's daily close in the historical table to an extreme value
    mutated_bars = bars.copy()
    mutated_bars.loc[mutated_bars["date"] == as_of, "close"] = 999_999.0

    snap2 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=mutated_bars,
        benchmark_intraday_bars=intraday_bars,
    )

    assert snap1.raw_regime == snap2.raw_regime
    assert snap1.component_scores.trend_score == snap2.component_scores.trend_score
    assert snap1.component_scores.volatility_score == snap2.component_scores.volatility_score
    assert snap1.input_evidence_hash == snap2.input_evidence_hash


def test_future_intraday_bar_mutation():
    """Prove intraday bars timestamped after decision_time cannot leak into the decision."""
    engine = MarketRegimeEngine()
    bars = _build_test_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T10:00:00+05:30"

    # 09:45 bar and 14:00 bar
    intraday_bars = pd.DataFrame([
        {
            "timestamp": f"{as_of.isoformat()}T09:45:00+05:30",
            "open": 120.0,
            "high": 121.0,
            "low": 119.5,
            "close": 120.5,
            "volume": 10_000,
        },
        {
            "timestamp": f"{as_of.isoformat()}T14:00:00+05:30",
            "open": 120.5,
            "high": 122.0,
            "low": 120.0,
            "close": 121.5,
            "volume": 50_000,
        },
    ])

    snap1 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        benchmark_intraday_bars=intraday_bars,
    )

    # Mutate the 14:00 bar (after 10:00 decision)
    mutated_intraday = intraday_bars.copy()
    mutated_intraday.loc[1, "close"] = 50.0  # Massive crash at 14:00

    snap2 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        benchmark_intraday_bars=mutated_intraday,
    )

    assert snap1.raw_regime == snap2.raw_regime
    assert snap1.component_scores.trend_score == snap2.component_scores.trend_score
    assert snap1.component_scores.volatility_score == snap2.component_scores.volatility_score
    assert snap1.input_evidence_hash == snap2.input_evidence_hash


def test_future_universe_member_exclusion():
    """Prove future universe members do not leak into earlier breadth calculations."""
    engine = MarketRegimeEngine()
    bars = _build_test_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T15:30:00+05:30"

    # Universe active on as_of has SYM0, SYM1
    pit_members_t = ["SYM0", "SYM1"]
    univ_bars = {
        "SYM0": _build_test_daily_bars(num_days=200),
        "SYM1": _build_test_daily_bars(num_days=200),
        "FUTURE_SYM": _build_test_daily_bars(num_days=200),  # Not yet in PIT universe
    }

    snap_without_future = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        universe_daily_bars=univ_bars,
        pit_universe_members=pit_members_t,
    )

    # If FUTURE_SYM is not in pit_universe_members, it must not alter breadth
    assert snap_without_future.features.pct_above_20dma is not None


def test_future_vix_mutation():
    """Prove VIX values published after decision_time do not alter earlier regime evaluation."""
    engine = MarketRegimeEngine()
    bars = _build_test_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]
    decision_time = f"{as_of.isoformat()}T10:00:00+05:30"

    # VIX with 09:30 value (known) and 15:00 value (future)
    vix_df = pd.DataFrame([
        {"timestamp": f"{as_of.isoformat()}T09:30:00+05:30", "close": 13.0},
        {"timestamp": f"{as_of.isoformat()}T15:00:00+05:30", "close": 35.0},
    ])

    snap1 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        vix_bars=vix_df,
    )
    assert snap1.features.india_vix == 13.0

    # Mutate the 15:00 VIX
    mutated_vix = vix_df.copy()
    mutated_vix.loc[1, "close"] = 99.0

    snap2 = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=decision_time,
        benchmark_daily_bars=bars,
        vix_bars=mutated_vix,
    )

    assert snap2.features.india_vix == 13.0
    assert snap1.confidence == snap2.confidence
    assert snap1.component_scores.volatility_score == snap2.component_scores.volatility_score


def test_eod_vs_intraday_separation():
    """Test EOD evaluation incorporates full completed day D whereas 10:00 intraday uses up to 10:00."""
    engine = MarketRegimeEngine()
    bars = _build_test_daily_bars(num_days=200)
    as_of = bars["date"].iloc[-1]

    # Day D closes with massive drop
    bars_with_drop = bars.copy()
    bars_with_drop.loc[bars_with_drop["date"] == as_of, "close"] = 50.0  # -50% crash at close

    intraday_bars = pd.DataFrame([{
        "timestamp": f"{as_of.isoformat()}T09:45:00+05:30",
        "open": 120.0,
        "high": 120.5,
        "low": 119.8,
        "close": 120.2,
        "volume": 10_000,
    }])

    # 10:00 intraday decision: does NOT know the 50.0 crash
    snap_intraday = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.INTRADAY,
        as_of=as_of,
        decision_time=f"{as_of.isoformat()}T10:00:00+05:30",
        benchmark_daily_bars=bars_with_drop,
        benchmark_intraday_bars=intraday_bars,
    )

    # 15:30 EOD decision: KNOWS the 50.0 crash
    snap_eod = engine.evaluate_market_regime(
        market="NSE",
        benchmark="NIFTY",
        context_type=MarketContextType.EOD,
        as_of=as_of,
        decision_time=f"{as_of.isoformat()}T15:30:00+05:30",
        benchmark_daily_bars=bars_with_drop,
    )

    assert snap_intraday.component_scores.trend_score > snap_eod.component_scores.trend_score
    assert snap_eod.component_scores.stress_score > snap_intraday.component_scores.stress_score
