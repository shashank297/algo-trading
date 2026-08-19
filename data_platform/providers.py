"""Provider adapters and ordered fallback without cross-source data blending."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

import pandas as pd
import requests

from data_platform.contracts import BarRequest, DatasetSnapshot, Instrument, PriceAdjustment
from storage.duckdb_manager import DuckDBManager


class ProviderUnavailable(RuntimeError):
    """Raised when one provider cannot satisfy a complete request."""


class MarketDataProvider(Protocol):
    """Interface that keeps strategy code independent of data vendors."""

    name: str

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        """Return one complete normalized snapshot or raise ProviderUnavailable."""


class ProviderRegistry:
    """Try configured providers in order and record the outcome of each attempt."""

    def __init__(self, providers: list[MarketDataProvider], db: DuckDBManager | None = None) -> None:
        self.providers = providers
        self.db = db

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        errors: list[str] = []
        for provider in self.providers:
            started_at = datetime.now(timezone.utc)
            try:
                snapshot = provider.fetch_bars(request)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                self._record_attempt(provider.name, request, "FAILED", started_at, str(exc))
                continue
            self._record_attempt(provider.name, request, "SUCCEEDED", started_at, None)
            return snapshot
        raise ProviderUnavailable("No provider could satisfy the request: " + "; ".join(errors))

    def _record_attempt(
        self,
        provider_name: str,
        request: BarRequest,
        status: str,
        started_at: datetime,
        error_message: str | None,
    ) -> None:
        if self.db is None:
            return
        self.db.record_provider_attempt(
            {
                "attempt_id": str(uuid.uuid4()),
                "provider_name": provider_name,
                "request_json": json.dumps(request.request_payload(), sort_keys=True),
                "status": status,
                "error_message": error_message,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
            },
        )


class DuckDBCacheProvider:
    """Read one canonical local series and identify legacy data explicitly."""

    name = "duckdb_cache"

    def __init__(self, db: DuckDBManager) -> None:
        self.db = db

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        frame = self.db.get_candles(request.symbol, request.timeframe)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        start = pd.Timestamp(request.start, tz="UTC") if request.start.tzinfo is None else pd.Timestamp(request.start).tz_convert("UTC")
        end = pd.Timestamp(request.end, tz="UTC") if request.end.tzinfo is None else pd.Timestamp(request.end).tz_convert("UTC")
        frame = frame[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)]
        if frame.empty:
            raise ProviderUnavailable("DuckDB cache has no bars in the requested range.")
        adjustment_states = {
            str(value).upper() for value in frame.get("adjustment", pd.Series(dtype="object")).dropna().unique()
        }
        if adjustment_states and adjustment_states != {request.adjustment.value}:
            raise ProviderUnavailable(
                f"DuckDB cache adjustment is {sorted(adjustment_states)}, requested {request.adjustment.value}."
            )
        minimum = frame["timestamp"].min()
        maximum = frame["timestamp"].max()
        boundary_tolerance = pd.Timedelta(days=7)
        if minimum > start + boundary_tolerance or maximum < end - boundary_tolerance:
            raise ProviderUnavailable(
                f"DuckDB cache is incomplete for the requested range: {minimum} to {maximum}."
            )
        return DatasetSnapshot.from_bars(
            instrument=Instrument(
                canonical_symbol=request.symbol,
                exchange=request.exchange,
                provider_name=self.name,
                provider_symbol=request.provider_symbol or request.symbol,
            ),
            timeframe=request.timeframe,
            bars=frame,
            adjustment=request.adjustment,
            timezone_name=request.timezone,
            metadata={"source": "canonical_cache", "legacy_provenance": True},
        )


class AngelOneProvider:
    """Adapter around the existing SmartAPI historical-data client."""

    name = "angel_one"
    _intervals = {"1M": "ONE_MINUTE", "1D": "ONE_DAY"}

    def __init__(self, historical_client: Any) -> None:
        self.historical_client = historical_client

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        if not request.token:
            raise ProviderUnavailable("Angel One requests require an instrument token.")
        interval = self._intervals.get(request.timeframe.upper())
        if interval is None:
            raise ProviderUnavailable(f"Angel One does not support timeframe {request.timeframe}.")
        try:
            bars = self.historical_client.fetch_candles(
                request.symbol,
                request.token,
                request.exchange,
                interval,
                request.start.date(),
                request.end.date(),
            )
        except Exception as exc:
            raise ProviderUnavailable(str(exc)) from exc
        failed_chunks = list(bars.attrs.get("failed_chunks", []))
        if failed_chunks:
            raise ProviderUnavailable("Angel One returned a partial request: " + "; ".join(failed_chunks))
        return DatasetSnapshot.from_bars(
            instrument=Instrument(
                canonical_symbol=request.symbol,
                exchange=request.exchange,
                provider_name=self.name,
                provider_symbol=request.provider_symbol or request.symbol,
                currency="INR",
                timezone="Asia/Kolkata",
            ),
            timeframe=request.timeframe,
            bars=bars,
            adjustment=PriceAdjustment.UNADJUSTED,
            timezone_name="Asia/Kolkata",
            metadata={"token": request.token, "source": "SmartAPI"},
        )


class OpenBBHttpProvider:
    """Optional HTTP adapter for a separately operated local OpenBB backend."""

    name = "openbb"

    def __init__(self, base_url: str, session: requests.Session | Any | None = None, timeout_seconds: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        url = f"{self.base_url}/api/v1/equity/price/historical"
        params = {
            "symbol": request.provider_symbol or request.symbol,
            "start_date": request.start.date().isoformat(),
            "end_date": request.end.date().isoformat(),
            "interval": request.timeframe,
        }
        try:
            response = self.session.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailable(f"OpenBB HTTP request failed: {exc}") from exc
        records = payload.get("results", payload.get("data", payload)) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise ProviderUnavailable("OpenBB response did not contain a list of bars.")
        frame = pd.DataFrame(records).rename(columns={"date": "timestamp"})
        return DatasetSnapshot.from_bars(
            instrument=Instrument(
                canonical_symbol=request.symbol,
                exchange=request.exchange,
                provider_name=self.name,
                provider_symbol=request.provider_symbol or request.symbol,
                timezone=request.timezone,
            ),
            timeframe=request.timeframe,
            bars=frame,
            adjustment=request.adjustment,
            timezone_name=request.timezone,
            metadata={"endpoint": url, "params": params},
        )
