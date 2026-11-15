# Bounded PIT evidence input

The bounded path consumes reviewed, source-linked evidence and invokes the existing
`validate_campaign` validator. It performs additional exact-set replay, chronology,
calendar completeness, identity and cross-artifact checks before a PASS is possible.
It does not admit new evidence, resolve missing identities, or grant independent QA,
import approval, or campaign authorization.

```powershell
python -m tools.nifty200_pit.cli validate --campaign-from 2016-01-29 --campaign-to 2022-03-31 --evidence-package path/to/package.json --output path/to/new-validation-report.json
```

The output path must be a new JSON file in an existing directory. Existing reports
and inputs are never overwritten by this path. Exit 0 means validation of the
supplied package passed; exit 2 means BLOCKED. Missing or malformed evidence is
BLOCKED, with `bounded_inputs_evaluable=false`. The legacy CLI path remains
available, but its caller-supplied flags/session omissions do not constitute a
bounded evidence certificate.

## Manifest

The package is JSON, version 1, with `index_id="NIFTY_200"`, `campaign_from`,
`campaign_to`, and `artifacts`. The two dates must exactly match the CLI request.
Each artifact descriptor is `{"path": "relative-or-absolute.json", "sha256": "..."}`.
Relative paths resolve from the manifest directory. Every artifact is read only,
SHA-256 checked, and parsed as JSON. No database or WAL may be a source file.

Required artifact roles:

| Role | JSON contents |
|---|---|
| `source_catalogue` | Registered source records with `local_path`, `source_url`, `source_sha256`, `source_tier`, and `document_date` where causal availability is required. Every registered file is hash checked. |
| `anchor` | Certified starting state described below. |
| `calendar` | Certified complete date census, session openings, and expected 200/201 counts. |
| `identities` | Complete reviewed historical identity evidence for packaged symbols, retaining competing and unresolved rows. |
| `continuity` | Explicit reviewed identity transitions; an empty list is allowed when no transition is needed. |
| `events` | CanonicalEvent dictionaries, including any pre-bound entry events used by supplied intervals. No post-bound events. |
| `intervals` | ConstituentInterval dictionaries with explicit event/anchor lineage. |
| `checkpoints` | Reviewed exact checkpoint member sets. |
| `conflicts` | Conflict dictionaries, including undated/global and pre-bound conflicts. |

Every evidence proof contains `source_url`, `source_sha256`,
`confidence="CERTIFIED"`, and `review_status="ACCEPTED"`. Referenced sources must
be registered A1/A2 sources. These fields consume existing admission decisions;
setting them is not a substitute for review of the underlying source semantics.
Event-result fields and comparison reports are not historical identity evidence.

## Starting state and identities

The anchor contains `date` equal to campaign start, timezone-aware `known_at`,
`members`, `applied_event_hashes`, and an evidence proof. It represents the members
at the opening of the starting session, after any events effective that day.
`applied_event_hashes` must equal the packaged start-date events exactly. `known_at`
must not exceed that session's opening, and registered source publication evidence
must establish availability by then. No availability timestamp is inferred from a
download date, filename, or later checkpoint.

ADD/INITIAL_MEMBER events effective on the first day must be present in the seed;
DROP events must be absent. Their hashes alone do not establish these postconditions.
Source URL, tier, hash and publication metadata must match the same authoritative
registry record. Conflicting publication records block. Date-only sources become
available conservatively at the next admitted session. Same-day availability
requires an independently admitted `publication_timestamp` on that source record;
the timestamp must agree with its document date in IST.

Each member contains `symbol`, `instrument_id`, `isin`, `valid_from`, exclusive
`valid_until` (or null for an admitted open interval),
`has_explicit_historical_interval=true`, and an evidence proof. Identity evidence
uses the same fields. Every event/member must have matching symbol, period-valid
identity and ISIN evidence. An overlapping unproven, unaccepted, or conflicting
identity row blocks the package. Do not exclude competitors from `identities` to
obtain a pass; its reviewed completeness remains an input evidence requirement.
Identity coverage and competitors are checked on every active session, including
sessions between checkpoints. Interval entry symbol/ISIN must match its event or
anchor evidence. Raw entry identities remain intact when later continuity applies.

Continuity rows contain `from_instrument_id`, `to_instrument_id`, `effective_date`,
timezone-aware `known_at`, and an evidence proof. They must come from separately
admitted corporate-action continuity evidence, not adjacent snapshots. Causal
availability must be proven. Normalization is date-sensitive; conflicting edges,
cycles encountered during normalization and collapsing two active members block.
Continuity does not create synthetic ADD/DROP events or independently prove raw
ISIN validity. Distinct DVR membership must remain distinct.
An unchanged-ID symbol rename requires explicit `from_symbol`, `to_symbol` and
unchanged `isin`, plus accepted period-valid identity evidence on the preceding
and effective sessions. This updates the dated identity lookup only; original
interval entry symbols and ISINs are preserved. Conflicting or cyclic symbol
transitions block.

## Calendar and checkpoints

The calendar contains an evidence proof, `coverage_from`, `coverage_to`, and
`records`. There must be exactly one record for **every calendar date**, including
closed days, throughout its declared coverage. Coverage must include campaign
bounds, event effective dates, publication dates, and next-session evidence used
for date-only causality; include pre-bound dates when required by carried events.

Each record contains `date`, boolean `is_session`, and `source_sha256`. Open
sessions also contain timezone-aware `open_at`. Each in-bound open session requires
an explicit `expected_member_count` of 200 or 201 and `count_source_sha256`.

Calendar-source admission does not establish membership counts. The calendar also
requires a nonempty `count_evidence` list of separately admitted semantic proofs:

```json
{
  "evidence_type": "MEMBERSHIP_COUNT",
  "index_id": "NIFTY_200",
  "coverage_from": "YYYY-MM-DD",
  "coverage_to": "YYYY-MM-DD",
  "expected_member_count": 201,
  "source_url": "<actual reviewed source URL>",
  "source_sha256": "<actual registered source SHA-256>",
  "confidence": "CERTIFIED",
  "review_status": "ACCEPTED"
}
```

Both coverage dates are inclusive and must form a valid ordered range. Counts
must be integers, either 200 or 201. Each proof must match an A1/A2 catalogue
record by both URL and hash; the registered source bytes are hash checked.
Every in-bound session must be covered by an admitted proof whose count and hash
match that session's `expected_member_count` and `count_source_sha256`.
All proofs covering that session must agree on its count, even if their sources
differ. A count proof outside its declared dates cannot establish that session.

These fields consume an existing review decision about source meaning; the reader
does not infer count coverage from a holiday circular, inclusion notice, observed
checkpoint count, or the nominal index size. A holiday source alone is insufficient.
Preserve legitimate expected 201-member/DVR observations and their original sources
without promoting them to accepted count evidence before semantic review.
Unsupported expected counts may remain assertions with `count_confidence="UNRESOLVED"`
and `count_review_status="MANUAL_REVIEW"`; an unproven ordinary-200 source can remain
null. Those row annotations do not substitute for an admitted count proof.
Emit `count_evidence: []` while no count proof has been admitted. Missing or empty
count evidence blocks with `member_count_evidence_missing`, with
`bounded_inputs_evaluable=false` and `actual_validator_executed=false`.
The admitted calendar transformation must reconcile official holidays, amendments
and special sessions. The reader does not infer open dates from weekdays or fill
missing dates from a library calendar. A complete date census detects missing
rows; review of source semantics establishes whether each classification is true.

The first campaign date must be a session. Session opening dates are checked in
IST, including special-session times. Every event must be effective on an admitted
session and known by its opening. DATE_ONLY_CONSERVATIVE_NEXT_SESSION events must
match the strict next admitted opening after publication. Exact-publication events
must carry the existing EXACT_SOURCE_TIMESTAMP basis.
For exact publication, the event known_at must match the source's admitted timestamp
and the announcement date in IST; legitimate publication before the same day's
opening is allowed. Date-only publication retains strict next-session handling.

Each checkpoint contains `date`, `members`, and an evidence proof. The starting
checkpoint and last in-bound session of every campaign month are mandatory.
Additional in-bound session checkpoints are allowed. Replay is carried from the
anchor through all sessions. Exact member identity sets must agree with both
intervals and checkpoints; equal counts alone cannot pass.

## Intervals, conflicts and determinism

Existing interval entry/exit event hashes, effective dates, announcement knowledge,
and known_at must agree with their canonical events. Preserve carried pre-bound
knowledge and evidence; provide calendar coverage needed to validate it. For an
explicit bounded seed interval, `entry_event_hash` can instead be
`ANCHOR:<anchor artifact SHA-256>`, with effective_from equal to campaign start,
the anchor member identity and the anchor's actual known_at. This references a
state certificate and does not fabricate a historical INITIAL_MEMBER event.

All HIGH/CRITICAL pre-bound, in-bound and undated conflicts remain blocking.
Post-bound conflicts use event effective dates under the Conflict contract; their
IDs are explicitly recorded as outside the evaluated horizon. There is no waiver
flag for unresolved membership, identities or undated applicability.
Interval exits beyond the requested horizon are retained and their interval IDs
are explicitly reported outside scope; this does not certify the later exit.
Same-day event collisions are checked after dated identity normalization as well
as raw duplicate-hash checks; event-hash sorting is not ordering evidence.

Reports include the input manifest and artifact hashes, actual-validator execution
status, exact checkpoint failures and scoped post-bound conflict IDs. generated_at
varies. Repeated validation of identical inputs must preserve reasons and metrics.
A complete source-to-package deterministic build still requires a producer using
the reviewed corpus; this reader does not certify an unexecuted reconstruction.

## Current evidence boundary

The existing historical certifications and raw source bytes remain intact. The
current residual rebuild lacks a complete admitted bounded input package. The
27 identity cases, 12 OCR reviews, replay conflicts, continuity/manifest mismatch,
and anchor availability requirements remain evidence/assembly blockers. Do not
fill schema fields from asserted event-result ISINs or convert NOT_EVALUABLE into
CERTIFIED to satisfy this interface.

## Assembly of unresolved evidence

Assembly can explicitly consume source-linked anchor derivation inputs using
`--anchor-derivation-inputs path/to/derivation_inputs.json`. It recomputes the
derivation from verified bytes using the assembly registry, rather than trusting
an input catalogue or a saved candidate's admission flags. The selected checkpoint
ledger path/hash, opening timestamp and exact symbol/instrument/ISIN set must
match assembly. The input JSON contains `start_at`, `seed`, `notices`, `renames`,
`checkpoint`, and optional `coverage`, as documented by `anchor_derivation.py`.

The derivation input file is hashed in `assembly_inputs.json`; primary dependencies
are registered in the source catalogue and referenced in the anchor derivation.
This option emits an unresolved anchor and seed intervals with null knowledge
times. It does not admit an anchor, source completeness, historical identity,
membership-count range or continuity assertion. Omission retains the existing
unresolved monthly-roster path. Missing requested inputs fail without fallback.

`assemble-bounded-package` assembles evidence without granting admission. The
reviewed 2026-11-03 package is in
`artifacts/nifty200_pit_bounded_package_reviewed_20261103/package.json`; the earlier
package and historical reports are retained for comparison.

When the starting roster's publication availability is unproven, the producer
emits an `UNRESOLVED` / `MANUAL_REVIEW` anchor with `known_at: null`. Its 200 seed
intervals also remain unresolved with null knowledge times. The unchanged reader
rejects this package at evidence admission; it does not execute the core validator.

Continuity reference observations retain their original dates and date semantics.
They do not become effective transitions or acquire opening-time knowledge
timestamps. Unresolved links cannot normalize identities during interval assembly.
Competing identity observations retain their actual master source URLs, SHA-256
hashes, validity fields, snapshot dates, and durable IDs, with unresolved review
status; a disposition event date is not an identity validity boundary.

`assembly_inputs.json` records the selected registry, circular, ledger, master,
event, conflict, continuity, and disposition dependencies with their hashes.
Missing required inputs and altered circular bytes fail assembly. These generated
and scratch dependencies mean raw-only regeneration remains unestablished.

The gap report computes conflict populations from the exact emitted file. For
this package there are 273 records: one undated, 117 before the period, 81 dated
within it, and 74 after it. The 81 bounded records comprise 45 missing durable
identities, 35 absent-member removals, and one duplicate ADD. The separate older
38-conflict residual build is not this package's population. None of these counts
waives undated or earlier blockers under the reader's validation contract.
