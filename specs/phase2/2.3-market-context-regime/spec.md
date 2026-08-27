# Feature Specification: Phase 2.3 — Market Context + Deterministic Regime Engine

## 1. Purpose & Core Invariant

Phase 2.3 implements a causal, versioned, deterministic Market Context and Raw Market Regime Engine (`trading_stack/market_regime.py`).
The engine ingests certified historical and intraday market evidence to compute point-in-time market context features, normalized component scores, and a discrete raw market regime classification.

### Central Invariant

> **"Every market-regime decision must satisfy `known_at <= decision_time` for all evidence used. The same (exact evidence, model version, policy version) deterministically produces identical raw_regime, confidence, component scores, and evidence hash. No future or unconfirmed information may leak into a historical decision."**

### Explicit Non-Goals
Phase 2.3 strictly describes market conditions. It does **NOT**:
- Select or rank trading strategies
- Allocate capital or size positions
- Route or submit broker orders
- Implement regime hysteresis, state dwell, or operational transition smoothing (deferred to Phase 2.4)
- Implement single-stock asset state classification (deferred to Phase 2.5)

---

## 2. Actors & Scope

| Actor | Responsibility |
|---|---|
| Strategy Pipeline & Research Engine | Consumes deterministic market context snapshots for causal multi-regime research |
| Market Regime Engine | Computes features, component scores, and raw regime classification |
| Storage Manager (`DuckDBManager`) | Persists and queries immutable `market_regime_snapshots` with full lineage |
| Operator CLI (`research.py`) | Provides CLI interface `--command market-regime` with historical point-in-time safety |

---

## 3. Domain Model & Enums

### 3.1 `MarketContextType`
- `EOD`: End-of-day evaluation for trading session $D$. Evaluated after official session close with completed daily bars and full session breadth.
- `INTRADAY`: Intraday evaluation at decision timestamp $T$ on session $D$. Uses completed daily bars through session $D-1$ and completed derived intraday bars up to $T$.

### 3.2 `RawMarketRegime` Taxonomy
- `BULL_LOW_VOL`: Strong positive trend, healthy breadth, low realized volatility, low stress.
- `BULL_HIGH_VOL`: Positive trend and positive breadth with elevated realized/implied volatility.
- `SIDEWAYS_LOW_VOL`: Neutral/flat trend, mixed breadth, compressed volatility, low stress.
- `SIDEWAYS_HIGH_VOL`: Neutral/flat trend, mixed or deteriorating breadth, elevated volatility.
- `BEAR_HIGH_VOL`: Negative trend, negative breadth, high volatility, significant drawdown or stress.
- `RECOVERY`: Prior deep drawdown/stress followed by improving trend, expanding breadth, and declining stress.
- `INSUFFICIENT_CONTEXT`: Critical evidence missing (e.g. insufficient benchmark history, missing breadth universe, or uncertified source data).

### 3.3 `MarketRegimeFeatures`
- **Trend Features**:
  - Benchmark 20-session return ($R_{20}$), 60-session return ($R_{60}$), 120-session return ($R_{120}$)
  - Benchmark close vs 50 DMA ratio ($C / \text{DMA}_{50} - 1$), close vs 200 DMA ratio ($C / \text{DMA}_{200} - 1$)
  - 50 DMA slope (trailing 10-bar normalized change), 200 DMA slope (trailing 20-bar normalized change)
- **Volatility Features**:
  - 20-session annualized realized volatility ($\sigma_{20}$), 60-session annualized realized volatility ($\sigma_{60}$)
  - Normalized ATR ($\text{ATR}_{14} / \text{Close}$)
  - Realized volatility percentile over trailing 252 sessions ($P_{\text{vol}}$)
  - Optional India VIX level ($VIX$) when certified and available
- **Breadth Features** (computed over PIT eligible universe):
  - % of eligible universe members above 20 DMA
  - % of eligible universe members above 50 DMA
  - % of eligible universe members above 200 DMA
  - Advance / Decline ratio ($A/D$) over trailing 1-session and 5-session
  - Net New Highs / New Lows (% 52-week highs - % 52-week lows)
- **Dispersion Features**:
  - Cross-sectional return standard deviation ($\sigma_{\text{CS}}$) over 20 sessions
  - Cross-sectional volatility dispersion ($\text{MAD}_{\text{vol}}$)
- **Liquidity Features**:
  - Median daily traded value ($\text{ADV}_{20}$) across PIT universe
  - Aggregate market turnover ratio vs 60-day median
  - Trailing liquidity percentile
- **Stress Features**:
  - Current benchmark drawdown from 252-day peak ($\text{DD}$)
  - Frequency of extreme downside days ($<-2.0\%$) over trailing 20 sessions
  - Overnight gap frequency ($|\text{Gap}| > 1.0\%$) over trailing 20 sessions
  - Volatility shock ratio ($\sigma_{10} / \sigma_{60}$)
  - Liquidity deterioration ratio ($\text{Turnover}_{5} / \text{Turnover}_{60}$)

### 3.4 `MarketRegimeComponentScores`
Normalized continuous metrics on $[-1.0, +1.0]$:
- `trend_score`: $[-1.0, +1.0]$ (+1.0 = strong bull, -1.0 = strong bear)
- `volatility_score`: $[-1.0, +1.0]$ (+1.0 = extreme high vol, -1.0 = extremely compressed vol)
- `breadth_score`: $[-1.0, +1.0]$ (+1.0 = broad market participation, -1.0 = widespread breakdowns)
- `dispersion_score`: $[-1.0, +1.0]$ (+1.0 = high stock-picking dispersion, -1.0 = correlated lockstep)
- `liquidity_score`: $[-1.0, +1.0]$ (+1.0 = deep liquid conditions, -1.0 = illiquid crunch)
- `stress_score`: $[0.0, 1.0]$ ($0.0$ = benign market, $1.0$ = panic liquidation / crash)

### 3.5 `MarketRegimeSnapshot`
- `regime_id`: Deterministic UUID/String combining `market:context_type:as_of:decision_time:evidence_hash:model_version`
- `market`: e.g. `NSE`
- `benchmark`: e.g. `NIFTY 50`
- `context_type`: `EOD` or `INTRADAY`
- `as_of`: Date of evaluation
- `decision_time`: Exact UTC/IST ISO timestamp of decision
- `raw_regime`: Enum value
- `confidence`: $[0.0, 1.0]$
- Component scores: `trend_score`, `volatility_score`, `breadth_score`, `dispersion_score`, `liquidity_score`, `stress_score`
- `input_evidence_json`: Canonical JSON with input dataset IDs, content hashes, member counts, VIX ID
- `input_evidence_hash`: SHA-256 hash of canonical input evidence
- `model_version`: Semantic version (e.g. `1.0.0`)
- `policy_version`: Policy version string (e.g. `1.0.0`)
- `policy_hash`: SHA-256 hash of classification thresholds
- `calendar_version`: Active trading calendar version
- `missing_evidence_json`: List of missing optional/critical evidence reasons

---

## 4. User Stories & Functional Requirements

### US1 — Causal Point-in-Time Feature Calculation (P1)
**Requirements**:
- All feature computations must strictly use bars and universe records with `known_at <= decision_time`.
- In `INTRADAY` context (e.g. 10:00 IST), the session's future close, final daily volume, afternoon intraday bars, and end-of-day breadth must NEVER be visible.
- Daily-style rolling indicators in `INTRADAY` context use the latest completed session ($D-1$).
- Mutating a future bar or future closing price produces zero changes in features, component scores, confidence, or evidence hash.

### US2 — Point-in-Time Universe Breadth & Dispersion (P1)
**Requirements**:
- Breadth and dispersion calculations evaluate only assets active in the PIT universe snapshot visible at `decision_time`.
- An asset added to the index at $T+1$ must not appear in the numerator or denominator at time $T$.
- If a constituent lacks required minimum history (e.g. newly listed stock), its state is not fabricated; it is excluded from the certified denominator deterministically.

### US3 — Optional India VIX Handling with Confidence Penalty (P1)
**Requirements**:
- If certified PIT India VIX is available with `known_at <= decision_time`, it is incorporated into volatility and stress scoring.
- If VIX is unavailable, no synthetic or default VIX value (e.g. 15.0) is fabricated.
- Absence of optional VIX reduces overall confidence deterministically (e.g. $-0.15$ confidence penalty).

### US4 — Deterministic Component Scoring & Raw Classification (P1)
**Requirements**:
- Features map to continuous component scores via versioned deterministic transforms.
- Decision tree / threshold rules map component scores into the 7 `RawMarketRegime` states:
  - `BULL_LOW_VOL`: $\text{trend\_score} \ge +0.3$, $\text{breadth\_score} \ge +0.2$, $\text{volatility\_score} \le +0.2$, $\text{stress\_score} \le 0.35$.
  - `BULL_HIGH_VOL`: $\text{trend\_score} \ge +0.2$, $\text{breadth\_score} \ge +0.1$, $\text{volatility\_score} > +0.2$.
  - `SIDEWAYS_LOW_VOL`: $|\text{trend\_score}| < 0.3$, $\text{volatility\_score} \le +0.1$, $\text{stress\_score} \le 0.35$.
  - `SIDEWAYS_HIGH_VOL`: $|\text{trend\_score}| < 0.3$, $\text{volatility\_score} > +0.1$.
  - `BEAR_HIGH_VOL`: $\text{trend\_score} \le -0.2$, $\text{breadth\_score} \le -0.1$, $\text{volatility\_score} > 0.0$ or $\text{stress\_score} \ge 0.5$.
  - `RECOVERY`: $\text{drawdown} \le -0.10$, $\text{trend\_score} > 0.0$ (or slope $> 0$), $\text{breadth\_score} \ge 0.0$, $\text{stress\_score} < 0.40$.
  - `INSUFFICIENT_CONTEXT`: Critical benchmark history $< 120$ days or missing PIT universe.

### US5 — Storage Migration & Audit Lineage (P1)
**Requirements**:
- Migration `017_market_regime.sql` creates table `market_regime_snapshots`.
- `DuckDBManager` provides `persist_market_regime_snapshot`, `get_market_regime_snapshot`, `list_market_regime_snapshots`.
- Snapshots are reproducible: reloading evidence by IDs and hashes with the same model version reproduces identical regime output.

### US6 — Operator CLI with Point-in-Time Safety (P2)
**Requirements**:
- `python research.py --command market-regime --context EOD --as-of 2026-08-27`
- `python research.py --command market-regime --context INTRADAY --as-of 2026-08-27 --decision-time 2026-08-27T10:00:00+05:30`
- CLI prints JSON/table with market, benchmark, context, decision time, raw regime, confidence, component scores, evidence hash, and missing evidence reasons.
