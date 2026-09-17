# NIFTY-200 PIT parser repair and rebuild

Build date: `2026-09-17`

Branch: `codex/nifty200-pit-2012-anchor`

The real corpus was rebuilt after correcting two defects exposed by the official
`ind_prs01122011.pdf` notice:

- effective dates written as `effect from December 7 , 2011` were not parsed;
- the PDF's first company-only table fragment was not joined to its later
  company/symbol fragment.

The repaired parser now extracts the official CNX 200 changes as:

| Symbol | Action | Effective date | Evidence |
|---|---|---|---|
| IBREALEST | DROP | 2011-12-07 | official A1 PDF |
| REDINGTON | ADD | 2011-12-07 | official A1 PDF |

## Measured rebuild

| Metric | Before repair | After repair |
|---|---:|---:|
| Sources | 471 | 471 |
| Event observations | 1,581 | 1,582 |
| Canonical events | 726 | 727 |
| ADD / DROP | 362 / 364 | 363 / 364 |
| Blocker ledger rows | 3,738 | 3,738 |
| Validation | BLOCKED | BLOCKED |

The repair is outside the campaign start date and therefore does not establish
the missing `2012-01-02` membership anchor. It changes the blocker classification
for the later `REDINGTON` removal from absent-membership history to a replay
membership conflict, and exposes the separate `PATNI` missing-announcement-date
blocker. It does not authorize synthetic repair.

Current blocker ledger classification:

- `COUNT_NOT_200`: 3,613 NSE campaign sessions;
- `MISSING_MEMBERSHIP_HISTORY`: 121 official removal rows;
- `REPLAY_MEMBERSHIP_CONFLICT`: 1 row (`REDINGTON`, 2012-04-27);
- `MISSING_ANNOUNCEMENT_DATE`: 1 row (`PATNI`, 2012-05-21);
- `MONTHLY_SNAPSHOT_MISSING`: 1 aggregate blocker covering 68 missing/non-200 months;
- `MISSING_INITIAL_ANCHOR`: 1 row for 2012-01-02.

The authoritative artifacts remain fail-closed: the anchor is `NOT_ESTABLISHED`,
validation is `BLOCKED`, independent QA is `NOT_ASSERTED`, and the importer dry
run is refused without touching the production database or WAL.

Regression verification: `974 passed, 3 warnings`; parser tests `13 passed`;
Ruff passed; Mypy passed; Pyright reported `0 errors, 783 warnings`; compileall
passed; `git diff --check` passed.
