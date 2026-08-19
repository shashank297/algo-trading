"""DuckDB-native data quality validation."""

from __future__ import annotations


from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
from loguru import logger

from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import SessionOverride, build_nse_calendar
from utils.timezone import IST, get_ist_now
from validators.severity import summarize_quality


def _required_row(row: tuple[Any, ...] | None, description: str) -> tuple[Any, ...]:
    if row is None:
        raise RuntimeError(f"DuckDB returned no row for {description}.")
    return row


class DuckDBValidator:
    """Run a fixed set of quality checks against historical candle data natively in DuckDB."""

    def __init__(
        self,
        timeframe: str,
        market_open: time = time(hour=9, minute=15),
        market_close: time = time(hour=15, minute=30),
        market_holidays: set[date] | None = None,
        session_overrides: tuple[SessionOverride, ...] = (),
        calendar_version: str = "config-v1",
        calendar_verified_through: date | None = None,
    ) -> None:
        """Initialize the validator for a timeframe label.

        Args:
            timeframe: Local timeframe label such as 1m or 1d.
        """

        self.timeframe = timeframe
        self.market_open = market_open
        self.market_close = market_close
        self.market_holidays = market_holidays or set()
        self.calendar = build_nse_calendar(
            overrides=session_overrides,
            verified_through=calendar_verified_through,
            version=calendar_version,
        )

    def run_all_checks(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Run all configured quality checks and return a structured report.

        Args:
            db: DuckDBManager connection.
            symbol: Trading symbol being validated.

        Returns:
            dict[str, Any]: Structured data-quality report.
        """

        # Ensure candles exist before running checks
        total_candles = db.get_candle_count(symbol, self.timeframe)
        if total_candles == 0:
            checks = {
                "missing_candles": {"count": 1, "gaps": [], "reason": "NO_DATA"},
                "duplicates": {"count": 0, "timestamps": []},
                "future_timestamps": {"count": 0, "timestamps": []},
                "null_values": {"count": 0, "columns": {}},
                "ohlc_integrity": {"count": 0, "details": []},
                "anomalies": {"count": 0, "details": []},
                "session_alignment": {"count": 0, "out_of_session": [], "missing_sessions": []},
            }
            return {
                "symbol": symbol,
                "timeframe": self.timeframe,
                "total_candles": 0,
                "checks": checks,
                **summarize_quality(checks),
                "checked_at": get_ist_now(),
            }

        checks = {
            "missing_candles": self.check_missing_candles(db, symbol),
            "duplicates": self.check_duplicates(db, symbol),
            "future_timestamps": self.check_future_timestamps(db, symbol),
            "null_values": self.check_null_values(db, symbol),
            "ohlc_integrity": self.check_ohlc_integrity(db, symbol),
            "anomalies": self.check_anomalies(db, symbol),
            "session_alignment": self.check_session_alignment(db, symbol),
        }
        summary = summarize_quality(checks)

        return {
            "symbol": symbol,
            "timeframe": self.timeframe,
            "total_candles": total_candles,
            "checks": checks,
            **summary,
            "checked_at": get_ist_now(),
        }

    def check_missing_candles(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Detect missing timestamps for the configured timeframe using Python (holidays logic)."""
        
        # Get only the timestamps to keep memory footprint low
        try:
            df = db.conn.execute(
                """
                SELECT timestamp
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp
                """,
                [symbol, self.timeframe],
            ).df()
        except Exception as exc:
            logger.error("Error checking missing candles: {}", exc)
            return {"count": 0, "gaps": []}
            
        if df.empty:
            return {"count": 0, "gaps": []}
            
        actual_timestamps = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST)
        
        if self.timeframe == "1m":
            expected_index = self.calendar.expected_minute_index(actual_timestamps.min().date(), actual_timestamps.max().date())
            missing_index = expected_index.difference(pd.DatetimeIndex(actual_timestamps))
            missing_values = [timestamp.isoformat() for timestamp in missing_index[:50]]
            missing_count = len(missing_index)
        elif self.timeframe == "1d":
            actual_dates = pd.Index(actual_timestamps.dt.normalize().dt.date)
            expected_dates = [
                trading_date
                for trading_date in self.calendar.iter_trading_days(
                    actual_timestamps.min().date(), actual_timestamps.max().date(),
                )
                if not self.calendar.is_special_session(trading_date)
            ]
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

    def check_session_alignment(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Classify bars outside the versioned exchange calendar."""

        timestamps = db.conn.execute(
            "SELECT timestamp FROM historical_candles WHERE symbol = ? AND timeframe = ? ORDER BY timestamp",
            [symbol, self.timeframe],
        ).df()["timestamp"]
        result = self.calendar.validate_bars(timestamps, self.timeframe)
        return {
            "count": result.out_of_session_count,
            "out_of_session": list(result.out_of_session),
            "missing_sessions": list(result.missing_sessions),
            "expected_interruptions": list(result.expected_interruptions),
            "calendar_version": self.calendar.version,
        }

    def check_duplicates(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Find duplicate timestamps in DuckDB (should be 0 since primary key prevents it)."""

        try:
            duplicates = db.conn.execute(
                """
                SELECT timestamp, COUNT(*) as cnt
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
                GROUP BY timestamp
                HAVING cnt > 1
                ORDER BY timestamp
                LIMIT 50
                """,
                [symbol, self.timeframe],
            ).fetchall()
            
            dup_count = _required_row(db.conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT timestamp
                    FROM historical_candles
                    WHERE symbol = ? AND timeframe = ?
                    GROUP BY timestamp
                    HAVING COUNT(*) > 1
                )
                """,
                [symbol, self.timeframe],
            ).fetchone(), "duplicate count")[0]
            
            return {
                "count": int(dup_count), 
                "timestamps": [pd.Timestamp(d[0]).tz_convert(IST).isoformat() for d in duplicates]
            }
        except Exception as exc:
            logger.error("Error checking duplicates: {}", exc)
            return {"count": 0, "timestamps": []}

    def check_future_timestamps(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Detect candles whose timestamps are in the future."""

        try:
            now_ist = get_ist_now()
            
            future_count = _required_row(db.conn.execute(
                """
                SELECT COUNT(*)
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ? AND timestamp > ?
                """,
                [symbol, self.timeframe, now_ist],
            ).fetchone(), "future timestamp count")[0]
            
            if future_count == 0:
                return {"count": 0, "timestamps": []}
                
            future_timestamps = db.conn.execute(
                """
                SELECT timestamp
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ? AND timestamp > ?
                ORDER BY timestamp
                LIMIT 50
                """,
                [symbol, self.timeframe, now_ist],
            ).fetchall()
            
            return {
                "count": int(future_count), 
                "timestamps": [pd.Timestamp(t[0]).tz_convert(IST).isoformat() for t in future_timestamps]
            }
        except Exception as exc:
            logger.error("Error checking future timestamps: {}", exc)
            return {"count": 0, "timestamps": []}

    def check_null_values(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Count null values across OHLCV columns."""

        try:
            nulls = _required_row(db.conn.execute(
                """
                SELECT 
                    SUM(CASE WHEN open IS NULL THEN 1 ELSE 0 END) as open_nulls,
                    SUM(CASE WHEN high IS NULL THEN 1 ELSE 0 END) as high_nulls,
                    SUM(CASE WHEN low IS NULL THEN 1 ELSE 0 END) as low_nulls,
                    SUM(CASE WHEN close IS NULL THEN 1 ELSE 0 END) as close_nulls,
                    SUM(CASE WHEN volume IS NULL THEN 1 ELSE 0 END) as volume_nulls
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
                """,
                [symbol, self.timeframe],
            ).fetchone(), "null counts")
            
            open_n, high_n, low_n, close_n, vol_n = nulls
            column_counts = {
                "open": int(open_n or 0),
                "high": int(high_n or 0),
                "low": int(low_n or 0),
                "close": int(close_n or 0),
                "volume": int(vol_n or 0),
            }
            return {"count": sum(column_counts.values()), "columns": column_counts}
        except Exception as exc:
            logger.error("Error checking null values: {}", exc)
            return {"count": 0, "columns": {}}

    def check_ohlc_integrity(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Validate core OHLCV integrity rules via SQL."""

        try:
            violations_count = _required_row(db.conn.execute(
                """
                SELECT COUNT(*)
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
                  AND (
                      high < open OR high < close OR
                      low > open OR low > close OR
                      high < low OR volume < 0 OR open <= 0
                  )
                """,
                [symbol, self.timeframe],
            ).fetchone(), "OHLC violation count")[0]
            
            if violations_count == 0:
                return {"count": 0, "details": []}
                
            violations = db.conn.execute(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
                  AND (
                      high < open OR high < close OR
                      low > open OR low > close OR
                      high < low OR volume < 0 OR open <= 0
                  )
                ORDER BY timestamp
                LIMIT 50
                """,
                [symbol, self.timeframe],
            ).fetchall()
            
            failed_rows = []
            for timestamp, open_price, high, low, close, volume in violations:
                issues = []
                if high < open_price:
                    issues.append("high < open")
                if high < close:
                    issues.append("high < close")
                if low > open_price:
                    issues.append("low > open")
                if low > close:
                    issues.append("low > close")
                if high < low:
                    issues.append("high < low")
                if volume < 0:
                    issues.append("volume < 0")
                if open_price <= 0:
                    issues.append("open <= 0")
                
                failed_rows.append({
                    "timestamp": pd.Timestamp(timestamp).tz_convert(IST).isoformat(),
                    "issues": issues
                })
                
            return {"count": int(violations_count), "details": failed_rows}
        except Exception as exc:
            logger.error("Error checking OHLC integrity: {}", exc)
            return {"count": 0, "details": []}

    def check_anomalies(self, db: DuckDBManager, symbol: str) -> dict[str, Any]:
        """Detect statistical anomalies like volume spikes or price jumps via SQL Window Functions."""
        
        try:
            # We use duckdb window functions to compute 20-period moving average and lag
            query = """
            WITH ranked AS (
                SELECT 
                    timestamp,
                    open,
                    close,
                    volume,
                    AVG(volume) OVER (
                        ORDER BY timestamp 
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) as vol_ma,
                    LAG(close) OVER (
                        ORDER BY timestamp
                    ) as prev_close,
                    ROW_NUMBER() OVER (ORDER BY timestamp) as rn
                FROM historical_candles
                WHERE symbol = ? AND timeframe = ?
            )
            SELECT timestamp, open, close, volume, vol_ma, prev_close
            FROM ranked
            WHERE rn >= 5 AND (
                (volume > 10 * vol_ma AND volume > 1000)
                OR
                (prev_close > 0 AND (
                    ABS(open - prev_close) / prev_close > 0.20
                    OR ABS(close - prev_close) / prev_close > 0.20
                ))
            )
            ORDER BY timestamp
            """
            
            anomalies = db.conn.execute(query, [symbol, self.timeframe]).fetchall()
            if not anomalies:
                return {"count": 0, "details": []}
                
            details = []
            for t, o, c, v, v_ma, p_c in anomalies[:50]:
                issues = []
                if v > 10 * v_ma and v > 1000:
                    issues.append("Volume spike")
                if p_c > 0:
                    open_gap = abs(o - p_c) / p_c
                    close_gap = abs(c - p_c) / p_c
                    if open_gap > 0.20 or close_gap > 0.20:
                        issues.append("Price gap > 20%")
                
                details.append({
                    "timestamp": pd.Timestamp(t).tz_convert(IST).isoformat(),
                    "issues": issues
                })
                
            return {"count": len(anomalies), "details": details}
        except Exception as exc:
            logger.error("Error checking anomalies: {}", exc)
            return {"count": 0, "details": []}

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
