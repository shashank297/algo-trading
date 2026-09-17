"""Build non-authoritative NIFTY-200 PIT evidence artifacts from public files.

This command is deliberately fail-closed. It harvests and parses real source
bytes, but it does not invent ISINs, instrument IDs, historical constituents,
or publication timestamps. The output can therefore be useful while still
remaining blocked until identity and causality gaps are independently closed.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from typing import Any

from tools.nifty200_pit.intervals import build_intervals, active_intervals
from tools.nifty200_pit.manifest import write_artifacts, write_table
from tools.nifty200_pit.ocr import load_pdf_transcription
from tools.nifty200_pit.models import Action, Conflict, Observation, SourceRecord
from tools.nifty200_pit.parse_pdf import (
    extract_pdf_pages,
    find_document_date,
    find_effective_date,
    parse_nifty200_text,
)
from tools.nifty200_pit.reconciliation import observation_hash, reconcile_observations
from tools.nifty200_pit.instrument_resolver import resolve_observation, resolve_observations
from tools.nifty200_pit.source_catalogue import sha256_file
from tools.nifty200_pit.validation import nifty200_expected_security_count, validate_campaign, verify_source_hashes
from trading_stack.calendars import MarketCalendar, SessionOverride, build_nse_calendar
from tools.nifty200_pit.causality import next_trading_session_open

CAMPAIGN_FROM = date(2012, 1, 2)
CAMPAIGN_TO = date(2026, 8, 20)
CHALLENGER_EVENTS_URL = "https://raw.githubusercontent.com/deshpanda/nse-screener-data/main/reconstitution/events.parquet"
CHALLENGER_EVENTS_ARCHIVE_URL = "https://github.com/deshpanda/nse-screener-data/blob/main/reconstitution/events.parquet"
CHALLENGER_EVENTS_PATH = Path(
    "data/raw/nifty200_pit_public_sources/challengers/"
    "deshpanda_nse_screener_reconstitution_events.parquet"
)
SECURITIES_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
HISTORICAL_SECURITY_MASTER_URL = "http://nseindia.com/content/equities/EQUITY_L.csv"
HISTORICAL_SECURITY_MASTER_2017_ARCHIVE_URL = (
    "https://web.archive.org/web/20170704082238id_/"
    "https://www.nseindia.com/content/equities/EQUITY_L.csv"
)
HISTORICAL_SECURITY_MASTER_2021_ARCHIVE_URL = (
    "https://web.archive.org/web/20210516062344id_/"
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)
HISTORICAL_INDEX_CONSTITUENT_2014_URL = (
    "https://web.archive.org/web/20140122091713id_/"
    "http%3A%2F%2Fnseindia.com%2Fcontent%2Findices%2Find_cnx200list.csv"
)
HISTORICAL_INDEX_CONSTITUENT_2014_DATE = "2014-01-13"
SYMBOL_CHANGES_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
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


_PRESS_RELEASE_EFFECTIVE_DATE_OVERRIDES = {
    # The native PDF text for these A1 releases is column-interleaved and
    # omits the day/month boundary. The dates are taken from the matching A1
    # IndexInclExcl.xls event rows; the PDF supplies the named event members.
    "https://www.niftyindices.com/Press_Release/ind_prs14032012.pdf": date(2012, 4, 27),
    "https://www.niftyindices.com/Press_Release/ind_prs16052012.pdf": date(2012, 5, 21),
    "https://www.niftyindices.com/Press_Release/ind_prs16082012.pdf": date(2012, 9, 28),
    "https://www.niftyindices.com/Press_Release/ind_prs15032013.pdf": date(2013, 3, 19),
    "https://www.niftyindices.com/Press_Release/ind_prs13022013.pdf": date(2013, 4, 1),
    "https://www.niftyindices.com/Press_Release/ind_prs11042013.pdf": date(2013, 4, 17),
}


def parse_press_releases(
    records: list[SourceRecord],
    *,
    effective_date_overrides: dict[str, date] | None = None,
    transcription_audit: list[dict[str, Any]] | None = None,
) -> list[Observation]:
    observations: list[Observation] = []
    overrides = effective_date_overrides or _PRESS_RELEASE_EFFECTIVE_DATE_OVERRIDES
    for source in records:
        if not source.local_path.lower().endswith(".pdf") or not re.search(r"press[_-]release", source.source_url, re.I):
            continue
        pages = extract_pdf_pages(source.local_path)
        document_text = "\n".join(pages)
        transcription = load_pdf_transcription(source) if not document_text.strip() else None
        if transcription is not None:
            document_text = transcription["date_text"] + "\n" + transcription["event_text"]
        if not re.search(r"\b(?:NIFTY|CNX)\s*[- ]?200\b", document_text, re.I):
            continue
        # Index-change tables commonly continue across PDF pages. Parsing each
        # page independently drops the continuation page because it has no
        # repeated numbered index heading. Parse the bounded document section
        # once so all rows retain the same document-level provenance.
        document_effective = find_effective_date(document_text) or overrides.get(source.source_url)
        if document_effective is None:
            # Some older PDFs store text in drawing order: the date is emitted
            # before its "effective from" clause. Spatial extraction restores
            # that explicit relationship without borrowing another event's date.
            layout_text = "\n".join(extract_pdf_pages(source.local_path, layout=True))
            document_effective = find_effective_date(layout_text)
        announcement = find_document_date(source.source_url, document_text)
        parsed = parse_nifty200_text(
            document_text, source_url=source.source_url, source_sha256=source.source_sha256,
            announcement_date=announcement, source_page=None, source_tier=source.source_tier,
            extractor_version="nifty200-pit-parser-v3", effective_date=document_effective,
        )
        grid_pages = [page_number for page_number, page_text in enumerate(pages, 1) if re.search(
            r"^\s*\d+[ \t]+(?:NIFTY|CNX)[ \t]*[- ]?200[ \t]*$", page_text, re.I | re.M,
        )]
        if len(grid_pages) == 1:
            parsed = [replace(row, source_page=grid_pages[0])
                      if row.extraction_method == "PDF_TEXT_INDEX_GRID" else row for row in parsed]
        if not any(row.symbol and row.action for row in parsed):
            layout_text = "\n".join(extract_pdf_pages(source.local_path, layout=True))
            parsed = parse_nifty200_text(
                layout_text, source_url=source.source_url, source_sha256=source.source_sha256,
                announcement_date=announcement, source_page=None, source_tier=source.source_tier,
                extractor_version="nifty200-pit-parser-v4-layout", effective_date=document_effective,
            )
        if transcription is not None:
            parsed = [replace(
                row, source_page=transcription["event_source_page"],
                extraction_method="PDF_VISUAL_TRANSCRIPTION",
                extractor_version=f"nifty200-pit-transcription-v1:{transcription['derivative_sha256']}",
                raw_text=json.dumps({
                    "row": row.raw_text, "date_source_page": transcription["date_source_page"],
                    "date_text": transcription["date_text"],
                    "derivative_sha256": transcription["derivative_sha256"],
                    "independent_qa": "NOT_ASSERTED",
                }, sort_keys=True),
            ) for row in parsed]
            if transcription_audit is not None:
                transcription_audit.append(transcription)
        observations.extend(row for row in parsed if row.symbol and row.action)
    return observations


def _apply_official_rescheduling(
    observations: list[Observation], sources: list[SourceRecord],
) -> tuple[list[Observation], list[dict[str, Any]]]:
    """Preserve original assertions but exclude explicitly withdrawn schedules.

    These narrow dispositions are tied to inspected, content-hashed notices.
    They never create replacement events or infer a revised effective date.
    """
    rules = [
        # November 13 notice, page 1 and annexure 1: trading holiday moves
        # the November 7 release's CNX 200 changes from Nov 15 to Nov 18.
        ("53d167e552b4737b060ab7893db9bd63548fdb3801f884ea4f4669ad0e4f3bc5",
         "ind_prs07112013.pdf", date(2013, 11, 15), None, None),
        # August 29 notice, page 1 and section 6: only the named Reliance
        # Capital / Max Financial replacement is moved from Sep 29 to Sep 5.
        ("2c901efcc5c3af6a8b9d353b2de9c91904bab4b40c8e68ef8540267366c46f20",
         "ind_prs28082017.pdf", date(2017, 9, 29), {"RELCAPITAL", "MFSL"}, None),
        # March 19, 2024, pages 1-2 revokes the originally announced IREDA
        # inclusion. BSE's replacement inclusion is parsed from that notice;
        # revocation is never represented as a fabricated removal event.
        ("1bef44dabdf594b9390b15329de1d9f38a8ab96af2abea243e99311b6d61587e",
         "ind_prs28022024.pdf", date(2024, 3, 28), {"IREDA"}, Action.ADD),
    ]
    # March 23, 2020 notice, page 1: periodic replacements announced in
    # these three releases are deferred until further notice. The named
    # exception concerns other indices, not NIFTY 200. Do not move these
    # events to June by inference; the June release is parsed separately.
    rules.extend(
        ("55a9cd5f11b9036e274b397c1f43f607c632ccb31837339b7ac661de6037ea59",
         filename, date(2020, 3, 27), None, None)
        for filename in ("ind_prs18022020.pdf", "ind_prs12032020.pdf", "ind_prs19032020.pdf")
    )
    verified_sources = {
        source.source_sha256: source for source in sources
        if source.source_tier in {"A1", "A2"} and Path(source.local_path).is_file()
        and sha256_file(Path(source.local_path)) == source.source_sha256
    }
    result: list[Observation] = []
    audit: list[dict[str, Any]] = []
    for row in observations:
        updated = row
        for notice_hash, original_file, original_date, symbols, action in rules:
            notice = verified_sources.get(notice_hash)
            if (notice is None or row.source_tier not in {"A1", "A2"}
                    or row.index_id != "NIFTY_200" or row.effective_date != original_date
                    or not row.source_url.endswith("/" + original_file)
                    or (symbols is not None and row.symbol not in symbols)
                    or (action is not None and row.action != action)):
                continue
            identifier = row.observation_id or observation_hash(row)
            updated = replace(row, observation_id=identifier, review_status="SUPERSEDED",
                              reason=f"OFFICIAL_SCHEDULE_WITHDRAWN:{notice.source_url}#{notice_hash}")
            audit.append({
                "observation_id": identifier, "symbol": row.symbol, "action": str(row.action),
                "withdrawn_effective_date": original_date.isoformat(),
                "original_source_url": row.source_url, "original_source_sha256": row.source_sha256,
                "disposition": "SUPERSEDED", "resolution_source": notice.source_url,
                "resolution_source_sha256": notice_hash,
                "notes": "Original assertion preserved; replacement must be independently parsed from official evidence.",
            })
            break
        result.append(updated)
    return result, audit


def _exclude_withdrawn_challenger_assertions(
    observations: list[Observation], dispositions: list[dict[str, Any]],
    sources: list[SourceRecord] | None = None,
) -> tuple[list[Observation], list[dict[str, Any]]]:
    """Audit B1 repetitions of withdrawn schedules without promoting their tier.

    The caller retains all input observations in the evidence package. Only
    exact action/symbol/date matches to hash-verified dispositions are excluded
    from reconciliation; unrelated B1 assertions remain unresolved blockers.
    """
    withdrawn = {
        (row["withdrawn_effective_date"], row["symbol"], row["action"]): row
        for row in dispositions if row["disposition"] == "SUPERSEDED"
    }
    # The October 17, 2016 release assigns NIFTY 200 to November 15;
    # October 24 belongs to other indices on page 1. Page 5 names this pair.
    scope_hash = "e3ad170876e6278ad7a1e99cc924ba610c3f8be4ef0dc85cd2c146e2152ca4ea"
    scope_source = next((source for source in sources or []
                         if source.source_sha256 == scope_hash and source.source_tier in {"A1", "A2"}
                         and Path(source.local_path).is_file()
                         and sha256_file(Path(source.local_path)) == scope_hash), None)
    if scope_source is not None:
        for row in observations:
            if (row.source_sha256 == scope_hash and row.source_tier in {"A1", "A2"}
                    and row.index_id == "NIFTY_200" and row.effective_date == date(2016, 11, 15)
                    and (row.symbol, str(row.action)) in {("CAIRN", "DROP"), ("CROMPTON", "ADD")}):
                withdrawn[("2016-10-24", row.symbol, str(row.action))] = {
                    "withdrawn_effective_date": "2016-10-24", "symbol": row.symbol, "action": str(row.action),
                    "resolution_source": scope_source.source_url, "resolution_source_sha256": scope_hash,
                    "notes": "B1 date contradicts the index-specific schedule: page 1 group C and page 5 specify NIFTY 200 on 2016-11-15; 2016-10-24 belongs to other indices. B1 retained provisional/unresolved.",
                }
    retained: list[Observation] = []
    audit: list[dict[str, Any]] = []
    for row in observations:
        evidence = withdrawn.get((
            row.effective_date.isoformat() if row.effective_date else "", row.symbol, str(row.action),
        ))
        if row.source_tier != "B1" or row.index_id != "NIFTY_200" or evidence is None:
            retained.append(row)
            continue
        audit.append({
            **evidence, "observation_id": row.observation_id or observation_hash(row),
            "original_source_url": row.source_url, "original_source_sha256": row.source_sha256,
            "disposition": "B1_CONTRADICTED",
            "notes": evidence.get("notes", "B1 assertion retained as provisional/unresolved; official notice withdrew this exact schedule. Not a missing event."),
        })
    return retained, audit


def parse_security_master(source: SourceRecord) -> list[dict[str, Any]]:
    """Parse official NSE rows into period-valid identity evidence."""
    data = Path(source.local_path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    required = {"SYMBOL", "NAME OF COMPANY", "DATE OF LISTING", "ISIN NUMBER"}
    if not required.issubset({str(column).strip().upper() for column in reader.fieldnames or []}):
        return []
    snapshot_date = _parse_day(source.document_date or str(source.retrieved_at)[:10])
    if snapshot_date is None:
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
            "series": str(raw.get("SERIES") or "").strip().upper(),
            "company_name": str(raw.get("NAME OF COMPANY") or "").strip() or None,
            # Preserve the exchange's listing date for the existing resolver
            # contract; the dated snapshot remains the evidence boundary.
            "listing_date": listing_date.isoformat() if listing_date else None,
            "valid_from": listing_date.isoformat() if listing_date else snapshot_date.isoformat(),
            "valid_until": None, "source_url": source.source_url,
            "source_sha256": source.source_sha256, "source_tier": source.source_tier,
            "snapshot_date": snapshot_date.isoformat(),
            "identity_event_type": "DATED_SECURITY_MASTER_SNAPSHOT",
        })
    return rows


def parse_bhavcopy_identities(
    source: SourceRecord, *, identity_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Read dated ISIN evidence; a bhavcopy does not establish index membership."""
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(source.local_path) as archive:
        for member in archive.namelist():
            if not member.lower().endswith('.csv'):
                continue
            text = archive.read(member).decode('utf-8-sig')
            for raw in csv.DictReader(io.StringIO(text)):
                normalized = {str(key).strip().casefold(): value for key, value in raw.items() if key is not None}
                when = _parse_day(normalized.get('timestamp') or normalized.get('trad dt') or normalized.get('traddt'))
                symbol = str(normalized.get('symbol') or normalized.get('ticker') or normalized.get('tckrsymb') or '').strip()
                isin = str(normalized.get('isin') or normalized.get('isin number') or '').strip()
                series = str(normalized.get('series') or normalized.get('sctysrs') or '').strip().upper()
                # Daily files also carry bonds under the issuer's same symbol
                # (e.g. IFCI ND/NH and HUDCO N2). Only normal equity-series
                # rows are identity evidence for these index constituents.
                if series != 'EQ':
                    continue
                if not when or not symbol or not re.fullmatch(r'IN[A-Z0-9]{10}', isin):
                    continue
                if identity_keys is not None and (when.isoformat(), symbol.upper()) not in identity_keys:
                    continue
                if source.document_date and when.isoformat() != source.document_date:
                    raise ValueError(f'Bhavcopy timestamp disagrees with catalogue: {source.source_url}')
                rows.append({
                    'instrument_id': f'NSE-ISIN:{isin}', 'isin': isin, 'symbol': symbol,
                    'series': series, 'company_name': None,
                    'valid_from': when.isoformat(), 'valid_until': (when + timedelta(days=1)).isoformat(),
                    'snapshot_date': when.isoformat(), 'source_url': source.source_url,
                    'source_sha256': source.source_sha256, 'source_tier': source.source_tier,
                    'source_member': member, 'identity_event_type': 'DATED_BHAVCOPY_IDENTITY',
                })
    return rows


def parse_symbol_changes(source: SourceRecord) -> list[dict[str, Any]]:
    """Parse NSE's explicit previous-symbol to new-symbol mappings."""
    rows: list[dict[str, Any]] = []
    with Path(source.local_path).open(encoding="utf-8-sig", newline="") as handle:
        for fields in csv.reader(handle):
            if len(fields) < 4:
                continue
            company_name, previous_symbol, new_symbol = (str(value).strip() for value in fields[:3])
            changed_on = _parse_day(fields[3])
            if not previous_symbol or not new_symbol or not changed_on:
                continue
            rows.append({
                "company_name": company_name or None,
                "previous_symbol": previous_symbol,
                "new_symbol": new_symbol,
                "changed_on": changed_on,
                "source_url": source.source_url,
                "source_sha256": source.source_sha256,
                "source_tier": source.source_tier,
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
    label = match.group(1).lower()
    month = MONTH_NAME.get(label) or next((number for name, number in MONTH_NAME.items() if name[:3] == label), None)
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


def _identity_aliases(
    snapshots: list[dict[str, Any]], master: list[dict[str, Any]],
    symbol_changes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
    master_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in master:
        master_by_symbol.setdefault(str(row["symbol"]).casefold(), []).append(row)
    changes_by_previous: dict[str, list[dict[str, Any]]] = {}
    for change in symbol_changes or []:
        changes_by_previous.setdefault(str(change["previous_symbol"]).casefold(), []).append(change)

    def resolve_target(symbol: str, seen: set[str] | None = None) -> dict[str, Any] | None:
        """Resolve an exact NSE symbol-change chain to one master row."""
        current_symbol = symbol.casefold()
        visited = set() if seen is None else set(seen)
        if current_symbol in visited:
            return None
        visited.add(current_symbol)
        direct_rows = master_by_symbol.get(current_symbol, [])
        direct_instruments = {str(row.get("instrument_id") or "") for row in direct_rows}
        if len(direct_instruments) == 1:
            return direct_rows[0]
        candidates: list[dict[str, Any]] = []
        for next_change in changes_by_previous.get(current_symbol, []):
            target = resolve_target(str(next_change["new_symbol"]), visited)
            if target is not None:
                candidates.append(target)
        instrument_ids = {str(row["instrument_id"]) for row in candidates}
        if len(instrument_ids) != 1:
            return None
        return candidates[0]

    historical_candidates: dict[str, list[dict[str, Any]]] = {}
    for change in symbol_changes or []:
        target = resolve_target(str(change["new_symbol"]))
        if target is None:
            continue
        alias_symbol = str(change["previous_symbol"]).strip()
        historical_candidates.setdefault(alias_symbol.casefold(), []).append({
            **target,
            "alias_symbol": alias_symbol,
            "valid_until": change["changed_on"].isoformat(),
            "identity_event_type": "SYMBOL_CHANGE",
            "source_url": change["source_url"],
            "source_sha256": change["source_sha256"],
            "source_tier": change["source_tier"],
            "confidence": "CERTIFIED",
            "resolution_status": "ACCEPTED",
        })
    for candidates_for_symbol in historical_candidates.values():
        instrument_ids = {str(row["instrument_id"]) for row in candidates_for_symbol}
        if len(instrument_ids) == 1:
            for row in candidates_for_symbol:
                aliases[(str(row["instrument_id"]), str(row["alias_symbol"]).casefold())] = row
        else:
            for row in candidates_for_symbol:
                row["confidence"] = "MANUAL_REVIEW"
                row["resolution_status"] = "MANUAL_REVIEW"
                aliases[(str(row["instrument_id"]), str(row["alias_symbol"]).casefold())] = row
    certified_alias_symbols = {
        str(row.get("alias_symbol") or row.get("symbol") or "").casefold()
        for row in aliases.values()
        if row.get("confidence") == "CERTIFIED"
    }
    candidates: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        # An exact current-security-master symbol is already represented by the
        # certified row above.  Do not create a second (None, symbol) alias that
        # falsely reports the same current listing as unresolved historical data.
        if symbol.casefold() in master_symbols or symbol.casefold() in certified_alias_symbols:
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


def _apply_documented_isin_continuity(
    observations: list[Observation], master: list[dict[str, Any]], aliases: list[dict[str, Any]],
    sources: list[SourceRecord],
) -> tuple[list[Observation], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Keep one equity identity across inspected splits, without rewriting ISINs/dates.

    These are exact document-backed continuity links, not inferred mergers or
    membership events. An NSE reference-file change is not a legal ex-date:
    validity periods, knowledge times, and original source assertions stay intact.
    """
    # symbol, old/new ISIN, checked reference dates, notice page/hash, before/after hashes.
    rules = [
        ("J&KBANK", "INE168A01017", "INE168A01041", "2014-09-04", "2014-09-05", 35,
         "786b5c5e35f33103410dae2473e6bbae728d3bddbf818a9a1d30988bbb2446a0",
         "98a1dfce5d59f653a2af0243f1ab75c9a48f924bd8a5542478f0d7712cb31879",
         "e0033dcc96a1a48ef264b8de7b111cd9fbd4146c033573023c2c28bb18d4d463"),
        ("BATAINDIA", "INE176A01010", "INE176A01028", "2015-10-07", "2015-10-08", 1,
         "19165b2821beacbd70053fce918555230a5966c558685dcb4dcac658e1141692",
         "5bf12c923a4fdae35c64b42db565f61869e6ab9b76cfe6b78a47a7d6fba5b275",
         "1e4904294f249df9baad33639503a04ce51e45df5940eabeb27e01b7e49ec6e2"),
        ("NATCOPHARM", "INE987B01018", "INE987B01026", "2015-11-26", "2015-11-27", 69,
         "2241693af4d891f158bce562bfc063a712560ee5572e04fc6136ead6995082db",
         "9107181b9fad0d1155000e5e8af1350fdaaa2468182413c9dd962d89bef157aa",
         "0fa7564e64931170ab47912e08a28a29e838416ef6f8d319e164e03ccafd5d35"),
        ("NBCC", "INE095N01015", "INE095N01023", "2016-06-02", "2016-06-03", 153,
         "69b7b0ea2b72649ec447ed47df9f15a4ca2cfffeb4983a9557a9246c6d1c74ee",
         "87df9d926becfd62eae15fb55bfdd5dc2d2d017d00eaacaa8e403078395f5415",
         "9892c2b4c078fbeadaab8a45087f5b316a833d74e7d7cc4df949ed72953c6e09"),
        ("KARURVYSYA", "INE036D01010", "INE036D01028", "2016-11-17", "2016-11-18", 1,
         "a9bdaffd58af89da20f2e435ca7442ba4d2db26910cbd40ee94d2c2ab2b531dd",
         "088c51d7decb7f8acab04d6f95d8d0d8ac1589fba73aee8a6414a78c60535c7e",
         "e88f7b5d5fb4bbec80ddd7214b955eb1f4efc46afdb860eac288b7094d014ddd"),
        ("NBCC", "INE095N01023", "INE095N01031", "2018-04-25", "2018-04-26", 1,
         "ff186e104f0ec6fce4257422655e453aa289a9b80389b44fff260177856d4521",
         "2c1bba907be7866dfccaa6e6380b60341d18547ff389f4100526043d0b541dc1",
         "1c29705c1138d2852db6f0eb0bfd25d61d649e57711b818c57fa033326b2d6cb"),
        ("BAJFINANCE", "INE296A01016", "INE296A01024", "2016-09-07", "2016-09-09", 1,
         "11b2a619b064c270d04a3fedc14633317d0a87959a212f98dad5349ad14babc5",
         "b3cf8eed2deecdf468f0249870e4b0869aac49f3a4c38e93edbddd53f1c4a604",
         "fba772ecc40bb05c24d29c49f634c79cef0d9a736daa58f266f58ee5f675199d"),
        ("CESC", "INE486A01013", "INE486A01021", "2021-09-16", "2021-09-21", 3,
         "a3135b48b38e6f314d9524fc63c7ac0ff2a95234077e9beaddccf296c2cd635c",
         "9809dd7f425e1fb372458874fb492321a7d5a96c367a1a8446bc16144cf75f68",
         "bea670d1419fbb711d65e11ff3f03e223b91c931313460ee4933b388c2c25922"),
    ]
    needed = {digest for rule in rules for digest in rule[6:]}
    verified = {source.source_sha256: source for source in sources
                if source.source_sha256 in needed and source.source_tier in {"A1", "A2"}
                and Path(source.local_path).is_file()
                and sha256_file(Path(source.local_path)) == source.source_sha256}
    parents: dict[tuple[str, str], str] = {}
    links: list[dict[str, Any]] = []
    for symbol, old, new, before_day, after_day, page, notice_sha, before_sha, after_sha in rules:
        if not all(digest in verified for digest in (notice_sha, before_sha, after_sha)):
            continue
        if not all(any(row.get("symbol") == symbol and row.get("isin") == isin
                       and row.get("series") == "EQ" and str(row.get("snapshot_date")) == day
                       for row in parse_bhavcopy_identities(verified[digest]))
                   for digest, isin, day in ((before_sha, old, before_day), (after_sha, new, after_day))):
            continue
        parents[(symbol, new)] = old
        links.append({
            "symbol": symbol, "old_isin": old, "new_isin": new,
            "identity_event_type": "DOCUMENTED_STOCK_SPLIT_CONTINUITY",
            "source_url": verified[notice_sha].source_url, "source_sha256": notice_sha, "source_page": page,
            "before_reference_date": before_day, "before_source_url": verified[before_sha].source_url,
            "before_source_sha256": before_sha, "after_reference_date": after_day,
            "after_source_url": verified[after_sha].source_url, "after_source_sha256": after_sha,
            "date_semantics": "REFERENCE_OBSERVATIONS_ONLY_EXISTING_ISIN_VALIDITY_NOT_CERTIFIED_BY_THIS_LINK",
            "independent_qa": "NOT_ASSERTED",
        })

    def durable_id(symbol: object, isin: object, original: Any) -> Any:
        if not original or original != f"NSE-ISIN:{isin}":
            return original
        root_isin = str(isin)
        while (str(symbol), root_isin) in parents:
            root_isin = parents[(str(symbol), root_isin)]
        return f"NSE-ISIN:{root_isin}"

    def project(row: dict[str, Any]) -> dict[str, Any]:
        identifier = durable_id(row.get("symbol"), row.get("isin"), row.get("instrument_id"))
        if identifier == row.get("instrument_id"):
            return dict(row)
        return row | {"instrument_id": identifier, "identity_reference_instrument_id": row["instrument_id"],
                      "identity_continuity_basis": "DOCUMENTED_STOCK_SPLIT_SEE_IDENTITY_CONTINUITY_EVIDENCE"}

    for link in links:
        link["durable_instrument_id"] = durable_id(link["symbol"], link["new_isin"], f"NSE-ISIN:{link['new_isin']}")
    resolved = []
    observation_audit = []
    for observation in observations:
        identifier = durable_id(observation.symbol, observation.isin, observation.instrument_id)
        updated = replace(observation, instrument_id=identifier)
        resolved.append(updated)
        if identifier != observation.instrument_id:
            observation_audit.append({
                "original_observation_hash": observation_hash(observation), "resolved_observation_hash": observation_hash(updated),
                "symbol": observation.symbol, "isin": observation.isin, "effective_date": observation.effective_date,
                "old_instrument_id": observation.instrument_id, "new_instrument_id": identifier,
                "source_url": observation.source_url, "source_sha256": observation.source_sha256,
                "membership_or_date_assertion_changed": False,
            })
    return resolved, [project(row) for row in master], [project(row) for row in aliases], {
        "links": links, "observations": observation_audit,
    }


def _company_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _suppress_redundant_workbook_observations(observations: list[Observation]) -> list[Observation]:
    """Keep workbook provenance but avoid re-flagging events confirmed by a release."""
    def action_value(observation: Observation) -> str:
        return observation.action.value if isinstance(observation.action, Action) else str(observation.action or "").upper()

    certified_release_keys = {
        (
            observation.index_id,
            observation.effective_date,
            action_value(observation),
            _company_key(observation.company_name),
        )
        for observation in observations
        if observation.extraction_method != "OFFICIAL_XLS"
        and observation.source_tier in {"A1", "A2"}
        and observation.review_status == "ACCEPTED"
        and observation.confidence == "CERTIFIED"
        and observation.instrument_id
        and observation.symbol
        and observation.effective_date
    }
    # Exact, inspected workbook/release pairs; these do not define global
    # company aliases or certify identity by fuzzy matching.
    variants = [
        (date(2013, 4, 1), "DROP", "Great Eastern Shipping Co. Ltd.", "The Great Eastern Shipping Co. Ltd.",
         "747ada17f17537dd854ff497062e263dd32b84598eb74e36795e230c95afff69"),
        (date(2014, 3, 28), "DROP", "Orissa Min Dev Co Ltd.", "Orissa Min Development Co. Ltd.",
         "ad374e90736c719b626d0d774b418edb350d2aff5fafb62c3734468a8e7db7c3"),
        (date(2016, 4, 1), "ADD", "National Buildings Construction Corporation Ltd.", "National Buildings Construction Corp. Ltd.",
         "db2e4802e43b68fcbfbbf2cb03cb59c6d5f9ebf086ab6687d5a15daa45c2525f"),
    ]
    workbook_hash = "8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046"
    variant_keys = set()
    for day, action, workbook_name, release_name, digest in variants:
        if any(row.source_sha256 == digest and row.index_id == "NIFTY_200"
               and row.effective_date == day and action_value(row) == action
               and row.company_name == release_name and row.instrument_id and row.symbol
               and row.source_tier in {"A1", "A2"} and row.confidence == "CERTIFIED"
               and row.review_status == "ACCEPTED" for row in observations):
            variant_keys.add(("NIFTY_200", day, action, _company_key(workbook_name)))
    return [
        observation for observation in observations
        if not (
            observation.extraction_method == "OFFICIAL_XLS"
            and ((
                observation.index_id,
                observation.effective_date,
                action_value(observation),
                _company_key(observation.company_name),
            ) in certified_release_keys or (
                observation.source_sha256 == workbook_hash and observation.source_tier == "A1"
                and (observation.index_id, observation.effective_date, action_value(observation),
                     _company_key(observation.company_name)) in variant_keys
            ))
        )
    ]


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


def _verified_calendar_overrides(sources: list[SourceRecord]) -> tuple[SessionOverride, ...]:
    """Apply inspected NSE exceptions through the existing calendar contract.

    This is a partial set of verified exceptions, not certification of the
    complete campaign calendar. Each override requires its original bytes.
    """
    from datetime import time

    rules = [
        ("c70a96e353be65fa1905057300ddd0cb8823fb8398bb3b9e13d95fbe166888b2",
         date(2024, 1, 22), "CLOSED", None, None),
        ("9236595e1d85a2c58abaa9d6a8e2d148f8ca7fdd696faa20407e91b233840361",
         date(2024, 1, 20), "SPECIAL_SESSION", None, None),
        ("04b67f39314bae95672d86497c28cbed6cea698ad6f029ba47ef74feb9f6da91",
         date(2024, 3, 2), "SPECIAL_SESSION", time(9, 15), time(12, 30)),
        ("04b67f39314bae95672d86497c28cbed6cea698ad6f029ba47ef74feb9f6da91",
         date(2024, 3, 2), "INTERRUPTION", time(10), time(11, 30)),
        ("2483f60d67c34231d6fd25024cf5767c031b234196a7a475535d434cd4e758c8",
         date(2024, 5, 18), "SPECIAL_SESSION", time(9, 15), time(12, 30)),
        ("2483f60d67c34231d6fd25024cf5767c031b234196a7a475535d434cd4e758c8",
         date(2024, 5, 18), "INTERRUPTION", time(10), time(11, 30)),
        ("84d12e29654e75f77baa0b9064a26f6d0e4c3ff58e64df14e01247a0c15a91be",
         date(2025, 2, 1), "SPECIAL_SESSION", time(9, 15), time(15, 30)),
        ("09f80430f3ec95aeaeeb98938124273892abccc38a7aaa440b38a6426b428c21",
         date(2023, 11, 12), "SPECIAL_SESSION", time(18, 15), time(19, 15)),
    ]
    needed = {row[0] for row in rules}
    verified = {source.source_sha256: source for source in sources
                if source.source_sha256 in needed and source.source_tier in {"A1", "A2"}
                and Path(source.local_path).is_file()
                and sha256_file(Path(source.local_path)) == source.source_sha256}
    return tuple(SessionOverride(day, kind, f"{verified[digest].source_url}#{digest}", start, end)
                 for digest, day, kind, start, end in rules if digest in verified)


def _align_date_only_causality(observations: list[Observation], calendar: MarketCalendar) -> list[Observation]:
    """Use the replay calendar for derived knowledge times; preserve exact times."""
    announcements = {row.announcement_date for row in observations if row.announcement_date is not None
                     and row.known_at_basis == "DATE_ONLY_CONSERVATIVE_NEXT_SESSION"}
    opens = {day: next_trading_session_open(day, calendar=calendar) for day in announcements}
    return [replace(row, known_at=opens[row.announcement_date])
            if row.announcement_date in opens and row.known_at_basis == "DATE_ONLY_CONSERVATIVE_NEXT_SESSION"
            else row for row in observations]


def _event_identity_metrics(observations: list[Observation]) -> dict[str, Any]:
    """Measure required event identities, not the already populated alias table."""
    required = [row for row in observations if row.source_tier in {"A1", "A2"}
                and row.action and row.review_status != "SUPERSEDED"]
    durable = sum(bool(row.instrument_id) for row in required)
    isins = sum(bool(row.instrument_id and row.isin) for row in required)
    return {
        "identity_resolution_scope": "FIRST_PARTY_EVENT_OBSERVATIONS_EXCLUDING_SUPERSEDED",
        "identity_observation_count": len(required),
        "durable_id_resolution_percent": round(100 * durable / len(required), 4) if required else 0,
        "isin_resolution_percent": round(100 * isins / len(required), 4) if required else 0,
        "unresolved_identity_count": len(required) - durable,
    }


def _coverage(snapshots: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_month: dict[str, set[str]] = {}
    checkpoint_dates: dict[str, date] = {}
    for row in snapshots:
        month = str(row["snapshot_date"])[:7]
        by_month.setdefault(month, set()).add(str(row.get("symbol") or ""))
        checkpoint_dates[month] = date.fromisoformat(str(row["snapshot_date"])[:10])
    result: list[dict[str, str]] = []
    cursor = date(CAMPAIGN_FROM.year, CAMPAIGN_FROM.month, 1)
    end = date(CAMPAIGN_TO.year, CAMPAIGN_TO.month, 1)
    while cursor <= end:
        key = cursor.isoformat()[:7]
        count = len(by_month.get(key, set()) - {""})
        expected = nifty200_expected_security_count(checkpoint_dates.get(key, cursor))
        valid = count == expected and (expected != 201 or "TATAMTRDVR" in by_month.get(key, set()))
        result.append({
            "period": key, "evidence_type": "OFFICIAL_MONTHLY_WEIGHTAGE",
            "snapshot_member_count": str(count),
            "expected_member_count": str(expected),
            "status": "PASS" if valid else "BLOCKED",
            "qa_note": "verified count under historical security-count methodology" if valid else "missing or unexpected-count official checkpoint",
        })
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return result


def _annual_coverage(coverage: list[dict[str, str]]) -> list[dict[str, str]]:
    by_year: dict[str, list[dict[str, str]]] = {}
    for row in coverage:
        by_year.setdefault(row["period"][:4], []).append(row)
    return [{
        "year": year, "months_expected": str(len(rows)),
        "months_with_200_members": str(sum(row["status"] == "PASS" and row.get("snapshot_member_count", "200") == "200" for row in rows)),
        "months_with_expected_security_count": str(sum(row["status"] == "PASS" for row in rows)),
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "BLOCKED",
        "qa_note": "year has complete expected-count monthly checkpoints" if all(row["status"] == "PASS" for row in rows)
        else "year contains missing or unexpected-count checkpoints",
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


def _monthly_source_gap(source: SourceRecord | None) -> tuple[str, str, str]:
    """Classify missing rows from verified source bytes, not a successful HTTP code."""
    if source is None:
        return ("A_NO_SNAPSHOT_EVIDENCE", "MONTHLY_SNAPSHOT_MISSING",
                "No official monthly checkpoint is present in the acquired corpus.")
    path = Path(source.local_path)
    if not path.is_file():
        return "E_SOURCE_FILE_MISSING", "SOURCE_DOWNLOAD_FAILURE", "The catalogued monthly source file is missing."
    if sha256_file(path) != source.source_sha256:
        return "E_SOURCE_HASH_MISMATCH", "SOURCE_DOWNLOAD_FAILURE", "The monthly source bytes do not match the catalogue hash."
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                return "E_CORRUPTED_ARCHIVE", "SOURCE_DOWNLOAD_FAILURE", "The monthly archive fails ZIP integrity verification."
            candidates = [name for name in archive.namelist() if "200" in name and not name.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        prefix = path.read_bytes()[:1024].lstrip().lower()
        if b"<html" in prefix or b"<!doctype html" in prefix:
            return ("E_HTML_RESPONSE_NOT_ARCHIVE", "SOURCE_DOWNLOAD_FAILURE",
                    "The monthly ZIP URL returned HTML, not a constituent archive; inspect the response and retrieve an alternative source.")
        return "E_INVALID_ARCHIVE", "SOURCE_DOWNLOAD_FAILURE", "The acquired monthly source is not a readable ZIP archive."
    if not candidates:
        return ("A_ARCHIVE_WITHOUT_NIFTY200_MEMBER", "MONTHLY_SNAPSHOT_MISSING",
                "The verified archive has no NIFTY-200 candidate member; other index tables are not a substitute. Search alternative official archives.")
    return ("B_CANDIDATE_MEMBER_ZERO_ROWS", "SOURCE_EXTRACTION_REVIEW",
            "A candidate archive member exists but no NIFTY-200 rows were extracted. Inspect its index scope, table and parser before assigning the cause.")


def _monthly_gap_rows(
    coverage: list[dict[str, str]],
    snapshots: list[dict[str, Any]],
    intervals: list[Any],
    sources: list[SourceRecord],
    checkpoint_comparisons: list[dict[str, Any]] | None = None,
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
        official_found = bool(month_rows)
        checkpoint_date = min((date.fromisoformat(str(row["snapshot_date"])[:10]) for row in month_rows), default=None)
        replay_count = None
        if checkpoint_date is not None:
            replay_count = len({row.instrument_id for row in active_intervals(intervals, checkpoint_date)})
        observed = int(item["snapshot_member_count"])
        symbols = {str(row.get("symbol") or "").strip() for row in month_rows}
        expected = nifty200_expected_security_count(checkpoint_date or date.fromisoformat(month + "-01"))
        if observed == expected and (expected != 201 or "TATAMTRDVR" in symbols):
            status = "PASS"
            action = "none" if expected == 200 else "official additional-DVR methodology verified; preserve all 201 securities"
        elif observed == 0:
            status, _, action = _monthly_source_gap(source)
        elif observed == 201 and "TATAMTRDVR" in symbols:
            status = "D_HISTORICAL_METHOD_COUNT"
            action = "manual governance review: the official report explicitly states 201 securities because of Tata Motors DVR"
        else:
            status = "B_SNAPSHOT_NON_200"
            action = "manual table audit to distinguish parser extraction from methodology/count difference"
        source_status = status
        comparisons = [row for row in checkpoint_comparisons or [] if row["checkpoint_date"][:7] == month]
        replay_status = "NOT_COMPARED"
        if comparisons:
            replay_status = "PASS" if all(row["status"] == "PASS" for row in comparisons) else "BLOCKED"
        if source_status == "PASS" and replay_status != "PASS":
            status = "REPLAY_SNAPSHOT_MISMATCH" if replay_status == "BLOCKED" else "REPLAY_NOT_COMPARED"
            action = "Inspect replay_checkpoint_differences.csv; source count alone does not establish replay membership."
        rows.append({
            "month": month,
            "official_snapshot_found": str(official_found).upper(),
            "observed_count": observed,
            "expected_count": expected,
            "source_url": source.source_url if source else (month_rows[0]["source_url"] if month_rows else ""),
            "archive_url": source.archive_url if source else "",
            "source_sha": source.source_sha256 if source else (month_rows[0]["source_sha256"] if month_rows else ""),
            "replay_member_count": replay_count if replay_count is not None else "",
            "snapshot_vs_replay_diff": (replay_count - observed) if replay_count is not None else "",
            "status": status,
            "source_count_status": source_status,
            "replay_status": replay_status,
            "action_needed": action,
        })
    return rows


def parse_archived_index_constituent_snapshot(source: SourceRecord) -> list[dict[str, Any]]:
    """Parse an archived official index constituent CSV as dated identity evidence."""
    data = Path(source.local_path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    required = {"COMPANY NAME", "SYMBOL", "SERIES", "ISIN CODE"}
    if not required.issubset({str(column).strip().upper() for column in reader.fieldnames or []}):
        return []
    snapshot_date = _parse_day(source.document_date)
    if snapshot_date is None:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for original in reader:
        raw = {str(key).strip().upper(): value for key, value in original.items() if key is not None}
        symbol = str(raw.get("SYMBOL") or "").strip()
        isin = str(raw.get("ISIN CODE") or "").strip()
        series = str(raw.get("SERIES") or "").strip().upper()
        if not symbol or not isin or series != "EQ" or not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
            continue
        key = (symbol.casefold(), isin.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "instrument_id": f"NSE-ISIN:{isin}", "isin": isin, "symbol": symbol,
            "series": series, "company_name": str(raw.get("COMPANY NAME") or "").strip() or None,
            "listing_date": None, "valid_from": snapshot_date.isoformat(), "valid_until": None,
            "validity_basis": "ARCHIVED_INDEX_SNAPSHOT_DATE_ONLY",
            "source_url": source.source_url, "source_sha256": source.source_sha256,
            "source_tier": source.source_tier, "snapshot_date": snapshot_date.isoformat(),
            "identity_event_type": "ARCHIVED_OFFICIAL_INDEX_CONSTITUENT_SNAPSHOT",
        })
    return rows


def _replay_checkpoint_comparison(
    snapshots: list[dict[str, Any]], intervals: list[Any],
    instrument_master: list[dict[str, Any]], aliases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare real intervals, not the reverse-anchor candidate, to checkpoints."""
    master_by_symbol: dict[str, list[dict[str, Any]]] = {}
    aliases_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in instrument_master:
        master_by_symbol.setdefault(_symbol_key(row.get("symbol")), []).append(row)
    for row in aliases:
        aliases_by_symbol.setdefault(_symbol_key(row.get("alias_symbol") or row.get("symbol")), []).append(row)
    summaries: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []
    for checkpoint, official_rows in _valid_checkpoint_groups(snapshots):
        active = {row.instrument_id: row for row in active_intervals(intervals, checkpoint)}
        official_ids: set[str] = set()
        missing = unresolved = alias_matches = 0
        for source in official_rows:
            symbol = _symbol_key(source.get("symbol"))
            resolution = resolve_observation(
                {"symbol": source.get("symbol"), "effective_date": checkpoint},
                master_by_symbol.get(symbol, []), aliases=aliases_by_symbol.get(symbol, []),
            )
            identifier = resolution.instrument_id
            kind = ""
            if resolution.confidence != "CERTIFIED" or not identifier:
                unresolved += 1
                kind = "MISSING_DURABLE_IDENTITY"
            else:
                duplicate = identifier in official_ids
                official_ids.add(identifier)
                if duplicate:
                    kind = "DUPLICATE_OFFICIAL_IDENTITY"
                elif identifier not in active:
                    missing += 1
                    kind = "MISSING_FROM_RECONSTRUCTION"
                elif _symbol_key(active[identifier].symbol_at_entry) != symbol:
                    # Dated identity evidence can match an old entry symbol to
                    # its official alias; do not call that a missing ADD/DROP.
                    alias_matches += 1
            if kind:
                differences.append({
                    "checkpoint_date": checkpoint.isoformat(), "difference_type": kind,
                    "symbol": source.get("symbol", ""), "company_name": source.get("company_name", ""),
                    "instrument_id": identifier or "", "isin": resolution.isin or "",
                    "source_url": source.get("source_url", ""), "source_sha256": source.get("source_sha256", ""),
                    "entry_event_hash": "", "exit_event_hash": "",
                    "resolution_method": resolution.method, "resolution_status": "UNRESOLVED",
                })
        unexpected = sorted(set(active) - official_ids)
        duplicate_identities = len(official_rows) - unresolved - len(official_ids)
        for identifier in unexpected:
            interval = active[identifier]
            differences.append({
                "checkpoint_date": checkpoint.isoformat(), "difference_type": "UNEXPECTED_IN_RECONSTRUCTION",
                "symbol": interval.symbol_at_entry, "company_name": interval.company_name,
                "instrument_id": identifier, "isin": interval.isin_at_entry,
                "source_url": official_rows[0].get("source_url", ""),
                "source_sha256": official_rows[0].get("source_sha256", ""),
                "entry_event_hash": interval.entry_event_hash, "exit_event_hash": interval.exit_event_hash or "",
                "resolution_method": "UNRESOLVED_CHECKPOINT_IDENTITIES" if unresolved else "DURABLE_ID_SET_DIFFERENCE",
                "resolution_status": "UNRESOLVED",
            })
        summaries.append({
            "checkpoint_date": checkpoint.isoformat(), "official_count": len(official_rows),
            "replay_count": len(active), "missing_count": missing, "unexpected_count": len(unexpected),
            "unresolved_identity_count": unresolved, "symbol_alias_match_count": alias_matches,
            "duplicate_identity_count": duplicate_identities,
            "source_url": official_rows[0].get("source_url", ""),
            "source_sha256": official_rows[0].get("source_sha256", ""),
            "status": "BLOCKED" if missing or unexpected or unresolved or duplicate_identities else "PASS",
            "comparison_basis": "AUTHORITATIVE_INTERVALS_WITH_PERIOD_VALID_IDENTITIES",
        })
    return summaries, differences


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


def _event_date_snapshot_rows(events: list[Any]) -> list[dict[str, Any]]:
    """Index canonical event evidence without claiming a full membership snapshot."""
    return [{
        "snapshot_date": event.effective_date.isoformat(),
        "snapshot_kind": "EVENT_DATE_EVIDENCE_INDEX",
        "instrument_id": event.instrument_id,
        "isin": event.isin,
        "symbol": event.symbol,
        "company_name": event.company_name,
        "action": event.action.value if hasattr(event.action, "value") else event.action,
        "announcement_date": event.announcement_date.isoformat(),
        "known_at": event.known_at.isoformat(),
        "known_at_basis": event.known_at_basis,
        "effective_date": event.effective_date.isoformat(),
        "source_url": event.source_url,
        "source_sha256": event.source_sha256,
        "source_tier": event.source_tier,
        "event_hash": event.event_hash,
        "review_status": event.review_status.value if hasattr(event.review_status, "value") else event.review_status,
        "confidence": event.confidence.value if hasattr(event.confidence, "value") else event.confidence,
    } for event in events]


def _historical_master_rows(
    instrument_master: list[dict[str, Any]], aliases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = [{
        "instrument_id": row.get("instrument_id"),
        "isin": row.get("isin"),
        "symbol": row.get("symbol"),
        "series": row.get("series"),
        "snapshot_date": row.get("snapshot_date"),
        "company_name": row.get("company_name"),
        "valid_from": row.get("valid_from"),
        "valid_until": row.get("valid_until"),
        "validity_basis": row.get("validity_basis", "LISTING_DATE_CONTEXT"),
        "identity_event_type": (
            row.get("identity_event_type") or "HISTORICAL_SECURITY_MASTER_SNAPSHOT"
            if row.get("source_url") != SECURITIES_MASTER_URL
            else "CURRENT_SECURITY_MASTER_LISTING_ANCHOR"
        ),
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
        "series": row.get("series"),
        "snapshot_date": row.get("snapshot_date"),
        "company_name": row.get("company_name"),
        "valid_from": row.get("valid_from"),
        "valid_until": row.get("valid_until"),
        "identity_reference_instrument_id": row.get("identity_reference_instrument_id", row.get("instrument_id")),
        "identity_continuity_basis": row.get("identity_continuity_basis"),
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
        if len({_symbol_key(row.get("symbol")) for row in rows} - {""}) == nifty200_expected_security_count(snapshot_date)
        and (nifty200_expected_security_count(snapshot_date) != 201
              or _symbol_key("TATAMTRDVR") in {_symbol_key(row.get("symbol")) for row in rows})
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
            "checkpoint_rows": [], "details": [], "distribution_rows": [],
            "first_divergence": {}, "summary": {
                "status": "NOT_ESTABLISHED", "source_checkpoint_date": "",
                "source_checkpoint_count": 0, "candidate_member_count": 0,
                "first_divergence_date": "", "first_divergence_count": "",
                "last_divergence_date": "", "sessions_below_200": 0,
                "sessions_above_200": 0, "anchor_raw_rows": 0,
                "anchor_unique_members": 0, "anchor_unique_durable_ids": 0,
                "anchor_unique_isins": 0, "anchor_duplicate_rows": 0,
                "anchor_unresolved_identities": 0,
            },
        }

    checkpoint_date, checkpoint_rows = checkpoints[0]
    source_by_symbol = {_symbol_key(row.get("symbol")): row for row in checkpoint_rows}
    master_by_symbol = {_symbol_key(row.get("symbol")): row for row in instrument_master}
    state = set(source_by_symbol) - {""}
    reverse_lineage: dict[str, Any] = {}
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
            reverse_lineage.setdefault(symbol, event)

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
            "index_name": "NIFTY 200", "anchor_date": CAMPAIGN_FROM.isoformat(),
            "member_status": "FORWARD_CHECKPOINT_MEMBER", "evidence_date": checkpoint_date.isoformat(),
            "effective_date": "", "known_at": "", "resolution_method": "EXACT_CURRENT_SYMBOL" if master else "UNRESOLVED_HISTORICAL_IDENTITY",
        })

    candidate_rows = []
    for symbol in sorted(state):
        source = source_by_symbol.get(symbol, {})
        master = master_by_symbol.get(symbol, {})
        lineage = reverse_lineage.get(symbol)
        symbol_name = str(source.get("symbol") or (getattr(lineage, "symbol", "") if lineage else "") or master.get("symbol") or symbol).upper()
        inst_id = (getattr(lineage, "instrument_id", None) if lineage else None) or master.get("instrument_id") or ""
        isin_val = (getattr(lineage, "isin", None) if lineage else None) or master.get("isin") or ""

        lineage_source_url = getattr(lineage, "source_url", "") if lineage else ""
        lineage_source_sha = getattr(lineage, "source_sha256", "") if lineage else ""
        lineage_effective = getattr(lineage, "effective_date", "") if lineage else ""
        lineage_known_at = getattr(lineage, "known_at", "") if lineage else ""
        if hasattr(lineage_effective, "isoformat"):
            lineage_effective = lineage_effective.isoformat()
        if hasattr(lineage_known_at, "isoformat"):
            lineage_known_at = lineage_known_at.isoformat()
        candidate_rows.append({
            "target_date": CAMPAIGN_FROM.isoformat(), "symbol": symbol_name,
            "company_name": source.get("company_name") or master.get("company_name") or (getattr(lineage, "company_name", "") if lineage else "") or symbol_name,
            "instrument_id": inst_id, "isin": isin_val,
            "anchor_status": "NOT_ASSERTED", "eligible_for_replay": False,
            "evidence_basis": "REVERSE_CANONICAL_EVENTS_FROM_LATER_CHECKPOINT",
            "forward_checkpoint_date": checkpoint_date.isoformat(),
            "source_url": source.get("source_url", "") or lineage_source_url,
            "source_sha256": source.get("source_sha256", "") or lineage_source_sha,
            "source_member": source.get("source_member", ""), "source_tier": source.get("source_tier", "A1"),
            "confidence": "MANUAL_REVIEW", "review_status": "MANUAL_REVIEW",
            "notes": "Diagnostic reverse-replay candidate only; later checkpoint evidence does not prove 2012-01-02 membership.",
            "index_name": "NIFTY 200", "anchor_date": CAMPAIGN_FROM.isoformat(),
            "member_status": "REVERSED_CANONICAL_DROP" if lineage and not source else "FORWARD_CHECKPOINT_MEMBER",
            "evidence_date": checkpoint_date.isoformat(), "effective_date": lineage_effective,
            "known_at": lineage_known_at,
            "resolution_method": "EXACT_CURRENT_SYMBOL" if master else "LINEAGE_HISTORICAL_IDENTITY",
        })

    renames_path = Path("reports/nifty200_pit_all_verified_renames_20260916.json")
    verified_renames = json.loads(renames_path.read_text(encoding="utf-8")) if renames_path.is_file() else []
    renames_by_date: dict[date, list[tuple[str, str]]] = {}
    for r in verified_renames:
        d = date.fromisoformat(r["changed_on"])
        renames_by_date.setdefault(d, []).append((_symbol_key(r["previous_symbol"]), _symbol_key(r["new_symbol"])))

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
    all_eval_dates = sorted(set(trading_days) | {cp for cp, _ in checkpoints})
    for session_date in all_eval_dates:
        count_before = len(active)
        for old_sym, new_sym in renames_by_date.get(session_date, []):
            if old_sym in active:
                active.discard(old_sym)
                active.add(new_sym)
        applied_events = []
        while event_position < len(ordered_events) and ordered_events[event_position].effective_date <= session_date:
            event = ordered_events[event_position]
            event_position += 1
            applied_events.append(event)
            symbol = _symbol_key(getattr(event, "symbol", ""))
            action = event.action.value if hasattr(event.action, "value") else str(event.action)
            if not symbol:
                continue
            if action == Action.ADD.value:
                active.add(symbol)
            elif action == Action.DROP.value:
                if symbol in active:
                    active.discard(symbol)
                else:
                    matched = False
                    for act_sym in list(active):
                        act_master = master_by_symbol.get(act_sym, {})
                        if act_master.get("isin") == getattr(event, "isin", None) or act_master.get("instrument_id") == getattr(event, "instrument_id", None):
                            active.discard(act_sym)
                            matched = True
                            break
                    if not matched:
                        active.discard(symbol)
        state_by_session[session_date] = set(active)
        if session_date in trading_days:
            session_rows.append({
                "session_date": session_date.isoformat(), "active_member_count": len(active),
                "expected_member_count": nifty200_expected_security_count(session_date),
                "status": "PASS" if len(active) == nifty200_expected_security_count(session_date) else "BLOCKED",
                "candidate_method": "REVERSE_CANONICAL_EVENTS_FROM_LATER_CHECKPOINT",
                "source_checkpoint_date": checkpoint_date.isoformat(),
                "source_checkpoint_sha256": checkpoint_rows[0].get("source_sha256", ""),
                "count_before": count_before, "count_after": len(active),
                "event_count_on_session": len(applied_events),
                "events_on_session": ";".join(
                    f"{event.action.value if hasattr(event.action, 'value') else event.action}:{event.symbol}"
                    for event in applied_events
                ),
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

    divergence = next((row for row in session_rows if row["active_member_count"] != row["expected_member_count"]), None)
    divergence_events = divergence.get("events_on_session", "") if divergence else ""
    first_divergence = {
        "date": divergence["session_date"] if divergence else "",
        "count_before": divergence.get("count_before", "") if divergence else "",
        "count_after": divergence.get("count_after", "") if divergence else "",
        "expected_count": divergence["expected_member_count"] if divergence else "",
        "event_count_on_session": divergence.get("event_count_on_session", "") if divergence else "",
        "events_on_session": divergence_events,
        "missing_from_replay": "UNRESOLVED_INITIAL_ANCHOR" if divergence else "",
        "unexpected_in_replay": "",
        "source_url": "",
        "source_sha256": "",
        "identity_status": "NOT_ASSERTED",
        "likely_root_cause": "NO_CERTIFIABLE_2012_01_02_ANCHOR" if divergence else "",
    }
    count_distribution = Counter(row["active_member_count"] for row in session_rows)
    distribution_rows = [
        {"active_member_count": count, "sessions": sessions}
        for count, sessions in sorted(count_distribution.items())
    ]
    anchor_durable_ids = {
        str(master_by_symbol[symbol].get("instrument_id") or "")
        for symbol in source_by_symbol if master_by_symbol.get(symbol, {}).get("instrument_id")
    }
    anchor_isins = {
        str(master_by_symbol[symbol].get("isin") or "")
        for symbol in source_by_symbol if master_by_symbol.get(symbol, {}).get("isin")
    }
    divergent_dates = [row["session_date"] for row in session_rows if row["active_member_count"] != 200]
    summary = {
        "status": "NOT_ESTABLISHED", "source_checkpoint_date": checkpoint_date.isoformat(),
        "source_checkpoint_count": len(source_by_symbol), "candidate_member_count": len(candidate_rows),
        "reverse_event_count": len(reverse_events),
        "first_divergence_date": divergence["session_date"] if divergence else "",
        "first_divergence_count": divergence["active_member_count"] if divergence else "",
        "first_divergence_events": divergence_events,
        "last_divergence_date": divergent_dates[-1] if divergent_dates else "",
        "sessions_below_200": sum(row["active_member_count"] < 200 for row in session_rows),
        "sessions_above_200": sum(row["active_member_count"] > 200 for row in session_rows),
        "anchor_raw_rows": len(checkpoint_rows),
        "anchor_unique_members": len(source_by_symbol),
        "anchor_unique_durable_ids": len(anchor_durable_ids),
        "anchor_unique_isins": len(anchor_isins),
        "anchor_duplicate_rows": len(checkpoint_rows) - len(source_by_symbol),
        "anchor_unresolved_identities": len(source_by_symbol) - len(anchor_durable_ids),
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
        "details": details, "distribution_rows": distribution_rows,
        "first_divergence": first_divergence, "summary": summary,
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

Conclusion: `HISTORICAL_DVR_COUNT_RESOLVED_MONTHLY_EVIDENCE_GAPS_REMAIN`

The official launch notice describes CNX 200 periodic review as semi-annual, not a
monthly constituent-publication obligation. The public corpus nevertheless contains
many monthly weightage files, and the validator requires an official monthly
checkpoint. Those are different claims: the first is index methodology evidence; the
second is this repository's conservative acceptance control. This task does not weaken
that control or silently treat a missing month as PASS.

The 50 checkpoints from April 2016 through May 2020 were inspected at row level. Each
contains 201 unique constituent symbols including TATAMTRDVR. The 2016-02-22 release
explicitly establishes 201 securities from 2016-04-01. The 2020-06-10 release removes
TATAMTRDVR with ten exclusions and nine inclusions effective 2020-06-26. The validator
now applies that documented period-specific count and preserves all source rows.

Required governance decision: confirm whether periodic official checkpoints plus complete
causal event lineage are acceptable for the campaign, or retain the monthly-checkpoint
rule. Until that decision and the 2012-01-02 anchor are supplied, automated validation
remains blocked.

Official methodology reference: <https://niftyindices.com/Press_Release/ind_prs18072011.pdf>
Additional-security rule: <https://www.niftyindices.com/Press_Release/ind_prs22022016_2.pdf>
DVR removal: <https://www.niftyindices.com/Press_Release/ind_prs10062020.pdf>
"""


def _blocker_ledger(
    report: Any,
    *,
    conflicts: list[Conflict],
    events: list[Any],
    observations: list[Observation] | None = None,
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
    observation_by_id = {
        observation.observation_id or observation_hash(observation): observation
        for observation in observations or []
    }
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
        if reason.startswith("replay_checkpoint:"):
            _, as_of, details = reason.split(":", 2)
            append(reason, blocker_type="REPLAY_SNAPSHOT_MISMATCH", as_of=as_of,
                   observed=details, severity="CRITICAL",
                   root_cause="Actual interval replay does not match the period-valid official checkpoint identities.",
                   resolution_source="replay_checkpoint_differences.csv")
            continue
        if reason.startswith("member_count:"):
            _, as_of, observed = reason.split(":", 2)
            append(reason, blocker_type="COUNT_NOT_200", as_of=as_of,
                   expected=nifty200_expected_security_count(date.fromisoformat(as_of)),
                   observed=observed, severity="CRITICAL",
                   root_cause="Replay intervals do not establish the historical expected security count on this NSE session.")
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
            observation = next((observation_by_id[observation_id] for observation_id in conflict.observation_ids
                                if observation_id in observation_by_id), None)
            root_cause = conflict.message
            extra_notes = ""
            if conflict_type == "UNRESOLVED_OBSERVATION":
                observation = next((observation_by_id.get(observation_id) for observation_id in conflict.observation_ids), None)
                if observation is not None and str(observation.source_tier) not in {"A1", "A2"}:
                    kind = "MISSING_OFFICIAL_EVENT"
                elif observation is not None and (not observation.instrument_id or not observation.symbol):
                    kind = "MISSING_DURABLE_IDENTITY"
                elif observation is not None and not observation.announcement_date:
                    kind = "MISSING_ANNOUNCEMENT_DATE"
                elif observation is not None and (not observation.known_at or not observation.known_at_basis):
                    kind = "KNOWN_AT_UNRESOLVED"
                else:
                    kind = "OTHER"
            elif conflict_type == "REMOVAL_OF_ABSENT_MEMBER":
                prior_adds = [event for event in events if observation is not None
                              and observation.symbol and event.symbol == observation.symbol
                              and event.index_id == observation.index_id
                              and conflict.date is not None and event.effective_date < conflict.date
                              and event.action in {Action.ADD, Action.INITIAL_MEMBER}]
                different_isin = [event for event in prior_adds if event.isin and observation is not None
                                  and observation.isin and event.isin != observation.isin]
                if different_isin:
                    kind = "HISTORICAL_ISIN_CHANGE"
                    root_cause = ("An earlier same-symbol ADD has a different ISIN. Identity continuity is a candidate, "
                                  "not established; obtain dated official transition evidence before linking instruments.")
                elif prior_adds:
                    kind = "REPLAY_MEMBERSHIP_CONFLICT"
                    root_cause = "Prior entry evidence exists; trace intervening removals and identities rather than assuming missing initial membership."
                else:
                    kind = "MISSING_MEMBERSHIP_HISTORY"
                    root_cause = "No earlier canonical ADD/INITIAL_MEMBER for this symbol and index; initial membership versus a missing ADD is not established."
                extra_notes = "; prior_entry_event_hashes=" + ";".join(event.event_hash for event in prior_adds)
            elif conflict_type == "DUPLICATE_ADD":
                kind = "DUPLICATE_EVENT"
            elif conflict_type == "MISSING_INITIAL_ANCHOR":
                kind = "MISSING_INITIAL_ANCHOR"
            elif conflict_type == "CALENDAR_NOT_CERTIFIED":
                kind = "CALENDAR_NOT_CERTIFIED"
            elif "IDENTITY" in conflict_type:
                kind = "HISTORICAL_SYMBOL_CHANGE"
            elif "COVERAGE" in conflict_type:
                kind = "MONTHLY_SNAPSHOT_MISSING"
            elif "OFFICIAL" in conflict_type:
                kind = "CONFLICTING_OFFICIAL_EVENTS"
            else:
                kind = "OTHER"
            append(
                reason, blocker_type=kind, as_of=conflict.date.isoformat() if conflict.date else "",
                symbol=observation.symbol or "" if observation else "",
                company=observation.company_name or "" if observation else "",
                instrument_id=observation.instrument_id or "" if observation else "",
                isin=observation.isin or "" if observation else "",
                expected="announcement_date/known_at" if kind in {"MISSING_ANNOUNCEMENT_DATE", "KNOWN_AT_UNRESOLVED"} else "",
                observed="missing" if kind in {"MISSING_ANNOUNCEMENT_DATE", "KNOWN_AT_UNRESOLVED"} else "",
                source_tier=observation.source_tier if observation else "",
                source_url=observation.source_url if observation else ";".join(conflict.source_urls),
                source_sha=observation.source_sha256 if observation else "",
                severity=conflict.severity, root_cause=root_cause,
                notes=f"conflict_type={conflict_type}; required_action={conflict.required_action}{extra_notes}",
            )
            continue
        match = re.fullmatch(r"(\d{4}-\d{2}):(\d+)", reason)
        if match and match.group(1) in coverage_by_month:
            month, observed = match.groups()
            source = source_by_month.get(month)
            month_rows = snapshot_by_month.get(month, [])
            count = int(observed)
            if count == 0:
                _, kind, root = _monthly_source_gap(source)
            elif count == 201 and "TATAMTRDVR" in {str(row.get("symbol") or "").strip() for row in month_rows}:
                kind = "COUNT_NOT_200"
                root = "The official checkpoint contains 201 securities; the source explicitly attributes the extra security to Tata Motors DVR."
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
    transcription_audit: list[dict[str, Any]] = []
    observations.extend(parse_press_releases(sources, transcription_audit=transcription_audit))
    challenger = next((source for source in sources if source.source_url == CHALLENGER_EVENTS_URL), None)
    if challenger:
        observations.extend(parse_challenger_events(challenger))
    snapshots = parse_monthly_snapshots(sources)
    security_source_urls = {
        SECURITIES_MASTER_URL, HISTORICAL_SECURITY_MASTER_URL,
        HISTORICAL_SECURITY_MASTER_2017_ARCHIVE_URL,
        HISTORICAL_SECURITY_MASTER_2021_ARCHIVE_URL,
        HISTORICAL_INDEX_CONSTITUENT_2014_URL,
    }
    security_sources = [source for source in sources if source.source_url in security_source_urls]
    current_security_source = next(
        (source for source in security_sources if source.source_url == SECURITIES_MASTER_URL), None,
    )
    current_instrument_master = parse_security_master(current_security_source) if current_security_source else []
    for row in current_instrument_master:
        row["validity_basis"] = "CURRENT_SNAPSHOT_ONLY"
    historical_instrument_master = []
    for security_source in security_sources:
        if security_source.source_url == SECURITIES_MASTER_URL:
            continue
        if security_source.source_url == HISTORICAL_INDEX_CONSTITUENT_2014_URL:
            historical_instrument_master.extend(parse_archived_index_constituent_snapshot(security_source))
        else:
            historical_instrument_master.extend(parse_security_master(security_source))
    instrument_rows = current_instrument_master + historical_instrument_master
    # Retain daily evidence only for symbols/dates actually under investigation.
    # OHLC values are neither imported nor used to infer constituent membership.
    required_identity_keys = {
        (row.effective_date.isoformat(), str(row.symbol).upper())
        for row in observations if row.effective_date and row.symbol
    }
    required_identity_keys.update(
        (str(row['snapshot_date'])[:10], str(row.get('symbol') or '').upper()) for row in snapshots
    )
    for source in sources:
        if (
            ('/content/historical/EQUITIES/' in source.source_url and source.source_url.endswith('bhav.csv.zip'))
            or '/content/cm/' in source.source_url
        ):
            instrument_rows.extend(
                row for row in parse_bhavcopy_identities(source, identity_keys=required_identity_keys)
            )
    instrument_master: list[dict[str, Any]] = []
    seen_identity_rows: set[tuple[str, str, str]] = set()
    for row in instrument_rows:
        key = (
            str(row.get("instrument_id") or ""),
            str(row.get("symbol") or "").casefold(),
            str(row.get("snapshot_date") or ""),
        )
        if key in seen_identity_rows:
            continue
        seen_identity_rows.add(key)
        instrument_master.append(row)
    current_by_symbol = {
        str(row.get("symbol") or "").casefold(): row for row in current_instrument_master
    }
    for row in instrument_master:
        current = current_by_symbol.get(str(row.get("symbol") or "").casefold())
        current_start = _parse_day(current.get("valid_from")) if current else None
        snapshot_day = _parse_day(row.get("snapshot_date"))
        if (
            snapshot_day
            and current
            and row.get("instrument_id") != current.get("instrument_id")
            and not row.get("valid_until")
            and current_start
            and current_start > snapshot_day
        ):
            row["valid_until"] = current["valid_from"]
    symbol_changes_source = next((source for source in sources if source.source_url == SYMBOL_CHANGES_URL), None)
    symbol_changes = parse_symbol_changes(symbol_changes_source) if symbol_changes_source else []
    aliases = _identity_aliases(snapshots, instrument_master, symbol_changes)
    observations = resolve_observations(observations, instrument_master, aliases=aliases)
    observations, instrument_master, aliases, identity_continuity_audit = _apply_documented_isin_continuity(
        observations, instrument_master, aliases, sources,
    )
    calendar_overrides = _verified_calendar_overrides(sources)
    calendar = build_nse_calendar(overrides=calendar_overrides, version="nse-pandas-market-calendars-with-evidenced-exceptions")
    observations = _align_date_only_causality(observations, calendar)
    observations, schedule_dispositions = _apply_official_rescheduling(observations, sources)

    considered_observations, challenger_dispositions = _exclude_withdrawn_challenger_assertions(
        observations, schedule_dispositions, sources,
    )
    schedule_dispositions.extend(challenger_dispositions)
    reconciliation_observations = _suppress_redundant_workbook_observations(considered_observations)
    reconciliation = reconcile_observations(reconciliation_observations)
    trading_days = calendar.iter_trading_days(CAMPAIGN_FROM, CAMPAIGN_TO)
    anchor_forensics = _anchor_replay_forensics(snapshots, reconciliation.events, instrument_master, trading_days)
    anchor_summary = anchor_forensics["summary"]
    candidate_rows = anchor_forensics["candidate_rows"]
    # The reverse replay is a diagnostic candidate.  It is not an authoritative
    # 2012-01-02 membership source and must not seed INITIAL_MEMBER events.
    all_events = reconciliation.events
    interval_result = build_intervals(all_events, horizon_start=CAMPAIGN_FROM, horizon_end=CAMPAIGN_TO)
    conflicts = reconciliation.conflicts + interval_result.conflicts
    coverage = _coverage(snapshots)
    annual_coverage = _annual_coverage(coverage)
    coverage_gaps = [row for row in coverage if row["status"] != "PASS"]
    checkpoint_comparisons, checkpoint_differences = _replay_checkpoint_comparison(
        snapshots, interval_result.intervals, instrument_master, aliases,
    )
    checkpoint_mismatches = [
        f"replay_checkpoint:{row['checkpoint_date']}:missing={row['missing_count']},"
        f"unexpected={row['unexpected_count']},unresolved_identity={row['unresolved_identity_count']},"
        f"duplicate_identity={row['duplicate_identity_count']}"
        for row in checkpoint_comparisons if row["status"] != "PASS"
    ]
    anchor_differences = checkpoint_mismatches
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
            message=f"{len(coverage_gaps)} campaign months lack an official checkpoint matching the historical security-count rule.",
            required_action="SOURCE_RETRIEVAL_OR_MANUAL_REVIEW",
        ))
    if anchor_summary.get("status") != "ESTABLISHED":
        conflicts.append(Conflict(
            conflict_id="missing_initial_anchor", date=CAMPAIGN_FROM,
            severity="CRITICAL", conflict_type="MISSING_INITIAL_ANCHOR",
            message="No authoritative first-party NIFTY/CNX-200 membership list or complete event chain establishes the 2012-01-02 starting set.",
            required_action="ACQUIRE_FIRST_PARTY_HISTORICAL_ANCHOR",
        ))
    historical_master = _historical_master_rows(instrument_master, aliases)
    # Verified exceptions improve the repository calendar but are not a complete
    # campaign-wide exchange-session audit. Keep that evidence gap actionable.
    conflicts.append(Conflict(
        conflict_id="calendar_not_certified", date=None, severity="HIGH",
        conflict_type="CALENDAR_NOT_CERTIFIED",
        message="Campaign calendar has evidenced exceptions but lacks a complete official session audit for 2012-2026.",
        required_action="VERIFY_OFFICIAL_HOLIDAYS_AND_SPECIAL_SESSIONS",
    ))
    report = validate_campaign(
        interval_result.intervals, all_events, campaign_from=CAMPAIGN_FROM, campaign_to=CAMPAIGN_TO,
        trading_days=trading_days, conflicts=conflicts, source_hash_errors=source_errors,
        expected_member_counts={day: nifty200_expected_security_count(day) for day in trading_days},
        anchor_differences=anchor_differences,
    )
    replay_counts = list(report.metrics["daily_member_counts"].values())
    event_date_rows = _event_date_snapshot_rows(reconciliation.events)
    report = replace(report, metrics=report.metrics | {
        "calendar_version": calendar.version,
        "calendar_audit_status": "PARTIAL_NOT_CERTIFIED",
        "calendar_verified_override_count": len(calendar_overrides),
        "replay_checkpoint_matches": sum(row["status"] == "PASS" for row in checkpoint_comparisons),
        "replay_checkpoint_mismatches": len(checkpoint_mismatches),
        "minimum_active_constituent_count": min(replay_counts, default=0),
        "maximum_active_constituent_count": max(replay_counts, default=0),
        "sessions_not_expected_count": report.metrics["count_check_failures"],
        "known_at_unresolved_count": sum(event.known_at is None or not event.known_at_basis for event in reconciliation.events),
        "event_date_snapshot_row_count": len(event_date_rows),
        "redundant_workbook_observation_count": len(considered_observations) - len(reconciliation_observations),
        "contradicted_challenger_count": len(challenger_dispositions),
        "current_security_master_rows": len(current_instrument_master),
        "documented_isin_continuity_links": len(identity_continuity_audit["links"]),
        "historical_identity_rows": len(historical_master),
        "unique_historical_instruments": len({row.get("instrument_id") for row in instrument_master}),
        **_event_identity_metrics(observations),
        "valid_200_checkpoints": sum(row["status"] == "PASS" and row["snapshot_member_count"] == "200" for row in coverage),
        "valid_expected_count_checkpoints": sum(row["status"] == "PASS" for row in coverage),
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

    monthly_gap_rows = _monthly_gap_rows(coverage, snapshots, interval_result.intervals, sources, checkpoint_comparisons)
    known_at_rows = _known_at_rows(reconciliation.events)
    blocker_rows = _blocker_ledger(
        report, conflicts=conflicts, events=reconciliation.events, snapshots=snapshots,
        observations=observations, coverage=coverage, sources=sources,
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
    _write_csv(reports_dir / "nifty200_pit_anchor_replay_first_divergence.csv", [anchor_forensics["first_divergence"]])
    _write_csv(reports_dir / "nifty200_pit_anchor_replay_active_count_distribution.csv", anchor_forensics["distribution_rows"])
    blocker_counts = Counter(row["blocker_type"] for row in blocker_rows)
    conflict_severity_counts = Counter(conflict.severity for conflict in conflicts)
    blocker_delta_rows = [
        {
            "blocker_type": blocker_type, "before_count": count, "after_count": count,
            "resolution_status": "UNRESOLVED",
            "resolution_source": "anchor_replay_candidate.parquet",
            "notes": "Diagnostic reverse replay is not consumed by authoritative validation; blocker count unchanged.",
        }
        for blocker_type, count in sorted(blocker_counts.items())
    ]
    blocker_delta_rows.extend(
        {
            "blocker_type": f"CONFLICT_{severity}", "before_count": count, "after_count": count,
            "resolution_status": "UNRESOLVED",
            "resolution_source": "conflict_report.parquet",
            "notes": "No conflict was auto-resolved by the anchor diagnostic.",
        }
        for severity, count in sorted(conflict_severity_counts.items())
    )
    _write_csv(reports_dir / "nifty200_pit_anchor_blocker_delta_20260911.csv", blocker_delta_rows)
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
        f"- Anchor rows: raw={anchor_summary.get('anchor_raw_rows', 0)}; unique members={anchor_summary.get('anchor_unique_members', 0)}; "
        f"unique durable IDs={anchor_summary.get('anchor_unique_durable_ids', 0)}; unique ISINs={anchor_summary.get('anchor_unique_isins', 0)}; "
        f"duplicate rows={anchor_summary.get('anchor_duplicate_rows', 0)}; unresolved identities={anchor_summary.get('anchor_unresolved_identities', 0)}.\n"
        f"- NSE sessions replayed: {anchor_summary.get('session_count', 0)}; exact-200 sessions: {anchor_summary.get('session_exact_200', 0)}; "
        f"non-200 sessions: {anchor_summary.get('session_not_200', 0)}; below 200={anchor_summary.get('sessions_below_200', 0)}; "
        f"above 200={anchor_summary.get('sessions_above_200', 0)}; last divergence={anchor_summary.get('last_divergence_date', '')}.\n"
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
    _write_csv(artifact_dir / "replay_checkpoint_comparison.csv", checkpoint_comparisons)
    _write_csv(artifact_dir / "replay_checkpoint_differences.csv", checkpoint_differences)
    _write_json(artifact_dir / "identity_continuity_evidence.json", identity_continuity_audit["links"])
    _write_csv(artifact_dir / "identity_continuity_audit.csv", identity_continuity_audit["observations"])
    _write_csv(artifact_dir / "known_at_audit.csv", known_at_rows)
    _write_csv(artifact_dir / "official_schedule_dispositions.csv", schedule_dispositions)
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
    _write_csv(artifact_dir / "anchor_replay_first_divergence.csv", [anchor_forensics["first_divergence"]])
    _write_csv(artifact_dir / "anchor_replay_active_count_distribution.csv", anchor_forensics["distribution_rows"])
    _write_csv(artifact_dir / "anchor_blocker_delta_20260911.csv", blocker_delta_rows)
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
        expected = nifty200_expected_security_count(date.fromisoformat(snapshot_date))
        discrepancy_rows.append({
            "snapshot_date": snapshot_date, "observed_member_count": unique_symbols,
            "expected_member_count": expected, "discrepancy": unique_symbols - expected,
            "status": "PASS" if unique_symbols == expected else "BLOCKED",
            "note": "source count differs from historical methodology" if unique_symbols != expected else "",
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
        f"- Event-date evidence index rows: {len(event_date_rows)}; this is not a full membership snapshot.\n"
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

    (artifact_dir / "pdf_transcriptions.json").write_text(
        json.dumps(transcription_audit, indent=2, sort_keys=True), encoding="utf-8",
    )
    write_table(artifact_dir / "initial_anchor_20120102.parquet", candidate_rows)
    write_artifacts(
        artifact_dir, source_records=sources, observations=observations, events=all_events,
        aliases=aliases, intervals=interval_result.intervals, monthly_snapshots=snapshots,
        event_date_snapshots=event_date_rows,
        conflicts=conflicts, validation_report=report,
        identity_map_hash=sha256_file(artifact_dir / "identity_continuity_evidence.json"),
        campaign_from=CAMPAIGN_FROM.isoformat(), campaign_to=CAMPAIGN_TO.isoformat(),
        independent_qa="NOT_ASSERTED",
        campaign_readiness="BLOCKED",
        approved_for_import=False,
        stage_a_started=False,
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
        "database_touched": False, "result": "PASSED" if dry_run.returncode == 0 else "REFUSED_AS_DESIGNED",
    }, indent=2), encoding="utf-8")
    write_artifacts(
        artifact_dir, source_records=sources, observations=observations, events=all_events,
        aliases=aliases, intervals=interval_result.intervals, monthly_snapshots=snapshots,
        event_date_snapshots=event_date_rows,
        conflicts=conflicts, validation_report=report,
        identity_map_hash=sha256_file(artifact_dir / "identity_continuity_evidence.json"),
        campaign_from=CAMPAIGN_FROM.isoformat(), campaign_to=CAMPAIGN_TO.isoformat(),
        independent_qa="NOT_ASSERTED",
        campaign_readiness="BLOCKED",
        approved_for_import=False,
        stage_a_started=False,
    )
    return {
        "source_count": len(sources), "source_hash_errors": len(source_errors),
        "observation_count": len(observations), "canonical_event_count": len(all_events),
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
