"""Normalized, validated contracts shared by every market-data provider."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator




class OrderSide(str, Enum):
    """Order direction."""

    BUY = "BUY"
    SELL = "SELL"


class PriceAdjustment(str, Enum):
    """Price adjustment state that must not be mixed inside a backtest."""

    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    BACK_ADJUSTED = "BACK_ADJUSTED"
    TOTAL_RETURN = "TOTAL_RETURN"


class DatasetLifecycleStatus(str, Enum):
    """Lifecycle progression states for market datasets."""

    RAW_RECORDED = "RAW_RECORDED"
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    QUARANTINED = "QUARANTINED"
    SEMANTICS_ADMITTED = "SEMANTICS_ADMITTED"
    AMBIGUOUS = "AMBIGUOUS"
    BLOCKED = "BLOCKED"
    CANONICAL_PROMOTED = "CANONICAL_PROMOTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RawMarketDataset:
    """Immutable verbatim provider dataset before domain validation."""

    raw_dataset_id: str
    symbol: str
    exchange: str
    timeframe: str
    provider_name: str
    provider_symbol: str | None
    provider_token: str | None
    declared_adjustment: PriceAdjustment | None
    timezone_name: str
    retrieved_at: datetime
    raw_payload: str
    raw_hash: str
    hash_algorithm: str = "SHA256"
    hash_version: str = "raw-provider-v1"
    parsed_rows: tuple[dict[str, Any], ...] = ()

    @property
    def bars_df(self) -> pd.DataFrame:
        """Defensive copy DataFrame of parsed provider rows."""
        if not self.parsed_rows:
            return pd.DataFrame(columns=["source_row_number", "timestamp", "open", "high", "low", "close", "volume"])
        return pd.DataFrame(list(self.parsed_rows)).copy(deep=True)


@dataclass(frozen=True)
class RawValidationIssue:
    """A specific structural defect identified on a specific provider row."""

    source_row_number: int
    event_timestamp: datetime | None
    reason_code: str


@dataclass(frozen=True)
class RawValidationResult:
    """Outcome of exhaustive raw structural validation."""

    is_valid: bool
    issues: tuple[RawValidationIssue, ...]
    malformed_row_count: int


@dataclass(frozen=True)
class RawIntakeResult:
    """Full lifecycle result of raw provider intake."""

    raw_dataset_id: str
    raw_hash: str
    raw_status: str
    canonical_dataset_id: str | None
    canonical_status: str | None
    quarantine_reasons: tuple[str, ...]
    bars: pd.DataFrame | None = None


def compute_raw_provider_hash(rows: list[dict[str, Any]] | list[list[Any]] | str | bytes | pd.DataFrame) -> str:
    """Deterministic canonical provider-row hash (raw-provider-v1)."""
    if isinstance(rows, bytes):
        payload_bytes = rows
    elif isinstance(rows, str):
        payload_bytes = rows.encode("utf-8")
    elif isinstance(rows, pd.DataFrame):
        clean_df = rows[[c for c in rows.columns if c not in ("source_row_number", "raw_dataset_id", "retrieved_at")]].copy()
        clean_rows = clean_df.to_dict(orient="records")
        payload_bytes = json.dumps(clean_rows, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    else:
        payload_bytes = json.dumps(rows, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()




class Instrument(BaseModel):
    """Canonical identity plus a provider-specific symbol alias."""

    canonical_symbol: str
    exchange: str
    provider_name: str
    provider_symbol: str
    currency: str = "USD"
    timezone: str = "UTC"

    @field_validator("canonical_symbol", "exchange", "provider_symbol")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("Instrument identifiers must not be empty.")
        return normalized

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if not normalized:
            raise ValueError("Provider name must not be empty.")
        return normalized


class BarRequest(BaseModel):
    """A complete single-provider request for a homogeneous OHLCV dataset."""

    symbol: str
    exchange: str
    timeframe: str
    start: datetime
    end: datetime
    provider_symbol: str | None = None
    token: str | None = None
    adjustment: PriceAdjustment = PriceAdjustment.UNADJUSTED
    timezone: str = "UTC"

    @field_validator("symbol", "exchange")
    @classmethod
    def normalize_request_identifiers(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("Market-data request identifiers must not be empty.")
        return normalized

    @field_validator("timeframe")
    @classmethod
    def normalize_timeframe(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if not normalized:
            raise ValueError("Market-data timeframe must not be empty.")
        return normalized

    def request_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DataProvenance(BaseModel):
    """Immutable origin and transformation details for a dataset snapshot."""

    provider_name: str
    provider_symbol: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_hash: str
    transformation_hash: str
    timezone: str
    adjustment: PriceAdjustment
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetSnapshot(BaseModel):
    """Normalized bars from one provider; cross-provider datasets are forbidden."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    instrument: Instrument
    timeframe: str
    bars: pd.DataFrame
    provenance: DataProvenance
    status: str = "VALID"

    @field_validator("bars")
    @classmethod
    def validate_bars(cls, value: pd.DataFrame) -> pd.DataFrame:
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required.difference(value.columns)
        if missing:
            raise ValueError(f"Bars are missing columns: {sorted(missing)}")
        frame = value.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
        if frame.empty:
            raise ValueError("A market-data snapshot cannot be empty.")
        invalid = (
            (frame["volume"] < 0)
            | (frame["open"] <= 0)
            | (frame["close"] <= 0)
            | (frame["high"] < frame[["open", "close"]].max(axis=1))
            | (frame["low"] > frame[["open", "close"]].min(axis=1))
            | (frame["high"] < frame["low"])
        )
        if invalid.any():
            frame = frame[~invalid].copy()
            if frame.empty:
                raise ValueError("All bar prices violate OHLC invariants.")
        return frame

    @classmethod
    def from_bars(
        cls,
        *,
        instrument: Instrument,
        timeframe: str,
        bars: pd.DataFrame,
        adjustment: PriceAdjustment = PriceAdjustment.UNADJUSTED,
        timezone_name: str = "UTC",
        metadata: dict[str, Any] | None = None,
        provider_name: str | None = None,
        provider_symbol: str | None = None,
    ) -> "DatasetSnapshot":
        """Construct a snapshot and hashes after deterministic normalization."""

        raw_hash = _frame_hash(bars)
        normalized = cls.model_validate(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "bars": bars,
                "provenance": {
                    "provider_name": provider_name or instrument.provider_name,
                    "provider_symbol": provider_symbol or instrument.provider_symbol,
                    "raw_hash": raw_hash,
                    "transformation_hash": _frame_hash(_normalize_for_hash(bars)),
                    "timezone": timezone_name,
                    "adjustment": adjustment,
                    "metadata": metadata or {},
                },
            },
        )
        return normalized

    def storage_metadata(self) -> dict[str, Any]:
        """Return a database-ready row without serializing the dataframe itself."""

        return {
            "dataset_id": self.dataset_id,
            "provider_name": self.provenance.provider_name,
            "provider_symbol": self.provenance.provider_symbol,
            "canonical_symbol": self.instrument.canonical_symbol,
            "exchange": self.instrument.exchange,
            "timeframe": self.timeframe,
            "adjustment": self.provenance.adjustment.value,
            "timezone": self.provenance.timezone,
            "retrieved_at": self.provenance.retrieved_at,
            "raw_hash": self.provenance.raw_hash,
            "transformation_hash": self.provenance.transformation_hash,
            "status": self.status,
            "metadata_json": json.dumps(self.provenance.metadata, sort_keys=True, default=str),
        }


def normalize_symbol(symbol: str) -> str:
    """Normalize a configured symbol without guessing an exchange alias."""

    normalized = str(symbol).strip().upper()
    if not normalized:
        raise ValueError("Symbol must not be empty.")
    return normalized


def _normalize_for_hash(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy().sort_index(axis=1).sort_values("timestamp")


def _frame_hash(frame: pd.DataFrame) -> str:
    from pandas.core.util.hashing import hash_pandas_object

    normalized = _normalize_for_hash(frame)
    digest = hashlib.sha256()
    hashed = hash_pandas_object(normalized, index=True)
    digest.update(hashed.to_numpy().tobytes())
    return digest.hexdigest()




class LiveTickerMode(str, Enum):
    """Streaming modes supported by Angel One SmartStream WebSocket."""

    LTP = "LTP"
    QUOTE = "QUOTE"
    SNAP_QUOTE = "SNAP_QUOTE"
    DEPTH = "DEPTH"


@dataclass(frozen=True, slots=True)
class DepthLevel:
    """Market depth level entry containing price, quantity, and order count."""

    price: float
    quantity: int
    orders: int
    flag: int = 1  # 1 for BUY, 0 for SELL


@dataclass(frozen=True, slots=True)
class BaseMarketEvent:
    """Shared header metadata for all normalized market data stream events."""

    exchange: str
    token: str
    symbol: str | None
    mode: LiveTickerMode
    exchange_timestamp: datetime | None
    received_at_utc: datetime
    received_monotonic_ns: int
    raw_packet_size: int
    feed_latency_ms: float | None = None
    dispatch_latency_ms: float | None = None
    quality_state: str = "TRUSTED"


@dataclass(frozen=True, slots=True)
class LtpTick(BaseMarketEvent):
    """Mode 1: Last Traded Price event."""

    sequence_number: int = 0
    ltp: float = 0.0


@dataclass(frozen=True, slots=True)
class QuoteTick(LtpTick):
    """Mode 2: Quote event extending LTP with volume and session day OHLC."""

    last_traded_qty: int = 0
    average_traded_price: float = 0.0
    cumulative_volume: int = 0
    total_buy_qty: float = 0.0
    total_sell_qty: float = 0.0
    day_open: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    day_close: float = 0.0


@dataclass(frozen=True, slots=True)
class SnapQuoteTick(QuoteTick):
    """Mode 3: Snap Quote extending Quote with OI, circuits, 52-week levels, and Best-5 depth."""

    last_traded_timestamp: datetime | None = None
    open_interest: int | None = None
    open_interest_change_raw: int | None = None
    open_interest_change_pct: float | None = None
    oi_change_pct: float | None = None
    upper_circuit: float | None = None
    lower_circuit: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    best_5_buy: tuple[DepthLevel, ...] = ()
    best_5_sell: tuple[DepthLevel, ...] = ()


@dataclass(frozen=True, slots=True)
class Depth20Snapshot(BaseMarketEvent):
    """Mode 4: Full 20-level order book depth snapshot."""

    packet_received_time: int | None = None
    bids: tuple[DepthLevel, ...] = ()
    asks: tuple[DepthLevel, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    """Order book snapshot with top bids and asks."""

    bids: tuple[DepthLevel, ...] = ()
    asks: tuple[DepthLevel, ...] = ()


# Backward compatible union type for market data consumers
MarketDataEvent = LtpTick | QuoteTick | SnapQuoteTick | Depth20Snapshot
LiveTick = LtpTick | QuoteTick | SnapQuoteTick


