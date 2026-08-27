# Data Model: Phase 2.1 Immutable Research Trial Registry

## Entities & Relational Schemas

### 1. `experiment_families` Table
Stores the pre-registered research hypothesis, configuration bounds, and trial budget.

```sql
CREATE TABLE IF NOT EXISTS experiment_families (
    experiment_family_id VARCHAR PRIMARY KEY,
    definition_hash VARCHAR NOT NULL,
    definition_json VARCHAR NOT NULL,
    maximum_trials BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ
);
```

#### Fields:
- `experiment_family_id`: Unique identifier for the family (e.g. `fam_momentum_opt_v1`).
- `definition_hash`: Canonical SHA-256 hash of all material research parameters (hypothesis, strategies, parameter space, walk-forward structure, cost model, universe, timeframe).
- `definition_json`: Serialized JSON of `ExperimentFamilySpec`.
- `maximum_trials`: Hard maximum trial budget (immutable once trials begin).
- `created_at`: UTC timestamp of pre-registration.
- `started_at`: UTC timestamp when the first trial was reserved/executed.

---

### 2. `research_trials_log` Table
Stores every attempted candidate evaluation, its lifecycle state, metrics, errors, and invalidation status.

```sql
CREATE TABLE IF NOT EXISTS research_trials_log (
    trial_id VARCHAR PRIMARY KEY,
    experiment_family_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    trial_json VARCHAR NOT NULL,
    metrics_json VARCHAR,
    metrics_hash VARCHAR,
    error_message VARCHAR,
    invalidation_reason VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    parent_trial_id VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_trials_family_status ON research_trials_log(experiment_family_id, status);
```

#### Fields:
- `trial_id`: Deterministic SHA-256 hash of the trial definition (excluding lifecycle timestamps and status).
- `experiment_family_id`: Foreign key reference to `experiment_families`.
- `status`: One of `PLANNED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `INVALIDATED`, `CANCELLED`.
- `trial_json`: Serialized JSON of `ResearchTrial` model.
- `metrics_json`: Summary metrics on success (Sharpe, Drawdown, Profit Factor, etc.).
- `metrics_hash`: SHA-256 hash of `metrics_json` for tamper-evidence.
- `error_message`: Error message/trace summary on failure (e.g., `INTERRUPTED_PROCESS` or exception string).
- `invalidation_reason`: Forensic invalidation reason if invalidated (e.g., `DATA_BUG`, `CAUSALITY_VIOLATION`).
- `created_at`, `started_at`, `finished_at`, `invalidated_at`: UTC timestamps.
- `selected`: `True` if this candidate was selected as winning/optimal; `False` otherwise.
- `parent_trial_id`: Optional parent trial identifier for derivative or multi-stage evaluations.

---

## Python Domain Models (`experiments/trials.py`)

### `ExperimentFamilySpec`
```python
class ExperimentFamilySpec(BaseModel):
    experiment_family_id: str
    hypothesis: str
    strategy_names: list[str]
    strategy_versions: list[str]
    universe_snapshot_id: str
    timeframe: str
    feature_versions: list[str]
    cost_model_version: str
    parameter_space: dict[str, Any]
    maximum_trials: int
    selection_metric: str
    walk_forward_design: dict[str, Any]
    regime_conditions: dict[str, Any] = Field(default_factory=dict)
    asset_cluster_conditions: dict[str, Any] = Field(default_factory=dict)
    source_revision: str
    operator_notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def definition_hash(self) -> str: ...
```

### `ResearchTrial`
```python
class ResearchTrial(BaseModel):
    experiment_family_id: str
    strategy_name: str
    strategy_version: str
    scope: str
    timeframe: str
    parameters: dict[str, Any]
    source_revision: str
    data_hash: str
    cost_model_hash: str
    universe_snapshot_id: str | None = None
    feature_version: str | None = None
    frame_certification_id: str | None = None
    fold_id: str | None = None
    train_start: datetime | None = None
    train_end: datetime | None = None
    test_start: datetime | None = None
    test_end: datetime | None = None
    status: TrialStatus = TrialStatus.PLANNED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def trial_id(self) -> str: ...
```
