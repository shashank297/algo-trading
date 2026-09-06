from __future__ import annotations

import argparse
import csv
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; Nifty200PITResearch/1.0; provenance-preserving research)"
TIMEOUT = 40
PARSER_VERSION = "zero-cost-acquire-v1"

INDEX_XLS = "https://archives.nseindia.com/content/indices/IndexInclExcl.xls"
PRESS_ARCHIVE = "https://www.niftyindices.com/press-release"
MONTHLY_BASE = "https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/"
START = "2012-01-02"
END = "2026-08-20"

KEEP_TITLE = re.compile(
    r"(replacements?\s+in\s+indices|index\s+changes|change\s+in\s+indices|"
    r"corporate.*nifty\s+indices|exclusion.*nifty\s+indices|inclusion.*nifty\s+indices|"
    r"launch.*cnx\s*200)",
    re.I,
)
DROP_TITLE = re.compile(
    r"(fixed\s+income|nifty\s+ipo|sme\s+emerge|g-sec|bond|debt\s+indices)",
    re.I,
)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def get(session: requests.Session, url: str, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last or RuntimeError(url)

def save_response(r, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # Do not overwrite provenance. Reuse identical file; version if bytes differ.
        new_hash = hashlib.sha256(r.content).hexdigest()
        old_hash = sha256_file(dest)
        if new_hash != old_hash:
            stem, suffix = dest.stem, dest.suffix
            dest = dest.with_name(f"{stem}_{datetime.now().strftime('%Y%m%dT%H%M%S')}{suffix}")
    if not dest.exists():
        dest.write_bytes(r.content)
    return {
        "local_path": str(dest),
        "sha256": sha256_file(dest),
        "file_size": dest.stat().st_size,
        "content_type": r.headers.get("content-type", ""),
    }

def month_range():
    year, month = 2013, 4
    while (year, month) <= (2022, 3):
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--sleep", type=float, default=0.25, help="polite delay between requests")
    args = ap.parse_args()

    root = Path(args.root)
    raw = root / "data" / "raw" / "nifty200_pit_public_sources"
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = raw / "source_manifest.csv"

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "*/*"})

    rows = []

    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # 1) Official inclusion/exclusion workbook
    try:
        r = get(session, INDEX_XLS)
        meta = save_response(r, raw / "index_inclusion_exclusion" / "IndexInclExcl.xls")
        rows.append({
            "source_url": INDEX_XLS,
            "source_organization": "NSE/NSE Indices",
            "document_name": "IndexInclExcl.xls",
            "downloaded_at": now(),
            "document_date": "",
            "coverage_hint": "historical inclusion/exclusion workbook",
            "source_type": "official_workbook",
            "status": "downloaded",
            **meta,
        })
    except Exception as e:
        rows.append({
            "source_url": INDEX_XLS, "source_organization": "NSE/NSE Indices",
            "document_name": "IndexInclExcl.xls", "downloaded_at": now(),
            "document_date": "", "coverage_hint": "historical inclusion/exclusion workbook",
            "source_type": "official_workbook", "status": f"FAILED: {e}",
            "local_path": "", "sha256": "", "file_size": "", "content_type": "",
        })

    # 2) Official monthly market-cap / weightage ZIPs, Apr-2013..Mar-2022.
    mons = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for year, month in month_range():
        mon = mons[month - 1]
        fn = f"indices_data{mon}{year}.zip"
        url = MONTHLY_BASE + fn
        try:
            r = get(session, url, retries=2)
            meta = save_response(r, raw / "monthly_weightage" / fn)
            status = "downloaded"
        except Exception as e:
            meta = {"local_path":"", "sha256":"", "file_size":"", "content_type":""}
            status = f"FAILED: {e}"
        rows.append({
            "source_url": url, "source_organization": "NSE Indices",
            "document_name": fn, "downloaded_at": now(),
            "document_date": f"{year:04d}-{month:02d}",
            "coverage_hint": "monthly index constituent/weightage checkpoint",
            "source_type": "official_monthly_zip", "status": status, **meta,
        })
        time.sleep(args.sleep)

    # 3) Press-release archive. The archive page itself carries historical links.
    try:
        archive = get(session, PRESS_ARCHIVE)
        archive_meta = save_response(archive, raw / "press_releases" / "press_release_archive.html")
        rows.append({
            "source_url": PRESS_ARCHIVE, "source_organization": "NSE Indices",
            "document_name": "press_release_archive.html", "downloaded_at": now(),
            "document_date": "", "coverage_hint": f"{START}..{END}",
            "source_type": "official_press_archive", "status": "downloaded", **archive_meta,
        })

        soup = BeautifulSoup(archive.text, "html.parser")
        seen = set()
        candidates = []
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text(" ", strip=True).split())
            href = urljoin(PRESS_ARCHIVE, a["href"])
            if not title or href in seen:
                continue
            seen.add(href)
            if KEEP_TITLE.search(title) and not DROP_TITLE.search(title):
                candidates.append((title, href))

        for idx, (title, href) in enumerate(candidates, 1):
            # Restrict to NSE/Nifty domains and likely PDF/press-release pages.
            if "niftyindices.com" not in href.lower() and "nseindia.com" not in href.lower():
                continue
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(href.split("?")[0]).name or f"release_{idx}")
            try:
                r = get(session, href, retries=2)
                meta = save_response(r, raw / "press_releases" / "candidates" / safe)
                status = "downloaded"
            except Exception as e:
                meta = {"local_path":"", "sha256":"", "file_size":"", "content_type":""}
                status = f"FAILED: {e}"
            rows.append({
                "source_url": href, "source_organization": "NSE Indices",
                "document_name": title, "downloaded_at": now(),
                "document_date": "", "coverage_hint": f"{START}..{END}",
                "source_type": "official_press_release_candidate", "status": status, **meta,
            })
            time.sleep(args.sleep)
    except Exception as e:
        rows.append({
            "source_url": PRESS_ARCHIVE, "source_organization": "NSE Indices",
            "document_name": "press_release_archive", "downloaded_at": now(),
            "document_date": "", "coverage_hint": f"{START}..{END}",
            "source_type": "official_press_archive", "status": f"FAILED: {e}",
            "local_path": "", "sha256": "", "file_size": "", "content_type": "",
        })

    fields = [
        "source_url","source_organization","document_name","downloaded_at","document_date",
        "coverage_hint","source_type","status","local_path","sha256","file_size","content_type"
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote manifest: {manifest_path}")
    print(f"Records: {len(rows)}")
    print("No trading workflow or trading database was touched.")

if __name__ == "__main__":
    main()
