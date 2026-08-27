# Feature Specification: Phase 2.2 — Certified Multi-Timeframe Data Platform

## 1. Purpose & Core Invariant

Phase 2.2 extends the canonical market-data platform from raw/canonical 1-minute + daily research into
a certified, lineage-preserving multi-timeframe data layer.

All derived bars must be reproducibly traceable back to the exact certified 1-minute source evidence
that produced them. No derived bar may be created from an uncertified or quarantined source.

### Central Invariant

> **"Every derived 5m, 15m, 30m, or 60m bar is cryptographically bound to its exact certified 1m
> source dataset. The same source + calendar + resampler version + timeframe deterministically
> produces identical OHLCV output and identical content hash."**

Phase 2.2 does NOT implement market regimes. It establishes the certified derivation layer and
cross-provider observational verification required for those features later.

---

## 2. Actors & Scope

| Actor | Responsibility |
|---|---|
| Research pipeline | Consumes derived bars for backtesting |
| Data operator | Triggers derivation and cross-provider checks via CLI |
| Storage layer | Persists derived datasets with full lineage metadata |
| DQ layer | Certifies derived bars before they enter research |
| Verification layer | Compares primary vs secondary provider (observational only) |

Out of scope: market regime detection, live order routing, forward-filling, synthetic prices.

---

## 3. User Stories (Functional Requirements)

### US1 — Session-Aware Bar Resampling (P1)

As the research pipeline, I need certified derived bars at 5m, 15m, 30m, and 60m timeframes
so I can backtest multi-timeframe strategies against lineage-verified source data.

**Acceptance Criteria:**

- Given CERTIFIED canonical 1m bars for a symbol and date range, the resampler produces correct 5m, 15m, 30m, and 60m OHLCV bars.
- Session boundaries are never crossed: a bar covering [9:15–9:19] IST must not include any bar from the next trading day or from after 15:30 IST.
- Only complete closing buckets are emitted; an incomplete trailing bucket is dropped.
- OHLCV aggregation rules are exact: open = first 1m open, high = max 1m high, low = min 1m low, close = last 1m close, volume = sum of all 1m volumes.
- Quarantined or untrusted 1m intervals are rejected and the resampler fails closed.
- Mixed adjustment basis (some bars SPLIT_ADJUSTED, some UNADJUSTED) is rejected with a clear error.
- Mixed symbol or exchange identity across source bars is rejected.
- No forward-fill, no synthetic prices, no interpolation of any kind.
- Market holidays produce zero derived bars for that date (not gaps with NaN).
- Special sessions (short trading days) produce bars only within the shortened session window.

### US2 — Derived Dataset Lineage Registry (P1)

As the audit system, I need every derived dataset to be registered with full lineage metadata
so a 15m derived dataset can be traced back to its exact certified 1m source.

**Acceptance Criteria:**

- Each derived dataset has a unique `derived_dataset_id`.
- Lineage persists: `source_dataset_ids`, `source_content_hashes`, `timeframe`, `resampler_version`, `calendar_version`, `adjustment_basis`, `start_ts`, `end_ts`, `row_count`, `content_hash`, `created_at`.
- Two resampling operations with the same inputs produce the same `content_hash`.
- Changing the source data (even one bar) produces a different `content_hash`.
- Derived datasets can only be created from CANONICAL_PROMOTED source datasets.
- A derived dataset for RELIANCE 15m can be joined to its source 1m canonical dataset_id.
- The registry is queryable by symbol, timeframe, and source_dataset_id.

### US3 — Derived Bar DQ Certification (P1)

As the research admission gate, I need derived bars to be certified via automated DQ checks
so no uncertified derived bar can enter a research fold.

**Acceptance Criteria:**

- Schema validation: all required columns present with correct types.
- OHLC integrity: high >= max(open, close), low <= min(open, close), high >= low for every bar.
- No duplicate timestamps within the same symbol+timeframe combination.
- Session alignment: no bar timestamp falls outside the declared session window for its trading date.
- Missing bucket detection: the expected number of bars per session is computed from the timeframe and session duration; missing buckets are reported.
- Timestamp monotonicity: bars are strictly ascending.
- Certification fails closed: any DQ failure prevents the derived dataset from receiving CANONICAL_PROMOTED status.
- DQ report is persisted with pass/fail per check and a summary certification status.

### US4 — Reproducible Derivation (P1)

As a research operator, I need identical inputs to produce identical derived datasets
so I can verify correctness and detect any silent data mutation.

**Acceptance Criteria:**

- The same `(source_dataset_id, calendar_version, resampler_version, target_timeframe)` tuple always produces the same `content_hash`.
- If the source dataset is mutated in any way (even one price changed), the derived `content_hash` changes.
- The resampler version is a semantic version string embedded in the derivation registry.
- The calendar version is the calendar's `version` attribute embedded in the derivation registry.

### US5 — Cross-Provider Observational Verification (P2)

As the data governance layer, I need to compare a secondary provider's bars against the canonical
primary provider's bars so I can detect divergence without blending provider data.

**Acceptance Criteria:**

- The verification module accepts a primary (canonical) dataset and a secondary (observational) dataset for the same symbol, timeframe, and date range.
- For each bar, comparison produces one of: MATCH, TOLERANCE_MATCH, DISAGREEMENT, or UNAVAILABLE.
- Tolerance thresholds are configurable per field (open, high, low, close, volume).
- A DISAGREEMENT result does NOT blend the two values; instead it emits a DATA_VERIFICATION_WARNING.
- Verification results are persisted in `cross_provider_reconciliations` with timestamps, tolerances, comparison version, and individual bar outcomes.
- Unavailable secondary bars produce UNAVAILABLE (not a gap filled from the primary).
- The primary data is never modified by verification.
- Severity of disagreement is configurable: WARNING (emit and continue) or BLOCKING (fail research admission).

### US6 — CLI Commands for Derivation & Verification (P2)

As a data operator, I need CLI commands to trigger derivation and verification from the command line
so I can run ad-hoc data quality checks and build pipeline automation.

**Acceptance Criteria:**

- `--command build-derived-bars` accepts `--symbol`, `--timeframe`, `--source-dataset`, date range, and reports lineage and certification status.
- `--command verify-market-provider` accepts `--symbol`, `--timeframe`, primary and secondary provider names, date range, and reports reconciliation summary.
- Commands emit structured console output listing derived dataset ID, row count, certification status, and any DQ failures.
- Commands exit non-zero on certification failure.

---

## 4. Assumptions

1. Source 1m bars reside in `historical_candles` and are associated with `CANONICAL_PROMOTED` datasets in `market_datasets`.
2. Market calendar uses the existing `MarketCalendar` and `MarketSpec` from `trading_stack/calendars.py`.
3. NSE standard session: 09:15–15:30 IST (Asia/Kolkata timezone).
4. Resampling uses UTC internally, converts to IST only for session boundary checks.
5. No cross-exchange or cross-symbol resampling in a single pass.
6. The secondary provider in cross-provider verification is purely observational; it is never promoted.
7. Derived bars are stored in the existing `historical_candles` table with a `derived_dataset_id` reference, or in a dedicated derived table.
8. Tolerance defaults: price fields ±0.01% relative, volume ±0 (exact match).

---

## 5. Success Criteria

1. All 5m, 15m, 30m, and 60m derivations from a canonical 1m dataset produce consistent, verifiable OHLCV output with no session boundary violations.
2. The same derivation inputs always produce the same content hash (deterministic within the same Python + pandas version).
3. Every derived dataset is registered with full lineage and is queryable from storage.
4. DQ certification fails closed on any structural violation.
5. Cross-provider verification never blends provider data; disagreements are surfaced as warnings or blocking errors.
6. CLI commands allow reproducible operator-triggered derivation and verification.
7. Full repository test suite remains green; new tests cover all required scenarios enumerated in Section 9 of the mission.
8. CI passes with zero regressions on the post-Phase-2.2 SHA.

---

## 6. Key Entities

| Entity | Description |
|---|---|
| `SessionBarResampler` | Derives N-minute bars from 1m certified canonical bars, session-aware |
| `DerivedDatasetCertification` | Registry entry persisting lineage of a derived dataset |
| `DerivedBarDQReport` | DQ certification report for a derived dataset |
| `CrossProviderVerification` | Comparison record between primary and secondary provider |
| `ProviderReconciliationResult` | Enum: MATCH, TOLERANCE_MATCH, DISAGREEMENT, UNAVAILABLE |
| `VerificationSeverity` | Enum: WARNING, BLOCKING |

---

## 7. Out of Scope

- Market regime detection
- Live order routing
- Data blending across providers
- Forward-filling OHLCV
- Synthetic price generation
- Derived timeframes other than 5m, 15m, 30m, 60m (e.g., 2m, 3m, weekly, monthly)
