"""Feature engineering for systematic trading research."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


from trading_stack.trading_calendar import TradingCalendar


@dataclass(slots=True)
class FeatureFactory:
    """Build common research features from OHLCV bars."""

    short_window: int = 5
    medium_window: int = 20
    long_window: int = 50
    calendar: TradingCalendar = field(default_factory=TradingCalendar)
    exchange: str = "NSE_CM"

    def build(self, bars: pd.DataFrame, timezone_name: str = "UTC") -> pd.DataFrame:
        """Return a feature-rich frame ordered by timestamp."""

        if bars.empty:
            return bars.copy()

        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required.difference(bars.columns)
        if missing:
            raise ValueError(f"Bars are missing columns: {sorted(missing)}")

        frame = bars.copy().sort_values("timestamp").reset_index(drop=True)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        if frame.empty:
            return frame

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        volume = frame["volume"]
        previous_close = close.shift(1)

        frame["return_1"] = close.pct_change().fillna(0.0)
        frame["log_return_1"] = np.log(close / previous_close).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        frame["gap_return"] = ((frame["open"] / previous_close) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        frame["range_pct"] = ((high - low) / close.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        # Use min_periods=window for SMAs used in signal generation to prevent look-ahead bias.
        # Strategies cannot rely on a 200-day MA computed from only 5 days of data.
        frame["sma_short"] = close.rolling(self.short_window, min_periods=self.short_window).mean()
        frame["sma_medium"] = close.rolling(self.medium_window, min_periods=self.medium_window).mean()
        frame["sma_long"] = close.rolling(self.long_window, min_periods=self.long_window).mean()
        frame["ema_fast"] = close.ewm(span=max(self.short_window * 2, 2), adjust=False).mean()
        frame["ema_slow"] = close.ewm(span=max(self.medium_window * 2, 2), adjust=False).mean()
        frame["volatility"] = frame["log_return_1"].rolling(self.medium_window, min_periods=self.medium_window).std().fillna(0.0)

        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        # ATR uses min_periods=1 because it is used for execution sizing and must never be NaN.
        frame["atr"] = true_range.rolling(self.medium_window, min_periods=1).mean()
        frame["trend_strength"] = (close / frame["sma_medium"].replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        frame["price_zscore"] = self._zscore(close, self.medium_window)
        frame["volume_sma"] = volume.rolling(self.medium_window, min_periods=self.medium_window).mean()
        frame["volume_zscore"] = self._zscore(volume, self.medium_window)
        frame["rolling_high"] = high.rolling(self.medium_window, min_periods=self.medium_window).max()
        frame["rolling_low"] = low.rolling(self.medium_window, min_periods=self.medium_window).min()
        frame["session_bar_index"] = self._session_bar_index(frame["timestamp"], timezone_name)
        frame["session_progress"] = self._session_progress(frame["timestamp"], timezone_name)
        frame["feature_available_at"] = frame["timestamp"]
        return frame

    def storeable_features(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return the numeric feature subset suitable for persistence."""

        excluded = {"timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe", "exchange", "asset_class"}
        numeric_columns = [
            column
            for column in frame.columns
            if column not in excluded and pd.api.types.is_numeric_dtype(frame[column])
        ]
        return frame[["timestamp", *numeric_columns]].copy()

    def _zscore(self, series: pd.Series, window: int) -> pd.Series:
        mean = series.rolling(window, min_periods=1).mean()
        std = series.rolling(window, min_periods=1).std(ddof=0).replace(0, np.nan)
        return ((series - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    def _session_bar_index(self, timestamps: pd.Series, timezone_name: str) -> pd.Series:
        localized = pd.to_datetime(timestamps, utc=True).dt.tz_convert(timezone_name)
        session_key = localized.dt.date
        return localized.groupby(session_key).cumcount()

    def _session_progress(self, timestamps: pd.Series, timezone_name: str) -> pd.Series:
        localized = pd.to_datetime(timestamps, utc=True).dt.tz_convert(timezone_name)
        dates = localized.dt.date.unique()
        bounds: dict[Any, tuple[Any, Any]] = {}
        for d in dates:
            open_utc, close_utc = self.calendar.get_session_window(self.exchange, d)
            open_loc = pd.Timestamp(open_utc).tz_convert(timezone_name)
            close_loc = pd.Timestamp(close_utc).tz_convert(timezone_name)
            bounds[d] = (open_loc, close_loc)


        progresses: list[float] = []
        for ts in localized:
            d = ts.date()
            if d in bounds:
                open_t, close_t = bounds[d]
                total_secs = (close_t - open_t).total_seconds()
                if total_secs > 0:
                    if open_t <= ts <= close_t:
                        elapsed = (ts - open_t).total_seconds()
                        progresses.append(min(max(elapsed / total_secs, 0.0), 1.0))
                    else:
                        progresses.append(float("nan"))
                else:
                    progresses.append(0.0)
            else:
                progresses.append(float("nan"))
        return pd.Series(progresses, index=timestamps.index, dtype="float64")

