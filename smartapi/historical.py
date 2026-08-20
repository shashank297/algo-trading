"""Historical candle download client for SmartAPI."""

from __future__ import annotations

import time
from collections import deque
from datetime import date, datetime, time as time_value
import threading
from typing import Any

import pandas as pd
import requests
from loguru import logger

from smartapi.auth import SmartAPIAuth
from utils.retry import (
    PERMANENT_API_ERRORS,
    TOKEN_EXPIRY_ERRORS,
    AuthTokenError,
    PermanentAPIError,
    TransientAPIError,
    TRANSIENT_HTTP_CODES,
    retry_auth,
    retry_transient,
)
from utils.timezone import IST, get_date_chunks, get_ist_now


class RateLimiter:
    """Token-bucket style limiter for second and minute request windows."""

    def __init__(self, rps: int, rpm: int) -> None:
        """Initialize the rate limiter.

        Args:
            rps: Maximum requests per second.
            rpm: Maximum requests per minute.
        """

        if rps <= 0 or rpm <= 0:
            raise ValueError("Rate limits must be greater than zero.")
        if rps > rpm:
            raise ValueError("Requests per second cannot exceed requests per minute.")
        self.rps = rps
        self.rpm = rpm
        self._second_timestamps: deque[float] = deque()
        self._minute_timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until the next request is allowed under both rate limits."""

        while True:
            sleep_seconds = 0.0
            with self._lock:
                now = time.monotonic()
                self._prune(now)

                second_sleep = 0.0
                minute_sleep = 0.0

                if len(self._second_timestamps) >= self.rps:
                    second_sleep = max(0.0, 1.0 - (now - self._second_timestamps[0]))
                if len(self._minute_timestamps) >= self.rpm:
                    minute_sleep = max(0.0, 60.0 - (now - self._minute_timestamps[0]))

                sleep_seconds = max(second_sleep, minute_sleep)
                if sleep_seconds <= 0:
                    self._second_timestamps.append(now)
                    self._minute_timestamps.append(now)
                    return

            logger.debug("Rate limit pacing sleep {:.2f}s", sleep_seconds)
            time.sleep(sleep_seconds)

    def _prune(self, now: float) -> None:
        """Remove timestamps that no longer affect the current windows."""

        while self._second_timestamps and now - self._second_timestamps[0] >= 1.0:
            self._second_timestamps.popleft()
        while self._minute_timestamps and now - self._minute_timestamps[0] >= 60.0:
            self._minute_timestamps.popleft()


class HistoricalDataClient:
    """Fetch historical candle data from SmartAPI with chunking and retries."""

    HISTORICAL_ENDPOINT = "/rest/secure/angelbroking/historical/v1/getCandleData"
    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        auth: SmartAPIAuth,
        config: dict[str, Any],
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize the historical data client.

        Args:
            auth: SmartAPI authentication helper.
            config: Full application configuration dictionary.
            rate_limiter: Optional shared RateLimiter instance across worker threads.
        """

        self.auth = auth
        self.config = config
        rate_limit_config = config["rate_limits"]
        self.retry_max_attempts = int(rate_limit_config.get("retry_max_attempts", 5))
        self.retry_wait_seconds = float(rate_limit_config.get("retry_wait_seconds", 2))
        self.retry_max_wait_seconds = float(rate_limit_config.get("retry_max_wait_seconds", 30))
        self._rate_limiter = rate_limiter or RateLimiter(
            rps=int(rate_limit_config["requests_per_second"]),
            rpm=int(rate_limit_config["requests_per_minute"]),
        )
        self.endpoint = f"{config['smartapi']['base_url'].rstrip('/')}{self.HISTORICAL_ENDPOINT}"
        self._local = threading.local()
        timezone_config = config["timezone"]
        self.market_open = time_value.fromisoformat(timezone_config["market_open"])
        self.market_close = time_value.fromisoformat(timezone_config["market_close"])

    @property
    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session") or self._local.session is None:
            self._local.session = requests.Session()
        return self._local.session

    def fetch_candles(
        self,
        symbol: str,
        token: str,
        exchange: str,
        interval: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """Fetch candles for a symbol over an inclusive date range.

        Args:
            symbol: Trading symbol for logging.
            token: SmartAPI symbol token.
            exchange: Exchange segment.
            interval: SmartAPI interval such as ONE_MINUTE or ONE_DAY.
            from_date: Inclusive start date.
            to_date: Inclusive end date.

        Returns:
            pd.DataFrame: Normalized candle DataFrame.
        """

        all_rows: list[dict[str, Any]] = []
        failed_chunks: list[str] = []

        try:
            chunk_days = self._get_chunk_days(interval)
            for chunk_start, chunk_end in get_date_chunks(from_date, to_date, chunk_days):
                chunk_from, chunk_to = self._build_chunk_datetimes(chunk_start, chunk_end)
                if chunk_to < chunk_from:
                    logger.info(
                        "Skipping {} {} chunk {} to {} because market has not opened yet.",
                        symbol,
                        interval,
                        chunk_start,
                        chunk_end,
                    )
                    continue

                payload = {
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": interval,
                    "fromdate": chunk_from.strftime("%Y-%m-%d %H:%M"),
                    "todate": chunk_to.strftime("%Y-%m-%d %H:%M"),
                }

                try:
                    self._rate_limiter.acquire()
                    response_payload = self._fetch_chunk(payload)
                except PermanentAPIError as exc:
                    logger.warning(
                        "Permanent SmartAPI error for {} {}: {} ({})",
                        symbol,
                        interval,
                        exc,
                        exc.error_code,
                    )
                    empty_frame = pd.DataFrame(columns=self._output_columns())
                    empty_frame.attrs["failed_chunks"] = [str(exc)]
                    empty_frame.attrs["partial"] = True
                    return empty_frame
                except Exception as exc:
                    failed_chunks.append(f"{chunk_start} to {chunk_end}: {exc}")
                    logger.error(
                        "Chunk fetch failed for {} {} {} to {}: {}",
                        symbol,
                        interval,
                        chunk_start,
                        chunk_end,
                        exc,
                    )
                    break

                chunk_data = response_payload.get("data")
                if not chunk_data:
                    logger.info(
                        "No candle data returned for {} {}: {} -> {}",
                        symbol,
                        interval,
                        chunk_from.strftime("%Y-%m-%d %H:%M"),
                        chunk_to.strftime("%Y-%m-%d %H:%M"),
                    )
                    continue

                all_rows.extend(self._parse_candle_rows(chunk_data))
                logger.info(
                    "📥 {} {}: {} → {} | {} candles",
                    symbol,
                    interval,
                    chunk_from.strftime("%Y-%m-%d"),
                    chunk_to.strftime("%Y-%m-%d"),
                    len(chunk_data),
                )

            if not all_rows:
                empty_frame = pd.DataFrame(columns=self._output_columns())
                empty_frame.attrs["failed_chunks"] = failed_chunks
                empty_frame.attrs["partial"] = bool(failed_chunks)
                return empty_frame

            frame = pd.DataFrame(all_rows, columns=self._output_columns())
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(IST)
            numeric_columns = ["open", "high", "low", "close", "volume"]
            for column in numeric_columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
            frame["volume"] = frame["volume"].astype("int64")
            frame = frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            frame.attrs["failed_chunks"] = failed_chunks
            frame.attrs["partial"] = bool(failed_chunks)
            return frame
        except Exception as exc:
            logger.exception("Historical fetch failed for {} {}: {}", symbol, interval, exc)
            empty_frame = pd.DataFrame(columns=self._output_columns())
            empty_frame.attrs["failed_chunks"] = [str(exc)]
            empty_frame.attrs["partial"] = True
            return empty_frame

    @retry_auth
    @retry_transient
    def _fetch_chunk(self, payload: dict[str, str]) -> dict[str, Any]:
        """Fetch a single historical data chunk from SmartAPI.

        Args:
            payload: Historical candle request payload.

        Returns:
            dict[str, Any]: SmartAPI response payload.

        Raises:
            AuthTokenError: When SmartAPI reports an expired or invalid token.
            PermanentAPIError: When SmartAPI reports a permanent request issue.
            TransientAPIError: When the request should be retried.
            requests.Timeout: When the request times out.
            requests.ConnectionError: When the request connection fails.
        """

        try:
            response = self._session.post(
                self.endpoint,
                json=payload,
                headers=self.auth.get_headers(),
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout:
            logger.warning("Historical request timed out for payload {}", payload)
            raise
        except requests.ConnectionError:
            logger.warning("Historical connection error for payload {}", payload)
            raise
        except requests.RequestException as exc:
            logger.exception("Unexpected historical request failure: {}", exc)
            raise TransientAPIError(str(exc)) from exc

        try:
            response_payload = response.json()
        except ValueError as exc:
            if response.status_code in TRANSIENT_HTTP_CODES:
                raise TransientAPIError(f"Transient HTTP {response.status_code} with invalid JSON.") from exc
            if response.status_code >= 500:
                raise TransientAPIError("Historical endpoint returned invalid JSON.") from exc
            raise PermanentAPIError(f"Historical endpoint returned HTTP {response.status_code} with invalid JSON.") from exc

        if not isinstance(response_payload, dict):
            raise PermanentAPIError("Historical endpoint returned an invalid JSON object.")

        if not response_payload.get("status", False):
            error_code = response_payload.get("errorcode") or response_payload.get("errorCode")
            message = response_payload.get("message", "Unknown SmartAPI historical error")
            if error_code in TOKEN_EXPIRY_ERRORS:
                raise AuthTokenError(message, status_code=response.status_code, error_code=error_code)
            if error_code in PERMANENT_API_ERRORS:
                raise PermanentAPIError(message, status_code=response.status_code, error_code=error_code)
            if response.status_code in TRANSIENT_HTTP_CODES:
                raise TransientAPIError(message, status_code=response.status_code, error_code=error_code)
            raise PermanentAPIError(message, status_code=response.status_code, error_code=error_code)

        return response_payload

    def _parse_candle_rows(self, candle_rows: list[list[Any]]) -> list[dict[str, Any]]:
        """Parse raw SmartAPI candle rows into normalized dictionaries."""

        parsed_rows: list[dict[str, Any]] = []
        for row in candle_rows:
            try:
                if len(row) < 6:
                    logger.warning("Skipping malformed candle row: {}", row)
                    continue
                # SmartAPI can return naive timestamps that are actually IST.
                # Explicitly localize naive timestamps to IST to prevent UTC shift.
                ts = pd.Timestamp(row[0])
                if ts.tzinfo is None:
                    ts = ts.tz_localize(IST)
                else:
                    ts = ts.tz_convert(IST)
                timestamp = ts.to_pydatetime()
                parsed_rows.append(
                    {
                        "timestamp": timestamp,
                        "open": row[1],
                        "high": row[2],
                        "low": row[3],
                        "close": row[4],
                        "volume": row[5],
                    },
                )
            except Exception as exc:
                logger.exception("Failed to parse candle row {}: {}", row, exc)
        return parsed_rows

    def _get_chunk_days(self, interval: str) -> int:
        """Resolve the configured chunk size for an interval."""

        if interval == "ONE_MINUTE":
            return int(self.config["rate_limits"]["chunk_days_1min"])
        if interval == "ONE_DAY":
            return int(self.config["rate_limits"]["chunk_days_1day"])
        raise ValueError(f"Unsupported interval: {interval}")

    def _build_chunk_datetimes(self, chunk_start: date, chunk_end: date) -> tuple[datetime, datetime]:
        """Build the SmartAPI datetime bounds for a date chunk."""

        from_datetime = datetime.combine(chunk_start, self.market_open, tzinfo=IST)
        market_close_datetime = datetime.combine(chunk_end, self.market_close, tzinfo=IST)
        today_ist = get_ist_now()

        if chunk_end == today_ist.date():
            to_datetime = min(today_ist, market_close_datetime)
        else:
            to_datetime = market_close_datetime

        return from_datetime, to_datetime

    def _output_columns(self) -> list[str]:
        """Return the standard candle DataFrame column order."""

        return ["timestamp", "open", "high", "low", "close", "volume"]
