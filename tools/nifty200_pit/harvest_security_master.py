"""Harvest the official NSE equity securities master as immutable evidence."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.source_catalogue import SourceCatalogue

SECURITIES_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
REQUIRED_COLUMNS = {
    "SYMBOL", "NAME OF COMPANY", "DATE OF LISTING", "ISIN NUMBER",
}


def _validate_csv(data: bytes) -> None:
    sample = data[:512].lstrip().lower()
    if sample.startswith((b"<html", b"<!doctype", b"access denied")):
        raise ValueError("NSE securities master response is HTML or an access-denied page")
    try:
        header = next(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
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


def main() -> int:
    record = harvest()
    print(json.dumps(record.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
