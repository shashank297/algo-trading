"""Generate decision-ready reports for unresolved NIFTY-200 PIT evidence.

This module deliberately does not promote provisional evidence, change
validation policy, or alter the production database.  It turns the current
fail-closed artifacts into case files that identify the exact evidence still
needed for closure.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


CASE_COLUMNS = [
    "case_id",
    "blocker_id",
    "blocker_type",
    "date",
    "year",
    "symbol",
    "company",
    "instrument_id",
    "isin",
    "expected_value",
    "observed_value",
    "source_tier",
    "source_url",
    "source_sha256",
    "severity",
    "root_cause",
    "resolution_status",
    "resolution_source",
    "missing_evidence",
    "searches_performed",
    "official_urls_checked",
    "why_insufficient",
    "closure_document",
]

OFFICIAL_URLS = ";".join(
    (
        "https://www.niftyindices.com/Press_Release/ind_prs16052012.pdf",
        "https://www.niftyindices.com/media",
        "https://niftyindices.com/indices/equity/broad-based-indices/nifty-200",
        "https://niftyindices.com/reports/monthly-reports",
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
        "https://nsearchives.nseindia.com/content/equities/namechange.csv",
        "https://web.archive.org/",
    )
)
SEARCHES = (
    "official Nifty Indices press releases and monthly reports; official NSE "
    "historical bhavcopies and security masters; official symbol/name-change "
    "candidates; Wayback copies of official URLs; exact symbol/ISIN joins only"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _metric(report: dict[str, Any], name: str, default: Any = 0) -> Any:
    metrics = report.get("metrics", {})
    if name in metrics:
        return metrics[name]
    return report.get(name, default)


def _case_row(row: dict[str, str], case_type: str) -> dict[str, str]:
    blocker_type = row.get("blocker_type", "")
    if case_type == "identity":
        missing = (
            "An authoritative historical security-master or corporate-action "
            "document linking the dated symbol/company to the exact ISIN."
        )
        closure = "reports/nifty200_pit_identity_blocker_cases.csv"
    else:
        missing = (
            "The official publication timestamp or dated announcement document "
            "for the event; effective date alone is not sufficient."
        )
        closure = "reports/nifty200_pit_announcement_blocker_cases.csv"
    return {
        "case_id": f"{case_type}-{row.get('blocker_id', '')[:16]}",
        "blocker_id": row.get("blocker_id", ""),
        "blocker_type": blocker_type,
        "date": row.get("date", ""),
        "year": row.get("year", ""),
        "symbol": row.get("symbol", ""),
        "company": row.get("company", ""),
        "instrument_id": row.get("instrument_id", ""),
        "isin": row.get("isin", ""),
        "expected_value": row.get("expected_value", ""),
        "observed_value": row.get("observed_value", ""),
        "source_tier": row.get("source_tier", ""),
        "source_url": row.get("source_url", ""),
        "source_sha256": row.get("source_sha256", ""),
        "severity": row.get("severity", ""),
        "root_cause": row.get("root_cause", ""),
        "resolution_status": "MANUAL_REVIEW",
        "resolution_source": "",
        "missing_evidence": missing,
        "searches_performed": SEARCHES,
        "official_urls_checked": OFFICIAL_URLS,
        "why_insufficient": (
            "The local corpus has no exact A1/A2 evidence that closes this case. "
            "B1, fuzzy matches, current-only identity, and name similarity remain "
            "non-authoritative under the fail-closed policy."
        ),
        "closure_document": closure,
    }


def _write_monthly_governance(root: Path, monthly_rows: list[dict[str, str]]) -> None:
    counts = Counter(row.get("source_issue", "UNCLASSIFIED") for row in monthly_rows)
    gap_rows = [row for row in monthly_rows if row.get("status") != "PASS"]
    lines = [
        "# NIFTY-200 PIT Monthly Checkpoint Governance Decision",
        "",
        "## Decision",
        "",
        "The monthly checkpoint gate remains BLOCKED. No missing checkpoint is",
        "converted into a synthetic snapshot, and no non-200 result is silently",
        "accepted as a complete historical constituent list.",
        "",
        "The current report contains "
        f"{len(gap_rows)} non-passing checkpoint rows. The categories below are",
        "kept separate because each requires different evidence.",
        "",
        "| Category | Rows | Required action |",
        "| --- | ---: | --- |",
        f"| A: no snapshot evidence | {counts.get('A_NO_SNAPSHOT_EVIDENCE', 0)} | Retrieve an official historical checkpoint or record an evidence gap |",
        f"| B: candidate/zero-row extraction | {counts.get('B_CANDIDATE_MEMBER_ZERO_ROWS', 0)} | Reconcile the official archive contents and parser output |",
        f"| C: wrong table or parser selection | {counts.get('C_WRONG_TABLE_OR_PARSER', 0)} | Inspect source tables and add parser coverage |",
        f"| D: documented non-200 methodology | {counts.get('D_DOCUMENTED_NON_200', 0)} | Obtain the methodology or official exception document |",
        f"| E: corrupt/incomplete download | {counts.get('E_HTML_RESPONSE_NOT_ARCHIVE', 0)} | Retrieve a verified archive or Wayback copy |",
        "",
        "The May 2012 response is retained as a source-access failure because the",
        "cached response is HTML rather than the expected archive. The official",
        "May 16, 2012 press-release URL remains a retrieval target; its publication",
        "does not substitute for a complete 2012-01-02 constituent checkpoint.",
        "",
        "No governance override is authorized. The validator must continue to",
        "require an authoritative checkpoint and replay reconciliation before import.",
    ]
    path = root / "reports" / "nifty200_pit_monthly_checkpoint_governance_decision.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate(root: Path) -> dict[str, Any]:
    artifact_root = root / "artifacts" / "nifty200_pit_v1"
    report_root = root / "reports"
    ledger = _read_csv(artifact_root / "blocker_ledger.csv")
    monthly = _read_csv(report_root / "nifty200_pit_monthly_gap_analysis.csv")
    validation_path = artifact_root / "validation_report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))

    identity_types = {
        "MISSING_DURABLE_IDENTITY",
        "HISTORICAL_SYMBOL_CHANGE",
        "HISTORICAL_ISIN_CHANGE",
        "DELISTED_SECURITY",
        "MERGER_SUCCESSOR",
        "AMBIGUOUS_COMPANY",
    }
    announcement_types = {
        "MISSING_ANNOUNCEMENT_DATE",
        "MISSING_EFFECTIVE_DATE",
        "MISSING_EVENT_CAUSALITY",
    }
    identity_rows = [row for row in ledger if row.get("blocker_type") in identity_types]
    announcement_rows = [
        row for row in ledger if row.get("blocker_type") in announcement_types
    ]
    _write_csv(
        report_root / "nifty200_pit_identity_blocker_cases.csv",
        [_case_row(row, "identity") for row in identity_rows],
        CASE_COLUMNS,
    )
    _write_csv(
        report_root / "nifty200_pit_announcement_blocker_cases.csv",
        [_case_row(row, "announcement") for row in announcement_rows],
        CASE_COLUMNS,
    )

    paid_columns = [
        "blocker_id",
        "date",
        "symbol",
        "company",
        "current_master_only",
        "free_sources_checked",
        "paid_source_needed",
        "decision",
        "notes",
    ]
    paid_rows = [
        {
            "blocker_id": row.get("blocker_id", ""),
            "date": row.get("date", ""),
            "symbol": row.get("symbol", ""),
            "company": row.get("company", ""),
            "current_master_only": "YES",
            "free_sources_checked": SEARCHES,
            "paid_source_needed": (
                "Historical exchange security master or corporate-action ISIN link"
            ),
            "decision": "NOT_PURCHASED; FREE_ONLY_SCOPE",
            "notes": (
                "Do not certify from current EQUITY_L.csv, fuzzy names, or a "
                "third-party paid mapping. Keep MANUAL_REVIEW."
            ),
        }
        for row in identity_rows
    ]
    _write_csv(report_root / "nifty200_pit_paid_identity_fallback.csv", paid_rows, paid_columns)
    _write_monthly_governance(root, monthly)

    blocker_counts = Counter(row.get("blocker_type", "OTHER") for row in ledger)
    current_summary = {
        "source_count": _metric(validation, "source_count"),
        "source_hash_error_count": _metric(validation, "source_hash_error_count"),
        "event_observation_count": _metric(validation, "event_observation_count"),
        "canonical_event_count": _metric(validation, "canonical_event_count"),
        "snapshot_row_count": _metric(validation, "snapshot_row_count"),
        "snapshot_date_count": _metric(validation, "snapshot_date_count"),
        "valid_200_checkpoints": _metric(validation, "valid_200_checkpoints"),
        "missing_or_non_200_checkpoints": _metric(
            validation, "missing_or_non_200_checkpoints"
        ),
        "interval_count": _metric(validation, "interval_count"),
        "trading_days_checked": _metric(validation, "trading_days_checked"),
        "minimum_active_constituent_count": _metric(
            validation, "minimum_active_constituent_count"
        ),
        "maximum_active_constituent_count": _metric(
            validation, "maximum_active_constituent_count"
        ),
        "sessions_not_expected_count": _metric(validation, "sessions_not_expected_count"),
        "known_at_unresolved_count": _metric(validation, "known_at_unresolved_count"),
        "conflict_count": _metric(validation, "conflict_count"),
        "high_conflict_count": _metric(validation, "high_conflict_count"),
        "critical_conflict_count": _metric(validation, "critical_conflict_count"),
        "status": validation.get("status", "UNKNOWN"),
        "passed": validation.get("passed", False),
    }
    summary_rows: list[dict[str, Any]] = []
    baseline_counts = {
        "MISSING_INITIAL_ANCHOR": 170,
        "MONTHLY_SNAPSHOT_MISSING": 68,
        "MISSING_ANNOUNCEMENT_DATE": 39,
        "MISSING_DURABLE_IDENTITY": 58,
        "SOURCE_DOWNLOAD_FAILURE": 1,
        "DUPLICATE_EVENT": 1,
    }
    for blocker_type in sorted(set(baseline_counts) | set(blocker_counts)):
        before = baseline_counts.get(blocker_type, 0)
        after = blocker_counts.get(blocker_type, 0)
        summary_rows.append(
            {
                "metric": blocker_type,
                "before": before,
                "after": after,
                "delta": after - before,
                "status": "REMAINING" if after else "CLOSED",
                "evidence_basis": "measured blocker ledger counts",
                "notes": "A negative delta is not an authority upgrade; unresolved rows remain fail-closed.",
            }
        )
    summary_rows.extend(
        [
            {
                "metric": "TOTAL_BLOCKER_ROWS",
                "before": 337,
                "after": len(ledger),
                "delta": len(ledger) - 337,
                "status": "REMAINING" if ledger else "CLOSED",
                "evidence_basis": "measured blocker ledger counts",
                "notes": "Starting point was the evidence-enriched build before this closure pass.",
            },
            {
                "metric": "CONFLICT_ROWS",
                "before": 268,
                "after": current_summary["conflict_count"],
                "delta": current_summary["conflict_count"] - 268,
                "status": "REMAINING" if current_summary["conflict_count"] else "CLOSED",
                "evidence_basis": "measured validation metrics",
                "notes": "Conflict reduction came from filtering superseded official assertions and parser correction.",
            },
        ]
    )
    _write_csv(
        report_root / "nifty200_pit_evidence_resolution_summary.csv",
        summary_rows,
        ["metric", "before", "after", "delta", "status", "evidence_basis", "notes"],
    )

    report_lines = [
        "# NIFTY-200 PIT Evidence Closure — Current Measured State",
        "",
        "## Scope and safety",
        "",
        "This report records the current real-data build after the evidence-closure",
        "pass. It does not create historical members, promote B1 evidence, certify",
        "fuzzy identity matches, weaken the checkpoint gate, or import into DuckDB.",
        "",
        "The earlier recovery baseline remains preserved in",
        "`reports/nifty200_pit_recovery_closure_20260919.md`. The evidence-enriched",
        "starting point for this pass was 583 sources and 337 blocker rows.",
        "",
        "## Current measurements",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
    ]
    labels = (
        ("Source count", "source_count"),
        ("Source hash failures", "source_hash_error_count"),
        ("Event observations", "event_observation_count"),
        ("Canonical events", "canonical_event_count"),
        ("Snapshot rows", "snapshot_row_count"),
        ("Snapshot dates", "snapshot_date_count"),
        ("Valid 200 checkpoints", "valid_200_checkpoints"),
        ("Missing/non-200 checkpoints", "missing_or_non_200_checkpoints"),
        ("Constituent intervals", "interval_count"),
        ("Trading sessions checked", "trading_days_checked"),
        ("Minimum active constituents", "minimum_active_constituent_count"),
        ("Maximum active constituents", "maximum_active_constituent_count"),
        ("Sessions not expected", "sessions_not_expected_count"),
        ("Known-at unresolved", "known_at_unresolved_count"),
        ("Conflicts", "conflict_count"),
        ("HIGH conflicts", "high_conflict_count"),
        ("CRITICAL conflicts", "critical_conflict_count"),
    )
    report_lines.extend(f"| {label} | {current_summary[key]} |" for label, key in labels)
    report_lines.extend(
        [
            "",
            f"Validation status: **{current_summary['status']}**.",
            "",
            "## Remaining blocker classes",
            "",
        ]
    )
    report_lines.extend(
        f"- `{key}`: {value} rows"
        for key, value in sorted(blocker_counts.items())
    )
    report_lines.extend(
        [
            "",
            "The case CSVs contain one row per current identity or announcement",
            "blocker, including the missing document, official URLs checked, and the",
            "exact condition needed to close it. The monthly governance report keeps",
            "missing, malformed, wrong-table, methodology, and HTML-response cases",
            "separate. The paid fallback file is an audit record only; no paid source",
            "was purchased or used.",
            "",
            "## Final disposition",
            "",
            "NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED",
            "",
            "INDEPENDENT QA: NOT ASSERTED",
            "",
            "CAMPAIGN STAGE A: BLOCKED",
        ]
    )
    (report_root / "nifty200_pit_evidence_closure_current.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    return {
        "identity_cases": len(identity_rows),
        "announcement_cases": len(announcement_rows),
        "monthly_non_passing": len([row for row in monthly if row.get("status") != "PASS"]),
        "blocker_rows": len(ledger),
        "validation_status": current_summary["status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = generate(args.root.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
