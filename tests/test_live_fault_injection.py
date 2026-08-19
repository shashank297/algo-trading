"""Institutional fault injection and resilience test suite for live streaming & admission gateway.

Simulates edge-case network anomalies, corrupt packets, clock skews, flash crashes,
and feed irregularities to guarantee fail-closed robustness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

import duckdb

from data_platform.contracts import (
    DepthLevel,
    LiveTickerMode,
    LtpTick,
    QuoteTick,
    SnapQuoteTick,
)
from data_platform.live_admission import (
    AdmissionReasonCode,
    LiveAdmissionPolicy,
    LiveMarketDataAdmissionValidator,
    TickAdmissionAction,
)
from smartapi.stream_decoder import SmartStreamDecoder
from trading_stack.trading_calendar import TradingCalendar


class TestLiveFaultInjection(unittest.TestCase):
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
        self.con = duckdb.connect(":memory:")
        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        self.con.execute(schema_sql)

    def tearDown(self) -> None:
        self.con.close()

    def test_fault_scenario_1_reconnect_replay_burst(self) -> None:
        """Scenario 1: Disconnection causes broker to replay 50 duplicate packets. Validator must drop all 50 duplicates."""
        # Wednesday 11:00 IST = 05:30 UTC
        base_time = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=base_time,
            received_at_utc=base_time,
            received_monotonic_ns=1_000_000,
            raw_packet_size=51,
            sequence_number=5001,
            ltp=600.0,
        )

        first_res = self.validator.validate(tick, received_at_utc=base_time)
        self.assertTrue(first_res.is_accepted)

        # Ingest 50 replayed duplicates
        for i in range(50):
            dup_res = self.validator.validate(tick, received_at_utc=base_time)
            self.assertEqual(dup_res.action, TickAdmissionAction.DROP_DUPLICATE)

        stats = self.validator.get_stats()
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["dropped_duplicate"], 50)

    def test_fault_scenario_2_stale_tick_delay(self) -> None:
        """Scenario 2: Extreme network lag delivers a 15-second old tick. Validator drops tick as STALE."""
        recv_time = datetime(2023, 1, 18, 5, 30, 15, tzinfo=timezone.utc)
        stale_tick_time = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)

        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=stale_tick_time,
            received_at_utc=recv_time,
            received_monotonic_ns=1_000_000,
            raw_packet_size=51,
            ltp=600.0,
        )
        res = self.validator.validate(tick, received_at_utc=recv_time)
        self.assertEqual(res.action, TickAdmissionAction.DROP_STALE)
        self.assertIn(AdmissionReasonCode.STALE_TICK_LATENCY, res.reasons)

    def test_fault_scenario_3_future_clock_skew(self) -> None:
        """Scenario 3: Sender/NTP clock anomaly sends timestamps 45 seconds into the future. Validator rejects as malformed."""
        recv_time = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        future_time = datetime(2023, 1, 18, 5, 30, 45, tzinfo=timezone.utc)

        tick = LtpTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=future_time,
            received_at_utc=recv_time,
            received_monotonic_ns=1_000_000,
            raw_packet_size=51,
            ltp=600.0,
        )
        res = self.validator.validate(tick, received_at_utc=recv_time)
        self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)
        self.assertIn(AdmissionReasonCode.FUTURE_TIMESTAMP_EXCEEDED, res.reasons)

    def test_fault_scenario_4_crossed_order_book(self) -> None:
        """Scenario 4: Flawed market depth packet where Best Bid exceeds Best Ask. Validator QUARANTINES and persists."""
        recv_time = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        crossed_tick = SnapQuoteTick(
            exchange="NSE",
            token="3045",
            symbol="SBIN",
            mode=LiveTickerMode.SNAP_QUOTE,
            exchange_timestamp=recv_time,
            received_at_utc=recv_time,
            received_monotonic_ns=1_000_000,
            raw_packet_size=379,
            ltp=600.0,
            best_5_buy=(DepthLevel(price=605.0, quantity=100, orders=2),),
            best_5_sell=(DepthLevel(price=601.0, quantity=100, orders=1),),  # 605 > 601 (Crossed!)
        )

        res = self.validator.validate(crossed_tick, received_at_utc=recv_time)
        self.assertEqual(res.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.CROSSED_BOOK_BID_GE_ASK, res.reasons)

        self.validator.persist_quarantine(self.con, res, raw_payload={"token": "3045", "error": "crossed"})
        row = self.con.execute("SELECT reasons, action FROM live_market_data_quarantine WHERE token = '3045'").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("CROSSED_BOOK_BID_GE_ASK", row[0])

    def test_fault_scenario_5_zero_and_negative_price_malformation(self) -> None:
        """Scenario 5: Broker glitch emits price = 0.0 or negative values. Validator rejects fail-closed."""
        recv_time = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        for bad_price in [0.0, -100.0, float("nan")]:
            res = self.validator.validate(
                {"token": "3045", "exchange": "NSE", "price": bad_price, "timestamp": recv_time},
                received_at_utc=recv_time,
            )
            self.assertEqual(res.action, TickAdmissionAction.REJECT_MALFORMED)

    def test_fault_scenario_6_intraday_volume_counter_reset(self) -> None:
        """Scenario 6: Midday volume counter decreases unexpectedly. Validator QUARANTINES anomaly."""
        recv_1 = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        tick1 = QuoteTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=recv_1, received_at_utc=recv_1, received_monotonic_ns=1,
            raw_packet_size=123, sequence_number=1, ltp=600.0, cumulative_volume=500_000,
        )
        self.assertTrue(self.validator.validate(tick1, received_at_utc=recv_1).is_accepted)

        # Glitched reset to 10,000 volume in same session
        recv_2 = datetime(2023, 1, 18, 5, 30, 1, tzinfo=timezone.utc)
        tick2 = QuoteTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=recv_2, received_at_utc=recv_2, received_monotonic_ns=2,
            raw_packet_size=123, sequence_number=2, ltp=600.5, cumulative_volume=10_000,
        )
        res2 = self.validator.validate(tick2, received_at_utc=recv_2)
        self.assertEqual(res2.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.CUMULATIVE_VOLUME_DECREASE, res2.reasons)

    def test_fault_scenario_7_out_of_order_jitter_handling(self) -> None:
        """Scenario 7: Out-of-order packets arriving beyond tolerance are classified as stale."""
        recv_1 = datetime(2023, 1, 18, 5, 30, 2, tzinfo=timezone.utc)
        tick1 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_1, received_at_utc=recv_1, received_monotonic_ns=1,
            raw_packet_size=51, sequence_number=1, ltp=600.0,
        )
        self.assertTrue(self.validator.validate(tick1, received_at_utc=recv_1).is_accepted)

        # Delayed tick with timestamp 2 seconds earlier (> 500ms tolerance)
        recv_2 = datetime(2023, 1, 18, 5, 30, 3, tzinfo=timezone.utc)
        earlier_ts = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        tick2 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=earlier_ts, received_at_utc=recv_2, received_monotonic_ns=2,
            raw_packet_size=51, sequence_number=2, ltp=600.1,
        )
        res2 = self.validator.validate(tick2, received_at_utc=recv_2)
        self.assertEqual(res2.action, TickAdmissionAction.DROP_STALE)
        self.assertIn(AdmissionReasonCode.OUT_OF_ORDER_TIMESTAMP, res2.reasons)

    def test_fault_scenario_8_extreme_flash_jump_velocity(self) -> None:
        """Scenario 8: Flash spike (+60% single tick) is QUARANTINED protecting downstream stop orders."""
        recv_1 = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        tick1 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_1, received_at_utc=recv_1, received_monotonic_ns=1,
            raw_packet_size=51, sequence_number=1, ltp=600.0,
        )
        self.assertTrue(self.validator.validate(tick1, received_at_utc=recv_1).is_accepted)

        # 60% jump to 960.0
        recv_2 = datetime(2023, 1, 18, 5, 30, 1, tzinfo=timezone.utc)
        tick2 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_2, received_at_utc=recv_2, received_monotonic_ns=2,
            raw_packet_size=51, sequence_number=2, ltp=960.0,
        )
        res2 = self.validator.validate(tick2, received_at_utc=recv_2)
        self.assertEqual(res2.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.EXTREME_PRICE_VELOCITY, res2.reasons)

    def test_fault_scenario_9_corrupt_binary_packets(self) -> None:
        """Scenario 9: Truncated or corrupted binary wire packets fail decoder safely without worker crash."""
        corrupt_packet = b"\x01\x01\x00\x00\x00"  # Truncated 5 bytes
        with self.assertRaises(ValueError):
            SmartStreamDecoder.decode(corrupt_packet)

    def test_fault_scenario_10_admission_persistence_resilience(self) -> None:
        """Scenario 10: Repeated quarantine persist calls execute safely with full isolation."""
        recv_time = datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc)
        for i in range(10):
            tick = LtpTick(
                exchange="NSE", token=f"TOK_{i}", symbol=f"SYM_{i}", mode=LiveTickerMode.LTP,
                exchange_timestamp=recv_time, received_at_utc=recv_time, received_monotonic_ns=i,
                raw_packet_size=51, sequence_number=i, ltp=-50.0,
            )
            res = self.validator.validate(tick, received_at_utc=recv_time)
            self.validator.persist_quarantine(self.con, res, raw_payload={"index": i})

        count = self.con.execute("SELECT COUNT(*) FROM live_market_data_quarantine").fetchone()[0]
        self.assertEqual(count, 10)


if __name__ == "__main__":
    unittest.main()
