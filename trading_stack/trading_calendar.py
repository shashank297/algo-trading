"""Exchange segment trading hours and calendar policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class SegmentSessionHours:
    """Trading session start and end times in Asia/Kolkata timezone."""

    open_time: time
    close_time: time


class TradingCalendar:
    """Segment-specific trading session policies."""

    DEFAULT_SESSIONS: dict[str, SegmentSessionHours] = {
        "NSE_CM": SegmentSessionHours(time(9, 15), time(15, 30)),
        "BSE_CM": SegmentSessionHours(time(9, 15), time(15, 30)),
        "NSE": SegmentSessionHours(time(9, 15), time(15, 30)),
        "BSE": SegmentSessionHours(time(9, 15), time(15, 30)),
        "NSE_FO": SegmentSessionHours(time(9, 15), time(15, 30)),
        "BSE_FO": SegmentSessionHours(time(9, 15), time(15, 30)),
        "NFO": SegmentSessionHours(time(9, 15), time(15, 30)),
        "BFO": SegmentSessionHours(time(9, 15), time(15, 30)),
        "CDE_FO": SegmentSessionHours(time(9, 0), time(17, 0)),
        "CDS": SegmentSessionHours(time(9, 0), time(17, 0)),
        "MCX_FO": SegmentSessionHours(time(9, 0), time(23, 30)),
        "MCX": SegmentSessionHours(time(9, 0), time(23, 30)),
        "NCX_FO": SegmentSessionHours(time(9, 0), time(17, 0)),
        "NCDEX": SegmentSessionHours(time(9, 0), time(17, 0)),
    }

    def __init__(self, overrides: dict[str, SegmentSessionHours] | None = None) -> None:
        self._sessions = dict(self.DEFAULT_SESSIONS)
        if overrides:
            self._sessions.update(overrides)

    def get_session_hours(self, exchange: str) -> SegmentSessionHours:
        """Return opening and closing times for an exchange segment."""
        norm = exchange.upper().strip()
        return self._sessions.get(norm, SegmentSessionHours(time(9, 15), time(15, 30)))

    def get_session_window(self, exchange: str, session_date: date) -> tuple[datetime, datetime]:
        """Return localized start and end datetime bounds for a trading session.

        Args:
            exchange: Exchange segment name.
            session_date: Calendar session date.

        Returns:
            tuple[datetime, datetime]: (session_open_utc, session_close_utc)
        """
        hours = self.get_session_hours(exchange)
        start_ist = datetime.combine(session_date, hours.open_time, tzinfo=IST)
        end_ist = datetime.combine(session_date, hours.close_time, tzinfo=IST)
        return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)

    def is_market_open(self, exchange: str, dt_utc: datetime) -> bool:
        """Check whether a given UTC datetime falls within active market hours."""
        dt_ist = dt_utc.astimezone(IST)
        session_d = dt_ist.date()
        # Weekend check
        if session_d.weekday() >= 5:
            return False
        hours = self.get_session_hours(exchange)
        current_time = dt_ist.time()
        return hours.open_time <= current_time <= hours.close_time
