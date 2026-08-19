"""Historical candle data quality validation."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from utils.timezone import IST, get_ist_now
from validators.severity import summarize_quality


class DataValidator:
    """Run a fixed set of quality checks against historical candle data."""

    def __init__(
        self,
        timeframe: str,
        market_open: time = time(hour=9, minute=15),
        market_close: time = time(hour=15, minute=30),
        market_holidays: set[date] | None = None,
    ) -> None:
        """Initialize the validator for a timeframe label.

        Args:
            timeframe: Local timeframe label such as 1m or 1d.
        """

        self.timeframe = timeframe
        self.market_open = market_open
        self.market_close = market_close
        self.market_holidays = market_holidays or set()

    def run_all_checks(self, df: pd.DataFrame, symbol: str) -> dict[str, Any]:
        """Run all configured quality checks and return a structured report.

        Args:
            df: Historical candle DataFrame.
            symbol: Trading symbol being validated.

        Returns:
            dict[str, Any]: Structured data-quality report.
        """

        normalized_df = df.copy()
        if not normalized_df.empty:
            normalized_df["timestamp"] = pd.to_datetime(normalized_df["timestamp"], utc=True).dt.tz_convert(IST)

        checks = {
            "missing_candles": self.check_missing_candles(normalized_df),
            "duplicates": self.check_duplicates(normalized_df),
            "future_timestamps": self.check_future_timestamps(normalized_df),
            "null_values": self.check_null_values(normalized_df),
            "ohlc_integrity": self.check_ohlc_integrity(normalized_df),
            "anomalies": self.check_anomalies(normalized_df),
        }
        summary = summarize_quality(checks)

        return {
            "symbol": symbol,
            "timeframe": self.timeframe,
            "total_candles": int(len(normalized_df)),
            "checks": checks,
            **summary,
            "checked_at": get_ist_now(),
        }

    def check_missing_candles(self, df: pd.DataFrame) -> dict[str, Any]:
        """Detect missing timestamps for the configured timeframe."""

        if df.empty:
            return {"count": 0, "gaps": []}

        actual_timestamps = pd.DatetimeIndex(df["timestamp"]).sort_values()
        missing_values: list[str]

        if self.timeframe == "1m":
            expected_index = self._build_expected_minute_index(actual_timestamps.min(), actual_timestamps.max())
            missing_index = expected_index.difference(actual_timestamps)
            missing_values = [timestamp.isoformat() for timestamp in missing_index[:50]]
            missing_count = len(missing_index)
        elif self.timeframe == "1d":
            actual_dates = pd.Index(actual_timestamps.normalize().date)
            expected_dates = []
            for current_date in pd.date_range(actual_timestamps.min().date(), actual_timestamps.max().date(), freq="D"):
                if current_date.weekday() < 5 and current_date.date() not in self.market_holidays:
                    expected_dates.append(current_date.date())
            actual_date_set = set(actual_dates)
            missing_dates = [
                d for d in expected_dates if d not in actual_date_set
            ]
            missing_values = [missing_date.isoformat() for missing_date in missing_dates[:50]]
            missing_count = len(missing_dates)
        else:
            missing_values = []
            missing_count = 0

        return {"count": missing_count, "gaps": missing_values}

    def check_duplicates(self, df: pd.DataFrame) -> dict[str, Any]:
        """Find duplicate timestamps."""

        if df.empty:
            return {"count": 0, "timestamps": []}

        duplicate_mask = df["timestamp"].duplicated(keep=False)
        duplicates = (
            df.loc[duplicate_mask, "timestamp"]
            .drop_duplicates()
            .sort_values()
            .astype(str)
            .tolist()
        )
        return {"count": len(duplicates), "timestamps": duplicates[:50]}

    def check_future_timestamps(self, df: pd.DataFrame) -> dict[str, Any]:
        """Detect candles whose timestamps are in the future."""

        if df.empty:
            return {"count": 0, "timestamps": []}

        future_rows = df.loc[df["timestamp"] > get_ist_now(), "timestamp"].sort_values()
        future_values = [timestamp.isoformat() for timestamp in future_rows[:50]]
        return {"count": len(future_rows), "timestamps": future_values}

    def check_null_values(self, df: pd.DataFrame) -> dict[str, Any]:
        """Count null values across OHLCV columns."""

        columns = ["open", "high", "low", "close", "volume"]
        column_counts = {column: int(df[column].isna().sum()) if column in df.columns else 0 for column in columns}
        return {"count": sum(column_counts.values()), "columns": column_counts}

    def check_ohlc_integrity(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate core OHLCV integrity rules for each row."""

        if df.empty:
            return {"count": 0, "details": []}

        # Vectorized check for violations
        mask = (
            (df["high"] < df[["open", "close"]].max(axis=1)) |
            (df["low"] > df[["open", "close"]].min(axis=1)) |
            (df["high"] < df["low"]) |
            (df["volume"] < 0) |
            (df["open"] <= 0)
        )
        failed_rows_df = df[mask].copy()

        failed_rows: list[dict[str, Any]] = []
        for row in failed_rows_df.itertuples(index=False):
            row_failures: list[str] = []
            if row.high < row.open:
                row_failures.append("high < open")
            if row.high < row.close:
                row_failures.append("high < close")
            if row.low > row.open:
                row_failures.append("low > open")
            if row.low > row.close:
                row_failures.append("low > close")
            if row.high < row.low:
                row_failures.append("high < low")
            if row.volume < 0:
                row_failures.append("volume < 0")
            if row.open <= 0:
                row_failures.append("open <= 0")
            if row_failures:
                failed_rows.append(
                    {
                        "timestamp": pd.Timestamp(row.timestamp).isoformat(),
                        "issues": row_failures,
                    },
                )

        return {"count": len(failed_rows), "details": failed_rows[:50]}

    def check_anomalies(self, df: pd.DataFrame) -> dict[str, Any]:
        """Detect statistical anomalies like volume spikes or price jumps."""

        if len(df) < 20:
            return {"count": 0, "details": []}

        anomalies_df = df.sort_values("timestamp").copy()
        
        # 1. Volume spikes: volume > 10 * 20-period moving average
        anomalies_df["vol_ma"] = anomalies_df["volume"].rolling(20, min_periods=5).mean()
        vol_mask = (anomalies_df["volume"] > 10 * anomalies_df["vol_ma"]) & (anomalies_df["volume"] > 1000)
        
        # 2. Price gaps: gap between previous close and current open/close > 20%
        anomalies_df["prev_close"] = anomalies_df["close"].shift(1)
        price_mask = (anomalies_df["prev_close"] > 0) & (
            (abs(anomalies_df["open"] - anomalies_df["prev_close"]) / anomalies_df["prev_close"] > 0.20) |
            (abs(anomalies_df["close"] - anomalies_df["prev_close"]) / anomalies_df["prev_close"] > 0.20)
        )
        
        detected_anomalies = anomalies_df[vol_mask | price_mask]
        details = []
        for row in detected_anomalies.itertuples(index=False):
            issues = []
            if getattr(row, "volume") > 10 * getattr(row, "vol_ma"):
                issues.append("Volume spike")
            
            prev_c = getattr(row, "prev_close")
            if prev_c > 0:
                open_gap = abs(getattr(row, "open") - prev_c) / prev_c
                close_gap = abs(getattr(row, "close") - prev_c) / prev_c
                if open_gap > 0.20 or close_gap > 0.20:
                    issues.append("Price gap > 20%")
            
            if issues:
                details.append({
                    "timestamp": pd.Timestamp(row.timestamp).isoformat(),
                    "issues": issues,
                })
            
        return {"count": len(details), "details": details[:50]}

    def _build_expected_minute_index(
        self,
        min_timestamp: pd.Timestamp,
        max_timestamp: pd.Timestamp,
    ) -> pd.DatetimeIndex:
        """Build the expected weekday trading-minute index."""

        expected_ranges: list[pd.DatetimeIndex] = []
        for current_date in pd.date_range(min_timestamp.date(), max_timestamp.date(), freq="D"):
            if current_date.weekday() >= 5:
                continue
            if current_date.date() in self.market_holidays:
                continue
            start = pd.Timestamp(
                datetime.combine(current_date.date(), self.market_open, tzinfo=IST),
            )
            end = pd.Timestamp(
                datetime.combine(current_date.date(), self.market_close, tzinfo=IST) - timedelta(minutes=1),
            )
            expected_ranges.append(pd.date_range(start, end, freq="min"))

        if not expected_ranges:
            return pd.DatetimeIndex([])

        combined = expected_ranges[0]
        for index in expected_ranges[1:]:
            combined = combined.union(index)
        return combined
