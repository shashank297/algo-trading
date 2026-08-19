"""Unit tests for historical data validation rules."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import patch

import pandas as pd

from utils.timezone import IST
from validators.data_quality import DataValidator


class DataValidatorTests(unittest.TestCase):
    """Test all five data quality checks."""

    def test_run_all_checks_for_one_minute_data(self) -> None:
        """One-minute validation should detect missing candles and duplicates."""

        timestamps = pd.date_range(
            start=datetime(2026, 6, 17, 9, 15, tzinfo=IST),
            end=datetime(2026, 6, 17, 15, 29, tzinfo=IST),
            freq="min",
        ).tolist()
        timestamps.remove(datetime(2026, 6, 17, 9, 30, tzinfo=IST))
        timestamps.append(datetime(2026, 6, 17, 9, 15, tzinfo=IST))

        frame = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0] * len(timestamps),
                "high": [101.0] * len(timestamps),
                "low": [99.0] * len(timestamps),
                "close": [100.5] * len(timestamps),
                "volume": [1000] * len(timestamps),
            },
        )

        validator = DataValidator("1m")
        report = validator.run_all_checks(frame, "NIFTY")

        self.assertEqual(report["checks"]["missing_candles"]["count"], 1)
        self.assertEqual(report["checks"]["duplicates"]["count"], 1)
        self.assertFalse(report["passed"])

    def test_future_timestamp_detection(self) -> None:
        """Future candles should be flagged."""

        future_time = datetime(2026, 6, 19, 9, 15, tzinfo=IST)
        frame = pd.DataFrame(
            {
                "timestamp": [future_time],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            },
        )

        validator = DataValidator("1m")
        with patch("validators.data_quality.get_ist_now", return_value=datetime(2026, 6, 18, 12, 0, tzinfo=IST)):
            result = validator.check_future_timestamps(frame)

        self.assertEqual(result["count"], 1)

    def test_null_values_detection(self) -> None:
        """Null OHLCV values should be counted by column."""

        frame = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 17, 9, 15, tzinfo=IST)],
                "open": [None],
                "high": [101.0],
                "low": [99.0],
                "close": [None],
                "volume": [1000],
            },
        )

        validator = DataValidator("1m")
        result = validator.check_null_values(frame)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["columns"]["open"], 1)
        self.assertEqual(result["columns"]["close"], 1)

    def test_ohlc_integrity_detection(self) -> None:
        """Invalid OHLC relationships should be reported."""

        frame = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 17, 9, 15, tzinfo=IST)],
                "open": [0.0],
                "high": [-1.0],
                "low": [2.0],
                "close": [5.0],
                "volume": [-10],
            },
        )

        validator = DataValidator("1m")
        result = validator.check_ohlc_integrity(frame)

        self.assertEqual(result["count"], 1)
        self.assertGreaterEqual(len(result["details"][0]["issues"]), 3)

    def test_daily_missing_business_day_detection(self) -> None:
        """Daily data should use business days for missing-candle checks."""

        frame = pd.DataFrame(
            {
                "timestamp": [
                    datetime(2026, 6, 15, 15, 30, tzinfo=IST),
                    datetime(2026, 6, 17, 15, 30, tzinfo=IST),
                ],
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1200],
            },
        )

        validator = DataValidator("1d")
        result = validator.check_missing_candles(frame)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["gaps"][0], "2026-06-16")

    def test_market_holidays_are_excluded_from_missing_checks(self) -> None:
        """Configured exchange holidays must not be reported as missing candles."""

        frame = pd.DataFrame(
            {
                "timestamp": [
                    datetime(2026, 6, 15, 15, 30, tzinfo=IST),
                    datetime(2026, 6, 17, 15, 30, tzinfo=IST),
                ],
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1200],
            },
        )

        validator = DataValidator("1d", market_holidays={date(2026, 6, 16)})
        result = validator.check_missing_candles(frame)

        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
