# FAB-32 — Authorized External Provider Inquiry: NIFTY 200 Historical PIT Dataset

**Date:** 2026-09-06T12:15:00+05:30 (Asia/Kolkata)  
**Project:** Algo Trading — Research, Backtesting & Paper Trading (`bc59843d-1e91-4232-af11-19d37b952301`)  
**Authorization Reference:** Human Board Decision — Authorize NIFTY 200 PIT Provider Inquiry (Non-Binding Information Gathering)  
**Status:** `AWAITING NIFTY 200 PIT PROVIDER RESPONSE`

---

## 1. Transmission Metadata

- **Sender:** Research & Engineering Governance, Algo Trading Platform
- **Recipient:** NSE Indices Ltd. (`indices@nse.co.in`)
- **CC / Administrative Contact:** Institutional Data Services
- **Subject:** Request for Historical NIFTY 200 Point-in-Time Constituent Dataset (2012–2026)
- **Transmission Timestamp:** `2026-09-06T06:45:00Z` (`2026-09-06T12:15:00+05:30`)
- **Action Type:** Official Non-Binding Information-Gathering Inquiry
- **Commitment Status:** Zero commercial, financial, or contractual commitment. Non-binding inquiry only.

---

## 2. Exact Message Body Transmitted

```text
To: indices@nse.co.in
Subject: Request for Historical NIFTY 200 Point-in-Time Constituent Dataset (2012–2026)
Date: 06 September 2026

Dear NSE Indices Team,

We are conducting institutional quantitative research and backtesting on Indian equity markets and are evaluating an authoritative, point-in-time (PIT) historical constituent dataset for the NIFTY 200 index.

This inquiry is non-binding and intended for information gathering, technical feasibility, and commercial evaluation.

We request information on the following specific requirements:

============================================================
1. HISTORICAL COVERAGE & TIMEFRAME
============================================================
Please confirm whether an authoritative, point-in-time historical constituent dataset is available for the NIFTY 200 index covering the full historical horizon:

    From: 02 January 2012
    To:   20 August 2026 (inclusive)

Can this horizon be provided without survivorship bias or retrospective projection of current index members?

============================================================
2. FIELD-LEVEL SPECIFICATIONS & DATA CONTRACT
============================================================
Please confirm the availability of the following historical fields for each constituent observation and index change event:
- Effective membership dates: discrete effective_from and effective_to / effective_until
- Event audit trail: additions, removals, and unchanged constituent membership at each review
- Permanent / stable instrument identity: ISIN, NSE Security ID, and permanent company identifier (historical company names alone are insufficient for our audit)
- Historical ticker / symbol at the time of each event, including symbol change history
- Delisting details: delisting date, reason, and final trading session
- Suspension and listing status history
- Corporate action lineage: mergers, demergers, spin-offs, and capital reorganizations
- Index metrics: constituent index weights (percentage), free-float market capitalizations, shares in index, and index closing prices at each rebalance
- Errata policy: historical restatements, corrections, and amendment audit logs

============================================================
3. CRITICAL QUESTION ON KNOWLEDGE-TIME (KNOWN_AT) CAUSALITY
============================================================
Does the historical dataset include the exact date and public publication / announcement timestamp at which each constituent addition, exclusion, or rebalance became publicly known, separately from its subsequent effective implementation date?

Because our institutional research framework strictly prohibits look-ahead bias, understanding the exact publication timing is critical. If exact timestamps (HH:MM:SS) are unavailable, what is the finest granularity available for publication evidence (e.g., circular publication date, press release date, or effective date only)?

============================================================
4. STABLE INSTRUMENT IDENTITY
============================================================
Can you explicitly confirm that historical records carry primary durable identifiers (such as ISIN and NSE Security ID) across the entire 2012–2026 horizon, ensuring continuity through historical ticker symbol or corporate name changes?

============================================================
5. DATA DICTIONARY & DELIVERY FORMATS
============================================================
Please provide:
- A formal data dictionary, schema documentation, and field definitions.
- Available delivery mechanisms (e.g., CSV bulk archive, REST API, SFTP, direct database extract).
- Update frequency and partition structure.

============================================================
6. REPRESENTATIVE SAMPLE REQUEST
============================================================
To validate schema compatibility and point-in-time integrity prior to procurement, we request a representative, non-production historical data sample across three historical periods:
1. Early Period:  2012 – 2013 (at least one rebalance/event)
2. Middle Period: 2018 – 2020 (at least one rebalance/event)
3. Recent Period: 2024 – 2026 (at least one rebalance/event)

Where available, please include: index_code, ISIN, security_id, historical_symbol, security_name, announcement_at, effective_from, effective_until, event_type, constituent weight, addition/removal reason, and source/version metadata.

============================================================
7. LICENSING TERMS FOR INTERNAL QUANTITATIVE RESEARCH
============================================================
Please clarify licensing terms for internal quantitative research:
- Is internal algorithmic research and backtesting permitted under the license?
- Can raw constituent data and derived backtest results be stored indefinitely in an internal database?
- Are there restrictions on derived factor scores, portfolio simulations, or internal risk models?
- Can an extract be licensed under a one-time historical purchase, or is an ongoing annual subscription mandatory?
- What are the user / workstation / server seat licensing parameters?

============================================================
8. COMMERCIAL PRICING & COST STRUCTURE
============================================================
Please provide formal indicative pricing:
- One-time historical extract fee (2012–2026)
- Ongoing annual subscription fee (if applicable)
- Onboarding or setup fees, if any
- Applicable taxes (GST)
- Cost of evaluation sample (if any)

We look forward to your response and guidance on available options.

Sincerely,

Quantitative Research & Platform Engineering  
Algo Trading Platform
```

---

## 3. Post-Transmission Governance & Invariants

In accordance with Human Board instructions:
- **Zero Commercial Commitment:** No agreement signed, no payment details shared, no fees committed.
- **Fail-Closed Staging Requirement:** Upon receipt of provider response and evaluation sample:
  1. Raw bytes must be preserved immutably and verified via SHA-256 checksum.
  2. Sample records must be loaded into isolated staging tables only.
  3. No promotion to canonical `index_constituents_pit` tables is permitted without independent QA/Risk review.
- **Current Status:** `AWAITING NIFTY 200 PIT PROVIDER RESPONSE`.
