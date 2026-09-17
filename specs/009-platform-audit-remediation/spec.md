# Feature Specification: Platform Correctness, Safety, PIT Identity & Governance Remediation

**Feature Branch**: `009-platform-audit-remediation`

**Created**: 2026-09-18

**Status**: Specified

**Input**: Repair verified platform correctness, safety, PIT identity, operational controls, and governance defects.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deterministic Risk Enforcement & Authentic Approval Verification (Priority: P1)

As a risk officer and platform operator, I require that all risk limits strictly constrain exposure under all order types (including position top-ups, reversals, and shorts), that external human approvals cannot be bypassed or stage-confused, and that AI advisory tools evaluate market liquidity rather than the system's own fills.

**Why this priority**: Directly protects capital and enforces the non-negotiable boundaries of the platform. Flaws here allow unauthorized or oversized risk exposure.

**Independent Test**:
- Submit a trade proposal with ₹100,000 capital, 5% max position limit, an existing long position of ₹4,000, and a requested buy order of ₹2,000. Verify the system caps the approved order at exactly ₹1,000 (resulting in exactly ₹5,000 position).
- Submit an external approval evidence payload marked `PAPER_CANDIDATE` when requesting `PAPER_ACTIVE` stage execution. Verify the verification fails closed with a permission error.
- Submit a trade proposal in AI research workflow for a stock with no strategy fills today but ₹100 crore market volume. Verify it is not rejected for zero liquidity.

**Acceptance Scenarios**:
1. **Given** an account with capital ₹100,000, max position limit 5% (₹5,000), and existing long position ₹4,000, **When** a buy order of ₹2,000 is proposed, **Then** the risk validator caps the approved notional at ₹1,000 with reason `notional_capped_by_risk_policy`.
2. **Given** an account with existing short position ₹4,000, **When** a sell order of ₹2,000 is proposed, **Then** it is capped at ₹1,000.
3. **Given** an existing position exceeding the limit (₹6,000), **When** a risk-reducing order (sell ₹2,000) is proposed, **Then** the risk-reducing portion is approved in full.
4. **Given** an external approval payload without verified authority, expired time, mismatched hash, or requesting `PAPER_ACTIVE` with only `PAPER_CANDIDATE` approval, **When** `verify_approval` is invoked, **Then** a `PermissionError` is raised.
5. **Given** AI research workflow evaluating a candidate trade, **When** calculating turnover liquidity, **Then** market liquidity is derived from candle volume/turnover, not internal `strategy_fills`.

---

### User Story 2 - Point-in-Time Identity, Valid Alias Intervals & Research Integration (Priority: P1)

As a quantitative researcher, I require historical index constituent datasets to accurately track corporate actions and ticker renames across time without dropping candles, that security master snapshots do not back-project listing dates as validity boundaries, and that alias intervals strictly satisfy `valid_from < valid_until`.

**Why this priority**: Lookahead bias or survivorship bias in historical constituents corrupts all subsequent backtests and statistical evaluations. Renamed constituents dropped from the universe distort research results.

**Independent Test**:
- Resolve an instrument from a 2012 event using only a 2026 security master snapshot. Verify the resolver refuses to certify historical validity unless dated evidence explicitly covers 2012.
- Inspect `instrument_aliases.parquet`. Verify 0 rows have `valid_from >= valid_until`.
- Load research dataset for a constituent that renamed during index membership (e.g. ADANIGAS to ATGL or INFRATEL to INDUSTOWER). Verify candles from both before and after the rename are eligible during the constituent's active membership interval.

**Acceptance Scenarios**:
1. **Given** an NSE security master retrieved in 2026, **When** parsed into identity evidence, **Then** `valid_from` is bounded by the snapshot date or period-substantiated date, not the company's IPO listing date.
2. **Given** corporate rename records, **When** generating aliases, **Then** each alias period is strictly validated (`valid_from < valid_until`), preserving distinct historical intervals without overwriting.
3. **Given** point-in-time constituent records in DuckDB, **When** filtering market candles by universe eligibility, **Then** filtering matches on durable instrument ID and dated aliases, ensuring historical candles match regardless of ticker rename.

---

### User Story 3 - Operational Hardening: Migrations, Backups, Maintenance & Dashboard (Priority: P2)

As an operations engineer, I require database migrations to execute atomically with schema version recording, database backups/restores to guarantee quiescence and clean WAL state, destructive commands to require explicit targets/confirmation, and the dashboard to accurately compute returns and handle network/backend errors.

**Why this priority**: Prevents database corruption, partial migrations, accidental data wiping, and misleading performance metrics in the monitoring interface.

**Independent Test**:
- Inject a SQL failure into a migration script. Verify that all changes roll back atomically and `schema_migrations` contains no record of the failed migration.
- Call `clean_db.py` without explicit arguments. Verify it refuses to delete data without an explicit target and confirmation flag.
- Inspect dashboard monthly return calculation. Verify it accurately compounds returns across month boundaries using previous month-end equity.
- Simulate an API error in the dashboard UI. Verify it displays a clear error state and ignores stale out-of-order responses.

**Acceptance Scenarios**:
1. **Given** a multi-statement migration, **When** any statement fails, **Then** the entire transaction rolls back atomically.
2. **Given** a database backup operation, **When** copying the file, **Then** writer quiescence is enforced and the connection remains synchronized.
3. **Given** a database restore operation, **When** overwriting a target, **Then** any orphaned WAL files at the destination are safely cleaned up.
4. **Given** `clean_db.py`, **When** executed without target and confirmation, **Then** it refuses execution.
5. **Given** a trading run with 100% winning trades, **When** viewing trade stats, **Then** profit factor is not reported as `0.0`.
6. **Given** task cancellation in the orchestration engine, **When** `cancel_task` is called, **Then** the worker thread cooperatively halts and does not overwrite status to `SUCCEEDED`.

---

### User Story 4 - Campaign Governance Reconciliation & CI/CD Reproducibility (Priority: P2)

As a governance auditor and platform maintainer, I require Campaign 1 experiment definitions to be immutably verified, the canonical risk policy hash to match the runtime configuration, and the dependency lockfile/CI pipeline to cover all tools, entrypoints, and parsers.

**Why this priority**: Ensures experiments cannot drift silently, dependencies are fully reproducible on clean machines, and CI checks catch type errors across all operational tools.

**Independent Test**:
- Run `research.py` against an experiment family with altered parameters. Verify it rejects the execution as an immutable specification violation.
- Inspect `run_pipeline.py` and `config/risk_policy.yaml`. Verify risk policy hashes are reconciled through documented governance.
- Build and type-check the repository in a fresh environment. Verify `xlrd` and `pypdf` are declared, and Pyright covers tools, AI research, and entrypoints.

**Acceptance Scenarios**:
1. **Given** an existing `ExperimentFamilySpec` in DuckDB, **When** `register_experiment_family` or `_ensure_campaign_1_family` runs, **Then** any difference in hypothesis, strategies, bounds, or configs raises an error.
2. **Given** `config/risk_policy.yaml`, **When** loaded by `risk/factory.py`, **Then** the computed canonical SHA-256 hash matches the policy declaration and pipeline expectations.
3. **Given** a fresh Python 3.12/3.13 virtual environment without pre-installed packages, **When** `pip install -r requirements.txt -r requirements.lock` runs, **Then** all parsers (including `.xls` and `.pdf`) execute without missing dependency errors.
4. **Given** Pyright and test coverage configurations, **When** CI runs, **Then** tools, entrypoints, and preflight scripts are included.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `PositionSizeValidator` MUST compute available increasing exposure by subtracting existing same-direction exposure from the position limit: `available = max(position_limit - abs(current_position), 0.0)`.
- **FR-002**: `PositionSizeValidator` MUST allow full execution of risk-reducing portions of any trade proposal while capping the risk-increasing portion.
- **FR-003**: `ExternalApprovalVerifier.verify_approval` MUST enforce that `approved_stage` strictly authorizes `expected_stage` (specifically, `PAPER_CANDIDATE` CANNOT authorize `PAPER_ACTIVE`).
- **FR-004**: `ExternalApprovalVerifier` MUST validate that approval evidence is non-empty, unexpired, bound to the exact `run_id`, `strategy_name`, and expected policy/certification hashes.
- **FR-005**: `parse_security_master` MUST NOT use company listing date as `valid_from` for an ISIN or symbol without contemporaneous evidence.
- **FR-006**: `instrument_resolver.py` MUST NOT certify an identity for a historical date based solely on a future snapshot and an old company listing date.
- **FR-007**: `build_public_dataset.py` alias construction MUST ensure `valid_from < valid_until` for every generated alias; any inverted or invalid intervals must be flagged or rejected.
- **FR-008**: `PointInTimeUniverseManager` and `trading_stack/datasets.py` MUST match universe constituent eligibility using durable instrument IDs and dated alias history, preventing ticker renames from dropping valid constituents.
- **FR-009**: `ai_research/workflow.py` MUST filter `historical_candles` by explicit `timeframe` and compute turnover liquidity from market candle volume/turnover rather than `strategy_fills`.
- **FR-010**: `MigrationRunner` MUST wrap migration SQL execution and `schema_migrations` insertion inside an explicit database transaction (`BEGIN TRANSACTION` / `COMMIT`).
- **FR-011**: `operations/backup.py` MUST maintain an open connection/lock during backup copying or ensure full writer quiescence before file copy, and `restore` MUST clean up any destination `.wal` files.
- **FR-012**: `clean_db.py` MUST require explicit `--target-db` and `--force`/`--confirm` flags, execute deletions within a transaction, and fail if any table deletion fails.
- **FR-013**: `data_platform/providers.py` MUST catch only classified transient exceptions (`ProviderUnavailable`, `ConnectionError`, `TimeoutError`) for fallback, and OpenBB provider MUST verify returned adjustment metadata.
- **FR-014**: `scheduler.py` MUST incorporate exchange trading session calendars to handle special sessions and weekend market schedules.
- **FR-015**: `orchestration/engine.py` MUST implement cooperative cancellation tokens (`threading.Event`) checked by worker loops.
- **FR-016**: `tools/dashboard/api/main.py` monthly returns MUST compute return from previous month-end equity to current month-end equity, and return `inf` or `None` (not `0.0`) when profit factor has no losses.
- **FR-017**: `tools/dashboard/ui/src/components/AnalyticsTab.tsx` MUST check `response.ok`, handle loading/error states, and use `AbortController` to cancel pending requests on run selection change.
- **FR-018**: `requirements.txt` and `requirements.lock` MUST declare `xlrd>=2.0.1` and include `pypdf`.
- **FR-019**: `pyrightconfig.json` and CI coverage settings MUST include `tools`, `ai_research`, `main.py`, `research.py`, `run_pipeline.py`, and `scheduler.py`.
- **FR-020**: `build_public_dataset.py` MUST generate stable `observation_id`s, distinguish redundant raw workbook observations from unestablished events, and make calendar audit certification evidence-driven rather than hardcoded.

---

## Success Criteria *(mandatory)*

- **SC-001**: 100% of new regression tests pass, covering position top-ups, short sizing, reversals, approval verification boundaries, alias intervals, and migration rollbacks.
- **SC-002**: `PositionSizeValidator` tests pass for all combinations of long/short top-up, reduce-only, and limit-breach conditions.
- **SC-003**: 0 rows in `instrument_aliases.parquet` have `valid_from >= valid_until`.
- **SC-004**: Renamed instruments (e.g. ADANIGAS/ATGL) maintain seamless candle eligibility across their rename dates in research dataset filtering.
- **SC-005**: All existing 992 unit tests in `tests/` continue to pass without regressions.
- **SC-006**: Ruff lint, Mypy type-checking, and Pyright type-checking pass with 0 errors across all audited packages.
- **SC-007**: Importer dry-run against the real artifact package safely verifies integrity and confirms fail-closed behavior (`REFUSED_AS_DESIGNED` while uncertified).
