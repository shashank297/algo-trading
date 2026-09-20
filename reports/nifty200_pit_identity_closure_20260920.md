# NIFTY-200 PIT identity-closure rerun

Date: 2026-09-20
Repository: `shashank297/algo-trading`
Worktree: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Code HEAD before this uncommitted closure work: `9e5016cb86d4c1cf8e05da22789f0e73b92b4cb2`

## Scope and safety

The existing NIFTY-200 PIT builder was used. No Campaign Stage A, research,
backtest, paper/live trading, broker API, production import, or database/WAL
operation was performed. The raw corpus remains content-addressed and the
previous baseline report/artifacts were preserved.

## Reproducibility and parser change

The post-recovery corpus increased from 593 to 597 source records because four
exact-date official historical NSE bhavcopies were newly acquired. The current
catalogue is:

| Tier | Records |
| --- | ---: |
| A1 | 590 |
| A2 | 6 |
| B1 | 1 |
| Total | 597 |

The builder now reads official NSE daily security-master `.csv.gz` files as
dated identity evidence and accepts the official equity trade series `EQ`,
`BE`, `BL`, and `BZ` in dated bhavcopies. A dated identity source supplies a
symbol/ISIN assertion only; it does not create index membership or event
timing. A regression test covers the gzip schema and the non-equity-series
rejection.

The blocker ledger now also records unresolved date-bearing observations that
were excluded from canonical events, preventing those evidence gaps from being
hidden by reconciliation.

## Official sources contacted or acquired

The following free first-party/archive-first-party sources were checked or
acquired:

- [NSE series legend](https://www.nseindia.com/static/market-data/legend-of-series)
  for the equity-series interpretation.
- [NSE daily security-master dissemination circular](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf)
  and [NSE all-reports page](https://www.nseindia.com/all-reports) for the
  official daily `.csv.gz` source family.
- Official daily security masters:
  `NSE_CM_security_28032025.csv.gz` SHA-256
  `3a8575d68a6f141a4b3046dbe02a60afea7560509f25024fe61632e094361487`,
  `NSE_CM_security_30092025.csv.gz` SHA-256
  `ccadc8d02c9771dc567795605278593362ee87ed6bf10bc5ad0cabadeaaf622f`, and
  `NSE_CM_security_30032026.csv.gz` SHA-256
  `282fbe09931c0507662afa8c4540f293f37166a08b1fc2fe9da2bf47c6b9f877`.
- Official PR bhavcopy bundles:
  `PR280325.zip` SHA-256
  `a5f429f451cbae0edf7ee627bae7cfae137a88018a29ddf30f3364aa2f77ce35`,
  `PR300925.zip` SHA-256
  `7908cb66063bfa344f6f79be228c00eea56d77171ceda163278c38eaeb499aa3`, and
  `PR300326.zip` SHA-256
  `7883e11cadaee1cb0d1a371299a0fa01668a9d3610cc8cabcf6f6e173214e04b`.
- Exact-date official historical bhavcopies through the existing NSE archive
  family, including newly added files:
  `cm27APR2012bhav.csv.zip` SHA-256
  `e60a1a6581cd78587706afd2acf59e67d26584550c9479f98a4aaef7ba4243f6`,
  `cm28SEP2012bhav.csv.zip` SHA-256
  `b75f22b397b9a760e40999cc19325a8360de311c7c263d8b3fb7ed0ecda31254`,
  `cm01NOV2013bhav.csv.zip` SHA-256
  `f48838ecf34819fb8d6669ab6e42a48eaf28bce85b7f373eddf9624d76d69c23`, and
  `cm24OCT2016bhav.csv.zip` SHA-256
  `26d2842b529d321489f7616ba2a41eade7ad292b9710b1e7c6e25edad0e9b746`.
  Other exact-date files were already present in the restored corpus.
- The attempted exact-date 2013-11-15 archive lookup returned no usable
  official archive (`nsearchives` HTTP 404); no substitute was admitted.
- Official Nifty Indices press-release and historical-report archives,
  Wayback captures of official NSE URLs, the archived security masters,
  `IndexInclExcl.xls`, and the B1 reconstruction were retained under their
  existing evidence policies. B1 remained a search index only.

## Measured build result

The full rebuild completed with:

| Metric | Result |
| --- | ---: |
| Source records | 597 |
| A1 / A2 / B1 | 590 / 6 / 1 |
| Source hash failures | 0 |
| Event observations | 1,544 |
| Canonical events | 671 |
| ADD / DROP | 327 / 344 |
| Snapshot rows / dates | 21,650 / 108 |
| Valid 200-member checkpoints | 58 |
| Missing/non-200 checkpoints | 68 |
| Current security-master rows | 2,578 |
| Historical identity rows | 230,784 |
| Unique historical instruments | 4,933 |
| Unresolved event identity cases | 15 |
| Durable-ID / ISIN resolution | 45.7902% / 45.7902% |
| Constituent intervals | 325 |
| Campaign sessions checked | 3,613 |
| Minimum/maximum active diagnostic count | 0 / 119 |
| Sessions not at expected count | 3,613 |
| `known_at` unresolved | 0 |
| Total conflicts | 137 |
| HIGH / CRITICAL conflicts | 1 / 136 |
| Validation | `BLOCKED` |

The campaign replay counts remain diagnostics only because the initial anchor is
not established.

## Blockers after this rerun

`artifacts/nifty200_pit_v1/blocker_ledger.csv` contains 222 rows:

| Blocker type | Rows | Resolution state |
| --- | ---: | --- |
| `MISSING_INITIAL_ANCHOR` | 135 | Unresolved: one root anchor plus downstream replay/removal conflicts |
| `MONTHLY_SNAPSHOT_MISSING` | 68 | Unresolved evidence/contract gaps |
| `MISSING_DURABLE_IDENTITY` | 15 | Unresolved manual identity evidence |
| `DUPLICATE_EVENT` | 2 | Unresolved manual review |
| `SOURCE_DOWNLOAD_FAILURE` | 1 | Unresolved May-2012 archive retrieval |
| `OTHER` | 1 | Calendar not fully certified |

The 15 remaining identity cases are:

| Effective date | Symbol | Company | Missing evidence needed |
| --- | --- | --- | --- |
| 2012-04-27 | — | Gujarat NRE Coke Ltd. | Exact official company-to-symbol/ISIN identity valid on the event date |
| 2012-09-28 | — | Fortis Healthcare Ltd. | Same |
| 2012-09-28 | — | Jammu & Kashmir Bank Ltd. | Same, including the period-valid ISIN choice |
| 2012-09-28 | — | Shree Cement Ltd. | Same |
| 2013-04-17 | — | Future Retail Ltd. | Same, distinguishing the historical Future group instrument |
| 2013-09-27 | — | GVK Power & Infrastructures Ltd. | Same, distinguishing GVK entities |
| 2015-05-29 | — | Alstom T&D India Ltd. | Official name/symbol/ISIN continuity or corporate-action evidence |
| 2015-09-28 | — | Ajanta Pharmaceuticals Ltd. | Exact dated identity evidence |
| 2016-04-01 | — | Alstom T&D India Ltd. | Exact dated identity evidence |
| 2016-04-01 | — | Jain Irrigation Systems Ltd. | Exact dated identity evidence, including ordinary/DVR distinction |
| 2016-04-01 | — | National Buildings Construction Corporation Ltd. | Exact dated identity evidence |
| 2018-09-28 | — | HDFC Standard Life Insurance Company Ltd. | Official name-change/ISIN continuity evidence |
| 2019-09-27 | — | Reliance Nippon Life Asset Management Ltd. | Official name-change/ISIN continuity evidence |
| 2020-06-26 | — | Adani Gas Ltd. | Official name-change/ISIN continuity evidence |
| 2013-11-15 | IBULHSGFIN | Indiabulls Housing Finance Limited | A first-party event/identity source; the exact-date official bhavcopy was not found |

The exact bhavcopies provide symbol/ISIN rows, but the old bhavcopy schema does
not carry company names. Linking those rows to name-only workbook assertions
would be name-based inference, so they were not auto-certified.

The two duplicate events remain:

- `ABBOTINDIA` ADD on 2022-03-31.
- `OFSS` ADD on 2024-03-28.

Both are official A1 observations that conflict with already-active membership
and later official checkpoint evidence. Raw observations are retained and the
conflicts remain `MANUAL_REVIEW`; no event was silently discarded.

Monthly status remains explicitly classified in
`reports/nifty200_pit_monthly_gap_analysis.csv`:

- 108 `PASS` months;
- 62 `A_NO_SNAPSHOT_EVIDENCE` months;
- 5 `E_SOURCE_PRESENT_ZERO_ROWS` months (May 2022 through May 2026);
- 1 `E_HTML_RESPONSE_NOT_ARCHIVE` month (May 2012).

## Artifact and safety pointers

- Blocker ledger: `artifacts/nifty200_pit_v1/blocker_ledger.csv`
- Unresolved gaps: `artifacts/nifty200_pit_v1/unresolved_gaps.csv`
- Validation: `artifacts/nifty200_pit_v1/validation_report.json`
- Evidence manifest: `artifacts/nifty200_pit_v1/evidence_manifest.json`
- Intervals: `artifacts/nifty200_pit_v1/constituent_intervals.parquet`
- Intervals SHA-256: `f5788d5a97393728dba3bd3603d435852273abcf66989cfd63addde9a4e1f14c`
- Dry-run importer: `artifacts/nifty200_pit_v1/dry_run_import_result.json`

The dry-run importer was refused as designed because validation is not PASS;
`database_touched=false` and `approved_for_import=false` remain in force.

## Verification

- Focused NIFTY-200 PIT suite: `112 passed`.
- Storage suite: `9 passed`.
- Full suite: the normal protected-worktree run reported `1004 passed, 8
  filesystem PermissionError failures, 3 warnings`; rerunning those eight
  cases with elevated access produced `8 passed`. Effective result:
  `1012 passed, 3 warnings`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 59 source files`.
- Pyright: `0 errors, 874 warnings, 0 informations`.
- Compileall: exit code `0`.
- `git diff --check`: clean (only Git's LF-to-CRLF working-copy warnings).

## Final status

NIFTY-200 PIT RECONSTRUCTION: **DATA EVIDENCE BLOCKED**
INDEPENDENT QA: **NOT ASSERTED**
IMPORT APPROVAL: **NOT GRANTED**
CAMPAIGN STAGE A: **BLOCKED**
