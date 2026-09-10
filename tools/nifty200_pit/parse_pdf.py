"""Conservative parser for NIFTY/CNX-200 source text."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import cast
from tools.nifty200_pit.causality import derive_known_at
from tools.nifty200_pit.models import Action, Observation, ReviewStatus

INDEX_RE = re.compile(r"\b(?:NIFTY|CNX)\s*[- ]?200\b", re.I)
DATE_PATTERNS = (
    re.compile(r"(?:effective\s+(?:from|w\.e\.f\.)|w\.e\.f\.)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I),
    re.compile(r"(?:effective\s+(?:from|w\.e\.f\.)|w\.e\.f\.)\s*[:\-]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
)
SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9&.-]{1,19}\b")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_pdf_text(path: str | Path) -> str:
    """Extract native PDF text; OCR is intentionally a separate operation."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF extraction; use the OCR command for scanned evidence") from exc
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_date(value: str) -> date | None:
    value = value.replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%B %d, %Y", "%B %d %Y"):
        from datetime import datetime

        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def find_effective_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = _parse_date(match.group(1))
            if parsed:
                return parsed
    return None


def extract_nifty200_section(text: str, *, window: int = 80) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    hits = [index for index, line in enumerate(lines) if INDEX_RE.search(line)]
    return "\n---SECTION---\n".join("\n".join(lines[max(0, i - 8): min(len(lines), i + window)]) for i in hits)


def _action_for_line(line: str) -> Action | None:
    if re.search(r"\b(add(?:ed|ition)?|inclusion|included|replacement)\b", line, re.I):
        return Action.ADD
    if re.search(r"\b(drop(?:ped)?|deletion|exclusion|excluded|removed)\b", line, re.I):
        return Action.DROP
    return None


def parse_nifty200_text(
    text: str,
    *,
    source_url: str,
    source_sha256: str,
    announcement_date: date | None = None,
    source_page: int | None = None,
    source_tier: str = "A1",
    extractor_version: str = "nifty200-pit-parser-v1",
    holidays: set[date] | None = None,
) -> list[Observation]:
    """Extract candidate event observations from native text.

    A generic ``Index Changes`` release is retained only when a line contains a
    NIFTY/CNX-200 section; symbols remain candidate values until identity resolution.
    """
    if not INDEX_RE.search(text):
        return []
    effective = find_effective_date(text)
    section = extract_nifty200_section(text)
    if not section or effective is None:
        return [Observation(source_url=source_url, source_sha256=source_sha256, announcement_date=announcement_date,
                            effective_date=effective, extraction_method="PDF_TEXT", extractor_version=extractor_version,
                            confidence="UNRESOLVED", review_status=ReviewStatus.MANUAL_REVIEW,
                            raw_text=section or text[:4000])]
    announcement = announcement_date or effective
    source_index_name = "CNX 200" if re.search(r"CNX\s*[- ]?200", text, re.I) else "NIFTY 200"
    known_at, basis, review_reason = derive_known_at(announcement, effective_date=effective, holidays=holidays)
    rows: list[Observation] = []
    for line in section.splitlines():
        action = _action_for_line(line)
        if action is None:
            continue
        words = SYMBOL_RE.findall(line.upper())
        excluded = {"NIFTY", "CNX", "INDEX", "INDICES", "CHANGE", "CHANGES", "ADDED", "DROPPED", "FROM", "THE"}
        symbols = [word for word in words if word not in excluded and not word.isdigit()]
        symbol = symbols[-1] if symbols else None
        rows.append(Observation(
            source_index_name=source_index_name,
            symbol=symbol, announcement_date=announcement, known_at=known_at, known_at_basis=basis,
            effective_date=effective, action=action, reason=review_reason or "INDEX_CHANGE",
            source_url=source_url, source_sha256=source_sha256, source_page=source_page,
            source_tier=source_tier, extraction_method="PDF_TEXT", extractor_version=extractor_version,
            confidence="MANUAL_REVIEW" if review_reason else "PROVISIONAL",
            review_status=ReviewStatus.MANUAL_REVIEW if review_reason else ReviewStatus.UNRESOLVED,
            raw_text=line,
        ))
    return rows


def parse_pdf(path: str | Path, **kwargs: object) -> list[Observation]:
    source = Path(path)
    announcement_date = cast(date | None, kwargs.pop("announcement_date", None))
    source_page = cast(int | None, kwargs.pop("source_page", None))
    source_tier = str(kwargs.pop("source_tier", "A1"))
    holidays = cast(set[date] | None, kwargs.pop("holidays", None))
    return parse_nifty200_text(extract_pdf_text(source), source_url=str(kwargs.pop("source_url", source)),
                               source_sha256=sha256_file(source), announcement_date=announcement_date,
                               source_page=source_page, source_tier=source_tier, holidays=holidays)


parse_release_text = parse_nifty200_text
