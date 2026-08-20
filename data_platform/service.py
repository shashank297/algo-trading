"""Persist provider-neutral datasets while retaining the legacy candle cache."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from data_platform.adjustments import PriceAdjustmentEngine
from data_platform.contracts import (
    BarRequest,
    DatasetLifecycleStatus,
    DatasetSnapshot,
    Instrument,
    PriceAdjustment,
    RawIntakeResult,
    RawMarketDataset,
    compute_raw_provider_hash,
)
from data_platform.providers import ProviderRegistry
from data_platform.source_semantics import (
    AmbiguousSourceBasisError,
    SourceSemanticsAdapter,
    SourceSemanticsPolicy,
    SourceValidationStatus,
)
from data_platform.validators import RawStructuralValidator
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
    raw_dataset_id: str | None = None,
) -> CanonicalDatasetResult:
    """Institutional Ground-Truth Gateway: validates semantics, applies canonical adjustments, and stores canonical bars."""
    active_policy = policy or SourceSemanticsPolicy()
    parent_id = raw_dataset_id or snapshot.dataset_id

    # Step 1: Persist snapshot metadata if not already recorded via raw intake
    if raw_dataset_id is None:
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
            # Raise so promotion fails closed
            raise RuntimeError(
                f"Corporate action lookup failed for {snapshot.instrument.canonical_symbol}: {exc}"
            ) from exc

    # Step 2: Infer source semantics
    try:
        semantics = SourceSemanticsAdapter.infer_semantics(
            snapshot.bars,
            ca_records,
            declared_adjustment=snapshot.provenance.adjustment,
            policy=active_policy,
        )
        SourceSemanticsAdapter.persist_detections(db, snapshot.dataset_id, semantics)
    except AmbiguousSourceBasisError:
        return CanonicalDatasetResult(
            raw_dataset_id=parent_id,
            canonical_dataset_id=None,
            admission_id=snapshot.dataset_id,
            semantics_hash="",
            status=SourceValidationStatus.CONTRACT_CONFLICT,
            bars=None,
        )

    # Step 3: Validate admission status
    if not semantics.is_admitted:
        return CanonicalDatasetResult(
            raw_dataset_id=parent_id,
            canonical_dataset_id=None,
            admission_id=snapshot.dataset_id,
            semantics_hash=semantics.semantics_hash,
            status=semantics.validation_status,
            bars=None,
        )

    # Step 4: Run canonical price & volume adjustment
    ca_df_for_adj = ca_records if isinstance(ca_records, pd.DataFrame) else pd.DataFrame(ca_records)
    canonical_bars = PriceAdjustmentEngine.adjust_ohlcv(
        snapshot.bars,
        corporate_actions=ca_df_for_adj,
        adjustment=target_adjustment,
        source_semantics=semantics,
    )

    # Step 5: Persist canonical instrument alias and canonical bars
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
        raw_dataset_id=parent_id,
        canonical_dataset_id=snapshot.dataset_id,
        admission_id=snapshot.dataset_id,
        semantics_hash=semantics.semantics_hash,
        status=semantics.validation_status,
        bars=canonical_bars,
    )


def ingest_raw_provider_dataset(
    *,
    bars: pd.DataFrame | list[dict[str, Any]] | tuple[dict[str, Any], ...],
    symbol: str,
    exchange: str,
    timeframe: str,
    provider_name: str,
    provider_symbol: str | None = None,
    provider_token: str | None = None,
    declared_adjustment: PriceAdjustment | None = None,
    timezone_name: str = "Asia/Kolkata",
    retrieved_at: datetime | None = None,
    raw_payload: str | bytes | None = None,
    db: DuckDBManager,
    policy: SourceSemanticsPolicy | None = None,
    corporate_actions: pd.DataFrame | list[Any] | None = None,
    target_adjustment: PriceAdjustment = PriceAdjustment.SPLIT_ADJUSTED,
    existing_raw_dataset_id: str | None = None,
) -> RawIntakeResult:
    """Universal forensic ingestion gateway for raw provider responses.
    
    1. Durably commits verbatim provider observations before running validation.
    2. Runs exhaustive structural validation.
    3. If malformed: atomically records historical quarantine + row-level issues and blocks canonical store.
    4. If structurally valid: promotes through source-semantics admission and canonical adjustment.
    """
    retrieval_time = retrieved_at or datetime.now(timezone.utc)
    raw_id = existing_raw_dataset_id or str(uuid.uuid4())

    # 1. Normalize rows into parsed_rows tuple preserving row ordinals
    if isinstance(bars, pd.DataFrame):
        row_dicts = bars.to_dict(orient="records")
    else:
        row_dicts = list(bars)

    parsed_rows_list = []
    for idx, r in enumerate(row_dicts):
        row_copy = dict(r)
        row_copy["source_row_number"] = idx
        parsed_rows_list.append(row_copy)
    parsed_rows_tuple = tuple(parsed_rows_list)

    # 2. Compute deterministic content hash
    raw_hash = compute_raw_provider_hash(parsed_rows_list)
    payload_str = (
        raw_payload if isinstance(raw_payload, str)
        else raw_payload.decode("utf-8") if isinstance(raw_payload, bytes)
        else json.dumps(parsed_rows_list, sort_keys=True, default=str)
    )

    raw_dataset = RawMarketDataset(
        raw_dataset_id=raw_id,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        provider_name=provider_name,
        provider_symbol=provider_symbol,
        provider_token=provider_token,
        declared_adjustment=declared_adjustment,
        timezone_name=timezone_name,
        retrieved_at=retrieval_time,
        raw_payload=payload_str,
        raw_hash=raw_hash,
        parsed_rows=parsed_rows_tuple,
    )

    # 3. Durably commit raw provider observation before running validation (if not already recorded)
    if existing_raw_dataset_id is None:
        db.persist_raw_dataset(raw_dataset)

    # 4. Run exhaustive structural validator
    validation = RawStructuralValidator.validate(parsed_rows_tuple)

    if not validation.is_valid:
        quarantine_id = str(uuid.uuid4())
        db.record_historical_quarantine(
            quarantine_id=quarantine_id,
            raw_dataset_id=raw_id,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            provider_name=provider_name,
            raw_hash=raw_hash,
            malformed_row_count=validation.malformed_row_count,
            issues=validation.issues,
        )
        quarantine_reasons = tuple(sorted(set(i.reason_code for i in validation.issues)))
        return RawIntakeResult(
            raw_dataset_id=raw_id,
            raw_hash=raw_hash,
            raw_status=DatasetLifecycleStatus.QUARANTINED.value,
            canonical_dataset_id=None,
            canonical_status=None,
            quarantine_reasons=quarantine_reasons,
            bars=None,
        )

    # 5. Transition to STRUCTURALLY_VALID
    db.update_dataset_lifecycle_status(raw_id, DatasetLifecycleStatus.STRUCTURALLY_VALID.value)

    # 6. Construct domain DatasetSnapshot
    clean_frame = pd.DataFrame(list(parsed_rows_tuple))
    clean_frame["timestamp"] = pd.to_datetime(clean_frame["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        clean_frame[col] = pd.to_numeric(clean_frame[col])

    snapshot = DatasetSnapshot.from_bars(
        instrument=Instrument(
            canonical_symbol=symbol,
            exchange=exchange,
            provider_name=provider_name,
            provider_symbol=provider_symbol or symbol,
        ),
        timeframe=timeframe,
        bars=clean_frame,
        adjustment=declared_adjustment or PriceAdjustment.UNADJUSTED,
        timezone_name=timezone_name,
        provider_name=provider_name,
        provider_symbol=provider_symbol,
    )

    # 7. Route through Ground-Truth admission and promotion
    promotion = admit_and_promote_dataset(
        snapshot=snapshot,
        db=db,
        corporate_actions=corporate_actions,
        target_adjustment=target_adjustment,
        policy=policy,
        raw_dataset_id=raw_id,
    )

    if promotion.status == SourceValidationStatus.VERIFIED or (promotion.bars is not None and not promotion.bars.empty):
        db.update_dataset_lifecycle_status(
            dataset_id=snapshot.dataset_id,
            status=DatasetLifecycleStatus.CANONICAL_PROMOTED.value,
            parent_dataset_id=raw_id,
        )
        return RawIntakeResult(
            raw_dataset_id=raw_id,
            raw_hash=raw_hash,
            raw_status=DatasetLifecycleStatus.STRUCTURALLY_VALID.value,
            canonical_dataset_id=promotion.canonical_dataset_id,
            canonical_status=promotion.status.value,
            quarantine_reasons=(),
            bars=promotion.bars,
        )
    else:
        db.update_dataset_lifecycle_status(
            dataset_id=snapshot.dataset_id,
            status=promotion.status.value,
            parent_dataset_id=raw_id,
        )
        return RawIntakeResult(
            raw_dataset_id=raw_id,
            raw_hash=raw_hash,
            raw_status=DatasetLifecycleStatus.STRUCTURALLY_VALID.value,
            canonical_dataset_id=None,
            canonical_status=promotion.status.value,
            quarantine_reasons=(),
            bars=None,
        )


def recover_incomplete_raw_intakes(
    db: DuckDBManager,
    policy: SourceSemanticsPolicy | None = None,
) -> list[RawIntakeResult]:
    """Find and reconcile any raw datasets stranded in 'RAW_RECORDED' status after a crash."""
    stranded = db.conn.execute(
        """
        SELECT dataset_id, symbol, exchange, timeframe, provider_name, provider_symbol, provider_token, declared_adjustment
        FROM market_datasets
        WHERE lifecycle_status = 'RAW_RECORDED'
        """
    ).fetchall()

    results = []
    for (
        dataset_id,
        symbol,
        exchange,
        timeframe,
        provider_name,
        provider_symbol,
        provider_token,
        declared_adj_str,
    ) in stranded:
        raw_rows = db.conn.execute(
            """
            SELECT source_row_number, timestamp_raw, open_raw, high_raw, low_raw, close_raw, volume_raw, raw_row_json
            FROM raw_bar_observations
            WHERE raw_dataset_id = ?
            ORDER BY source_row_number
            """,
            [dataset_id],
        ).fetchall()

        if not raw_rows:
            db.update_dataset_lifecycle_status(dataset_id, DatasetLifecycleStatus.FAILED.value)
            continue

        parsed_rows = []
        for r in raw_rows:
            try:
                row_dict = json.loads(r[7])
            except Exception:
                row_dict = {
                    "source_row_number": r[0],
                    "timestamp": r[1],
                    "open": r[2],
                    "high": r[3],
                    "low": r[4],
                    "close": r[5],
                    "volume": r[6],
                }
            parsed_rows.append(row_dict)

        decl_adj = PriceAdjustment(declared_adj_str) if declared_adj_str else None
        res = ingest_raw_provider_dataset(
            bars=parsed_rows,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            provider_name=provider_name,
            provider_symbol=provider_symbol,
            provider_token=provider_token,
            declared_adjustment=decl_adj,
            db=db,
            policy=policy,
            existing_raw_dataset_id=dataset_id,
        )
        results.append(res)

    return results


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

        target_adj = (
            request.adjustment
            if hasattr(request, "adjustment") and request.adjustment is not None
            else PriceAdjustment.SPLIT_ADJUSTED
        )
        result = admit_and_promote_dataset(
            snapshot=snapshot,
            db=self.db,
            corporate_actions=corporate_actions,
            target_adjustment=target_adj,
            policy=self.policy,
        )

        if result.bars is None or result.status != SourceValidationStatus.VERIFIED:
            raise ValueError(
                f"Historical Ground-Truth Admission Gateway Rejected dataset for {snapshot.instrument.canonical_symbol}: "
                f"status={result.status.value}"
            )

        return snapshot
