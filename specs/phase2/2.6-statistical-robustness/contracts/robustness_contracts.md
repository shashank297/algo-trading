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

### Deflated Sharpe Ratio (DSR) & Statistical Primitive
```python
class TrialCountSource(str, Enum):
    """Authoritative provenance source of trial multiplicity count for DSR."""
    PHASE2_1_REGISTRY = "PHASE2_1_REGISTRY"
    MANUAL_STATISTICAL_INPUT = "MANUAL_STATISTICAL_INPUT"


def compute_dsr_statistic(
    returns: pd.Series | np.ndarray | list[float],
    trial_sharpes: list[float] | np.ndarray,
    *,
    effective_trials: int | None = None,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
) -> DSRResult:
    """Pure mathematical Deflated Sharpe Ratio calculation primitive.
    
    Returns mathematical DSR and SR_0 with trial_count_source=MANUAL_STATISTICAL_INPUT
    and status=INSUFFICIENT_EVIDENCE (cannot produce authoritative VALID Phase 2.6 evidence).
    """
    ...


def compute_dsr(
    returns: pd.Series | np.ndarray | list[float],
    trial_sharpes: list[float] | np.ndarray,
    *,
    trial_count_source: TrialCountSource = TrialCountSource.MANUAL_STATISTICAL_INPUT,
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
    
    Only authoritative registry-backed execution (trial_count_source=PHASE2_1_REGISTRY)
    with non-empty experiment_family_id and verified trial_ids produces EvidenceStatus.VALID.
    Fails closed with UNVERIFIED_TRIAL_REGISTRY_PROVENANCE on manual or unverified input.
    """
    ...
```

### Deterministic Bootstrap
```python
class ExpectancyBasis(str, Enum):
    """Basis for bootstrap expectancy confidence intervals."""
    NET_TRADE_PNL = "NET_TRADE_PNL"
    PERIOD_RETURN = "PERIOD_RETURN"


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
    """Compute deterministic bootstrap confidence intervals for key metrics.
    
    When authoritative trade observations exist in fills:
    Resamples actual trade-PnL observations directly; expectancy_basis = NET_TRADE_PNL.
    When no fills exist:
    Resamples period returns; expectancy_basis = PERIOD_RETURN.
    """
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
    
    def split_plans(
        self,
        total_bars: int,
        *,
        train_size: int,
        val_size: int,
        test_size: int,
        purge_window: int = 0,
        embargo_window: int = 0,
    ) -> list[FoldSplitPlan]:
        """Generate structured fold plans. Fails closed with ValueError(PURGE_WINDOW_EXHAUSTS_TRAIN)
        or ValueError(PURGE_WINDOW_EXHAUSTS_VALIDATION) if purge_window exhausts a stage."""
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

