"""HTML catalogue parsing without trusting page titles as membership evidence."""

from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((" ".join("".join(self._text).split()), self._href))
            self._href = None


def extract_links(html: str, *, base_url: str = "") -> list[tuple[str, str]]:
    parser = _LinkParser()
    parser.feed(html)
    seen: set[str] = set()
    result = []
    for title, href in parser.links:
        absolute = urljoin(base_url, href)
        if absolute not in seen:
            seen.add(absolute)
            result.append((title, absolute))
    return result


def is_index_change_candidate(title: str) -> bool:
    return bool(re.search(r"index\s+changes?|replacements?|inclusions?|exclusions?|launch.*cnx\s*200", title, re.I))


def parse_date(value: str) -> date | None:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None
