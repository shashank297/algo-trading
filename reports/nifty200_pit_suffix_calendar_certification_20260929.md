# NIFTY-200 bounded PIT suffix calendar certification

Date: 2026-09-29  
Scope: authoritative NSE capital-market session transformation for the already membership-reconciled suffix 2016-01-29 through 2022-03-31.

## Decision

`SUFFIX_CALENDAR_CERTIFIED`

`MEMBERSHIP_LAYER = PASS` (precondition; this report does not reopen membership reconciliation).  
`CALENDAR_LAYER = PASS` for event chronology, conservative known_at mapping, and effective-session mapping.  
`DATA_COMPLETENESS = NOT ASSESSED`.  
`INDEPENDENT PIT/DATA QA = NOT ASSERTED`.  

The bounded suffix contains 310 canonical membership events, 155 ADD and 155 DROP, all non-synthetic, A1, and event-hash unique. All 310 event chronology checks pass; all 310 known_at values exactly match the strict next NSE session at 09:15 IST under the existing DATE_ONLY_CONSERVATIVE_NEXT_SESSION basis; all 310 effective dates are regular or explicitly special NSE sessions.

## Membership precondition

The prior YESBANK continuity closure records 75 checkpoints, 74 intervals, 15,050/15,050 checkpoint identities, CERTIFICATION_GRADE_EXACT = 74/74, ECONOMIC_DIVERGENCES = 0, REPRESENTATION_ONLY = 26, and MEMBERSHIP_AFFECTING_UNRESOLVED_CONFLICTS = 0. Its decision is SUFFIX_MEMBERSHIP_REPLAY_RECONCILED. Those claims are consumed as a precondition only; no YESBANK, GRASIM, corporate-action, checkpoint, event-membership, frontier, anchor, post-2022, or monthly-governance work was reopened here.

## Admitted official evidence

Seven NSE capital-market circulars were downloaded as raw PDFs, preserved under `reports/nifty200_pit_suffix_calendar_sources_20260929/`, and SHA-256 hashed. Each is an A1 first-party exchange source and covers one calendar year:

- 2016: `NSE/CMTR/31297`, circular date `2015-12-07`, `nse_cmtr_31297_2016.pdf`, SHA-256 `bf33e9aade8773908fc5d6de105cc731e93bf063cd1564a82fe1998c5aaf6432`, 195966 bytes, https://archives.nseindia.com/content/circulars/CMTR31297.pdf
- 2017: `NSE/CMTR/33746`, circular date `2016-12-05`, `nse_cmtr_33746_2017.pdf`, SHA-256 `2fd7ee17432434df26154bbdb9de549d3e4a7acd4cf567843513457e9c98fbce`, 183784 bytes, https://archives.nseindia.com/content/circulars/CMTR33746.pdf
- 2018: `NSE/CMTR/36475`, circular date `2017-12-12`, `nse_cmtr_36475_2018.pdf`, SHA-256 `d80ac64d32806f9ada629bc96ba91c6d85546dfde405f4468bbfcb194fdb22fb`, 183198 bytes, https://nsearchives.nseindia.com/content/circulars/CMTR36475.pdf
- 2019: `NSE/CMTR/39612`, circular date `2018-12-07`, `nse_cmtr_39612_2019.pdf`, SHA-256 `3fe8f7356085b75a14efec16e765216d09b99be6f00ff2305d813a864394ab88`, 205887 bytes, https://archives.nseindia.com/content/circulars/CMTR39612.pdf
- 2020: `NSE/CMTR/42877`, circular date `2019-12-11`, `nse_cmtr_42877_2020.pdf`, SHA-256 `635535e35ddc37e79b188d9f21409210cfdef00f44cde1cb980c4f64ed005eaf`, 192477 bytes, https://archives.nseindia.com/content/circulars/CMTR42877.pdf
- 2021: `NSE/CMTR/46623`, circular date `2020-12-11`, `nse_cmtr_46623_2021.pdf`, SHA-256 `3c922e234ad2cbe8320cc34507e281477e0ce273ba9ee39d73da2a49d5629add`, 75512 bytes, https://archives.nseindia.com/content/circulars/CMTR46623.pdf
- 2022: `NSE/CMTR/50560`, circular date `2021-12-10`, `nse_cmtr_50560_2022.pdf`, SHA-256 `731a4f0f3b3633e53ff344ffda23dab0277c4a6608f5a6da8874f931c9be4ead`, 94485 bytes, https://archives.nseindia.com/content/circulars/CMTR50560.pdf

The circulars provide the capital-market holiday table, weekend-holiday table, and the explicit Muhurat Trading exception. The reconstruction treats Monday-Friday dates not in the weekday-holiday table as regular sessions, Saturday/Sunday as closed, and the seven expressly noted Muhurat dates as special sessions even when listed as holidays.

## Year-by-year coverage accounting

The accompanying CSV is the arithmetic ledger. `year_reconstructed_sessions` counts the deterministic full-year session set after applying the admitted weekday holidays, weekend closure, and Muhurat exceptions. It is a calendar transformation count, not a claim that market data is complete.

| Year | Weekday holidays | Weekend holidays | Special sessions | Reconstructed sessions | Effective events | known_at exact |
|---:|---:|---:|---:|---:|---:|---:|
| 2016 | 15 | 4 | 1 | 247 | 91 | 91 |
| 2017 | 13 | 5 | 1 | 248 | 34 | 34 |
| 2018 | 16 | 3 | 1 | 246 | 52 | 52 |
| 2019 | 15 | 4 | 1 | 247 | 36 | 36 |
| 2020 | 12 | 7 | 1 | 251 | 39 | 39 |
| 2021 | 14 | 5 | 1 | 248 | 30 | 30 |
| 2022 | 13 | 5 | 1 | 248 | 28 | 28 |

Total event arithmetic: 310 rows = 155 ADD + 155 DROP; 310 unique event hashes; 310/310 effective-session validations; 310/310 known_at validations; 310/310 chronology validations.

## Required special and exception audit

- 2016-10-30: Sunday Muhurat Trading; admitted as a special session.
- 2017-10-19: Thursday Muhurat Trading; admitted as a special session despite the holiday table entry.
- 2018-11-07: Wednesday Muhurat Trading; admitted as a special session despite the holiday table entry.
- 2019-10-27: Sunday Muhurat Trading; admitted as a special session.
- 2020-11-14: Saturday Muhurat Trading; admitted as a special session.
- 2021-11-04: Thursday Muhurat Trading; admitted as a special session despite the holiday table entry.
- 2022-10-24: Monday Muhurat Trading; admitted as a special session despite the holiday table entry; outside the bounded suffix end but retained in the full-year 2022 coverage audit.
- 2020-07-31: Friday, not listed in the official 2020 weekday or weekend holiday tables, therefore reconstructed as a regular NSE session. The previously admitted NSE bhavcopy corroboration is `https://archives.nseindia.com/content/historical/EQUITIES/2020/JUL/cm31JUL2020bhav.csv.zip`, SHA-256 `26cbb9286efe0123d66c0e988f90107e32b6f3ea8a2e63701ec97d73a20dd306`. This corroborates date/session existence only; it does not certify market-data completeness or reopen the prior identity adjudication.

## Three-layer validation

### A. Event chronology

PASS: all 310 source publication dates precede their effective dates. Publication time is not present in the canonical evidence: all 310 rows are DATE_ONLY_CONSERVATIVE_NEXT_SESSION. No timestamp was fabricated.

### B. known_at / publication timing

PASS as a conservative transformation: for every event, `known_at` equals 09:15 IST on the strict next reconstructed NSE session after the source publication date. This certifies no look-ahead under the existing date-only conservative rule; it does not claim the exact historical publication clock time.

### C. Effective-session mapping

PASS: every effective date in the 310-row bounded suffix ledger is a regular NSE session or an explicitly admitted special Muhurat session. No event effective date required an unrecorded holiday-to-next-session substitution.

### D. Market-data completeness

NOT ASSESSED. This certification does not assert OHLC, bhavcopy, instrument-level, or PIT data completeness.

## Reproducibility and outputs

The deterministic reconstruction was run at base HEAD `e8eb02d38a1ec0ae0c29b8360ee7a51b384119a5` using the canonical `events_canonical.parquet`, the seven preserved PDFs, and the explicit date tables represented in this report. The event-date ledger is `reports/nifty200_pit_suffix_calendar_event_dates_20260929.csv`; the year/source accounting is `reports/nifty200_pit_suffix_calendar_certification_20260929.csv`.

## Governance boundary

The next gate is `BOUNDED_PIT_VALIDATION / INDEPENDENT_PIT_DATA_QA`. No import approval is granted, no Stage A was run, and no research/backtest/trading/broker API/production DuckDB/WAL action occurred.

```text
INDEPENDENT PIT/DATA QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```
