# NIFTY-200 suffix membership state forensic audit

Audit date: 2026-09-24. Scope is limited to the suffix 2016-01-29 through 2022-03-31 and the 40 alias-normalized unresolved intervals plus 35 suffix removal conflicts. No calendar, frontier, 2012 anchor, post-2022 governance, Stage A, strategy, broker, trading, production DuckDB, or WAL work was performed.

## Baseline and method

- Starting HEAD: `cc63772c4ce0b8a4cab33b231294ee1aaff2c622`; branch: `codex/nifty200-pit-authoritative-evidence`.
- Evidence read: checkpoint identity ledger and rosters, canonical events, event observations, constituent intervals, historical instrument master, symbol-transition evidence, source catalogue, and the three prior reconciliation/conflict reports.
- Replay was recomputed as an ID-only state machine seeded from the 2016-01-29 checkpoint. Endpoint labels were derived from the checkpoint ledger or period-valid identity evidence; aliases were applied only at comparison time and never by mutating active state.
- No new first-party source was admitted. Existing event URLs, SHA-256 hashes, announcement/effective dates, and known_at values are retained in the CSV diagnostics.

## Results

- Starting checkpoint: 200 rows, 200 durable IDs, 200 symbols; identity completeness is 200/200 and no duplicate seed row was found.
- Namespace-only cases frozen: 26/26, all `REPRESENTATION_ONLY_CONFIRMED` under the already-admitted temporal alias diagnostic. They are excluded from the remaining economic-divergence count.
- Initial unresolved membership divergences: 40; corrected replay reconciles 34/40 and leaves 6/40 economic divergences.
- Certification-grade accounting after separation: 68/74 exact (8 raw-ID exact + 26 representation-only + 34 corrected membership cases); 6/74 remain economic-membership divergent. Remaining intervals: 2020-02-28->2020-03-31, 2020-03-31->2020-04-30, 2020-04-30->2020-05-29, 2020-05-29->2020-06-30, 2020-06-30->2020-07-31, 2020-07-31->2020-08-31.
- The 6 remaining intervals are the YESBANK state family from 2020-02-28 through 2020-07-31. The 2020-03-19 DROP is applied to an absent durable identity under seeded replay and is not cured by endpoint reconciliation.
- Invalid transitions: ABSENT→DROP=2, PRESENT→ADD=0. Missing-prior-ADD conflicts=2; duplicate-DROP conflicts=0; identity-mismatch classifications E/D=0; checkpoint-state inconsistency I=0.
- Conflict overlap: {'NO_ORIGINAL_DIVERGENCE_INTERVAL': 23, 'IN_ORIGINAL_DIVERGENCE_NO_FINAL_MEMBERSHIP_CONSEQUENCE': 11, 'DIRECTLY_CAUSING_REMAINING_ECONOMIC_DIVERGENCE': 1}. The many-to-many conflict↔interval↔event mapping is explicit in `nifty200_pit_suffix_conflict_resolution_20260924.csv`.
- Conflict recomputation: before=35 `MANUAL_QA_REQUIRED`; after=resolved 24, representation-only 9, nonblocking duplicate 0, genuine membership conflict 0, unresolved evidence gap 2. The 24 seed-carried cases are resolved by the audited suffix seed, 9 are evidence-backed representation/corporate-action transitions, and 2 remain unresolved evidence gaps.
- Production replay defect: NO. The production state machine already replays durable IDs exactly once with deterministic `(effective_date, event_hash)` ordering; the stale-symbol behavior was confined to the temporary audit helper and was not committed.

## First five causal traces

The first five rows are the first five of the original 40, in checkpoint order. Each row's full checkpoint sets, event payloads, raw observation IDs, source hashes, effective dates, known_at values, and conflict IDs are in the forensic CSV.
1. `2018-11-30 → 2018-12-31`: initial economic extra=`SKSMICRO`; corrected status=`ECONOMIC_STATE_RECONCILED`. The relevant same-ID trace is `INE180K01011`: period-valid `SKSMICRO`/`BHARATFIN` identity evidence → canonical `DROP` event at 2018-12-28 under `BHARATFIN` → durable-ID removal → endpoint state reconciles after removing the ID rather than removing a standalone symbol. The interval's CENTURYTEX conflict is separate and has no final membership consequence.
2. `2018-12-31 → 2019-01-31`: initial economic extra=`SKSMICRO`; corrected status=`ECONOMIC_STATE_RECONCILED`. The relevant same-ID trace is `INE180K01011`: period-valid `SKSMICRO`/`BHARATFIN` identity evidence → canonical `DROP` event at 2018-12-28 under `BHARATFIN` → durable-ID removal → endpoint state reconciles after removing the ID rather than removing a standalone symbol. The interval's CENTURYTEX conflict is separate and has no final membership consequence.
3. `2019-01-31 → 2019-02-28`: initial economic extra=`SKSMICRO`; corrected status=`ECONOMIC_STATE_RECONCILED`. The relevant same-ID trace is `INE180K01011`: period-valid `SKSMICRO`/`BHARATFIN` identity evidence → canonical `DROP` event at 2018-12-28 under `BHARATFIN` → durable-ID removal → endpoint state reconciles after removing the ID rather than removing a standalone symbol. The interval's CENTURYTEX conflict is separate and has no final membership consequence.
4. `2019-02-28 → 2019-03-29`: initial economic extra=`SKSMICRO`; corrected status=`ECONOMIC_STATE_RECONCILED`. The relevant same-ID trace is `INE180K01011`: period-valid `SKSMICRO`/`BHARATFIN` identity evidence → canonical `DROP` event at 2018-12-28 under `BHARATFIN` → durable-ID removal → endpoint state reconciles after removing the ID rather than removing a standalone symbol. The interval's CENTURYTEX conflict is separate and has no final membership consequence.
5. `2019-03-29 → 2019-04-30`: initial economic extra=`SKSMICRO`; corrected status=`ECONOMIC_STATE_RECONCILED`. The relevant same-ID trace is `INE180K01011`: period-valid `SKSMICRO`/`BHARATFIN` identity evidence → canonical `DROP` event at 2018-12-28 under `BHARATFIN` → durable-ID removal → endpoint state reconciles after removing the ID rather than removing a standalone symbol. The interval's CENTURYTEX conflict is separate and has no final membership consequence.
- Control cases explicitly inspected: GRASIM and JSWSTEEL have identity namespace transitions with no corresponding canonical membership event in the affected interval; they are identity-transition/representation cases, not invented ADD/DROP events.

## Conflict root causes and evidence requirements

- `F START_STATE_MISSING_MEMBER`: 24. The identity is present in the 2016-01-29 seed; the old unseeded full-chain conflict is not a suffix membership failure once the requested seed is carried.
- `H CORPORATE_ACTION_TRANSITION`: 9. Same durable identity has period-valid symbol/name continuity. No DROP+ADD was manufactured; the identity evidence is preserved by source URL/hash in the conflict CSV.
- `A MISSING_PRIOR_ADD`: 2. These are the only remaining true event-pairing gaps and require an authoritative prior ADD or an explicit corrected event history before any membership claim.
- `B/C/D/E/G/I/J`: 0. No duplicate DROP, effective-date error, wrong-ID proof, supersession proof, checkpoint inconsistency, or replay-ordering defect was established.
- No B1 discovery source was used for certification and no new first-party source was admitted. The unresolved evidence requirement is an authoritative first-party ADD/assertion for the two A cases plus an independent dated resolution of the YESBANK wrong/absent-drop identity state.

## Prior report impact and decision

- The historical 107/107 statement remains structural transition/delta replay only and is superseded for full-state certification claims by the baseline 8/74 raw-ID result and this audit's 68/74 separated accounting.
- The event-sourced contract proposal, bounded feasibility audit, checkpoint identity audit, and identity-gap analysis remain valid as governance evidence, but none can be read as suffix certification; the six YESBANK economic divergences and two missing-prior-ADD gaps remain blocking.
- Decision: `SUFFIX_MEMBERSHIP_REPLAY_BLOCKED`. Do not extend the frontier while suffix replay is unresolved. Next evidence target: resolve the smallest high-impact group first—the YESBANK durable identity/action/date assertion and the two missing prior ADDs—using dated first-party NSE/NSE Indices evidence, preserving bytes, URL, hash, publication/known_at, effective date, and explicit ADD/DROP assertion.

## Governance and verification boundaries

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
- Calendar and 2015-12-31 frontier were untouched. Production DuckDB/WAL were untouched. No Stage A, strategy research/backtests, broker calls, trading, push, or merge occurred.
- Verification: arithmetic checks, deterministic rerun, CSV uniqueness checks, `git diff --check`, and a focused pure replay calculation were run. This is report-only; no production code or evidence corpus was changed.
