# FAB-31 — Board Decision Pack: Canonical Risk Limits & PIT Strategy Horizon

**Date:** 2026-09-06 (Asia/Kolkata)  
**Project:** Algo Trading — Research, Backtesting & Paper Trading (`bc59843d-1e91-4232-af11-19d37b952301`)  
**Scope:** Governance decision pack only; live trading and real capital deployment remain strictly disabled.

---

## 1. Executive Summary

During the foundation audit, material conflicts were identified among documentation, active configuration files, example configurations, and runtime code defaults for core portfolio risk limits. In accordance with institutional risk governance, the platform will **fail closed** on unconfigured, conflicting, or permissive parameters.

This document formally submits the canonical risk reconciliation matrix and the point-in-time (PIT) universe data route for **explicit Human/Board review and resolution**.

---

## 2. Canonical Risk Policy Reconciliation Matrix

| Control | Current Runtime Default | `config.example.yaml` | `risk_limits.yaml` | `docs/risk_management.md` | Strictest Value | Options | Recommendation | Rationale | Business & Execution Impact |
|---|---|---|---|---|---|---|---|---|---|
| **Sector Concentration** (`max_sector_exposure_pct`) | 40% (0.40) | 40% (0.40) | 20% (0.20) | 10% (0.10) | **10%** | A: 10% (Strictest)<br>B: 20% (Balanced)<br>C: 40% (Permissive) | **Option B: 20%** | 10% is overly restrictive for a 20-stock NIFTY 200 portfolio with high tech/financials index weights. 40% creates excessive idiosyncratic sector shock risk. 20% provides robust sector diversification. | Max 20% allocation to any single industry sector (e.g. BFSI or IT). |
| **Gross Portfolio Exposure** (`max_gross_exposure_pct`) | 100% (1.00) | 20% (0.20) | 100% (1.00) | Unstated | **20%** | A: 20% (Exploratory)<br>B: 100% (Full Cash equity)<br>C: >100% (Leveraged) | **Option B: 100%** | Cash equity trading without leverage naturally permits up to 100% aggregate portfolio capital deployment. 20% was an artificial test fixture. | Allows deploying up to 100% of available trading capital across all open positions without margin debt. |
| **Daily Loss Limit** (`max_daily_loss_pct`) | 3% (0.03) | 1% (0.01) | 2% (0.02) | 1% (0.01) | **1%** | A: 1% (Strict)<br>B: 2% (Medium)<br>C: 3% (Permissive) | **Option A: 1%** | A 1% daily portfolio drawdown halt protects capital against intraday flash crashes and execution slippage. | Halts new order entries for the day when net daily unrealized + realized losses hit 1.0% of portfolio value. |
| **Max Portfolio Drawdown** (`max_drawdown_pct`) | 15% (0.15) | 5% (0.05) | 10% (0.10) | 5% (0.05) | **5%** | A: 5% (Strict)<br>B: 10% (Balanced)<br>C: 15% (Permissive) | **Option A: 5%** | Standard institutional threshold for systematic equities: trading halts if cumulative peak-to-trough drawdown reaches 5%. | System enters protective halt mode if portfolio equity falls 5% below historical high-water mark. |
| **Minimum Daily Liquidity** (`min_liquidity_crore`) | 0.0 Cr (Permissive) | 0.0 Cr | Unstated | Unstated | **5.0 Cr** | A: 5.0 Cr (Institutional)<br>B: 1.0 Cr (Smallcap)<br>C: 0.0 Cr (Permissive) | **Option A: 5.0 Cr** | A 0.0 Cr floor allows illiquid micro-caps into execution. A ₹5 Crore median daily turnover threshold ensures high fill rates and low market impact in NIFTY 200. | Rejects trade proposals in securities with less than ₹5 Crore average daily turnover. |
| **Max Open Positions** (`max_open_positions`) | 20 | 20 | 20 | 20 | **20** | A: 20<br>B: 30 | **Option A: 20** | All configurations agree on 20 max open positions (5% average position size at 100% gross exposure). | Caps active simultaneous holdings at 20 instruments. |
| **Daily 95% VaR** (`max_var_pct`) | 2% (0.02) | 2% (0.02) | 2% (0.02) | 2% (0.02) | **2%** | A: 2% | **Option A: 2%** | Standard 1-day 95% Parametric/Historical VaR limit of 2%. | Rejects trade proposals that would push forecasted 1-day 95% portfolio VaR above 2%. |

---

## 3. Recommended Board Action on Risk Policy

**Board Resolution Draft:**
> "RESOLVED, that the Board of Directors hereby adopts the canonical risk limits specified under Option B for Sector Concentration (20%), Option B for Gross Exposure (100%), Option A for Daily Loss (1%), Option A for Max Drawdown (5%), and Option A for Minimum Daily Liquidity (₹5.0 Crore).  
> FURTHER RESOLVED, that runtime configuration and code defaults must strictly conform to `config/risk_policy.yaml` with zero runtime bypass allowed."

---

## 4. Point-in-Time (PIT) Universe Data Route Decision

As documented in FAB-28 and FAB-30, no certified historical NIFTY 200 point-in-time constituent dataset is currently populated for the 2012–2026 horizon.

| Option | Description | Budget / Cost | Timeline | Regulatory & Correctness Quality | Status |
|---|---|---|---|---|---|
| **Option A: Licensed Provider Route** | Procure historical NIFTY 200 point-in-time constituent archive directly from NSE Indices / authorized market data vendor with announcement timestamps and ISIN history. | Commercial subscription fees apply | Fastest (immediate upon delivery) | Certified first-party provider provenance with complete corporate action lineage. | **Recommended** |
| **Option B: First-Party Public Extract** | Complete extraction and independent reconciliation of public historical press releases and inclusion/exclusion workbooks. | Zero external licensing fee | Significant engineering/QA verification effort | Gaps remain in historical announcement timestamps and delisting ISIN continuity. | Contingency / Secondary |
| **Option C: Shortened Pilot Horizon** | Bound research to recent verified interval (e.g. 2022–2026). | Zero or low cost | Immediate pilot scope | Reduces statistical sample size; requires explicit disclaimer. | Diagnostic Only |

---

## 5. Summary of System Status Pending Decision

- **Risk Policy Status**: `PENDING_BOARD_RECONCILIATION` (`config/risk_policy.yaml` locked to strict values).
- **PIT Universe Status**: `BLOCKED_EXTERNAL_DATA` (clean fail-closed behavior across all authoritative research and paper workflows).
- **Live Execution**: Strictly disabled.
