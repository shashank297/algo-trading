# Phase 2.6 Interface Contracts

## 1. `experiments/statistical_tests.py`

### Probabilistic Sharpe Ratio (PSR)
```python
def compute_psr(
    returns: pd.Series | np.ndarray | list[float],
    benchmark_sharpe: float = 0.0,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
) -> PSRResult:
    """Calculate Probabilistic Sharpe Ratio under non-normal returns.
    
    Formula:
        PSR(SR*) = Phi( (SR - SR*) * sqrt(n - 1) / sqrt(1 - skew*SR + (kurt - 1)/4 * SR^2) )
    where SR is sample non-annualized Sharpe, SR* is non-annualized benchmark Sharpe,
    skew is sample skewness, and kurt is sample kurtosis (normal=3).
    """
    ...
```

### Deflated Sharpe Ratio (DSR)
```python
def compute_dsr(
    returns: pd.Series | np.ndarray | list[float],
    trial_sharpes: list[float] | np.ndarray,
    effective_trials: int | None = None,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
    experiment_family_id: str | None = None,
    trial_ids: list[str] | None = None,
    invalidated_count: int = 0,
) -> DSRResult:
    """Calculate Deflated Sharpe Ratio correcting for multiple testing.
    
    SR_0 = sqrt(V) * [ (1 - gamma) * Phi^{-1}(1 - 1/N) + gamma * Phi^{-1}(1 - 1/(N*e)) ]
    where gamma is Euler-Mascheroni constant (~0.5772156649), N is trial count,
    V is trial Sharpe variance, and DSR = PSR(SR_0).
    """
    ...
```

### Deterministic Bootstrap
```python
def compute_bootstrap_confidence_intervals(
    returns: pd.Series | np.ndarray | list[float],
    fills: pd.DataFrame | None = None,
    confidence_level: float = 0.95,
    n_resamples: int = 1000,
    method: str = "MOVING_BLOCK",
    block_size: int = 10,
    seed: int = 42,
    minimum_observations: int = 20,
) -> dict[str, BootstrapConfidenceIntervals]:
    """Compute deterministic bootstrap confidence intervals for key metrics."""
    ...
```

### Monte Carlo Simulation
```python
def compute_monte_carlo_robustness(
    returns: pd.Series | np.ndarray | list[float],
    fills: pd.DataFrame | None = None,
    n_simulations: int = 1000,
    drawdown_threshold: float = 0.20,
    ruin_threshold: float = 0.50,
    seed: int = 42,
    minimum_observations: int = 20,
) -> MonteCarloRobustnessResult:
    """Simulate return paths and trade sequences to estimate risk distributions."""
    ...
```

---

## 2. `experiments/robustness.py`

### Robustness Evaluator
```python
class RobustnessEvaluator:
    """Evaluates strategy robustness using nested walk-forward, statistical tests, and stress testing."""
    
    def __init__(
        self,
        db: DuckDBManager,
        policy: RobustnessPolicy | None = None,
        india_calendar: MarketCalendar | None = None,
    ) -> None:
        ...

    def evaluate(
        self,
        parent_run_id: str,
        spec: ExperimentSpec,
        *,
        train_size: int = 252,
        val_size: int = 63,
        test_size: int = 63,
        purge_window: int = 5,
        embargo_window: int = 5,
        starting_capital: float = 100_000.0,
    ) -> RobustnessBundle:
        """Run full Phase 2.6 nested walk-forward robustness evaluation and persist bundle."""
        ...
```

### DuckDB Manager Extensions
```python
class DuckDBManager:
    ...
    def save_robustness_evaluation(self, bundle: RobustnessBundle) -> str:
        """Persist immutable robustness evaluation bundle with conflict detection."""
        ...

    def get_robustness_evaluation(self, robustness_id: str) -> RobustnessBundle | None:
        """Retrieve persisted robustness evaluation bundle by ID."""
        ...

    def list_robustness_evaluations(
        self,
        strategy_name: str | None = None,
        experiment_family_id: str | None = None,
    ) -> list[RobustnessBundle]:
        """List persisted robustness evaluations matching filters."""
        ...
```
