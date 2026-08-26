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

        # Active windows buffer: (symbol, window_start) -> dict
        self._active_windows: dict[tuple[str, pd.Timestamp], dict[str, Any]] = {}
        # Max event time seen per symbol
        self._max_event_time_seen: dict[str, datetime] = {}
        # Count of dropped late ticks
        self._dropped_late_ticks_count: int = 0
        # Prior cumulative volume per symbol: symbol -> last_day_volume
        self._last_day_volumes: dict[str, int] = {}
        # Completed bar history / deduplication
        self._closed_windows: set[tuple[str, pd.Timestamp]] = set()
        # Thread-safe canonical gap projection: symbol -> (gap_id, start_time, end_time).
        self._untrusted_windows: dict[str, list[tuple[str, datetime, datetime | None]]] = {}

    def mark_untrusted(
        self, gap_id: str, symbol: str | datetime, start_time: datetime | None = None, end_time: datetime | None = None,
    ) -> None:
        """Flag an interval for a symbol as degraded/untrusted due to stream sequence gaps."""
        if isinstance(symbol, datetime):
            # Compatibility projection for old diagnostic callers; production callbacks
            # always provide the canonical gap ID explicitly.
            legacy_symbol = gap_id
            gap_id = f"legacy:{legacy_symbol}:{symbol.isoformat()}"
            end_time = start_time
            start_time = symbol
            symbol = legacy_symbol
        if start_time is None:
            raise ValueError("Untrusted interval requires a start timestamp.")
        with self._lock:
            intervals = self._untrusted_windows.setdefault(symbol, [])
            if any(existing_id == gap_id for existing_id, _, _ in intervals):
                return
            intervals.append((gap_id, start_time, end_time))

    def close_degraded_interval(self, gap_id: str, reanchor_time: datetime) -> None:
        """Close exactly one persisted gap interval at its authoritative re-anchor time."""
        with self._lock:
            for symbol, intervals in self._untrusted_windows.items():
                for index, (existing_id, start_time, end_time) in enumerate(intervals):
                    if existing_id == gap_id:
                        intervals[index] = (existing_id, start_time, end_time or reanchor_time)
                        return
            # Legacy diagnostics addressed intervals by symbol. This compatibility
            # path is intentionally not used by live lifecycle callbacks.
            if gap_id in self._untrusted_windows:
                intervals = self._untrusted_windows[gap_id]
                self._untrusted_windows[gap_id] = [
                    (existing_id, start_time, end_time or reanchor_time)
                    for existing_id, start_time, end_time in intervals
                ]
                return
            raise KeyError(f"Unknown canonical stream gap {gap_id}.")

    def repair_gap(self, gap_id: str, from_time: datetime | None = None, to_time: datetime | None = None) -> None:
        """Remove or resolve historical untrusted interval upon verified backfill."""
        with self._lock:
            for symbol, intervals in list(self._untrusted_windows.items()):
                updated = [interval for interval in intervals if interval[0] != gap_id]
                if len(updated) != len(intervals):
                    if updated:
                        self._untrusted_windows[symbol] = updated
                    else:
                        del self._untrusted_windows[symbol]
                    return
            if from_time is not None and gap_id in self._untrusted_windows:
                self._untrusted_windows[gap_id] = [
                    (existing_id, start_time, end_time)
                    for existing_id, start_time, end_time in self._untrusted_windows[gap_id]
                    if not (start_time == from_time and (to_time is None or end_time == to_time or end_time is None))
                ]
                if not self._untrusted_windows[gap_id]:
                    del self._untrusted_windows[gap_id]
                return
            raise KeyError(f"Unknown canonical stream gap {gap_id}.")

    def load_unresolved_gaps(self, db: Any) -> None:
        """Reload unrepaired stream gaps from DuckDB into untrusted window registry."""
        with self._lock:
            self._untrusted_windows.clear()
            rows = db.load_unrepaired_stream_gaps()
            for gap_id, sym, start_time, end_time in rows:
                self._untrusted_windows.setdefault(sym, []).append((gap_id, start_time, end_time))
            logger.info("Loaded {} canonical unrepaired stream gaps into aggregator.", len(rows))

    @property
    def _open_bars(self) -> dict[str, dict[str, Any]]:
        """Convenience map of symbol -> latest active window state."""
        result: dict[str, dict[str, Any]] = {}
        for (sym, _), state in sorted(self._active_windows.items(), key=lambda x: x[0][1]):
            result[sym] = state
        return result

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

            # Update event time watermark
            event_dt = pd.Timestamp(event_time).to_pydatetime()
            if sym not in self._max_event_time_seen or event_dt > self._max_event_time_seen[sym]:
                self._max_event_time_seen[sym] = event_dt

            watermark = self._max_event_time_seen[sym] - self.allowed_lateness
            window_key = (sym, window_start)

            # Check if this tick is for an already closed window (late arrival after finalization)
            if window_key in self._closed_windows:
                self._dropped_late_ticks_count += 1
            else:
                # Buffer tick into active window
                if window_key not in self._active_windows:
                    self._active_windows[window_key] = {
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
                    open_bar = self._active_windows[window_key]
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

            # Finalize any active windows for this symbol where window_end <= watermark
            windows_to_close = []
            for (s, ws), state in list(self._active_windows.items()):
                if s == sym:
                    w_end_dt = state["window_end"].to_pydatetime()
                    if watermark >= w_end_dt:
                        windows_to_close.append((s, ws))

            for w_key in windows_to_close:
                state = self._active_windows.pop(w_key)
                bar = self._build_bar(state, is_final=True)
                completed_bars.append(bar)
                self._closed_windows.add(w_key)
                if len(self._closed_windows) > 10_000:
                    self._closed_windows = set(list(self._closed_windows)[-5000:])

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
            windows_to_close = []
            for w_key, state in list(self._active_windows.items()):
                w_end_dt = state["window_end"].to_pydatetime()
                if (now - self.allowed_lateness) >= w_end_dt:
                    windows_to_close.append(w_key)

            for w_key in windows_to_close:
                state = self._active_windows.pop(w_key)
                bar = self._build_bar(state, is_final=True)
                completed_bars.append(bar)
                self._closed_windows.add(w_key)

        if completed_bars:
            self._dispatch_bars(completed_bars)

        return completed_bars

    def get_current_bar_snapshot(self, symbol: str) -> Bar | None:
        """Get the current in-progress (non-final) bar for a symbol."""
        with self._lock:
            # Return newest active window for symbol
            symbol_windows = [
                state for (sym, _), state in self._active_windows.items() if sym == symbol
            ]
            if not symbol_windows:
                return None
            latest_state = max(symbol_windows, key=lambda s: s["window_start"])
            return self._build_bar(latest_state, is_final=False)

    def _build_bar(self, state: dict[str, Any], is_final: bool) -> Bar:
        """Construct a validated Bar domain object from internal state."""
        symbol = state["symbol"]
        exchange = state.get("exchange", "NSE_CM")
        spec = infer_market_spec(symbol, exchange, self.default_asset_class)
        vol = state["volume"] if state["has_volume"] else 0.0

        w_start = state["window_start"].to_pydatetime()
        w_end = state["window_end"].to_pydatetime()
        is_authoritative = True
        quality_status = "TRUSTED"

        for _, gap_start, gap_end in self._untrusted_windows.get(symbol, []):
            if gap_start < w_end and (gap_end is None or gap_end > w_start):
                is_authoritative = False
                quality_status = "UNTRUSTED"
                break

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
            is_authoritative=is_authoritative,
            quality_status=quality_status,
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
