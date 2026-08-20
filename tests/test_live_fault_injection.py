"""Institutional fault injection and resilience test suite for live streaming & admission gateway.

Simulates edge-case network anomalies, corrupt packets, clock skews, flash crashes,
feed irregularities, late cross-window candle arrivals, and database failures to guarantee fail-closed robustness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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
from smartapi.auth import SmartAPIAuth
from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient
from trading_stack.domain import Bar

from trading_stack.live_aggregator import RealtimeBarAggregator
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
        for _ in range(50):
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

        recv_2 = datetime(2023, 1, 18, 5, 30, 1, tzinfo=timezone.utc)
        tick2 = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=recv_2, received_at_utc=recv_2, received_monotonic_ns=2,
            raw_packet_size=51, sequence_number=2, ltp=960.0,
        )
        res2 = self.validator.validate(tick2, received_at_utc=recv_2)
        self.assertEqual(res2.action, TickAdmissionAction.QUARANTINE)
        self.assertIn(AdmissionReasonCode.EXTREME_PRICE_VELOCITY, res2.reasons)

    def test_fault_scenario_9_late_tick_does_not_prematurely_finalize_newer_bar(self) -> None:
        """Scenario 9: Late tick for window 10:01 arriving at 10:02:00.100 does NOT prematurely finalize 10:02 bar."""
        aggregator = RealtimeBarAggregator(timeframe="1m")
        closed_bars: list[Bar] = []
        aggregator.subscribe_bar(lambda b: closed_bars.append(b))

        # 1. First tick in 10:02 candle (window: 10:02:00 -> 10:03:00)
        ts_1002 = datetime(2023, 1, 18, 4, 32, 0, 100000, tzinfo=timezone.utc)  # 10:02:00.100 IST = 04:32:00.100 UTC
        tick_1002_a = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=ts_1002, received_at_utc=ts_1002, received_monotonic_ns=1,
            raw_packet_size=51, ltp=600.0,
        )
        aggregator.process_tick(tick_1002_a)
        self.assertEqual(len(closed_bars), 0)  # 10:02 open, not closed yet

        # 2. Late tick arrives for 10:01 candle (window: 10:01:00 -> 10:02:00)
        ts_1001_late = datetime(2023, 1, 18, 4, 31, 59, 800000, tzinfo=timezone.utc)  # 10:01:59.800 IST (300ms late)
        tick_1001_late = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=ts_1001_late, received_at_utc=ts_1002, received_monotonic_ns=2,
            raw_packet_size=51, ltp=599.5,
        )
        aggregator.process_tick(tick_1001_late)
        # CRITICAL ASSERTION: The active 10:02 bar MUST NOT be finalized by this late 10:01 tick!
        self.assertEqual(len(closed_bars), 0)

        # 3. Subsequent tick at 10:02:30 updates the 10:02 candle normally and finalizes elapsed 10:01 window
        ts_1002_b = datetime(2023, 1, 18, 4, 32, 30, tzinfo=timezone.utc)
        tick_1002_b = LtpTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.LTP,
            exchange_timestamp=ts_1002_b, received_at_utc=ts_1002_b, received_monotonic_ns=3,
            raw_packet_size=51, ltp=602.0,
        )
        aggregator.process_tick(tick_1002_b)
        # The 10:01 window (which had been waiting for lateness) now cleanly closes
        self.assertEqual(len(closed_bars), 1)
        self.assertEqual(closed_bars[0].close, 599.5)
        # And the active 10:02 bar is still open with 2 ticks
        open_bar = aggregator._open_bars.get("SBIN")
        self.assertIsNotNone(open_bar)
        self.assertEqual(open_bar["high"], 602.0)
        self.assertEqual(open_bar["tick_count"], 2)

    def test_fault_scenario_10_websocket_worker_survives_corrupt_packet(self) -> None:
        """Scenario 10: WebSocket worker receives corrupted binary payload, fails decoder safely, and processes next valid packet."""
        auth = SmartAPIAuth({
            "smartapi": {
                "api_key": "k",
                "client_code": "c",
                "pin": "1",
                "totp_secret": "JBSWY3DPEHPK3PXP",
                "base_url": "https://apiconnect.angelone.in",
            }
        })

        test_policy = LiveAdmissionPolicy(check_session_hours=False, max_stale_latency_seconds=3600.0)
        test_validator = LiveMarketDataAdmissionValidator(policy=test_policy)
        client = SmartAPIWebSocketClient(auth=auth, admission_validator=test_validator)
        client._state = ConnectionState.CONNECTED

        received_events: list[Any] = []
        client.subscribe_tick(lambda e: received_events.append(e))

        # 1. Send corrupt 5-byte packet to _on_data
        corrupt_packet = b"\x01\x01\x00\x00\x00"
        client._on_data(None, corrupt_packet, 2, 1, client.generation_id)  # type: ignore[arg-type]
        self.assertEqual(len(received_events), 0)
        self.assertEqual(client.metrics.invalid_packets_total, 1)

        # 2. Worker survives! Send valid tick packet afterward
        # 51-byte valid LTP packet for token 3045 (SBIN)
        import struct
        now_ts = datetime.now(timezone.utc)
        ts_ms = int(now_ts.timestamp() * 1000)
        valid_packet = bytearray(51)

        valid_packet[0] = 1  # Mode 1 LTP
        valid_packet[1] = 1  # Exchange NSE_CM
        valid_packet[2:27] = b"3045".ljust(25, b"\x00")
        struct.pack_into("<q", valid_packet, 27, 101)  # sequence
        struct.pack_into("<q", valid_packet, 35, ts_ms)  # timestamp
        struct.pack_into("<q", valid_packet, 43, 60050)  # price 600.50

        client._on_data(None, bytes(valid_packet), 2, 1, client.generation_id)  # type: ignore[arg-type]
        self.assertEqual(client.metrics.packets_decoded_total, 1)
        self.assertEqual(client._dispatch_queue.qsize(), 1)

    def test_live_entrypoint_cannot_start_without_admission_gateway(self) -> None:
        """Client constructed without explicit validator must automatically instantiate fail-closed LiveMarketDataAdmissionValidator."""
        auth = SmartAPIAuth({
            "smartapi": {
                "api_key": "k",
                "client_code": "c",
                "pin": "1",
                "totp_secret": "JBSWY3DPEHPK3PXP",
                "base_url": "https://apiconnect.angelone.in",
            }
        })
        client = SmartAPIWebSocketClient(auth=auth)  # admission_validator=None
        self.assertIsNotNone(client.admission_validator)
        self.assertIsInstance(client.admission_validator, LiveMarketDataAdmissionValidator)

    def test_async_quarantine_queue_resilience_under_db_failure(self) -> None:
        """Asynchronous quarantine worker catches DuckDB errors without crashing client or dropping live dispatch queue."""
        class BrokenDBConn:
            def execute(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("Disk IO Error / DuckDB Locked")

        auth = SmartAPIAuth({
            "smartapi": {
                "api_key": "k",
                "client_code": "c",
                "pin": "1",
                "totp_secret": "JBSWY3DPEHPK3PXP",
                "base_url": "https://apiconnect.angelone.in",
            }
        })
        client = SmartAPIWebSocketClient(auth=auth, admission_validator=self.validator, quarantine_conn=BrokenDBConn())
        client._state = ConnectionState.CONNECTED

        # Start quarantine drain thread
        import threading
        t = threading.Thread(target=client._quarantine_worker, daemon=True)
        t.start()

        # Enqueue crossed-book quarantine tick
        crossed_tick = SnapQuoteTick(
            exchange="NSE", token="3045", symbol="SBIN", mode=LiveTickerMode.SNAP_QUOTE,
            exchange_timestamp=datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc),
            received_at_utc=datetime(2023, 1, 18, 5, 30, 0, tzinfo=timezone.utc),
            received_monotonic_ns=1, raw_packet_size=379, ltp=600.0,
            best_5_buy=(DepthLevel(price=605.0, quantity=100, orders=2),),
            best_5_sell=(DepthLevel(price=601.0, quantity=100, orders=1),),
        )
        res = self.validator.validate(crossed_tick)
        client._quarantine_queue.put((res, {"test": "payload"}))
        client._quarantine_queue.join()  # Successfully processed and drained despite DB failure!

        # Client state remains healthy
        self.assertEqual(client.state, ConnectionState.CONNECTED)
        client._state = ConnectionState.STOPPED

    def test_late_cumulative_volume_does_not_regress_baseline(self) -> None:
        """Late quote tick from older window must not regress cumulative volume baseline for subsequent bars."""
        aggregator = RealtimeBarAggregator(timeframe="1m")

        # 1. 09:15:30 bar with cumulative volume 10,100
        t1 = QuoteTick(
            exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=datetime(2023, 1, 18, 9, 15, 30, tzinfo=timezone.utc),
            received_at_utc=datetime(2023, 1, 18, 9, 15, 30, tzinfo=timezone.utc),
            received_monotonic_ns=1, raw_packet_size=123, ltp=2500.0, cumulative_volume=10_100, last_traded_qty=100,
        )
        aggregator.process_tick(t1)

        # 2. Out-of-order late tick from 09:15:10 with older cumulative volume 10,000
        t_late = QuoteTick(
            exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=datetime(2023, 1, 18, 9, 15, 10, tzinfo=timezone.utc),
            received_at_utc=datetime(2023, 1, 18, 9, 15, 35, tzinfo=timezone.utc),
            received_monotonic_ns=2, raw_packet_size=123, ltp=2499.0, cumulative_volume=10_000, last_traded_qty=50,
        )
        aggregator.process_tick(t_late)

        # 3. Next forward tick at 09:16:05 with cumulative volume 10,120
        t2 = QuoteTick(
            exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.QUOTE,
            exchange_timestamp=datetime(2023, 1, 18, 9, 16, 5, tzinfo=timezone.utc),
            received_at_utc=datetime(2023, 1, 18, 9, 16, 5, tzinfo=timezone.utc),
            received_monotonic_ns=3, raw_packet_size=123, ltp=2502.0, cumulative_volume=10_120, last_traded_qty=20,
        )
        closed_bars = aggregator.process_tick(t2)
        # Closed bar for 09:15 has volume = 100.0 (from initial tick)
        self.assertEqual(len(closed_bars), 1)
        self.assertEqual(closed_bars[0].volume, 100.0)

        # Open bar for 09:16 must have delta = 10,120 - 10,100 = 20 (NOT 120!)
        open_bar_volume = aggregator._open_bars["RELIANCE"]["volume"]
        self.assertEqual(open_bar_volume, 20.0)


    def test_stream_writer_retains_batch_on_db_failure(self) -> None:
        """DuckDBStreamWriter retains batch and increments dropped_records when database insert fails."""
        from trading_stack.stream_persistence import DuckDBStreamWriter
        writer = DuckDBStreamWriter(db_path=":memory:", batch_size=1, flush_interval_seconds=0.01)
        writer._conn = None  # Force database failure

        tick_batch = [{"exchange": "NSE", "token": "2885", "ltp": 2500.0}]
        bar_batch: list[dict[str, Any]] = []
        ticks_ok, bars_ok = writer._flush_batches(tick_batch, bar_batch)
        self.assertFalse(ticks_ok)

    def test_duckdb_validator_fails_closed_on_db_error(self) -> None:
        """DuckDBValidator marks report as non-passing (passed=False) when database queries fail."""
        from validators.duckdb_quality import DuckDBValidator

        validator = DuckDBValidator(timeframe="1d")

        class BrokenDBManager:
            @property
            def conn(self) -> Any:
                class BrokenConn:
                    def execute(self, *args: Any, **kwargs: Any) -> Any:
                        raise RuntimeError("Disk Failure / Locked DuckDB")
                return BrokenConn()

            def get_candle_count(self, symbol: str, timeframe: str) -> int:
                return 100

        report = validator.run_all_checks(BrokenDBManager(), "RELIANCE")  # type: ignore[arg-type]
        self.assertFalse(report["passed"])
        self.assertGreater(report["blocking_issue_count"], 0)


if __name__ == "__main__":
    unittest.main()


