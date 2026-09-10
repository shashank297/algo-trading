"""Discover archived official artifacts through the Wayback CDX API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests


def discover_captures(
    original_url: str,
    *,
    cdx_url: str = "https://web.archive.org/cdx/search/cdx",
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    client = session or requests.Session()
    response = client.get(cdx_url, params={"url": original_url, "output": "json", "filter": "statuscode:200", "fl": "timestamp,original,mimetype,statuscode,digest,length"}, timeout=(10, 90))
    response.raise_for_status()
    payload = response.json()
    if not payload:
        return []
    header, *items = payload
    return [dict(zip(header, row)) for row in items]


def wayback_url(capture: dict[str, Any]) -> str:
    return "https://web.archive.org/web/{timestamp}id_/{original}".format(timestamp=capture["timestamp"], original=quote(str(capture["original"]), safe=":/?=&%"))
