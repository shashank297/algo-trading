# FAB-27 — Independent QA / Risk review

Verdict: **FAIL — disposition remains BLOCKED**

Review date: 2026-09-06  
Reviewer: Independent QA / Risk Lead

## Inputs reviewed

- `nifty200_zero_cost_pit_package/PAPERCLIP_HANDOFF.md`
- `nifty200_zero_cost_pit_package/candidate_output_schema.json`
- `nifty200_zero_cost_pit_package/liquid_universe_spec.py`
- `nifty200_zero_cost_pit_package/test_liquid_universe_spec.py`
- `nifty200_zero_cost_pit_package/source_manifest_seed.csv`
- `reports/FAB-27_zero_cost_nse_pit_liquid_equity_certification_20260906.md`
- `data/raw/nifty200_pit_public_sources/source_manifest.csv` and its referenced raw files

## Controls executed

Command:

```powershell
.\venv\Scripts\python.exe -m pytest -q nifty200_zero_cost_pit_package/test_liquid_universe_spec.py
```

Expected: deterministic nominal/admissible and fail-closed cases pass.  
Observed: **3 passed in 0.03s**.

Independent adversarial calls to `fail_closed_reasons` produced:

| Input defect | Expected | Observed | Result |
|---|---|---|---|
| missing `as_of` | rejection reason, no exception | `KeyError('as_of')` | FAIL |
| non-numeric turnover | rejection reason, no exception | `ValueError` from `float(...)` | FAIL |
| malformed URL and SHA-256 | rejection reason | returned `[]` | FAIL |
| missing `effective_from` | rejection reason | `missing_effective_date` | PASS |

The current tests do not cover the first three defects and therefore do not establish
malformed-row safety.

## Evidence and PIT assessment

The repository-level raw directory contains 358 files and its manifest contains 357 rows;
all 357 manifest rows have non-empty hashes.  This is useful retained material, but it is
not sufficient certification evidence: the package itself contains only the seed manifest,
and the reviewed report marks all three required horizon bands `UNRESOLVED_GAP`.  No complete,
independently reconciled ISIN identity, historical symbol/listing/status, pre-decision turnover,
and rebalance set covering 2012-01-02 through 2026-08-20 was demonstrated.

Manifest reproducibility also has a path constraint: `local_path` values resolve from the
package directory, not from the manifest's repository-level raw directory.  A clean replay must
document this base explicitly or emit portable paths and verify each path/hash pair.

## Required corrections before re-review

1. Engineering must make every required-field, type, URL, and SHA-256 failure return explicit
   fail-closed rejection reasons without exceptions; add adversarial tests through both
   `fail_closed_reasons` and `validate_rows`.
2. Research + Engineering must acquire and independently reconcile first-party NSE/NSE Indices
   evidence across the complete horizon, including identity/listing/status, turnover windows,
   effective dates, rebalance additions/removals/unchanged members, and source hashes.
3. The replay must verify manifest paths and hashes from a clean checkout, record command/runtime/
   parser versions and output hashes, and rerun nominal plus adversarial tests.
4. Preserve `FAB-17` as BLOCKED and `NIFTY200_HISTORICAL_PIT_DATA` as unresolved. Do not emit
   `CANDIDATE_ACCEPTABLE_FOR_BOARD_REVIEW` until all material gaps are closed and QA/Risk signs off.

Unblock owner/action: Research & Engineering; produce the reconciled evidence bundle and request
a fresh Independent QA/Risk review. No live, broker, credential, strategy, backtest, or paper
workflow is authorized by this review.

## Heartbeat recheck (2026-09-06)

Independent rerun from the canonical workspace reproduced the disposition:

```text
.\venv\Scripts\python.exe -m pytest -q nifty200_zero_cost_pit_package/test_liquid_universe_spec.py
3 passed in 0.03s
```

Adversarial direct calls and a `validate_rows` call again observed `KeyError('as_of')` for a
missing required field, `ValueError` for non-numeric turnover, and `[]` for malformed URL/hash
metadata; only the missing-effective-date case returned an explicit rejection reason. This is
not a certification change. Research & Engineering remain the unblock owners: harden validation,
add the missing adversarial tests, and deliver independently reconciled first-party PIT evidence
for the entire required horizon before requesting re-review.
