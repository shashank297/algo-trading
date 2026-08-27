# Phase 2.3 — Market Context + Deterministic Regime Engine: Implementation Plan

## 1. Tech Stack & Dependencies

- **Language**: Python 3.12+ (standard dataclasses, enums, typing)
- **Data manipulation**: pandas 2.x, numpy (vectorized feature calculations)
- **Persistence**: DuckDB via `storage.duckdb_manager.DuckDBManager`
- **Lineage / Hashing**: `hashlib.sha256` for deterministic evidence and policy hashes
- **Calendar & Sessions**: `trading_stack.calendars.MarketCalendar` (IST timezone handling)
- **CLI**: `argparse` via `research.py`
- **Testing**: `pytest`, `pytest-cov`

---

## 2. Architecture & Component Design

```
                     ┌────────────────────────────────────────┐
                     │          research.py (CLI)             │
                     │  --command market-regime --as-of ...   │
                     └───────────────────┬────────────────────┘
                                         │
                                         ▼
                     ┌────────────────────────────────────────┐
                     │  trading_stack/market_regime.py        │
                     │  MarketRegimeEngine                    │
                     ├────────────────────────────────────────┤
                     │ 1. Point-in-Time Evidence Collector    │
                     │    - Benchmark daily/derived bars      │
                     │    - PIT Universe Membership           │
                     │    - Optional India VIX                │
                     │ 2. Causal Feature Extractor            │
                     │    - Trend, Vol, Breadth, Dispersion,  │
                     │      Liquidity, Stress                 │
                     │ 3. Component Scorer                    │
                     │    - Normalized continuous scores      │
                     │ 4. Deterministic Classifier            │
                     │    - RawMarketRegime + Confidence      │
                     └───────────────────┬────────────────────┘
                                         │
                                         ▼
                     ┌────────────────────────────────────────┐
                     │  storage/duckdb_manager.py             │
                     │  DuckDBManager.persist_market_regime_  │
                     │  snapshot()                            │
                     ├────────────────────────────────────────┤
                     │  Table: market_regime_snapshots        │
                     │  (Migration 017_market_regime.sql)     │
                     └────────────────────────────────────────┘
```

---

## 3. Detailed Component Specifications

### 3.1 `trading_stack/market_regime.py`

#### A. Domain Types
- `MarketContextType`: `EOD`, `INTRADAY`
- `RawMarketRegime`: `BULL_LOW_VOL`, `BULL_HIGH_VOL`, `SIDEWAYS_LOW_VOL`, `SIDEWAYS_HIGH_VOL`, `BEAR_HIGH_VOL`, `RECOVERY`, `INSUFFICIENT_CONTEXT`
- `MarketRegimeFeatures`: Dataclass of all raw calculated metrics.
- `MarketRegimeComponentScores`: Dataclass of `trend_score`, `volatility_score`, `breadth_score`, `dispersion_score`, `liquidity_score`, `stress_score`.
- `MarketRegimeEvidence`: Dataclass recording input dataset IDs, content hashes, row counts, member list hash, VIX ID, decision timestamp bounds.
- `MarketRegimeSnapshot`: Full persisted domain record.
- `MarketRegimePolicy`: Deterministic configuration with version and hash.

#### B. Calculation Algorithms & Formulas
1. **Trend Features & Scoring**:
   - $R_{20} = (P_t - P_{t-20}) / P_{t-20}$
   - $R_{60} = (P_t - P_{t-60}) / P_{t-60}$
   - $R_{120} = (P_t - P_{t-120}) / P_{t-120}$
   - $\text{DMA}_{50\_Ratio} = P_t / \text{SMA}_{50}(P) - 1.0$
   - $\text{DMA}_{200\_Ratio} = P_t / \text{SMA}_{200}(P) - 1.0$
   - $\text{Slope}_{50} = (\text{SMA}_{50}[t] - \text{SMA}_{50}[t-10]) / (10 \cdot \text{SMA}_{50}[t-10])$
   - $\text{Slope}_{200} = (\text{SMA}_{200}[t] - \text{SMA}_{200}[t-20]) / (20 \cdot \text{SMA}_{200}[t-20])$
   - $\text{trend\_score} = \text{clip}(0.25 \cdot \frac{R_{20}}{0.05} + 0.25 \cdot \frac{R_{60}}{0.10} + 0.25 \cdot \frac{\text{DMA}_{50\_Ratio}}{0.03} + 0.25 \cdot \frac{\text{DMA}_{200\_Ratio}}{0.06}, -1.0, 1.0)$

2. **Volatility Features & Scoring**:
   - $\sigma_{20} = \text{std}(\text{returns}_{20}) \cdot \sqrt{252}$
   - $\sigma_{60} = \text{std}(\text{returns}_{60}) \cdot \sqrt{252}$
   - $\text{ATR}_{14\_Norm} = \text{ATR}_{14} / P_t$
   - $P_{\text{vol}} = \text{percentile}(\sigma_{20}, \text{trailing 252 days})$
   - $\text{volatility\_score} = \text{clip}(2.0 \cdot (P_{\text{vol}} - 0.5), -1.0, 1.0)$

3. **Breadth Features & Scoring**:
   - Evaluated exclusively over PIT universe active at `decision_time`.
   - $\% > \text{DMA}_{20}$, $\% > \text{DMA}_{50}$, $\% > \text{DMA}_{200}$
   - $\text{Adv\_Dec\_Ratio} = (\text{Advancing} - \text{Declining}) / \text{Total}$
   - $\text{breadth\_score} = \text{clip}(0.4 \cdot (2 \cdot \%_{>\text{DMA}_{50}} - 1.0) + 0.3 \cdot (2 \cdot \%_{>\text{DMA}_{200}} - 1.0) + 0.3 \cdot \text{Adv\_Dec\_Ratio}, -1.0, 1.0)$

4. **Dispersion Features & Scoring**:
   - $\sigma_{\text{CS}} = \text{std}(\text{constituent 20-day returns})$
   - $\text{dispersion\_score} = \text{clip}(2.0 \cdot (\text{percentile}(\sigma_{\text{CS}}) - 0.5), -1.0, 1.0)$

5. **Liquidity Features & Scoring**:
   - $\text{Turnover\_Ratio} = \text{Turnover}_{5} / \text{Turnover}_{60}$
   - $\text{liquidity\_score} = \text{clip}((\text{Turnover\_Ratio} - 1.0) / 0.5, -1.0, 1.0)$

6. **Stress Features & Scoring**:
   - $\text{DD} = (P_t - \max_{252}(P)) / \max_{252}(P)$
   - $\text{Downside\_Freq} = \text{count}(R_{\text{daily}} \le -0.02) / 20$
   - $\text{Gap\_Freq} = \text{count}(|\text{Gap}| \ge 0.01) / 20$
   - $\text{Vol\_Shock} = \max(0, \sigma_{10} / \sigma_{60} - 1.0)$
   - $\text{stress\_score} = \text{clip}(0.4 \cdot \frac{|\min(0, \text{DD})|}{0.15} + 0.3 \cdot \frac{\text{Downside\_Freq}}{0.15} + 0.3 \cdot \text{Vol\_Shock}, 0.0, 1.0)$

7. **Deterministic Raw Regime Classification Tree**:
   - If critical evidence missing: $\rightarrow \text{INSUFFICIENT\_CONTEXT}$
   - Else if $\text{DD} \le -0.10$ and $\text{trend\_score} > 0.0$ and $\text{breadth\_score} \ge 0.0$ and $\text{stress\_score} < 0.40$: $\rightarrow \text{RECOVERY}$
   - Else if $\text{trend\_score} \le -0.20$ and $(\text{breadth\_score} \le -0.10 \text{ or } \text{stress\_score} \ge 0.50)$: $\rightarrow \text{BEAR\_HIGH\_VOL}$
   - Else if $\text{trend\_score} \ge +0.30$ and $\text{breadth\_score} \ge +0.20$ and $\text{volatility\_score} \le +0.20$ and $\text{stress\_score} \le 0.35$: $\rightarrow \text{BULL\_LOW\_VOL}$
   - Else if $\text{trend\_score} \ge +0.20$ and $\text{breadth\_score} \ge +0.10$ and $\text{volatility\_score} > +0.20$: $\rightarrow \text{BULL\_HIGH\_VOL}$
   - Else if $\text{volatility\_score} > +0.10$: $\rightarrow \text{SIDEWAYS\_HIGH\_VOL}$
   - Else: $\rightarrow \text{SIDEWAYS\_LOW\_VOL}$

---

## 4. Storage & Migration Design

### `storage/migrations/017_market_regime.sql`
```sql
CREATE TABLE IF NOT EXISTS market_regime_snapshots (
    regime_id VARCHAR PRIMARY KEY,
    market VARCHAR NOT NULL,
    benchmark VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    decision_time TIMESTAMP WITH TIME ZONE NOT NULL,
    raw_regime VARCHAR NOT NULL,
    confidence DOUBLE NOT NULL,
    trend_score DOUBLE NOT NULL,
    volatility_score DOUBLE NOT NULL,
    breadth_score DOUBLE NOT NULL,
    dispersion_score DOUBLE NOT NULL,
    liquidity_score DOUBLE NOT NULL,
    stress_score DOUBLE NOT NULL,
    input_evidence_json JSON NOT NULL,
    input_evidence_hash VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    calendar_version VARCHAR NOT NULL,
    missing_evidence_json JSON NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_regime_lookup ON market_regime_snapshots(market, context_type, as_of, decision_time);
CREATE INDEX IF NOT EXISTS idx_regime_evidence ON market_regime_snapshots(input_evidence_hash);
```
