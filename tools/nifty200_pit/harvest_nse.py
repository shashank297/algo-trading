"""Harvest official NSE/NSE Indices pages into the immutable source catalogue."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlparse

import requests

from tools.nifty200_pit.parse_html import extract_links, is_index_change_candidate
from tools.nifty200_pit.source_catalogue import SourceCatalogue

DEFAULT_ARCHIVE = "https://www.niftyindices.com/press-release"


def _extension(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".pdf", ".csv", ".xls", ".xlsx", ".zip", ".html"}:
        return suffix
    if "pdf" in content_type.lower():
        return ".pdf"
    if "html" in content_type.lower():
        return ".html"
    return ".bin"


def harvest_urls(
    root: str | Path,
    urls: list[str],
    *,
    session: requests.Session | None = None,
    timeout: tuple[float, float] = (10, 90),
) -> list:
    catalogue = SourceCatalogue(Path(root) / "data" / "raw" / "nifty200_pit_public_sources")
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", "Nifty200PITResearch/1.0 (provenance-preserving)")
    for url in urls:
        response = client.get(url, timeout=timeout)
        response.raise_for_status()
        catalogue.add_bytes(response.content, source_url=url, extension=_extension(url, response.headers.get("content-type", "")),
                            content_type=response.headers.get("content-type", ""), http_status=response.status_code,
                            etag=response.headers.get("etag"), last_modified=response.headers.get("last-modified"),
                            retrieved_at=datetime.now(timezone.utc).isoformat())
    catalogue.save()
    return catalogue.records

def discover_press_release_urls(html: str, *, base_url: str = DEFAULT_ARCHIVE) -> list[str]:
    return [url for title, url in extract_links(html, base_url=base_url) if is_index_change_candidate(title) or re.search(r"\.pdf(?:$|\?)", url, re.I)]


def harvest_nse(root: str | Path, *, archive_url: str = DEFAULT_ARCHIVE, session: requests.Session | None = None) -> list:
    client = session or requests.Session()
    response = client.get(archive_url, timeout=(10, 90))
    response.raise_for_status()
    urls = [archive_url] + discover_press_release_urls(response.text, base_url=archive_url)
    return harvest_urls(root, list(dict.fromkeys(urls)), session=client)
