"""Generate fail-closed residual-evidence reports for the NIFTY-200 PIT build."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


CASE_COLUMNS = [
    "case_id", "blocker_id", "blocker_type", "date", "year", "symbol", "company",
    "instrument_id", "isin", "expected_value", "observed_value", "source_tier",
    "source_url", "source_sha256", "severity", "root_cause", "resolution_status",
    "resolution_source", "missing_evidence", "searches_performed", "official_urls_checked",
    "why_insufficient", "closure_document",
]
IDENTITY_COLUMNS = [
    "case_id", "event_id", "effective_date", "action", "raw_company", "raw_symbol",
    "existing_instrument_id", "existing_isin", "final_status", "resolved_symbol",
    "resolved_isin", "resolved_instrument_id", "valid_from", "valid_until", "source_url",
    "source_document", "source_sha256", "source_tier", "resolution_type", "notes",
]
ANNOUNCEMENT_COLUMNS = [
    "case_id", "event_id", "effective_date", "company", "symbol", "final_status",
    "announcement_date", "known_at", "known_at_rule", "source_url", "source_document",
    "source_sha256", "source_tier", "notes",
]
PAID_COLUMNS = [
    "case_id", "blocker_type", "company", "symbol", "effective_date", "required period",
    "required fields", "free sources checked", "reason unresolved", "minimum paid evidence needed",
]

OFFICIAL_URLS = ";".join((
    "https://www.niftyindices.com/Press_Release/ind_prs16052012.pdf",
    "https://www.niftyindices.com/Press_Release/ind_prs22022016_2.pdf",
    "https://www.niftyindices.com/Press_Release/ind_prs10062020.pdf",
    "https://www.niftyindices.com/media",
    "https://niftyindices.com/indices/equity/broad-based-indices/nifty-200",
    "https://niftyindices.com/reports/monthly-reports",
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
    "https://nsearchives.nseindia.com/content/equities/namechange.csv",
    "https://web.archive.org/",
))
SEARCHES = (
    "official Nifty Indices press releases and monthly reports; official NSE "
    "historical security masters and change notices; exact symbol/ISIN joins; "
    "Wayback copies of official URLs; no fuzzy or paid source used"
)
IDENTITY_TYPES = {
    "MISSING_DURABLE_IDENTITY", "HISTORICAL_SYMBOL_CHANGE", "HISTORICAL_ISIN_CHANGE",
    "DELISTED_SECURITY", "MERGER_SUCCESSOR", "AMBIGUOUS_COMPANY",
}
ANNOUNCEMENT_TYPES = {
    "MISSING_ANNOUNCEMENT_DATE", "MISSING_EFFECTIVE_DATE", "MISSING_EVENT_CAUSALITY",
}


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


def _read_parquet_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        import duckdb
    except ImportError:
        return []
    connection = duckdb.connect()
    try:
        result = connection.execute("SELECT * FROM read_parquet(?)", [str(path)])
        columns = [item[0] for item in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        connection.close()


def _metric(report: dict[str, Any], name: str, default: Any = 0) -> Any:
    metrics = report.get("metrics", {})
    return metrics.get(name, report.get(name, default))


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _source_document(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1] if url else ""


def _canonical_event_id(row: dict[str, str], canonical: list[dict[str, Any]]) -> str:
    date = row.get("date", "")
    symbol = row.get("symbol", "").upper()
    action = row.get("observed_value", "").upper()
    for event in canonical:
        if _text(event.get("effective_date"))[:10] != date:
            continue
        if _text(event.get("symbol")).upper() != symbol:
            continue
        if action and _text(event.get("action")).upper() != action:
            continue
        return _text(event.get("event_hash")) or _text(event.get("observation_id"))
    return row.get("blocker_id", "")


def _missing_evidence(blocker_type: str) -> str:
    if blocker_type in IDENTITY_TYPES:
        return "An authoritative historical security-master or corporate-action document linking the dated symbol/company to the exact ISIN."
    if blocker_type in ANNOUNCEMENT_TYPES:
        return "The official publication timestamp or dated announcement document; effective date alone is not sufficient."
    if blocker_type == "MISSING_INITIAL_ANCHOR":
        return "A complete authoritative CNX/NIFTY-200 membership list effective on or before 2012-01-02, or a complete first-party event chain proving it."
    if blocker_type == "MONTHLY_SNAPSHOT_MISSING":
        return "An official dated checkpoint for the affected month, or an official methodology/exception document explaining the gap."
    if blocker_type == "SOURCE_DOWNLOAD_FAILURE":
        return "Valid archive bytes or a verified Wayback copy of the official source."
    if blocker_type == "DUPLICATE_EVENT":
        return "An official correction, withdrawal, or superseding notice proving whether the duplicate event is stale or a distinct event."
    return "The authoritative first-party evidence required by the blocker root cause."


def _case_row(row: dict[str, str], case_type: str) -> dict[str, str]:
    blocker_type = row.get("blocker_type", "")
    if blocker_type in IDENTITY_TYPES:
        closure = "reports/nifty200_pit_identity_blocker_cases.csv" if case_type == "identity" else "reports/nifty200_pit_evidence_gap_report.csv"
    elif blocker_type in ANNOUNCEMENT_TYPES:
        closure = "reports/nifty200_pit_announcement_blocker_cases.csv" if case_type == "announcement" else "reports/nifty200_pit_evidence_gap_report.csv"
    else:
        closure = "reports/nifty200_pit_evidence_gap_report.csv"
    return {
        "case_id": f"{case_type}-{row.get('blocker_id', '')[:16]}",
        "blocker_id": row.get("blocker_id", ""), "blocker_type": blocker_type,
        "date": row.get("date", ""), "year": row.get("year", ""),
        "symbol": row.get("symbol", ""), "company": row.get("company", ""),
        "instrument_id": row.get("instrument_id", ""), "isin": row.get("isin", ""),
        "expected_value": row.get("expected_value", ""), "observed_value": row.get("observed_value", ""),
        "source_tier": row.get("source_tier", ""), "source_url": row.get("source_url", ""),
        "source_sha256": row.get("source_sha256", ""), "severity": row.get("severity", ""),
        "root_cause": row.get("root_cause", ""), "resolution_status": "MANUAL_REVIEW",
        "resolution_source": "", "missing_evidence": _missing_evidence(blocker_type),
        "searches_performed": SEARCHES, "official_urls_checked": OFFICIAL_URLS,
        "why_insufficient": "No exact A1/A2 evidence in the local corpus closes this case. B1, fuzzy matches, current-only identity, and name similarity remain non-authoritative under the fail-closed policy.",
        "closure_document": closure,
    }


def _identity_case(row: dict[str, str], canonical: list[dict[str, Any]]) -> dict[str, str]:
    source_url = row.get("source_url", "")
    return {
        "case_id": f"identity-{row.get('blocker_id', '')[:16]}",
        "event_id": _canonical_event_id(row, canonical), "effective_date": row.get("date", ""),
        "action": row.get("observed_value", ""), "raw_company": row.get("company", ""),
        "raw_symbol": row.get("symbol", ""), "existing_instrument_id": row.get("instrument_id", ""),
        "existing_isin": row.get("isin", ""), "final_status": "UNRESOLVED",
        "resolved_symbol": "", "resolved_isin": "", "resolved_instrument_id": "",
        "valid_from": "", "valid_until": "", "source_url": source_url,
        "source_document": _source_document(source_url), "source_sha256": row.get("source_sha256", ""),
        "source_tier": row.get("source_tier", ""), "resolution_type": "MANUAL_REVIEW",
        "notes": _missing_evidence(row.get("blocker_type", "")),
    }


def _announcement_case(row: dict[str, str], canonical: list[dict[str, Any]]) -> dict[str, str]:
    source_url = row.get("source_url", "")
    return {
        "case_id": f"announcement-{row.get('blocker_id', '')[:16]}",
        "event_id": _canonical_event_id(row, canonical), "effective_date": row.get("date", ""),
        "company": row.get("company", ""), "symbol": row.get("symbol", ""),
        "final_status": "UNRESOLVED", "announcement_date": "", "known_at": "",
        "known_at_rule": "DATE_ONLY_REQUIRES_NEXT_CERTIFIED_SESSION_OPEN",
        "source_url": source_url, "source_document": _source_document(source_url),
        "source_sha256": row.get("source_sha256", ""), "source_tier": row.get("source_tier", ""),
        "notes": _missing_evidence(row.get("blocker_type", "")),
    }


def _write_monthly_governance(root: Path, monthly_rows: list[dict[str, str]]) -> None:
    counts = Counter(row.get("source_issue", "UNCLASSIFIED") for row in monthly_rows)
    gap_rows = [row for row in monthly_rows if row.get("status") != "PASS"]
    lines = [
        "# NIFTY-200 PIT Monthly Checkpoint Governance Recommendation", "",
        "The strict monthly checkpoint gate remains in force. No missing checkpoint is",
        "converted into a synthetic snapshot, and no non-200 result is silently accepted",
        "as a complete historical constituent list.", "", f"Non-passing checkpoint rows: {len(gap_rows)}.", "",
        "| Classification | Rows | Required evidence/action |", "| --- | ---: | --- |",
        f"| A: no snapshot evidence | {counts.get('A_NO_SNAPSHOT_EVIDENCE', 0)} | Retrieve an official checkpoint or retain an evidence gap |",
        f"| B: candidate/zero-row extraction | {counts.get('B_CANDIDATE_MEMBER_ZERO_ROWS', 0)} | Inspect archive member/table and parser output |",
        f"| C: wrong table/parser | {counts.get('C_WRONG_TABLE_OR_PARSER', 0)} | Add parser coverage only after source inspection |",
        f"| D: documented non-200 methodology | {counts.get('D_DOCUMENTED_NON_200', 0)} | Obtain the official exception/methodology document |",
        f"| E1: corrupt/incomplete download | {counts.get('E_HTML_RESPONSE_NOT_ARCHIVE', 0)} | Retrieve valid archive bytes or a verified Wayback copy |",
        f"| E2: official archive has no NIFTY-200 member file | {counts.get('A_ARCHIVE_WITHOUT_NIFTY200_MEMBER', 0)} | Obtain an official NIFTY-200 member checkpoint; do not treat other index files as a substitute |",
        "", "The May 2012 archive response remains an HTML download failure. The May 2012",
        "press release is event evidence, not a full historical checkpoint. The five",
        "later May archives are valid official archives, but their members are for other",
        "indices and do not contain a NIFTY-200 constituent file.",
        "The current evidence does not justify governance Model B or an override.",
        "Keep validation BLOCKED until the anchor and checkpoint chain is closed.",
    ]
    text = "\n".join(lines) + "\n"
    (root / "reports" / "nifty200_pit_checkpoint_governance_recommendation.md").write_text(text, encoding="utf-8")
    (root / "reports" / "nifty200_pit_monthly_checkpoint_governance_decision.md").write_text(text.replace("Recommendation", "Decision"), encoding="utf-8")


def _write_anchor_report(root: Path, validation: dict[str, Any]) -> None:
    divergence = _read_csv(root / "artifacts" / "nifty200_pit_v1" / "anchor_replay_first_divergence.csv")
    first = divergence[0] if divergence else {}
    lines = [
        "# NIFTY-200 PIT Anchor Reconstruction — Current", "",
        "The initial historical anchor is not established. The candidate member count",
        "is evidence inventory only and is not promoted to authoritative membership.", "",
        "| Measure | Value |", "| --- | ---: |",
        f"| Candidate anchor members | {_metric(validation, 'anchor_candidate_member_count')} |",
        f"| Reverse event observations | {_metric(validation, 'anchor_reverse_event_count')} |",
        f"| Forward checkpoint date | {_metric(validation, 'anchor_forward_checkpoint_date', '')} |",
        f"| Checkpoint set matches | {_metric(validation, 'anchor_replay_checkpoint_set_matches')} |",
        f"| Checkpoint set mismatches | {_metric(validation, 'anchor_replay_checkpoint_set_mismatches')} |",
        f"| Anchor session not 200 | {_metric(validation, 'anchor_replay_session_not_200')} |",
        f"| Anchor status | {_metric(validation, 'anchor_status', 'UNKNOWN')} |", "",
        f"First replay divergence: {_text(first.get('date')) or 'not available'} ({_text(first.get('count_before')) or 'n/a'} → {_text(first.get('count_after')) or 'n/a'}; expected {_text(first.get('expected_count')) or 'n/a'}).",
        f"First-divergence root cause: {_text(first.get('likely_root_cause')) or 'not available'}.", "",
        "The direct free-evidence search covered official Nifty Indices releases, monthly",
        "archives, NSE security masters, NSE identity-change notices, and Wayback copies.",
        "No complete authoritative 2012-01-02 list was found. B1 remains a search index only.", "",
        "Required closure document: an official full CNX/NIFTY-200 constituent list effective",
        "on or before 2012-01-02, or a complete first-party event chain that reproduces it.",
    ]
    (root / "reports" / "nifty200_pit_anchor_reconstruction_current.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_baseline(report_root: Path) -> dict[str, str]:
    rows = _read_csv(report_root / "nifty200_pit_residual_evidence_baseline_20260919.csv")
    return {row.get("metric", ""): row.get("before", "") for row in rows}


def _source_tier_counts(path: Path) -> Counter[str]:
    return Counter(_text(row.get("source_tier")) for row in _read_parquet_records(path) if row.get("source_tier"))


def _value(baseline: dict[str, str], metric: str, default: Any = 0) -> Any:
    value = baseline.get(metric, default)
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return value


def _write_paid_fallback(report_root: Path, ledger: list[dict[str, str]]) -> None:
    rows: list[dict[str, str]] = []
    for row in ledger:
        blocker_type = row.get("blocker_type", "")
        include = blocker_type in {"MONTHLY_SNAPSHOT_MISSING", "SOURCE_DOWNLOAD_FAILURE", "DUPLICATE_EVENT", *IDENTITY_TYPES, *ANNOUNCEMENT_TYPES}
        if blocker_type == "MISSING_INITIAL_ANCHOR":
            include = row.get("date", "") == "2012-01-02"
        if not include:
            continue
        rows.append({
            "case_id": f"paid-{row.get('blocker_id', '')[:16]}", "blocker_type": blocker_type,
            "company": row.get("company", ""), "symbol": row.get("symbol", ""),
            "effective_date": row.get("date", ""), "required period": row.get("date", "") or "affected checkpoint period",
            "required fields": _missing_evidence(blocker_type), "free sources checked": SEARCHES,
            "reason unresolved": "No exact free A1/A2 evidence was found; B1/fuzzy/current-only evidence cannot be promoted.",
            "minimum paid evidence needed": "Licensed historical exchange/index archive or official response containing the exact requested membership/event/identity fields.",
        })
    _write_csv(report_root / "nifty200_pit_paid_fallback_cases.csv", rows, PAID_COLUMNS)


def generate(root: Path) -> dict[str, Any]:
    artifact_root = root / "artifacts" / "nifty200_pit_v1"
    report_root = root / "reports"
    ledger = _read_csv(artifact_root / "blocker_ledger.csv")
    monthly = _read_csv(report_root / "nifty200_pit_monthly_gap_analysis.csv")
    validation = json.loads((artifact_root / "validation_report.json").read_text(encoding="utf-8"))
    canonical = _read_parquet_records(artifact_root / "events_canonical.parquet")
    identity_rows = [row for row in ledger if row.get("blocker_type") in IDENTITY_TYPES]
    announcement_rows = [row for row in ledger if row.get("blocker_type") in ANNOUNCEMENT_TYPES]

    _write_csv(report_root / "nifty200_pit_identity_blocker_cases.csv", [_case_row(row, "identity") for row in identity_rows], CASE_COLUMNS)
    _write_csv(report_root / "nifty200_pit_announcement_blocker_cases.csv", [_case_row(row, "announcement") for row in announcement_rows], CASE_COLUMNS)
    _write_csv(report_root / "nifty200_pit_evidence_gap_report.csv", [_case_row(row, "gap") for row in ledger], CASE_COLUMNS)
    _write_csv(report_root / "nifty200_pit_residual_identity_cases.csv", [_identity_case(row, canonical) for row in identity_rows], IDENTITY_COLUMNS)
    _write_csv(report_root / "nifty200_pit_residual_announcement_cases.csv", [_announcement_case(row, canonical) for row in announcement_rows], ANNOUNCEMENT_COLUMNS)
    _write_paid_fallback(report_root, ledger)
    _write_monthly_governance(root, monthly)
    _write_anchor_report(root, validation)

    blocker_counts = Counter(row.get("blocker_type", "OTHER") for row in ledger)
    baseline = _load_baseline(report_root)
    source_tiers = _source_tier_counts(artifact_root / "source_catalogue.parquet")
    source_failures = [row for row in ledger if row.get("blocker_type") == "SOURCE_DOWNLOAD_FAILURE"]
    duplicate_rows = [row for row in ledger if row.get("blocker_type") == "DUPLICATE_EVENT"]
    current = {
        "source_count": _metric(validation, "source_count"), "source_hash_error_count": _metric(validation, "source_hash_error_count"),
        "event_observation_count": _metric(validation, "event_observation_count"), "canonical_event_count": _metric(validation, "canonical_event_count"),
        "add_event_count": _metric(validation, "add_event_count"), "drop_event_count": _metric(validation, "drop_event_count"),
        "snapshot_row_count": _metric(validation, "snapshot_row_count"), "snapshot_date_count": _metric(validation, "snapshot_date_count"),
        "valid_200_checkpoints": _metric(validation, "valid_200_checkpoints"), "missing_or_non_200_checkpoints": _metric(validation, "missing_or_non_200_checkpoints"),
        "current_security_master_rows": _metric(validation, "current_security_master_rows"), "historical_identity_rows": _metric(validation, "historical_identity_rows"),
        "unique_historical_instruments": _metric(validation, "unique_historical_instruments"), "durable_id_resolution_pct": _metric(validation, "durable_id_resolution_percent", _metric(validation, "durable_id_resolution_pct")),
        "isin_resolution_pct": _metric(validation, "isin_resolution_percent", _metric(validation, "isin_resolution_pct")), "unresolved_identity_count": _metric(validation, "unresolved_identity_count"),
        "interval_count": _metric(validation, "interval_count"), "trading_days_checked": _metric(validation, "trading_days_checked"),
        "minimum_active_constituent_count": _metric(validation, "minimum_active_constituent_count"), "maximum_active_constituent_count": _metric(validation, "maximum_active_constituent_count"),
        "sessions_not_expected_count": _metric(validation, "sessions_not_expected_count"), "known_at_unresolved_count": _metric(validation, "known_at_unresolved_count"),
        "conflict_count": _metric(validation, "conflict_count"), "high_conflict_count": _metric(validation, "high_conflict_count"), "critical_conflict_count": _metric(validation, "critical_conflict_count"),
        "status": validation.get("status", "UNKNOWN"),
    }
    reportable = IDENTITY_TYPES | ANNOUNCEMENT_TYPES | {"MISSING_INITIAL_ANCHOR", "MONTHLY_SNAPSHOT_MISSING", "SOURCE_DOWNLOAD_FAILURE", "DUPLICATE_EVENT"}
    summary_rows: list[dict[str, Any]] = []
    for blocker_type in sorted(reportable & (set(baseline) | set(blocker_counts))):
        before = _value(baseline, blocker_type, 0)
        after = blocker_counts.get(blocker_type, 0)
        summary_rows.append({"metric": blocker_type, "before": before, "after": after, "delta": after - before, "status": "REMAINING" if after else "CLOSED", "evidence_basis": "measured blocker ledger counts", "notes": "Remaining rows stay fail-closed and require exact A1/A2 evidence."})
    before_total = _value(baseline, "TOTAL_BLOCKER_ROWS", 0)
    summary_rows.extend([
        {"metric": "TOTAL_BLOCKER_ROWS", "before": before_total, "after": len(ledger), "delta": len(ledger) - before_total, "status": "REMAINING" if ledger else "CLOSED", "evidence_basis": "measured blocker ledger counts", "notes": "Parser closure reduced rows; no unresolved row was suppressed."},
        {"metric": "CONFLICT_ROWS", "before": _value(baseline, "conflict_count", 0), "after": current["conflict_count"], "delta": current["conflict_count"] - _value(baseline, "conflict_count", 0), "status": "REMAINING" if current["conflict_count"] else "CLOSED", "evidence_basis": "measured validation metrics", "notes": "Parser correction changed the conflict set; conflicts remain visible."},
    ])
    _write_csv(report_root / "nifty200_pit_evidence_resolution_summary.csv", summary_rows, ["metric", "before", "after", "delta", "status", "evidence_basis", "notes"])

    lines = [
        "# NIFTY-200 PIT Residual Evidence Closure", "", "## Scope and safety", "",
        "This report is generated from the latest full real-data build. It does not create historical members, promote B1 evidence, certify fuzzy identity matches, weaken validation, run Stage A, or import into DuckDB.", "",
        "The pre-fix residual baseline is recorded in `reports/nifty200_pit_residual_evidence_baseline_20260919.md`.", "", "## Before → after blocker counts", "", "| Blocker | Before | After | Delta |", "| --- | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(f"| {row['metric']} | {row['before']} | {row['after']} | {row['delta']} |")
    lines.extend(["", "## Current measured build", "", "| Measure | Value |", "| --- | ---: |"])
    labels = (
        ("Source count", "source_count"), ("Source hash failures", "source_hash_error_count"), ("Event observations", "event_observation_count"),
        ("Canonical events", "canonical_event_count"), ("ADD events", "add_event_count"), ("DROP events", "drop_event_count"),
        ("Snapshot rows", "snapshot_row_count"), ("Snapshot dates", "snapshot_date_count"), ("Valid 200 checkpoints", "valid_200_checkpoints"),
        ("Missing/non-200 checkpoints", "missing_or_non_200_checkpoints"), ("Current security-master rows", "current_security_master_rows"),
        ("Historical identity rows", "historical_identity_rows"), ("Unique historical instruments", "unique_historical_instruments"),
        ("Durable-ID resolution %", "durable_id_resolution_pct"), ("ISIN resolution %", "isin_resolution_pct"), ("Unresolved identity count", "unresolved_identity_count"),
        ("Constituent intervals", "interval_count"), ("Trading sessions checked", "trading_days_checked"), ("Minimum active constituents", "minimum_active_constituent_count"),
        ("Maximum active constituents", "maximum_active_constituent_count"), ("Sessions not expected", "sessions_not_expected_count"), ("Known-at unresolved", "known_at_unresolved_count"),
        ("Conflicts", "conflict_count"), ("HIGH conflicts", "high_conflict_count"), ("CRITICAL conflicts", "critical_conflict_count"),
    )
    lines.extend(f"| {label} | {current[key]} |" for label, key in labels)
    lines.extend([
        "", "## Evidence-resolution results", "",
        "The parser defect was fixed for official multi-page NIFTY-200 press-release tables, including wrapped rows and a continuation page that restarts numbering for the next action table. Official 2016/2020 rows now enter the canonical chain. No B1 row was promoted.", "",
        f"Source tiers: A1={source_tiers.get('A1', 0)}, A2={source_tiers.get('A2', 0)}, B1={source_tiers.get('B1', 0)}. No new source tier or non-authoritative promotion was introduced by this pass.",
        f"Announcement blockers: {_value(baseline, 'MISSING_ANNOUNCEMENT_DATE', 0)} → {len(announcement_rows)}.",
        f"Identity blockers: {_value(baseline, 'MISSING_DURABLE_IDENTITY', 0)} → {len(identity_rows)}.",
        f"Residual identity cases: {len(identity_rows)}.", f"Residual announcement cases: {len(announcement_rows)}.", f"Non-passing monthly checkpoint rows: {len([row for row in monthly if row.get('status') != 'PASS'])}.",
        "The source-download failure, duplicate OFSS event, initial anchor, and monthly checkpoint gaps remain explicitly unresolved where no free exact A1/A2 evidence closes them.", "", "## Final blockers", "",
    ])
    if source_failures:
        lines.append("Source download failures retained: " + "; ".join(_text(row.get("source_url")) for row in source_failures) + ".")
    if duplicate_rows:
        lines.append("Duplicate events retained for manual review: " + "; ".join(f"{row.get('date')} {row.get('symbol')}" for row in duplicate_rows) + ".")
    lines.extend(f"- `{key}`: {value} rows" for key, value in sorted(blocker_counts.items()))
    lines.extend(["", "## Final status", "", "NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED", "", "INDEPENDENT QA: NOT ASSERTED", "", "CAMPAIGN STAGE A: BLOCKED"])
    report_text = "\n".join(lines) + "\n"
    (report_root / "nifty200_pit_residual_evidence_closure.md").write_text(report_text, encoding="utf-8")
    (report_root / "nifty200_pit_evidence_closure_current.md").write_text(report_text, encoding="utf-8")
    return {"identity_cases": len(identity_rows), "announcement_cases": len(announcement_rows), "monthly_non_passing": len([row for row in monthly if row.get("status") != "PASS"]), "blocker_rows": len(ledger), "validation_status": current["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(generate(args.root.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
