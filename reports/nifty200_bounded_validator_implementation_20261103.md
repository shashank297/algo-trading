# Bounded PIT validator implementation

Data decision: **BOUNDED_PIT_VALIDATION_BLOCKED**.

Date: 2026-11-03 IST. Requested data scope: 2016-01-29 through 2022-03-31.
Worktree: `C:\Python projects\algo trading`. Branch: `codex/nifty200-pit-residual-evidence`.
Starting and ending HEAD: `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`. Changes remain uncommitted; the pre-existing dirty work was preserved.
The authoritative evidence checkout was not modified.

## Implemented

- New `tools/nifty200_pit/bounded_validation.py` verifies hash-bound artifacts, registered raw source bytes, accepted A1/A2 provenance, complete daily calendar coverage, actual session openings, explicit 200/201 count evidence, starting membership and causal availability, and period-valid identity proofs.
- The reader independently carries membership through every bounded session, applies only admitted dated continuity/symbol transitions, validates identity coverage/competitors between checkpoints, compares exact checkpoint and interval member sets, and executes the existing `validate_campaign` function once evidence is evaluable. Equal counts alone cannot pass.
- Entry and exit lineage, original interval symbol/ISIN fields, first-day event postconditions, date-only conservative availability, the existing EXACT_SOURCE_TIMESTAMP policy, IST date semantics, and same-day normalized event collisions are checked. Date-only sources cannot prove same-day pre-opening availability. Publication hash, URL, tier and timing must hold on the same registered source record.
- Pre-bound and undated HIGH/CRITICAL conflicts remain blocking. Post-bound conflicts and interval exit metadata are explicitly recorded outside scope, without asserting those later facts are validated. Legitimate 201-member/DVR states are preserved.
- The CLI accepts `validate --evidence-package ... --output ...`; the output must be a new JSON file. This path does not overwrite historical reports or create legacy output directories. The generic validator also now rejects unaccepted/provisional/non-authoritative events and future known_at dates after IST normalization.
- Schema, producer responsibilities and exact evidence boundaries are documented in `C:\Python projects\algo trading\docs\nifty200_bounded_validation.md`. This is an evidence consumer, not an automatic raw-source certifier or a completed real-data package producer.

## Regression and review evidence

Three initial false PASS cases were reproduced before implementation. A further timezone regression was reproduced before its fix. Focused contract regressions cover sparse calendars, hash/source tampering, equal-count wrong-member checkpoints, manual/provisional evidence, unavailable anchors, source-record timing substitution, exact and date-only publication semantics, daily identity gaps, conflict scope, preserved future exits, start-day state, continuity, symbol renames and separate DVR membership.

An independent engineering reviewer identified six unsafe/incomplete behaviors during implementation. They were addressed and the reviewed reproducers were rechecked. The final narrow follow-up found no remaining actionable findings in its scope, including symbol rename handling. This is code review using isolated fixtures, not independent PIT/data QA or an Arena tournament verdict. Existing causality-helper compatibility and timezone regressions are also tested.

Final focused suite: **43 passed**. The fresh full regression/coverage run below uses the final source state. Fingerprints cover 228 tracked/new implementation Python files; source drift is `[]`.

| Check | Result | Observed |
|---|---|---|
| full_regression | PASS | {'name': 'pytest', 'errors': '0', 'failures': '0', 'skipped': '0', 'tests': '1084', 'time': '643.161', 'timestamp': '2026-11-03T00:16:31.442503+05:30', 'hostname': 'Legion'} |
| source_fingerprint | PASS | 228 |
| adapter_focused_coverage | MEASURED | 96.08 |
| overall_coverage | PASS | TOTAL                                               17498   2080   5504   1107    84% |
| critical_coverage | PASS | TOTAL                               5230    168   1660    169    95% |
| robustness_coverage | PASS | TOTAL                               1148     40    344     32    95% |
| ruff_changed | PASS | 0 |
| mypy_ci | PASS | 0 |
| pyright | PASS_WITH_WARNINGS | 0 |
| compile | PASS | 0 |
| mypy_all | PRE_EXISTING_FAILURE | 1 |
| ruff_all | PRE_EXISTING_FAILURE | 1 |
| diff_check | PRE_EXISTING_FAILURE | 2 |

Configured CI Mypy covers 129 files and passes. Broader `mypy .` retains the prior **43 errors in 11 other files**, including scratch scripts, the separate zero-cost package, utils/retry.py and validate_cache.py. No new implementation MyPy errors remain. Pyright has 0 errors and 874 warnings. Repository-wide Ruff retains 15 prior scratch/export findings and access-denied directories. `git diff --check` retains the prior extra EOF blank line in tests/test_nifty200_pit_parser.py; the implementation files pass targeted whitespace/lint checks. These failures are recorded separately and are not converted to PASS.

Runtime: Python 3.13.11 in the shared interpreter. A fresh `pip check` fails with eight dependency constraints involving protobuf 7.35.1, websockets 17.0.1 and pandas 3.0.5 versus installed Google/grpc/Streamlit packages. This implementation introduced/installed no dependencies. This environment issue is newly measured here, not retrospectively claimed as a clean baseline. Details are in pip_check.log. A clean environment built from the repository lock files remains a release requirement. Cross-platform CI, frontend and network security/dependency vulnerability audits are not claimed to have run.

Early full-suite attempts stalled while Windows created FastAPI's loopback socketpair in the restricted environment; they were interrupted and are not counted as successful runs. The same dashboard tests passed 3/3 with local socket access. The final full run used that execution permission, unchanged tests and fresh isolated temporary databases. No source test or production socket behavior was patched to bypass the environment symptom.

## Actual invocation on existing real artifacts

The actual new CLI was run for the requested bounds against the available real registered catalogue plus existing rebuild events, intervals and conflicts. Its descriptor deliberately omits unavailable evidence roles instead of asserting certification.

Input descriptor: `C:\Python projects\algo trading\.arena\pit-evidence-closure-20261102\bounded-implementation-checks\existing_inputs_incomplete_package.json`.
Actual report: `C:\Python projects\algo trading\.arena\pit-evidence-closure-20261102\bounded-implementation-checks\actual_bounded_cli.json`.
CLI exit: **2**. Result: **BLOCKED**, `bounded_inputs_evaluable=false`, `actual_validator_executed=false`.
Reason: `bounded_input:missing_artifacts:anchor,calendar,checkpoints,continuity,identities`.

The production validator is executed by passing complete artificial fixtures in regression tests. It has not passed against complete real bounded evidence. The early input block above must not be described as a completed economic replay or a real bounded validator PASS.

| Required real input role | Current result | Exact remaining requirement |
|---|---|---|
| anchor | NOT_EVALUABLE | 200 certified ledger entries exist at start; executable seed and proven causal availability remain required. |
| calendar | NOT_EVALUABLE | Seven prior NSE CM PDFs/certificate exist; register sources and supply complete admitted session/200-201 date census. |
| checkpoints | NOT_EVALUABLE | 75 dates / 15,050 ledger entries exist; assemble reviewed exact member sets and source proofs. |
| continuity | NOT_EVALUABLE | Consume admitted dated links and symbol transitions; reconcile existing continuity hash/namespace mismatches. |
| identities | NOT_EVALUABLE | Provide complete admitted period-valid source proofs, retaining competitors; 27 event identity cases remain unresolved. |

The earlier detailed recheck remains the evidence disposition record: the isolated rebuild contains 271 bounded canonical events versus the prior 310-row comparison component, and 81 bounded conflicts (45 identity records, 35 absent-member removals and 1 duplicate ABBOTINDIA ADD). The 39 missing key occurrences comprise 27 identity cases and 12 recovered OCR observations awaiting review. These populations overlap and must not be summed. This implementation did not admit those rows, manufacture identity boundaries or reopen the historical membership/calendar decisions.

## Determinism, remaining work and next action

Repeated fixture validation preserves reasons and metrics for identical inputs; report generated_at varies. Implementation hashes are recorded below; real input artifact hashes are preserved in the descriptor listed above. Full registered-source-to-integrated-package deterministic reproduction remains NOT_EVALUABLE because admitted inputs and assembly are incomplete. Existing historical artifacts were not replaced with fixture outputs.

Next action: assemble the new input roles only from already admitted, exact source-linked evidence; preserve unknown causal availability and unresolved competitors as blockers. Resolve the 27 identity cases, review the 12 OCR observations, reconcile the continuity/manifest differences and every in-scope replay conflict, then produce the coherent bounded events/intervals/checkpoints/calendar/lineage package twice. Execute this actual validator on that package, compare regenerated artifacts and run required final-source gates. Independent bounded PIT/data QA and import approval follow only after successful bounded validation and the documented campaign baseline requirements. No independent QA gate is asserted here.

| Implementation file | SHA-256 |
|---|---|
| `tools/nifty200_pit/bounded_validation.py` | `8dccc353a54de90ee8ea2c55dcd316cbaf8b634fb1b41bd96e6877f9b9094985` |
| `tools/nifty200_pit/validation.py` | `b890a39f4d5cc6d5042230634d25ae7653550fa098b068b59160017ebf3d736a` |
| `tools/nifty200_pit/cli.py` | `efcdd56b73bd2385c8539eb3ab5635b3dda04d519bbb0ce4266779d809ce8ab3` |
| `tests/test_nifty200_pit_bounded_validation.py` | `05cf0b6e9bcca77d51d7552947db1497f442d1e6f0bdb020246f4f7c90eff6ec` |
| `docs/nifty200_bounded_validation.md` | `c30ab08e3f987f44f14fca85c17f4e5563051364f1bb4b5e442fad34958ba450` |

Complete logs, XML regression results, coverage data/threshold reports, before/after source fingerprints and machine-readable gate results are under `C:\Python projects\algo trading\.arena\pit-evidence-closure-20261102\bounded-implementation-checks`. The companion CSV records failed and non-evaluable gates explicitly.
The CSV exists locally under the repository's existing `reports/*.csv` ignore rule. Ignore rules and Git staging were not changed.

Fresh source-byte verification (`source_recheck.json`): 585 residual and 603 authoritative registered source records have zero hash errors; all seven preserved NSE calendar PDF hashes match their prior certificate. This establishes byte integrity, not new source admission or package completeness.

No production market_data.duckdb/WAL, actual backtest, optimization, Stage A, paper/live trading, broker integration, import, commit, push or merge was performed. Unit-test fixtures exercising those modules are not campaign runs.

INDEPENDENT PIT/DATA QA: NOT ASSERTED  
IMPORT APPROVAL: NOT GRANTED  
CAMPAIGN STAGE A: BLOCKED
