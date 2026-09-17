# NIFTY-200 PIT post-PR25 empirical closure report

Build date: 2026-09-12  
Branch: `codex/nifty200-pit-2012-anchor`  
Working-tree HEAD: `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31`  
`origin/main`: `a8f383149187b8d0bbfb23253ba81c464ec8563f`

## Decision

**DATA EVIDENCE BLOCKED.** The full real-data build and validator completed, but the
2012-01-02 initial membership anchor is not certifiable. The nearest valid official
checkpoint is 2013-04-18. Reverse replay remains diagnostic only and is not used to
fabricate an initial universe.

Independent QA remains `NOT_ASSERTED`; import approval is not granted; Campaign
Stage A remains blocked.

## Measured final build

| Measure | Result |
|---|---:|
| Source records | 364 |
| A1 / A2 / B1 | 360 / 3 / 1 |
| Source hash failures | 0 |
| Event observations | 2,037 |
| Canonical events | 1,128 |
| ADD / DROP | 559 / 569 |
| Snapshot rows / dates | 21,650 / 108 |
| Valid 200-member checkpoints | 58 |
| Missing or non-200 checkpoints | 118 |
| Current security-master rows | 2,568 |
| Historical identity rows | 7,280 |
| Unique historical instruments | 3,450 |
| Durable-ID resolution | 100.0% |
| ISIN resolution | 100.0% |
| Unresolved identity count | 0 |
| Constituent intervals | 429 |
| NSE campaign sessions checked | 3,609 |
| Minimum / maximum active members | 0 / 123 |
| Sessions with count != 200 | 3,609 |
| Canonical known_at unresolved | 0 |
| Total conflicts | 450 |
| HIGH / CRITICAL conflicts | 75 / 375 |
| Initial validation | BLOCKED |
| Final validation | BLOCKED |

The prior post-PR25 baseline was 361 sources, 1,693 observations, 795 canonical
events, 282 intervals, and 874 conflicts. The final run added three A2 archived
security-master snapshots, fixed document-level PDF table continuation parsing, and
made identity resolution period-aware without promoting fuzzy or successor matches.
The parser fix increased official event coverage to 2,037 observations and 1,128
canonical events; reconciliation conflicts fell to 450. Symbol aliases sharing the
same durable identity/action/effective date are now treated as corroboration, which
removed the former official-source conflict without discarding either source.

The initial failure package was preserved under
`artifacts/baseline_post_pr25_20260911/`; the initial anchor diagnostic package was
preserved under `artifacts/baseline_anchor_task_20260911/`.

## Remaining blocker ledger

The machine-readable ledger contains 4,177 rows. Its final categories are:

| Blocker | Rows | Meaning |
|---|---:|---|
| COUNT_NOT_200 | 3,659 | Every campaign session is affected by the unproven initial anchor; this includes 50 official checkpoints that explicitly report 201 securities. Replay ranges from 0 to 123. |
| MISSING_INITIAL_ANCHOR | 253 | Removal events cannot be proven against a dated starting set. Exact dates/securities are in the ledger. |
| MISSING_ANNOUNCEMENT_DATE | 56 | Date-only official workbook observations lack publication/announcement timing. |
| MONTHLY_SNAPSHOT_MISSING | 69 | Ledger-level coverage blockers; the gap analysis identifies 68 months with no snapshot evidence plus the coverage conflict row. |
| MONTHLY_SNAPSHOT_NOT_200 | 50 | Official source exists but parsed checkpoint is not 200; retained for source/table audit. |
| DUPLICATE_EVENT | 122 | Replay still encounters repeated ADD assertions for already-active instruments; they remain fail-closed pending event-chain review. |
| MISSING_DURABLE_IDENTITY | 18 | Historical event rows still lack a defensible first-party durable identity. |

The 18 unresolved durable-identity rows cover Jammu & Kashmir Bank, Great Eastern
Shipping, Berger Paints, GVK Power, Opto Circuits, Orissa Min Dev, National Buildings
Construction Corporation, PC Jeweller, Tata Chemicals (two rows), Indian Railway
Catering and Tourism Corporation, NXST / Nexus Select Trust, and HAL / Hindustan
Aeronautics, plus the corresponding B1-only rows where the official mapping is not
independently established. The exact row-level date, source URL, hash, and status are
in `blocker_ledger.csv`; no fuzzy match was certified.

The event identities needing specific first-party follow-up include HAL, where the
historical ISIN evidence remains ambiguous, and NXST, which is a REIT/security type
not present in the current EQUITY_L.csv equity master. Official NSE quote/filing and
listing evidence was located for NXST but was not silently promoted into the equity
master.

## Evidence acquired/contacted

- Official Nifty Indices media, reports, monthly reports, press-release PDFs, and the
  official `IndexInclExcl.xls` change log.
- Official NSE current `EQUITY_L.csv` and `symbolchange.csv`.
- Wayback captures of official NSE `EQUITY_L.csv` dated 2011, 2017, and 2021, retained
  as A2 content-addressed historical identity evidence.
- The B1 public challenger event parquet, retained as provisional search-index data.
- Official NSE NXST quote/filing and REIT primer pages were inspected as identity
  evidence but do not replace a dated NIFTY-200 constituent record.
- The official Historical Data Reports UI was queried for NIFTY 200 from 2011-07-19
  through 2012-01-02; it returned index OHLC/close values, not constituent membership.
  Its free composition archive returned no data for December 2011 or January 2012,
  and the available composition archive begins with 2013 checkpoints. This confirms
  an external evidence gap; it is not used as a synthetic anchor.

## Required closure evidence

The next action is to obtain either:

1. an authoritative CNX/NIFTY-200 constituent list effective on or before
   2012-01-02, with a durable identifier and hash for every member; or
2. a complete first-party event chain from that date forward with announcement/publication
   timestamps, effective dates, and period-valid identity mappings.

Then resolve the 118 checkpoint gaps (68 months with no snapshot plus 50 official
201-security checkpoints), the 56 date-only observations, the 18 identity rows, and
the 253 initial-anchor/122 replay conflicts; rebuild, validate all 3,609 NSE sessions,
and obtain independent QA.

## Safety and importer

The dry-run importer returned `REFUSED_AS_DESIGNED` with exit code 1 because the
manifest validation is not PASS. `database_touched=false`. Neither
`market_data.duckdb` nor its WAL was modified, and `approved_for_import=true` was not
set.

## Verification

- PIT-focused tests: **59 passed** in 1.66s across the 11 `test_nifty200_pit_*.py` files.
- Storage tests: **9 passed** in 7.74s.
- Full suite: **918 passed, 3 warnings** in 345.86s (5:45). Warnings are the pre-existing
  `CorporateActionBasisWarning` tests.
- Ruff: **passed**.
- Mypy: **passed; no issues in 57 source files**.
- Pyright: **0 errors, 783 warnings**.
- Compileall: **passed**.
- `git diff --check`: **passed** (only Git line-ending notices were emitted).

## Artifact paths

All final artifacts are under `artifacts/nifty200_pit_v1/`, including the source
catalogue, observations, canonical events, historical identity master, aliases,
intervals, snapshots, conflicts, discrepancy report, unresolved gaps, blocker ledger,
coverage matrices, identity-resolution report, known_at audit, validation report,
manifest, hashes, dry-run result, and README.

SHA-256 of `constituent_intervals.parquet`:

`b68ef62cd5f1737c51479723578d42bb4ce90e48563a6706b3de9b409403e33a`

## Separate Campaign-governance findings

These were not mixed into the PIT changes:

- `origin/main` still has `_ensure_campaign_1_family` returning after only the
  `maximum_trials` and `universe` checks.
- `run_pipeline.py` still pins risk-policy hash
  `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c`, while
  `config/risk_policy.yaml` contains
  `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092`.
- `research_campaign_1_baseline_v2.md` is not on `origin/main`.

## Final status

NIFTY-200 PIT RECONSTRUCTION: **DATA EVIDENCE BLOCKED**  
INDEPENDENT QA: **NOT ASSERTED**  
CAMPAIGN STAGE A: **BLOCKED**
