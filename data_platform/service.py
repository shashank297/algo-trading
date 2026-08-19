"""Persist provider-neutral datasets while retaining the legacy candle cache."""

from __future__ import annotations

from data_platform.contracts import BarRequest, DatasetSnapshot
from data_platform.providers import ProviderRegistry
from storage.duckdb_manager import DuckDBManager


class DataPlatform:
    """Coordinates provider selection, validation, provenance, and local storage."""

    def __init__(self, db: DuckDBManager, providers: ProviderRegistry) -> None:
        self.db = db
        self.providers = providers

    def fetch_and_store(self, request: BarRequest) -> DatasetSnapshot:
        """Fetch a homogeneous snapshot and atomically retain its provenance."""

        snapshot = self.providers.fetch_bars(request)
        self.db.record_dataset(snapshot.storage_metadata(), snapshot.bars)
        self.db.upsert_instrument_alias(
            {
                "canonical_symbol": snapshot.instrument.canonical_symbol,
                "exchange": snapshot.instrument.exchange,
                "provider_name": snapshot.provenance.provider_name,
                "provider_symbol": snapshot.provenance.provider_symbol,
            },
        )
        token = request.token or snapshot.provenance.provider_symbol
        self.db.upsert_candles(
            snapshot.bars,
            snapshot.instrument.canonical_symbol,
            token,
            snapshot.instrument.exchange,
            snapshot.timeframe,
            adjustment=snapshot.provenance.adjustment.value,
            provider_name=snapshot.provenance.provider_name,
            dataset_id=snapshot.dataset_id,
        )
        return snapshot
