# NIFTY-200 PIT final two-blocker identity adjudication

Date: 2026-09-24
Repository: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Scope: YESBANK `INE528G01027 -> INE528G01035` and GRASIM `INE047A01013 -> INE047A01021` only.

## Decision

The final decision remains `SUFFIX_MEMBERSHIP_REPLAY_BLOCKED`. GRASIM continuity is admitted and registered; YESBANK remains an unresolved blocker because the priority NSDL Circular 0029 bytes could not be preserved and hashed.

| Blocker | Adjudication | Replay consequence |
|---|---|---|
| YESBANK `027 -> 035` | Not admissible without preserved NSDL bytes | Six YESBANK economic divergences and one unresolved evidence-gap conflict remain |
| GRASIM `013 -> 021` | Admissible multi-source period-valid continuity | GRASIM identity conflict resolved; no synthetic NIFTY-200 ADD created |

## Starting state and boundaries

- Starting HEAD: `810f9f53d30f64a4e3011fa4625c26b9def554fb`.
- The worktree had pre-existing dirty anchor reports and unrelated untracked reports; they were preserved and not staged.
- No calendar, 2015 frontier, 2012 anchor, post-2022, monthly governance, general identity acquisition, Stage A, research, backtest, broker, trading, production DuckDB, or WAL work was performed.
- No push, merge, live order, broker call, or production database access was performed.

## Existing governance applied

The decision applies the existing contracts, not a new exception:

- `reports/FAB-27_zero_cost_nse_pit_liquid_equity_certification_20260906.md`: identity is ISIN-primary; symbol-only joins, missing ISIN, conflicting aliases, and unexplained corporate actions fail closed.
- `reports/FAB-27_zero_cost_nse_pit_liquid_equity_certification_20260906.md`: every membership mutation requires first-party URL, retrieval timestamp, SHA-256, parser version, effective date, and reconciliation status.
- `reports/nifty200_pit_event_sourced_certification_contract_proposal_20260923.md`: affected securities require period-valid durable IDs and explicit corporate-action event evidence; current security master and fuzzy/symbol-only joins are insufficient.
- `reports/nifty200_pit_evidence_closure_current.md`: historical identity may be certified by a period-valid first-party observation or a separately evidenced explicit historical interval, selected by temporal validity and exact identity.

## YESBANK adjudication

The requested priority order was followed.

1. NSDL [Circular 0029](https://nsdl.co.in/downloadables/pdf/2020-0029-Policy-Yes%20Bank%20Limited%20Reconstruction%20Scheme%202020.pdf) was tried first. The endpoint returned a repeated self-redirect/redirect loop and no validated PDF bytes.
2. NSDL [Circular 0034](https://nsdl.co.in/downloadables/pdf/2020-0034-Policy-Yes%20Bank%20Limited%20Reconstruction%20Scheme%2C%202020.pdf) was not admitted because validated bytes were likewise unavailable.
3. The official search-result wording is consistent with `INE528G01027 -> INE528G01035`, but search-result text is not a preserved source file and cannot receive the required source SHA-256, retrieval record, or pipeline registration.
4. Existing dated NSE identity observations remain unchanged: `027` is observed before the reconstruction window and `035` after it; those observations do not independently prove the corporate-action bridge.

YESBANK result: `YESBANK_DURABLE_IDENTITY_CONTINUITY_NOT_PROVEN`.

## GRASIM multi-source adjudication

The chain is admissible under the existing governance because every component is first-party, hash-verified, temporally bounded, and exact by company/symbol/ISIN. No source is being treated as a symbol-only join.

1. The official [Grasim FY2015-16 annual report](https://www.grasim.com/upload/pdf/Grasim_Industries_annual_report_2015-16.pdf), page 96, establishes the pre-split equity-share ISIN `INE047A01013`. Preserved SHA-256: `a440b212d603643847859e643b34bfee79e049911307187b717e86b8d493b2eb`.
2. The official [Grasim Q2 FY17 results filing](https://www.grasim.com/Upload/PDF/Q2FY17_results.pdf), page 9, establishes that one Rs10 equity share became five Rs2 equity shares effective 2016-10-08. Preserved SHA-256: `b70a7d5d4d324de72c825c8262786fa8683ec96511e27e6c90a9552cba811db7`.
3. The dated official NSE bhavcopy for 2016-09-30 establishes `GRASIM -> INE047A01013`, SHA-256 `85d073115ed588f5a00e0e511f852c9259eef2d305cdc55196b566637fce6b57`.
4. The dated official NSE bhavcopy for 2016-10-30 establishes `GRASIM -> INE047A01021`, SHA-256 `c2c0d671d8d4bbc8d20dbd5e18ebcb57267c603c3db8c8c69746fc73e86c624c`.
5. The official [NIFTY Indices 12 August 2016 release](https://niftyindices.com/Press_Release/ind_prs12082016.pdf), SHA-256 `5a62ae30702b448323496a7099a40cef446941cabd1b1677af63d6ff2aef6742`, corroborates that the September 2016 NIFTY 200 review had no GRASIM membership action.

There is no single-document old/new ISIN sentence. That is not required by the current contract where the old and new durable IDs are separately period-valid first-party observations and the same issuer's dated first-party filing supplies the explicit causal corporate action. The chain therefore satisfies the current `DOCUMENTED_STOCK_SPLIT_CONTINUITY` rule.

GRASIM result: `GRASIM_DURABLE_IDENTITY_CONTINUITY_PROVEN`.

## Pipeline registration and replay accounting

- The existing `_apply_documented_isin_continuity` pipeline hook was extended with the Grasim chain and invoked against the hash-verified source catalogue.
- The scoped pipeline invocation emitted 9 continuity links, including the new Grasim link with the annual-report identity-support hash and dated before/after hashes.
- The full repository builder was not run because it rewrites the entire derived PIT artifact set; the scoped registration wrote only `artifacts/nifty200_pit_v1/identity_continuity_evidence.json` and did not touch unrelated derived artifacts.
- Grasim's 2017-05-26 `MISSING_PRIOR_ADD` conflict is reclassified as resolved by corporate-action continuity. This resolves an identity namespace conflict only; it does not create a NIFTY-200 index ADD.
- YESBANK's 2020-03-19 `MISSING_PRIOR_ADD` conflict remains `UNRESOLVED_EVIDENCE_GAP`.

| Metric | Before | After adjudication |
|---|---:|---:|
| Checkpoints | 75 | 75 |
| Intervals | 74 | 74 |
| Checkpoint identity rows | 15,050 / 15,050 | 15,050 / 15,050 |
| Certification-grade exact intervals | 68 / 74 | 68 / 74 |
| Economic divergences | 6 / 74 | 6 / 74 |
| Representation-only intervals | 26 | 26 |
| Unresolved evidence-gap conflicts | 2 | 1 |
| Membership-affecting unresolved conflicts | 2 | 1 |
| Synthetic events introduced | 0 | 0 |

The six remaining economic divergences are the YESBANK family from 2020-02-28 through 2020-08-31. The Grasim conflict was outside the original divergence set, so resolving it changes the conflict ledger but not the 68/74 economic interval result.

## Verification

- All three preserved Grasim PDFs were rehashed after preservation; manifest hashes and byte lengths match.
- The scoped pipeline function was run twice with the same source corpus; both runs emitted the same 9 links and the same Grasim link hash tuple.
- The adjudication CSV contains exactly two unique `record_id` values and exactly the two requested transitions.
- Arithmetic reconciles: `68 exact + 6 economic divergent = 74 intervals`; `2 unresolved - 1 resolved Grasim conflict = 1 unresolved`.
- `git diff --check` is required before each scoped commit.

Global governance remains:

```text
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT PIT/DATA QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```

## Narrow next workstream

Only the preserved, byte-level NSDL Circular 0029/0034 evidence path remains for the YESBANK identity edge. Until that source is admitted, suffix replay remains blocked. No calendar, frontier, anchor, membership expansion, or trading work is authorized by this adjudication.
