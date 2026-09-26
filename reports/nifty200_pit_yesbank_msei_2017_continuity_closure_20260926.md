# YESBANK MSEI 2017 continuity closure

Date: 2026-09-26  
Scope: YESBANK `INE528G01019 -> INE528G01027` only. The prior `INE528G01027 -> INE528G01035` chain remains unchanged. No calendar, frontier, 2012 anchor, post-2022, GRASIM, broad research, Stage A, trading, broker API, production DuckDB, or WAL work was performed.

## Governance and source validation

The current `DOCUMENTED_STOCK_SPLIT_CONTINUITY` rule requires a hash-verified first-party issuer/corporate-action assertion plus period-valid identity evidence, preserved bytes and temporal bounds. A recognized exchange circular is an A1 first-party corporate-action source under the existing evidence catalogue/source-tier policy. The MSEI circular itself explicitly asserts both old and new ISINs, so the separate 2011 diagnostic old-side source is not needed for this direct continuity link and remains diagnostic only.

Result: `MSEI_OFFICIAL_EXCHANGE_CIRCULAR_ADMISSIBLE`  
Result: `MSEI_5543_2017_VALIDATED`  
Result: `YESBANK_019_027_CONTINUITY_ADMISSIBLE`  
Result: `YESBANK_019_027_DURABLE_IDENTITY_CONTINUITY_PROVEN`

Preserved source: `reports/nifty200_pit_yesbank_msei_2017_continuity_sources_20260926/Circular-5543.pdf`  
Official URL: `https://www.msei.in/SX-Content/Circulars/2017/September/Circular-5543.pdf`  
SHA-256: `6bee48b705e78b19574ba0a393fc52d493dd8f071c28e0f32bba855229b595e9`  
Bytes: `218428`  
Retrieved: `2026-09-26T17:16:12.352161+05:30`  
PDF: `%PDF-1.5`, one readable page, HTTP 200.

Page 1, the Listing/Capital Market table and following Ex-date sentence verify:

- circular `MSE/LIST/5543/2017`, dated September 18, 2017;
- title `Change in ISIN of Yes Bank Limited`;
- symbol `YESBANK`;
- existing ISIN `INE528G01019`;
- new ISIN `INE528G01027`;
- reason `Sub-division from Rs. 10/- to Rs. 2/-`;
- record date September 22, 2017;
- new ISIN effective for trades from Ex-date September 21, 2017.

The relationship is a security-identity transition caused by share subdivision, not an index membership change. The edge is registered as `DOCUMENTED_STOCK_SPLIT_CONTINUITY`; no synthetic NIFTY-200 DROP or ADD was created.

## Chain and replay

The provenance-backed durable chain is:

`NSE-ISIN:INE528G01019`  
→ MSEI documented subdivision, corporate-action date `2017-09-22`, effective trading date `2017-09-21`, source hash `6bee48b705e78b19574ba0a393fc52d493dd8f071c28e0f32bba855229b595e9`  
→ `NSE-ISIN:INE528G01027`, period-valid post source date `2017-09-29`, source hash `02c7a906d55e08a0d3fde86d440577b23a47f21cd09581ef953e90ccc79f752e`  
→ existing 2020 reconstruction continuity  
→ `NSE-ISIN:INE528G01035`.

The focused certification-grade replay leaves no absent-root YESBANK DROP. All six baseline YESBANK intervals are `STILL_DIVERGENT` before the edge and `EXACT` after it; the row-level result is in the accompanying CSV.

Suffix accounting after the scoped continuity correction:

- checkpoints: `75`;
- intervals: `74`;
- checkpoint identities: `15,050 / 15,050`;
- `CERTIFICATION_GRADE_EXACT = 74 / 74`;
- `ECONOMIC_DIVERGENCES = 0`;
- `REPRESENTATION_ONLY = 26`;
- `YESBANK_CONFLICT_RESOLVED`;
- `MEMBERSHIP_AFFECTING_UNRESOLVED_CONFLICTS = 0`;
- decision: `SUFFIX_MEMBERSHIP_REPLAY_RECONCILED`;
- next workstream: `CALENDAR_CERTIFICATION_FOR_2016_01_29_TO_2022_03_31`.

## Verification and delivery

Source hash/PDF semantic validation passed. Focused PIT tests passed: `120 passed`. Storage tests passed: `9 passed`. The complete collected suite was `1,020` tests across `82` files: `1,011` passed in the per-file run and the five environment-sensitive files were rerun with elevated writable-path access for the remaining `69`; final coverage is `1,020 passed`. Ruff, Mypy, Pyright, compileall, CSV arithmetic/uniqueness, deterministic replay, and `git diff --check` also passed. The remediation changed only test execution paths; no production code, database, or WAL was used.

The source catalogue and ignored continuity artifact were updated locally. No existing failed YES BANK source report was rewritten. No push or merge was performed.

```text
DATA EVIDENCE BLOCKED
INDEPENDENT PIT/DATA QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```
