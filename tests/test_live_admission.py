"""Comprehensive unit and adversarial test suite for Live Market Data Admission Gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

import duckdb

from data_platform.contracts import DepthLevel, LiveTickerMode, LtpTick, QuoteTick, SnapQuoteTick
from data_platform.live_admission import (
    AdmissionReasonCode,
    LiveAdmissionPolicy,
    LiveMarketDataAdmissionValidator,
    TickAdmissionAction,
)
from trading_stack.trading_calendar import TradingCalendar


class TestLiveAdmissionGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.calendar = TradingCalendar()
        self.policy = LiveAdmissionPolicy(

            max_future_skew_seconds=1.0,
            max_stale_latency_seconds=5.0,
            max_price_velocity_pct=0.10,
            enforce_monotonic_cumulative_volume=True,
            check_session_hours=True,
            fail_closed=True,
        )
        self.validator = LiveMarketDataAdmissionValidator(policy=self.policy, calendar=self.calendar)

    def test_clean_accepted_tick(self) -> None:
        """Valid intraday tick in market hours (e.g. Wednesday 10:30 IST) is ACCEPTED."""
        # Wednesday 2023-01-18 10:30:00 IST = 05:00:00 UTC
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick_ts = datetime(2023, 1, 18, 4, 59, 59, 800000, tzinfo=timezone.utc)

        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=tick_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=1_000_000_000,
            raw_packet_size=51,
            sequence_number=100,
            ltp=600.50,
        )

        res = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertTrue(res.is_accepted)
        self.assertEqual(res.action, TickAdmissionAction.ACCEPT)
        self.assertIn(AdmissionReasonCode.VALID_TICK, res.reasons)
        self.assertEqual(res.price, 600.50)

    def test_reject_non_positive_and_non_finite_price(self) -> None:
        """Price <= 0, NaN, or Inf is REJECTED as MALFORMED."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        bad_prices = [0.0, -50.0, float("nan"), float("inf"), float("-inf")]

        for bad_p in bad_prices:
            tick_dict = {
                "token": "3045",
                "exchange": "NSE",
                "symbol": "SBIN",
                "timestamp": recv_utc,
                "price": bad_p,
                "volume": 100,
            }
            res = self.validator.validate(tick_dict, received_at_utc=recv_utc)
            self.assertFalse(res.is_accepted)
            self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)

    def test_reject_negative_volume(self) -> None:
        """Negative volume is REJECTED as MALFORMED."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick_dict = {
            "token": "3045",
            "exchange": "NSE",
            "symbol": "SBIN",
            "timestamp": recv_utc,
            "price": 600.0,
            "volume": -500,
        }
        res = self.validator.validate(tick_dict, received_at_utc=recv_utc)
        self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)
        self.assertIn(AdmissionReasonCode.VOLUME_NEGATIVE, res.reasons)

    def test_future_timestamp_skew_rejection(self) -> None:
        """Timestamp > 1s into the future is REJECTED as FUTURE_TIMESTAMP_EXCEEDED."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        future_ts = datetime(2023, 1, 18, 5, 0, 5, tzinfo=timezone.utc)  # 5s in future

        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=future_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=1_000_000_000,
            raw_packet_size=51,
            ltp=600.0,
        )
        res = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)
        self.assertIn(AdmissionReasonCode.FUTURE_TIMESTAMP_EXCEEDED, res.reasons)

    def test_stale_tick_drop(self) -> None:
        """Tick with latency > 5s is DROPPED as STALE."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 10, tzinfo=timezone.utc)
        stale_ts = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)  # 10s lag

        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=stale_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=1_000_000_000,
            raw_packet_size=51,
            ltp=600.0,
        )
        res = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertEqual(res.action, TickAdmissionAction.DROP_STALE)
        self.assertIn(AdmissionReasonCode.STALE_TICK_LATENCY, res.reasons)

    def test_crossed_book_quarantine(self) -> None:
        """SnapQuote with Bid >= Ask is QUARANTINED."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick = SnapQuoteTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.SNAP_QUOTE,
            exchange_timestamp=recv_utc,
            received_at_utc=recv_utc,
            received_monotonic_ns=1_000_000_000,
            raw_packet_size=379,
            ltp=600.0,
            best_5_buy=(DepthLevel(price=605.0, quantity=100, orders=2),),   # Bid 605
            best_5_sell=(DepthLevel(price=600.0, quantity=100, orders=2),),  # Ask 600 (Crossed!)
        )
        res = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertEqual(res.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.CROSSED_BOOK_BID_GE_ASK, res.reasons)

    def test_duplicate_tick_and_sequence_drop(self) -> None:
        """Duplicate tick payload or same sequence number drops subsequent duplicates."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_utc,
            received_at_utc=recv_utc,
            received_monotonic_ns=1_000_000_000,
            raw_packet_size=51,
            sequence_number=101,
            ltp=600.0,
        )

        res1 = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertTrue(res1.is_accepted)

        # Ingest same tick again
        res2 = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertEqual(res2.action, TickAdmissionAction.DROP_DUPLICATE)

    def test_extreme_price_velocity_quarantine(self) -> None:
        """Sudden 50% single-tick price jump triggers QUARANTINE."""
        recv_utc_1 = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick1 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_utc_1, received_at_utc=recv_utc_1, received_monotonic_ns=1,
            raw_packet_size=51, sequence_number=1, ltp=600.0,
        )
        res1 = self.validator.validate(tick1, received_at_utc=recv_utc_1)
        self.assertTrue(res1.is_accepted)

        # Second tick jumps from 600.0 to 900.0 (+50%)
        recv_utc_2 = datetime(2023, 1, 18, 5, 0, 1, tzinfo=timezone.utc)
        tick2 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_utc_2, received_at_utc=recv_utc_2, received_monotonic_ns=2,
            raw_packet_size=51, sequence_number=2, ltp=900.0,
        )
        res2 = self.validator.validate(tick2, received_at_utc=recv_utc_2)
        self.assertEqual(res2.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.EXTREME_PRICE_VELOCITY, res2.reasons)

    def test_cumulative_volume_intraday_decrease_quarantine(self) -> None:
        """Cumulative volume decreasing in same session triggers QUARANTINE."""
        recv_utc_1 = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick1 = QuoteTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=recv_utc_1, received_at_utc=recv_utc_1, received_monotonic_ns=1,
            raw_packet_size=123, sequence_number=1, ltp=600.0, cumulative_volume=50_000,
        )
        res1 = self.validator.validate(tick1, received_at_utc=recv_utc_1)
        self.assertTrue(res1.is_accepted)

        # Second tick reports lower cumulative volume (30,000)
        recv_utc_2 = datetime(2023, 1, 18, 5, 0, 1, tzinfo=timezone.utc)
        tick2 = QuoteTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=recv_utc_2, received_at_utc=recv_utc_2, received_monotonic_ns=2,
            raw_packet_size=123, sequence_number=2, ltp=600.5, cumulative_volume=30_000,
        )
        res2 = self.validator.validate(tick2, received_at_utc=recv_utc_2)
        self.assertEqual(res2.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.CUMULATIVE_VOLUME_DECREASE, res2.reasons)

    def test_session_calendar_rejection_weekend_and_out_of_hours(self) -> None:
        """Ticks on weekend or outside 09:15-15:30 IST are classified as DROP_OUT_OF_SESSION."""
        # Saturday 2023-01-21 10:30 IST
        sat_utc = datetime(2023, 1, 21, 5, 0, 0, tzinfo=timezone.utc)
        res_sat = self.validator.validate(
            {"token": "3045", "exchange": "NSE", "price": 600.0, "timestamp": sat_utc},
            received_at_utc=sat_utc,
        )
        self.assertEqual(res_sat.action, TickAdmissionAction.DROP_OUT_OF_SESSION)
        self.assertIn(AdmissionReasonCode.WEEKEND_SESSION_REJECTED, res_sat.reasons)

        # Wednesday 2023-01-18 at 08:30 IST (Pre-market out of hours)
        early_utc = datetime(2023, 1, 18, 3, 0, 0, tzinfo=timezone.utc)
        res_early = self.validator.validate(
            {"token": "3045", "exchange": "NSE", "price": 600.0, "timestamp": early_utc},
            received_at_utc=early_utc,
        )
        self.assertEqual(res_early.action, TickAdmissionAction.DROP_OUT_OF_SESSION)
        self.assertIn(AdmissionReasonCode.OUT_OF_SESSION_HOURS, res_early.reasons)

    def test_duckdb_quarantine_persistence(self) -> None:
        """Quarantined events persist to live_market_data_quarantine table."""
        con = duckdb.connect(":memory:")
        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        con.execute(schema_sql)

        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick = SnapQuoteTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.SNAP_QUOTE,
            exchange_timestamp=recv_utc,
            received_at_utc=recv_utc,
            received_monotonic_ns=1,
            raw_packet_size=379,
            ltp=600.0,
            best_5_buy=(DepthLevel(price=610.0, quantity=100, orders=1),),
            best_5_sell=(DepthLevel(price=600.0, quantity=100, orders=1),),
        )
        res = self.validator.validate(tick, received_at_utc=recv_utc)
        self.assertEqual(res.action, TickAdmissionAction.QUARANTINE)

        self.validator.persist_quarantine(con, res, raw_payload={"token": "3045", "error": "crossed"})
        quar_df = con.execute("SELECT * FROM live_market_data_quarantine").df()
        self.assertEqual(len(quar_df), 1)
        self.assertEqual(quar_df["token"].iloc[0], "3045")
        self.assertEqual(quar_df["action"].iloc[0], "QUARANTINE")
        self.assertIn("CROSSED_BOOK_BID_GE_ASK", quar_df["reasons"].iloc[0])
        con.close()


if __name__ == "__main__":
    unittest.main()
