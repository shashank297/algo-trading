# NIFTY-200 PIT authoritative-evidence phase baseline

This baseline was generated before any evidence-closure changes in the clean
authoritative-evidence worktree.

- Worktree HEAD: `635acfcf62596c0c145f4032dde1e7020407e98e`
- Build status: `BLOCKED`
- Source count: 362 (`A1=361`, `A2=0`, `B1=1`)
- Source hash errors: 0
- Event observations: 1,534
- Canonical events: 0 (`ADD=0`, `DROP=0`)
- Snapshot rows: 21,650 across 108 dates
- Valid 200-member checkpoints: 58
- Missing/non-200 checkpoints: 68
- Current security-master rows: 2,578
- Historical identity rows: 6,896
- Unique historical instruments: 2,578
- Durable identity resolution among historical event rows: 91.26%
- ISIN resolution among historical event rows: 91.26%
- Unresolved historical event identity cases: 1,520
- Constituent intervals: 0
- Trading sessions checked: 3,609
- Minimum/maximum active constituents: 0 / 0
- Sessions not at expected count: 3,609
- Known-at unresolved: 0 (no canonical events)
- Conflicts: 1,145 total; HIGH 1,145; CRITICAL 0
- Blocker ledger: 1,215 rows
- Blockers: `MISSING_DURABLE_IDENTITY=1,143`,
  `MISSING_INITIAL_ANCHOR=1`, `MONTHLY_SNAPSHOT_MISSING=69`, `OTHER=2`

The initial build used the existing acquisition and build pipeline only. No
production database or WAL was accessed.
