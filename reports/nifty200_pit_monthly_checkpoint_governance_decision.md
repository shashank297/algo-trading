# NIFTY-200 PIT Monthly Checkpoint Governance Decision

## Decision

The monthly checkpoint gate remains BLOCKED. No missing checkpoint is
converted into a synthetic snapshot, and no non-200 result is silently
accepted as a complete historical constituent list.

The current report contains 68 non-passing checkpoint rows. The categories below are
kept separate because each requires different evidence.

| Category | Rows | Required action |
| --- | ---: | --- |
| A: no snapshot evidence | 161 | Retrieve an official historical checkpoint or record an evidence gap |
| B: candidate/zero-row extraction | 9 | Reconcile the official archive contents and parser output |
| C: wrong table or parser selection | 0 | Inspect source tables and add parser coverage |
| D: documented non-200 methodology | 0 | Obtain the methodology or official exception document |
| E: corrupt/incomplete download | 1 | Retrieve a verified archive or Wayback copy |

The May 2012 response is retained as a source-access failure because the
cached response is HTML rather than the expected archive. The official
May 16, 2012 press-release URL remains a retrieval target; its publication
does not substitute for a complete 2012-01-02 constituent checkpoint.

No governance override is authorized. The validator must continue to
require an authoritative checkpoint and replay reconciliation before import.
