# Authoritative bounded PIT validator: first broken dependency

Result: `VALIDATOR_INTEGRATION_ROOT_CAUSE_IDENTIFIED`.

`PRIMARY_ROOT_CAUSE = PIPELINE_WIRING_GAP`

The certified 2016-01-29 checkpoint never becomes the interval builder's initial membership state. The first concrete assembly break is `tools/nifty200_pit/build_public_dataset.py:build_dataset:2990`: the builder passes canonical changes only, not the checkpoint or its certified identity ledger. Its callee, `tools/nifty200_pit/intervals.py:build_intervals:45`, initializes `active = {}` and has no seed argument. Date bounds on validation cannot repair intervals already built from an empty state.

Calendar input consumption and continuity freshness have separate branches in the actual graph. They are not caused by that empty anchor. This report selects the first anchor-path wiring break as primary, as requested; it does not invent a unique chronological ordering among independent DAG branches or claim that fixing only the anchor yields certification.

Scope: 2016-01-29 through 2022-03-31 inclusive. Analysis only: no code fix, historical reconstruction, new evidence acquisition, validator rerun, import, or governance change.

## 0. Repository state and evidence read

All project-relative paths in this report resolve beneath `C:\Python projects\algo trading-authoritative-evidence`. The CSV records absolute paths.

- Worktree: `C:\Python projects\algo trading-authoritative-evidence`.
- Branch: `codex/nifty200-pit-authoritative-evidence`.
- Starting HEAD: `4ad334ef15baa3d5dc3aa8bae9c90bb2c30027c3`.
- Ending HEAD: `4ad334ef15baa3d5dc3aa8bae9c90bb2c30027c3`.
- Local `origin/main`: `635acfcf62596c0c145f4032dde1e7020407e98e`. No fetch/remote contact was performed; this is the locally available ref, not a claim about current GitHub state.
- Staged changes: none.
- Unstaged: the two pre-existing modified reports `reports/nifty200_pit_2012_anchor_forensics_20260911.md` and `reports/nifty200_pit_initial_anchor_20120102.md`.
- Complete elevated read-only status: 281 entries: two unstaged changes and 279 untracked files, including preserved test-fixture files inside eight `.pytest-tmp*` trees. Non-elevated status omits those restricted directories; the complete inventory is retained in CSV category `starting_git_status`.
- Existing untracked report/support files were preserved. The requested new CSV is covered by existing ignore rules; it exists regardless of Git status visibility. Nothing was staged or committed.

The prior validation MD, all 2,861 CSV records, October 1 recheck, final September 26 membership closure, September 29 calendar certificate/accounting/event ledger, and checkpoint identity ledger were read. The broader September 23 identity report was also inspected; its earlier/global blocked status is not substituted for the later bounded closure.

| Existing report read | SHA-256 |
|---|---|
| reports\nifty200_bounded_pit_validation_20260930.md | 58fc706eda723ac3036516b4020cea77a955e71c86bc018c17e75726835c9223 |
| reports\nifty200_bounded_pit_validation_20260930.csv | 53443f81892ebe979f900361a3a30295b804e3743813d8939909183269275066 |
| reports\nifty200_bounded_pit_validation_recheck_20261001.md | f86fe81ae60b2ba4342d27935149ca8e1a207d3e8534aaf4387f27147aa08a5c |
| reports\nifty200_pit_yesbank_msei_2017_continuity_closure_20260926.md | 20caf60e49694e04f9b56adf173966d724abe063d95546aaf3971fc814e4857b |
| reports\nifty200_pit_suffix_calendar_certification_20260929.md | 0500e0b76b9cacff4efb4c8669b73454e07b6e49cf167c0251c9b0389eba73fb |

The historical membership conclusion remains 75 checkpoints, 74 intervals, 15,050 certified identities, 74/74 certification-grade exact, zero economic divergences and zero genuine membership conflicts. The historical calendar conclusion remains `SUFFIX_CALENDAR_CERTIFIED`, with 310/310 chronology, known_at and effective-session validations. Neither is reopened or treated as fresh production-validator success.

## 1. Exact validator entry, inputs and actual call paths

Actual validator: `tools/nifty200_pit/validation.py:validate_campaign:49`.

Documented executable CLI, shown only and not run through its writing/validation step:

```text
python -m tools.nifty200_pit.cli --root . validate --campaign-from 2016-01-29 --campaign-to 2022-03-31 --require-member-count 200
```

Configuration is an argparse namespace, not a bounded certification configuration file: `cli.py:build_parser:51`, date arguments at 69–70, count at 71. The function independently accepts both dates at `validation.py:53–54`; bounded date support therefore exists. `config/nifty200_pit_corpus_requirements.json` is a corpus guard used by the global builder, not a bounded validator-input manifest. `artifacts/nifty200_pit_v1/evidence_manifest.json` describes a global 2012-01-02→2026-08-20 package; neither CLI validation nor `validate_campaign` reads it.

| Boundary | Exact file:function:line | What crosses it |
|---|---|---|
| CLI entry | `tools/nifty200_pit/cli.py:main:77`; module execution at 174 | Parsed bounds; root resolved at 79 |
| Path selection | `tools/nifty200_pit/cli.py:_paths:23`; called at 80 | Raw, derived JSON, artifact directories; normally creates directories |
| Event loader | `tools/nifty200_pit/cli.py:main:124` → `_load:36` → `_event:143` | All 683 global JSON events; no effective-date selection |
| Interval loader | `tools/nifty200_pit/cli.py:main:125` → `_load:36` → `_interval:156` | All 332 global JSON intervals |
| Conflict/source loaders | `tools/nifty200_pit/cli.py:main:126` → `_load:36`, `_conflict:166`, `SourceRecord` | All 132 global conflicts and 603 source catalogue records |
| Source-byte verifier | `tools/nifty200_pit/validation.py:verify_source_hashes:23` | Checks local source files against source_sha256; no artifact-manifest check |
| Validator input boundary | `tools/nifty200_pit/cli.py:main:126` → `validation.py:validate_campaign:49` | Dates/count/conflicts/source errors only; no anchor, calendar, expected-count map, checkpoint or manifest input |
| Calendar gates | `tools/nifty200_pit/validation.py:validate_campaign:73`, 75, 86 | Missing/empty dates; provenance and calendar_certified |
| Count/state checks | `tools/nifty200_pit/validation.py:validate_campaign:94` → `intervals.py:active_intervals:98` | Derives active IDs from supplied intervals, not checkpoint replay |
| Anchor/count gate | `tools/nifty200_pit/validation.py:validate_campaign:100`, 106, 130 | Count check conditional on anchor boolean; no seed loader |
| Event/interval/conflict checks | `tools/nifty200_pit/validation.py:validate_campaign:109`, 118, 121 | Basic completeness, synthetic exclusion, certified intervals, severity blockers |
| Decision | `tools/nifty200_pit/validation.py:validate_campaign:139` | Returns only PASS or BLOCKED; no complete economic-replay status function |

Line numbers are one-based at the unchanged starting/ending HEAD. The exact source-file hashes are included in the CSV.

### Read-only loader probe performed in this task

The real `cli.main` validation branch was executed only up to its validator-call boundary, with `_paths` intercepted to avoid directory writes, `verify_source_hashes` stubbed to avoid following catalogue paths, and `validate_campaign` replaced by an argument-capture sentinel that stopped execution before the actual validator or report write. Real `_load` and typed object constructors read the four actual JSON inputs. This is a loader diagnostic, not another validator execution or source-verification PASS.

The four opened artifact paths were exactly:

1. `data/derived/nifty200_pit/events_canonical.json`.
2. `data/derived/nifty200_pit/constituent_intervals.json`.
3. `data/derived/nifty200_pit/conflicts.json`.
4. `data/raw/nifty200_pit_public_sources/source_catalogue.json`.

Captured defaults: `trading_days=None`, `calendar_provenance=None`, `calendar_certified=False`, `expected_member_counts=None`, **`initial_anchor_established=True`**, `anchor_differences=()`. The CLI's true anchor default is not evidence that a checkpoint was integrated. Calendar gates still block this invocation. No checkpoint ledger, calendar report/PDF, continuity JSON, evidence manifest, or parquet package was opened by this branch.

### The earlier actual bounded validator invocation was different

The existing diagnostic `reports/bounded_pit_validation_20260930_support/audit.py:table:37` uses `manifest.py:read_table:54`, with DuckDB `:memory:` at 58, to load `events_canonical.parquet`, `constituent_intervals.parquet` and `conflict_report.parquet`. Selection at audit.py:86–89 gives 310 bounded events, 231 overlapping intervals, and 36 bounded/undated conflicts. `_event`, `_interval` and `_conflict` create typed inputs.

`audit.py:<module>:195–201` invokes the unchanged `validate_campaign` twice at 198/199, explicitly passing `initial_anchor_established=False` at 196. First call supplies no calendar; second supplies 1,529 diagnostic annual-table dates, existing 200/201 expected counts, diagnostic provenance and `calendar_certified=False`. The actual results already persisted are BLOCKED/40 reasons and BLOCKED/38 reasons respectively. They were read, not rerun here.

The diagnostic loader also reads the checkpoint ledger, both calendar CSVs, seven preserved PDFs, package manifest/checksums and registered source metadata/bytes for its separate input audits. Those extra reads do **not** make them parameters of `validate_campaign`. The function itself takes objects/flags and opens no files. The global builder has a third path: `build_public_dataset.py:build_dataset:2841` → `load_sources:185` → parsers/resolver/continuity → `build_intervals:2990` → global anchor diagnostic at 3025 → validator at 3035 → manifest writer at 3370/3389. It was not executed.

## 2. Anchor-only trace: the first assembly break

`ANCHOR_FIRST_BREAK = tools/nifty200_pit/build_public_dataset.py:build_dataset:2990 + the certified 2016-01-29 checkpoint/identity state is not supplied to interval construction; only canonical changes are passed.`

Classification: `PIPELINE_WIRING_GAP`.

This is not an observed rejection by a schema validator, missing roster bytes, or a new membership-certification defect. The identity ledger and raw roster are present. The seed's causal availability remains a separate unmet executable contract, not a reason to invent a known_at timestamp.

| Boundary | Input → output actually present | Path/hash/schema/scope | Disposition |
|---|---|---|---|
| Authoritative checkpoint source | January 2016 official ZIP member `nifty200_Jan2016.pdf` → 200 roster rows dated 2016-01-29 | Exact raw ZIP and bhavcopy paths/hashes below; roster source is A1, monthly document date; dated identity source covers 2016-01-29 | PASS: stored evidence present and dependency bytes hash-valid |
| Period-valid identity certification | 200 roster rows + exact dated identities → 200 unique certified durable IDs | `reports/nifty200_pit_checkpoint_identity_ledger_20260923.csv`; full ledger hash below, 21,650 global rows, 15,050 requested-bound rows; key fields checkpoint_date/durable_instrument_id/identity_status/source_hash/identity_source_hash/validity | PASS for bounded-start membership identities; no known_at field |
| Roster materialization | Source roster → `monthly_snapshots.parquet`, 200 start rows | Full table 21,650 rows; schema includes date/symbol/source/member but no durable ID or known_at | PASS for roster custody, not a typed causal seed |
| Interval assembly | Canonical change events → `build_intervals(events, horizon_start=2012-01-02, horizon_end=2026-08-20)` | `build_public_dataset.py:build_dataset:2990`; callee signature `intervals.py:build_intervals:35–41` has no checkpoint/seed parameter; `active={}` at 45 | **BROKEN: first concrete loss of checkpoint state on the actual assembly branch** |
| Manifest custody (separate output branch) | Raw roster table → manifest artifact_hashes entry; certified ledger → no entry | `manifest.py:build_manifest:137–139` hashes only files in artifact_dir; global manifest records monthly_snapshots.parquet hash but no typed 2016 anchor or external certified ledger | PASS for raw-roster hash; bounded certified seed NOT_CONSUMED; this manifest is not an upstream runtime gate |
| Validator loader | Stored intervals JSON/parquet → active IDs, not roster/ledger seed | CLI `main:125`; earlier audit.py:87–88 selects overlapping parquet intervals; schemas in inventory | NOT_CONSUMED: certified seed; 76 active IDs at first checkpoint vs 200 certified |
| Validator gate | Supplied anchor boolean → conditional counts | `validation.py:106/130`; earlier audit.py:196 passes False; CLI omits it and gets True | Earlier bounded count evaluability False; default True is not proof |
| Replay state | Unseeded event intervals → incomplete initial state | `intervals.py:active_intervals:98`; exclusive effective_until semantics retained | 76 start members, not 200; no checkpoint-state equality gate exists inside validate_campaign |

The empty-state builder does support explicit, source-backed `Action.INITIAL_MEMBER` at `intervals.py:65`, but neither the 310 bounded event population nor the 683 stored global population contains such an event. This is not permission to fabricate INITIAL_MEMBER observations, backdate knowledge, or turn checkpoint identity into an unsupported historical announcement.

| Anchor dependency | Exact absolute source path | SHA-256 | Schema / date |
|---|---|---|---|
| https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJan2016.zip | C:\Python projects\algo trading-authoritative-evidence\data\raw\nifty200_pit_public_sources\monthly_weightage\indices_dataJan2016.zip | e433e6f2f94f9a94d150f2fbdc178d6a63ee3d3771d2d1c7e3794db9b6d00535 | ZIP containing official monthly PDF; checkpoint 2016-01-29 |
| https://archives.nseindia.com/content/historical/EQUITIES/2016/JAN/cm29JAN2016bhav.csv.zip | C:\Python projects\algo trading-authoritative-evidence\data\raw\nifty200_pit_public_sources\raw\15\150dda3cee1aa92aaa41244ce74d1c0c6282e9b412011d0db89500181095fdd2.zip | 150dda3cee1aa92aaa41244ce74d1c0c6282e9b412011d0db89500181095fdd2 | ZIP/CSV dated EQ symbol-ISIN rows; 2016-01-29 identity observation |

The roster and identity ledger lack an explicit causal seed-availability field. Establishing that field from already preserved evidence is a follow-up validation requirement; this RCA proves the current path does not load even the existing membership state. It does not certify that all seed availability evidence is already sufficient.

## 3. Calendar-only trace

`CALENDAR_FIRST_BREAK = tools/nifty200_pit/build_public_dataset.py:load_sources:186 + the authoritative 2016–2022 calendar report corpus is not an input to the executable source registry; none of its seven hashes reaches the loaded sources.`

Classification: `PIPELINE_WIRING_GAP`. CLI parallel boundary: `_load(raw/source_catalogue.json)` at `cli.py:main:126` likewise sees zero of the seven hashes.

| Boundary | Input → output actually present | Path/hash/schema/scope | Value consumed |
|---|---|---|---|
| NSE source evidence | Seven annual circular PDFs → certification's holiday/weekend/Muhurat transformation | `reports/nifty200_pit_suffix_calendar_sources_20260929/`; seven hashes below; annual 2016–2022 coverage | Existing report evidence: PASS for bytes; not an executable calendar object |
| Certification outputs | Annual tables → 8-row source/accounting CSV and 310-row event-date CSV | Accounting fields: year/source/hash/circular/counts; event fields include publication/known_at/effective/validation outcomes; hashes/schemas below | Historical 310/310 PASS; no complete serialized session set or maintained loader contract |
| Report corpus → executable catalogue | Seven PDF hashes → zero registered/loaded calendar hashes | `build_public_dataset.py:load_sources:186`, `load_catalogue_sources:164/167`; registry hash below | **BROKEN: earliest calendar intake edge** |
| Calendar manifest | Certificate/accounting outputs → no bounded executable calendar manifest entry | Global evidence_manifest lacks the seven source hashes and certified session artifact | NOT_CONSUMED; no calendar-manifest loader exists in CLI validate |
| Global builder calendar construction | Registry → eight explicitly hardcoded override rules → package calendar | `_verified_calendar_overrides:826/830–844` rules cover 2023–2025, not 2016–2022; `build_dataset:2857`; `calendars.py:build_nse_calendar:354` → `PandasNSECalendar.__init__:217`, provider at 235 | Maintained pandas-market-calendars NSE provider, not September 29 authoritative date tables |
| Validator calendar input | CLI omits dates/provenance/certification | `cli.py:main:126`, default parameters `validation.py:55/62/63` | None / None / False |
| Existing bounded diagnostic | Annual-table reconstruction in audit.py:98–130 → diagnostic date list → validate_campaign | `audit.py:199–201`; bounds respected; provenance explicitly diagnostic | 1,529 dates, calendar_certified=False, not a certified production object |
| Date evaluation | `_align_date_only_causality:916/919` uses next session on builder's calendar; validator checks supplied dates and boolean | `validation.py:73/86/112` | Missing/uncertified dates block; known_at is checked for presence, not recomputed against certification inside validate_campaign |

No annual calendar evidence is reacquired, and no completed 310-event certificate is reopened. The raw calendar evidence exists; its executable intake/serialization/consumption is missing. The hardcoded `calendar_audit_status="PARTIAL_NOT_CERTIFIED"` at `build_dataset:3034`, passed as False at 3042, is downstream of that intake gap, not evidence that the completed calendar audit failed.

| Calendar source | SHA-256 | Registered/manifest/CLI consumed |
|---|---|---|
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_31297_2016.pdf | bf33e9aade8773908fc5d6de105cc731e93bf063cd1564a82fe1998c5aaf6432 | No / No / No |
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_33746_2017.pdf | 2fd7ee17432434df26154bbdb9de549d3e4a7acd4cf567843513457e9c98fbce | No / No / No |
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_36475_2018.pdf | d80ac64d32806f9ada629bc96ba91c6d85546dfde405f4468bbfcb194fdb22fb | No / No / No |
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_39612_2019.pdf | 3fe8f7356085b75a14efec16e765216d09b99be6f00ff2305d813a864394ab88 | No / No / No |
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_42877_2020.pdf | 635535e35ddc37e79b188d9f21409210cfdef00f44cde1cb980c4f64ed005eaf | No / No / No |
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_46623_2021.pdf | 3c922e234ad2cbe8320cc34507e281477e0ce273ba9ee39d73da2a49d5629add | No / No / No |
| reports\nifty200_pit_suffix_calendar_sources_20260929\nse_cmtr_50560_2022.pdf | 731a4f0f3b3633e53ff344ffda23dab0277c4a6608f5a6da8874f931c9be4ead | No / No / No |

## 4. Continuity trace and first stale outputs

`CONTINUITY_FIRST_STALE = artifacts/nifty200_pit_v1/identity_continuity_evidence.json + the newly registered YESBANK INE528G01019→INE528G01027 dependency is not propagated into the existing INE528G01027→INE528G01035 link's durable root.`

The direct 019→027 record is present and has root 019; the 027→035 record still has root 027. The root obtained by following the two admitted links is 019. This is a metadata inconsistency, not new inferred corporate-action evidence. The JSON's current SHA-256 is `09f0711a3bc9268e3644382bfdd476376c84018f3ad87d02f3eab51177c2e4ed`; old manifest/checksum expectation is `3e52643736902de73574c8f85720297d3761b0821c6e16cb9c45f15e0e40f384`.

Important correction to the proposed linear chain: the canonical builder **does not read this JSON**. `build_dataset:2963` calls `_apply_documented_isin_continuity:599` using verified source records and code rules; that routine outputs projected observations, master, aliases and continuity audit as siblings. The JSON is an output at 3248. It cannot be described as an actual loaded ancestor of canonical events.

On the actual canonical-consumption branch, the first proven stale materialization is `artifacts/nifty200_pit_v1/event_observations.parquet`: the immediate observation projection output still has GRASIM root 021 and YESBANK root 035 for four ACCEPTED assertions. `_apply_documented_isin_continuity:733–735` would project these under the current admitted parents; GRASIM 013→021 and YESBANK 019→027→035 are already recorded in sources/rules. Historical master/aliases are sibling projections; no unique sequential order between those siblings is asserted.

The current catalogue is SHA-256 `4136dfd717556ea30be6afea09046033fb3e6b3e67064aa3a32881bbc4ef2fc4`, last-written 2026-09-26T11:49:27.926847Z. MSEI source retrieval is documented at 2026-09-26T17:16:12.352161+05:30. Most projected package/JSON artifacts date from September 23; continuity JSON was modified September 26 and therefore does **not** predate final registration, but retains inconsistent transitive-root metadata. Filesystem timestamps are labelled as such, not asserted as signed generation timestamps. The manifest's explicit generated_at is 2026-09-23T08:02:54.319908Z at old head c22a14094defb7e7b446753bce0e73b6b111f4ef and an uncommitted build identity.

Actual call path: `load_sources:185` → `_apply_documented_isin_continuity:599` (source hash admission at 660–675/690–695, parent graph at 677/697, durable projection at 712–744) → official schedule/disposition rules at 2967–2972 → `reconcile_observations:148`/`_canonical:112`, event hash payload at 133–138 → `build_intervals:2990` → artifact writer at 3370/3389 → `manifest.py:build_manifest:123`. The validator instead consumes existing event/interval/conflict JSON or the earlier harness's parquet objects, not any of these generating functions or continuity JSON.

| Generated artifact | Current SHA-256 | Filesystem mtime UTC (generation timestamp unavailable except manifest) | Dependencies | Predates final registration / semantic finding | Actual validator consumption |
|---|---|---|---|---|---|
| artifacts/nifty200_pit_v1/identity_continuity_evidence.json | 09f0711a3bc9268e3644382bfdd476376c84018f3ad87d02f3eab51177c2e4ed | 2026-09-26T12:09:22.812643+00:00 | current catalogue / registered old-new notice and period-valid identity hashes; exact links in CSV / build_public_dataset.py:_apply_documented_isin_continuity:599 | No: September 26 modification, but transitive root inconsistent | No |
| artifacts/nifty200_pit_v1/event_observations.parquet | b87d90bb253133d968f7bc2fea323454ed7b4f37fcce84bc1f9e568f8f41ac3e | 2026-09-23T08:02:53.087055+00:00 | current catalogue / all admitted continuity relationship hashes / continuity projection + date alignment/schedule dispositions | Yes; four accepted roots stale | No |
| artifacts/nifty200_pit_v1/historical_instrument_master.parquet | 674370c37a94febd4fbebf2ffefa02e9f1ca302ea4b54ada3bf84fd8328b0e33 | 2026-09-23T08:02:48.596279+00:00 | current catalogue / period-valid identity sources, official aliases and continuity projection / _historical_master_rows:1964 | Yes; mixed raw/durable IDs observed, complete projection freshness NOT_EVALUABLE | No |
| artifacts/nifty200_pit_v1/instrument_aliases.parquet | bda0055ac5570cb5f0cbc2eb5f6de108516f20b952915a720220d4a226a803af | 2026-09-23T08:02:53.232525+00:00 | current catalogue / identity/alias/continuity sources / _identity_aliases:1623 + continuity projection | Yes; focused GRASIM/YESBANK roots already match; complete freshness NOT_EVALUABLE | No |
| artifacts/nifty200_pit_v1/events_canonical.parquet | c18c45e4fccf0daebb57a688019bdb9c17ac09c8fb4cc2cb084fb35e4f492fd0 | 2026-09-23T08:02:53.147707+00:00 | b87d90bb253133d968f7bc2fea323454ed7b4f37fcce84bc1f9e568f8f41ac3e / current continuity dependency sources / reconciliation.py:_canonical:112 | Yes; four stale hashes | Earlier bounded function via parquet; CLI reads JSON counterpart |
| artifacts/nifty200_pit_v1/constituent_intervals.parquet | c9f558692a3428c4dd19aaab4de907fe35b718a60c9a1da8913153e1ccd2afb5 | 2026-09-23T08:02:53.274999+00:00 | c18c45e4fccf0daebb57a688019bdb9c17ac09c8fb4cc2cb084fb35e4f492fd0 / no bounded seed dependency / intervals.py:build_intervals:35 | Yes; follows old events and has no seed | Earlier bounded function via parquet; CLI reads JSON counterpart |
| artifacts/nifty200_pit_v1/conflict_report.parquet | 1cd51df75ac4f4997daa9fdb1e36187a0d3a40da9a68b2e5a0edbf8fda372815 | 2026-09-23T08:02:53.450672+00:00 | c18c45e4fccf0daebb57a688019bdb9c17ac09c8fb4cc2cb084fb35e4f492fd0 / reconciliation and unseeded interval conflicts / build_dataset:2992 | Yes; legacy unseeded conflicts retained | Earlier bounded function via parquet; CLI reads JSON counterpart |
| artifacts/nifty200_pit_v1/evidence_manifest.json | f1bfcbe167d44701c5b5990cefb85d8c3bbf62339367a88ea4142010ff7ba4e7 | 2026-09-23T08:02:54.323339+00:00 | 09f0711a3bc9268e3644382bfdd476376c84018f3ad87d02f3eab51177c2e4ed / artifact_hashes and source_hashes listed in stored manifest / manifest.py:build_manifest:123 | Yes; continuity digest and latest source list stale | No |

Direct dependency hashes for all eleven links, exact source paths and generation-code hashes are recorded in CSV categories `continuity_dependency` and `artifact_inventory`. The 37 registered anchor/continuity source records needed for this trace were rehashed in this task: zero errors. The seven calendar PDF bytes also match their certified hashes. No source parser or artifact rebuild was executed.

Five latest GRASIM/YESBANK admission/support source hashes are absent from the global manifest source_hashes, along with one other registered hash; all six are enumerated in the CSV. The manifest still matches old observation/event/interval byte hashes: hash equality to an old manifest does not establish freshness against new registered evidence. Manifest/checksum root-metadata mismatch is a downstream integrity symptom, not a Boolean actually evaluated by validate_campaign.

## 5. Canonical certified versus consumed population

The certified population here is the preserved September 29 calendar event ledger, not the later diagnostic rekeyed component parquet. Its 310 hash set exactly matches the 310 stored bounded events consumed by the earlier actual function calls. The CLI loader probe, in contrast, captures unfiltered global events.

| Property | Certified calendar ledger | Earlier actual bounded function input | Current CLI loader input |
|---|---|---|---|
| CERTIFIED_COUNT / VALIDATOR_COUNT | 310 | 310 | 683 |
| Actions | 155 ADD / 155 DROP | 155 ADD / 155 DROP | 333 ADD / 350 DROP |
| Effective event date range | 2016-04-01→2022-03-31 | 2016-04-01→2022-03-31 | 2012-04-27→2026-03-30 |
| Hash-set digest | `5273e6c67093fe3f78b5bf07e30144fb8258acc41f6b791b5e84663cdb1a2399` | Same | `ed9a5f81cb5b0f555432bb060d1d906626ea0de5bbd7569ab5a0470549df7faa` |
| MISSING_HASHES relative to certified | N/A | Empty set | Empty set |
| EXTRA_HASHES relative to certified | N/A | Empty set | 373: 226 pre-bound + 147 post-bound |
| Synthetic | 0 (joined to matching stored event rows; ledger has no synthetic column) | 0 | 0 |

The bounds include a checkpoint on January 29, but the first *change event* is April 1; those dates are not contradictory. Set digests are SHA-256 of sorted unique lowercase hashes joined with newline and a final newline, UTF-8. The complete `CERTIFIED_HASH_SET`, both `VALIDATOR_HASH_SET` populations, every missing/extra member and every member's effective date are explicitly enumerated in the CSV, not replaced by digests.

Cause of CLI extras: `cli.py:main:124` reads all events, and `validate_campaign:65/109` examines all supplied events rather than filtering them by campaign_from/to. Bounds constrain calendar date range, not event/conflict input scope. This is a loader/assembly wiring gap, not a wrong manifest chosen by a manifest loader: no manifest is loaded. It is also not the source of the earlier bounded BLOCKED result, whose hashes already match.

Separately, latest admitted continuity changes four identity-bearing canonical hashes without changing actions/dates/source assertions. The old certified ledger and both old validator inputs reference the old hashes. Existing diagnostic reconciliation outputs already demonstrate these differences; they were read, not regenerated or promoted:

| Symbol/date | Old durable ID → latest admitted root | Old hash → diagnostic new hash |
|---|---|---|
| GRASIM 2017-05-26 | NSE-ISIN:INE047A01021 → NSE-ISIN:INE047A01013 | ceb006fc816c3ddfee0e419fa0067be0d5da7f20a5657937bc69eb49820a51c8 → b2549efd564dbf706f50494caed2bf15b12df92e7b195d39763f5320a1060c87 |
| GRASIM 2018-04-02 | NSE-ISIN:INE047A01021 → NSE-ISIN:INE047A01013 | 82a4011625116dc115aeeadff3076991bf0cf14744444ab46cc1f62220852d67 → 28084fb94f4997ee484c5ddb2277856c3bc44ea0bc3be84449fa51d88893bcf5 |
| YESBANK 2020-03-19 | NSE-ISIN:INE528G01035 → NSE-ISIN:INE528G01019 | 713bfae9fba9ebac12fa8cf13c34fc8b79bc640862683570144e1bda25ed6d54 → 5d70645d5ba8643f9f105ea841e2d12325987ad57c22d133be96b1b103883254 |
| YESBANK 2020-09-25 | NSE-ISIN:INE528G01035 → NSE-ISIN:INE528G01019 | 391328cc82b38f20fe051c73c0ae9a01c45bc0e1c61009bfeb7c8093408c6eb9 → acc2758c04f2942ef31081a0403e719d91811f6cdfbf16261054a5890d86bc55 |

Thus count equality is not freshness; a 310-row population can still carry four outdated durable roots. These diagnostic new hashes are not substituted for certified events or silently used to rewrite the historical calendar ledger. Any future coherent version requires explicit old/new lineage.

## 6. Exact NOT_EVALUABLE origin and backward predicates

There is **no production function returning `NOT_EVALUABLE` for complete economic replay**. `models.py:EvidenceStatus:26–28` defines only PASS/BLOCKED. `validate_campaign:139` returns those statuses. It has no complete 74-interval checkpoint-economic-replay decision, no continuity-map parameter and no `manifest_current` predicate.

| Result/predicate | File:function:line | Actual value and upstream origin |
|---|---|---|
| Complete replay NOT_EVALUABLE label | `reports/bounded_pit_validation_20260930_support/input_checks.py:<module>:63` | Literal string assigned in result dict, **not a conditional production return**: maintained eleven edges do not encode the full accepted namespace-only input layer |
| 74/74 NOT_EVALUABLE row | `reports/bounded_pit_validation_20260930_support/render_csv.py:<module>:29` | Literal report status; prior closure 74 retained, component diagnostic 64 exact / 10 namespace endpoint differences |
| Component replay comparison | `reports/bounded_pit_validation_20260930_support/render_csv.py:<module>:47–48` | `exact = not (missing or unexpected or absent_drops or duplicate_adds)`; 64 True, 10 False under current limited map; this is not a newly asserted economic divergence |
| Daily-count evaluability | `tools/nifty200_pit/validation.py:validate_campaign:130` | Exactly `initial_anchor_established`; False in both prior actual bounded calls due to audit.py:196; NOT a conjunction of calendar/manifest predicates |
| Count error suppression and explicit blocking | `tools/nifty200_pit/validation.py:validate_campaign:100/106/127–130` | False anchor skips count-mismatch reasons and sets zero count failures, but adds initial_anchor_not_established; zero is not PASS |
| Missing dates | `tools/nifty200_pit/validation.py:validate_campaign:73/75` | First call None/empty; second list has 1,529 diagnostic dates. These predicates are separate from anchor evaluability |
| Calendar certification gate | `tools/nifty200_pit/validation.py:validate_campaign:86` | `not calendar_provenance or not calendar_certified`; fails in both prior calls because certification False; CLI also provenance None |
| Global anchor diagnostic (not bounded seed) | `tools/nifty200_pit/build_public_dataset.py:_anchor_replay_forensics:2456` → `build_dataset:3038` | Summary status explicitly NOT_ESTABLISHED for global 2012 reverse diagnostic; status == ESTABLISHED is False, not a conclusion about 2016 checkpoint certification |
| Manifest current | No predicate in validator | Independently observed old continuity digest/source list; not a reason returned by actual validator and not an input to evaluability |
| Complete package NOT_EVALUABLE label | `reports/bounded_pit_validation_20260930_support/reconciliation_checks.py:<module>:54`; render_csv.py:68 | Literal audit label: integrated causal anchor/calendar/identity-disposition assembly absent |

Backward anchor trace: False passed by diagnostic → unseeded stored interval state → empty active state at intervals.py:45 → missing checkpoint input at builder.py:2990. This is earlier than count metrics or unseeded-removal conflicts on that branch.

Backward calendar trace: False/None → no certified session loader/artifact → absent calendar sources at load_sources:186. Backward continuity/freshness trace: stored projected observations/manifest lag admission of already preserved source relationships. These are parallel branch failures, not a fabricated three-flag replay function.

## 7. One actual dependency graph

The graph includes current pipeline edges and labels required-but-missing edges explicitly; the manifest is an output sibling, not an actual input to validation. It is intentionally not the proposed artificial serial chain of checkpoints→calendar→manifest→validator.

```text
Registered raw roster/identity bytes --PASS--> source catalogue
  --PASS--> monthly roster artifact + external certified identity ledger
  --BROKEN [builder:2990; no seed input]--> interval initial state

Registered raw continuity bytes --PASS--> current source catalogue/code rules
  --STALE--> projected observations
  --NOT_CONSUMED--> master / aliases (sibling outputs; no full freshness test here)
  --STALE--> canonical events --PASS (same stored hash set)--> unseeded intervals
  |              |                                           |
  |              +--WRONG_SCOPE via CLI:683 not310-------------+
  +--STALE--> continuity evidence JSON (output sibling; NOT_CONSUMED by builder/validator)

Preserved NSE calendar PDFs --PASS--> calendar certification/accounting/event ledgers
  --BROKEN [not registered at load_sources:186]--> executable source catalogue
  --NOT_CONSUMED--> bounded authoritative session object/manifest (not implemented)
  --NOT_CONSUMED--> validator calendar input (None/False; diagnostic list also False)

Stored event/interval/conflict outputs --PASS--> global derived manifest old hashes
Continuity JSON --STALE--> manifest digest
Derived manifest --NOT_CONSUMED--> CLI / validate_campaign

Existing stored JSON --WRONG_SCOPE--> CLI objects (683 /332 /132)
Existing stored parquet --PASS [bounded diagnostic selection]--> objects (310 /231 /36)
Objects + absent integrated seed/calendar --BROKEN--> actual bounded validator (BLOCKED)
Validator --NOT_CONSUMED / no implementation--> complete checkpoint economic replay gate
Separate audit component replay --BROKEN (incomplete executable namespace layer)
  --> audit-only NOT_EVALUABLE label
```

PASS on a custody/loading edge means only the described propagation, not whole-package validation. Earliest anchor failure: certified checkpoint→seeded interval assembly. Earliest calendar failure: report source corpus→executable registry. Earliest continuity metadata staleness: newly admitted parent→transitive durable root; first canonical-branch stale projection is processed observations. The primary classification is one wiring gap; independent freshness defects remain explicitly separate, not falsely claimed as consequences of anchor loss.

## 8. Primary classification and downstream symptoms

`PRIMARY_ROOT_CAUSE = PIPELINE_WIRING_GAP`

Evidence: present hash-valid 200-ID checkpoint; no seed parameter/call; empty active dictionary; only four global JSON loaders; no certified calendar input; no manifest consumption. Function date bounds exist and source bytes are present, so missing authoritative membership/calendar acquisition and bounded date support are not established root causes.

Downstream anchor-path symptoms: 76 rather than 200 starting members, incomplete checkpoint equality, legacy absent-member removal conflicts, diagnostic False anchor/count evaluability, and incomplete production-equivalent economic replay.

Other observed branch conditions: calendar intake absent; package/continuity root metadata stale; CLI global-scope extras; no production complete-replay gate. Calendar absence and continuity staleness are independent of empty anchor, although all must be resolved before validation can pass. The existing 35 critical bounded removal conflicts and undated HIGH global coverage gap remain retained, not deleted or declared resolved by this RCA.

## 9. One hypothesis and smallest test

Hypothesis: **I believe the checkpoint-to-interval handoff is the primary root cause because the 200 certified start identities exist, but the actual assembly call supplies only events and initializes an empty state; the validation loader then consumes that unseeded result without loading the certified checkpoint.**

Smallest isolated structural test: intercept `_paths`, observe real `_load` calls, replace `validate_campaign` with a capture sentinel, call CLI validate with the two bounds, and assert the captured interval state contains exactly the certified 2016-01-29 ID set with evidence-backed causal metadata. It must stop before report writes and may stub source-byte checks, since provenance is tested separately. Also assert no source population or legacy checks are silently dropped. No historical parser or full validator run is needed to show this missing handoff.

Current observed counterexample: loader opens only four global JSON files; start state contains 76 IDs rather than 200; no checkpoint/seed or certified calendar is loaded. The read-only loader spy described in section 1 proves the absence. It does not prove a future seed's causal metadata or calendar authority. A hypothetical successful injection test cannot use a supposed 'existing bounded-input manifest': no such manifest was found, and no loader supporting it exists.

## 10. Minimal fix plan, not implemented

Target only the first broken seed handoff; do not conflate this with a one-line complete-package fix.

**CHANGE 1 — first missing capability:** `tools/nifty200_pit/intervals.py:build_intervals:35/45`. Accept an explicit immutable evidence-backed initial membership/interval state for a supplied bounded horizon; validate durable IDs, uniqueness, source/causal metadata and horizon compatibility before populating active. Preserve existing ADD/DROP conflict detection and exclusive end semantics; never fabricate membership announcements or backfill known_at. Legacy unseeded behavior must not be relabelled certified.

**Required call-site wiring for that same handoff:** the bounded assembly caller must pass the verified 2016-01-29 ledger/seed into that explicit input instead of the events-only call represented by `build_public_dataset.py:build_dataset:2990`. The current global builder must not silently be reused with 2012 globals; an explicitly bounded caller/adapter is needed. This is necessary wiring, not optional cleanup. A seed API edit alone is not claimed to fix the loader or all validation.

**FAILING TEST FIRST:** `test_bounded_checkpoint_seed_initializes_complete_membership` in `tests/test_nifty200_pit_temporal_contract.py` (proposed, not added). Use a hash-backed isolated seed fixture with explicit causal metadata and a bounded event stream; require complete initial durable-ID equality and preserved 200/201 policy, and check invalid/missing causal seed evidence blocks. Current API fails for an explicit seed argument; current existing-package integration yields 76 IDs instead of 200. A separate loader-level regression named `test_validate_cli_consumes_bounded_certified_seed` must fail against the current four-loader branch before caller wiring is implemented. No tests are marked passed for a fix that was not implemented.

**EXPECTED RESULT:** empty builder state becomes the verified 200-ID bounded initial state; the caller can set `initial_anchor_established=True` only after real seed validation, changing the earlier diagnostic's `count_validation_evaluable=False` to True and making count errors enforceable. Calendar_certified remains False and package blockers remain until their independently verified inputs are wired. Merely flipping any flag, using required_member_count=200 throughout, injecting synthetic events, removing conflicts or trusting an audit label is not the fix.

After authorization, calendar serialization/registry consumption, complete admitted namespace/disposition consumption, coherent lineage/manifests and actual complete economic replay require their own narrow integration tests. No broad rebuild is recommended before those input contracts are defined. This report does not implement or authorize these changes.

## 11. Evidence requirements, verification and safety

New historical membership/calendar acquisition is **not required to demonstrate this root cause or write the first plumbing regression**: the 200-ID checkpoint, seven PDFs and proven GRASIM/YESBANK relationships already exist. No new acquisition is justified by the observed loader omissions. Whether preserved evidence proves initial seed availability at the requested causal instant is **NOT_EVALUABLE in the current schema**; the ledger carries no known_at and this task does not infer it. If a future strict adapter cannot prove availability from admitted evidence, it must remain blocked and report the precise requirement, not claim this RCA proved that no additional evidence could ever be needed.

The maintained eleven-link routine does not encode every historically accepted namespace-only disposition; the prior 74/74 certificate is preserved, but complete executable replay is not established. This is an evidence-consumption/representation requirement, not an instruction to infer more continuity or reopen membership certification.

Verification performed now: current branch/HEAD/local origin ref; complete Git inventory; artifact and source hashes/schemas; manifest references; current code boundaries; read-only real-loader argument probe; set equality/differences; 37 focused registered dependency byte checks and seven calendar PDF hash checks. No parser/reconstruction or actual validator was rerun. The prior 1,020-passed regression/static-analysis evidence was read from the recheck; it is historical verification, not a new RCA test execution. Existing broad Mypy errors and Pyright warnings remain as previously documented; this analysis does not change or suppress them.

Preservation: the 238 existing report/support/package/derived/source-code/registry/config files hashed at entry were compared after writing the two new reports; zero changed existing files. Starting/ending HEAD are equal; staged changes remain empty; only the requested new MD and ignored CSV were added to this worktree. Disposable inspection/rendering scripts/state were staged in the OS temporary directory and are not repository code changes. All existing local changes and restricted fixture trees were retained.

No production `market_data.duckdb` or WAL was opened, hashed, modified, or imported into. Parquet reads use DuckDB `:memory:` only. No Stage A, broad historical research, new source acquisition, strategy optimization, backtest, paper/live trading, broker integration, push or merge was performed. No historical report, certified ledger, source catalogue, manifest, event, interval, conflict or governance file was modified.

The CSV records all twenty requested report items, exact hashes and schemas, full starting Git inventory, three complete event hash sets, all 373 CLI extras, explicit empty missing sets, four namespace old/new hashes, dependency sources and root-cause boundaries.

```text
INDEPENDENT PIT/DATA QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```

Final result: `VALIDATOR_INTEGRATION_ROOT_CAUSE_IDENTIFIED`.

## Exact artifact inventory for the trace

| Artifact path (beneath worktree) | SHA-256 | Rows / object keys | Exact field schema | Declared/selected scope |
|---|---|---|---|---|
| artifacts/nifty200_pit_v1/identity_continuity_evidence.json | 09f0711a3bc9268e3644382bfdd476376c84018f3ad87d02f3eab51177c2e4ed | 11 | symbol, old_isin, new_isin, identity_event_type, source_url, source_sha256, source_page, identity_source_url, identity_source_sha256, before_reference_date, before_source_url, before_source_sha256, after_reference_date, after_source_url, after_source_sha256, date_semantics, independent_qa, durable_instrument_id | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/event_observations.parquet | b87d90bb253133d968f7bc2fea323454ed7b4f37fcce84bc1f9e568f8f41ac3e | 1556 | index_id, source_index_name, instrument_id, isin, symbol, company_name, announcement_date, known_at, known_at_basis, effective_date, action, reason, source_url, archive_url, source_sha256, source_page, source_tier, extraction_method, extractor_version, confidence, review_status, observation_id, supersedes_observation_id, synthetic, raw_text | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/historical_instrument_master.parquet | 674370c37a94febd4fbebf2ffefa02e9f1ca302ea4b54ada3bf84fd8328b0e33 | 230784 | instrument_id, isin, symbol, company_name, listing_date, valid_from, valid_until, snapshot_date, observed_snapshot_date, retrieved_at, validity_basis, has_explicit_historical_interval, identity_event_type, source_url, source_sha256, source_tier, confidence, review_status, predecessor_instrument_id, successor_instrument_id, series, source_member, company_name_source_url, company_name_source_sha256, company_name_resolution_basis, identity_master_source_url, identity_master_source_sha256, historical_identity_status, identity_source_url, identity_source_sha256, identity_observation_date, identity_validity_basis, symbol_change_source_url, symbol_change_source_sha256, identity_candidate_basis, name_evidence_confidence, name_evidence_review_status, name_change_source_url, name_change_source_sha256 | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/instrument_aliases.parquet | bda0055ac5570cb5f0cbc2eb5f6de108516f20b952915a720220d4a226a803af | 4861 | instrument_id, isin, symbol, company_name, listing_date, valid_from, valid_until, source_url, source_sha256, source_tier, snapshot_date, observed_snapshot_date, retrieved_at, has_explicit_historical_interval, validity_basis, exchange, alias_symbol, confidence, resolution_status, alias_id, series, source_member, identity_event_type, company_name_source_url, company_name_source_sha256, company_name_resolution_basis, symbol_change_source_url, symbol_change_source_sha256, identity_candidate_basis, identity_validity_basis, identity_master_source_url, identity_master_source_sha256, identity_reference_before_source_url, identity_reference_before_source_sha256, identity_reference_after_source_url, identity_reference_after_source_sha256 | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/events_canonical.parquet | c18c45e4fccf0daebb57a688019bdb9c17ac09c8fb4cc2cb084fb35e4f492fd0 | 683 | index_id, instrument_id, isin, symbol, company_name, announcement_date, known_at, known_at_basis, effective_date, action, reason, source_url, archive_url, source_sha256, source_page, source_tier, extraction_method, extractor_version, confidence, review_status, event_hash, observation_id, synthetic | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/constituent_intervals.parquet | c9f558692a3428c4dd19aaab4de907fe35b718a60c9a1da8913153e1ccd2afb5 | 332 | interval_id, index_id, instrument_id, symbol_at_entry, isin_at_entry, company_name, effective_from, effective_until, known_from, known_at, reason, entry_event_hash, exit_event_hash, confidence, dataset_version, synthetic | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/conflict_report.parquet | 1cd51df75ac4f4997daa9fdb1e36187a0d3a40da9a68b2e5a0edbf8fda372815 | 132 | conflict_id, date, severity, conflict_type, message, observation_ids, source_urls, required_action | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/evidence_manifest.json | f1bfcbe167d44701c5b5990cefb85d8c3bbf62339367a88ea4142010ff7ba4e7 | 19 | approved_for_import, artifact_hashes, automated_validation, build_configuration, build_id, campaign_readiness, code_identity, date_range, generated_at, identity_map_hash, independent_qa, known_at_policy, manifest_version, parser_git_sha, source_hashes, stage_a_started, unresolved_conflict_count, validation_report, validation_status | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| artifacts/nifty200_pit_v1/monthly_snapshots.parquet | e0120ed943abaac46c4c0b0e47d936defbac19c60513c26acf7f689a19abd84a | 21650 | snapshot_date, index_id, symbol, company_name, source_url, source_sha256, source_member, source_page, evidence_type, source_tier, raw_text | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| reports/nifty200_pit_checkpoint_identity_ledger_20260923.csv | 7b9e0eff6dc1941cfeb7fe9517662709197bcc9d08807708efd79959d4776747 | 21650 | checkpoint_row_id, checkpoint_date, source_row_number, source_symbol, source_name, source_hash, source_url, source_member, resolved_isin, durable_instrument_id, identity_status, identity_valid_from, identity_valid_to, identity_source_type, identity_source_hash, identity_source_url_reference, resolution_method, conflict_id, diagnostic_candidate_count, notes | global ledger 2013-04-18..2022-03-31; requested suffix 2016-01-29..2022-03-31 |
| reports/nifty200_pit_suffix_calendar_certification_20260929.csv | 0613d3601402ff3f74c1a95058e32bb1c4149c4531193f36d3835bc2f42938f0 | 8 | year, calendar_source, source_url, source_sha256, bytes, circular_reference, circular_date, source_tier, source_authority, year_weekday_holidays, year_weekend_holidays, year_special_sessions, year_reconstructed_sessions, suffix_effective_events, suffix_publication_dates, suffix_effective_dates_all_sessions, suffix_known_at_all_exact | annual 2016-2022; requested bound 2016-01-29..2022-03-31 |
| reports/nifty200_pit_suffix_calendar_event_dates_20260929.csv | 9855d9d76e0b10ae1d169d6b75934cf828048f4778f9be1e532b8c375fb997b4 | 310 | event_hash, symbol, instrument_id, action, source_publication_date, publication_timestamp, publication_timestamp_available, known_at, known_at_basis, effective_date, announcement_session_status, known_at_session_status, effective_session_status, next_session_after_publication_date, next_session_after_effective_date, event_chronology_validation, known_at_validation, effective_session_validation, source_tier, source_url, source_sha256 | annual 2016-2022; requested bound 2016-01-29..2022-03-31 |
| data/raw/nifty200_pit_public_sources/source_catalogue.json | 4136dfd717556ea30be6afea09046033fb3e6b3e67064aa3a32881bbc4ef2fc4 | 603 | source_url, local_path, source_sha256, retrieved_at, content_type, status, archive_url, original_url, document_date, source_tier, http_status, etag, last_modified, file_size | requested bound 2016-01-29..2022-03-31; registry/code metadata may cover broader dates |
| data/derived/nifty200_pit/events_canonical.json | 686f2ceb981a2bfdf6fe30dfd7d96927091da259fe6c80f65805fb6dff999121 | 683 | index_id, instrument_id, isin, symbol, company_name, announcement_date, known_at, known_at_basis, effective_date, action, reason, source_url, archive_url, source_sha256, source_page, source_tier, extraction_method, extractor_version, confidence, review_status, event_hash, observation_id, synthetic | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| data/derived/nifty200_pit/constituent_intervals.json | b5da6e553c6ad8aae6d0648993cdb912262a52efcf0296d5a6e0e34d9483175b | 332 | interval_id, index_id, instrument_id, symbol_at_entry, isin_at_entry, company_name, effective_from, effective_until, known_from, known_at, reason, entry_event_hash, exit_event_hash, confidence, dataset_version, synthetic | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| data/derived/nifty200_pit/conflicts.json | 95e88f27cbfec8a39e14d8a13aceae836b3ac96e923a6a3bfad11b0bec4fc820 | 132 | conflict_id, date, severity, conflict_type, message, observation_ids, source_urls, required_action | global package manifest 2012-01-02..2026-08-20; not a bounded seed/calendar package |
| tools/nifty200_pit/build_public_dataset.py | 202be61b080d1e59d3f74bd736f1ac0bf31775450033d6fe72135762c436d310 | N/A | Python source | requested bound 2016-01-29..2022-03-31; registry/code metadata may cover broader dates |
| tools/nifty200_pit/cli.py | 38a8e0c999045c90d22e89a5efc62492487e06d1acd2c44753fb7b74433263b9 | N/A | Python source | requested bound 2016-01-29..2022-03-31; registry/code metadata may cover broader dates |
| tools/nifty200_pit/validation.py | 6605cd493c93587670d0a64d25e1e40a5d4660780c5ab018cfb526468e040688 | N/A | Python source | requested bound 2016-01-29..2022-03-31; registry/code metadata may cover broader dates |
