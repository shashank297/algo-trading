"""Market calendar helpers for India, US, forex, and crypto."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from importlib.metadata import version as package_version

import pandas as pd

from trading_stack.domain import AssetClass, MarketSpec, infer_market_spec


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


@dataclass(frozen=True)
class SessionWindow:
    """Concrete trading session boundaries for a calendar date."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class SessionOverride:
    """A versioned exchange closure, special session, or trading interruption."""

    session_date: date
    override_type: str
    reason: str
    start_time: time | None = None
    end_time: time | None = None


@dataclass(frozen=True)
class CalendarValidation:
    """Classified bar/session alignment evidence."""

    valid: bool
    out_of_session_count: int = 0
    missing_session_count: int = 0
    out_of_session: tuple[str, ...] = field(default_factory=tuple)
    missing_sessions: tuple[str, ...] = field(default_factory=tuple)
    expected_interruptions: tuple[str, ...] = field(default_factory=tuple)


class MarketCalendar:
    """Session and holiday logic for one market family."""

    def __init__(
        self,
        spec: MarketSpec,
        *,
        overrides: tuple[SessionOverride, ...] = (),
        version: str = "builtin-v1",
        verified_through: date | None = None,
    ) -> None:
        self.spec = spec
        self.zone = ZoneInfo(spec.timezone)
        self.session_open = _parse_hhmm(spec.session_open)
        self.session_close = _parse_hhmm(spec.session_close)
        self.overrides = overrides
        self.version = version
        self.verified_through = verified_through

    def is_trading_day(self, trading_date: date) -> bool:
        """Return whether the supplied date is a session day."""

        if self._overrides_for(trading_date, "CLOSED"):
            return False
        if self._overrides_for(trading_date, "SPECIAL_SESSION"):
            return True
        if self.spec.asset_class == AssetClass.CRYPTO:
            return True
        if self.spec.asset_class == AssetClass.FOREX:
            return trading_date.weekday() < 5
        return trading_date.weekday() < 5 and trading_date not in self.spec.holidays

    def is_special_session(self, trading_date: date) -> bool:
        """Return whether a date is an explicitly declared non-standard session."""

        return bool(self._overrides_for(trading_date, "SPECIAL_SESSION"))

    def session_bounds(self, trading_date: date) -> SessionWindow:
        """Return the session open and close for a trading date."""

        special = self._overrides_for(trading_date, "SPECIAL_SESSION")
        start_time = special[0].start_time if special and special[0].start_time else self.session_open
        end_time = special[0].end_time if special and special[0].end_time else self.session_close
        start = datetime.combine(trading_date, start_time, tzinfo=self.zone)
        end = datetime.combine(trading_date, end_time, tzinfo=self.zone)
        if self.spec.asset_class == AssetClass.CRYPTO and end <= start:
            end = start + timedelta(days=1) - timedelta(minutes=1)
        return SessionWindow(start=start, end=end)

    def is_session_open(self, timestamp: datetime) -> bool:
        """Return whether a timestamp falls inside the active session."""

        current = self._to_local(timestamp)
        if not self.is_trading_day(current.date()):
            return False
        window = self.session_bounds(current.date())
        return window.start <= current <= window.end

    def iter_trading_days(self, start_date: date, end_date: date) -> list[date]:
        """Return all trading dates in an inclusive range."""

        days: list[date] = []
        current = start_date
        while current <= end_date:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def intraday_session_positions(self, timestamps: pd.Series) -> pd.Series:
        """Return the zero-based bar index within each trading session."""

        local_index = pd.to_datetime(timestamps, utc=True).dt.tz_convert(self.zone)
        session_dates = local_index.dt.date
        return local_index.groupby(session_dates).cumcount()

    def validate_bars(self, timestamps: pd.Series, timeframe: str) -> CalendarValidation:
        """Classify session alignment without treating known interruptions as provider gaps."""

        if timestamps.empty:
            return CalendarValidation(valid=True)
        local = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True)).tz_convert(self.zone).sort_values()
        if self.verified_through and local.max().date() > self.verified_through:
            raise ValueError(
                f"Calendar {self.version} is verified only through {self.verified_through.isoformat()}."
            )
        out_of_session: list[str] = []
        for timestamp in local:
            if timeframe == "1d":
                if not self.is_trading_day(timestamp.date()):
                    out_of_session.append(timestamp.isoformat())
            elif not self.is_session_open(timestamp.to_pydatetime()):
                out_of_session.append(timestamp.isoformat())
        actual_dates = set(local.date)
        expected_dates = self.iter_trading_days(local.min().date(), local.max().date())
        missing_sessions = [value.isoformat() for value in expected_dates if value not in actual_dates]
        interruptions = [
            f"{override.session_date.isoformat()}:{override.start_time}-{override.end_time}:{override.reason}"
            for override in self.overrides
            if override.override_type == "INTERRUPTION" and local.min().date() <= override.session_date <= local.max().date()
        ]
        return CalendarValidation(
            valid=not out_of_session and not missing_sessions,
            out_of_session_count=len(out_of_session),
            missing_session_count=len(missing_sessions),
            out_of_session=tuple(out_of_session[:50]),
            missing_sessions=tuple(missing_sessions[:50]),
            expected_interruptions=tuple(interruptions),
        )

    def expected_minute_index(self, start_date: date, end_date: date) -> pd.DatetimeIndex:
        """Build expected bars while excluding versioned exchange interruptions."""

        ranges: list[pd.DatetimeIndex] = []
        for trading_date in self.iter_trading_days(start_date, end_date):
            bounds = self.session_bounds(trading_date)
            values = pd.date_range(bounds.start, bounds.end - timedelta(minutes=1), freq="min")
            for interruption in self._overrides_for(trading_date, "INTERRUPTION"):
                if interruption.start_time and interruption.end_time:
                    interruption_start = datetime.combine(trading_date, interruption.start_time, tzinfo=self.zone)
                    interruption_end = datetime.combine(trading_date, interruption.end_time, tzinfo=self.zone)
                    values = values[(values < interruption_start) | (values >= interruption_end)]
            ranges.append(values)
        if not ranges:
            return pd.DatetimeIndex([])
        result = ranges[0]
        for values in ranges[1:]:
            result = result.union(values)
        return result

    def _overrides_for(self, trading_date: date, override_type: str) -> list[SessionOverride]:
        return [
            override for override in self.overrides
            if override.session_date == trading_date and override.override_type == override_type
        ]

    def _to_local(self, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=self.zone)
        return timestamp.astimezone(self.zone)


class PandasNSECalendar(MarketCalendar):
    """NSE schedule backed by the maintained pandas-market-calendars package."""

    def __init__(
        self,
        spec: MarketSpec,
        *,
        overrides: tuple[SessionOverride, ...] = (),
        verified_through: date | None = None,
        version: str | None = None,
    ) -> None:
        try:
            import pandas_market_calendars as market_calendars
        except ImportError as exc:
            raise RuntimeError("Production NSE validation requires pandas-market-calendars.") from exc
        super().__init__(
            spec,
            overrides=overrides,
            version=version or f"pandas-market-calendars-{package_version('pandas_market_calendars')}",
            verified_through=verified_through,
        )
        self.provider = market_calendars.get_calendar("NSE")

    def _schedule(self, start_date: date, end_date: date) -> pd.DataFrame:
        return self.provider.schedule(start_date=start_date, end_date=end_date)

    def is_trading_day(self, trading_date: date) -> bool:
        if self._overrides_for(trading_date, "CLOSED"):
            return False
        if self._overrides_for(trading_date, "SPECIAL_SESSION"):
            return True
        return not self._schedule(trading_date, trading_date).empty

    def session_bounds(self, trading_date: date) -> SessionWindow:
        if self._overrides_for(trading_date, "SPECIAL_SESSION"):
            return super().session_bounds(trading_date)
        schedule = self._schedule(trading_date, trading_date)
        if schedule.empty:
            raise ValueError(f"{trading_date.isoformat()} is not an NSE session.")
        row = schedule.iloc[0]
        return SessionWindow(
            start=pd.Timestamp(row["market_open"]).tz_convert(self.zone).to_pydatetime(),
            end=pd.Timestamp(row["market_close"]).tz_convert(self.zone).to_pydatetime(),
        )

    def iter_trading_days(self, start_date: date, end_date: date) -> list[date]:
        schedule = self._schedule(start_date, end_date)
        dates = {pd.Timestamp(value).date() for value in schedule.index}
        dates.update(
            override.session_date for override in self.overrides
            if override.override_type == "SPECIAL_SESSION" and start_date <= override.session_date <= end_date
        )
        dates.difference_update(
            override.session_date for override in self.overrides if override.override_type == "CLOSED"
        )
        return sorted(dates)

    def expected_minute_index(self, start_date: date, end_date: date) -> pd.DatetimeIndex:
        schedule = self._schedule(start_date, end_date)
        ranges: list[pd.DatetimeIndex] = []
        scheduled_dates: set[date] = set()
        for index, row in schedule.iterrows():
            trading_date = pd.Timestamp(index).date()
            scheduled_dates.add(trading_date)
            start = pd.Timestamp(row["market_open"]).tz_convert(self.zone)
            end = pd.Timestamp(row["market_close"]).tz_convert(self.zone)
            values = pd.date_range(start, end - timedelta(minutes=1), freq="min")
            for interruption in self._overrides_for(trading_date, "INTERRUPTION"):
                if interruption.start_time and interruption.end_time:
                    interruption_start = datetime.combine(trading_date, interruption.start_time, tzinfo=self.zone)
                    interruption_end = datetime.combine(trading_date, interruption.end_time, tzinfo=self.zone)
                    values = values[(values < interruption_start) | (values >= interruption_end)]
            ranges.append(values)
        for override in self.overrides:
            if (
                override.override_type == "SPECIAL_SESSION"
                and start_date <= override.session_date <= end_date
                and override.session_date not in scheduled_dates
            ):
                bounds = super().session_bounds(override.session_date)
                ranges.append(pd.date_range(bounds.start, bounds.end - timedelta(minutes=1), freq="min"))
        if not ranges:
            return pd.DatetimeIndex([])
        result = ranges[0]
        for values in ranges[1:]:
            result = result.union(values)
        return result

    def validate_bars(self, timestamps: pd.Series, timeframe: str) -> CalendarValidation:
        if timestamps.empty:
            return CalendarValidation(valid=True)
        local = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True)).tz_convert(self.zone).sort_values()
        if self.verified_through and local.max().date() > self.verified_through:
            raise ValueError(
                f"Calendar {self.version} is verified only through {self.verified_through.isoformat()}."
            )
        schedule = self._schedule(local.min().date(), local.max().date())
        bounds = {
            pd.Timestamp(index).date(): (
                pd.Timestamp(row["market_open"]).tz_convert(self.zone),
                pd.Timestamp(row["market_close"]).tz_convert(self.zone),
            )
            for index, row in schedule.iterrows()
        }
        for override in self.overrides:
            if override.override_type == "SPECIAL_SESSION":
                special = super().session_bounds(override.session_date)
                bounds[override.session_date] = (pd.Timestamp(special.start), pd.Timestamp(special.end))
            elif override.override_type == "CLOSED":
                bounds.pop(override.session_date, None)
        out_of_session = []
        for timestamp in local:
            session = bounds.get(timestamp.date())
            valid = session is not None and (
                timeframe == "1d" or session[0] <= timestamp <= session[1]
            )
            if not valid:
                out_of_session.append(timestamp.isoformat())
        actual_dates = set(local.date)
        missing_sessions = [value.isoformat() for value in sorted(bounds) if value not in actual_dates]
        interruptions = [
            f"{override.session_date.isoformat()}:{override.start_time}-{override.end_time}:{override.reason}"
            for override in self.overrides
            if override.override_type == "INTERRUPTION" and local.min().date() <= override.session_date <= local.max().date()
        ]
        return CalendarValidation(
            valid=not out_of_session and not missing_sessions,
            out_of_session_count=len(out_of_session),
            missing_session_count=len(missing_sessions),
            out_of_session=tuple(out_of_session[:50]),
            missing_sessions=tuple(missing_sessions[:50]),
            expected_interruptions=tuple(interruptions),
        )


def build_nse_calendar(
    *,
    overrides: tuple[SessionOverride, ...] = (),
    verified_through: date | None = None,
    version: str | None = None,
) -> MarketCalendar:
    """Build the production NSE calendar and fail if its maintained dependency is absent."""

    return PandasNSECalendar(
        infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY"),
        overrides=overrides,
        verified_through=verified_through,
        version=version,
    )


def build_default_calendars(
    india_holidays: set[date] | None = None,
    us_holidays: set[date] | None = None,
) -> dict[AssetClass, MarketCalendar]:
    """Create market calendars for the supported asset classes."""

    return {
        AssetClass.INDIA_EQUITY: build_nse_calendar(overrides=tuple(
            SessionOverride(value, "CLOSED", "caller-supplied holiday")
            for value in (india_holidays or set())
        )),
        AssetClass.INDIA_INDEX: MarketCalendar(
            infer_market_spec("INDIA_INDEX", "NSE", "INDEX", holidays=india_holidays)
        ),
        AssetClass.US_EQUITY: MarketCalendar(
            infer_market_spec("US_EQUITY", "NYSE", "EQUITY", holidays=us_holidays)
        ),
        AssetClass.FOREX: MarketCalendar(infer_market_spec("FOREX", "FOREX", "FX")),
        AssetClass.CRYPTO: MarketCalendar(infer_market_spec("CRYPTO", "CRYPTO", "CRYPTO")),
    }
