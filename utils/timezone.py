"""Timezone and market-hours helpers for Indian market data."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_TIME = time(hour=9, minute=15)
MARKET_CLOSE_TIME = time(hour=15, minute=30)


def get_ist_now() -> datetime:
    """Return the current timezone-aware IST datetime."""

    return datetime.now(tz=IST)


def to_ist(dt: datetime) -> datetime:
    """Convert a datetime to IST.

    Args:
        dt: Source datetime. Naive datetimes are assumed to be UTC.

    Returns:
        datetime: Timezone-aware datetime in IST.
    """

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def is_market_open() -> bool:
    """Return whether the Indian cash market is currently open."""

    current_time = get_ist_now()
    if current_time.weekday() >= 5:
        return False
    market_open = datetime.combine(current_time.date(), MARKET_OPEN_TIME, tzinfo=IST)
    market_close = datetime.combine(current_time.date(), MARKET_CLOSE_TIME, tzinfo=IST)
    return market_open <= current_time <= market_close


def get_date_chunks(
    from_date: date,
    to_date: date,
    chunk_days: int,
) -> list[tuple[date, date]]:
    """Split an inclusive date range into smaller inclusive chunks.

    Args:
        from_date: Start date for the overall range.
        to_date: End date for the overall range.
        chunk_days: Maximum day span per chunk.

    Returns:
        list[tuple[date, date]]: Inclusive date chunks.
    """

    if chunk_days <= 0:
        raise ValueError("chunk_days must be greater than zero.")
    if from_date > to_date:
        return []

    chunks: list[tuple[date, date]] = []
    current_start = from_date

    while current_start <= to_date:
        current_end = min(current_start + timedelta(days=chunk_days - 1), to_date)
        chunks.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)

    return chunks
