# Data Model & Schema Contracts: Final Audit Remediation

## 1. Domain Entities

### `OpeningTickObservation`
```python
@dataclass(frozen=True)
class OpeningTickObservation:
    symbol: str
    exchange: str
    token: str
    price: float
    exchange_timestamp: datetime
    received_at_utc: datetime
    quality_state: str = "TRUSTED"
    sequence_number: int | None = None
    stream_epoch: int | None = None
```

### `ResearchDataset`
```python
@dataclass
class ResearchDataset:
    name: str
    metadata: dict[str, Any]
    panel: pd.DataFrame
    contributing_dataset_ids: list[str] = field(default_factory=list)
    dq_certification_ids: list[str] = field(default_factory=list)
    dataset_content_hashes: dict[str, str] = field(default_factory=dict)
    frame_certification_id: str = ""
    pit_evidence_hash: str | None = None
```

## 2. Relational Schema & State Transitions

### `research_frame_certifications`
```sql
CREATE TABLE IF NOT EXISTS research_frame_certifications (
    frame_certification_id VARCHAR NOT NULL PRIMARY KEY,
    research_frame_hash VARCHAR NOT NULL,
    contributing_dataset_ids_json VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    basis VARCHAR NOT NULL,
    validator_version VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL,
    dataset_evidence_json VARCHAR DEFAULT '{}',
    dq_certification_ids_json VARCHAR DEFAULT '[]',
    pit_evidence_hash VARCHAR
);
```

### `stream_gaps`
```sql
CREATE TABLE IF NOT EXISTS stream_gaps (
    gap_id VARCHAR NOT NULL PRIMARY KEY,
    token VARCHAR NOT NULL,
    symbol VARCHAR,
    exchange VARCHAR NOT NULL,
    expected_sequence BIGINT NOT NULL,
    received_sequence BIGINT NOT NULL,
    gap_size BIGINT NOT NULL,
    stream_epoch BIGINT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    gap_status VARCHAR NOT NULL DEFAULT 'UNREPAIRED',
    repaired_at TIMESTAMPTZ
);
```

### `run_certification_bundles` & `run_certifications`
- `run_certification_bundles`: `(bundle_id, run_id, dataset_id, status, certified_at, validator_version, ...)`
- `run_certifications`: `(certification_id, bundle_id, category, status, details_json, verified_at)`
  - Categories: `DATA_LINEAGE`, `DATA_QUALITY`, `CAUSALITY`, `PIT_SURVIVORSHIP`, `OOS_WALK_FORWARD`
  - Atomic persistence in a single transaction.
