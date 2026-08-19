"""Unit tests for segment-specific TradingCalendar and session policies."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from trading_stack.trading_calendar import TradingCalendar

IST = ZoneInfo("Asia/Kolkata")


class TestTradingCalendar(unittest.TestCase):
    def setUp(self) -> None:
        self.calendar = TradingCalendar()

    def test_default_segment_session_hours(self) -> None:
        """Verify default session hours for Cash, Derivatives, Currency, and Commodity."""
        # NSE Cash & Derivatives: 09:15 to 15:30 IST
        nse_hours = self.calendar.get_session_hours("NSE_CM")
        self.assertEqual(nse_hours.open_time, time(9, 15))
        self.assertEqual(nse_hours.close_time, time(15, 30))

        # Currency CDS (CDE_FO): 09:00 to 17:00 IST
        cds_hours = self.calendar.get_session_hours("CDE_FO")
        self.assertEqual(cds_hours.open_time, time(9, 0))
        self.assertEqual(cds_hours.close_time, time(17, 0))

        # Commodity MCX: 09:00 to 23:30 IST
        mcx_hours = self.calendar.get_session_hours("MCX_FO")
        self.assertEqual(mcx_hours.open_time, time(9, 0))
        self.assertEqual(mcx_hours.close_time, time(23, 30))

    def test_is_market_open_evaluation(self) -> None:
        # Thursday 2026-08-20 09:30 IST (04:00 UTC) -> Open on NSE Cash & CDS
        dt_0930_ist = datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc)
        self.assertTrue(self.calendar.is_market_open("NSE_CM", dt_0930_ist))
        self.assertTrue(self.calendar.is_market_open("CDE_FO", dt_0930_ist))

        # Thursday 2026-08-20 16:00 IST (10:30 UTC) -> Closed on NSE Cash, Open on CDS & MCX
        dt_1600_ist = datetime(2026, 8, 20, 10, 30, tzinfo=timezone.utc)
        self.assertFalse(self.calendar.is_market_open("NSE_CM", dt_1600_ist))
        self.assertTrue(self.calendar.is_market_open("CDE_FO", dt_1600_ist))
        self.assertTrue(self.calendar.is_market_open("MCX_FO", dt_1600_ist))

        # Weekend check (Saturday 2026-08-22 10:00 IST) -> Closed
        dt_saturday = datetime(2026, 8, 22, 4, 30, tzinfo=timezone.utc)
        self.assertFalse(self.calendar.is_market_open("NSE_CM", dt_saturday))

    def test_session_window_bounds(self) -> None:
        d = date(2026, 8, 20)
        open_utc, close_utc = self.calendar.get_session_window("NSE_CM", d)
        # 09:15 IST = 03:45 UTC
        self.assertEqual(open_utc, datetime(2026, 8, 20, 3, 45, tzinfo=timezone.utc))
        # 15:30 IST = 10:00 UTC
        self.assertEqual(close_utc, datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
