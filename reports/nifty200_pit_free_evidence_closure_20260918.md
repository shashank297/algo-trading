# NIFTY-200 Free Evidence Closure Audit

**Status:** `SUPERSEDED_BASELINE_DIAGNOSTIC` — this report describes the pre-recovery degraded build and is retained for lineage only.

**Audit date:** 2026-09-18
**Repository HEAD:** `a8f383149187b8d0bbfb23253ba81c464ec8563f`
**Dataset build used:** `artifacts/nifty200_pit_v1/validation_report.json` generated `2026-09-18T11:15:29.897174+00:00`
**Result:** DATA EVIDENCE BLOCKED
**Independent QA:** NOT ASSERTED
**Campaign Stage A:** BLOCKED

## Scope and decision

This pass searched for free, first-party evidence for the remaining anchor,
checkpoint, and historical identity gaps. No newly acquired authoritative bytes
met the certification rules. No B1 row, fuzzy match, company-name-to-ISIN
inference, or predecessor/successor merge was promoted. Existing artifacts and
their fail-closed status were therefore preserved; no rebuild was run because
there was no new source or parser change to rebuild.

The row-level inventory remains authoritative in
`artifacts/nifty200_pit_v1/blocker_ledger.csv`; the existing detailed inventory
is preserved in `reports/nifty200_pit_evidence_gap_report_20260918.md`.

## Current measured blocker state

| Blocker type | Rows | Dates / scope | Missing evidence | Status |
|---|---:|---|---|---|
| `MISSING_INITIAL_ANCHOR` | 1 | 2012-01-02 | A dated official full 200-member CNX/NIFTY-200 roster with durable identities | `UNRESOLVED / MANUAL_REVIEW` |
| `MONTHLY_SNAPSHOT_MISSING` | 69 ledger rows, representing 68 missing periods | 2012-01..2013-03 and 2022-04..2026-08 | An official checkpoint containing the period's NIFTY-200 constituents | `UNRESOLVED / MANUAL_REVIEW` |
| `MISSING_DURABLE_IDENTITY` | 1,050 | Official event observations, mainly `IndexInclExcl.xls` and press-release assertions | A period-valid historical symbol/ISIN record and, where needed, corporate-action continuity proof | `UNRESOLVED / MANUAL_REVIEW` |
| `OTHER / NO_CERTIFIABLE_EVENTS` | 1 | Complete event chain | Publication/announcement causality sufficient for canonical certification | `UNRESOLVED / MANUAL_REVIEW` |
| **Total** | **1,121** |  |  | **BLOCKED** |

All 1,121 ledger rows remain unresolved. The ledger has 1 CRITICAL row (the
initial anchor) and 1,120 HIGH rows. `unresolved_gaps.csv` contains 68 blocked
monthly periods; `monthly_gap_analysis.csv` distinguishes 108 passing official
months from 68 `A_NO_SNAPSHOT_EVIDENCE` months.

## Exact evidence gaps and closure requirements

### 1. Initial anchor — 2012-01-02

The launch notice defines the CNX 200 methodology and launch context but does
not contain the 200-member roster. The historical inclusion/exclusion workbook
is a delta log, not a starting roster. Reverse replay from the first available
forward checkpoint is not proof of the initial state.

**Required closure artifact:** an official NSE/NSE Indices/IISL CSV, XLS, PDF,
or circular that lists all 200 members effective on 2012-01-02 (or an official
launch annexure with an unambiguous effective date), including exchange symbol
and durable identity/ISIN or an explicit official identity link for every row.

### 2. Missing monthly checkpoints

The exact missing periods are:

- `2012-01` through `2013-03` — 15 periods; the public historical-report
  endpoint returned no report for these periods and no official NIFTY-200 member
  file was acquired.
- `2022-04` through `2026-08` — 53 periods; the free monthly archive form and
  ZIP pattern were checked, but the acquired bundles did not contain a
  NIFTY-200 constituent report.

**Required closure artifacts:** one official constituent/weightage file for
each of the 68 periods, with the report date and the complete member rows. A
methodology or index-level return series does not close a membership checkpoint.

### 3. Historical durable identity — 1,050 rows

The official event corpus contains dated company/event assertions, but many
rows lack a period-valid ISIN and exchange identity. Current `EQUITY_L.csv` is
an official current snapshot, not a historical security master. NSE
`symbolchange.csv` and `namechange.csv` are retained as candidates only; they
do not independently prove historical ISIN continuity. Official daily NSE press
pages can contain symbol/ISIN for individual listings, but the pages checked do
not provide a complete historical identity table for the affected NIFTY-200
events or prove predecessor/successor continuity for every row.

**Required closure artifact:** for each affected event/company/date, an
official historical security master row, listing/admission notice, or
corporate-action/merger/delisting circular that binds the historical symbol to
the exact ISIN and identifies the valid period. For a renamed, merged, or
delisted security, the document must explicitly link the old and new durable
identities. A name-only match, fuzzy match, current-symbol match, or B1 row is
not sufficient.

### 4. Canonical event and causality closure

Because durable identity is not established across the event set, no canonical
event is currently certifiable. The exact missing evidence is a complete
announcement/publication/effective-date chain with a conservative `known_at`
for every event that would enter the replay.

**Required closure artifact:** an official dated publication or circular for
each event, with a verifiable announcement/publication timestamp or an
explicitly supportable date-only causality basis.

## First-party URLs checked in this pass

- [Nifty 200 index page](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-200) — current constituent download and methodology; no historical checkpoints.
- [Nifty monthly reports](https://niftyindices.com/reports/monthly-reports) and [historical reports](https://www.niftyindices.com/reports) — archive/report forms; no missing-period NIFTY-200 member files were acquired.
- [CNX 200 launch notice](https://www.niftyindices.com/Press_Release/ind_prs18072011.pdf) — methodology/launch notice, no full roster.
- [Nifty press-release archive](https://niftyindices.com/press-release) — dated change notices, not a complete initial roster or historical identity master.
- [NSE securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading) — current equity master and current change tables.
- [NSE equity market-data reports](https://www.nseindia.com/static/products-services/equity-market-data-reports-download) and [historical capital-market reports](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives) — report descriptions and historical archive navigation; no free historical NIFTY-200 identity master was found.
- [NSE historical inclusion/exclusion workbook](https://archives.nseindia.com/content/indices/IndexInclExcl.xls) — event/delta evidence without a complete initial roster or durable identity fields.
- [NSE symbol changes](https://nsearchives.nseindia.com/content/equities/symbolchange.csv) and [name changes](https://nsearchives.nseindia.com/content/equities/namechange.csv) — candidate relationships without historical ISIN continuity.
- [NSE Masters Data specification](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE-Masters%20Data-v1.6.pdf) — confirms security-master fields, but is not a historical data extract.
- Representative official NSE daily press pages [27-Jan-2012](https://nsearchives.nseindia.com/content/press/27012012.htm), [09-Mar-2012](https://nsearchives.nseindia.com/content/press/09032012.htm), [20-Mar-2012](https://nsearchives.nseindia.com/content/press/20032012.htm), and [11-Apr-2012](https://nsearchives.nseindia.com/content/press/11042012.htm) — individual listing/ISIN evidence, not a complete historical NIFTY-200 membership or identity table.
- [NSE Indices data subscription](https://www.niftyindices.com/offerings/data-subscription) — confirms historical constituent data is offered as a data product; paid/subscription evidence was not used.

## Current build measurements

The preserved build remains:

- sources: 363 (`A1=362`, `A2=0`, `B1=1`), hash failures 0;
- observations: 1,446; canonical events 0 (`ADD=0`, `DROP=0`);
- snapshots: 21,650 rows across 108 dates; valid 200-member checkpoints 58;
  valid expected-count checkpoints 108; missing/non-200 periods 68;
- identity: current master 2,578 rows; historical identity table 6,896 rows;
  unique current historical instruments 2,578; durable-ID/ISIN resolution
  43.3861%; unresolved aliases 3,364;
- intervals: 0; campaign sessions checked 3,609; active count min/max 0/0;
  sessions not at expected count 3,609 (not evaluable without anchor/events);
- known-at unresolved count 0 (vacuous because no canonical events exist);
- conflicts: 1,052 total, 1,052 HIGH, 0 CRITICAL;
- validation: `BLOCKED`, anchor `NOT_ESTABLISHED`, count validation
  `false`.

## Safety and verification

No source catalogue, identity table, blocker ledger, validation artifact, or
production database was modified by this closure pass. The correctly scoped
dry-run importer refused the blocked manifest with `REFUSED_AS_DESIGNED`, exit
code 1, and `database_touched=false`. `approved_for_import=false` and
`independent_qa=NOT_ASSERTED` remain unchanged.

Verification run with repository-local pytest temporary roots:

- NIFTY-200 PIT tests: **62 passed**;
- storage tests: **9 passed**;
- Ruff: **pass**;
- Mypy: **pass, 57 files**;
- Pyright: **0 errors, 867 existing warnings**;
- compileall: **pass**;
- `git diff --check`: **pass** (only existing CRLF normalization warnings).

## Next exact action

Obtain one of the required first-party closure artifacts above—starting with a
full 2012-01-02/launch roster and a period-valid historical NSE security master.
Then add and hash only that evidence, update the existing parser/identity
tables, rebuild, and compare this report against the prior blocker ledger. Until
that evidence exists, the correct operational state is:

```text
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT QA:
NOT ASSERTED

CAMPAIGN STAGE A:
BLOCKED
```
