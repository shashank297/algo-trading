# NIFTY-200 PIT Corpus Reconciliation

Date: 2026-09-20  
Repository: `shashank297/algo-trading`  
Worktree: `C:\Python projects\algo trading-authoritative-evidence`  
Branch: `codex/nifty200-pit-authoritative-evidence`  
HEAD: `635acfcf62596c0c145f4032dde1e7020407e98e`  
`origin/main`: `635acfcf62596c0c145f4032dde1e7020407e98e`

## Scope

This report documents the reproducibility repair for the NIFTY-200 public-evidence
corpus. It does not change PIT semantics, fabricate historical constituents, or
certify unresolved evidence. Campaign Stage A, research, trading, database import,
and independent QA remain blocked.

The prior local governance changes in the two anchor-forensics reports were
preserved and were not mixed into this repair.

## Finding

The apparent post-PR#29 collapse was caused by loss of raw source bytes in the
clean checkout:

| Build state | Sources | Event observations | Canonical events | Historical identity rows | Intervals | Conflicts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prior authoritative build | 585 | 1,544 | 641 | 196,196 | 306 | 165 |
| Degraded clean checkout | 362 | 1,534 | 0 | 6,896 | 0 | 1,145 |
| Recovered checkout | 587 | 1,544 | 641 | 196,196 | 306 | 165 |

The 587 recovered sources contain the prior 585-record corpus plus two newer A1
records already present in the clean checkout. Comparing the common 585-record
corpus, all measured substantive outputs match the prior build. This confirms that
the missing historical bhavcopy/security-master/evidence files, combined with the
fail-closed temporal identity rules, caused the 641-to-0 canonical-event result.

The two additional records are:

| Source ID | Tier | Type | URL | Local path | SHA-256 | Why absent from prior 585 | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `7c6300a2033d6495bf92561a46189d4383c8a5d31bf39ea0c79c738fa3c64b6c` | A1 | HTML press-release archive | `https://www.niftyindices.com/press-release` | `data/raw/nifty200_pit_public_sources/press_releases/press_release_archive.html` | `474c3bf91e3a3476c6443b12bb2c9c308ce2c63489b526407fa770cf472fb6d1` | Retrieved after the prior 585-source catalogue was created | Legitimate first-party archive/provenance source; retained |
| `ffa5e8fb12fa07d6f6abe3d3c252f132be7ef1b3901d9c1ea388b9ed8b04d671` | A1 | PDF press release | `https://www.niftyindices.com/Press_Release/ind_prs15092026.pdf` | `data/raw/nifty200_pit_public_sources/press_releases/candidates/ind_prs15092026.pdf` | `10598bd797d673082be4055d1916fa98e9aea300f3d103bf67b7851417e97356` | Retrieved after the prior 585-source catalogue was created | Legitimate first-party evidence; outside the 2026-08-20 campaign end and metric-neutral; retained |

Neither record is a duplicate by `(source_url, source_sha256)`. They were not
removed merely to force the source count back to 585.

## Exact source delta

The path-level and source-record inventories are preserved at:

- `reports/nifty200_pit_corpus_inventory_20260920.csv`
- `reports/nifty200_pit_source_delta_20260920.csv`

The old catalogue had 585 records and the degraded catalogue had 362 records:

- 360 record keys were common.
- 225 old record keys were absent from the degraded checkout: 219 A1 and 6 A2.
- The degraded checkout had 2 new-only A1 records.
- The net loss was 223 source records.
- The 225 old-only records represented 206 unique source hashes; 205 unique hashes
  were absent by content from the degraded checkout, while one hash was present
  under a different URL.
- Every old-only local file existed in the old checkout and matched its recorded
  SHA-256. No source hash error was found during restoration.
- Old-only source statuses were 157 downloaded, 53 `NO_NIFTY200_CHECKPOINT`, and
  15 `UNUSABLE_HTML_RESPONSE`.
- Old-only content types were 130 ZIP, 53 ZIP-compressed, 18 PDF, 16 HTML, 4 CSV,
  3 text/CSV, and 1 plain text.
- URL-family classification was 134 historical security-master/bhavcopy-like,
  16 press-release/circular-like, 3 Wayback, 2 index-report/snapshot-like, and
  70 other official/archive records.

All 225 old-only source records were restored to content-addressed raw paths in
the new worktree. Raw evidence remains ignored by Git; no source bytes were added
to the commit. The merged current catalogue has 587 records and all current
catalogue paths pass recorded SHA verification.

## Reproducibility guard

The following tracked files were added or changed:

- `tools/nifty200_pit/corpus.py`
- `config/nifty200_pit_corpus_requirements.json`
- `tools/nifty200_pit/build_public_dataset.py`
- `tests/test_nifty200_pit_sources.py`

The requirements manifest records the exact 585-record authoritative baseline,
including source URL, SHA-256, tier, local relative path, size, and content type.
The builder now verifies both required raw bytes and their presence in the loaded
source catalogue before parsing. Missing metadata or bytes fails closed with
`CORPUS_INCOMPLETE`; it cannot silently produce an apparently valid but empty
canonical dataset. The two new A1 sources remain in the current catalogue but are
not silently substituted for any required baseline record.

## Recovered build metrics

The current generated artifacts under `artifacts/nifty200_pit_v1/` report:

- Sources: 587; A1 580, A2 6, B1 1; source hash failures 0.
- Event observations: 1,544.
- Canonical events: 641; ADD 308; DROP 333.
- Monthly snapshots: 21,650 rows across 108 dates; 58 valid 200-member
  checkpoints; 68 missing or non-200 checkpoints.
- Current security-master rows: 2,578.
- Historical identity rows: 196,196; unique historical instruments 3,874.
- Certified historical identity rows: 192,097; unresolved historical identity
  rows: 65.
- Durable-ID resolution: 43.8472%; ISIN resolution: 43.8472% under the
  validator's historical-event-row denominator.
- Constituent intervals: 306.
- Conflicts: 165 total, 31 HIGH, 134 CRITICAL.
- `known_at` unresolved: 0 for the 641 canonical events.
- Validation: `BLOCKED`.
- Calendar audit: `PARTIAL_NOT_CERTIFIED`; anchor: `NOT_ESTABLISHED`.

The campaign-session diagnostic covers 3,613 sessions. Because the initial anchor
is not established, daily replay counts are not certifiable: the diagnostic range
is 0 to 117 and all 3,613 sessions are reported as not expected. These are not
treated as certified constituent-count failures.

## Remaining blockers

The current `artifacts/nifty200_pit_v1/blocker_ledger.csv` contains 235 unresolved
ledger rows:

| Root category | Rows | Meaning | Evidence needed |
| --- | ---: | --- | --- |
| `MISSING_INITIAL_ANCHOR` | 133 | One root 2012-01-02 anchor gap produces replay diagnostics that cannot be certified. | A complete authoritative NIFTY-200/CNX-200 constituent list valid on 2012-01-02, with durable identity evidence. |
| `MONTHLY_SNAPSHOT_MISSING` | 68 | Official monthly checkpoints are absent or not usable in the acquired corpus. | The exact official monthly NIFTY-200 member/weight file, or a verified Wayback copy, for each affected period. |
| `MISSING_DURABLE_IDENTITY` | 30 | Historical event rows still lack a certifiable durable identity. | Official historical security master, ISIN mapping, symbol/name-change, merger, or delisting document linking the exact instrument and valid period. |
| `DUPLICATE_EVENT` | 2 | Two duplicate ADD observations remain in the event evidence set. | An official correction/superseding notice or enough first-party publication metadata to resolve the duplicate causally. |
| `SOURCE_DOWNLOAD_FAILURE` | 1 | The May 2012 archive URL returned HTML instead of the expected archive. | The original official May 2012 archive or a hash-verifiable Wayback capture of that archive. |
| `OTHER` | 1 | Calendar provenance is not fully certified. | A complete authoritative NSE trading-calendar source/exception audit for the campaign interval. |

The conflict report explains the 165 conflicts in more detail: 132 critical
`REMOVAL_OF_ABSENT_MEMBER`, 2 critical `DUPLICATE_ADD`, 30 high
`MISSING_DURABLE_IDENTITY`, and 1 high `COVERAGE_GAP`. The 132 removal conflicts
are downstream of the unresolved initial anchor and must not be “fixed” by
inventing membership.

The 68 monthly gaps are retained with their A-E source classifications in
`reports/nifty200_pit_monthly_gap_analysis.csv`. They must not be collapsed into
one generic failure: the May 2012 HTML response is a source-download failure,
whereas the other gaps require a per-period determination of absent source,
parser failure, wrong table selection, count exception, or incomplete download.

## Preserved evidence and safety boundaries

The degraded baseline artifacts were preserved before restoration under:

`artifacts/nifty200_pit_v1_baseline_authoritative_phase_20260920/`

The earlier degraded narrative reports were preserved rather than overwritten:

- `reports/nifty200_pit_authoritative_phase_baseline_20260920.md`
- `reports/nifty200_pit_authoritative_evidence_gap_report_20260920.md`

No production database, `market_data.duckdb`, WAL, authoritative import, or old
worktree file was modified. The importer is limited to dry-run and
`approved_for_import` remains false/not granted. Independent QA remains
`NOT_ASSERTED`.

The final dry-run command was refused as designed with exit code 1 and
`ValueError: Manifest validation is not PASS; import refused`; its recorded
result is `artifacts/nifty200_pit_v1/dry_run_import_result.json` with
`database_touched: false` and `REFUSED_AS_DESIGNED`.

## Artifact pointers

- Validation: `artifacts/nifty200_pit_v1/validation_report.json`
- Blocker ledger: `artifacts/nifty200_pit_v1/blocker_ledger.csv`
- Unresolved gaps: `artifacts/nifty200_pit_v1/unresolved_gaps.csv`
- Evidence manifest: `artifacts/nifty200_pit_v1/evidence_manifest.json`
- Constituent intervals: `artifacts/nifty200_pit_v1/constituent_intervals.parquet`
- Historical identity: `artifacts/nifty200_pit_v1/historical_instrument_master.parquet`
- Source delta: `reports/nifty200_pit_source_delta_20260920.csv`
- Corpus inventory: `reports/nifty200_pit_corpus_inventory_20260920.csv`

Current SHA-256 of `constituent_intervals.parquet`:

`d01ae32acbe9db66e7fa86a2bc2c9a6e68ca9fe7d4cbe80f8a8250be4ec252c5`

## Status

NIFTY-200 PIT RECONSTRUCTION: **DATA EVIDENCE BLOCKED**  
INDEPENDENT QA: **NOT ASSERTED**  
IMPORT APPROVAL: **NOT GRANTED**  
CAMPAIGN STAGE A: **BLOCKED**
