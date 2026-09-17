# FAB-30 — Draft External Provider Inquiry: Historical NIFTY 200 PIT Dataset

**Date:** 2026-09-06<br>
**Task:** FAB-30 (`5df98343-f451-4858-a4ec-da5734ff993f`)<br>
**Project:** Algo Trading — Research, Backtesting & Paper Trading (`bc59843d-1e91-4232-af11-19d37b952301`)<br>
**Recipient:** NSE Indices Ltd. (`indices@nse.co.in`)<br>
**Subject:** Request for Historical NIFTY 200 Point-in-Time Constituent Dataset (2012–2026)<br>
**Status:** DRAFT PREPARED — PENDING HUMAN BOARD APPROVAL (DO NOT SEND AUTOMATICALLY)

---

## Exact Outbound Email Draft

```text
To: indices@nse.co.in
Subject: Request for Historical NIFTY 200 Point-in-Time Constituent Dataset (2012–2026)
Date: 06 September 2026

Dear NSE Indices Team,

We are conducting institutional quantitative research and algorithmic backtesting on Indian equities and are evaluating an authoritative, licensed historical constituent dataset for the NIFTY 200 index.

This inquiry is non-binding and intended solely for technical evaluation, licensing review, and commercial quotation.

======================================================================
1. MANDATORY POINT-IN-TIME (PIT) CONFIRMATION REQUIREMENT
======================================================================
To satisfy our strict institutional audit and survivorship-bias standards, we require written confirmation of the following specific statement:

    "The dataset represents historical NIFTY 200 constituent membership as of each historical effective date."

Please note that generic confirmations (such as "historical NIFTY 200 data is available") are insufficient for our validation requirements.

======================================================================
2. HISTORICAL COVERAGE & TIMEFRAME
======================================================================
Please confirm whether the dataset provides complete, contiguous historical coverage for:

    From: 02 January 2012
    To:   20 August 2026 (inclusive)

Without retrospective projection or backfilling of current constituents into earlier dates.

======================================================================
3. FIELD-LEVEL DATA SPECIFICATIONS & EVENT AUDIT TRAIL
======================================================================
Please confirm the availability of the following specific fields and historical event records:

1. Historical Effective Dates: Discrete effective_from and effective_to / effective_until dates for every constituent interval.
2. Additions and Removals: Complete event logs specifying additions, removals, and unchanged members at each periodic and ad-hoc rebalance.
3. Historical Symbol History: Active ticker/symbol at the time of each event, including historical symbol changes.
4. Historical ISIN History: Durable ISIN mapping across the entire 2012–2026 horizon to preserve stable instrument identity across ticker or corporate name changes.
5. Constituent Weights: Historical index weights (percentage), shares in index, free-float market capitalization, and closing prices as of each rebalance.
6. Corporate Actions: Full logging and adjustment semantics for splits, consolidations, dividends, rights issues, and bonus issues.
7. Mergers & Demergers: Event details and treatment for spin-offs, amalgamations, restructurings, and successor constituent tracking.
8. Delistings: Comprehensive details on voluntary and compulsory delistings, trading suspensions, and final active trading sessions.
9. Announcement Timestamps: Public circular publication date/timestamp (knowledge-time / known_at) separately recorded from effective implementation dates.
10. Machine-Readable Format: Available delivery formats (e.g., CSV bulk archive, JSON, Parquet, SFTP, or direct API).

======================================================================
4. COMMERCIAL & CONTRACTUAL TERMS
======================================================================
Please provide formal commercial pricing and contract details:

1. One-Time Historical Extract Availability: Is it possible to purchase a one-time historical extract for 2012–2026 without an ongoing subscription?
2. Subscription Requirement: Is an ongoing recurring subscription mandatory to acquire the historical dataset?
3. Exact Quote: Formal fee quotation in INR for the historical dataset (and ongoing subscription, if applicable).
4. Applicable Taxes: Exact breakdown of applicable Goods & Services Tax (GST) or other statutory levies.
5. Minimum Contract Term: Required minimum commitment period (e.g., month-to-month, annual).

======================================================================
5. LICENSING & INTELLECTUAL PROPERTY TERMS
======================================================================
Please clarify the licensing parameters for internal proprietary quantitative research:

1. Internal Research & Backtesting Permission: Explicit permission to use the dataset for internal algorithmic trading strategy research, model training, factor development, and deterministic backtesting.
2. Local Retention Permission: Authorization to retain raw data and derived analytical models locally in an internal relational database (DuckDB/PostgreSQL).
3. Non-Redistribution Restrictions: Confirmation of standard non-redistribution terms (confirming that we will NOT resell, redistribute, or publicly publish raw index constituent data).
4. Data Retention After Subscription Expiry: Perpetual internal retention and audit rights for historical data and derived research results if an ongoing subscription is later terminated.

======================================================================
6. PRE-PURCHASE REPRESENTATIVE VALIDATION SAMPLE
======================================================================
Prior to entering any commercial agreement, we require a representative, non-production machine-readable sample across three historical periods to verify point-in-time schema integrity:

    - Slice 1 (Early Period):  2012-01-02 through 2013-12-31 (at least one rebalance/event)
    - Slice 2 (Middle Period): 2018-01-01 through 2020-12-31 (at least one rebalance/event)
    - Slice 3 (Recent Period): 2024-01-01 through 2026-08-20 (at least one rebalance/event)

Please provide instructions on how we may access this validation sample and data dictionary.

We look forward to your guidance and response.

Sincerely,

Quantitative Research & Platform Engineering
Algo Trading Platform
```
