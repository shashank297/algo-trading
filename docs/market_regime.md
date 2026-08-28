# Market Context and Deterministic Regime Engine (Phase 2.3)

## 1. Overview & Architecture

The Market Context and Deterministic Raw Market Regime Engine (`trading_stack/market_regime.py`) provides causal, point-in-time evaluated market condition intelligence for the algorithmic trading platform.

The engine strictly separates:
1. **Evidence Ingestion**: Point-in-time filtering of certified market data.
2. **Feature Extraction**: Causal calculation of multi-dimensional market statistics.
3. **Component Scoring**: Normalization into standardized continuous score scales.
4. **Deterministic Classification**: Transparent, versioned classification tree into raw market regimes.

```
+-------------------------------------------------------------+
|               MarketRegimeEngine (v1.0.0)                   |
|                                                             |
|  1. Ingest PIT Evidence (known_at <= decision_time)         |
|  2. Compute 6 Feature Families (Trend, Vol, Breadth, etc.)  |
|  3. Normalize to Continuous Component Scores [-1.0, +1.0]   |
|  4. Classify RawMarketRegime + Compute Deterministic Conf   |
|  5. Bind to Immutable SHA-256 Evidence Hash                 |
+-------------------------------------------------------------+
```

---

## 2. Core Invariant & Point-in-Time Causality

> **Every decision satisfies `known_at <= decision_time` for all evidence used.**
> The same exact evidence + model version + policy version deterministically produces identical raw regime, confidence, component scores, and evidence hash.

### Context Types: EOD vs. INTRADAY
- **`EOD` (End of Day)**: Evaluated after the official trading session close. Uses completed daily bars up to session $D$.
- **`INTRADAY`**: Evaluated at decision timestamp $T$ on session $D$.
  - Daily-style rolling features use completed historical sessions through $D-1$.
  - Certified intraday bars are retained as causal evidence, but do not become synthetic daily observations.
  - Today's daily close, end-of-day volume, post-$T$ intraday bars, and post-$T$ breadth are NEVER visible.

---

## 3. Raw Market Regime Taxonomy

| Regime | Description | Key Conditions |
|---|---|---|
| `BULL_LOW_VOL` | Strong bull market with low volatility and broad participation | $\text{trend\_score} \ge +0.25$, $\text{breadth\_score} \ge +0.15$, $\text{vol\_score} \le +0.15$, $\text{stress} \le 0.40$ |
| `BULL_HIGH_VOL` | Bullish market with elevated realized or implied volatility | $\text{trend\_score} \ge +0.25$, $\text{breadth\_score} \ge +0.05$, $\text{vol\_score} > +0.15$ |
| `SIDEWAYS_LOW_VOL` | Rangebound market with compressed volatility | $\text{vol\_score} \le +0.15$, $\text{stress} < 0.45$, not meeting Bull/Bear/Recovery |
| `SIDEWAYS_HIGH_VOL` | Rangebound or erratic market with elevated volatility | $\text{vol\_score} > +0.15$ or $\text{stress} \ge 0.45$, not meeting Bull/Bear/Recovery |
| `BEAR_HIGH_VOL` | Downtrend with elevated volatility and high stress | $\text{trend\_score} \le -0.20$, $\text{breadth\_score} \le -0.10$ or $\text{stress} \ge 0.45$ |
| `RECOVERY` | Post-drawdown recovery with expanding breadth and positive momentum | $\text{drawdown} \le -10\%$, $\text{trend\_score} > 0$ (or slope $> 0$), $\text{breadth\_score} \ge 0.0$, $\text{downside\_freq} \le 0.10$, $\text{vol\_shock} \le 0.25$ |
| `INSUFFICIENT_CONTEXT` | Critical evidence missing or insufficient history | Benchmark history $< 220$ days, breadth coverage $< 80\%$, or missing critical trend/breadth |

---

## 4. Features & Scoring Formulas

### Trend Family
- Trailing returns: 20-day ($R_{20}$), 60-day ($R_{60}$), 120-day ($R_{120}$).
- Moving average ratios: Close vs. 50 DMA, Close vs. 200 DMA.
- Normalized DMA slopes: 50 DMA slope over 10 bars, 200 DMA slope over 20 bars.
- Normalized `trend_score` in $[-1.0, +1.0]$.
- Versioned weights: hard-required `R20` 0.20, `R60` 0.20, close-vs-50DMA 0.15, and close-vs-200DMA 0.20; optional `R120` 0.10 and each DMA slope 0.075. Trend requires all hard features and at least 75% available weighted evidence.

### Volatility Family
- Realized annualized volatility: 20-day ($\sigma_{20}$), 60-day ($\sigma_{60}$).
- Normalized ATR: $\text{ATR}_{14} / \text{Close}$.
- Rolling 252-day volatility percentile ($P_{\text{vol}}$).
- Optional certified India VIX level (if unavailable, deterministic confidence penalty of $-0.15$).
- Normalized `volatility_score` in $[-1.0, +1.0]$.
- Hard-required evidence is realized 20/60-session volatility and normalized ATR (0.30/0.25/0.25); optional volatility percentile and VIX carry 0.10 each. Volatility requires all hard features and at least 75% available weighted evidence.

### Breadth Family (Point-in-Time Universe)
- Constituent % above 20 DMA, 50 DMA, 200 DMA.
- Advance/Decline ratio: $(\text{Advancing} - \text{Declining}) / \text{Total}$.
- Net New Highs / New Lows (% 52w Highs - % 52w Lows).
- Normalized `breadth_score` in $[-1.0, +1.0]$.
- Each required 20/50/200-DMA and advance/decline coverage is measured independently; the minimum must cover at least 80% of the PIT universe.

### Dispersion & Liquidity
- Cross-sectional 20-day return standard deviation ($\sigma_{\text{CS}}$).
- Market turnover ratio: causal PIT-universe traded value over a trailing 60-session baseline.
- Liquidity percentile: causal 252-session cross-sectional aggregate; unavailable until the full history exists.
- Normalized `dispersion_score` and `liquidity_score` in $[-1.0, +1.0]$.

### Stress Family
- Drawdown from 252-day high ($\text{DD}$).
- Extreme downside day frequency ($R_{\text{daily}} \le -2\%$).
- Overnight gap frequency ($|\text{Gap}| \ge 1\%$).
- Volatility shock: $\max(0, \sigma_{10} / \sigma_{60} - 1.0)$.
- Normalized `stress_score` in $[0.0, 1.0]$ ($0.0$ = benign, $1.0$ = panic/crash).

---

## 5. Storage Lineage & Migration 017

Snapshots are persisted to `market_regime_snapshots` via `DuckDBManager.persist_market_regime_snapshot()`:
- `regime_id`: UUIDv5 generated from canonical input string and namespace.
- `input_evidence_hash`: SHA-256 of canonical input evidence JSON.
- `model_version`: Semantic engine version (e.g. `1.0.0`).
- `policy_hash`: SHA-256 hash of policy threshold parameters.

---

## 6. CLI Usage

### EOD Evaluation
```bash
python research.py --command market-regime --context EOD --as-of 2026-08-27
```

### Intraday Evaluation
```bash
python research.py --command market-regime --context INTRADAY --as-of 2026-08-27 --decision-time 2026-08-27T10:00:00+05:30
```

---

## 7. Explicit Non-Goals (Scope Boundaries)

- **No Strategy Selection**: Phase 2.3 strictly classifies market conditions. It does not select strategies or allocate capital.
- **No Regime Hysteresis**: Dwell times, transition smoothing, and operational switching belong to Phase 2.4.
- **No Asset State Classification**: Single-stock categorization belongs to Phase 2.5.
- **Live Trading**: Remains strictly DISABLED.
