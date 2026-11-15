# Detailed bounded PIT readiness recheck

Decision: **BOUNDED_PIT_VALIDATION_BLOCKED**.

Scope: 2016-01-29 through 2022-03-31. Current checkout is `C:/Python projects/algo trading`, branch `codex/nifty200-pit-residual-evidence`, starting HEAD `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`. The authoritative checkout at `C:/Python projects/algo trading-authoritative-evidence` was read only. Existing changes were preserved. This recheck added diagnostic scripts and results plus this report; it changed no production source, tests, historical reports, evidence inputs, or manifests.

## Corrections to the preceding status

The historical membership closure records 74/74 certification-grade replay and zero economic divergences. That historical decision remains recorded. However, the maintained executable package has not independently reproduced it: the previous bounded audit contains 64/74 exact comparisons and ten unresolved endpoint identity-namespace discrepancies. Those ten differences are not proven economic membership errors. This recheck inspected that stored diagnostic; it did not rerun its historical replay helper.

The 310-row `regenerated_bounded_events_run1.parquet` is a comparison diagnostic produced by the prior bounded audit, not a certified replacement package. Both the stored residual outputs and the isolated rebuild differ from it. A current all-layer bounded PASS has never been demonstrated.

The 2016-01-29 checkpoint exists with 200 certified ledger rows. Calling the bounded anchor simply missing is imprecise. What is absent is its verified consumption as a bounded seed, with causal availability, complete identity lineage, and coherent intervals. The uncertified 2012 global anchor is a separate wider-history issue.

## Fresh verification

| Item | Fresh result | Meaning |
|---|---|---|
| Residual source catalogue | 585 records / 565 unique hashes; 0 missing files or hash mismatches | Raw registered bytes match |
| Authoritative source catalogue | 603 records / 583 unique hashes; 0 missing files or hash mismatches | A different registered corpus, also hash-valid |
| Residual artifact manifest | 45/45 artifact hashes match | Integrity does not imply correctness or readiness |
| Authoritative artifact manifest | 45/46 match | Continuity artifact and manifest disagree |
| Bounded checkpoint ledger | 15,050 rows / 75 dates; all CERTIFIED_UNIQUE; 0 duplicate row IDs | Ledger identity population is present |
| First bounded checkpoint | 200 rows on 2016-01-29 | Candidate bounded seed exists |
| Legitimate 201-member checkpoints | 50; all retain TATAMTRDVR | Preserved without reducing counts |
| Seven NSE calendar PDFs | 7/7 SHA-256 hashes match the prior certificate | Preserved official bytes verified |
| Calendar event ledger | 310 rows; stored chronology, known_at and effective-session statuses each 310 PASS | Recounted stored results, not newly executed calendar certification |
| Calendar PDF hashes in either executable source catalogue | 0/7 | Certificate sources are not registered in either executable catalogue |
| Prior OCR verification input hashes | 0 changed files across its seven source/test/requirements entries | Those earlier tested files have not drifted |

The authoritative continuity mismatch is `artifacts/nifty200_pit_v1/identity_continuity_evidence.json`. The prior bounded audit already recorded it: manifest hash `3e52643736902de73574c8f85720297d3761b0821c6e16cb9c45f15e0e40f384`, file hash `09f0711a3bc9268e3644382bfdd476376c84018f3ad87d02f3eab51177c2e4ed`. This recheck independently confirms a mismatch. Regenerate a coherent new package from reviewed inputs; changing the recorded checksum alone would not establish correctness.

## Populations must remain separate

| Population | Bounded events | Missing versus 310 comparison keys | Bounded conflicts |
|---|---:|---:|---:|
| Stored residual `data/derived/nifty200_pit` | 298 | 12; zero extras | 38: 37 absent-member removals, 1 duplicate ADD |
| Isolated `.arena/pit-evidence-closure-20261102/rebuild-full` | 271 | 39; zero extras | 81: 45 missing durable identity, 35 absent-member removals, 1 duplicate ADD |
| Prior bounded comparison diagnostic | 310 | Reference population only | Not a complete executable replacement package |

Both residual populations retain 75 checkpoints and 15,050 checkpoint rows: 25 checkpoints of 200 and 50 of 201. Neither bounded event population contains duplicate symbol/action/effective-date keys. The `DUPLICATE_ADD` conflict describes replay state (adding an already active instrument), which differs from duplicate event keys.

The isolated rebuild predates integrated consumption of the latest OCR fix. Its 39 missing key occurrences comprise 27 parsed but unresolved identity cases and 12 scanned-release observations. The latter have since been recovered separately and remain MANUAL_REVIEW. The 27 cases and 45 identity-conflict records are different denominators and must not be summed or treated as equivalent counts.

## Actual validator execution and limitations

The current `tools/nifty200_pit/validation.py:validate_campaign` was executed directly using the same event/interval/conflict deserializers used by the CLI and the existing isolated rebuild. This avoids rewriting the old CLI validation report. New output: `.arena/pit-evidence-closure-20261102/detailed-recheck/actual_validator.json`.

Result: **BLOCKED**, 277 reasons, 0 sessions checked, count validation not evaluable, 604 global events, 289 intervals, 273 HIGH/CRITICAL global conflicts. Initial reasons are `trading_days_required`, `trading_days_empty`, `calendar_not_certified`, and `initial_anchor_not_established`. This is execution against the existing rebuild, not validation of a newly assembled certified bounded package. Source hashes were independently verified above; the isolated function invocation did not pass a fabricated certification flag or calendar.

The CLI accepts historical bounds but exposes no evidence-bound anchor or calendar artifact input and no 200/201 expected-count map. Its validate branch loads all events and conflicts without establishing bounded applicability. Date bounds alone do not produce a complete bounded validation.

Additional isolated caller-contract probes used artificial fixtures, with no evidence promotion or production data:

| Probe | Direct API result |
|---|---|
| Baseline with 200 certified fixture intervals | PASS |
| One event known_at moved to 2030, intervals unchanged | PASS |
| One event changed to MANUAL_REVIEW, intervals unchanged | PASS |
| Session list omits the final requested session | PASS |
| One event marked synthetic (negative control) | BLOCKED |

These prove the direct validator does not independently enforce event/interval causal consistency, event review eligibility, or completeness of caller-asserted sessions. Other pipeline stages may reject such inputs; these probes do not establish a bypass of the whole ingestion pipeline. They do establish that plumbing booleans and dates into this function alone is insufficient for the requested end-to-end certificate. The bounded assembly/validation path needs explicit evidence, cross-artifact consistency checks, exact checkpoint membership comparisons, chronology/known_at/session checks, and complete source linkage, with meaningful failing regressions before implementation changes.

## Remaining work, in dependency order

1. Review and freeze the intended source changes and corpus. The checkout is dirty and differs from the authoritative commit; neither source state is an integrated bounded release.
2. Make the already admitted continuity and identity dispositions executable. Resolve the ten stored namespace comparisons and the previously documented four canonical-event identity rekeys/YESBANK metadata mismatch through existing admitted evidence. Recheck these affected rows when assembling the new package; this turn did not independently recalculate all four rekeys.
3. Adjudicate the 27 unresolved event identity cases using admissible dated source segments; review the 12 OCR observations against the official release. Do not copy asserted ISINs from event-result files into resolver inputs.
4. Reconcile every in-scope conflict against the seeded membership and source chronology, including the 35 absent-member removals and ABBOTINDIA duplicate ADD in the isolated rebuild. Earlier official-release/checkpoint checks support the ABBOTINDIA 2022-03-31 transition but do not explain the conflicting prior active state. Evidence closure must be demonstrated before any conflict is dispositioned as nonblocking.
5. Build and validate an evidence-bound bounded adapter: consume the certified first checkpoint with causal availability, register/consume the certified NSE calendar transformation and complete session artifact, retain source-backed 200/201 counts, preserve pre-bound knowledge, apply complete continuity, and prove bounded applicability of every global/undated blocker. Enforce the direct API gaps demonstrated above in the actual certification path.
6. Produce a coherent new events/intervals/conflicts/calendar/lineage package and fresh manifests. Regenerate twice from the selected registered corpus, compare exact outputs, and explain every difference from existing certified components. Full integrated deterministic reproduction is still NOT_EVALUABLE.
7. Execute the actual validator successfully on that package and run required CI, coverage, regression and static gates against the exact intended frozen source. Then establish the campaign baseline and obtain independent bounded PIT/data QA and import approval under the documented governance.

## Tests and scope of this recheck

- Fresh complete PIT-specific suite: **147 passed in 6.20 seconds**, exit 0.
- Fresh MyPy for `tools/nifty200_pit`: **20 source files, no issues**, exit 0.
- Fresh Ruff for the PIT package and changed PIT test files: **passed**, exit 0.
- Fresh direct validator invocation and five artificial contract probes completed; evidence package stayed BLOCKED.
- The earlier 1,040-test full run plus the later OCR test is historical verification. This turn did not rerun the full suite, coverage, global Mypy or Pyright. Previously reported 43 global Mypy errors/other warnings are not freshly remeasured here. Exact final-source CI remains required after assembly changes.
- No Arena tournament verdict is available; the earlier tournament stopped before producing candidates because child agents hit usage limits. This local recheck makes no independent QA claim.

Machine-readable evidence: `.arena/pit-evidence-closure-20261102/detailed-recheck/results.json`, `supplement.json`, and `actual_validator.json`. Diagnostic scripts are `detailed_recheck.py`, `detailed_supplement.py`, and `run_detailed_tests.py` in the parent scratch directory. The results distinguish current measurements, artificial probes, and historical diagnostics.

No production database/WAL, Stage A, actual backtest, optimization, trading, broker integration, import, commit, push or merge was used. Ending HEAD remains `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`.

INDEPENDENT PIT/DATA QA: NOT ASSERTED  
IMPORT APPROVAL: NOT GRANTED  
CAMPAIGN STAGE A: BLOCKED
