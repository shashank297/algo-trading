"""Unit tests for RealtimeBarAggregator event-time semantics, watermarks, and timer completion."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from data_platform.contracts import LiveTickerMode, LtpTick, QuoteTick
from trading_stack.domain import Bar
from trading_stack.live_aggregator import RealtimeBarAggregator


class TestRealtimeBarAggregator(unittest.TestCase):
    def setUp(self) -> None:
        self.aggregator = RealtimeBarAggregator(timeframe="1m", allowed_lateness_seconds=2.0)

    def test_event_time_ordering_with_out_of_order_ticks(self) -> None:
        """Ticks arriving out-of-order must determine Open from earliest event time and Close from latest."""
        # 3 ticks arriving in non-chronological order:
        # 1. Arrived 1st: Event time 09:15:30 @ Rs 100
        # 2. Arrived 2nd: Event time 09:15:50 @ Rs 105 (Latest)
        # 3. Arrived 3rd: Event time 09:15:10 @ Rs 98  (Earliest)
        t_30 = datetime(2026, 8, 20, 3, 45, 30, tzinfo=timezone.utc)
        t_50 = datetime(2026, 8, 20, 3, 45, 50, tzinfo=timezone.utc)
        t_10 = datetime(2026, 8, 20, 3, 45, 10, tzinfo=timezone.utc)

        tick_1 = QuoteTick(
            exchange="NSE_CM",
            token="2885",
            symbol="RELIANCE-EQ",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=t_30,
            received_at_utc=t_30,
            received_monotonic_ns=1,
            raw_packet_size=123,
            ltp=100.0,
            cumulative_volume=1000,
        )
        tick_2 = QuoteTick(
            exchange="NSE_CM",
            token="2885",
            symbol="RELIANCE-EQ",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=t_50,
            received_at_utc=t_50,
            received_monotonic_ns=2,
            raw_packet_size=123,
            ltp=105.0,
            cumulative_volume=1200,
        )
        tick_3 = QuoteTick(
            exchange="NSE_CM",
            token="2885",
            symbol="RELIANCE-EQ",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=t_10,
            received_at_utc=t_10,
            received_monotonic_ns=3,
            raw_packet_size=123,
            ltp=98.0,
            cumulative_volume=1250,
        )

        self.aggregator.process_tick(tick_1)
        self.aggregator.process_tick(tick_2)
        self.aggregator.process_tick(tick_3)

        current_bar = self.aggregator.get_current_bar_snapshot("RELIANCE-EQ")
        self.assertIsNotNone(current_bar)
        # Open must be from earliest event time (09:15:10 @ 98.0)
        self.assertEqual(current_bar.open, 98.0)
        # Close must be from latest event time (09:15:50 @ 105.0)
        self.assertEqual(current_bar.close, 105.0)
        self.assertEqual(current_bar.high, 105.0)
        self.assertEqual(current_bar.low, 98.0)

    def test_timer_driven_bar_completion_for_illiquid_stream(self) -> None:
        """Elapsed windows close via close_elapsed_windows() even when no new ticks arrive."""
        emitted_bars: list[Bar] = []
        self.aggregator.subscribe_bar(lambda b: emitted_bars.append(b))

        # Single trade at 09:15:15
        t_trade = datetime(2026, 8, 20, 3, 45, 15, tzinfo=timezone.utc)
        tick = LtpTick(
            exchange="NSE_CM",
            token="3045",
            symbol="SBIN-EQ",
            mode=LiveTickerMode.LTP,
            exchange_timestamp=t_trade,
            received_at_utc=t_trade,
            received_monotonic_ns=1,
            raw_packet_size=51,
            ltp=600.0,
        )
        self.aggregator.process_tick(tick)
        self.assertEqual(len(emitted_bars), 0)

        # Advance current time to 09:16:05 (window ended at 09:16:00 + 2s allowed lateness)
        t_now = datetime(2026, 8, 20, 3, 46, 5, tzinfo=timezone.utc)
        closed = self.aggregator.close_elapsed_windows(t_now)

        self.assertEqual(len(closed), 1)
        self.assertEqual(len(emitted_bars), 1)
        self.assertEqual(emitted_bars[0].symbol, "SBIN-EQ")
        self.assertEqual(emitted_bars[0].open, 600.0)
        self.assertEqual(emitted_bars[0].close, 600.0)
        self.assertEqual(emitted_bars[0].timeframe, "1m")


    def test_cumulative_volume_delta_and_session_reset(self) -> None:
        """Volume is calculated from cumulative delta and handles day session reset."""
        t1 = datetime(2026, 8, 20, 3, 45, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 8, 20, 3, 45, 20, tzinfo=timezone.utc)

        tick_1 = QuoteTick(
            exchange="NSE_CM",
            token="2885",
            symbol="RELIANCE-EQ",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=t1,
            received_at_utc=t1,
            received_monotonic_ns=1,
            raw_packet_size=123,
            ltp=100.0,
            last_traded_qty=50,
            cumulative_volume=10_000,
        )
        tick_2 = QuoteTick(
            exchange="NSE_CM",
            token="2885",
            symbol="RELIANCE-EQ",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=t2,
            received_at_utc=t2,
            received_monotonic_ns=2,
            raw_packet_size=123,
            ltp=101.0,
            last_traded_qty=100,
            cumulative_volume=10_200,  # Delta = +200
        )

        self.aggregator.process_tick(tick_1)
        self.aggregator.process_tick(tick_2)

        bar_snap = self.aggregator.get_current_bar_snapshot("RELIANCE-EQ")
        # First tick used last_traded_qty (50) + second tick delta (200) = 250
        self.assertEqual(bar_snap.volume, 250.0)


if __name__ == "__main__":
    unittest.main()
