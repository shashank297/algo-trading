"""Comprehensive unit and adversarial test suite for Live Market Data Admission Gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

import duckdb

from data_platform.contracts import (
    Depth20Snapshot,
    DepthLevel,
    LiveTickerMode,
    LtpTick,
    SnapQuoteTick,
)
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

    def test_depth20_snapshot_admission_accepted_without_ltp(self) -> None:
        """Depth20Snapshot contains no LTP but has valid 20-level order book. Must be ACCEPTED."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        bids = tuple(DepthLevel(price=600.0 - i * 0.05, quantity=100 + i * 10, orders=1) for i in range(20))
        asks = tuple(DepthLevel(price=600.10 + i * 0.05, quantity=100 + i * 10, orders=1) for i in range(20))

        depth_event = Depth20Snapshot(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.DEPTH,
            exchange_timestamp=recv_utc,
            received_at_utc=recv_utc,
            received_monotonic_ns=1_000_000_000,
            raw_packet_size=443,
            bids=bids,
            asks=asks,
        )

        res = self.validator.validate(depth_event, received_at_utc=recv_utc)
        self.assertTrue(res.is_accepted)
        self.assertEqual(res.action, TickAdmissionAction.ACCEPT)
        self.assertIn(AdmissionReasonCode.VALID_TICK, res.reasons)

    def test_depth20_crossed_book_and_monotonicity_rejections(self) -> None:
        """Depth book with crossed spread (Bid >= Ask) or non-monotonic ordering is quarantined/rejected."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        
        # 1. Crossed top of book (Bid 605 >= Ask 600)
        crossed_depth = Depth20Snapshot(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.DEPTH,
            exchange_timestamp=recv_utc, received_at_utc=recv_utc, received_monotonic_ns=1, raw_packet_size=443,
            bids=(DepthLevel(price=605.0, quantity=100, orders=1),),
            asks=(DepthLevel(price=600.0, quantity=100, orders=1),),
        )
        res_cross = self.validator.validate(crossed_depth, received_at_utc=recv_utc)
        self.assertEqual(res_cross.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.CROSSED_BOOK_BID_GE_ASK, res_cross.reasons)

        # 2. Inverted bid order (Bid[0] = 590, Bid[1] = 595 - should be descending)
        inverted_depth = Depth20Snapshot(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.DEPTH,
            exchange_timestamp=recv_utc, received_at_utc=recv_utc, received_monotonic_ns=1, raw_packet_size=443,
            bids=(DepthLevel(price=590.0, quantity=100, orders=1), DepthLevel(price=595.0, quantity=100, orders=1)),
            asks=(DepthLevel(price=600.0, quantity=100, orders=1),),
        )
        res_inv = self.validator.validate(inverted_depth, received_at_utc=recv_utc)
        self.assertEqual(res_inv.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.INVALID_DEPTH_ORDERING, res_inv.reasons)

    def test_missing_exchange_timestamp_fail_closed(self) -> None:
        """Missing or non-positive exchange timestamp is rejected fail-closed (never replaced with arrival time)."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick_no_ts = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=None,  # Missing!
            received_at_utc=recv_utc, received_monotonic_ns=1, raw_packet_size=51, ltp=600.0,
        )
        res = self.validator.validate(tick_no_ts, received_at_utc=recv_utc)
        self.assertFalse(res.is_accepted)
        self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)
        self.assertIn(AdmissionReasonCode.MISSING_EXCHANGE_TIMESTAMP, res.reasons)

    def test_missing_exchange_fail_closed(self) -> None:
        """Missing exchange in input is rejected fail-closed without silent defaulting."""
        recv_utc = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick_dict = {"token": "3045", "price": 600.0, "timestamp": recv_utc}  # Missing exchange!
        res = self.validator.validate(tick_dict, received_at_utc=recv_utc)
        self.assertFalse(res.is_accepted)
        self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)
        self.assertIn(AdmissionReasonCode.MISSING_EXCHANGE, res.reasons)

    def test_legitimate_overnight_gap_not_quarantined(self) -> None:
        """Legitimate 15% price jump between Friday close and Monday open is NOT quarantined."""
        # Friday 15:29 IST = 09:59 UTC
        fri_utc = datetime(2023, 1, 13, 9, 59, 0, tzinfo=timezone.utc)
        tick_fri = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=fri_utc, received_at_utc=fri_utc, received_monotonic_ns=1,
            raw_packet_size=51, ltp=100.0,
        )
        res_fri = self.validator.validate(tick_fri, received_at_utc=fri_utc)
        self.assertTrue(res_fri.is_accepted)

        # Monday 09:16 IST = 03:46 UTC (Price opened at 115.0, +15% overnight gap)
        mon_utc = datetime(2023, 1, 16, 3, 46, 0, tzinfo=timezone.utc)
        tick_mon = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=mon_utc, received_at_utc=mon_utc, received_monotonic_ns=2,
            raw_packet_size=51, ltp=115.0,
        )
        res_mon = self.validator.validate(tick_mon, received_at_utc=mon_utc)
        self.assertTrue(res_mon.is_accepted)
        self.assertEqual(res_mon.action, TickAdmissionAction.ACCEPT)

    def test_sequence_tracking_does_not_regress_backward(self) -> None:
        """Out-of-order sequence arrival updates sequence gap reason but keeps highest_sequence_seen monotonic."""
        recv_1 = datetime(2023, 1, 18, 5, 0, 0, tzinfo=timezone.utc)
        tick1 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_1, received_at_utc=recv_1, received_monotonic_ns=1,
            raw_packet_size=51, sequence_number=100, ltp=600.0,
        )
        self.assertTrue(self.validator.validate(tick1, received_at_utc=recv_1).is_accepted)

        # Arrives with sequence 98 (out-of-order sequence)
        recv_2 = datetime(2023, 1, 18, 5, 0, 0, 100000, tzinfo=timezone.utc)
        tick2 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_2, received_at_utc=recv_2, received_monotonic_ns=2,
            raw_packet_size=51, sequence_number=98, ltp=600.1,
        )
        self.validator.validate(tick2, received_at_utc=recv_2)
        state = self.validator._token_states["3045"]
        self.assertEqual(state.highest_sequence_seen, 100)

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
