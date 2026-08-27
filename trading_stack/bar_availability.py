"""Authoritative availability timestamps for completed market bars."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from trading_stack.calendars import MarketCalendar


IST = ZoneInfo("Asia/Kolkata")
_INTRADAY_DURATIONS = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "60m": timedelta(minutes=60),
}


def bar_available_at(timestamp: datetime, timeframe: str, calendar: MarketCalendar) -> datetime:
    """Return when an opening-timestamp OHLCV bar is usable."""
    timestamp = timestamp.replace(tzinfo=IST) if timestamp.tzinfo is None else timestamp.astimezone(IST)
    if timeframe in _INTRADAY_DURATIONS:
        return timestamp + _INTRADAY_DURATIONS[timeframe]
    if timeframe == "1d":
        try:
            return calendar.session_bounds(timestamp.date()).end
        except ValueError:
            # Data outside a configured exchange schedule is still governed by its
            # explicit source timestamp; callers may separately reject it by DQ.
            return timestamp
    raise ValueError(f"Unsupported regime timeframe: {timeframe}")


def is_bar_available(timestamp: datetime, timeframe: str, decision_time: datetime, calendar: MarketCalendar) -> bool:
    """Return whether a completed bar can causally inform a decision."""
    decision_time = decision_time.replace(tzinfo=IST) if decision_time.tzinfo is None else decision_time.astimezone(IST)
    return bar_available_at(timestamp, timeframe, calendar) <= decision_time
