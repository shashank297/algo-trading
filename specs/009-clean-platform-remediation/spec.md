# Feature Specification: Clean Platform Audit Remediation & PIT Identity Hardening

**Feature Branch**: `codex/platform-audit-remediation-clean`

**Created**: 2026-09-18

**Status**: Draft

**Input**: User description: "Clean integration and remediation of platform audit and PIT identity hardening"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Risk Headroom & Cryptographic Approval Authenticity (Priority: P1)

As a risk officer and platform governor, I want position sizing to strictly cap same-direction top-ups to remaining headroom and require verifiable cryptographic proof for external human/board promotion authorizations, so that no unauthorized or out-of-bounds capital exposure is permitted into paper or live trading.

**Why this priority**: Preventing excessive risk exposure and enforcing tamper-proof, non-repudiable governance gates are safety-critical preconditions for all downstream trading workflows.

**Independent Test**: Can be tested independently via unit tests passing valid/invalid position top-ups and valid/tampered/untrusted cryptographic approval payloads to `PromotionEngine.assert_paper_authorized()`.

**Acceptance Scenarios**:

1. **Given** an account with capital 100,000 and max position limit 5% (5,000), having an existing BUY position of 4,000, **When** a new BUY order of 2,000 is requested, **Then** the validator caps the approved quantity to at most 1,000.
2. **Given** an account with an existing BUY position, **When** a SELL order is requested (pure risk reduction or reversal), **Then** headroom capping does not truncate the reducing order.
3. **Given** an external approval payload signed by an untrusted key, a revoked key, or containing a tampered field, **When** `PromotionEngine.assert_paper_authorized()` evaluates it, **Then** authorization fails closed with an authenticity error.
4. **Given** a validly signed approval payload where `expected_code_sha`, `expected_evidence_hash`, `expected_scope`, or `expected_subject_type` does not match the execution context, **When** `assert_paper_authorized()` runs, **Then** authorization fails closed with a binding mismatch error.
5. **Given** an approval with status `PAPER_CANDIDATE`, **When** evaluated for `PAPER_ACTIVE`, **Then** authorization is rejected because `approved_stage != expected_stage`.

---

### User Story 2 - PIT Temporal Identity & Date-Valid Alias Joins (Priority: P2)

As a quantitative researcher, I want historical point-in-time index datasets to enforce strict temporal validity on instruments and ticker aliases, so that backtests and research joins never match candles across ticker renames outside their true historical periods or produce zero-length intervals.

**Why this priority**: Survivorship bias and lookahead bias compromise research validity; backdated snapshot assertions or corrupted intervals invalidate the research pipeline.

**Independent Test**: Can be tested independently by replaying candle joins against renamed symbols (e.g. ADANIGAS -> ATGL, L&TFH -> LTF) at dates inside and outside their alias validity windows, and checking that interval generation produces zero instances of `effective_from >= effective_until`.

**Acceptance Scenarios**:

1. **Given** an instrument with a 2026 security-master snapshot date and no explicit historical interval proof, **When** evaluated for a 2012 identity, **Then** the security-master resolver refuses to backdate the certification prior to its evidence-backed snapshot date.
2. **Given** an alias row with `valid_from >= valid_until`, **When** the alias validator processes it, **Then** the row is downgraded or rejected from certified status.
3. **Given** historical candles for a company that underwent a ticker change, **When** joining candles with the research dataset, **Then** candles match via durable `instrument_id` or date-bounded alias interval (`valid_from <= candle_date < valid_until`), and do not match outside that window.
4. **Given** the AMTEKAUTO corporate event history, **When** constituent intervals are generated, **Then** no zero-length interval (`effective_from == effective_until`) is emitted, and canonical event records remain intact.

---

### User Story 3 - Platform Hardening, Storage Resilience & Analytics Correctness (Priority: P3)

As an operations engineer, I want database migrations, backups, maintenance scripts, and analytics metrics to be atomic, fail-safe, and mathematically rigorous, so that operational routines never corrupt the database or mislead performance dashboards.

**Why this priority**: Operational safety prevents catastrophic data corruption and ensures analytics displays accurately reflect true performance.

**Independent Test**: Can be tested independently by simulating migration failures to verify transaction rollback, checking clean_db safety flags, and validating dashboard compound return and profit factor computations on edge cases.

**Acceptance Scenarios**:

1. **Given** a database migration where DDL or migration log insertion raises an error, **When** the migration runner executes, **Then** the transaction is rolled back and the database state remains uncorrupted.
2. **Given** `clean_db.py` executed without explicit confirmation, **When** run in dry-run or default mode, **Then** it refuses to drop research tables without explicit operator override.
3. **Given** strategy equity returns over month boundaries or trades with zero losses, **When** analytics APIs compute monthly compounding and profit factor, **Then** returns compound across boundary bars and zero-loss profit factor returns infinity without dividing by zero.
4. **Given** AI liquidity risk calculation, **When** liquidity metrics are computed, **Then** inputs are grounded in market candle volume and turnover rather than strategy fills.

---

### User Story 4 - Campaign 1 Governance & Reproducibility (Priority: P4)

As a governance auditor, I want Campaign 1 family registration to validate the complete immutable specification hash, and the codebase to pass all linters, typecheckers, and regression tests under pinned dependencies, so that execution remains blocked until empirical data is certified.

**Why this priority**: Guarantees that code quality meets all strict CI standards while keeping Campaign Stage A blocked until data evidence is independently certified.

**Independent Test**: Can be tested independently by running Mypy, Pyright, Ruff, compileall, and pytest on the clean branch and asserting that Campaign 1 registration enforces full family spec immutability.

**Acceptance Scenarios**:

1. **Given** a campaign registration request where any parameter of `ExperimentFamilySpec` differs from the frozen definition, **When** `_campaign_1_family` validates it, **Then** registration is rejected.
2. **Given** the clean codebase, **When** Ruff, Mypy, and Pyright are executed, **Then** all static analysis passes with zero errors.
3. **Given** the PIT data status, **When** validation completes, **Then** `approved_for_import` remains `false`, `Independent QA` remains `NOT_ASSERTED`, and `Campaign Stage A` remains `BLOCKED`.

---

### Edge Cases

- Reversal orders where requested size exceeds existing opposite position: allowed up to reversal limit.
- Signature verification on malformed base64, truncated keys, or altered JSON key ordering: rejected with canonical deserialization error.
- Ticker aliases with open-ended `valid_until`: matched for all candle dates `>= valid_from`.
- Consecutive corporate actions on the exact same date for the same instrument: handled without collapsing into a zero-length interval or losing provenance.
- Clean database command pointed at production database path without override flags: hard exit.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Sizing validator MUST cap non-reversal risk-increasing position requests to `position_limit - abs(current_position_notional)`.
- **FR-002**: Approval evidence MUST include `issuer_key_id` and a digital signature covering a deterministic canonical payload.
- **FR-003**: The approval verifier MUST verify digital signatures using trusted public keys configured outside the approval evidence (Ed25519 asymmetric cryptography).
- **FR-004**: The approval verifier MUST reject unknown issuers, unknown key IDs, malformed signatures, modified payloads, expired keys, or revoked keys.
- **FR-005**: `PromotionEngine.assert_paper_authorized()` MUST bind and enforce `run_id`, `strategy_name`, `stage`, `foundation_cert_id`, `risk_policy_hash`, `code_sha`, `evidence_hash`, `scope`, and `subject_type`.
- **FR-006**: If any required context at `assert_paper_authorized()` cannot be resolved or does not match, the engine MUST fail closed.
- **FR-007**: Security-master resolver MUST NOT certify historical identities using current snapshots when no historical evidence exists prior to the snapshot date.
- **FR-008**: Aliases with `valid_from >= valid_until` MUST NOT be accepted as certified.
- **FR-009**: The research and PIT candle join MUST match candles by durable `instrument_id`, falling back to alias resolution ONLY within date-bounded intervals (`valid_from <= candle_date < valid_until`).
- **FR-010**: Ticker renames MUST represent identity continuity without manufacturing artificial index ADD/DROP events.
- **FR-011**: Constituent interval builder MUST NEVER emit intervals where `effective_from >= effective_until`.
- **FR-012**: Canonical events for AMTEKAUTO MUST be preserved while resolving any interval anomalies to ensure valid, non-zero interval coverage.
- **FR-013**: Database migrations MUST execute SQL changes and migration record insertion within a single atomic transaction.
- **FR-014**: Database backup and maintenance tools MUST enforce file safety, connection quiescence, and explicit confirmation flags.
- **FR-015**: Platform scheduler and providers MUST classify fallbacks, respect market trading sessions, and support cooperative cancellation.
- **FR-016**: Dashboard analytics MUST correctly compound monthly returns across boundary bars and return infinite profit factor when gross loss is zero.
- **FR-017**: AI liquidity evaluation MUST be calculated from market candle volume and turnover rather than internal execution fills.
- **FR-018**: Campaign 1 family registration MUST validate the full `ExperimentFamilySpec` definition hash rather than a partial subset of fields.
- **FR-019**: Frozen risk-policy lineage in `run_pipeline.py` MUST match the canonical hash of `config/risk_policy.yaml`.
- **FR-020**: The PIT package rebuild MUST use only existing tracked evidence, with no new scraping or web requests.
- **FR-021**: The structural PIT importer dry-run MUST validate structural integrity independently of governance approval flags.
- **FR-022**: Governance statuses MUST remain fail-closed: `approved_for_import = false`, `Independent QA = NOT_ASSERTED`, `Campaign Stage A = BLOCKED`, `live trading = DISABLED`.
- **FR-023**: Required dependencies (`cryptography`, `xlrd`, `pypdf`, etc.) MUST be declared in `requirements.txt` and pinned in lockfiles.
- **FR-024**: All modified modules MUST pass Ruff, Mypy, and Pyright without blanket ignores or relaxed rules.
- **FR-025**: The pull request MUST be created from a clean branch based on `origin/main` without bloating Git history with generated Parquet/CSV artifacts.

### Key Entities

- **ApprovalEvidence**: Canonical container for promotion approvals, containing stage, timestamps, scope, subject, hashes, `issuer_key_id`, and `signature`.
- **TrustedKeyStore**: External registry mapping `issuer_key_id` to authorized public verification keys and validity status.
- **InstrumentAliasHistory**: Representation of historical ticker aliases with `instrument_id`, `alias_symbol`, `valid_from`, and `valid_until`.
- **ConstituentInterval**: Date range (`effective_from` to `effective_until`) representing continuous index membership for an `instrument_id`.
- **ExperimentFamilySpec**: Complete immutable definition of a research campaign family, including model, space, universe, costs, and walk-forward parameters.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of invalid risk-increasing top-up requests exceeding headroom are capped or rejected.
- **SC-002**: 100% of forged, tampered, or mismatched external approval payloads are rejected fail-closed.
- **SC-003**: 0 instances of zero-length or inverted constituent intervals (`effective_from >= effective_until`) in rebuilt PIT data.
- **SC-004**: 0 instances of out-of-period ticker alias candle matches in research datasets.
- **SC-005**: 100% of migration failure tests demonstrate complete transaction rollback with zero partial schema changes.
- **SC-006**: All static analysis gates (Ruff, Mypy, Pyright, compileall) pass with 0 errors.
- **SC-007**: Rebuilt PIT package structurally validates while preserving `approved_for_import = false` and `Campaign Stage A = BLOCKED`.
- **SC-008**: PR diff contains 0 tracked Parquet files, 0 database files, 0 private signing keys, and 0 temporary test artifacts.

## Assumptions

- Ed25519 public keys for test environments can be stored in configuration files or test fixtures without embedding private keys.
- Existing historical PIT evidence in the repository is sufficient to rebuild the current dataset package without external network access.
- DuckDB single-writer file lock semantics are preserved by using temporary isolated databases during testing and rebuilds.
