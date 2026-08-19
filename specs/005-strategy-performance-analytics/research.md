# Research: Strategy Performance Analytics

**Feature**: `005-strategy-performance-analytics`
**Date**: 2026-08-19

---

## 1. Current Database Schema (Verified)

### `trade_round_trips`
Columns confirmed via `PRAGMA table_info`:
| Column | Type | Notes |
|---|---|---|
| `trade_id` | PK | |
| `run_id` | FK | links to strategy_runs |
| `symbol` | text | |
| `entry_timestamp` | timestamp | |
| `exit_timestamp` | timestamp | |
| `quantity` | float | may be fractional |
| `entry_price` | float | |
| `exit_price` | float | |
| `entry_cost` | float | fees on entry leg only (small) |
| `exit_cost` | float | fees on exit leg only (small) |
| `gross_pnl` | float | pre-fee profit |
| `net_pnl` | float | after-fee profit |
| `holding_period_days` | float | precomputed |
| `entry_reason` | text | |
| `exit_reason` | text | |
| `exit_classification` | text | WIN / LOSS / BREAKEVEN |

### `strategy_equity_curve`
Contains `equity`, `net_return`, `drawdown`, `gross_exposure` at each bar timestamp.

### `strategy_metrics`
Available metrics per run: `total_return`, `win_rate`, `max_drawdown`, `sharpe`, `sortino`, `profit_factor`, `cagr`, `fees`, `trades`, etc.

---

## 2. Key Bug Fixed (Pre-Research Context)
The previous monthly return calculation used `entry_cost` (brokerage fee ~Rs 20) as the denominator for percentage return. This caused astronomical values. The correct approach is to use `gross_pnl / (entry_price * quantity)` or just use the `net_pnl` sum scaled against the Rs 1,00,000 base.

**Decision**: 
- Monthly matrix for portfolio-level → Use equity curve: `(month_end_equity / month_start_equity) - 1`
- Monthly matrix for stock-level → Use `SUM(net_pnl)` per month divided by 100,000 base
- KPI "Profit on Rs 1,00,000 Base" → `total_return * 100,000` from `strategy_metrics`

---

## 3. New KPI Requirements & Sources

| KPI | Source |
|---|---|
| Total Trades | `COUNT(*)` from `trade_round_trips` |
| Profitable Trades | `COUNT WHERE net_pnl > 0` |
| Losing Trades | `COUNT WHERE net_pnl <= 0` |
| Win Rate | `profitable / total` |
| Avg Profit per Winning Trade | `AVG(net_pnl) WHERE net_pnl > 0` |
| Avg Loss per Losing Trade | `AVG(net_pnl) WHERE net_pnl <= 0` |
| Profit Factor | `SUM(net_pnl WHERE net_pnl > 0) / ABS(SUM(net_pnl WHERE net_pnl < 0))` |
| Max Drawdown | from `strategy_metrics` |
| Profit on Rs 1,00,000 Base | `total_return * 100000` from `strategy_metrics` |

---

## 4. Year Filter Design

**Decision**: Year filter lives entirely in the **frontend**. The API already returns all monthly data; the frontend filters by year. The KPI stats endpoint needs a `?year=YYYY` parameter added to recompute stats for that year only.

**Rationale**: Avoids an extra API round-trip for the monthly matrix since all data is already fetched. Year-specific KPI stats require a backend filter because they involve aggregate recomputation.

---

## 5. Yearly Bar Chart

**Decision**: Compute yearly totals on the frontend by summing the monthly matrix data per year. This avoids a new API endpoint. A simple bar chart using Recharts (already in the project) is sufficient.

---

## 6. RCA Ledger Improvements

**Decision**: 
- Add `gross_pnl`, `holding_period_days`, `entry_cost + exit_cost` as fees to the ledger response
- Add pagination (25 rows per page) using frontend-only pagination (data already fetched)
- Sort by `exit_timestamp DESC` by default
- Add CSV export via frontend `Blob` download (no server needed)
- Fix price display from `$` to `₹` (Indian Rupees)

---

## 7. Alternatives Considered

| Area | Chosen | Alternative | Reason |
|---|---|---|---|
| Year filter KPIs | Backend `?year=` param | Frontend only | Frontend cannot recompute Win Rate without raw trade list |
| Monthly returns for portfolio | Equity curve approach | Trade compounding | Equity curve is already smoothed and free of fractional-share bugs |
| Yearly chart | Frontend Recharts | New chart library | Recharts already used in EquityCurve component |
| CSV Export | Frontend Blob | Backend endpoint | Simpler, no server change needed |
