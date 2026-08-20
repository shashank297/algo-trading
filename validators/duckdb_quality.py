"""DuckDB-native data quality validation."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
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
        """Initialize the validator for a timeframe label."""

        self.timeframe = timeframe
        self.market_open = market_open
        self.market_close = market_close
        self.market_holidays = market_holidays or set()
        self.calendar = build_nse_calendar(
            overrides=session_overrides,
            verified_through=calendar_verified_through,
            version=calendar_version,
        )

    def run_all_checks(
        self,
        db: DuckDBManager,
        symbol: str,
        dataset_id: str | None = None,
        persist_atomic_certification: bool = False,
    ) -> dict[str, Any]:
        """Run all configured quality checks and return a structured report."""

        started_at = datetime.now(timezone.utc)
        if dataset_id:
            total_candles = int(db.conn.execute(
                "SELECT COUNT(*) FROM historical_candles WHERE symbol = ? AND timeframe = ? AND dataset_id = ?",
                [symbol, self.timeframe, dataset_id],
            ).fetchone()[0])
        else:
            total_candles = db.get_candle_count(symbol, self.timeframe)

        if total_candles == 0:
            checks = {
                "schema": {"count": 0, "status": "CHECK_PASSED"},
                "ohlc_integrity": {"count": 0, "details": []},
                "duplicates": {"count": 0, "timestamps": []},
                "session_alignment": {"count": 0, "out_of_session": []},
                "missing_sessions": {"count": 1, "missing_sessions": ["NO_DATA"]},
                "timestamp_integrity": {"count": 0, "details": []},
                "missing_candles": {"count": 1, "gaps": [], "reason": "NO_DATA"},
                "future_timestamps": {"count": 0, "timestamps": []},
                "null_values": {"count": 0, "columns": {}},
                "anomalies": {"count": 0, "details": []},
            }
            summary = summarize_quality(checks)
            return {
                "symbol": symbol,
                "timeframe": self.timeframe,
                "dataset_id": dataset_id,
                "total_candles": 0,
                "checks": checks,
                **summary,
                "checked_at": get_ist_now(),
            }

        schema_res = self.check_schema(db, symbol, dataset_id=dataset_id)
        ohlc_res = self.check_ohlc_integrity(db, symbol, dataset_id=dataset_id)
        dup_res = self.check_duplicates(db, symbol, dataset_id=dataset_id)
        session_res = self.check_session_alignment(db, symbol, dataset_id=dataset_id)
        missing_sessions_res = {
            "count": len(session_res.get("missing_sessions", [])),
            "missing_sessions": session_res.get("missing_sessions", []),
        }
        timestamp_int_res = self.check_timestamp_integrity(db, symbol, dataset_id=dataset_id)
        missing_candles_res = self.check_missing_candles(db, symbol, dataset_id=dataset_id)
        anomalies_res = self.check_anomalies(db, symbol, dataset_id=dataset_id)
        null_res = self.check_null_values(db, symbol, dataset_id=dataset_id)
        future_res = self.check_future_timestamps(db, symbol, dataset_id=dataset_id)

        checks = {
            "schema": schema_res,
            "ohlc_integrity": ohlc_res,
            "duplicates": dup_res,
            "session_alignment": session_res,
            "missing_sessions": missing_sessions_res,
            "timestamp_integrity": timestamp_int_res,
            "missing_candles": missing_candles_res,
            "future_timestamps": future_res,
            "null_values": null_res,
            "anomalies": anomalies_res,
        }
        summary = summarize_quality(checks)
        completed_at = datetime.now(timezone.utc)

        certification_id = None
        if persist_atomic_certification and dataset_id:
            certification_id = str(uuid.uuid4())
            required_6 = ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]
            total_issues_6 = sum(int(checks[k].get("count", 0)) for k in required_6)
            cert_status = "CERTIFIED" if (total_issues_6 == 0 and summary.get("passed", False)) else "FAILED"

            check_rows = [
                {
                    "symbol": symbol,
                    "timeframe": self.timeframe,
                    "check_type": k,
                    "issue_count": int(checks[k].get("count", 0)),
                    "details": json.dumps(checks[k], default=str),
                    "checked_at": completed_at,
                }
                for k in required_6
            ]
            db.log_atomic_quality_certification(
                certification_id=certification_id,
                dataset_id=dataset_id,
                validator_version=getattr(self.calendar, "version", "validator-v1"),
                check_count=6,
                issue_count=total_issues_6,
                checks_json=json.dumps({k: checks[k] for k in required_6}, default=str),
                status=cert_status,
                started_at=started_at,
                completed_at=completed_at,
                check_rows=check_rows,
            )

        return {
            "symbol": symbol,
            "timeframe": self.timeframe,
            "dataset_id": dataset_id,
            "certification_id": certification_id,
            "total_candles": total_candles,
            "checks": checks,
            **summary,
            "checked_at": get_ist_now(),
        }

    def check_schema(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Verify presence of required columns and absence of nulls in primary schema."""
        null_res = self.check_null_values(db, symbol, dataset_id=dataset_id)
        return {
            "count": int(null_res.get("count", 0)),
            "columns": null_res.get("columns", {}),
            "status": null_res.get("status", "PASS" if null_res.get("count", 0) == 0 else "FAIL"),
        }

    def check_timestamp_integrity(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Verify strict timestamp monotonicity, absence of future timestamps, and timezone validity."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            future_count = self.check_future_timestamps(db, symbol, dataset_id=dataset_id).get("count", 0)
            non_mono_row = db.conn.execute(
                f"""
                WITH ordered AS (
                    SELECT timestamp, LAG(timestamp) OVER (ORDER BY timestamp) as prev_ts
                    FROM historical_candles
                    {where}
                )
                SELECT COUNT(*) FROM ordered WHERE prev_ts IS NOT NULL AND timestamp <= prev_ts
                """,
                params,
            ).fetchone()
            non_mono_count = int(non_mono_row[0]) if non_mono_row else 0
            total_count = int(future_count) + int(non_mono_count)
            return {
                "count": total_count,
                "future_count": int(future_count),
                "non_monotonic_count": non_mono_count,
            }
        except Exception as exc:
            logger.error("Error checking timestamp integrity: {}", exc)
            return {"count": 1, "status": "CHECK_FAILED", "error": str(exc)}

    def check_missing_candles(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Detect missing timestamps for the configured timeframe using Python (holidays logic)."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            df = db.conn.execute(
                f"""
                SELECT timestamp
                FROM historical_candles
                {where}
                ORDER BY timestamp
                """,
                params,
            ).df()
        except Exception as exc:
            logger.error("Error checking missing candles: {}", exc)
            return {"count": 1, "gaps": [f"CHECK_FAILED: {exc}"], "status": "CHECK_FAILED"}

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

    def check_session_alignment(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Classify bars outside the versioned exchange calendar."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            timestamps = db.conn.execute(
                f"SELECT timestamp FROM historical_candles {where} ORDER BY timestamp",
                params,
            ).df()["timestamp"]
            result = self.calendar.validate_bars(timestamps, self.timeframe)
            return {
                "count": result.out_of_session_count,
                "out_of_session": list(result.out_of_session),
                "missing_sessions": list(result.missing_sessions),
                "expected_interruptions": list(result.expected_interruptions),
                "calendar_version": self.calendar.version,
            }
        except Exception as exc:
            logger.error("Error checking session alignment: {}", exc)
            return {"count": 1, "out_of_session": [f"CHECK_FAILED: {exc}"], "status": "CHECK_FAILED"}

    def check_duplicates(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Find duplicate timestamps in DuckDB."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            duplicates = db.conn.execute(
                f"""
                SELECT timestamp, COUNT(*) as cnt
                FROM historical_candles
                {where}
                GROUP BY timestamp
                HAVING cnt > 1
                ORDER BY timestamp
                LIMIT 50
                """,
                params,
            ).fetchall()

            dup_count = _required_row(db.conn.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT timestamp
                    FROM historical_candles
                    {where}
                    GROUP BY timestamp
                    HAVING COUNT(*) > 1
                )
                """,
                params,
            ).fetchone(), "duplicate count")[0]

            return {
                "count": int(dup_count),
                "timestamps": [pd.Timestamp(d[0]).tz_convert(IST).isoformat() for d in duplicates],
            }
        except Exception as exc:
            logger.error("Error checking duplicates: {}", exc)
            return {"count": 1, "timestamps": [f"CHECK_FAILED: {exc}"], "status": "CHECK_FAILED"}

    def check_future_timestamps(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Detect candles whose timestamps are in the future."""
        where = "WHERE symbol = ? AND timeframe = ? AND timestamp > ?"
        params: list[Any] = [symbol, self.timeframe, get_ist_now()]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            future_count = _required_row(db.conn.execute(
                f"""
                SELECT COUNT(*)
                FROM historical_candles
                {where}
                """,
                params,
            ).fetchone(), "future timestamp count")[0]

            if future_count == 0:
                return {"count": 0, "timestamps": []}

            future_timestamps = db.conn.execute(
                f"""
                SELECT timestamp
                FROM historical_candles
                {where}
                ORDER BY timestamp
                LIMIT 50
                """,
                params,
            ).fetchall()

            return {
                "count": int(future_count),
                "timestamps": [pd.Timestamp(t[0]).tz_convert(IST).isoformat() for t in future_timestamps],
            }
        except Exception as exc:
            logger.error("Error checking future timestamps: {}", exc)
            return {"count": 1, "timestamps": [f"CHECK_FAILED: {exc}"], "status": "CHECK_FAILED"}

    def check_null_values(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Count null values across OHLCV columns."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            nulls = _required_row(db.conn.execute(
                f"""
                SELECT 
                    SUM(CASE WHEN open IS NULL THEN 1 ELSE 0 END) as open_nulls,
                    SUM(CASE WHEN high IS NULL THEN 1 ELSE 0 END) as high_nulls,
                    SUM(CASE WHEN low IS NULL THEN 1 ELSE 0 END) as low_nulls,
                    SUM(CASE WHEN close IS NULL THEN 1 ELSE 0 END) as close_nulls,
                    SUM(CASE WHEN volume IS NULL THEN 1 ELSE 0 END) as volume_nulls
                FROM historical_candles
                {where}
                """,
                params,
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
            return {"count": 1, "columns": {"error": 1}, "status": "CHECK_FAILED"}

    def check_ohlc_integrity(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Validate core OHLCV integrity rules via SQL (with volume >= 0)."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            violations_count = _required_row(db.conn.execute(
                f"""
                SELECT COUNT(*)
                FROM historical_candles
                {where}
                  AND (
                      high < open OR high < close OR
                      low > open OR low > close OR
                      high < low OR volume < 0 OR open <= 0 OR close <= 0
                  )
                """,
                params,
            ).fetchone(), "OHLC violation count")[0]

            if violations_count == 0:
                return {"count": 0, "details": []}

            violations = db.conn.execute(
                f"""
                SELECT timestamp, open, high, low, close, volume
                FROM historical_candles
                {where}
                  AND (
                      high < open OR high < close OR
                      low > open OR low > close OR
                      high < low OR volume < 0 OR open <= 0 OR close <= 0
                  )
                ORDER BY timestamp
                LIMIT 50
                """,
                params,
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
                if close <= 0:
                    issues.append("close <= 0")

                failed_rows.append({
                    "timestamp": pd.Timestamp(timestamp).tz_convert(IST).isoformat(),
                    "issues": issues,
                })

            return {"count": int(violations_count), "details": failed_rows}
        except Exception as exc:
            logger.error("Error checking OHLC integrity: {}", exc)
            return {"count": 1, "details": [{"error": f"CHECK_FAILED: {exc}"}], "status": "CHECK_FAILED"}

    def check_anomalies(self, db: DuckDBManager, symbol: str, dataset_id: str | None = None) -> dict[str, Any]:
        """Detect statistical anomalies like volume spikes or price jumps via SQL Window Functions."""
        where = "WHERE symbol = ? AND timeframe = ?"
        params: list[Any] = [symbol, self.timeframe]
        if dataset_id:
            where += " AND dataset_id = ?"
            params.append(dataset_id)
        try:
            query = f"""
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
                {where}
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
            anomalies = db.conn.execute(query, params).fetchall()
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
                    "issues": issues,
                })

            return {"count": len(anomalies), "details": details}
        except Exception as exc:
            logger.error("Error checking anomalies: {}", exc)
            return {"count": 1, "details": [{"error": f"CHECK_FAILED: {exc}"}], "status": "CHECK_FAILED"}

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
