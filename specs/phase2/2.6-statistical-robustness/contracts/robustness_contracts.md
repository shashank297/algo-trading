# Phase 2.6 Interface Contracts

## 1. `experiments/statistical_tests.py`

### Probabilistic Sharpe Ratio (PSR)
```python
def compute_psr(
    returns: pd.Series | np.ndarray | list[float],
    *,
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
    *,
    effective_trials: int | None = None,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
    experiment_family_id: str | None = None,
    trial_ids: list[str] | None = None,
    sharpe_count: int | None = None,
    succeeded_count: int = 0,
    failed_count: int = 0,
    invalidated_count: int = 0,
    deduplicated_count: int = 0,
    trial_policy_version: str = "2.6.0",
    trial_policy_hash: str = "",
) -> DSRResult:
    """Calculate Deflated Sharpe Ratio correcting for multiple testing.
    
    SR_0 = sqrt(V) * [ (1 - gamma) * Phi^{-1}(1 - 1/N) + gamma * Phi^{-1}(1 - 1/(N*e)) ]
    where gamma is Euler-Mascheroni constant (~0.5772156649), N is authoritative effective trial count,
    V is trial Sharpe variance, and DSR = PSR(SR_0). Fails closed without authoritative family.
    """
    ...
```

### Deterministic Bootstrap
```python
def compute_bootstrap_confidence_intervals(
    returns: pd.Series | np.ndarray | list[float],
    *,
    fills: pd.DataFrame | None = None,
    confidence_level: float = 0.95,
    n_resamples: int = 1000,
    method: str = "MOVING_BLOCK",
    block_size: int = 10,
    seed: int = 42,
    minimum_observations: int = 20,
    annualization_factor: float = 252.0,
) -> dict[str, BootstrapConfidenceIntervals]:
    """Compute deterministic bootstrap confidence intervals for key metrics."""
    ...
```

### Monte Carlo Simulation
```python
def compute_monte_carlo_robustness(
    returns: pd.Series | np.ndarray | list[float],
    *,
    fills: pd.DataFrame | None = None,
    n_simulations: int = 1000,
    drawdown_threshold: float = 0.20,
    ruin_threshold: float = 0.50,
    seed: int = 42,
    minimum_observations: int = 20,
    annualization_factor: float = 252.0,
    starting_capital: float = 100_000.0,
) -> MonteCarloRobustnessResult:
    """Simulate return paths to estimate risk distributions and capital ruin."""
    ...
```

---

## 2. `experiments/robustness.py`

### Nested Walk-Forward Splitter
```python
class NestedWalkForwardSplitter:
    """Authoritative generator of 3-stage nested walk-forward folds with dual purge and embargo."""
    
    def split(
        self,
        total_bars: int,
        *,
        train_size: int,
        val_size: int,
        test_size: int,
        purge_window: int = 0,
        embargo_window: int = 0,
    ) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        ...
```

### Robustness Evaluator
```python
class RobustnessEvaluator:
    """Evaluates strategy robustness using nested walk-forward, statistical tests, and stress testing."""
    
    def __init__(
        self,
        db: DuckDBManager,
        *,
        policy: RobustnessPolicy | None = None,
        india_calendar: MarketCalendar | None = None,
        maximum_candidates: int = 32,
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
        purge_window: int | None = None,
        embargo_window: int | None = None,
        starting_capital: float = 100_000.0,
    ) -> RobustnessBundle:
        """Run full Phase 2.6 nested walk-forward robustness evaluation and persist bundle."""
        ...
```

