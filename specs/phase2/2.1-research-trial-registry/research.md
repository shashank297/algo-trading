# Research: Phase 2.1 Immutable Research Trial Registry

## Key Technical Decisions & Invariant Grounding

### 1. Multiple-Testing & Deflated Sharpe Foundation (Bailey & López de Prado)
In quantitative backtesting, selecting the strategy parameter configuration with the highest Sharpe ratio from $N$ evaluated trials introduces selection bias under multiple testing. The Deflated Sharpe Ratio (DSR) adjusts the estimated Sharpe ratio downward as a function of the number of independent trials $N$, the variance of trial returns, the skewness and kurtosis of returns, and the sample length.

To compute DSR legitimately:
1. **$N$ must reflect the total number of tested candidates**, not merely the single winning parameter configuration.
2. If losing candidates are discarded (survivorship bias in research), $N$ appears artificially small (e.g. $N=1$), leading to false statistical confidence and live performance degradation.
3. Therefore, an **immutable, append-only trial registry** where every evaluated candidate is persisted before execution is mathematically required.

### 2. Atomic Trial Slot Reservation
To prevent concurrent workers in mass research from exceeding the pre-registered search budget, reservation must happen within an exclusive DuckDB transaction before candidate execution starts. If `consumed >= maximum_trials`, the worker fails closed immediately.

### 3. Forensic Invalidation vs Deletion
When a backtest is found to be flawed (e.g. data leak or bug in feature calculation), deletion would artificially reduce the research trial count $N$. Invalidation marks `invalidated = True` and records `invalidation_reason` and `invalidated_at`, preserving the record for statistical discounting.
