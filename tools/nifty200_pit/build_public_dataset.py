"""Build non-authoritative NIFTY-200 PIT evidence artifacts from public files.

This command is deliberately fail-closed. It harvests and parses real source
bytes, but it does not invent ISINs, instrument IDs, historical constituents,
or publication timestamps. The output can therefore be useful while still
remaining blocked until identity and causality gaps are independently closed.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from typing import Any

from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.intervals import active_intervals
from tools.nifty200_pit.manifest import write_artifacts, write_table
from tools.nifty200_pit.models import Action, Conflict, Observation, SourceRecord
from tools.nifty200_pit.parse_pdf import (
    extract_pdf_pages,
    find_document_date,
    find_effective_date,
    parse_nifty200_text,
)
from tools.nifty200_pit.reconciliation import reconcile_observations
from tools.nifty200_pit.instrument_resolver import resolve_observations
from tools.nifty200_pit.source_catalogue import sha256_file
from tools.nifty200_pit.validation import validate_campaign, verify_source_hashes
from trading_stack.calendars import build_nse_calendar

CAMPAIGN_FROM = date(2012, 1, 2)
CAMPAIGN_TO = date(2026, 8, 20)
CHALLENGER_EVENTS_URL = "https://raw.githubusercontent.com/deshpanda/nse-screener-data/main/reconstitution/events.parquet"
CHALLENGER_EVENTS_ARCHIVE_URL = "https://github.com/deshpanda/nse-screener-data/blob/main/reconstitution/events.parquet"
CHALLENGER_EVENTS_PATH = Path(
    "data/raw/nifty200_pit_public_sources/challengers/"
    "deshpanda_nse_screener_reconstitution_events.parquet"
)
SECURITIES_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
RAW_RELATIVE_MARKER = re.compile(r"(?:^|[\\/])(data[\\/]raw[\\/].*)$", re.I)
MONTH_NAME = {name.lower(): number for number, name in enumerate(
    ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
) if name}
CHECKPOINT_FORENSICS_FROM = date(2016, 4, 1)
CHECKPOINT_FORENSICS_TO = date(2020, 5, 31)


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


def load_catalogue_sources(root: Path) -> list[SourceRecord]:
    """Load harvested immutable records while preserving the legacy manifest."""
    path = root / "data/raw/nifty200_pit_public_sources/source_catalogue.json"
    if not path.is_file():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    records: list[SourceRecord] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("source_url") or not row.get("source_sha256"):
            continue
        local_path = _normalise_local_path(root, str(row.get("local_path", "")))
        records.append(SourceRecord(
            source_url=str(row["source_url"]), original_url=row.get("original_url") or str(row["source_url"]),
            archive_url=row.get("archive_url"), local_path=str(local_path),
            source_sha256=str(row["source_sha256"]), retrieved_at=str(row.get("retrieved_at", "")),
            content_type=str(row.get("content_type", "")), status=str(row.get("status", "downloaded")),
            document_date=row.get("document_date"), source_tier=str(row.get("source_tier", "A1")),
            http_status=row.get("http_status"), etag=row.get("etag"), last_modified=row.get("last_modified"),
            file_size=int(row.get("file_size", 0) or 0),
        ))
    return records


def load_sources(root: Path) -> list[SourceRecord]:
    records = load_legacy_sources(root) + load_catalogue_sources(root) + load_challenger_sources(root)
    unique: dict[tuple[str, str], SourceRecord] = {}
    for record in records:
        unique.setdefault((record.source_url, record.source_sha256), record)
    return list(unique.values())


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
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%B-%Y", "%B %d, %Y", "%B %d %Y"):
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
        if not source.local_path.lower().endswith(".pdf") or not re.search(r"press[_-]release", source.source_url, re.I):
            continue
        pages = extract_pdf_pages(source.local_path)
        document_effective = find_effective_date("\n".join(pages))
        for page_number, page_text in enumerate(pages, start=1):
            if not re.search(r"\b(?:NIFTY|CNX)\s*[- ]?200\b", page_text, re.I):
                continue
            announcement = find_document_date(source.source_url, page_text)
            effective = find_effective_date(page_text) or document_effective
            observations.extend(parse_nifty200_text(
                page_text, source_url=source.source_url, source_sha256=source.source_sha256,
                announcement_date=announcement, source_page=page_number, source_tier="A1",
                extractor_version="nifty200-pit-parser-v3", effective_date=effective,
            ))
    return observations


def parse_security_master(source: SourceRecord) -> list[dict[str, Any]]:
    """Parse official NSE rows into period-valid identity evidence."""
    with Path(source.local_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"SYMBOL", "NAME OF COMPANY", "DATE OF LISTING", "ISIN NUMBER"}
        if not required.issubset({str(column).strip().upper() for column in reader.fieldnames or []}):
            return []
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for original in reader:
            raw = {str(key).strip().upper(): value for key, value in original.items() if key is not None}
            symbol = str(raw.get("SYMBOL") or "").strip()
            isin = str(raw.get("ISIN NUMBER") or "").strip()
            if not symbol or not isin or isin.casefold() in {"na", "nan"}:
                continue
            key = (symbol.casefold(), isin.casefold())
            if key in seen:
                continue
            seen.add(key)
            listing_date = _parse_day(raw.get("DATE OF LISTING"))
            rows.append({
                "instrument_id": f"NSE-ISIN:{isin}", "isin": isin, "symbol": symbol,
                "company_name": str(raw.get("NAME OF COMPANY") or "").strip() or None,
                "valid_from": listing_date.isoformat() if listing_date else None,
                "valid_until": None, "source_url": source.source_url,
                "source_sha256": source.source_sha256, "source_tier": source.source_tier,
            })
        return rows


def parse_challenger_events(source: SourceRecord) -> list[Observation]:
    """Load traceable public reconstruction rows as unresolved B1 candidates."""
    import pandas as pd

    try:
        frame = pd.read_parquet(source.local_path)
    except ImportError:
        import duckdb

        frame = duckdb.connect().execute(
            "SELECT * FROM read_parquet(?)", [source.local_path]
        ).fetchdf()
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
                "SYMBOL", "SECURITY", "INDEX", "WEIGHTAGE", "CONSTITUENTS", "NIFTY", "CNX",
                "PUBLICATION",
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


def _identity_aliases(snapshots: list[dict[str, Any]], master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine official identities with unresolved snapshot symbol candidates."""
    aliases: dict[tuple[str, str], dict[str, Any]] = {}
    master_symbols: set[str] = set()
    for row in master:
        symbol = str(row["symbol"]).strip()
        master_symbols.add(symbol.casefold())
        aliases[(str(row["instrument_id"]), symbol.casefold())] = {
            **row, "alias_symbol": row["symbol"], "confidence": "CERTIFIED",
            "resolution_status": "ACCEPTED",
        }
    candidates: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        # An exact current-security-master symbol is already represented by the
        # certified row above.  Do not create a second (None, symbol) alias that
        # falsely reports the same current listing as unresolved historical data.
        if symbol.casefold() in master_symbols:
            continue
        item = candidates.setdefault(symbol, {
            "instrument_id": None, "isin": None, "alias_symbol": symbol,
            "company_name": row.get("company_name"), "valid_from": row["snapshot_date"],
            "valid_until": None, "confidence": "UNRESOLVED", "resolution_status": "MANUAL_REVIEW",
            "source_url": row["source_url"], "source_sha256": row["source_sha256"],
        })
        if not item.get("company_name") and row.get("company_name"):
            item["company_name"] = row["company_name"]
    for row in candidates.values():
        key = (str(row["instrument_id"]), str(row["alias_symbol"]).casefold())
        aliases.setdefault(key, row)
    return sorted(aliases.values(), key=lambda row: (str(row.get("alias_symbol", "")), str(row.get("instrument_id", ""))))


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


_BLOCKER_FIELDS = [
    "blocker_id", "blocker_type", "date", "year", "symbol", "company",
    "instrument_id", "isin", "expected_value", "observed_value", "source_tier",
    "source_url", "source_sha256", "severity", "root_cause", "resolution_status",
    "resolution_source", "notes",
]


def _source_by_month(sources: list[SourceRecord]) -> dict[str, SourceRecord]:
    result: dict[str, SourceRecord] = {}
    for source in sources:
        month = _zip_month(source.source_url)
        if month is not None:
            result.setdefault(month.isoformat()[:7], source)
    return result


def _monthly_gap_rows(
    coverage: list[dict[str, str]],
    snapshots: list[dict[str, Any]],
    intervals: list[Any],
    sources: list[SourceRecord],
) -> list[dict[str, Any]]:
    source_by_month = _source_by_month(sources)
    snapshots_by_month: dict[str, list[dict[str, Any]]] = {}
    for row in snapshots:
        snapshots_by_month.setdefault(str(row["snapshot_date"])[:7], []).append(row)
    rows: list[dict[str, Any]] = []
    for item in coverage:
        month = item["period"]
        month_rows = snapshots_by_month.get(month, [])
        source = source_by_month.get(month)
        official_found = bool(month_rows or source)
        checkpoint_date = min((date.fromisoformat(str(row["snapshot_date"])[:10]) for row in month_rows), default=None)
        replay_count = None
        if checkpoint_date is not None:
            replay_count = len({row.instrument_id for row in active_intervals(intervals, checkpoint_date)})
        observed = int(item["snapshot_member_count"])
        if observed == 200:
            status = "PASS"
            action = "none"
        elif not official_found:
            status = "A_NO_SNAPSHOT_EVIDENCE"
            action = "retrieve an official historical checkpoint or record an external evidence gap"
        elif observed == 0:
            status = "E_SOURCE_PRESENT_ZERO_ROWS"
            action = "inspect the downloaded archive member/table and parser output"
        else:
            status = "B_SNAPSHOT_NON_200"
            action = "manual table audit to distinguish parser extraction from methodology/count difference"
        rows.append({
            "month": month,
            "official_snapshot_found": str(official_found).upper(),
            "observed_count": observed,
            "expected_count": 200,
            "source_url": source.source_url if source else (month_rows[0]["source_url"] if month_rows else ""),
            "archive_url": source.archive_url if source else "",
            "source_sha": source.source_sha256 if source else (month_rows[0]["source_sha256"] if month_rows else ""),
            "replay_member_count": replay_count if replay_count is not None else "",
            "snapshot_vs_replay_diff": (replay_count - observed) if replay_count is not None else "",
            "status": status,
            "action_needed": action,
        })
    return rows


def _known_at_rows(events: list[Any]) -> list[dict[str, Any]]:
    return [{
        "instrument_id": event.instrument_id,
        "symbol": event.symbol,
        "action": event.action.value if hasattr(event.action, "value") else event.action,
        "announcement_date": event.announcement_date,
        "publication_timestamp": event.known_at,
        "effective_date": event.effective_date,
        "known_at": event.known_at,
        "known_at_basis": event.known_at_basis,
        "source": event.source_url,
        "review_status": event.review_status.value if hasattr(event.review_status, "value") else event.review_status,
    } for event in events]


def _historical_master_rows(
    instrument_master: list[dict[str, Any]], aliases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = [{
        "instrument_id": row.get("instrument_id"),
        "isin": row.get("isin"),
        "symbol": row.get("symbol"),
        "company_name": row.get("company_name"),
        "valid_from": row.get("valid_from"),
        "valid_until": row.get("valid_until"),
        "identity_event_type": "CURRENT_SECURITY_MASTER_LISTING_ANCHOR",
        "source_url": row.get("source_url"),
        "source_sha256": row.get("source_sha256"),
        "source_tier": row.get("source_tier"),
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
        "predecessor_instrument_id": None,
        "successor_instrument_id": None,
    } for row in instrument_master]
    rows.extend({
        "instrument_id": row.get("instrument_id"),
        "isin": row.get("isin"),
        "symbol": row.get("alias_symbol") or row.get("symbol"),
        "company_name": row.get("company_name"),
        "valid_from": row.get("valid_from"),
        "valid_until": row.get("valid_until"),
        "identity_event_type": "HISTORICAL_ALIAS_UNRESOLVED",
        "source_url": row.get("source_url"),
        "source_sha256": row.get("source_sha256"),
        "source_tier": row.get("source_tier", "A1"),
        "confidence": "MANUAL_REVIEW",
        "review_status": "MANUAL_REVIEW",
        "predecessor_instrument_id": None,
        "successor_instrument_id": None,
    } for row in aliases if row.get("confidence") != "CERTIFIED")
    return rows


def _historical_identity_resolution_rows(
    snapshots: list[dict[str, Any]], aliases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Explain each snapshot-symbol identity decision without fuzzy certification."""
    observed: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        item = observed.setdefault(symbol.casefold(), {
            "symbol": symbol, "company_name": row.get("company_name") or "",
            "first_observed": row.get("snapshot_date"), "last_observed": row.get("snapshot_date"),
            "observation_count": 0, "source_url": row.get("source_url", ""),
            "source_sha256": row.get("source_sha256", ""),
        })
        item["first_observed"] = min(str(item["first_observed"]), str(row.get("snapshot_date")))
        item["last_observed"] = max(str(item["last_observed"]), str(row.get("snapshot_date")))
        item["observation_count"] += 1
        if not item["company_name"] and row.get("company_name"):
            item["company_name"] = row["company_name"]
    result = []
    for alias in aliases:
        symbol = str(alias.get("alias_symbol") or alias.get("symbol") or "")
        item = observed.get(symbol.casefold(), {})
        certified = alias.get("confidence") == "CERTIFIED"
        result.append({
            "symbol": symbol, "company_name": alias.get("company_name") or item.get("company_name", ""),
            "first_observed": item.get("first_observed", alias.get("valid_from", "")),
            "last_observed": item.get("last_observed", ""),
            "observation_count": item.get("observation_count", 0),
            "instrument_id": alias.get("instrument_id") or "", "isin": alias.get("isin") or "",
            "resolution_status": "ACCEPTED_CURRENT_MASTER" if certified else "MANUAL_REVIEW",
            "resolution_method": "EXACT_CURRENT_SYMBOL" if certified else "NO_HISTORICAL_DURABLE_ID_EVIDENCE",
            "confidence": "CERTIFIED" if certified else "MANUAL_REVIEW",
            "root_cause": "Current official NSE security master exact match" if certified else "Historical symbol is absent from the current NSE security master; no first-party historical ISIN mapping was acquired",
            "source_url": alias.get("source_url") or item.get("source_url", ""),
            "source_sha256": alias.get("source_sha256") or item.get("source_sha256", ""),
            "source_tier": alias.get("source_tier", "A1"),
            "review_status": "ACCEPTED" if certified else "MANUAL_REVIEW",
            "notes": "Exact symbol matching only; no fuzzy or successor inference." if not certified else "Current listing evidence is not by itself historical anchor evidence.",
        })
    return sorted(result, key=lambda row: row["symbol"])


def _checkpoint_forensics(
    snapshots: list[dict[str, Any]], sources: list[SourceRecord], instrument_master: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Audit every 201-row official checkpoint and retain row-level evidence."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in snapshots:
        grouped.setdefault(str(row["snapshot_date"])[:7], []).append(row)
    master_by_symbol = {str(row.get("symbol", "")).casefold(): row for row in instrument_master}
    summaries: list[dict[str, Any]] = []
    debug: list[dict[str, Any]] = []
    for month in sorted(grouped):
        checkpoint = date.fromisoformat(month + "-01")
        if not CHECKPOINT_FORENSICS_FROM <= checkpoint <= CHECKPOINT_FORENSICS_TO:
            continue
        rows = grouped[month]
        symbols = [str(row.get("symbol") or "") for row in rows]
        duplicate_symbols = sorted(symbol for symbol, count in Counter(symbols).items() if count > 1 and symbol)
        companies = [str(row.get("company_name") or "").strip() for row in rows if str(row.get("company_name") or "").strip()]
        duplicate_companies = sorted(company for company, count in Counter(companies).items() if count > 1)
        source_file = str(rows[0].get("source_member") or "")
        source = next((item for item in sources if item.source_sha256 == rows[0].get("source_sha256")), None)
        suspect = [row["symbol"] for row in rows if "disclaimer:" in str(row.get("raw_text", "")).casefold()]
        for number, row in enumerate(rows, start=1):
            debug.append({
                "checkpoint_date": row["snapshot_date"], "row_number": number, "symbol": row.get("symbol", ""),
                "raw_text": row.get("raw_text", ""), "source_member": row.get("source_member", ""),
                "source_page": row.get("source_page", ""),
                "suspect_row": "TRUE" if row.get("symbol") in suspect else "FALSE",
                "suspect_reason": "footer disclaimer is attached to final row; constituent token remains valid" if row.get("symbol") in suspect else "",
            })
        unique_isins = {master_by_symbol[symbol.casefold()].get("isin") for symbol in symbols if symbol.casefold() in master_by_symbol}
        summaries.append({
            "checkpoint_date": rows[0]["snapshot_date"], "source_file": source_file,
            "source_url": source.source_url if source else rows[0].get("source_url", ""),
            "source_sha256": rows[0].get("source_sha256", ""), "raw_rows_extracted": len(rows),
            "unique_symbols": len(set(symbols) - {""}), "unique_isins": len({value for value in unique_isins if value}),
            "duplicate_symbols": ";".join(duplicate_symbols), "duplicate_company_names": ";".join(duplicate_companies),
            "suspect_rows": ";".join(suspect),
            "root_cause": "Official checkpoint contains 201 unique constituent rows; no parser-created symbol or duplicate was found. Final-row disclaimer text is attached to ZEEL.",
            "fix_applied": "NONE; retained fail-closed for manual count/methodology review",
            "post_fix_count": len(set(symbols) - {""}), "status": "MANUAL_REVIEW_REQUIRED_SOURCE_COUNT",
        })
    return summaries, debug


def _anchor_candidate_rows(
    snapshots: list[dict[str, Any]], instrument_master: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retain the nearest forward checkpoint as non-authoritative anchor evidence."""
    available = [row for row in snapshots if str(row.get("snapshot_date", "")) >= "2012-01-02"]
    if not available:
        return []
    earliest = min(str(row["snapshot_date"]) for row in available)
    master_by_symbol = {str(row.get("symbol", "")).casefold(): row for row in instrument_master}
    seen: set[str] = set()
    result = []
    for row in available:
        symbol = str(row.get("symbol") or "")
        if str(row["snapshot_date"]) != earliest or symbol in seen:
            continue
        seen.add(symbol)
        master = master_by_symbol.get(symbol.casefold(), {})
        result.append({
            "target_date": CAMPAIGN_FROM.isoformat(), "symbol": row.get("symbol", ""),
            "company_name": row.get("company_name") or "", "instrument_id": master.get("instrument_id") or "",
            "isin": master.get("isin") or "", "anchor_status": "NOT_ASSERTED",
            "eligible_for_replay": False, "evidence_basis": "FORWARD_CHECKPOINT_ONLY",
            "forward_checkpoint_date": row.get("snapshot_date"), "source_url": row.get("source_url", ""),
            "source_sha256": row.get("source_sha256", ""), "source_member": row.get("source_member", ""),
            "source_tier": row.get("source_tier", "A1"), "confidence": "MANUAL_REVIEW",
            "review_status": "MANUAL_REVIEW",
            "notes": "This row is a later official checkpoint member, not evidence of membership on 2012-01-02.",
        })
    return result


def _symbol_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _valid_checkpoint_groups(
    snapshots: list[dict[str, Any]],
) -> list[tuple[date, list[dict[str, Any]]]]:
    grouped: dict[date, list[dict[str, Any]]] = {}
    for row in snapshots:
        try:
            snapshot_date = date.fromisoformat(str(row["snapshot_date"])[:10])
        except (KeyError, TypeError, ValueError):
            continue
        grouped.setdefault(snapshot_date, []).append(row)
    return sorted(
        (snapshot_date, rows) for snapshot_date, rows in grouped.items()
        if len({_symbol_key(row.get("symbol")) for row in rows} - {""}) == 200
    )


def _anchor_replay_forensics(
    snapshots: list[dict[str, Any]],
    events: list[Any],
    instrument_master: list[dict[str, Any]],
    trading_days: list[date],
) -> dict[str, Any]:
    """Measure a later-checkpoint reverse replay without making it authoritative."""
    checkpoints = _valid_checkpoint_groups(snapshots)
    if not checkpoints:
        return {
            "anchor_evidence": [], "candidate_rows": [], "session_rows": [],
            "checkpoint_rows": [], "details": [], "summary": {
                "status": "NOT_ESTABLISHED", "source_checkpoint_date": "",
                "source_checkpoint_count": 0, "candidate_member_count": 0,
                "first_divergence_date": "", "first_divergence_count": "",
            },
        }

    checkpoint_date, checkpoint_rows = checkpoints[0]
    source_by_symbol = {_symbol_key(row.get("symbol")): row for row in checkpoint_rows}
    master_by_symbol = {_symbol_key(row.get("symbol")): row for row in instrument_master}
    state = set(source_by_symbol) - {""}
    reverse_events = [
        (position, event) for position, event in enumerate(events)
        if getattr(event, "effective_date", None) is not None
        and CAMPAIGN_FROM <= event.effective_date <= checkpoint_date
        and _symbol_key(getattr(event, "symbol", ""))
        and str(getattr(event, "action", "")).upper().replace("ACTION.", "") in {"ADD", "DROP"}
    ]
    reverse_events.sort(key=lambda item: (item[1].effective_date, item[0]), reverse=True)
    for _, event in reverse_events:
        symbol = _symbol_key(event.symbol)
        action = event.action.value if hasattr(event.action, "value") else str(event.action)
        if action == Action.ADD.value:
            state.discard(symbol)
        elif action == Action.DROP.value:
            state.add(symbol)

    anchor_evidence = []
    for row in sorted(checkpoint_rows, key=lambda item: _symbol_key(item.get("symbol"))):
        symbol = _symbol_key(row.get("symbol"))
        master = master_by_symbol.get(symbol, {})
        anchor_evidence.append({
            "target_date": CAMPAIGN_FROM.isoformat(), "symbol": row.get("symbol", ""),
            "company_name": row.get("company_name") or "", "instrument_id": master.get("instrument_id") or "",
            "isin": master.get("isin") or "", "anchor_status": "NOT_ASSERTED",
            "eligible_for_replay": False, "evidence_basis": "FORWARD_CHECKPOINT_ONLY",
            "forward_checkpoint_date": checkpoint_date.isoformat(), "source_url": row.get("source_url", ""),
            "source_sha256": row.get("source_sha256", ""), "source_member": row.get("source_member", ""),
            "source_tier": row.get("source_tier", "A1"), "confidence": "MANUAL_REVIEW",
            "review_status": "MANUAL_REVIEW",
            "notes": "Official later checkpoint evidence; not proof of 2012-01-02 membership.",
        })

    candidate_rows = []
    for symbol in sorted(state):
        source = source_by_symbol.get(symbol, {})
        master = master_by_symbol.get(symbol, {})
        candidate_rows.append({
            "target_date": CAMPAIGN_FROM.isoformat(), "symbol": source.get("symbol", symbol),
            "company_name": source.get("company_name") or master.get("company_name") or "",
            "instrument_id": master.get("instrument_id") or "", "isin": master.get("isin") or "",
            "anchor_status": "NOT_ASSERTED", "eligible_for_replay": False,
            "evidence_basis": "REVERSE_CANONICAL_EVENTS_FROM_LATER_CHECKPOINT",
            "forward_checkpoint_date": checkpoint_date.isoformat(),
            "source_url": source.get("source_url", ""), "source_sha256": source.get("source_sha256", ""),
            "source_member": source.get("source_member", ""), "source_tier": source.get("source_tier", "A1"),
            "confidence": "MANUAL_REVIEW", "review_status": "MANUAL_REVIEW",
            "notes": "Diagnostic candidate only; canonical chain is incomplete and this row is not eligible for authoritative replay.",
        })

    events_by_date: dict[date, list[Any]] = {}
    ordered_events = []
    for event in events:
        effective = getattr(event, "effective_date", None)
        if effective is not None and CAMPAIGN_FROM <= effective <= CAMPAIGN_TO:
            events_by_date.setdefault(effective, []).append(event)
            ordered_events.append(event)
    ordered_events.sort(key=lambda event: event.effective_date)
    active = set(state)
    session_rows = []
    state_by_session: dict[date, set[str]] = {}
    event_position = 0
    for session_date in sorted(trading_days):
        while event_position < len(ordered_events) and ordered_events[event_position].effective_date <= session_date:
            event = ordered_events[event_position]
            event_position += 1
            symbol = _symbol_key(getattr(event, "symbol", ""))
            action = event.action.value if hasattr(event.action, "value") else str(event.action)
            if not symbol:
                continue
            if action == Action.ADD.value:
                active.add(symbol)
            elif action == Action.DROP.value:
                active.discard(symbol)
        state_by_session[session_date] = set(active)
        session_rows.append({
            "session_date": session_date.isoformat(), "active_member_count": len(active),
            "expected_member_count": 200, "status": "PASS" if len(active) == 200 else "BLOCKED",
            "candidate_method": "REVERSE_CANONICAL_EVENTS_FROM_LATER_CHECKPOINT",
            "source_checkpoint_date": checkpoint_date.isoformat(),
            "source_checkpoint_sha256": checkpoint_rows[0].get("source_sha256", ""),
            "event_count_applied": sum(len(rows) for day, rows in events_by_date.items() if day <= session_date),
        })

    checkpoint_rows_out = []
    details = []
    for checkpoint, official_rows in checkpoints:
        official = {_symbol_key(row.get("symbol")) for row in official_rows} - {""}
        replay = state_by_session.get(checkpoint)
        if replay is None:
            prior = [day for day in state_by_session if day <= checkpoint]
            replay = state_by_session[max(prior)] if prior else set()
        missing = sorted(official - replay)
        unexpected = sorted(replay - official)
        checkpoint_rows_out.append({
            "checkpoint_date": checkpoint.isoformat(), "official_count": len(official),
            "replay_count": len(replay), "set_match": "PASS" if not missing and not unexpected else "BLOCKED",
            "missing_count": len(missing), "unexpected_count": len(unexpected),
            "identity_mismatch_count": 0, "status": "PASS" if not missing and not unexpected else "BLOCKED",
        })
        for symbol in missing:
            details.append({
                "checkpoint_date": checkpoint.isoformat(), "difference_type": "MISSING_FROM_REPLAY",
                "symbol": symbol, "source_checkpoint_date": checkpoint_date.isoformat(),
                "source_checkpoint_sha256": checkpoint_rows[0].get("source_sha256", ""),
                "resolution_status": "UNRESOLVED_MANUAL_REVIEW",
                "notes": "No authoritative 2012 anchor or complete certified event chain; symbol is in the official checkpoint but absent from diagnostic replay.",
            })
        for symbol in unexpected:
            details.append({
                "checkpoint_date": checkpoint.isoformat(), "difference_type": "UNEXPECTED_IN_REPLAY",
                "symbol": symbol, "source_checkpoint_date": checkpoint_date.isoformat(),
                "source_checkpoint_sha256": checkpoint_rows[0].get("source_sha256", ""),
                "resolution_status": "UNRESOLVED_MANUAL_REVIEW",
                "notes": "Diagnostic reverse replay retains a symbol not present in the official checkpoint.",
            })

    divergence = next((row for row in session_rows if row["active_member_count"] != 200), None)
    divergence_events = []
    if divergence:
        divergence_date = date.fromisoformat(str(divergence["session_date"]))
        divergence_events = [
            f"{event.action.value if hasattr(event.action, 'value') else event.action}:{event.symbol}"
            for event in ordered_events if event.effective_date == divergence_date
        ]
    summary = {
        "status": "NOT_ESTABLISHED", "source_checkpoint_date": checkpoint_date.isoformat(),
        "source_checkpoint_count": len(source_by_symbol), "candidate_member_count": len(candidate_rows),
        "reverse_event_count": len(reverse_events),
        "first_divergence_date": divergence["session_date"] if divergence else "",
        "first_divergence_count": divergence["active_member_count"] if divergence else "",
        "first_divergence_events": ";".join(divergence_events),
        "session_count": len(session_rows),
        "session_exact_200": sum(row["active_member_count"] == 200 for row in session_rows),
        "session_not_200": sum(row["active_member_count"] != 200 for row in session_rows),
        "checkpoint_count": len(checkpoint_rows_out),
        "checkpoint_set_matches": sum(row["set_match"] == "PASS" for row in checkpoint_rows_out),
        "checkpoint_set_mismatches": sum(row["set_match"] != "PASS" for row in checkpoint_rows_out),
        "first_checkpoint_mismatch": next((row["checkpoint_date"] for row in checkpoint_rows_out if row["set_match"] != "PASS"), ""),
    }
    return {
        "anchor_evidence": anchor_evidence, "candidate_rows": candidate_rows,
        "session_rows": session_rows, "checkpoint_rows": checkpoint_rows_out,
        "details": details, "summary": summary,
    }


def _conflict_forensics(
    conflicts: list[Conflict], observations: list[Observation], *, conflict_type: str,
) -> list[dict[str, Any]]:
    """Materialise conflict evidence so each unresolved assertion is reviewable."""
    from tools.nifty200_pit.reconciliation import observation_hash

    by_id = {row.observation_id or observation_hash(row): row for row in observations}
    result = []

    def action_value(observation: Observation | None) -> str:
        if observation is None or observation.action is None:
            return ""
        return observation.action.value if isinstance(observation.action, Action) else str(observation.action)

    for conflict in conflicts:
        if conflict.conflict_type != conflict_type:
            continue
        rows = [by_id[oid] for oid in conflict.observation_ids if oid in by_id]
        first = rows[0] if rows else None
        second = rows[1] if len(rows) > 1 else None
        result.append({
            "conflict_id": conflict.conflict_id, "date": conflict.date.isoformat() if conflict.date else "",
            "symbol": (first.symbol if first else "") or (first.company_name if first else ""),
            "company": first.company_name if first else "", "action_1": action_value(first),
            "action_2": action_value(second),
            "effective_date_1": first.effective_date.isoformat() if first and first.effective_date else "",
            "effective_date_2": second.effective_date.isoformat() if second and second.effective_date else "",
            "source_url_1": first.source_url if first else (conflict.source_urls[0] if conflict.source_urls else ""),
            "source_url_2": second.source_url if second else (conflict.source_urls[1] if len(conflict.source_urls) > 1 else ""),
            "source_sha256_1": first.source_sha256 if first else "", "source_sha256_2": second.source_sha256 if second else "",
            "observation_ids": ";".join(conflict.observation_ids), "severity": conflict.severity,
            "difference": conflict.message, "root_cause": conflict.required_action,
            "correction_applied": "NONE", "resolution_status": "UNRESOLVED_MANUAL_REVIEW",
            "notes": "Duplicate or same-priority assertions remain fail-closed; no row was discarded.",
        })
    return result


def _checkpoint_requirement_audit() -> str:
    return """# NIFTY-200 PIT checkpoint requirement audit

Conclusion: `PERIODIC_CHECKPOINT_SUFFICIENT_PENDING_GOVERNANCE_APPROVAL`

The official launch notice describes CNX 200 periodic review as semi-annual, not a
monthly constituent-publication obligation. The public corpus nevertheless contains
many monthly weightage files, and the current validator requires a 200-member monthly
checkpoint. Those are different claims: the first is index methodology evidence; the
second is this repository's conservative acceptance control. This task does not weaken
that control or silently treat a missing month as PASS.

The 50 checkpoints from April 2016 through May 2020 were inspected at row level. Each
contains 201 unique constituent symbols in the extracted official PDF, with no duplicate
symbol or parser-created header row. Their status remains manual-review because the
repository acceptance rule expects exactly 200 and the source semantics/count discrepancy
cannot be resolved by deleting an apparently valid constituent.

Required governance decision: confirm whether periodic official checkpoints plus complete
causal event lineage are acceptable for the campaign, or retain the monthly/200-member
rule. Until that decision and the 2012-01-02 anchor are supplied, automated validation
remains blocked.

Official methodology reference: <https://niftyindices.com/Press_Release/ind_prs18072011.pdf>
"""


def _blocker_ledger(
    report: Any,
    *,
    conflicts: list[Conflict],
    events: list[Any],
    snapshots: list[dict[str, Any]],
    coverage: list[dict[str, str]],
    sources: list[SourceRecord],
) -> list[dict[str, Any]]:
    source_by_month = _source_by_month(sources)
    snapshot_by_month: dict[str, list[dict[str, Any]]] = {}
    for row in snapshots:
        snapshot_by_month.setdefault(str(row["snapshot_date"])[:7], []).append(row)
    conflict_by_id = {conflict.conflict_id: conflict for conflict in conflicts}
    event_by_hash = {event.event_hash: event for event in events}
    coverage_by_month = {row["period"]: row for row in coverage}
    rows: list[dict[str, Any]] = []

    def append(reason: str, *, blocker_type: str, as_of: str = "", symbol: str = "",
               company: str = "", instrument_id: str = "", isin: str = "",
               expected: Any = "", observed: Any = "", source_tier: str = "",
               source_url: str = "", source_sha: str = "", severity: str = "HIGH",
               root_cause: str = "", resolution_source: str = "", notes: str = "") -> None:
        rows.append({
            "blocker_id": f"{blocker_type}:{as_of}:{len(rows) + 1}",
            "blocker_type": blocker_type, "date": as_of, "year": as_of[:4] if as_of else "",
            "symbol": symbol, "company": company, "instrument_id": instrument_id, "isin": isin,
            "expected_value": expected, "observed_value": observed, "source_tier": source_tier,
            "source_url": source_url, "source_sha256": source_sha, "severity": severity,
            "root_cause": root_cause, "resolution_status": "UNRESOLVED",
            "resolution_source": resolution_source, "notes": notes or reason,
        })

    for reason in report.reasons:
        if reason.startswith("member_count:"):
            _, as_of, observed = reason.split(":", 2)
            append(reason, blocker_type="COUNT_NOT_200", as_of=as_of, expected=200,
                   observed=observed, severity="CRITICAL",
                   root_cause="Replay intervals do not establish 200 durable members on this NSE session.")
            continue
        if reason.startswith("unresolved_conflict:"):
            conflict_id = reason.split(":", 1)[1]
            conflict = conflict_by_id.get(conflict_id)
            if conflict is None:
                event = event_by_hash.get(conflict_id)
                append(reason, blocker_type="OTHER", as_of=event.effective_date.isoformat() if event else "",
                       symbol=event.symbol if event else "", instrument_id=event.instrument_id if event else "",
                       severity="HIGH", root_cause="Validation references an unresolved conflict not present in the structured conflict table.")
                continue
            conflict_type = conflict.conflict_type
            if conflict_type == "UNRESOLVED_OBSERVATION":
                kind = "MISSING_DURABLE_IDENTITY"
            elif conflict_type == "REMOVAL_OF_ABSENT_MEMBER":
                kind = "MISSING_INITIAL_ANCHOR"
            elif conflict_type == "DUPLICATE_ADD":
                kind = "DUPLICATE_EVENT"
            elif "IDENTITY" in conflict_type:
                kind = "HISTORICAL_SYMBOL_CHANGE"
            elif "COVERAGE" in conflict_type:
                kind = "MONTHLY_SNAPSHOT_MISSING"
            elif "OFFICIAL" in conflict_type:
                kind = "CONFLICTING_OFFICIAL_EVENTS"
            else:
                kind = "OTHER"
            append(reason, blocker_type=kind, as_of=conflict.date.isoformat() if conflict.date else "",
                   source_url=";".join(conflict.source_urls), severity=conflict.severity,
                   root_cause=conflict.message, notes=f"conflict_type={conflict_type}; required_action={conflict.required_action}")
            continue
        match = re.fullmatch(r"(\d{4}-\d{2}):(\d+)", reason)
        if match and match.group(1) in coverage_by_month:
            month, observed = match.groups()
            source = source_by_month.get(month)
            month_rows = snapshot_by_month.get(month, [])
            count = int(observed)
            if count == 0 and not source and not month_rows:
                kind = "MONTHLY_SNAPSHOT_MISSING"
                root = "No official monthly checkpoint is present in the acquired corpus."
            elif count == 0:
                kind = "PARSER_FAILURE"
                root = "An official monthly source is present but the parser extracted zero members."
            else:
                kind = "MONTHLY_SNAPSHOT_NOT_200"
                root = "The official checkpoint was parsed but does not establish exactly 200 members."
            snapshot_row = month_rows[0] if month_rows else None
            append(reason, blocker_type=kind, as_of=f"{month}-01", expected=200, observed=count,
                   source_tier=source.source_tier if source else (snapshot_row.get("source_tier", "") if snapshot_row else ""),
                   source_url=source.source_url if source else (snapshot_row.get("source_url", "") if snapshot_row else ""),
                   source_sha=source.source_sha256 if source else (snapshot_row.get("source_sha256", "") if snapshot_row else ""),
                   severity="HIGH", root_cause=root,
                   notes="Status categories A-E are kept separate in the monthly gap analysis.")
            continue
        if reason.startswith("interval_overlap:"):
            append(reason, blocker_type="INTERVAL_OVERLAP", instrument_id=reason.split(":", 1)[1], severity="CRITICAL",
                   root_cause="Two certified intervals overlap for one instrument.")
            continue
        if reason.startswith("missing_instrument_id:"):
            append(reason, blocker_type="MISSING_DURABLE_IDENTITY", severity="CRITICAL",
                   root_cause="Canonical event has no durable instrument identifier.")
            continue
        if reason.startswith("missing_event_causality:"):
            append(reason, blocker_type="KNOWN_AT_UNRESOLVED", severity="CRITICAL",
                   root_cause="Canonical event lacks a complete causality chain.")
            continue
        if reason.startswith("missing_source_sha:") or reason.startswith("missing_source:") or reason.startswith("hash_mismatch:"):
            append(reason, blocker_type="SOURCE_DOWNLOAD_FAILURE", severity="CRITICAL",
                   root_cause="Source bytes cannot be verified against the recorded SHA-256.")
            continue
        if reason.startswith("non_certifiable_interval:"):
            append(reason, blocker_type="MISSING_DURABLE_IDENTITY", severity="CRITICAL",
                   root_cause="Interval is not certified for import.")
            continue
        append(reason, blocker_type="OTHER", severity="HIGH", root_cause="Unclassified validation reason; manual classification required.")
    return rows


def build_dataset(root: str | Path = ".") -> dict[str, Any]:
    root = Path(root).resolve()
    derived = root / "data/derived/nifty200_pit"
    artifact_dir = root / "artifacts/nifty200_pit_v1"
    derived.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    sources = load_sources(root)
    source_errors = verify_source_hashes(sources)
    workbook = next((source for source in sources if source.source_url.endswith("IndexInclExcl.xls")), None)
    observations = parse_workbook_events(root, workbook) if workbook else []
    observations.extend(parse_press_releases(sources))
    challenger = next((source for source in sources if source.source_url == CHALLENGER_EVENTS_URL), None)
    if challenger:
        observations.extend(parse_challenger_events(challenger))
    snapshots = parse_monthly_snapshots(sources)
    security_master = next((source for source in sources if source.source_url == SECURITIES_MASTER_URL), None)
    instrument_master = parse_security_master(security_master) if security_master else []
    aliases = _identity_aliases(snapshots, instrument_master)
    observations = resolve_observations(observations, instrument_master, aliases=aliases)

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
    calendar = build_nse_calendar(verified_through=CAMPAIGN_TO, version="nse-pandas-market-calendars")
    trading_days = calendar.iter_trading_days(CAMPAIGN_FROM, CAMPAIGN_TO)
    anchor_forensics = _anchor_replay_forensics(snapshots, reconciliation.events, instrument_master, trading_days)
    anchor_summary = anchor_forensics["summary"]
    historical_master = _historical_master_rows(instrument_master, aliases)
    report = validate_campaign(
        interval_result.intervals, reconciliation.events, campaign_from=CAMPAIGN_FROM, campaign_to=CAMPAIGN_TO,
        trading_days=trading_days, conflicts=conflicts, source_hash_errors=source_errors,
        anchor_differences=anchor_differences,
    )
    replay_counts = list(report.metrics["daily_member_counts"].values())
    report = replace(report, metrics=report.metrics | {
        "calendar_version": calendar.version,
        "minimum_active_constituent_count": min(replay_counts, default=0),
        "maximum_active_constituent_count": max(replay_counts, default=0),
        "sessions_not_expected_count": sum(value != 200 for value in replay_counts),
        "known_at_unresolved_count": sum(event.known_at is None or not event.known_at_basis for event in reconciliation.events),
        "current_security_master_rows": len(instrument_master),
        "historical_identity_rows": len(historical_master),
        "unique_historical_instruments": len({row.get("instrument_id") for row in instrument_master}),
        "durable_id_resolution_percent": round((sum(row.get("confidence") == "CERTIFIED" for row in aliases) / len(aliases) * 100) if aliases else 0, 4),
        "isin_resolution_percent": round((sum(bool(row.get("isin")) for row in aliases if row.get("confidence") == "CERTIFIED") / len(aliases) * 100) if aliases else 0, 4),
        "unresolved_identity_count": sum(row.get("confidence") != "CERTIFIED" for row in aliases),
        "valid_200_checkpoints": sum(row["status"] == "PASS" for row in coverage),
        "missing_or_non_200_checkpoints": len(coverage_gaps),
        "anchor_status": anchor_summary.get("status", "NOT_ESTABLISHED"),
        "anchor_forward_checkpoint_date": anchor_summary.get("source_checkpoint_date", ""),
        "anchor_candidate_member_count": anchor_summary.get("candidate_member_count", 0),
        "anchor_reverse_event_count": anchor_summary.get("reverse_event_count", 0),
        "anchor_replay_session_not_200": anchor_summary.get("session_not_200", 0),
        "anchor_replay_checkpoint_set_matches": anchor_summary.get("checkpoint_set_matches", 0),
        "anchor_replay_checkpoint_set_mismatches": anchor_summary.get("checkpoint_set_mismatches", 0),
    })
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

    monthly_gap_rows = _monthly_gap_rows(coverage, snapshots, interval_result.intervals, sources)
    known_at_rows = _known_at_rows(reconciliation.events)
    blocker_rows = _blocker_ledger(
        report, conflicts=conflicts, events=reconciliation.events, snapshots=snapshots,
        coverage=coverage, sources=sources,
    )
    identity_resolution_rows = _historical_identity_resolution_rows(snapshots, aliases)
    checkpoint_forensics, checkpoint_debug = _checkpoint_forensics(snapshots, sources, instrument_master)
    anchor_rows = _anchor_candidate_rows(snapshots, instrument_master)
    duplicate_event_forensics = _conflict_forensics(conflicts, observations, conflict_type="DUPLICATE_ADD")
    official_conflict_forensics = _conflict_forensics(conflicts, observations, conflict_type="OFFICIAL_SOURCE_CONFLICT")
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(reports_dir / "nifty200_pit_monthly_gap_analysis.csv", monthly_gap_rows)
    _write_csv(reports_dir / "nifty200_pit_known_at_audit.csv", known_at_rows)
    _write_csv(reports_dir / "nifty200_pit_historical_identity_resolution.csv", identity_resolution_rows)
    _write_csv(reports_dir / "nifty200_pit_201_member_checkpoint_forensics.csv", checkpoint_forensics)
    _write_csv(reports_dir / "nifty200_pit_checkpoint_forensics_debug.csv", checkpoint_debug)
    _write_csv(reports_dir / "nifty200_pit_duplicate_event_forensics.csv", duplicate_event_forensics)
    _write_csv(reports_dir / "nifty200_pit_official_event_conflicts.csv", official_conflict_forensics)
    _write_csv(reports_dir / "nifty200_pit_anchor_replay_checkpoint_comparison.csv", anchor_forensics["checkpoint_rows"])
    _write_csv(reports_dir / "nifty200_pit_anchor_replay_checkpoint_differences.csv", anchor_forensics["details"])
    (reports_dir / "nifty200_pit_checkpoint_requirement_audit.md").write_text(
        _checkpoint_requirement_audit(), encoding="utf-8",
    )
    anchor_summary = anchor_forensics["summary"]
    (reports_dir / "nifty200_pit_initial_anchor_20120102.md").write_text(
        "# NIFTY-200 PIT initial-anchor audit\n\n"
        "Status: `BLOCKED_NO_CERTIFIABLE_2012_01_02_ANCHOR`\n\n"
        f"The nearest valid acquired official checkpoint is {anchor_summary.get('source_checkpoint_date', 'not available')} "
        f"with {anchor_summary.get('source_checkpoint_count', 0)} unique rows. The backward diagnostic candidate contains "
        f"{anchor_summary.get('candidate_member_count', 0)} members after reversing {anchor_summary.get('reverse_event_count', 0)} "
        "canonical events. It remains `NOT_ASSERTED`, `MANUAL_REVIEW`, and ineligible for authoritative replay.\n\n"
        "The candidate is a measurement tool only: it does not establish membership on 2012-01-02, and no synthetic membership, "
        "predecessor, successor, ISIN, or announcement date was created.\n\n"
        "Required closure evidence: an authoritative historical CNX/NIFTY-200 membership anchor effective on or before 2012-01-02, "
        "with durable identity and source hash for every member, or a complete first-party event chain that proves the anchor.\n\n"
        "The official CNX 200 launch notice is methodology evidence, not a dated constituent list: "
        "<https://niftyindices.com/Press_Release/ind_prs18072011.pdf>\n",
        encoding="utf-8",
    )
    (reports_dir / "nifty200_pit_2012_anchor_forensics_20260911.md").write_text(
        "# NIFTY-200 PIT 2012 anchor forensics\n\n"
        "## Decision\n\n"
        "The 2012-01-02 anchor is not defensibly established. This diagnostic reverse replay is not authoritative and is not used by "
        "the normal interval builder or validator.\n\n"
        "## Evidence options checked\n\n"
        "- A: the official `IndexInclExcl.xls` `Nifty 200` sheet is a dated inclusion/exclusion change log; its earliest NIFTY-200 row "
        "is 2011-11-22, not a 2012-01-02 membership list.\n"
        "- B: the official CNX 200 launch notice establishes methodology and launch context, but contains no 200-member list.\n"
        "- C: the nearest acquired official monthly checkpoint is used as a forward anchor only.\n"
        "- D: reversing the currently canonical, certified event chain gives a diagnostic candidate; unresolved official observations are "
        "not promoted and B1 rows are not used as authority.\n\n"
        "## Measured result\n\n"
        f"- Forward checkpoint: {anchor_summary.get('source_checkpoint_date', '')}; rows: {anchor_summary.get('source_checkpoint_count', 0)}; "
        f"source SHA-256: {anchor_forensics['anchor_evidence'][0].get('source_sha256', '') if anchor_forensics['anchor_evidence'] else ''}.\n"
        f"- Reverse canonical events: {anchor_summary.get('reverse_event_count', 0)}; candidate initial rows: {anchor_summary.get('candidate_member_count', 0)}.\n"
        f"- NSE sessions replayed: {anchor_summary.get('session_count', 0)}; exact-200 sessions: {anchor_summary.get('session_exact_200', 0)}; "
        f"non-200 sessions: {anchor_summary.get('session_not_200', 0)}.\n"
        f"- First count divergence: {anchor_summary.get('first_divergence_date', '')} at "
        f"{anchor_summary.get('first_divergence_count', '')} members; event rows applied that day: "
        f"{anchor_summary.get('first_divergence_events', '') or 'none'}; cause is the unproven initial set, not a fabricated event.\n"
        f"- Valid official checkpoints compared: {anchor_summary.get('checkpoint_count', 0)}; set matches: "
        f"{anchor_summary.get('checkpoint_set_matches', 0)}; set mismatches: {anchor_summary.get('checkpoint_set_mismatches', 0)}; "
        f"first mismatch: {anchor_summary.get('first_checkpoint_mismatch', '') or 'none'}.\n\n"
        "## Interpretation\n\n"
        "A candidate that matches a later checkpoint cannot prove the starting membership when the intervening official event chain has "
        "unresolved observations and missing publication/effective-date linkage. Remaining closure evidence must be first-party historical "
        "membership or event evidence with durable identity and causality.\n",
        encoding="utf-8",
    )
    _write_csv(artifact_dir / "monthly_gap_analysis.csv", monthly_gap_rows)
    _write_csv(artifact_dir / "known_at_audit.csv", known_at_rows)
    _write_csv(artifact_dir / "blocker_ledger.csv", blocker_rows)
    _write_csv(artifact_dir / "historical_identity_resolution.csv", identity_resolution_rows)
    _write_csv(artifact_dir / "checkpoint_forensics.csv", checkpoint_forensics)
    _write_csv(artifact_dir / "checkpoint_forensics_debug.csv", checkpoint_debug)
    _write_csv(artifact_dir / "duplicate_event_forensics.csv", duplicate_event_forensics)
    _write_csv(artifact_dir / "official_event_conflicts.csv", official_conflict_forensics)
    write_table(artifact_dir / "initial_anchor_20120102.parquet", anchor_rows)
    write_table(artifact_dir / "initial_anchor_evidence.parquet", anchor_forensics["anchor_evidence"])
    write_table(artifact_dir / "anchor_replay_candidate.parquet", anchor_forensics["candidate_rows"])
    write_table(artifact_dir / "anchor_replay_sessions.parquet", anchor_forensics["session_rows"])
    _write_csv(artifact_dir / "anchor_replay_checkpoint_comparison.csv", anchor_forensics["checkpoint_rows"])
    _write_csv(artifact_dir / "anchor_replay_checkpoint_differences.csv", anchor_forensics["details"])
    (artifact_dir / "2012_anchor_forensics.md").write_text(
        (reports_dir / "nifty200_pit_2012_anchor_forensics_20260911.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    write_table(derived / "historical_instrument_master.parquet", historical_master)
    write_table(artifact_dir / "historical_instrument_master.parquet", historical_master)

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
        f"- Durable identity mappings: {sum(row.get('confidence') == 'CERTIFIED' for row in aliases)} certified; "
        f"{sum(row.get('confidence') != 'CERTIFIED' for row in aliases)} remain manual-review candidates.\n"
        f"- Coverage gaps or non-200 checkpoints: {len(coverage_gaps)} campaign months.\n"
        f"- NSE sessions checked: {len(trading_days)}; replay count range: {min(replay_counts, default=0)}..{max(replay_counts, default=0)}.\n"
        f"- Blocker ledger rows: {len(blocker_rows)}; known_at unresolved canonical events: "
        f"{sum(event.known_at is None or not event.known_at_basis for event in reconciliation.events)}.\n"
        f"- Automated validation: **{report.status.value}**.\n\n"
        "The package is intentionally blocked because the available evidence does not yet provide a complete, causally timestamped, "
        "durable-identity reconstruction for every campaign day. No synthetic initial membership or fabricated ISIN was created.\n",
        encoding="utf-8",
    )

    write_artifacts(
        artifact_dir, source_records=sources, observations=observations, events=reconciliation.events,
        aliases=aliases, intervals=interval_result.intervals, monthly_snapshots=snapshots,
        conflicts=conflicts, validation_report=report,
        campaign_from=CAMPAIGN_FROM.isoformat(), campaign_to=CAMPAIGN_TO.isoformat(),
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
        campaign_from=CAMPAIGN_FROM.isoformat(), campaign_to=CAMPAIGN_TO.isoformat(),
    )
    return {
        "source_count": len(sources), "source_hash_errors": len(source_errors),
        "observation_count": len(observations), "canonical_event_count": len(reconciliation.events),
        "snapshot_row_count": len(snapshots), "snapshot_dates": len({row["snapshot_date"] for row in snapshots}),
        "interval_count": len(interval_result.intervals), "conflict_count": len(conflicts),
        "coverage_gap_count": len(coverage_gaps), "validation_status": report.status.value,
        "trading_days_checked": len(trading_days),
        "minimum_active_constituent_count": min(replay_counts, default=0),
        "maximum_active_constituent_count": max(replay_counts, default=0),
        "blocker_ledger_count": len(blocker_rows),
        "artifact_dir": str(artifact_dir),
    }


def main() -> int:
    result = build_dataset()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
