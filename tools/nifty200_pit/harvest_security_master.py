"""Harvest the official NSE equity securities master as immutable evidence."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.source_catalogue import SourceCatalogue

SECURITIES_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
HISTORICAL_SECURITY_MASTER_URL = "http://nseindia.com/content/equities/EQUITY_L.csv"
HISTORICAL_SECURITY_MASTER_ARCHIVE_URL = (
    "https://web.archive.org/web/20111030150304id_/"
    "http://nseindia.com/content/equities/EQUITY_L.csv"
)
HISTORICAL_SECURITY_MASTER_2017_ARCHIVE_URL = (
    "https://web.archive.org/web/20170704082238id_/"
    "https://www.nseindia.com/content/equities/EQUITY_L.csv"
)
HISTORICAL_SECURITY_MASTER_2021_ARCHIVE_URL = (
    "https://web.archive.org/web/20210516062344id_/"
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)
SYMBOL_CHANGES_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
REQUIRED_COLUMNS = {
    "SYMBOL", "NAME OF COMPANY", "DATE OF LISTING", "ISIN NUMBER",
}


def bhavcopy_url(session_date: date) -> str:
    """Return the free official NSE cash bhavcopy URL for a session."""
    if session_date >= date(2024, 7, 8):
        return (
            "https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{session_date:%Y%m%d}_F_0000.csv.zip"
        )
    filename = f"cm{session_date.strftime('%d%b%Y').upper()}bhav.csv.zip"
    return (
        "https://archives.nseindia.com/content/historical/EQUITIES/"
        f"{session_date.year}/{session_date.strftime('%b').upper()}/{filename}"
    )


def _validate_csv(data: bytes) -> None:
    sample = data[:512].lstrip().lower()
    if sample.startswith((b"<html", b"<!doctype", b"access denied")):
        raise ValueError("NSE securities master response is HTML or an access-denied page")
    try:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
        header = next(csv.reader(io.StringIO(text)))
    except (UnicodeDecodeError, StopIteration, csv.Error) as exc:
        raise ValueError("NSE securities master response is not valid CSV") from exc
    columns = {column.strip().upper() for column in header}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise ValueError(f"NSE securities master is missing columns: {sorted(missing)}")


def _append_record(path: Path, record: SourceRecord) -> None:
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not isinstance(existing, list):
        raise ValueError(f"Source catalogue must be a JSON list: {path}")
    key = (record.source_url, record.source_sha256)
    if any((row.get("source_url"), row.get("source_sha256")) == key for row in existing):
        return
    existing.append(record.to_dict())
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def harvest(root: str | Path = ".", *, timeout: int = 30) -> SourceRecord:
    root = Path(root).resolve()
    request = Request(
        SECURITIES_MASTER_URL,
        headers={"User-Agent": "nifty200-pit-evidence-harvester/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = getattr(response, "status", None)
            headers = response.headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to retrieve official NSE securities master: {exc}") from exc
    if status is not None and not 200 <= status < 300:
        raise RuntimeError(f"Official NSE securities master returned HTTP {status}")
    _validate_csv(data)
    catalogue_root = root / "data/raw/nifty200_pit_public_sources"
    catalogue = SourceCatalogue(catalogue_root)
    record = catalogue.add_bytes(
        data,
        source_url=SECURITIES_MASTER_URL,
        extension=".csv",
        content_type=headers.get("Content-Type", "text/csv"),
        http_status=status,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        source_tier="A1",
    )
    _append_record(catalogue_root / "source_catalogue.json", record)
    return record


def harvest_symbol_changes(root: str | Path = ".", *, timeout: int = 30) -> SourceRecord:
    """Harvest NSE's explicit historical symbol-change table."""
    root = Path(root).resolve()
    request = Request(
        SYMBOL_CHANGES_URL,
        headers={"User-Agent": "nifty200-pit-evidence-harvester/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = getattr(response, "status", None)
            headers = response.headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to retrieve official NSE symbol changes: {exc}") from exc
    if status is not None and not 200 <= status < 300:
        raise RuntimeError(f"Official NSE symbol changes returned HTTP {status}")
    if not data or data.lstrip().startswith((b"<html", b"<!doctype")):
        raise ValueError("NSE symbol changes response is not valid CSV evidence")
    catalogue_root = root / "data/raw/nifty200_pit_public_sources"
    catalogue = SourceCatalogue(catalogue_root)
    record = catalogue.add_bytes(
        data,
        source_url=SYMBOL_CHANGES_URL,
        extension=".csv",
        content_type=headers.get("Content-Type", "text/csv"),
        http_status=status,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        source_tier="A1",
    )
    _append_record(catalogue_root / "source_catalogue.json", record)
    return record


def harvest_historical(root: str | Path = ".", *, timeout: int = 60) -> SourceRecord:
    """Harvest an archived official NSE security master snapshot."""
    root = Path(root).resolve()
    request = Request(
        HISTORICAL_SECURITY_MASTER_ARCHIVE_URL,
        headers={"User-Agent": "nifty200-pit-evidence-harvester/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = getattr(response, "status", None)
            headers = response.headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to retrieve archived NSE securities master: {exc}") from exc
    if status is not None and not 200 <= status < 300:
        raise RuntimeError(f"Archived NSE securities master returned HTTP {status}")
    _validate_csv(data)
    catalogue_root = root / "data/raw/nifty200_pit_public_sources"
    catalogue = SourceCatalogue(catalogue_root)
    record = catalogue.add_bytes(
        data,
        source_url=HISTORICAL_SECURITY_MASTER_URL,
        archive_url=HISTORICAL_SECURITY_MASTER_ARCHIVE_URL,
        extension=".csv",
        content_type=headers.get("Content-Type", "text/csv"),
        http_status=status,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
        document_date="2011-10-30",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        source_tier="A2",
    )
    _append_record(catalogue_root / "source_catalogue.json", record)
    return record


def harvest_historical_snapshot(
    root: str | Path = ".", *, archive_url: str, document_date: str, timeout: int = 60,
) -> SourceRecord:
    """Harvest a specified archived official NSE security master snapshot."""
    root = Path(root).resolve()
    request = Request(archive_url, headers={"User-Agent": "nifty200-pit-evidence-harvester/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = getattr(response, "status", None)
            headers = response.headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to retrieve archived NSE securities master: {exc}") from exc
    if status is not None and not 200 <= status < 300:
        raise RuntimeError(f"Archived NSE securities master returned HTTP {status}")
    _validate_csv(data)
    catalogue_root = root / "data/raw/nifty200_pit_public_sources"
    catalogue = SourceCatalogue(catalogue_root)
    record = catalogue.add_bytes(
        data,
        source_url=archive_url,
        archive_url=archive_url,
        extension=".csv",
        content_type=headers.get("Content-Type", "text/csv"),
        http_status=status,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
        document_date=document_date,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        source_tier="A2",
    )
    _append_record(catalogue_root / "source_catalogue.json", record)
    return record


def harvest_official_document(
    root: str | Path = ".", *, source_url: str, document_date: str | None = None,
    source_tier: str = "A1", timeout: int = 60,
) -> SourceRecord:
    """Harvest a public first-party document into the immutable source catalogue."""
    root = Path(root).resolve()
    request = Request(source_url, headers={"User-Agent": "nifty200-pit-evidence-harvester/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = getattr(response, "status", None)
            headers = response.headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to retrieve official document: {exc}") from exc
    if status is not None and not 200 <= status < 300:
        raise RuntimeError(f"Official document returned HTTP {status}")
    if not data or data.lstrip().startswith((b"<html", b"<!doctype")):
        raise ValueError("Official document response is HTML, not evidence")
    extension = ".pdf" if source_url.casefold().endswith(".pdf") else ".bin"
    catalogue_root = root / "data/raw/nifty200_pit_public_sources"
    record = SourceCatalogue(catalogue_root).add_bytes(
        data, source_url=source_url, extension=extension, source_tier=source_tier,
        document_date=document_date, http_status=status,
        content_type=headers.get("Content-Type", ""),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    _append_record(catalogue_root / "source_catalogue.json", record)
    return record


def harvest_bhavcopy_identity(
    root: str | Path = ".", *, session_date: date, timeout: int = 30,
) -> SourceRecord:
    """Acquire official daily ISIN evidence, not index membership or price imports."""
    url = bhavcopy_url(session_date)
    request = Request(url, headers={"User-Agent": "nifty200-pit-evidence-harvester/1.0"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        status = getattr(response, "status", None)
        headers = response.headers
    if status is not None and not 200 <= status < 300:
        raise RuntimeError(f"Official NSE bhavcopy returned HTTP {status}")
    observed_rows = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.namelist():
            if not member.lower().endswith(".csv"):
                continue
            reader = csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig")))
            fields = {str(field).strip().casefold() for field in reader.fieldnames or []}
            required = (
                {"symbol", "series", "timestamp", "isin"}
                if session_date < date(2024, 7, 8)
                else {"tckrsymb", "sctysrs", "traddt", "isin"}
            )
            if not required.issubset(fields):
                raise ValueError("Bhavcopy is missing dated identity columns")
            for row in reader:
                normalized = {str(key).strip().casefold(): value for key, value in row.items() if key is not None}
                raw_date = str(normalized.get("timestamp") or normalized.get("traddt") or "").strip()
                try:
                    observed_date = datetime.strptime(raw_date, "%d-%b-%Y").date()
                except ValueError:
                    observed_date = date.fromisoformat(raw_date[:10])
                if observed_date != session_date:
                    raise ValueError("Bhavcopy timestamp disagrees with requested session")
                observed_rows += 1
    if not observed_rows:
        raise ValueError("Bhavcopy contains no dated identity rows")
    catalogue_root = Path(root).resolve() / "data/raw/nifty200_pit_public_sources"
    record = SourceCatalogue(catalogue_root).add_bytes(
        data, source_url=url, extension=".zip", source_tier="A1",
        document_date=session_date.isoformat(), http_status=status,
        content_type=headers.get("Content-Type", "application/zip"),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    _append_record(catalogue_root / "source_catalogue.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bhavcopy-date", type=date.fromisoformat)
    parser.add_argument("--document-url")
    parser.add_argument("--document-date")
    args = parser.parse_args()
    if args.document_url:
        record = harvest_official_document(source_url=args.document_url, document_date=args.document_date)
    else:
        record = harvest_bhavcopy_identity(session_date=args.bhavcopy_date) if args.bhavcopy_date else harvest()
    print(json.dumps(record.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
