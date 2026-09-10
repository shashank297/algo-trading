"""Build non-authoritative NIFTY-200 PIT evidence artifacts from public files.

This command is deliberately fail-closed. It harvests and parses real source
bytes, but it does not invent ISINs, instrument IDs, historical constituents,
or publication timestamps. The output can therefore be useful while still
remaining blocked until identity and causality gaps are independently closed.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from typing import Any

from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.manifest import write_artifacts
from tools.nifty200_pit.models import Action, Conflict, Observation, SourceRecord
from tools.nifty200_pit.parse_pdf import (
    extract_pdf_pages,
    find_document_date,
    parse_nifty200_text,
)
from tools.nifty200_pit.reconciliation import reconcile_observations
from tools.nifty200_pit.source_catalogue import sha256_file
from tools.nifty200_pit.validation import validate_campaign, verify_source_hashes

CAMPAIGN_FROM = date(2012, 1, 2)
CAMPAIGN_TO = date(2026, 8, 20)
CHALLENGER_EVENTS_URL = "https://raw.githubusercontent.com/deshpanda/nse-screener-data/main/reconstitution/events.parquet"
CHALLENGER_EVENTS_ARCHIVE_URL = "https://github.com/deshpanda/nse-screener-data/blob/main/reconstitution/events.parquet"
CHALLENGER_EVENTS_PATH = Path(
    "data/raw/nifty200_pit_public_sources/challengers/"
    "deshpanda_nse_screener_reconstitution_events.parquet"
)
RAW_RELATIVE_MARKER = re.compile(r"(?:^|[\\/])(data[\\/]raw[\\/].*)$", re.I)
MONTH_NAME = {name.lower(): number for number, name in enumerate(
    ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
) if name}


def _normalise_local_path(root: Path, value: str) -> Path:
    raw = value.replace("\\", "/")
    match = RAW_RELATIVE_MARKER.search(raw)
    if match:
        return root / Path(match.group(1))
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def load_legacy_sources(root: Path) -> list[SourceRecord]:
    """Convert the existing source manifest into verified source records."""
    manifest = root / "data/raw/nifty200_pit_public_sources/source_manifest.csv"
    records: list[SourceRecord] = []
    seen: set[tuple[str, str]] = set()
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            path = _normalise_local_path(root, row["local_path"])
            key = (row["source_url"], row["sha256"])
            if key in seen:
                continue
            seen.add(key)
            records.append(SourceRecord(
                source_url=row["source_url"], original_url=row["source_url"],
                local_path=str(path), source_sha256=row["sha256"],
                retrieved_at=row["downloaded_at"], content_type=row["content_type"],
                status=row["status"], document_date=row["document_date"] or None,
                source_tier="A1", file_size=int(row["file_size"] or 0),
            ))
    return records


def load_challenger_sources(root: Path) -> list[SourceRecord]:
    """Register downloaded B1 evidence without promoting it to authority."""
    path = root / CHALLENGER_EVENTS_PATH
    if not path.is_file():
        return []
    return [SourceRecord(
        source_url=CHALLENGER_EVENTS_URL,
        original_url=CHALLENGER_EVENTS_URL,
        archive_url=CHALLENGER_EVENTS_ARCHIVE_URL,
        local_path=str(path),
        source_sha256=sha256_file(path),
        retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        content_type="application/vnd.apache.parquet",
        status="downloaded",
        source_tier="B1",
        file_size=path.stat().st_size,
    )]


def _parse_day(value: object) -> date | None:
    if value is None or str(value).strip() in {"", "nan", "NaT"}:
        return None
    if hasattr(value, "date"):
        try:
            return value.date()
        except (TypeError, ValueError):
            pass
    value = str(value).strip().replace(".", "/")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_workbook_events(root: Path, source: SourceRecord) -> list[Observation]:
    """Read official workbook events without treating event date as publication."""
    import pandas as pd

    frame = pd.read_excel(source.local_path, sheet_name="Nifty 200", header=0)
    rows: list[Observation] = []
    for raw in frame.to_dict(orient="records"):
        effective = _parse_day(raw.get("Event Date"))
        name = str(raw.get("Scrip Name") or "").strip()
        description = str(raw.get("Description") or "").strip().lower()
        if not effective or not name or effective < CAMPAIGN_FROM or effective > CAMPAIGN_TO:
            continue
        action = Action.ADD if "inclusion" in description else Action.DROP if "exclusion" in description else None
        if action is None:
            continue
        rows.append(Observation(
            source_index_name="NIFTY 200", company_name=name, effective_date=effective,
            action=action, reason="OFFICIAL_WORKBOOK_EVENT_DATE_ONLY",
            source_url=source.source_url, source_sha256=source.source_sha256,
            source_tier="A1", extraction_method="OFFICIAL_XLS", extractor_version="nifty200-pit-builder-v1",
            confidence="UNRESOLVED", review_status="MANUAL_REVIEW",
            raw_text=json.dumps(raw, default=str, sort_keys=True),
        ))
    return rows


def parse_press_releases(records: list[SourceRecord]) -> list[Observation]:
    observations: list[Observation] = []
    for source in records:
        if not source.local_path.lower().endswith(".pdf") or "Press_Release" not in source.source_url:
            continue
        pages = extract_pdf_pages(source.local_path)
        for page_number, page_text in enumerate(pages, start=1):
            if not re.search(r"\b(?:NIFTY|CNX)\s*[- ]?200\b", page_text, re.I):
                continue
            announcement = find_document_date(source.source_url, page_text)
            observations.extend(parse_nifty200_text(
                page_text, source_url=source.source_url, source_sha256=source.source_sha256,
                announcement_date=announcement, source_page=page_number, source_tier="A1",
                extractor_version="nifty200-pit-parser-v2",
            ))
    return observations


def parse_challenger_events(source: SourceRecord) -> list[Observation]:
    """Load traceable public reconstruction rows as unresolved B1 candidates."""
    import pandas as pd

    frame = pd.read_parquet(source.local_path)
    required = {"announce", "effective", "index", "action", "symbol", "company", "pdf"}
    if not required.issubset(frame.columns):
        return []
    index = frame["index"].astype("string").str.strip().str.casefold()
    selected = frame[index.isin({"nifty 200", "nifty 200 index"})].copy()
    selected["announce"] = pd.to_datetime(selected["announce"], errors="coerce").dt.date
    selected["effective"] = pd.to_datetime(selected["effective"], errors="coerce").dt.date
    selected["action"] = selected["action"].astype("string").str.strip().str.casefold()
    selected["symbol"] = selected["symbol"].astype("string").str.strip()
    selected = selected[
        selected["action"].isin({"add", "drop"})
        & selected["announce"].notna()
        & selected["effective"].notna()
        & selected["symbol"].notna()
        & ~selected["symbol"].str.casefold().isin({"isin", "sr. no.", "security"})
        & (selected["effective"] >= CAMPAIGN_FROM)
        & (selected["effective"] <= CAMPAIGN_TO)
    ]
    observations: list[Observation] = []
    for row in selected.itertuples(index=False):
        action = Action.ADD if row.action == "add" else Action.DROP
        observations.append(Observation(
            source_index_name=str(row.index),
            symbol=str(row.symbol),
            company_name=str(row.company) if pd.notna(row.company) else None,
            announcement_date=row.announce,
            effective_date=row.effective,
            action=action,
            reason="B1_PUBLIC_RECONSTRUCTION_CANDIDATE",
            source_url=source.source_url,
            archive_url=source.archive_url,
            source_sha256=source.source_sha256,
            source_tier="B1",
            extraction_method="B1_PARQUET",
            extractor_version="nifty200-pit-builder-v2",
            confidence="PROVISIONAL",
            review_status="UNRESOLVED",
            raw_text=json.dumps({
                "index": row.index, "action": row.action, "symbol": row.symbol,
                "company": row.company, "announce": str(row.announce),
                "effective": str(row.effective), "pdf": row.pdf,
            }, sort_keys=True, default=str),
        ))
    return observations


def _snapshot_date(text: str, fallback: date | None) -> date | None:
    match = re.search(r"(?:CNX|NIFTY)\s*[- ]?200\s*\n?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", text, re.I)
    if match:
        value = match.group(1).replace(",", "")
        try:
            return datetime.strptime(value, "%B %d %Y").date()
        except ValueError:
            pass
    return fallback


def _zip_month(value: str) -> date | None:
    match = re.search(r"indices_data([A-Za-z]+)(\d{4})", value, re.I)
    if not match:
        return None
    month = MONTH_NAME.get(match.group(1).lower())
    return date(int(match.group(2)), month, 1) if month else None


def _pdf_snapshot_rows(data: bytes, source: SourceRecord, member: str) -> list[dict[str, Any]]:
    pages = extract_pdf_pages(data)
    full_text = "\n".join(pages)
    snapshot_date = _snapshot_date(full_text, None)
    if snapshot_date is None:
        return []
    rows: list[dict[str, Any]] = []
    for page_number, page in enumerate(pages, start=1):
        pending: tuple[str, int] | None = None
        pending_lines: list[str] = []

        def emit() -> None:
            if pending is None or not any(re.search(r"\d+\.\d+", value) for value in pending_lines):
                return
            rows.append({
                "snapshot_date": snapshot_date.isoformat(), "index_id": "NIFTY_200",
                "symbol": pending[0], "company_name": None,
                "source_url": source.source_url, "source_sha256": source.source_sha256,
                "source_member": member, "source_page": pending[1],
                "evidence_type": "OFFICIAL_MONTHLY_WEIGHTAGE_PDF", "source_tier": "A1",
                "raw_text": " ".join(pending_lines),
            })

        for raw_line in page.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            match = re.match(r"^([A-Z][A-Z0-9&.-]{1,19})\s+(.+)$", line)
            symbol = match.group(1) if match and match.group(1) not in {
                "SYMBOL", "SECURITY", "INDEX", "WEIGHTAGE", "CONSTITUENTS", "NIFTY", "CNX"
            } else None
            if symbol:
                emit()
                pending = (symbol, page_number)
                pending_lines = [line]
            elif pending is not None:
                pending_lines.append(line)
        emit()
    return rows


def _csv_snapshot_rows(data: bytes, source: SourceRecord, member: str, fallback: date | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = data.decode("latin1", errors="replace")
    for fields in csv.reader(text.splitlines()):
        if len(fields) < 4 or "200" not in fields[1].upper():
            continue
        snapshot_date = _parse_day(fields[0]) or fallback
        if snapshot_date is None:
            continue
        rows.append({
            "snapshot_date": snapshot_date.isoformat(), "index_id": "NIFTY_200",
            "symbol": fields[2].strip() or None, "company_name": fields[3].strip() or None,
            "source_url": source.source_url, "source_sha256": source.source_sha256,
            "source_member": member, "source_page": None,
            "evidence_type": "OFFICIAL_MONTHLY_WEIGHTAGE_CSV", "source_tier": "A1",
            "raw_text": ",".join(fields[:4]),
        })
    return rows


def parse_monthly_snapshots(records: list[SourceRecord]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for source in records:
        if not source.source_url.lower().endswith(".zip"):
            continue
        try:
            archive = zipfile.ZipFile(source.local_path)
        except (OSError, zipfile.BadZipFile):
            continue
        with archive:
            fallback = _zip_month(source.source_url)
            for member in archive.namelist():
                if "200" not in member.upper() or member.endswith("/"):
                    continue
                data = archive.read(member)
                if member.lower().endswith(".pdf"):
                    snapshots.extend(_pdf_snapshot_rows(data, source, member))
                elif member.lower().endswith((".csv", ".txt")):
                    snapshots.extend(_csv_snapshot_rows(data, source, member, fallback))
    return snapshots


def _identity_aliases(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create review candidates only; no row receives an invented durable ID."""
    candidates: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        item = candidates.setdefault(symbol, {
            "instrument_id": None, "isin": None, "alias_symbol": symbol,
            "company_name": row.get("company_name"), "valid_from": row["snapshot_date"],
            "valid_until": None, "confidence": "UNRESOLVED", "resolution_status": "MANUAL_REVIEW",
            "source_url": row["source_url"], "source_sha256": row["source_sha256"],
        })
        if not item.get("company_name") and row.get("company_name"):
            item["company_name"] = row["company_name"]
    return sorted(candidates.values(), key=lambda row: row["alias_symbol"])


def _write_json(path: Path, rows: Any) -> None:
    def serialise(value: Any) -> Any:
        if hasattr(value, "to_dict"):
            return serialise(value.to_dict())
        if isinstance(value, list):
            return [serialise(item) for item in value]
        if isinstance(value, dict):
            return {key: serialise(item) for key, item in value.items()}
        return value
    path.write_text(json.dumps(serialise(rows), indent=2, default=str), encoding="utf-8")


def _coverage(snapshots: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_month: dict[str, set[str]] = {}
    for row in snapshots:
        month = str(row["snapshot_date"])[:7]
        by_month.setdefault(month, set()).add(str(row.get("symbol") or ""))
    result: list[dict[str, str]] = []
    cursor = date(CAMPAIGN_FROM.year, CAMPAIGN_FROM.month, 1)
    end = date(CAMPAIGN_TO.year, CAMPAIGN_TO.month, 1)
    while cursor <= end:
        key = cursor.isoformat()[:7]
        count = len(by_month.get(key, set()) - {""})
        result.append({
            "period": key, "evidence_type": "OFFICIAL_MONTHLY_WEIGHTAGE",
            "snapshot_member_count": str(count),
            "status": "PASS" if count == 200 else "BLOCKED",
            "qa_note": "verified symbol count" if count == 200 else "missing or non-200 official checkpoint",
        })
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return result


def _annual_coverage(coverage: list[dict[str, str]]) -> list[dict[str, str]]:
    by_year: dict[str, list[dict[str, str]]] = {}
    for row in coverage:
        by_year.setdefault(row["period"][:4], []).append(row)
    return [{
        "year": year, "months_expected": str(len(rows)),
        "months_with_200_members": str(sum(row["status"] == "PASS" for row in rows)),
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "BLOCKED",
        "qa_note": "year has complete 200-member monthly checkpoints" if all(row["status"] == "PASS" for row in rows)
        else "year contains missing or non-200 checkpoints",
    } for year, rows in sorted(by_year.items())]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(root: str | Path = ".") -> dict[str, Any]:
    root = Path(root).resolve()
    derived = root / "data/derived/nifty200_pit"
    artifact_dir = root / "artifacts/nifty200_pit_v1"
    derived.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    sources = load_legacy_sources(root) + load_challenger_sources(root)
    source_errors = verify_source_hashes(sources)
    workbook = next((source for source in sources if source.source_url.endswith("IndexInclExcl.xls")), None)
    observations = parse_workbook_events(root, workbook) if workbook else []
    observations.extend(parse_press_releases(sources))
    challenger = next((source for source in sources if source.source_url == CHALLENGER_EVENTS_URL), None)
    if challenger:
        observations.extend(parse_challenger_events(challenger))
    snapshots = parse_monthly_snapshots(sources)
    aliases = _identity_aliases(snapshots)

    reconciliation = reconcile_observations(observations)
    interval_result = build_intervals(reconciliation.events, horizon_start=CAMPAIGN_FROM, horizon_end=CAMPAIGN_TO)
    conflicts = reconciliation.conflicts + interval_result.conflicts
    coverage = _coverage(snapshots)
    annual_coverage = _annual_coverage(coverage)
    coverage_gaps = [row for row in coverage if row["status"] != "PASS"]
    anchor_differences = [
        f"{row['period']}:{row['snapshot_member_count']}" for row in coverage if row["status"] != "PASS"
    ]
    if not reconciliation.events:
        conflicts.append(Conflict(
            conflict_id="no_certifiable_events", date=None, severity="HIGH",
            conflict_type="NO_CERTIFIABLE_EVENTS",
            message="All parsed event assertions lack durable instrument identity and/or publication causality.",
            required_action="MANUAL_REVIEW",
        ))
    if coverage_gaps:
        conflicts.append(Conflict(
            conflict_id="monthly_coverage_gaps", date=None, severity="HIGH",
            conflict_type="COVERAGE_GAP",
            message=f"{len(coverage_gaps)} campaign months lack a verified 200-member official checkpoint.",
            required_action="SOURCE_RETRIEVAL_OR_MANUAL_REVIEW",
        ))
    report = validate_campaign(
        interval_result.intervals, reconciliation.events, campaign_from=CAMPAIGN_FROM, campaign_to=CAMPAIGN_TO,
        conflicts=conflicts, source_hash_errors=source_errors, anchor_differences=anchor_differences,
    )
    _write_json(root / "data/raw/nifty200_pit_public_sources/source_catalogue.json", [row.to_dict() for row in sources])
    _write_json(derived / "event_observations.json", observations)
    _write_json(derived / "events_canonical.json", reconciliation.events)
    _write_json(derived / "constituent_intervals.json", interval_result.intervals)
    _write_json(derived / "conflicts.json", [row.to_dict() for row in conflicts])
    _write_json(derived / "monthly_snapshots.json", snapshots)
    _write_csv(derived / "coverage_matrix_2012_2026.csv", coverage)
    _write_csv(derived / "coverage_matrix_by_year.csv", annual_coverage)
    _write_csv(derived / "unresolved_gaps.csv", coverage_gaps)
    _write_json(derived / "validation_report.json", report.to_dict())

    discrepancy_rows = []
    by_date: dict[str, set[str]] = {}
    for row in snapshots:
        by_date.setdefault(str(row["snapshot_date"]), set()).add(str(row.get("symbol") or ""))
    for snapshot_date, symbols in sorted(by_date.items()):
        unique_symbols = len(symbols - {""})
        discrepancy_rows.append({
            "snapshot_date": snapshot_date, "observed_member_count": unique_symbols,
            "expected_member_count": 200, "discrepancy": unique_symbols - 200,
            "status": "PASS" if unique_symbols == 200 else "BLOCKED",
            "note": "source checkpoint count differs from required 200" if unique_symbols != 200 else "",
        })
    source_contact_rows = [{
        "source_url": source.source_url, "source_tier": source.source_tier, "status": source.status,
        "local_path": source.local_path, "hash_status": "PASS" if source.source_sha256 not in {
            error.split(":", 1)[-1] for error in source_errors
        } else "BLOCKED", "file_size": source.file_size,
    } for source in sources]
    _write_csv(artifact_dir / "coverage_matrix_2012_2026.csv", coverage)
    _write_csv(artifact_dir / "coverage_matrix_by_year.csv", annual_coverage)
    _write_csv(artifact_dir / "unresolved_gaps.csv", coverage_gaps)
    _write_csv(artifact_dir / "discrepancy_report.csv", discrepancy_rows)
    _write_csv(artifact_dir / "source_access_report.csv", source_contact_rows)
    (artifact_dir / "evidence_report.md").write_text(
        "# NIFTY-200 PIT public evidence build\n\n"
        "## Scope and safety\n\n"
        f"This build covers {CAMPAIGN_FROM} through {CAMPAIGN_TO}. It parses cached official NSE/Nifty Indices evidence "
        "and a separately labelled non-authoritative B1 public reconstruction challenger; "
        "it does not alter `market_data.duckdb`, import authoritative rows, start Stage A, or enable trading. "
        "Independent QA remains `NOT_ASSERTED`.\n\n"
        "## Evidence sources\n\n"
        "- [Nifty 200 official index page](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-200)\n"
        "- [Nifty Indices reports](https://www.niftyindices.com/reports)\n"
        "- [Monthly reports](https://niftyindices.com/reports/monthly-reports)\n"
        "- [Nifty rebalancing schedule](https://www.niftyindices.com/resources/index-rebalancing-schedule)\n"
        "- [NSE equity market-data downloads](https://www.nseindia.com/static/products-services/equity-market-data-reports-download)\n\n"
        f"- [B1 challenger event reconstruction]({CHALLENGER_EVENTS_ARCHIVE_URL})\n\n"
        "## Results\n\n"
        f"- Source records: {len(sources)}; source hash errors: {len(source_errors)}.\n"
        f"- Source tiers: A1={sum(source.source_tier == 'A1' for source in sources)}, "
        f"B1={sum(source.source_tier == 'B1' for source in sources)}.\n"
        f"- Event observations: {len(observations)}; canonical events: {len(reconciliation.events)}.\n"
        f"- Monthly snapshot rows: {len(snapshots)} across {len(by_date)} checkpoints.\n"
        f"- Durable identity mappings: 0 certified; symbol rows remain manual-review candidates.\n"
        f"- Coverage gaps or non-200 checkpoints: {len(coverage_gaps)} campaign months.\n"
        f"- Automated validation: **{report.status.value}**.\n\n"
        "The package is intentionally blocked because the available evidence does not yet provide a complete, causally timestamped, "
        "durable-identity reconstruction for every campaign day. No synthetic initial membership or fabricated ISIN was created.\n",
        encoding="utf-8",
    )

    write_artifacts(
        artifact_dir, source_records=sources, observations=observations, events=reconciliation.events,
        aliases=aliases, intervals=interval_result.intervals, monthly_snapshots=snapshots,
        conflicts=conflicts, validation_report=report,
    )
    dry_run = subprocess.run(
        [sys.executable, str(root / "tools/import_nifty200_pit.py"),
         "--input", str(artifact_dir / "constituent_intervals.parquet"),
         "--manifest", str(artifact_dir / "evidence_manifest.json"), "--dry-run"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    (artifact_dir / "dry_run_import_result.json").write_text(json.dumps({
        "command": "tools/import_nifty200_pit.py --dry-run", "exit_code": dry_run.returncode,
        "stdout": dry_run.stdout, "stderr": dry_run.stderr,
        "database_touched": False, "result": "REFUSED_AS_DESIGNED" if dry_run.returncode else "PASSED",
    }, indent=2), encoding="utf-8")
    write_artifacts(
        artifact_dir, source_records=sources, observations=observations, events=reconciliation.events,
        aliases=aliases, intervals=interval_result.intervals, monthly_snapshots=snapshots,
        conflicts=conflicts, validation_report=report,
    )
    return {
        "source_count": len(sources), "source_hash_errors": len(source_errors),
        "observation_count": len(observations), "canonical_event_count": len(reconciliation.events),
        "snapshot_row_count": len(snapshots), "snapshot_dates": len({row["snapshot_date"] for row in snapshots}),
        "interval_count": len(interval_result.intervals), "conflict_count": len(conflicts),
        "coverage_gap_count": len(coverage_gaps), "validation_status": report.status.value,
        "artifact_dir": str(artifact_dir),
    }


def main() -> int:
    result = build_dataset()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
