"""Tests for Phase 2.2 — SessionBarResampler, DQ certification, and deterministic hash.

These tests are fully deterministic and require no network access or real credentials.
All test data is synthetic 1m bars.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data_platform.resampling import (
    MixedAdjustmentBasisError,
    QuarantinedSourceError,
    ResamplingError,
    SessionBarResampler,
    UnsupportedTimeframeError,
    compute_derived_content_hash,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def _make_nse_calendar():
    """Build a minimal NSE calendar for testing."""
    from trading_stack.calendars import MarketCalendar
    from trading_stack.domain import infer_market_spec

    spec = infer_market_spec("RELIANCE", "NSE", "EQUITY")
    return MarketCalendar(spec)


def _make_1m_bars(
    trading_date: str = "2024-01-02",
    n_minutes: int = 375,
    base_price: float = 100.0,
    session_open_hhmm: str = "09:15",
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    adjustment: str = "SPLIT_ADJUSTED",
) -> pd.DataFrame:
    """Generate synthetic 1m bars for a full NSE session."""
    h, m = map(int, session_open_hhmm.split(":"))
    session_open_ist = datetime.fromisoformat(f"{trading_date}T{h:02d}:{m:02d}:00").replace(tzinfo=IST)
    bars = []
    for i in range(n_minutes):
        ts = (session_open_ist.astimezone(UTC) + pd.Timedelta(minutes=i))
        p = base_price + i * 0.1
        bars.append(
            {
                "timestamp": ts,
                "open": p,
                "high": p + 0.5,
                "low": p - 0.5,
                "close": p + 0.25,
                "volume": 1000 + i,
                "symbol": symbol,
                "exchange": exchange,
                "adjustment": adjustment,
            }
        )
    return pd.DataFrame(bars)


@pytest.fixture()
def calendar():
    return _make_nse_calendar()


@pytest.fixture()
def bars_375() -> pd.DataFrame:
    """Full 375-bar NSE session on 2024-01-02."""
    return _make_1m_bars()


@pytest.fixture()
def resampler() -> SessionBarResampler:
    return SessionBarResampler()


# ---------------------------------------------------------------------------
# T016 — 1m → 5m correct OHLCV aggregation
# ---------------------------------------------------------------------------

class TestResample5m:
    def test_bar_count(self, resampler, bars_375, calendar):
        """T016: 375 1m bars → 75 complete 5m bars."""
        result = resampler.resample(bars_375, "5m", calendar, "SPLIT_ADJUSTED")
        assert len(result) == 75

    def test_ohlcv_aggregation(self, resampler, bars_375, calendar):
        """T016: First 5m bar aggregates bars [0..4]; open=first, high=max, low=min, close=last, vol=sum."""
        result = resampler.resample(bars_375, "5m", calendar, "SPLIT_ADJUSTED")
        first = result[0]
        src_slice = bars_375.sort_values("timestamp").head(5)

        assert pytest.approx(first.open, rel=1e-9) == float(src_slice["open"].iloc[0])
        assert pytest.approx(first.high, rel=1e-9) == float(src_slice["high"].max())
        assert pytest.approx(first.low, rel=1e-9) == float(src_slice["low"].min())
        assert pytest.approx(first.close, rel=1e-9) == float(src_slice["close"].iloc[-1])
        assert first.volume == int(src_slice["volume"].sum())
        assert first.bucket_bar_count == 5

    def test_last_bar_close_time(self, resampler, bars_375, calendar):
        """T016: Last 5m bucket starts at 15:25 IST (= 09:55 UTC offset)."""
        result = resampler.resample(bars_375, "5m", calendar, "SPLIT_ADJUSTED")
        last = result[-1]
        last_ist = last.timestamp.astimezone(IST)
        # 15:25 IST = last complete 5m bucket before 15:30 close
        assert last_ist.hour == 15
        assert last_ist.minute == 25


# ---------------------------------------------------------------------------
# T017 — 1m → 15m correct aggregation
# ---------------------------------------------------------------------------

class TestResample15m:
    def test_bar_count(self, resampler, bars_375, calendar):
        """T017: 375 1m bars → 25 complete 15m bars (375 / 15 = 25)."""
        result = resampler.resample(bars_375, "15m", calendar, "SPLIT_ADJUSTED")
        assert len(result) == 25

    def test_ohlcv_aggregation(self, resampler, bars_375, calendar):
        """T017: Each 15m bar aggregates 15 source 1m bars correctly."""
        result = resampler.resample(bars_375, "15m", calendar, "SPLIT_ADJUSTED")
        first = result[0]
        src_slice = bars_375.sort_values("timestamp").head(15)

        assert pytest.approx(first.open, rel=1e-9) == float(src_slice["open"].iloc[0])
        assert pytest.approx(first.high, rel=1e-9) == float(src_slice["high"].max())
        assert pytest.approx(first.low, rel=1e-9) == float(src_slice["low"].min())
        assert pytest.approx(first.close, rel=1e-9) == float(src_slice["close"].iloc[-1])
        assert first.volume == int(src_slice["volume"].sum())
        assert first.bucket_bar_count == 15


# ---------------------------------------------------------------------------
# T018 — 1m → 30m correct aggregation
# ---------------------------------------------------------------------------

class TestResample30m:
    def test_bar_count(self, resampler, bars_375, calendar):
        """T018: 375 / 30 = 12.5 → 12 complete bars (trailing partial dropped)."""
        result = resampler.resample(bars_375, "30m", calendar, "SPLIT_ADJUSTED")
        assert len(result) == 12

    def test_last_bucket_is_complete(self, resampler, bars_375, calendar):
        """T018: All 12 emitted bars have exactly 30 source bars each."""
        result = resampler.resample(bars_375, "30m", calendar, "SPLIT_ADJUSTED")
        for bar in result:
            assert bar.bucket_bar_count == 30, (
                f"Expected 30 source bars per 30m bucket, got {bar.bucket_bar_count}"
            )


# ---------------------------------------------------------------------------
# T019 — 1m → 60m correct aggregation
# ---------------------------------------------------------------------------

class TestResample60m:
    def test_bar_count(self, resampler, bars_375, calendar):
        """T019: 375 / 60 = 6.25 → 6 complete bars (trailing partial dropped)."""
        result = resampler.resample(bars_375, "60m", calendar, "SPLIT_ADJUSTED")
        assert len(result) == 6

    def test_each_bar_has_60_sources(self, resampler, bars_375, calendar):
        """T019: Each 60m bar aggregates exactly 60 1m source bars."""
        result = resampler.resample(bars_375, "60m", calendar, "SPLIT_ADJUSTED")
        for bar in result:
            assert bar.bucket_bar_count == 60


# ---------------------------------------------------------------------------
# T020 — Session boundary enforcement
# ---------------------------------------------------------------------------

class TestSessionBoundary:
    def test_bars_after_session_close_excluded(self, resampler, calendar):
        """T020: 1m bars timestamped after 15:30 IST are not included in any bucket."""
        # Generate 390 bars: 375 in session + 15 after 15:30
        bars = _make_1m_bars(n_minutes=390)
        result_5m = resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")
        # Should still produce 75 bars (same as 375-bar session)
        assert len(result_5m) == 75

    def test_no_cross_day_bar(self, resampler, calendar):
        """T020: Bars from two different trading days produce separate, non-crossing buckets."""
        bars_day1 = _make_1m_bars(trading_date="2024-01-02")
        bars_day2 = _make_1m_bars(trading_date="2024-01-03")
        combined = pd.concat([bars_day1, bars_day2], ignore_index=True)
        result = resampler.resample(combined, "5m", calendar, "SPLIT_ADJUSTED")
        # Both days produce 75 bars each = 150 total
        assert len(result) == 150

        # Verify no derived bar spans across day boundary
        for bar in result:
            ist = bar.timestamp.astimezone(IST)
            assert ist.date().isoformat() in ("2024-01-02", "2024-01-03")


# ---------------------------------------------------------------------------
# T021 — Market holiday produces zero bars
# ---------------------------------------------------------------------------

class TestMarketHoliday:
    def test_holiday_produces_zero_bars(self, resampler, calendar):
        """T021: Bars on a market holiday are excluded; result has zero bars."""
        # Find a holiday in the NSE calendar
        # We use a known Saturday as a simple non-trading day

        # Saturday is guaranteed non-trading for NSE
        sat_bars = _make_1m_bars(trading_date="2024-01-06")  # 6 Jan 2024 = Saturday
        result = resampler.resample(sat_bars, "5m", calendar, "SPLIT_ADJUSTED")
        assert len(result) == 0, "Bars on a non-trading Saturday must produce zero derived bars"


# ---------------------------------------------------------------------------
# T022 — Special session (shortened) produces bars only within short window
# ---------------------------------------------------------------------------

class TestSpecialSession:
    def test_short_session_limits_bars(self, resampler):
        """T022: A market calendar with a shortened session limits bars to that window."""
        from trading_stack.calendars import MarketCalendar, SessionOverride
        from trading_stack.domain import infer_market_spec
        from datetime import date, time

        spec = infer_market_spec("RELIANCE", "NSE", "EQUITY")
        # Create a special session: only 09:15–10:30 IST (75 minutes)
        override = SessionOverride(
            session_date=date(2024, 1, 15),
            override_type="SPECIAL_SESSION",
            reason="Test shortened session",
            start_time=time(9, 15),
            end_time=time(10, 30),
        )
        short_cal = MarketCalendar(spec, overrides=(override,))

        # Generate 375 bars (full session), but the special session only has 75 min
        bars = _make_1m_bars(trading_date="2024-01-15")
        result = resampler.resample(bars, "5m", short_cal, "SPLIT_ADJUSTED")
        # 75 minutes / 5m = 15 bars
        assert len(result) == 15, (
            f"Shortened special session (75 min) should produce 15 5m bars, got {len(result)}"
        )


# ---------------------------------------------------------------------------
# T023 — Missing minute in session: bucket with gap aggregates available bars
# ---------------------------------------------------------------------------

class TestMissingMinute:
    def test_bucket_with_gap_fails_closed(self, resampler, calendar):
        """A complete 5m bucket cannot be derived from four source minutes."""
        bars = _make_1m_bars(trading_date="2024-01-02", n_minutes=375)
        # Remove bar index 2 (third 1m bar of the first 5m bucket)
        bars_with_gap = bars.drop(index=2).reset_index(drop=True)
        with pytest.raises(ResamplingError, match="Incomplete or misaligned"):
            resampler.resample(bars_with_gap, "5m", calendar, "SPLIT_ADJUSTED")


# ---------------------------------------------------------------------------
# T024 — Quarantined minute rejection
# ---------------------------------------------------------------------------

class TestQuarantinedRejection:
    def test_quarantined_flag_raises(self, resampler, calendar):
        """T024: Any quarantined=True flag causes ResamplingError (fail closed)."""
        bars = _make_1m_bars()
        bars["quarantined"] = False
        bars.loc[5, "quarantined"] = True  # One quarantined bar
        with pytest.raises(QuarantinedSourceError, match="quarantined"):
            resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")

    def test_untrusted_flag_raises(self, resampler, calendar):
        """T024: Any trusted=False flag causes ResamplingError (fail closed)."""
        bars = _make_1m_bars()
        bars["trusted"] = True
        bars.loc[10, "trusted"] = False
        with pytest.raises(QuarantinedSourceError, match="untrusted"):
            resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")


# ---------------------------------------------------------------------------
# T025 — Incomplete last bucket is dropped
# ---------------------------------------------------------------------------

class TestIncompleteTrailingBucket:
    def test_incomplete_trailing_bucket_not_emitted(self, resampler, calendar):
        """T025: A partial trailing bucket (< target_minutes bars) is never emitted."""
        # Add 3 extra bars after 15:30 IST (they'd be an incomplete extra bucket anyway)
        bars = _make_1m_bars(n_minutes=377)  # 375 + 2 extra
        result = resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")
        # Still 75 complete 5m bars
        assert len(result) == 75

    def test_partial_session_30m_trailing_dropped(self, resampler, calendar):
        """T025: 375 min / 30m = 12.5 → trailing 15-bar incomplete bucket is dropped."""
        bars = _make_1m_bars()
        result = resampler.resample(bars, "30m", calendar, "SPLIT_ADJUSTED")
        assert len(result) == 12
        # Verify last 30m bar starts at 14:45 IST (minute 330) and closes at 15:15 IST (minute 360)
        last = result[-1]
        last_ist = last.timestamp.astimezone(IST)
        assert last_ist.hour == 14
        assert last_ist.minute == 45


# ---------------------------------------------------------------------------
# T026 — Mixed adjustment basis rejection
# ---------------------------------------------------------------------------

class TestMixedAdjustmentBasis:
    def test_mixed_basis_raises(self, resampler, calendar):
        """T026: Mixed adjustment basis in source bars raises MixedAdjustmentBasisError."""
        bars = _make_1m_bars()
        bars.loc[50, "adjustment"] = "UNADJUSTED"  # Mix in a different basis
        with pytest.raises(MixedAdjustmentBasisError, match="mixed adjustment"):
            resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")

    def test_conflicting_stated_basis_raises(self, resampler, calendar):
        """T026: All bars UNADJUSTED but source_adjustment='SPLIT_ADJUSTED' raises."""
        bars = _make_1m_bars(adjustment="UNADJUSTED")
        with pytest.raises(MixedAdjustmentBasisError):
            resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")


# ---------------------------------------------------------------------------
# T027 — Deterministic hash: same source → same content_hash
# ---------------------------------------------------------------------------

class TestDeterministicHash:
    def test_same_source_same_hash(self, resampler, bars_375, calendar):
        """T027: Resampling the same source twice produces identical content_hash."""
        result1 = resampler.resample(bars_375, "15m", calendar, "SPLIT_ADJUSTED")
        result2 = resampler.resample(bars_375, "15m", calendar, "SPLIT_ADJUSTED")

        df1 = pd.DataFrame([{"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in result1])
        df2 = pd.DataFrame([{"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in result2])

        assert compute_derived_content_hash(df1) == compute_derived_content_hash(df2)

    def test_unsupported_timeframe_raises(self, resampler, bars_375, calendar):
        """T027 guard: unsupported timeframe raises UnsupportedTimeframeError."""
        with pytest.raises(UnsupportedTimeframeError):
            resampler.resample(bars_375, "3m", calendar, "SPLIT_ADJUSTED")

    def test_empty_input_raises(self, resampler, calendar):
        """T027 guard: empty DataFrame raises ResamplingError."""
        empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        with pytest.raises(ResamplingError, match="empty"):
            resampler.resample(empty_df, "5m", calendar, "SPLIT_ADJUSTED")


# ---------------------------------------------------------------------------
# T028 — Source mutation changes derived hash
# ---------------------------------------------------------------------------

class TestSourceMutationChangesHash:
    def test_price_mutation_changes_hash(self, resampler, bars_375, calendar):
        """T028: Changing one price in the source bars produces a different derived content_hash."""
        result_original = resampler.resample(bars_375, "15m", calendar, "SPLIT_ADJUSTED")
        df_original = pd.DataFrame([{"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in result_original])

        # Mutate one bar's open price
        bars_mutated = bars_375.copy()
        bars_mutated.loc[0, "open"] = bars_mutated.loc[0, "open"] + 999.0

        result_mutated = resampler.resample(bars_mutated, "15m", calendar, "SPLIT_ADJUSTED")
        df_mutated = pd.DataFrame([{"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in result_mutated])

        hash_original = compute_derived_content_hash(df_original)
        hash_mutated = compute_derived_content_hash(df_mutated)
        assert hash_original != hash_mutated, (
            "Mutating a source bar price must produce a different derived content_hash"
        )


# ---------------------------------------------------------------------------
# T029 — No future/incomplete bar leakage
# ---------------------------------------------------------------------------

class TestNoFutureBarLeakage:
    def test_bars_after_session_close_not_in_any_bucket(self, resampler, calendar):
        """T029: 1m bars timestamped strictly after session close are never included."""
        # 09:15 IST start, add 400 bars (375 + 25 after-close)
        bars = _make_1m_bars(n_minutes=400)
        result = resampler.resample(bars, "5m", calendar, "SPLIT_ADJUSTED")

        # Validate no bar's open timestamp is after 15:30 IST
        for bar in result:
            bar_ist = bar.timestamp.astimezone(IST)
            session_close_ist = bar_ist.replace(hour=15, minute=30, second=0, microsecond=0)
            assert bar.timestamp <= session_close_ist.astimezone(UTC), (
                f"Bar at {bar.timestamp} is after session close (15:30 IST)"
            )


# ---------------------------------------------------------------------------
# DQ Certification tests
# ---------------------------------------------------------------------------

class TestDerivedBarDQCertifier:
    """Tests for the DerivedBarDQCertifier (T016 / T025 support)."""

    def _make_derived_df(self, n_bars: int = 25) -> pd.DataFrame:
        """Produce a valid 15m derived DataFrame for 2024-01-02."""
        IST_TZ = ZoneInfo("Asia/Kolkata")
        session_open = datetime(2024, 1, 2, 9, 15, tzinfo=IST_TZ)
        rows = []
        for i in range(n_bars):
            ts = (session_open + pd.Timedelta(minutes=15 * i)).astimezone(UTC)
            rows.append({"timestamp": ts, "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i, "volume": 10000})
        return pd.DataFrame(rows)

    def test_valid_bars_certified(self):
        """Valid derived bars produce certified=True."""
        from data_platform.dq_derived import DerivedBarDQCertifier
        from trading_stack.calendars import MarketCalendar
        from trading_stack.domain import infer_market_spec

        cal = MarketCalendar(infer_market_spec("RELIANCE", "NSE", "EQUITY"))
        certifier = DerivedBarDQCertifier(calendar=cal, target_timeframe="15m")
        df = self._make_derived_df()
        report = certifier.certify(df, symbol="RELIANCE", exchange="NSE")
        assert report.certified, f"Expected certified=True; issues: {report.issues}"

    def test_ohlc_violation_fails_certification(self):
        """OHLC violation (high < open) causes certified=False."""
        from data_platform.dq_derived import DerivedBarDQCertifier
        from trading_stack.calendars import MarketCalendar
        from trading_stack.domain import infer_market_spec

        cal = MarketCalendar(infer_market_spec("RELIANCE", "NSE", "EQUITY"))
        certifier = DerivedBarDQCertifier(calendar=cal, target_timeframe="15m")
        df = self._make_derived_df()
        df.loc[0, "high"] = df.loc[0, "open"] - 1.0  # high < open
        report = certifier.certify(df, symbol="RELIANCE", exchange="NSE")
        assert not report.certified

    def test_duplicate_timestamp_fails_certification(self):
        """Duplicate timestamps cause certified=False."""
        from data_platform.dq_derived import DerivedBarDQCertifier
        from trading_stack.calendars import MarketCalendar
        from trading_stack.domain import infer_market_spec

        cal = MarketCalendar(infer_market_spec("RELIANCE", "NSE", "EQUITY"))
        certifier = DerivedBarDQCertifier(calendar=cal, target_timeframe="15m")
        df = self._make_derived_df()
        df_dup = pd.concat([df, df.head(1)], ignore_index=True)
        report = certifier.certify(df_dup, symbol="RELIANCE", exchange="NSE")
        assert not report.certified
        assert not report.no_duplicates

    def test_empty_df_fails_certification(self):
        """Empty DataFrame causes certified=False."""
        from data_platform.dq_derived import DerivedBarDQCertifier
        from trading_stack.calendars import MarketCalendar
        from trading_stack.domain import infer_market_spec

        cal = MarketCalendar(infer_market_spec("RELIANCE", "NSE", "EQUITY"))
        certifier = DerivedBarDQCertifier(calendar=cal, target_timeframe="15m")
        report = certifier.certify(pd.DataFrame(), symbol="RELIANCE", exchange="NSE")
        assert not report.certified
