"""Event-time tick-to-bar aggregator with timer-driven window completion and watermark lateness handling."""

from __future__ import annotations

import threading
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Callable

import pandas as pd
from loguru import logger

from data_platform.contracts import (
    LtpTick,
    MarketDataEvent,
    QuoteTick,
    SnapQuoteTick,
)
from data_platform.live_admission import EventTimePolicy
from trading_stack.calendars import MarketCalendar, build_nse_calendar
from trading_stack.domain import AssetClass, Bar, infer_market_spec
from trading_stack.trading_calendar import TradingCalendar

TIMEFRAME_SECONDS: dict[str, int] = {
    "1s": 1,
    "5s": 5,
    "10s": 10,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "1d": 86400,
}


def _floor_timestamp_to_window(dt: datetime, timeframe: str) -> pd.Timestamp:
    """Align a datetime to the start boundary of its timeframe candle window."""
    tf = timeframe.lower()
    if tf == "1d":
        # Align daily bars to the start of the NSE trading session (09:15 IST)
        local_dt = pd.Timestamp(dt).tz_convert("Asia/Kolkata") if getattr(dt, "tzinfo", None) else pd.Timestamp(dt, tz="Asia/Kolkata")
        session_start = datetime.combine(local_dt.date(), time(9, 15), tzinfo=ZoneInfo("Asia/Kolkata"))
        return pd.Timestamp(session_start.astimezone(timezone.utc))
    secs = TIMEFRAME_SECONDS.get(tf, 60)
    epoch_secs = int(dt.timestamp())
    window_start_secs = (epoch_secs // secs) * secs
    return pd.Timestamp(datetime.fromtimestamp(window_start_secs, tz=timezone.utc))


class RealtimeBarAggregator:
    """Aggregate sub-second live ticks into deterministic OHLCV candles using event-time semantics."""

    def __init__(
        self,
        timeframe: str = "1m",
        default_asset_class: AssetClass = AssetClass.INDIA_EQUITY,
        allowed_lateness_seconds: float = 2.0,
        calendar: TradingCalendar | None = None,
        event_time_policy: EventTimePolicy | None = None,
        market_calendar: MarketCalendar | None = None,
    ) -> None:
        """Initialize the event-time bar aggregator.

        Args:
            timeframe: Aggregation candle interval ('1s', '1m', '5m', '15m', etc.).
            default_asset_class: Market family if not inferred.
            allowed_lateness_seconds: Grace period in seconds for out-of-order ticks before window closure.
            calendar: TradingCalendar instance for session boundaries.
            event_time_policy: Shared institutional EventTimePolicy instance.
            market_calendar: MarketCalendar instance for trading session boundaries.
        """
        self.timeframe = timeframe.lower()
        self.interval_seconds = TIMEFRAME_SECONDS.get(self.timeframe, 60)
        self.default_asset_class = default_asset_class
        lateness_sec = (
            event_time_policy.bar_finalization_lateness_seconds
            if event_time_policy is not None
            else allowed_lateness_seconds
        )
        self.allowed_lateness = timedelta(seconds=lateness_sec)
        self.calendar = calendar or TradingCalendar()
        self.market_calendar = market_calendar or build_nse_calendar()

        self._lock = threading.Lock()
        self._bar_subscribers: list[Callable[[Bar], None]] = []

        # Current open bar state per symbol: symbol -> dict
        self._open_bars: dict[str, dict[str, Any]] = {}
        # Prior cumulative volume per symbol: symbol -> last_day_volume
        self._last_day_volumes: dict[str, int] = {}
        # Completed bar history / deduplication
        self._closed_windows: set[tuple[str, pd.Timestamp]] = set()

    def subscribe_bar(self, callback: Callable[[Bar], None]) -> None:
        """Register a callback for completed Bar events."""
        with self._lock:
            if callback not in self._bar_subscribers:
                self._bar_subscribers.append(callback)

    def process_tick(self, tick: MarketDataEvent) -> list[Bar]:
        """Process an incoming tick, update active bar, and return newly closed bars.

        Args:
            tick: Live streaming tick from WebSocket.

        Returns:
            list[Bar]: Completed bars triggered by this tick.
        """
        completed_bars: list[Bar] = []
        sym = tick.symbol or tick.token
        exchange = tick.exchange

        price = getattr(tick, "ltp", 0.0)
        if price <= 0:
            return []

        # Use exchange timestamp if available, else arrival time
        event_time = tick.exchange_timestamp or tick.received_at_utc
        window_start = _floor_timestamp_to_window(event_time, self.timeframe)
        window_end = window_start + pd.Timedelta(seconds=self.interval_seconds)

        with self._lock:
            open_bar = self._open_bars.get(sym)

            # Calculate volume delta from cumulative volume
            tick_volume: float | None = None
            if isinstance(tick, (QuoteTick, SnapQuoteTick)):
                cum_vol = tick.cumulative_volume
                last_vol = self._last_day_volumes.get(sym)
                current_date = event_time.date() if hasattr(event_time, "date") else None
                last_date = getattr(self, "_session_dates", {}).get(sym)

                if not hasattr(self, "_session_dates"):
                    self._session_dates = {}

                if last_date is not None and current_date != last_date:
                    # Legitimate overnight session rollover
                    self._session_dates[sym] = current_date
                    self._last_day_volumes[sym] = cum_vol
                    tick_volume = float(tick.last_traded_qty) if tick.last_traded_qty > 0 else 0.0
                elif last_vol is not None:
                    if cum_vol >= last_vol:
                        tick_volume = float(cum_vol - last_vol)
                        self._last_day_volumes[sym] = cum_vol
                    else:
                        # Out-of-order / late earlier tick: DO NOT regress baseline
                        tick_volume = 0.0
                else:
                    self._session_dates[sym] = current_date
                    self._last_day_volumes[sym] = cum_vol
                    tick_volume = float(tick.last_traded_qty) if tick.last_traded_qty > 0 else 0.0
            elif isinstance(tick, LtpTick):
                tick_volume = None


            # If tick belongs to a strictly NEWER window, finalize the open older bar if lateness period elapsed
            if open_bar is not None and window_start > open_bar["window_start"]:
                if (sym, open_bar["window_start"]) not in self._closed_windows:
                    bar = self._build_bar(open_bar, is_final=True)
                    completed_bars.append(bar)
                    self._closed_windows.add((sym, open_bar["window_start"]))
                    if len(self._closed_windows) > 10_000:
                        self._closed_windows = set(list(self._closed_windows)[-5000:])
                open_bar = None
                self._open_bars.pop(sym, None)

            # Check if this tick is too late for a closed window
            if (sym, window_start) not in self._closed_windows:
                # If tick belongs to an older window while a newer open_bar exists, do not finalize current bar
                if open_bar is not None and window_start < open_bar["window_start"]:
                    pass
                elif open_bar is None:
                    self._open_bars[sym] = {
                        "symbol": sym,
                        "exchange": exchange,
                        "window_start": window_start,
                        "window_end": window_end,
                        "earliest_event_time": event_time,
                        "latest_event_time": event_time,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": tick_volume or 0.0,
                        "has_volume": tick_volume is not None,
                        "turnover": (price * tick_volume) if tick_volume is not None else 0.0,
                        "tick_count": 1,
                    }

                else:
                    # Update event-time open/close
                    if event_time < open_bar["earliest_event_time"]:
                        open_bar["open"] = price
                        open_bar["earliest_event_time"] = event_time
                    if event_time >= open_bar["latest_event_time"]:
                        open_bar["close"] = price
                        open_bar["latest_event_time"] = event_time

                    open_bar["high"] = max(open_bar["high"], price)
                    open_bar["low"] = min(open_bar["low"], price)
                    if tick_volume is not None:
                        open_bar["volume"] += tick_volume
                        open_bar["turnover"] += price * tick_volume
                        open_bar["has_volume"] = True
                    open_bar["tick_count"] += 1

        # Dispatch completed bars outside the lock
        if completed_bars:
            self._dispatch_bars(completed_bars)

        return completed_bars


    def close_elapsed_windows(self, current_time: datetime | None = None) -> list[Bar]:
        """Timer-driven window closure for elapsed intervals (even when no new ticks arrive).

        Args:
            current_time: Current UTC reference time.

        Returns:
            list[Bar]: Closed bars emitted by this check.
        """
        now = current_time or datetime.now(timezone.utc)
        completed_bars: list[Bar] = []

        with self._lock:
            symbols_to_close: list[str] = []
            for sym, bar_state in self._open_bars.items():
                window_end_dt = bar_state["window_end"].to_pydatetime()
                if now >= window_end_dt + self.allowed_lateness:
                    if (sym, bar_state["window_start"]) not in self._closed_windows:
                        bar = self._build_bar(bar_state, is_final=True)
                        completed_bars.append(bar)
                        self._closed_windows.add((sym, bar_state["window_start"]))
                    symbols_to_close.append(sym)

            for sym in symbols_to_close:
                self._open_bars.pop(sym, None)

        if completed_bars:
            self._dispatch_bars(completed_bars)

        return completed_bars

    def get_current_bar_snapshot(self, symbol: str) -> Bar | None:
        """Get the current in-progress (non-final) bar for a symbol."""
        with self._lock:
            bar_state = self._open_bars.get(symbol)
            if bar_state is None:
                return None
            return self._build_bar(bar_state, is_final=False)

    def _build_bar(self, state: dict[str, Any], is_final: bool) -> Bar:
        """Construct a validated Bar domain object from internal state."""
        symbol = state["symbol"]
        exchange = state.get("exchange", "NSE_CM")
        spec = infer_market_spec(symbol, exchange, self.default_asset_class)
        vol = state["volume"] if state["has_volume"] else 0.0

        return Bar(
            timestamp=state["window_start"],
            open=state["open"],
            high=state["high"],
            low=state["low"],
            close=state["close"],
            volume=vol,
            symbol=symbol,
            timeframe=self.timeframe,
            exchange=exchange,
            asset_class=spec.asset_class,
        )


    def _dispatch_bars(self, bars: list[Bar]) -> None:
        """Notify all registered bar listeners with exception isolation."""
        with self._lock:
            subscribers_snapshot = list(self._bar_subscribers)

        for bar in bars:
            for cb in subscribers_snapshot:
                try:
                    cb(bar)
                except Exception as exc:
                    logger.exception("Error in Bar subscriber callback: {}", exc)
