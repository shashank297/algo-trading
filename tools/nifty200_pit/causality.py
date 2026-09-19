"""Conservative announcement-to-knowledge-time policy."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

MARKET_TZ = ZoneInfo("Asia/Kolkata")


def next_trading_session_open(
    announcement_date: date,
    *,
    holidays: set[date] | None = None,
    open_time: time = time(9, 15),
    calendar: Any | None = None,
) -> datetime:
    """Return the first actual exchange session open after publication date."""
    excluded = holidays or set()
    candidate = announcement_date + timedelta(days=1)
    while candidate in excluded or (
        calendar is None and candidate.weekday() >= 5
    ) or (calendar is not None and not calendar.is_trading_day(candidate)):
        candidate += timedelta(days=1)
    if calendar is not None:
        return calendar.session_bounds(candidate).start
    return datetime.combine(candidate, open_time, tzinfo=MARKET_TZ)


def derive_known_at(
    announcement_date: date,
    *,
    exact_timestamp: datetime | None = None,
    effective_date: date | None = None,
    holidays: set[date] | None = None,
    calendar: Any | None = None,
) -> tuple[datetime | None, str, str | None]:
    """Return ``(known_at, basis, review_reason)`` without inventing precision."""
    if exact_timestamp is not None:
        timestamp = exact_timestamp if exact_timestamp.tzinfo else exact_timestamp.replace(tzinfo=MARKET_TZ)
        return timestamp.astimezone(MARKET_TZ), "EXACT_SOURCE_TIMESTAMP", None
    if effective_date == announcement_date:
        return None, "DATE_ONLY_SAME_DAY_REVIEW", "same_day_effective_date_without_source_time"
    return (
        next_trading_session_open(announcement_date, holidays=holidays, calendar=calendar),
        "DATE_ONLY_CONSERVATIVE_NEXT_SESSION",
        None,
    )
