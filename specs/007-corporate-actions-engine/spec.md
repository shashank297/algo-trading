# Feature Specification: Institutional Corporate Actions & Total Return Engine

**Feature Branch**: `007-corporate-actions-engine`

**Created**: 2026-08-20

**Status**: Draft

**Input**: User feedback and specification for institutional-grade corporate actions handling: canonical `share_multiplier` for splits/bonuses/consolidations, distinct `UNADJUSTED`, `SPLIT_ADJUSTED`, `BACK_ADJUSTED`, and `TOTAL_RETURN` modes, robust database schema with unique `action_id`, IST session boundary alignment, trading session $P_{\text{prev}}$ lookup, turnover invariance, and double-adjustment idempotency protection.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Split, Bonus, and Consolidation Adjustment (Priority: P1)

As a quantitative trader running technical strategies, I want historical OHLCV data to be accurately adjusted for stock splits, bonus issues, and share consolidations using canonical `share_multiplier` values, so that price series and indicators are continuous across corporate action ex-dates.

**Why this priority**: Core quant foundation. Without split adjustment, indicators like EMA, RSI, and ATR produce catastrophic false signals around ex-dates.

**Independent Test**: Load `TATASTEEL-EQ` around its 2022-07-28 10:1 split. Verify that pre-split bars are scaled by 10x while ex-date and post-split bars remain unchanged, and traded turnover ($P \times V$) remains invariant.

**Acceptance Scenarios**:
1. **Given** a 10:1 split on 2022-07-28, **When** `SPLIT_ADJUSTED` data is requested, **Then** all bars prior to 2022-07-28 have OHLC divided by 10 and volume multiplied by 10, while bars on or after 2022-07-28 remain identical to raw data.
2. **Given** a 1:3 bonus issue (1 bonus for 3 held), **When** parsed, **Then** `share_multiplier` is calculated as $(3 + 1) / 3 = 1.333333$.
3. **Given** a 5:1 consolidation (5 old for 1 new), **When** parsed, **Then** `share_multiplier` is calculated as $1 / 5 = 0.2$.

---

### User Story 2 - Backward Dividend Gap Adjustment (Priority: P2)

As a chartist and indicator researcher, I want cash dividends to provide continuous back-adjusted price levels (`BACK_ADJUSTED`), so that dividend price drops do not register as false technical breakdown gaps.

**Why this priority**: Eliminates artificial gap-downs caused by large dividend payouts on ex-dates without distorting volume.

**Independent Test**: Provide a synthetic series with a cash dividend and verify that pre-ex prices are multiplied by $1 - \frac{D}{P_{\text{prev}}}$ where $P_{\text{prev}}$ is the previous trading session close (not calendar day - 1).

**Acceptance Scenarios**:
1. **Given** a cash dividend with ex-date on Monday, **When** calculating the continuity factor, **Then** the engine retrieves Friday's official session closing price as $P_{\text{prev}}$.
2. **Given** a `BACK_ADJUSTED` request, **Then** prices reflect both split and dividend continuity scaling, while volume reflects split scaling only.

---

### User Story 3 - Exact Total Return Index & Series (Priority: P2)

As a portfolio manager and quant researcher, I want an exact dividend-reinvested Total Return Index (`TOTAL_RETURN`), so that strategy performance, CAGR, and benchmark comparisons accurately reflect total shareholder return.

**Why this priority**: Price return underestimates long-term equity performance by ignoring dividend reinvestment economics.

**Independent Test**: Compute $r_t^{\text{TR}} = \frac{P_t + D_t}{P_{t-1}} - 1$ and verify $\text{TRI}_t = \text{TRI}_{t-1} \times (1 + r_t^{\text{TR}})$ matches compounding math.

**Acceptance Scenarios**:
1. **Given** an initial index value of 100.0, a ₹100 pre-ex close, ₹5 dividend, and ₹96 ex-date close, **Then** daily total return is exactly $+1.0\%$ and the Total Return Index compounds to 101.0.

---

### User Story 4 - Resilient Corporate Action Schema & Ingestion (Priority: P1)

As a data engineer, I want the `corporate_actions` database table to use a unique `action_id` primary key and store comprehensive metadata (face value transitions, bonus ratios, event IDs), so that multiple distributions on the same date and historical revisions are stored safely.

**Why this priority**: Prevents database collisions when regular and special dividends occur on the same ex-date.

**Independent Test**: Insert multiple corporate action events for the same symbol on the same ex-date and verify all records persist without primary key violations.

**Acceptance Scenarios**:
1. **Given** a regular dividend and a special dividend on the same ex-date, **When** stored, **Then** both rows persist with unique `action_id` values.

---

### User Story 5 - Idempotency & Double-Adjustment Protection (Priority: P1)

As a pipeline architect, I want the adjustment engine to reject re-adjusting already-adjusted data, so that accidental double-adjustment bugs cannot corrupt backtest datasets.

**Why this priority**: Prevents scaling prices by $10 \times 10 = 100\times$ if a dataset is passed through an adjustment function twice.

**Independent Test**: Pass a DataFrame with `adjustment="SPLIT_ADJUSTED"` into `adjust_ohlcv(..., adjustment=SPLIT_ADJUSTED)` and verify it raises a `ValueError` or returns early without re-multiplying.

**Acceptance Scenarios**:
1. **Given** a DataFrame already marked as `SPLIT_ADJUSTED`, **When** adjustment is invoked, **Then** the engine raises an error or safely preserves the existing adjusted state.

---

### Edge Cases

- **Exchange Session Date vs UTC Date**: When evaluating intraday 1-minute bars, timestamps must be localized to `Asia/Kolkata` date before comparing with `ex_date`.
- **Pre-Ex Session Lookup**: On Monday ex-dates or after multi-day exchange holidays, $P_{\text{prev}}$ must resolve to the immediately preceding active trading session.
- **Zero or Negative Ratio Validation**: Any corporate action with non-positive ratio or dividend $\ge P_{\text{prev}}$ must raise validation errors during ingestion.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST define four strongly typed adjustment modes: `UNADJUSTED`, `SPLIT_ADJUSTED`, `BACK_ADJUSTED`, and `TOTAL_RETURN`.
- **FR-002**: `corporate_actions` table MUST use `action_id VARCHAR PRIMARY KEY` and include `share_multiplier DOUBLE NOT NULL DEFAULT 1.0`.
- **FR-003**: System MUST correctly parse bonus ratios where `Bonus N:M` yields `share_multiplier = (M + N) / M`.
- **FR-004**: System MUST maintain traded turnover ($P_{\text{close}} \times \text{Volume}$) invariance for all split/bonus/consolidation transformations.
- **FR-005**: System MUST compute Total Return Index as a dedicated return series rather than distorting raw OHLC candles.
- **FR-006**: System MUST enforce idempotency, preventing double-adjustment of already-adjusted datasets.
- **FR-007**: System MUST use `Asia/Kolkata` exchange session dates for all intraday and daily date boundary comparisons.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% mathematical accuracy on Tata Steel 10:1 split test with exact continuity across the 2022-07-28 boundary.
- **SC-002**: $P_{\text{adj}} \times V_{\text{adj}} == P_{\text{raw}} \times V_{\text{raw}}$ within floating point epsilon ($10^{-5}$) across all split transformations.
- **SC-003**: 0% chance of primary key collision on same-day multiple corporate distributions.
- **SC-004**: 100% of unit, integration, and regression tests passing.
