# Phase 0 Research: Technical Analysis & Remediation Strategy

**Feature**: `009-platform-audit-remediation`

## 1. Risk Engine Position Sizing (`risk/validators.py`)
- **Current Defect**: `PositionSizeValidator.evaluate` calculates `base_offset = abs(proposal.current_position_notional) if proposal.net_exposure_reducing else 0.0`.
  For top-ups (increasing an existing position), `net_exposure_reducing` is `False`, setting `base_offset = 0.0`. This computes `available_increasing = position_limit - 0 = position_limit`, completely ignoring the existing position!
- **Resolution**:
  - Distinguish risk-reducing from risk-increasing notionals.
  - For risk-increasing notional in the same direction, the maximum allowable incremental exposure is `max(position_limit - abs(proposal.current_position_notional), 0.0)`.
  - The capped notional must be `proposal.risk_reducing_notional + min(proposal.risk_increasing_notional, available_increasing)`.
  - Handle direction reversals: closing existing long of ₹4,000 and going short ₹2,000 (total sell ₹6,000): risk-reducing portion is ₹4,000 (approved in full); risk-increasing portion is ₹2,000 short, checked against `position_limit` (₹5,000) -> approved ₹6,000.

## 2. External Approval Verification (`trading_stack/approval.py`)
- **Current Defect**: Line 124 checks `approved_stage not in {expected_stage.upper(), "PAPER_ACTIVE", "PAPER_CANDIDATE"}`. This permits an approval granted only for `PAPER_CANDIDATE` to be accepted when executing `PAPER_ACTIVE`. Additionally, there is no enforcement of signature/digest verification or bound hashes.
- **Resolution**:
  - Strict stage hierarchy or exact matching: if `expected_stage == "PAPER_ACTIVE"`, `approved_stage` MUST be `"PAPER_ACTIVE"`. `PAPER_CANDIDATE` cannot authorize `PAPER_ACTIVE`.
  - Validate all declared evidence fields: `code_sha`, `risk_policy_hash`, `evidence_hash`, `approved_at`, `expires_at`, and `scope`.
  - Fail closed on missing fields, expired timestamps, or mismatched hashes.

## 3. Historical Identity & Alias Validation (`tools/nifty200_pit`)
- **Current Defect 1**: `parse_security_master` sets `"valid_from": listing_date`, and `instrument_resolver.py` considers an instrument valid on date `when` if `start <= when` and `end is None`. A 2026 snapshot thus certifies an ISIN back to 1995.
- **Current Defect 2**: `build_public_dataset.py` alias construction generates 54 rows where `valid_from >= valid_until`.
- **Resolution**:
  - `parse_security_master`: Snapshot evidence validity starts at `snapshot_date`, NOT `listing_date`. Listing date is purely informational metadata.
  - Aliases: Filter and validate that `valid_from < valid_until` for every alias. Inverted rows are discarded or marked `UNCERTIFIED` / `MANUAL_REVIEW`.
  - Lineage: Assign stable deterministic observation IDs (`obs_{sha256(content)[:16]}`).
  - Calendar: Decouple `calendar_not_certified` conflict from hardcoded unconditional injection; make it evaluate calendar certification evidence.

## 4. PIT to Research Dataset Integration (`trading_stack/datasets.py`)
- **Current Defect**: `filter_by_point_in_time_universe` matches candles using `symbols == str(row["symbol"]).upper()`. Renamed symbols like `ADANIGAS -> ATGL` fail to match candles post-rename because the constituent interval stores `symbol_at_entry`.
- **Resolution**:
  - Load instrument aliases and historical instrument master into universe metadata.
  - Map candle symbols to durable `instrument_id` or match symbols across the constituent's historical alias interval so that both pre-rename and post-rename tickers are recognized as belonging to the constituent interval.

## 5. Storage Migration Atomicity (`storage/migrations/runner.py`)
- **Current Defect**: `self.conn.execute(sql_content)` runs outside a transaction. A mid-migration failure leaves partial schema changes applied without recording the version in `schema_migrations`.
- **Resolution**:
  - Wrap migration execution and history insert in `BEGIN TRANSACTION` and `COMMIT`, with `ROLLBACK` on exception.
  - In DuckDB, DDL statements like `CREATE TABLE` and `INSERT` can be enclosed in transaction blocks.

## 6. Operational Controls (`backup.py`, `clean_db.py`, `scheduler.py`, `engine.py`)
- **Backup/Restore**: Perform checkpoint while connection is active, ensure file copy occurs under quiescence or file lock, and clean up destination `.wal` before restoring.
- **`clean_db.py`**: Add command-line argument parsing with `--database <path>` and `--confirm`/`--yes`. Do not default to silent deletion.
- **Scheduler**: Interface with market calendar utilities to obtain trading days rather than hardcoding Monday-Friday.
- **Task Engine**: Pass `threading.Event` as a cancellation token into long-running tasks.
