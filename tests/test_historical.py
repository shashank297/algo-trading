"""Unit tests for the historical data client."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

import pandas as pd
import requests

from smartapi.historical import HistoricalDataClient, RateLimiter
from tools.backfill_market_history import (
    SOURCE_BOUNDARY_EMPTY_WINDOWS,
    _backfill_timeframe,
    _backward_windows,
    _forward_windows,
    _persist_backfill_frame,
)
from storage import DuckDBManager
from pathlib import Path
import tempfile
from utils.retry import PermanentAPIError
from utils.timezone import IST


class DummyAuth:
    """Simple auth stub for historical client tests."""

    def __init__(self) -> None:
        """Initialize counters for header access and token refresh."""

        self.refresh_count = 0

    def get_headers(self) -> dict[str, str]:
        """Return a static bearer token header."""

        return {"Authorization": "Bearer token"}

    def refresh_token(self) -> bool:
        """Track token refresh attempts."""

        self.refresh_count += 1
        return True


class HistoricalDataClientTests(unittest.TestCase):
    def test_backfill_windows_are_non_overlapping_and_reach_requested_boundaries(self) -> None:
        backward = list(_backward_windows(date(2020, 1, 1), date(2019, 11, 1), 20))
        forward = list(_forward_windows(date(2020, 1, 1), date(2020, 3, 1), 20))

        self.assertEqual(backward[0], (date(2019, 12, 13), date(2020, 1, 1)))
        self.assertEqual(backward[-1][0], date(2019, 11, 1))
        self.assertEqual(forward[0], (date(2020, 1, 1), date(2020, 1, 20)))
        self.assertEqual(forward[-1][1], date(2020, 3, 1))
        self.assertTrue(all(
            backward[index][0] - backward[index + 1][1] == pd.Timedelta(days=1)
            for index in range(len(backward) - 1)
        ))
        self.assertTrue(all(
            forward[index + 1][0] - forward[index][1] == pd.Timedelta(days=1)
            for index in range(len(forward) - 1)
        ))

    def test_backfill_persists_dataset_and_provider_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "backfill.duckdb"))
            try:
                frame = pd.DataFrame({
                    "timestamp": [pd.Timestamp("2020-01-02", tz="UTC")],
                    "open": [100.0], "high": [101.0], "low": [99.0],
                    "close": [100.5], "volume": [1000],
                })
                inserted = _persist_backfill_frame(
                    db, frame, "TEST-EQ", "1", "NSE", "1d", date(2020, 1, 1), date(2020, 1, 3),
                )
                lineage = db.conn.execute(
                    """SELECT c.provider_name, c.dataset_id, a.status
                       FROM historical_candles c JOIN provider_attempts a ON c.dataset_id = a.dataset_id"""
                ).fetchone()
            finally:
                db.close()
        self.assertEqual(inserted, 1)
        self.assertEqual(lineage[0], "angel_one")
        self.assertIsNotNone(lineage[1])
        self.assertEqual(lineage[2], "SUCCEEDED")

    def test_backward_backfill_requires_repeated_empty_windows_for_source_boundary(self) -> None:
        db = Mock()
        historical = Mock()
        historical.config = {"rate_limits": {"chunk_days_1min": 20}}
        historical.fetch_candles.side_effect = [
            pd.DataFrame(),
            pd.DataFrame({
                "timestamp": [pd.Timestamp("2020-02-01", tz="UTC")],
                "open": [100.0], "high": [101.0], "low": [99.0],
                "close": [100.5], "volume": [1000],
            }),
            *[pd.DataFrame() for _ in range(SOURCE_BOUNDARY_EMPTY_WINDOWS)],
        ]
        with (
            patch("tools.backfill_market_history._stored_bounds", side_effect=[(None, None), (None, None)]),
            patch("tools.backfill_market_history._persist_backfill_batch", return_value=1) as persist,
            patch("tools.backfill_market_history._record_backfill_attempt"),
        ):
            result = _backfill_timeframe(
                db,
                historical,
                {"symbol": "TEST-EQ", "token": "1", "exchange": "NSE"},
                "1m",
                date(2019, 11, 1),
                date(2020, 3, 1),
                None,
            )

        self.assertEqual(historical.fetch_candles.call_count, SOURCE_BOUNDARY_EMPTY_WINDOWS + 2)
        self.assertEqual(persist.call_count, 1)
        self.assertTrue(result["source_boundary"])

    """Test historical data chunking, retries, and normalization."""

    def setUp(self) -> None:
        """Create a reusable historical client config."""

        self.config = {
            "smartapi": {
                "base_url": "https://apiconnect.angelone.in",
            },
            "rate_limits": {
                "requests_per_second": 3,
                "requests_per_minute": 180,
                "chunk_days_1min": 60,
                "chunk_days_1day": 2000,
            },
            "timezone": {
                "market_open": "09:15",
                "market_close": "15:30",
            },
        }
        self.auth = DummyAuth()
        self.client = HistoricalDataClient(self.auth, self.config)

    def test_fetch_candles_sorts_and_deduplicates(self) -> None:
        """Fetched candles should be sorted and deduplicated by timestamp."""

        payload = {
            "status": True,
            "data": [
                ["2026-06-17T09:16:00+05:30", 102, 103, 101, 102.5, 1500],
                ["2026-06-17T09:15:00+05:30", 100, 101, 99, 100.5, 1000],
                ["2026-06-17T09:15:00+05:30", 100, 101, 99, 100.5, 1000],
            ],
        }

        with patch.object(self.client, "_fetch_chunk", return_value=payload), patch.object(
            self.client._rate_limiter,
            "acquire",
            return_value=None,
        ):
            frame = self.client.fetch_candles(
                symbol="NIFTY",
                token="26000",
                exchange="NSE",
                interval="ONE_MINUTE",
                from_date=date(2026, 6, 17),
                to_date=date(2026, 6, 17),
            )

        self.assertEqual(len(frame), 2)
        self.assertTrue(frame["timestamp"].is_monotonic_increasing)
        self.assertEqual(str(frame["timestamp"].dt.tz), str(IST))

    def test_fetch_candles_returns_empty_on_permanent_error(self) -> None:
        """Permanent SmartAPI errors should produce an empty DataFrame."""

        with patch.object(
            self.client,
            "_fetch_chunk",
            side_effect=PermanentAPIError("Symbol not found", error_code="AB1009"),
        ), patch.object(self.client._rate_limiter, "acquire", return_value=None):
            frame = self.client.fetch_candles(
                symbol="BAD",
                token="0",
                exchange="NSE",
                interval="ONE_MINUTE",
                from_date=date(2026, 6, 17),
                to_date=date(2026, 6, 17),
            )

        self.assertTrue(frame.empty)

    def test_fetch_candles_returns_empty_on_empty_data(self) -> None:
        """Empty SmartAPI data payloads should return an empty DataFrame."""

        with patch.object(
            self.client,
            "_fetch_chunk",
            return_value={"status": True, "data": []},
        ), patch.object(self.client._rate_limiter, "acquire", return_value=None):
            frame = self.client.fetch_candles(
                symbol="NIFTY",
                token="26000",
                exchange="NSE",
                interval="ONE_DAY",
                from_date=date(2026, 6, 17),
                to_date=date(2026, 6, 17),
            )

        self.assertTrue(frame.empty)

    @patch("smartapi.historical.requests.Session.post")
    def test_fetch_chunk_retries_transient_connection_error(self, post_mock: Mock) -> None:
        """Transient network errors should be retried before succeeding."""

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "status": True,
            "data": [["2026-06-17T09:15:00+05:30", 100, 101, 99, 100.5, 1000]],
        }

        post_mock.side_effect = [requests.ConnectionError("temporary"), success_response]

        response = self.client._fetch_chunk(
            {
                "exchange": "NSE",
                "symboltoken": "26000",
                "interval": "ONE_MINUTE",
                "fromdate": "2026-06-17 09:15",
                "todate": "2026-06-17 15:30",
            },
        )

        self.assertTrue(response["status"])
        self.assertEqual(post_mock.call_count, 2)

    @patch("smartapi.historical.requests.Session.post")
    def test_fetch_chunk_uses_configured_retry_attempts(self, post_mock: Mock) -> None:
        """The configured retry limit must bound transient requests."""

        self.client.retry_max_attempts = 1
        post_mock.side_effect = requests.ConnectionError("persistent failure")

        with self.assertRaises(requests.ConnectionError):
            self.client._fetch_chunk(
                {
                    "exchange": "NSE",
                    "symboltoken": "26000",
                    "interval": "ONE_MINUTE",
                    "fromdate": "2026-06-17 09:15",
                    "todate": "2026-06-17 15:30",
                },
            )

        self.assertEqual(post_mock.call_count, 1)

    @patch("smartapi.historical.requests.Session.post")
    def test_fetch_chunk_refreshes_token_on_auth_error(self, post_mock: Mock) -> None:
        """Token-expiry API errors should refresh the token and retry once."""

        expired_response = Mock()
        expired_response.status_code = 200
        expired_response.json.return_value = {
            "status": False,
            "errorcode": "AG8002",
            "message": "Token expired",
        }

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "status": True,
            "data": [["2026-06-17T09:15:00+05:30", 100, 101, 99, 100.5, 1000]],
        }

        post_mock.side_effect = [expired_response, success_response]

        response = self.client._fetch_chunk(
            {
                "exchange": "NSE",
                "symboltoken": "26000",
                "interval": "ONE_MINUTE",
                "fromdate": "2026-06-17 09:15",
                "todate": "2026-06-17 15:30",
            },
        )

        self.assertTrue(response["status"])
        self.assertEqual(self.auth.refresh_count, 1)
        self.assertEqual(post_mock.call_count, 2)

    def test_build_chunk_datetimes_caps_today_to_now(self) -> None:
        """Today chunks should cap their end time to the current IST time."""

        fake_now = datetime(2026, 6, 18, 12, 0, tzinfo=IST)
        with patch("smartapi.historical.get_ist_now", return_value=fake_now):
            chunk_from, chunk_to = self.client._build_chunk_datetimes(date(2026, 6, 18), date(2026, 6, 18))

        self.assertEqual(chunk_from, datetime(2026, 6, 18, 9, 15, tzinfo=IST))
        self.assertEqual(chunk_to, fake_now)

    def test_rate_limiter_sleeps_when_second_limit_is_hit(self) -> None:
        """The rate limiter should sleep when the per-second window is full."""

        limiter = RateLimiter(rps=1, rpm=10)
        with patch("smartapi.historical.time.monotonic", side_effect=[0.0, 0.0, 0.2, 1.3]), patch(
            "smartapi.historical.time.sleep",
            return_value=None,
        ) as sleep_mock:
            limiter.acquire()
            limiter.acquire()

        sleep_mock.assert_called()

    def test_fetch_candles_marks_failed_chunks(self) -> None:
        """A failed chunk must be visible to the caller instead of looking successful."""

        with patch.object(
            self.client,
            "_fetch_chunk",
            side_effect=PermanentAPIError("Symbol not found", error_code="AB1009"),
        ), patch.object(self.client._rate_limiter, "acquire", return_value=None):
            frame = self.client.fetch_candles(
                symbol="BAD",
                token="0",
                exchange="NSE",
                interval="ONE_MINUTE",
                from_date=date(2026, 6, 17),
                to_date=date(2026, 6, 17),
            )

        self.assertTrue(frame.attrs["failed_chunks"])
        self.assertTrue(frame.attrs["partial"])


if __name__ == "__main__":
    unittest.main()
