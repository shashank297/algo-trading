# NIFTY-200 PIT empirical closure report

Build timestamp: `2026-09-16T11:20:21.303469+00:00`

Campaign: `2012-01-02` through `2026-08-20`

Branch: `codex/nifty200-pit-2012-anchor`

Worktree HEAD at report refresh: `d41f907d151ab907c40b13f627fcd6e443faf89a`
`origin/main`: `a8f383149187b8d0bbfb23253ba81c464ec8563f`

## Result

The full real build completed, but strict automated validation remains `BLOCKED`. The remaining failures are evidence gaps, not a reason to synthesize an initial membership set or certify the reverse-replay candidate.

## Measured build

| Metric | Result |
|---|---:|
| Source records | 471 |
| A1 / A2 / B1 sources | 467 / 3 / 1 |
| Source hash failures | 0 |
| Event observations | 1,581 |
| Canonical events | 726 |
| ADD / DROP | 362 / 364 |
| Monthly snapshot rows | 21,650 |
| Snapshot dates | 108 |
| Valid expected-count checkpoints | 108 |
| Literal 200-member checkpoints | 58 |
| Missing/non-200 checkpoints | 68 |
| Current security-master rows | 2,568 |
| Historical identity rows | 7,912 |
| Unique historical instruments | 3,445 |
| Durable-ID / ISIN resolution | 97.3154% / 97.3154% |
| Unresolved identity observations | 32 |
| Constituent intervals | 354 |
| Sessions checked | 3,613 |
| Active constituent range | 0..122 |
| Sessions not at expected count | 3,613 |
| Known-at unresolved | 0 |
| Conflicts | 125 (HIGH 1, CRITICAL 124) |
| Validation | `BLOCKED` |

The 32 unresolved identity observations are redundant official workbook observations excluded from the identity-resolution scope; they are not silently certified as historical identities. The canonical event output contains no synthetic `INITIAL_MEMBER` rows.

## Remaining root-cause blockers

1. `MISSING_INITIAL_ANCHOR`: 1 blocker for `2012-01-02`. The official CNX 200 launch material establishes the index launch and methodology but does not provide the complete 200-member list. The 200-row reverse-replay candidate therefore remains diagnostic/manual-review only.
2. `MONTHLY_SNAPSHOT_MISSING`: 68 campaign months. The exact classification is in `artifacts/nifty200_pit_v1/monthly_gap_analysis.csv`:
   - 15 months from 2012-01 through 2013-03: the candidate official endpoint returned HTML rather than an archived snapshot (`E_HTML_RESPONSE_NOT_ARCHIVE`). Required evidence: an alternative official or archived monthly membership source.
   - 53 months from 2022-04 through 2026-08: the archived material was retrieved but contains no NIFTY-200 member table (`A_ARCHIVE_WITHOUT_NIFTY200_MEMBER`). Other index tables cannot be substituted. Required evidence: an official NIFTY-200 checkpoint or an authoritative archive containing it.
3. `MISSING_MEMBERSHIP_HISTORY`: 123 removal-of-absent-member conflicts. These are downstream of the missing/unproven initial anchor and/or missing predecessor ADD evidence. They are listed with exact dates and symbols in `artifacts/nifty200_pit_v1/blocker_ledger.csv`.
4. `COUNT_NOT_200`: 3,613 session-level validation rows. These are derived failures caused by the unanchored/incomplete interval chain, not 3,613 independent permissions to fill members synthetically.

### Exact membership-history conflict list

The following 123 symbol/date pairs are the current `MISSING_MEMBERSHIP_HISTORY` rows:

- 2012-04-27: BRFL, CMC, CORPBANK, GTL, GUJNRECOKE, MRPL, MTNL, NATIONALUM, ORCHIDCHEM, REDINGTON, REIAGROLTD, SKSMICRO
- 2012-05-21: PATNI
- 2012-09-28: BEML, EDUCOMP, EMAMILTD, ESSAROIL, FORTIS, HCC, HINDOILEXP, JSWISPAT, NCC, RAJESHEXPO, STER, STERLINBIO
- 2013-03-19: INDIABULLS
- 2013-04-01: CONCOR, COROMANDEL, DISHTV, ENGINERSIN, GESHIP, RUCHISOYA, SCI, THERMAX, WIPRO
- 2013-04-17: FRL
- 2013-09-27: AMTEKAUTO, COREEDUTEC, DHFL, GVKPIL, INDIAINFO, IVRCLINFRA, LITL
- 2013-11-01: MARICO
- 2013-11-18: WELCORP
- 2014-02-28: CASTROL
- 2014-03-28: CENTRALBK, CHAMBLFERT, FINANTECH, OPTOCIRCUI, ORISSAMINE, PUNJLLOYD, SINTEX, VIDEOIND
- 2014-09-19: ADANIPOWER, BAJAJFINSV, BAJAJHLDNG, BHUSANSTL, GSKCONS, MCDOWELL-N, RENUKA, VIJAYABANK
- 2014-11-28: RANBAXY
- 2015-03-27: GLAXO, INDIANB, MPHASIS
- 2015-05-29: ADANIENT, IDFC
- 2015-09-28: CROMPGREAV, INDHOTEL, IOB, MAX, MCLEODRUSS, UCOBANK
- 2015-10-19: ABIRLANUVO
- 2016-04-01: ANDHRABANK, HDIL, IFCI, INDIACEM, JISLJALEQS, JPASSOCIAT, KTKBANK, ORIENTBANK, PIPAVAVDOC, PTC, SOUTHBANK, UNITECH
- 2016-09-30: ALBK
- 2016-11-15: CAIRN
- 2017-05-26: GRASIM
- 2017-09-05: RELCAPITAL
- 2018-02-05: CESC, STAR
- 2018-04-02: RCOM, SYNDIBANK
- 2018-06-29: TATACOMM
- 2018-09-28: IRB, SUZLON
- 2018-12-28: CENTURYTEX
- 2019-09-27: ABB, RELINFRA, RPOWER
- 2019-12-27: TATACHEM
- 2020-03-19: YESBANK
- 2020-07-31: VEDL
- 2020-09-25: IDBI, NHPC
- 2021-03-31: OFSS
- 2021-06-30: MOTHERSUMI
- 2021-10-29: GMRINFRA
- 2022-08-08: PEL
- 2022-09-30: APOLLOTYRE, EXIDEIND, GLENMARK
- 2023-03-31: GSPL
- 2023-07-13: HDFC
- 2024-03-28: UBL
- 2024-09-30: IDEA, SUNTV, ZEEL
- 2025-09-30: PETRONET
- 2026-03-30: ACC, IGL

## Changes made in this task

- Added first-party narrative PDF extraction for the official TATAMTRDVR exclusion, with a regression test.
- Corrected the documented 2016–2020 and 2023–2024 expected constituent-count windows.
- Removed unsupported hardcoded historical ISIN assignments and weak continuity links.
- Removed the reverse-replay candidate's synthetic initial-member events and marked the candidate manual-review/diagnostic only.
- Added explicit initial-anchor and coverage conflicts.
- Forced generated manifests to remain `independent_qa=NOT_ASSERTED`, `campaign_readiness=BLOCKED`, `approved_for_import=false`, and `stage_a_started=false`.
- Narrowed the gitleaks allowlist so arbitrary artifact/report SHA-256 strings are not broadly exempted; explicitly scoped the exception to immutable `evidence_manifest.json` integrity metadata after CI identified historical manifest false positives.

The post-PR25 baseline was also preserved before remediation under `artifacts/pre_repair_walkthrough_20260916/`; that directory must not be committed as a final artifact because it contains the pre-repair package.

## Import and verification

The importer dry run returned `REFUSED_AS_DESIGNED`, exit code 1, with `database_touched=false`, because validation is not `PASS`. `market_data.duckdb` and its WAL were not modified. Independent QA remains `NOT_ASSERTED`; import approval is not granted.

Verification completed:

- Full pytest: `973 passed, 3 warnings in 524.63s (0:08:44)`.
- NIFTY-200 focused selection: `114 passed, 852 deselected`.
- Storage selection: `15 passed, 951 deselected`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 57 source files`.
- Pyright: `0 errors, 783 warnings, 0 informations`.
- Compileall: passed.
- `git diff --check`: passed.

## Required evidence to close the build

Obtain and ingest, with source URL and SHA-256 provenance, (a) a complete official/archived 2012-01-02 NIFTY/CNX-200 constituent list or an equivalent authoritative anchor, (b) the 68 missing monthly NIFTY-200 checkpoints, and (c) any missing first-party predecessor ADD records needed to explain the 123 absent-member removals. Then rebuild, replay all 3,613 NSE sessions, reconcile each checkpoint, and rerun strict validation. Until that evidence exists, the correct state is data-evidence blocked.

The current public Nifty 200 page exposes a current constituent download, while NSE Indices describes consistent historical constituent data as a data offering; neither is a free period-valid historical feed for the missing dates. This explains why the remaining work requires a newly located official archive or an evidence package supplied for ingestion.
