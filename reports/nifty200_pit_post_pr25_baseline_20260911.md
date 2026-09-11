# NIFTY-200 PIT post-PR25 baseline

Initial post-PR25 real build baseline, captured before remediation in this run.

- Build timestamp: 2026-09-11T04:02:43Z (UTC)
- Build worktree HEAD: `915afa8dca7a44097842f83917b6dc0619c5d2c1`
- Remote main at verification: `a358ed3c2139f9c364c2b53fc749babc9f136a26`
- Campaign: 2012-01-02 through 2026-08-20
- Source records: 359 (A1 358, A2 0, B1 1); source hash errors 0
- Event observations: 1,866 (ADD 746, DROP 1,084, unclassified 36)
- Canonical events: 935 (ADD 375, DROP 560)
- Current security-master identity rows: 2,568
- Alias rows: 2,940 (certified 2,568, unresolved/manual-review 372)
- Constituent intervals: 316
- Monthly snapshot rows: 21,650 across 108 dates; valid 200-member checkpoints 46; missing/non-200 checkpoints 130
- Conflicts: 913 (HIGH 539, CRITICAL 372, MEDIUM 2)
- Trading days checked: 3,819; count-check failures: 3,819; minimum/maximum replay counts require the blocker ledger audit
- Anchor differences: 130
- Validation: `BLOCKED`
- Dry-run importer: exit 1, `REFUSED_AS_DESIGNED`, `database_touched=false`

The complete pre-remediation artifact copy is preserved under `artifacts/baseline_post_pr25_20260911/`. The live Nifty Indices press-release page also timed out during this run; no unverified replacement was used.
