# NIFTY-200 PIT residual-evidence baseline

This is the measured baseline immediately before the page-continuation parser
fix and the residual-evidence rebuild on 2026-09-19. It is preserved so the
closure report can distinguish this task's changes from earlier work.

## Build metrics

| Metric | Baseline |
|---|---:|
| Source records | 585 |
| Source hash errors | 0 |
| Event observations | 1,496 |
| Canonical events | 623 |
| ADD events | 281 |
| DROP events | 342 |
| Monthly snapshot rows | 21,650 |
| Snapshot dates | 108 |
| Valid 200-member checkpoints | 58 |
| Constituent intervals | 280 |
| Conflicts | 220 |
| HIGH conflicts | 49 |
| CRITICAL conflicts | 171 |
| Trading sessions checked | 3,613 |
| Minimum active constituents | 0 |
| Maximum active constituents | 108 |
| Sessions not at expected count | 3,613 |
| Known-at unresolved | 0 |
| Validation | BLOCKED |

## Blocker counts

| Blocker type | Count |
|---|---:|
| MISSING_INITIAL_ANCHOR | 171 |
| MONTHLY_SNAPSHOT_MISSING | 68 |
| MISSING_ANNOUNCEMENT_DATE | 48 |
| MISSING_DURABLE_IDENTITY | 0 |
| SOURCE_DOWNLOAD_FAILURE | 1 |
| DUPLICATE_EVENT | 1 |
| Total ledger rows | 289 |

The baseline was generated from the existing post-PR25/current-security-master
build before official multi-page NIFTY-200 press-release continuation parsing
was corrected. The unresolved database/WAL was not opened or modified.
