"""Persist provider-neutral datasets while retaining the legacy candle cache."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from data_platform.adjustments import PriceAdjustmentEngine
from data_platform.contracts import BarRequest, DatasetSnapshot, PriceAdjustment
from data_platform.providers import ProviderRegistry
from data_platform.source_semantics import (
    SourceSemanticsAdapter,
    SourceSemanticsPolicy,
    SourceValidationStatus,
)
from storage.duckdb_manager import DuckDBManager


@dataclass(frozen=True)
class CanonicalDatasetResult:
    """Result of dataset admission and canonical promotion."""

    raw_dataset_id: str
    canonical_dataset_id: str | None
    admission_id: str
    semantics_hash: str
    status: SourceValidationStatus
    bars: pd.DataFrame | None


def admit_and_promote_dataset(
    *,
    snapshot: DatasetSnapshot,
    db: DuckDBManager,
    corporate_actions: pd.DataFrame | list[Any] | None = None,
    target_adjustment: PriceAdjustment = PriceAdjustment.SPLIT_ADJUSTED,
    policy: SourceSemanticsPolicy | None = None,
) -> CanonicalDatasetResult:
    """Institutional Ground-Truth Gateway: persists raw provider observation, validates semantics, applies canonical adjustments, and stores canonical bars."""
    active_policy = policy or SourceSemanticsPolicy()

    # Step 1: Persist immutable raw snapshot first
    db.record_dataset(snapshot.storage_metadata(), snapshot.bars)

    # Step 2: Fetch corporate actions if not supplied (with instrument identity lookup)
    ca_records = corporate_actions
    if ca_records is None:
        try:
            ca_df = db.conn.execute(
                "SELECT action_type, ex_date, share_multiplier, symbol, exchange, dividend_amount "
                "FROM corporate_actions WHERE symbol = ?",
                [snapshot.instrument.canonical_symbol],
            ).df()
            ca_records = ca_df
        except Exception as exc:
            # Raise so promotion fails closed, but raw dataset is already persisted
            raise RuntimeError(
                f"Corporate action lookup failed for {snapshot.instrument.canonical_symbol}: {exc}"
            ) from exc

    # Step 3: Infer source semantics
    semantics = SourceSemanticsAdapter.infer_semantics(
        snapshot.bars,
        ca_records,
        declared_adjustment=snapshot.provenance.adjustment,
        policy=active_policy,
    )
    SourceSemanticsAdapter.persist_detections(db, snapshot.dataset_id, semantics)

    # Step 4: Validate admission status
    if not semantics.is_admitted:
        return CanonicalDatasetResult(
            raw_dataset_id=snapshot.dataset_id,
            canonical_dataset_id=None,
            admission_id=snapshot.dataset_id,
            semantics_hash=semantics.semantics_hash,
            status=semantics.validation_status,
            bars=None,
        )

    # Step 5: Run canonical price & volume adjustment
    ca_df_for_adj = ca_records if isinstance(ca_records, pd.DataFrame) else pd.DataFrame(ca_records)
    canonical_bars = PriceAdjustmentEngine.adjust_ohlcv(
        snapshot.bars,
        corporate_actions=ca_df_for_adj,
        adjustment=target_adjustment,
        source_semantics=semantics,
    )

    # Step 6: Persist canonical instrument alias and canonical bars
    db.upsert_instrument_alias(
        {
            "canonical_symbol": snapshot.instrument.canonical_symbol,
            "exchange": snapshot.instrument.exchange,
            "provider_name": snapshot.provenance.provider_name,
            "provider_symbol": snapshot.provenance.provider_symbol,
        },
    )

    token = getattr(snapshot.instrument, "provider_token", None) or snapshot.provenance.provider_symbol
    db.upsert_candles(
        canonical_bars,
        snapshot.instrument.canonical_symbol,
        token,
        snapshot.instrument.exchange,
        snapshot.timeframe,
        adjustment=target_adjustment.value,
        provider_name=snapshot.provenance.provider_name,
        dataset_id=snapshot.dataset_id,
    )

    return CanonicalDatasetResult(
        raw_dataset_id=snapshot.dataset_id,
        canonical_dataset_id=snapshot.dataset_id,
        admission_id=snapshot.dataset_id,
        semantics_hash=semantics.semantics_hash,
        status=semantics.validation_status,
        bars=canonical_bars,
    )


class DataPlatform:
    """Coordinates provider selection, validation, provenance, ground-truth semantics admission, and local storage."""

    def __init__(
        self,
        db: DuckDBManager,
        providers: ProviderRegistry,
        policy: SourceSemanticsPolicy | None = None,
    ) -> None:
        self.db = db
        self.providers = providers
        self.policy = policy or SourceSemanticsPolicy()

    def fetch_and_store(
        self,
        request: BarRequest,
        corporate_actions: Any | None = None,
    ) -> DatasetSnapshot:
        """Fetch a homogeneous snapshot and enforce Ground-Truth semantics admission before storing."""
        snapshot = self.providers.fetch_bars(request)

        target_adj = request.adjustment if hasattr(request, "adjustment") and request.adjustment is not None else PriceAdjustment.SPLIT_ADJUSTED
        result = admit_and_promote_dataset(
            snapshot=snapshot,
            db=self.db,
            corporate_actions=corporate_actions,
            target_adjustment=target_adj,
            policy=self.policy,
        )

        if result.bars is None or not result.status == SourceValidationStatus.VERIFIED:
            raise ValueError(
                f"Historical Ground-Truth Admission Gateway Rejected dataset for {snapshot.instrument.canonical_symbol}: "
                f"status={result.status.value}"
            )

        return snapshot
