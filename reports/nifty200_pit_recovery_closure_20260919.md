# NIFTY-200 PIT recovery closure report

**Status:** `DATA EVIDENCE BLOCKED`
**Independent QA:** `NOT_ASSERTED`
**Import approval:** `NOT_GRANTED`
**Campaign Stage A:** `BLOCKED`

## Scope

This report records the recovery build after restoring the already acquired
official/A2 corpus from the stronger PIT implementation baseline. No new web
research, B1 promotion, synthetic anchor, fuzzy identity certification, or
database import was used. The prior degraded report
`reports/nifty200_pit_free_evidence_closure_20260918.md` is retained and marked
`SUPERSEDED_BASELINE_DIAGNOSTIC`.

## Measured build

| Metric | Result |
|---|---:|
| Source records | 572 |
| Source tiers | A1=565, A2=6, B1=1 |
| Source hash failures | 0 |
| Event observations | 1,497 |
| Canonical events | 587 |
| ADD / DROP | 257 / 330 |
| Monthly snapshot rows / dates | 21,650 / 108 |
| Valid 200-member checkpoints | 58 |
| Valid expected-count checkpoints | 108 |
| Missing/non-200 checkpoints | 68 |
| Current security-master rows | 2,568 |
| Historical identity rows | 23,883 |
| Unique historical instruments | 3,444 |
| Durable-ID / ISIN resolution | 100% / 100% |
| Unresolved identity aliases | 0 |
| Constituent intervals | 256 |
| NSE sessions checked | 3,613 |
| Replay active-count range | 0..102 |
| Sessions not at expected count | 3,613 (diagnostic; anchor not established) |
| Known-at unresolved canonical events | 0 |
| Total conflicts | 281 |
| HIGH / CRITICAL conflicts | 109 / 172 |
| Validation | `BLOCKED` |

The diagnostic reverse replay contains 199 candidate initial members, but it is
not authoritative and is not used to seed membership.

## Remaining blocker ledger

| Blocker | Rows | Root cause |
|---|---:|---|
| `MISSING_INITIAL_ANCHOR` | 172 | Removal-of-absent conflicts remain downstream of the unproven 2012-01-02 starting set. |
| `MISSING_DURABLE_IDENTITY` | 69 | Historical event rows still lack an exact period-valid durable identity. |
| `MONTHLY_SNAPSHOT_MISSING` | 68 | No complete official checkpoint was acquired for the listed months. |
| `MISSING_ANNOUNCEMENT_DATE` | 39 | Official event assertions lack a causally supportable announcement/publication date. |
| `SOURCE_DOWNLOAD_FAILURE` | 1 | The cached May 2012 URL response is HTML 404, not a ZIP archive. |
| `DUPLICATE_EVENT` | 1 | One unresolved duplicate ADD remains. |
| **Total** | **350** | Validation remains fail-closed. |

The 68 missing checkpoint periods are `2012-01` through `2013-03` and
`2022-04` through `2026-08`. The source classification now distinguishes the
May 2012 HTML response from a parser failure; five previously apparent parser
failures were resolved by restoring the complete acquired corpus.

## Recovery changes measured

- Restored the 572-record acquired corpus: 565 A1, 6 A2, 1 B1.
- Restored document-level press-release parsing and exact effective-date
  propagation already supported by the stronger baseline.
- Restored eight hash-verified documented ISIN-continuity links; no legal
  predecessor/successor inference was made.
- Restored hash-verified official schedule supersession and B1 contradiction
  dispositions without promoting B1 evidence.
- Suppressed 402 redundant workbook observations from reconciliation while
  retaining their raw provenance.
- Applied the NSE calendar implementation with eight verified session
  exceptions; the calendar remains only partially certified.

## Safety

The dry-run importer returned exit code 1 with
`REFUSED_AS_DESIGNED`; `database_touched=false`,
`approved_for_import=false`, and `independent_qa=NOT_ASSERTED`. The production
DuckDB and WAL were not modified.

## Closure evidence still required

1. A dated official full NIFTY/CNX-200 roster effective on or before
   2012-01-02, with exact durable identity for each member.
2. Official complete checkpoints for the 68 missing periods.
3. Exact historical security-master or corporate-action evidence for the 69
   unresolved identity cases.
4. Official publication/announcement evidence for the 39 date-only cases.
5. A verified official replacement for the cached May 2012 HTML response.

Until those artifacts are obtained, the correct state is:

```text
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT QA:
NOT ASSERTED

CAMPAIGN STAGE A:
BLOCKED
```
