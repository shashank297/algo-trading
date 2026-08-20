"""Persist provider-neutral datasets while retaining the legacy candle cache."""

from __future__ import annotations

from typing import Any

from data_platform.contracts import BarRequest, DatasetSnapshot
from data_platform.providers import ProviderRegistry
from data_platform.source_semantics import (
    SourceSemanticsAdapter,
    SourceSemanticsPolicy,
)


from storage.duckdb_manager import DuckDBManager


class DataPlatform:
    """Coordinates provider selection, validation, provenance, ground-truth semantics admission, and local storage."""

    def __init__(
        self,
        db: DuckDBManager,
        providers: ProviderRegistry,
        policy: SourceSemanticsPolicy | None = None,
        require_admission: bool = True,
    ) -> None:
        self.db = db
        self.providers = providers
        self.policy = policy or SourceSemanticsPolicy()

        self.require_admission = require_admission

    def fetch_and_store(
        self,
        request: BarRequest,
        corporate_actions: Any | None = None,
    ) -> DatasetSnapshot:
        """Fetch a homogeneous snapshot and enforce Ground-Truth semantics admission before storing."""

        snapshot = self.providers.fetch_bars(request)

        # Retrieve corporate actions for the symbol if not explicitly supplied
        ca_records = corporate_actions
        if ca_records is None:
            try:
                ca_df = self.db.conn.execute(
                    "SELECT action_type, ex_date, share_multiplier, split_ratio FROM corporate_actions WHERE symbol = ?",
                    [snapshot.instrument.canonical_symbol],
                ).df()
                ca_records = ca_df if not ca_df.empty else []
            except Exception:
                ca_records = []

        # Run Ground-Truth Gateway inference
        semantics = SourceSemanticsAdapter.infer_semantics(
            snapshot.bars,
            ca_records,
            declared_adjustment=snapshot.provenance.adjustment,
            policy=self.policy,
        )

        if self.require_admission and not semantics.is_admitted:
            # Persist quarantine audit record and fail closed
            SourceSemanticsAdapter.persist_detections(self.db, snapshot.dataset_id, semantics)
            raise ValueError(
                f"Historical Ground-Truth Admission Gateway Rejected dataset for {snapshot.instrument.canonical_symbol}: "
                f"status={semantics.validation_status.value}, reasons={[r.value for r in semantics.reasons]}"
            )

        self.db.record_dataset(snapshot.storage_metadata(), snapshot.bars)
        SourceSemanticsAdapter.persist_detections(self.db, snapshot.dataset_id, semantics)

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
