# Bounded PIT validation recheck — 2026-10-01

Decision: `BOUNDED_PIT_VALIDATION_BLOCKED`.

This is a fresh repeat of the requested validation-only assessment, for **2016-01-29 through 2022-03-31 inclusive**. No membership reconstruction, recertification, governance relaxation, production import or adapter implementation was performed.

## Repository and original requested reports

Worktree: `C:\Python projects\algo trading-authoritative-evidence`.

Branch: `codex/nifty200-pit-authoritative-evidence`.

Starting and ending HEAD: `4ad334ef15baa3d5dc3aa8bae9c90bb2c30027c3`, exactly the expected HEAD. Existing local changes and all historical reports were preserved. The validation harness checked 117 existing report/package files before and after execution and found zero changes. No production source or existing test files changed.

The requested comprehensive reports already exist and their results were reproduced, not replaced:

- `C:\Python projects\algo trading-authoritative-evidence\reports\nifty200_bounded_pit_validation_20260930.md`, SHA-256 `58fc706eda723ac3036516b4020cea77a955e71c86bc018c17e75726835c9223`.
- `C:\Python projects\algo trading-authoritative-evidence\reports\nifty200_bounded_pit_validation_20260930.csv`, 2,861 result rows, SHA-256 `53443f81892ebe979f900361a3a30295b804e3743813d8939909183269275066`.

Those reports contain the exact certified inputs, all 13 coverage categories, every validator reason, source and artifact hashes, event population reconciliation, complete component comparisons, non-evaluable checks, limitations and recommended next action. This addendum records the new execution and test-invocation issue without modifying them.

## Fresh validation evidence

Evidence checks began at **2026-10-01T01:41:31.622736+05:30**. The existing evidence harness and raw-source parsers were executed with only their final historical-output writes omitted. Every validation check and the actual `validate_campaign` calls ran unchanged. New comparison parquets and JSON were saved only under the worktree's artifacts directory.

Actual validator entry point: `C:\Python projects\algo trading-authoritative-evidence\tools\nifty200_pit\validation.py`, function `validate_campaign`. It supports explicit date bounds; the CLI still omits calendar/anchor input plumbing and the global builder still does not consume the certified bounded package. The bounded input population remains 310 events, 231 overlapping intervals, and 36 bounded/undated conflicts.

- No-calendar call: **BLOCKED, 40 reasons**.
- Annual-calendar diagnostic call: **BLOCKED, 38 reasons**, 1,529 diagnostic session dates, calendar_certified=False and initial_anchor_established=False because certified executable input integration is absent. Existing 200/201 expected-count policy was preserved.
- Both calls reproduced the previous reports' **status, reasons and every metric exactly**. Time-varying generated_at metadata is not a deterministic-data claim.
- Registered source verification: **603 records / 583 distinct hashes**, zero missing or mismatched bytes. All **585 required-corpus records** pass registry/raw-byte checks. All seven preserved calendar PDF hashes still match, but none is consumed by the current executable registry/builder.
- Membership inputs: **75 checkpoints, 74 adjacent intervals, 15,050/15,050 certified and raw-source-verified identities**. Zero identity proof mismatches, duplicate checkpoint IDs or parser errors. All **50 legitimate 201-member checkpoints retain TATAMTRDVR**.
- All **310/310 chronology, next-session known_at, effective-session, date-only-basis and date-level no-leakage checks pass**. The 310 raw source membership assertions are verified against 26 registered PDFs.
- Complete certification-grade economic replay remains **NOT_EVALUABLE** through the maintained executable package. The existing 11-link component diagnostic reproduces 64 exact intervals and 10 endpoint namespace discrepancies; these are not newly asserted economic divergences. Prior 74/74 historical certification is not revoked or substituted for execution.
- Stored package defects persist: missing integrated causal seed/calendar, 35 critical unseeded-removal conflicts plus one undated global coverage blocker, stale continuity checksum/root metadata, and four stale GRASIM/YESBANK canonical namespace hashes.
- Both regenerated bounded canonical component parquets are byte-identical to one another and to the prior diagnostic serializations: SHA-256 `8b1a75802c8106c79481403426f0df3aba41754ea7a0e2f65205f7f09fe3ecd9`. Their four namespace changes versus the stored canonical artifact remain unchanged. They are diagnostic comparison outputs, not certified replacements.

Fresh complete evidence: `C:\Python projects\algo trading-authoritative-evidence\artifacts\bounded_pit_validation_20261001_recheck.json`. It contains both complete actual validator reports, raw-source checks, all checkpoint/replay/event comparisons, source/manifest verification, preservation checks and deterministic reproduction results. New parquets are `C:\Python projects\algo trading-authoritative-evidence\artifacts\bounded_pit_validation_20261001_events_run1.parquet` and `C:\Python projects\algo trading-authoritative-evidence\artifacts\bounded_pit_validation_20261001_events_run2.parquet`.

## Fresh full tests and static analysis

The first plain repository-wide `python -m pytest -q` attempt **failed during collection**, before the suite ran. It discovered identical-named `tests/new_test.py` files generated by earlier manifest-test fixtures inside two disposable artifact directories. They clash under pytest's module import naming. No production test failed and no files were deleted. The collection failure is preserved in `C:\Python projects\algo trading-authoritative-evidence\artifacts\bounded_pit_validation_20261001_recheck.xml` (one collection error).

Tracked-file inspection identifies **81 actual test modules under tests and one additional test module under nifty200_zero_cost_pit_package**. The complete intended suite was then run by explicitly naming these test locations, preserving every tracked test and avoiding discovery of disposable fixture code. No assertion, validation rule, threshold or test configuration was weakened.

Commands, working directory `C:\Python projects\algo trading-authoritative-evidence`:

```text
python -m pytest tests -q --basetemp=artifacts/bounded_pit_validation_20261001_suite_tmp -o cache_dir=artifacts/bounded_pit_validation_20261001_recheck_cache --junitxml=artifacts/bounded_pit_validation_20261001_full_suite.xml
python -m pytest nifty200_zero_cost_pit_package/test_liquid_universe_spec.py -q --basetemp=artifacts/bounded_pit_validation_20261001_package_tmp --junitxml=artifacts/bounded_pit_validation_20261001_package_suite.xml
python -m ruff check . --no-cache
python -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py --cache-dir=artifacts/bounded_pit_validation_20261001_mypy_cache
python -m mypy . --cache-dir=artifacts/bounded_pit_validation_20261001_mypy_cache
python -m pyright
python -m compileall -q main.py research.py ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools tests
git diff --check
```

Results:

- Main tests directory: **1,013 passed**, three existing adjusted-provider fixture CorporateActionBasisWarning warnings, 367.04 seconds.
- Additional tracked package module: **7 passed**. Complete intended suite total: **1,020 passed, zero failures/errors/skips** after correcting the test-discovery invocation. JUnit files preserve both completed runs.
- Ruff: **passed** with complete elevated directory access.
- Configured CI Mypy: **no issues in 129 files**.
- Broad Mypy: **the same 10 pre-existing errors in four unchanged files**, 143 files checked. Locations/types are documented separately in the original requested report; no new application error was introduced or suppressed.
- Pyright: **0 errors, 875 existing/environment warnings**; configured venv remains absent. This is not a warning-free result.
- Complete compileall and whitespace checks: **passed**.
- The temporary recheck wrapper initially lacked the worktree import path and exited before checks with ModuleNotFoundError. Only that temporary wrapper was corrected to use the explicit authoritative-worktree import path; the successful evidence rerun is the persisted JSON described above. No production code was modified.

## Remaining blockers, next action and safety

All data-package blockers in the original requested reports remain. The actual validator did not validate a complete certified bounded package successfully. Anchor availability, complete executable continuity coverage and full source-to-package reconstruction remain NOT_EVALUABLE, not PASS.

Recommended next action remains approval for the smallest bounded evidence-consumption/assembly adapter, using only existing admitted evidence, preserving causal lineage, 201-member exceptions and fail-closed conflict dispositions. Do not silently flip certification flags, drop unresolved/undated checks, infer new identity edges or reconstruct outside the bounded scope. No such adapter or import is authorized by this validation-only request.

For future suite invocations in this worktree, explicitly name both real test locations (or explicitly exclude only generated artifact directories). The earlier disposable fixtures are preserved; source/test configuration was not changed to hide the collection failure.

Production market_data.duckdb/WAL was not used by the validation harness; parquet processing uses DuckDB :memory:. No actual backtest/research, Stage A, optimization, paper/live trading, broker API/integration, production import, commit, push or merge was performed. Regression fixtures are disposable test simulations, not trading workflows.

```text
INDEPENDENT PIT/DATA QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```

Independent bounded PIT data QA is not asserted and is not the next executable gate until actual bounded validation passes.
