# Immutable Research Trial Registry (Phase 2.1)

## 1. Why Research Trial Accounting Exists

In quantitative algorithmic trading, strategy selection bias under multiple testing is the single most common cause of backtest overfitting. When a researcher tests $N$ candidate parameter configurations, features, or rule variations and selects the candidate with the highest Sharpe ratio, the expected maximum Sharpe ratio increases purely due to search intensity:

$$\mathbb{E}[\max_{i=1\dots N} \text{Sharpe}_i] > \mathbb{E}[\text{Sharpe}_i]$$

To properly evaluate strategy statistical significance using:
- **Probabilistic Sharpe Ratio (PSR)**
- **Deflated Sharpe Ratio (DSR)** (Bailey and López de Prado, 2014)
- **Family-Wise Error Rate (FWER) & False Discovery Rate (FDR)** corrections
- **Hansen's Superior Predictive Ability (SPA) / White's Reality Check**

the statistical testing procedure requires the **actual total number of distinct research attempts ($N$)**, the variance of returns across all attempted candidates, and the sample characteristics.

If unsuccessful or losing research trials are deleted, pruned, or overwritten, $N$ appears artificially small (e.g. $N=1$), leading to catastrophic overconfidence in backtested performance.

### Central Invariant
> **"Every materially distinct attempted research candidate is retained, including unsuccessful candidates, so future multiple-testing and Deflated Sharpe analysis can use the real research search count."**

Phase 2.1 creates the trustworthy, auditable, immutable trial registry foundation required to compute these statistical controls correctly in subsequent phases.

---

## 2. Domain Models

### `ExperimentFamilySpec` (`experiments/trials.py`)
Represents a pre-registered research hypothesis, parameter search space, and search budget.

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
    def definition_hash(self) -> str:
        """Deterministic SHA-256 hash of the material research specification."""
```

#### Immutability & Budget Integrity
- Once research begins for an experiment family, its material definition is immutable.
- A researcher **cannot** observe losing trials and silently increase `maximum_trials` for the same family. Extending search budgets or changing hypotheses requires creating a new experiment family with distinct identity.

---

### `ResearchTrial` (`experiments/trials.py`)
Represents one materially distinct research evaluation.

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
    symbol: str | None = None
    universe_snapshot_id: str | None = None
    feature_version: str | None = None
    cost_model_version: str | None = None
    frame_certification_id: str | None = None
    fold_id: str | None = None
    train_start: datetime | None = None
    train_end: datetime | None = None
    test_start: datetime | None = None
    test_end: datetime | None = None
    parent_trial_id: str | None = None
    status: TrialStatus = TrialStatus.PLANNED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def trial_id(self) -> str:
        """Deterministic SHA-256 hash of the material trial inputs."""
```

---

## 3. Trial Counting Semantics

### What Counts as a Trial
Any materially distinct candidate evaluation, including variations in:
- Strategy algorithm or strategy version
- Parameter configuration values
- Feature definition or version
- Underlying dataset hash / data lineage
- Universe or universe snapshot members
- Timeframe
- Fold or research date window
- Transaction cost model

In walk-forward parameter optimization, **every individual candidate evaluated on each fold is recorded as a distinct trial**.

### What Does NOT Count as a Trial
Operational operations that do not evaluate new hypotheses:
- Reading existing backtest results
- Generating reports or rendering dashboard charts
- Reloading already persisted data
- Retrying transient database write locks
- Exact deterministic resume of already-completed trials

---

## 4. Lifecycle States & Audit Retention

Trials transition through strict lifecycle states:
1. `PLANNED`: Trial definition created.
2. `RUNNING`: Slot reserved in DuckDB transaction; backtest in progress.
3. `SUCCEEDED`: Backtest finished cleanly; metrics and metrics hash recorded.
4. `FAILED`: Exception raised during execution; error message recorded.
5. `INVALIDATED`: Forensic invalidation (e.g. data leak or code defect discovered later).
6. `CANCELLED`: Explicitly cancelled before or during execution.

### Losing & Failed Candidate Retention
Losing candidates are retained with `status = 'SUCCEEDED'` and `selected = False`. Failed evaluations are retained with `status = 'FAILED'`. **No trial rows are ever deleted.**

### Forensic Invalidation
When backtest outputs are invalidated, `invalidate_trial(trial_id, reason)` records:
- `invalidated = True`
- `invalidation_reason` (e.g. `DATA_BUG`, `CAUSALITY_VIOLATION`)
- `invalidated_at`

The original parameters, lineage, and metrics remain intact in the database for post-mortem audits and statistical discounting.

---

## 5. Trial Budget & Pre-Evaluation Reservation

1. **Pre-Evaluation Enforcement**: Before `_run()` or backtest execution begins, `create_research_trial(trial)` atomically checks:
   $$\text{consumed} + 1 \le \text{maximum\_trials}$$
   If `consumed >= maximum_trials`, execution raises `RuntimeError("Experiment family trial budget exhausted.")` immediately before running candidate $N+1$.
2. **Concurrency Safety**: DuckDB transactions (`with self.transaction():`) prevent concurrent worker threads in mass research from racing to exceed `maximum_trials`.

---

## 6. Interrupted Process Recovery

If a worker or host process crashes while trials are `RUNNING`:
- On startup / recovery, `recover_interrupted_research_trials()` transitions orphaned `RUNNING` trials to `FAILED` with `error_message = 'INTERRUPTED_PROCESS'`.
- Running trials are never silently converted to `SUCCEEDED`.

---

## 7. CLI Reference (Read-Only)

```powershell
# View summary and trial counts for an experiment family
.\venv\Scripts\python.exe research.py --command research-trials --experiment-family-id fam_nifty200_momentum_v1

# Inspect a specific research trial by ID
.\venv\Scripts\python.exe research.py --command research-trials --trial-id <trial_hash>

# List trials filtered by status
.\venv\Scripts\python.exe research.py --command research-trials --status FAILED

# List all registered families and global trial count
.\venv\Scripts\python.exe research.py --command research-trials
```

The CLI is strictly read-only; no deletion or destructive commands exist.
