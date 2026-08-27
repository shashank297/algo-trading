# Phase 2.2 — Certified Multi-Timeframe Data: Data Model

## New Tables (Migration 016)

### `derived_datasets`

Persists full lineage for every derived (resampled) dataset.

```sql
CREATE TABLE IF NOT EXISTS derived_datasets (
    derived_dataset_id     VARCHAR NOT NULL PRIMARY KEY,
    source_dataset_ids     VARCHAR NOT NULL,       -- JSON array of canonical source dataset_ids
    source_content_hashes  VARCHAR NOT NULL,       -- JSON array of source content hashes
    symbol                 VARCHAR NOT NULL,
    exchange               VARCHAR NOT NULL,
    timeframe              VARCHAR NOT NULL,        -- '5m', '15m', '30m', '60m'
    adjustment_basis       VARCHAR NOT NULL,        -- PriceAdjustment value
    resampler_version      VARCHAR NOT NULL,        -- e.g. 'session-resampler-v1'
    calendar_version       VARCHAR NOT NULL,        -- e.g. 'builtin-v1'
    start_ts               TIMESTAMPTZ NOT NULL,
    end_ts                 TIMESTAMPTZ NOT NULL,
    row_count              INTEGER NOT NULL,
    content_hash           VARCHAR NOT NULL,        -- SHA256 of derived bar content
    dq_status              VARCHAR NOT NULL DEFAULT 'PENDING',  -- PENDING | CERTIFIED | DQ_FAILED
    dq_report_json         VARCHAR DEFAULT '{}',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### `cross_provider_reconciliations`

Persists cross-provider bar-by-bar comparison records.

```sql
CREATE TABLE IF NOT EXISTS cross_provider_reconciliations (
    reconciliation_id      VARCHAR NOT NULL PRIMARY KEY,
    symbol                 VARCHAR NOT NULL,
    exchange               VARCHAR NOT NULL,
    timeframe              VARCHAR NOT NULL,
    primary_provider       VARCHAR NOT NULL,
    secondary_provider     VARCHAR NOT NULL,
    comparison_version     VARCHAR NOT NULL,         -- e.g. 'cross-provider-v1'
    comparison_date        DATE NOT NULL,
    primary_dataset_id     VARCHAR NOT NULL,
    secondary_dataset_id   VARCHAR,                  -- NULL if secondary unavailable
    total_bars_primary     INTEGER NOT NULL,
    total_bars_secondary   INTEGER,
    bars_match             INTEGER NOT NULL DEFAULT 0,
    bars_tolerance_match   INTEGER NOT NULL DEFAULT 0,
    bars_disagreement      INTEGER NOT NULL DEFAULT 0,
    bars_unavailable       INTEGER NOT NULL DEFAULT 0,
    tolerance_config_json  VARCHAR NOT NULL DEFAULT '{}',
    bar_outcomes_json      VARCHAR NOT NULL DEFAULT '[]',  -- JSON array of per-bar results
    overall_status         VARCHAR NOT NULL,         -- MATCH | PARTIAL_MATCH | DISAGREEMENT | UNAVAILABLE
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## Key Python Entities

### `data_platform/resampling.py`

```python
@dataclass(frozen=True)
class ResampledBar:
    """Single derived OHLCV bar."""
    timestamp: datetime          # UTC open timestamp of this bucket
    open: float
    high: float
    low: float
    close: float
    volume: int
    bucket_bar_count: int        # number of 1m source bars aggregated


@dataclass(frozen=True)
class DerivedDatasetCertification:
    """Registry entry for a derived dataset."""
    derived_dataset_id: str
    source_dataset_ids: list[str]
    source_content_hashes: list[str]
    symbol: str
    exchange: str
    timeframe: str
    adjustment_basis: str
    resampler_version: str
    calendar_version: str
    start_ts: datetime
    end_ts: datetime
    row_count: int
    content_hash: str
    dq_status: str
    dq_report: dict


class SessionBarResampler:
    """
    Derives N-minute OHLCV bars from certified 1m canonical bars.

    Rules:
    - never crosses NSE session boundaries
    - never combines different trading days
    - drops incomplete trailing buckets
    - rejects mixed adjustment basis
    - rejects quarantined/untrusted input
    - preserves all OHLCV aggregation invariants
    """
    RESAMPLER_VERSION: str = "session-resampler-v1"
    SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "30m", "60m")

    def resample(
        self,
        bars_1m: pd.DataFrame,
        target_timeframe: str,
        calendar: MarketCalendar,
        source_adjustment: str,
    ) -> list[ResampledBar]: ...

    def derive_and_certify(
        self,
        source_dataset_id: str,
        bars_1m: pd.DataFrame,
        target_timeframe: str,
        calendar: MarketCalendar,
        source_adjustment: str,
        source_content_hash: str,
        db: DuckDBManager,
    ) -> DerivedDatasetCertification: ...
```

### `data_platform/provider_verification.py`

```python
class ProviderReconciliationResult(str, Enum):
    MATCH = "MATCH"
    TOLERANCE_MATCH = "TOLERANCE_MATCH"
    DISAGREEMENT = "DISAGREEMENT"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationSeverity(str, Enum):
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


@dataclass(frozen=True)
class BarComparisonOutcome:
    timestamp: datetime
    result: ProviderReconciliationResult
    primary_ohlcv: dict
    secondary_ohlcv: dict | None
    field_deltas: dict[str, float]


@dataclass(frozen=True)
class ProviderVerificationReport:
    reconciliation_id: str
    symbol: str
    exchange: str
    timeframe: str
    primary_provider: str
    secondary_provider: str
    bars_match: int
    bars_tolerance_match: int
    bars_disagreement: int
    bars_unavailable: int
    overall_status: str
    bar_outcomes: list[BarComparisonOutcome]


class CrossProviderVerifier:
    """
    Compare a secondary provider observationally against a canonical primary.
    Never blends provider data. Disagreements raise DATA_VERIFICATION_WARNING
    or fail the research admission gate depending on severity configuration.
    """
    COMPARISON_VERSION: str = "cross-provider-v1"

    def verify(
        self,
        primary_bars: pd.DataFrame,
        secondary_bars: pd.DataFrame | None,
        symbol: str,
        exchange: str,
        timeframe: str,
        primary_provider: str,
        secondary_provider: str,
        severity: VerificationSeverity,
        tolerance: dict[str, float] | None,
        db: DuckDBManager,
    ) -> ProviderVerificationReport: ...
```

### `data_platform/dq_derived.py`

```python
@dataclass(frozen=True)
class DerivedDQReport:
    derived_dataset_id: str
    certified: bool
    schema_ok: bool
    ohlc_integrity_ok: bool
    no_duplicates: bool
    session_aligned: bool
    missing_buckets: list[str]
    timestamp_monotonic: bool
    issues: list[str]
```

---

## Table Relationships

```
market_datasets  (canonical source)
    |
    | 1:N
    v
derived_datasets (one per symbol+timeframe+source combination)
    |
    | 1:N (via derived_dataset_id)
    v
historical_candles (derived bars stored with derived_dataset_id tag)

cross_provider_reconciliations
    ← references primary_dataset_id → market_datasets
```

---

## Modification to Existing Tables

### `historical_candles`

No schema change needed. The existing `dataset_id` column stores the `derived_dataset_id` for derived bars, distinguishing them from raw/canonical bars via the `derived_datasets` registry.

### `market_datasets`

No schema change needed. Derived datasets are tracked exclusively in `derived_datasets`.
