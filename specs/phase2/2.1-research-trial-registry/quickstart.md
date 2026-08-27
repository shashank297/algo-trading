# Quickstart: Phase 2.1 Immutable Research Trial Registry

## 1. Register an Experiment Family
```python
from experiments.trials import ExperimentFamilySpec
from storage.duckdb_manager import DuckDBManager

db = DuckDBManager("market_data.duckdb")

family = ExperimentFamilySpec(
    experiment_family_id="fam_nifty200_momentum_v1",
    hypothesis="Cross-sectional momentum with 20-day lookback yields positive OOS Sharpe on NIFTY 200.",
    strategy_names=["cross_sectional_momentum"],
    strategy_versions=["v1.0.0"],
    universe_snapshot_id="NIFTY200_2026_08_17",
    timeframe="1d",
    feature_versions=["v1"],
    cost_model_version="indian_delivery_2024",
    parameter_space={"long_lookback": [10, 20, 30, 40], "skip_recent": [0, 5]},
    maximum_trials=20,
    selection_metric="sharpe",
    walk_forward_design={"train_size": 252, "test_size": 63, "folds": 5},
    source_revision="git-commit-hash",
)

db.register_experiment_family(family)
```

## 2. Run Governed Research via CLI
```powershell
.\venv\Scripts\python.exe research.py --command run --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --experiment-family-id fam_nifty200_momentum_v1
```

## 3. Query Trial Summary & History
```powershell
# View summary for an experiment family
.\venv\Scripts\python.exe research.py --command research-trials --experiment-family-id fam_nifty200_momentum_v1

# View all failed or invalidated trials
.\venv\Scripts\python.exe research.py --command research-trials --status FAILED
```
