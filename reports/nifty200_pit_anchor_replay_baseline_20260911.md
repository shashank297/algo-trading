# NIFTY-200 PIT anchor-task baseline

Captured from the existing builder before adding the anchor replay diagnostic.

- Build date: 2026-09-11
- Builder HEAD: `1cd6160c12c9954191e3af76fb2c7713e4c2a37e`
- origin/main: `a358ed3c2139f9c364c2b53fc749babc9f136a26`
- Campaign: 2012-01-02 through 2026-08-20
- Sources: 359 total; A1 358; A2 0; B1 1; source hash failures 0
- Event observations: 1,866; canonical events: 935; canonical ADD 375; DROP 560
- Monthly snapshots: 21,650 rows across 108 dates; valid 200-member checkpoints 58; missing/non-200 checkpoints 118
- Current security-master rows: 2,568; historical identity rows: 2,654; unresolved identities 86
- Durable-ID resolution: 96.7596%; ISIN resolution: 96.7596%
- Constituent intervals: 316
- NSE sessions: 3,609; replay range 0..87; sessions not equal to 200: 3,609
- Known-at unresolved canonical events: 0
- Conflicts: 914 total; HIGH 539; CRITICAL 373
- Blocker ledger: 4,639 rows
- Validation: `BLOCKED`
- Dry-run importer: exit 1, `REFUSED_AS_DESIGNED`, `database_touched=false`

The initial failure-state files are preserved under
`artifacts/baseline_anchor_task_20260911/`. The normal authoritative artifacts
were not changed by the anchor diagnostic; it is explicitly non-authoritative.
