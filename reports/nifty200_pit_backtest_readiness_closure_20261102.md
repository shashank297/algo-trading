# NIFTY-200 PIT Backtest Readiness Closure

**Decision: `BACKTEST_BLOCKED`**

**Scope assessed:** 2016-01-29 through 2022-03-31 inclusive  
**Branch:** `codex/nifty200-pit-residual-evidence`  
**Starting and ending HEAD:** `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`  
**Independent PIT/Data QA:** `NOT ASSERTED`  
**Import approval:** `NOT GRANTED`  
**Campaign Stage A:** `BLOCKED`

This report records a fresh, isolated verification on the current dirty checkout. It does not certify the bounded PIT series and does not authorize backtests or production import.

## Repository and safety

- The worktree remains on the branch and HEAD above. Existing user modifications and untracked files were preserved. No commit, push, or merge was made.
- No production `market_data.duckdb` or WAL was opened or modified. No Stage A, strategy optimization, backtest, paper/live trading, or broker integration was run.
- Source regeneration used `.arena/pit-evidence-closure-20261102/rebuild-full/`; test temp files were directed only to `.pytest-temp/` where possible.

## Changes made in this work

Focused regressions first reproduced four unsafe behaviors, and a fifth checkpoint test reproduced count-only PASS:

1. A current-only master row plus a name/symbol change could be promoted to a historical certified ISIN segment.
2. A matching explicit ISIN overrode a contradictory event-date symbol/company.
3. A checkpoint with the same count but different members could be marked `PASS`.
4. The validator defaulted `initial_anchor_established=True` without anchor evidence.
5. The production builder discarded press-release observations it could not associate with an allowed NIFTY-200 page.

The current dirty source now keeps identity-change links as candidates until separate historical identity evidence exists, returns manual review for contradictory explicit-ISIN observations, requires matching checkpoint/replay membership sets before monthly `PASS`, defaults anchor establishment to false, and retains unassociated press-release rows as unresolved/manual-review evidence in the production build path.

## Certification inputs and bounded results

The fresh regeneration read `data/raw/nifty200_pit_public_sources/` and verified **585 source records with 0 SHA-256 mismatches**. The generated source inventory and outputs are under `.arena/pit-evidence-closure-20261102/rebuild-full/`.

| Measure | Fresh result | Assessment |
|---|---:|---|
| Bounded checkpoint dates | 75 | Present |
| Bounded checkpoint member rows | 15,050 | Present |
| Checkpoints with 200 members | 25 | Present |
| Checkpoints with 201 members | 50 | Preserved; legitimate periods include `TATAMTRDVR` |
| Bounded coverage rows | 74 | Their count-only `PASS` labels are not replay certification |
| Rebuilt canonical events in scope | 271 (135 ADD, 136 DROP) | 39 exact key omissions vs the 310-row component; detailed disposition below |
| Bounded unresolved conflicts | 81 (45 HIGH, 36 CRITICAL) | Blocking |
| Conflict types | 45 missing durable identity; 35 removal of absent member; 1 duplicate add | Blocking |
| Bounded event rows with missing `known_at` | 0 | Structural check only; does not establish complete source chronology |
| Bounded event rows with `known_at` after effective date | 0 | Structural check only |
| Bounded synthetic canonical events | 0 | No synthetic events found in this generated population |
| Intersecting intervals | 195 | Insufficient for complete replay |
| Full-build sessions parsed | 3,613 | Not accepted as a certified complete NSE calendar input by the validator |
| Replay active-constituent range | 0–106 | Fails complete universe reconstruction |

Earlier larger event totals (including 641 and 673) span wider dates and/or different parser/build revisions, so they are not comparable populations. For the same bounded dates, a direct event-key comparison between the authoritative 310-row component and the residual 271-row canonical output found **39 missing key occurrences and zero extras**. The gap is now mechanically reconciled row by row, but remains substantively unresolved:

- All 39 authoritative source URL/hash pairs are present in the residual registered source catalogue; the fresh 585-source build had zero hash mismatches.
- **27** matching official-release observations were parsed, but remain `UNRESOLVED` with no durable ISIN. They cannot be promoted into the canonical event set without admissible event-date identity evidence.
- **12** official rows from the release effective **2021-09-30** are absent from residual `event_observations.json`, even though their release URL/hash is registered. This is a parser/reconciliation coverage gap.
- The missing key occurrences by effective year are 2016: 4, 2017: 1, 2018: 5, 2019: 4, 2020: 7, 2021: 14, and 2022: 4.

The event-level crosswalk is `.arena/pit-evidence-closure-20261102/authoritative_310_vs_residual_271_event_diff.csv`. It records each symbol/action/effective-date key, source URL/hash/page, source-catalogue registration, and residual observation/identity status. This comparison explains the 310-versus-271 difference; it does **not** certify event identity, chronology, replay, or bounded PIT validation.

The two source catalogues also differ: the authoritative catalogue has 603 records / 583 unique hashes; the residual catalogue has 585 / 565. There are **18 authoritative-only hashes and zero residual-only hashes**. All 18 local source files exist in the authoritative worktree and their bytes match their registered SHA-256. They comprise out-of-scope 2025–2026 NSE records and release-catalogue material, three 2012–2013 NSE bhavcopies, one in-scope 2016 bhavcopy, and Grasim/YESBANK/MSEI continuity evidence. The exact delta and recalculated hashes are in `.arena/pit-evidence-closure-20261102/authoritative_only_source_hashes.csv`. The 18-file delta does not explain the 39 missing event keys; those 39 source pairs are already registered in the residual catalogue.

The February 2022 official NSE Indices release supports the ABBOTINDIA inclusion effective 2022-03-31, and the adjacent official monthly checkpoints support the membership transition. This supports that individual event assertion; it does not clear the duplicate-add/replay conflict or certify the remaining event chain. [Official NSE Indices release](https://www.niftyindices.com/Press_Release/ind_prs24022022_1.pdf)

## Validator result and limitations

**Entry point:** `python -m tools.nifty200_pit.cli --root .arena/pit-evidence-closure-20261102/rebuild-full validate --campaign-from 2016-01-29 --campaign-to 2022-03-31 --require-member-count 200`  
**Exit:** 2  
**Result:** `BLOCKED`

The actual validator reports `trading_days_required`, `trading_days_empty`, `calendar_not_certified`, and `initial_anchor_not_established`, plus 273 unresolved global conflicts. Metrics report 0 trading days checked, `count_validation_evaluable=false`, and 0 source hash errors. Its CLI accepts date bounds but has no inputs for a certified anchor member set, complete trading-session artifact/certificate, or bounded conflict selection. The library validation function accepts a session list and explicit anchor boolean, but the boolean is not an evidence-bound anchor record. The validator cannot establish the requested production-equivalent bounded PASS with the available interface.

The smallest safe tooling change is to accept and verify explicit, hash-bound anchor and NSE session artifacts, scope conflicts and replay inputs to the requested bounds, and compare exact member/identity sets at the bounded checkpoints and effective dates. The existing fail-closed requirements must remain in force; a bare `--anchor-established` flag or count-only comparison would be insufficient.

The regenerated `monthly_gap_analysis.csv` now has **108 `B_SNAPSHOT_REPLAY_MEMBER_MISMATCH`** rows and **68 `A_NO_SNAPSHOT_EVIDENCE`** rows; it has no monthly `PASS` rows. These are fresh builder outputs, separate from the coverage matrix's 74 count-only `PASS` rows.

## Artifact regeneration and comparison

One full rebuild completed from the registered corpus:

- Sources: 585; hash errors: 0.
- Observations: 1,582; canonical events: 604.
- Intervals: 289; conflicts: 273; global coverage gaps: 68.
- Validator status: `BLOCKED`.
- The dry-run importer could not import `utils` in the isolated scratch export and returned 1. The run was isolated and did not touch a database; this does not count as an import or importer pass.

The rebuilt output was compared byte-for-byte with existing certified artifacts:

- `data/derived/nifty200_pit`: 4 matching, 7 mismatched, 3 missing from regeneration.
- `artifacts/nifty200_pit_v1`: 10 matching, 37 mismatched, none missing.
- No second full regeneration was run, so deterministic repeatability is **NOT_EVALUABLE**. The observed mismatches mean the existing artifacts are not reproduced by this current dirty source/corpus run.

## Tests and static analysis

- PIT-specific tests: **141 passed**.
- The three targeted database persistence tests: **21 passed** when run independently using a writable temp runner.
- Full suite: **NOT_COMPLETE**. Full-suite attempts hit Windows `Access is denied` while `tempfile.TemporaryDirectory` created DuckDB files under the sandbox-managed AppData temp path; the later full run was interrupted before a complete result. No production database was involved.
- Ruff on changed PIT source and test files: **passed**.
- MyPy on `tools/nifty200_pit`: **20 source files, no issues**.
- Repository-wide MyPy: **43 existing errors across 11 files**, mainly `scratch/`, the separate `nifty200_zero_cost_pit_package/`, `utils/retry.py`, and `validate_cache.py`; none were reported in the changed PIT package files.
- `compileall` on `tools/nifty200_pit` and `tests`: **passed**.
- Repository-wide Ruff traversed Arena scratch/rebuild copies and encountered access-denied paths and scratch-only lint findings; the targeted changed-file Ruff run is the applicable clean result.

## Remaining blockers

1. Historical anchor admissibility/date is not established from evidence available in the registered corpus.
2. The actual validator has no evidence-bound bounded anchor/calendar input path; complete certified NSE sessions are not supplied to it.
3. The bounded rebuild has 39 exact event-key omissions versus the authoritative 310-row component: 27 parsed official observations lack durable identity, and 12 official 2021-09-30 rows are not parsed into observations. The build also has 81 HIGH/CRITICAL bounded conflicts.
4. Full event chronology, durable identity, corporate-action continuity, and exact daily membership replay remain incomplete; active replay never exceeds 106.
5. Existing certified artifacts do not match the current rebuild, and repeat-build determinism was not evaluated.
6. Full test suite did not complete because of the Windows temp-path restriction; repository-wide MyPy still has 43 unrelated/pre-existing errors.
7. Frozen Campaign 1 baseline remains unestablished; independent QA and import approval remain absent.

## Recommended next action

Keep `BACKTEST_BLOCKED`. First supply admissible dated anchor evidence and a complete, hash-bound NSE session calendar; then reconcile each of the 39 missing expected bounded events and 81 conflict rows against first-party evidence. Add the evidence-bound bounded validator inputs, rerun exact-source regeneration twice, and complete tests in a writable exact-source environment. Only after a passing bounded validator and artifact/test gates should the project request `INDEPENDENT_BOUNDED_PIT_DATA_QA`, establish the frozen baseline, and seek import approval. Do not start Campaign 1 Stage A yet.
