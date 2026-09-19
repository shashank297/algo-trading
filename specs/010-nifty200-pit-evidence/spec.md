# Feature Specification: NIFTY-200 PIT Evidence Resolution & Forensic Gap Audit

**Feature Branch**: `codex/platform-audit-remediation-clean`

**Created**: 2026-09-18

**Status**: Blocked on External Evidence (Fail-Closed As Designed)

**Input**: User description: "Resolve the remaining NIFTY-200 PIT evidence blockers using free, authoritative evidence only."

## Summary & Governance Posture

The objective is to resolve the remaining NIFTY-200 Point-in-Time (PIT) evidence blockers using free, authoritative evidence only. Under strict platform constitution rules:
1. Do not fabricate pre-listing prices or synthetic initial memberships.
2. Do not promote B1 rows into authoritative events.
3. Do not infer an ISIN from a company name.
4. Do not use fuzzy matching to certify identity.
5. Do not merge predecessor/successor companies without an official corporate-action or ISIN-linking document.
6. Treat symbolchange.csv and namechange.csv as candidates unless an official source explicitly proves the durable identity relationship.
7. Keep all unresolved cases as MANUAL_REVIEW.
8. If authoritative free evidence cannot be found, fail closed and produce an exact final evidence-gap report.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Exhaustive Authoritative Source Harvesting (Priority: P1)

As a quantitative researcher, I want the PIT evidence harvester to systematically probe all official NSE and Nifty Indices endpoints, archives, and historical reports for 2012-01-02 initial anchor, 2012-01..2013-03 checkpoints, and 2022-04..2026-08 checkpoints, so that all available free authoritative bytes are captured and hashed without omissions.

**Acceptance Scenarios**:
1. **Given** the official Nifty Indices archive API (`/reports/historical-data/Index/`), **When** queried for Report Type 4 (Indices - Market Capitalisation & Weightage) for months prior to April 2013, **Then** it returns `{"success":false,"message":"No Data Found"}`, proving no pre-April 2013 monthly checkpoints exist in the publisher's digital archive.
2. **Given** Nifty Indices monthly report ZIP archives from April 2022 through August 2026, **When** inspected for member constituents, **Then** all files contain derivative/flagship index PDFs only (`NIFTY_50`, `NIFTY_Bank`, etc.) and omit `NIFTY_200`, establishing a publisher-side discontinuation of free public NIFTY 200 monthly weightage PDFs.
3. **Given** the 2011-07-18 CNX 200 launch press release (`ind_prs18072011.pdf`), **When** extracted and audited, **Then** it provides methodology and selection criteria but contains no dated 200-constituent member list.

---

### User Story 2 - Strict Identity & Lineage Non-Inference (Priority: P1)

As a platform risk and compliance officer, I want the reconciliation and instrument resolver engines to strictly enforce non-inference on 1,050 raw event observations from `IndexInclExcl.xls`, so that no company name is converted to an ISIN or ticker without an official primary linking document.

**Acceptance Scenarios**:
1. **Given** an observation row with company name only (e.g. "Bata India Ltd." on 2012-04-27), **When** evaluated by `resolve_observations()`, **Then** it is marked `UNRESOLVED` / `MANUAL_REVIEW` and prohibited from becoming a `CERTIFIED` canonical event.
2. **Given** candidate identity mappings from `symbolchange.csv` and `namechange.csv`, **When** evaluated without a primary corporate-action circular carrying durable ISINs, **Then** they remain uncertified candidates and cannot close PIT blockers.
3. **Given** candidate records from B1 challenger files (`deshpanda_nse_screener_reconstitution_events.parquet`), **When** processed by reconciliation, **Then** they serve only as search indexes and never override or fabricate official event records.

---

### User Story 3 - Complete Forensic Evidence Gap Reporting & Importer Safety (Priority: P1)

As a research auditor, I want a comprehensive evidence-gap report detailing every unresolved blocker, and a dry-run importer verification proving the database is never mutated while evidence is blocked, so that the platform state remains 100% reproducible and tamper-proof.

**Acceptance Scenarios**:
1. **Given** unresolved blockers in `blocker_ledger.csv`, **When** the evidence gap audit is generated, **Then** it enumerates every blocker with type, date, symbol/company, missing evidence, searches performed, official URLs checked, why evidence is insufficient, and exact required closure document.
2. **Given** blocked validation status, **When** `import_nifty200_pit.py --dry-run` is executed, **Then** it refuses import (`REFUSED_AS_DESIGNED`), exits with code 1, and leaves `market_data.duckdb` and `market_data.duckdb.wal` untouched.
3. **Given** platform governance gates, **When** final certification status is evaluated, **Then** status remains:
   - `NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED`
   - `INDEPENDENT QA: NOT ASSERTED`
   - `CAMPAIGN STAGE A: BLOCKED`
