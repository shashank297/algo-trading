"""Conservative parser for NIFTY/CNX-200 source text."""

from __future__ import annotations

import hashlib
from io import BytesIO
import re
from datetime import date
from pathlib import Path
from tools.nifty200_pit.causality import derive_known_at
from tools.nifty200_pit.models import Action, Observation, ReviewStatus

INDEX_RE = re.compile(r"\b(?:NIFTY|CNX)\s*[- ]?200\b", re.I)
DATE_PATTERNS = (
    re.compile(r"(?:effective\s+(?:from|w\.e\.f\.)|w\.e\.f\.)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I),
    re.compile(r"(?:effective\s+(?:from|w\.e\.f\.)|w\.e\.f\.)\s*[:\-]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
)
SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9&.-]{1,19}\b")
ROW_RE = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s+([A-Z][A-Z0-9&.-]{1,19})\s*$")
PDF_DATE_RE = re.compile(r"ind_prs(\d{2})(\d{2})(\d{4})", re.I)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_pdf_text(path: str | Path) -> str:
    """Extract native PDF text; OCR is intentionally a separate operation."""
    return "\n".join(extract_pdf_pages(path))


def extract_pdf_pages(source: str | Path | bytes | BytesIO) -> list[str]:
    """Return native text page-by-page so evidence can retain source pages."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF extraction; use the OCR command for scanned evidence") from exc
    if isinstance(source, (bytes, BytesIO)):
        reader = PdfReader(BytesIO(source) if isinstance(source, bytes) else source)
    else:
        reader = PdfReader(str(source))
    return [page.extract_text() or "" for page in reader.pages]


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


def find_document_date(source: str | Path, text: str = "") -> date | None:
    """Find a publication date only when it is explicit in source metadata/text."""
    match = PDF_DATE_RE.search(str(source))
    if match:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    for pattern in (
        re.compile(r"(?:dated|date)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I),
        re.compile(r"(?:dated|date)\s*[:\-]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    ):
        match = pattern.search(text)
        if match:
            value = _parse_date(match.group(1))
            if value:
                return value
    return None


def extract_nifty200_section(text: str, *, window: int = 80) -> str:
    sections = extract_nifty200_sections(text)
    if sections:
        return "\n---SECTION---\n".join(section for _, section in sections)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    hits = [index for index, line in enumerate(lines) if INDEX_RE.search(line)]
    return "\n---SECTION---\n".join("\n".join(lines[max(0, i - 8): min(len(lines), i + window)]) for i in hits)


def extract_nifty200_sections(text: str) -> list[tuple[int, str]]:
    """Extract bounded numbered-index sections, avoiding neighboring indices."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    starts = [index for index, line in enumerate(lines) if INDEX_RE.search(line)]
    sections: list[tuple[int, str]] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if re.match(r"^\d{1,3}\)\s+", lines[index]) and not INDEX_RE.search(lines[index]):
                end = index
                break
        sections.append((start, "\n".join(lines[max(0, start - 4):end])))
    return sections


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
    effective_date: date | None = None,
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
    effective = effective_date if effective_date is not None else find_effective_date(text)
    sections = extract_nifty200_sections(text)
    section = "\n---SECTION---\n".join(value for _, value in sections)
    if not section or effective is None:
        return [Observation(source_url=source_url, source_sha256=source_sha256, announcement_date=announcement_date,
                            effective_date=effective, extraction_method="PDF_TEXT", extractor_version=extractor_version,
                            confidence="UNRESOLVED", review_status=ReviewStatus.MANUAL_REVIEW,
                            raw_text=section or text[:4000])]
    announcement = announcement_date
    source_index_name = "CNX 200" if re.search(r"CNX\s*[- ]?200", text, re.I) else "NIFTY 200"
    known_at = basis = review_reason = None
    if announcement is not None:
        known_at, basis, review_reason = derive_known_at(announcement, effective_date=effective, holidays=holidays)
    rows: list[Observation] = []
    for section_start, section_text in sections:
        current_action: Action | None = None
        for line_offset, line in enumerate(section_text.splitlines()):
            action_heading = _action_for_line(line)
            if action_heading is not None and not ROW_RE.match(line):
                current_action = action_heading
                continue
            row_match = ROW_RE.match(line)
            if current_action is None or row_match is None:
                continue
            _, company_name, symbol = row_match.groups()
            raw_text = line
            confidence = "PROVISIONAL" if announcement and known_at and effective else "MANUAL_REVIEW"
            review = ReviewStatus.UNRESOLVED if confidence == "PROVISIONAL" else ReviewStatus.MANUAL_REVIEW
            reason = "INDEX_CHANGE" if confidence == "PROVISIONAL" else "missing_explicit_publication_date"
            rows.append(Observation(
                source_index_name=source_index_name,
                symbol=symbol, company_name=company_name.strip(), announcement_date=announcement, known_at=known_at,
                known_at_basis=basis, effective_date=effective, action=current_action, reason=reason,
                source_url=source_url, source_sha256=source_sha256, source_page=source_page,
                source_tier=source_tier, extraction_method="PDF_TEXT", extractor_version=extractor_version,
                confidence=confidence, review_status=review, raw_text=raw_text,
            ))
    if not rows:
        # Keep support for compact text releases used by the existing parser
        # contract; table rows above remain the preferred extraction path.
        for line in section.splitlines():
            action = _action_for_line(line)
            if action is None:
                continue
            symbol_match = re.search(r"\(([A-Z][A-Z0-9&.-]{1,19})\)", line)
            if not symbol_match:
                continue
            rows.append(Observation(
                source_index_name=source_index_name, symbol=symbol_match.group(1),
                announcement_date=announcement, known_at=known_at, known_at_basis=basis,
                effective_date=effective, action=action, reason=review_reason or "INDEX_CHANGE",
                source_url=source_url, source_sha256=source_sha256, source_page=source_page,
                source_tier=source_tier, extraction_method="PDF_TEXT", extractor_version=extractor_version,
                confidence="PROVISIONAL" if announcement and known_at else "MANUAL_REVIEW",
                review_status=ReviewStatus.UNRESOLVED if announcement and known_at else ReviewStatus.MANUAL_REVIEW,
                raw_text=line,
            ))
    if not rows:
        return [Observation(source_url=source_url, source_sha256=source_sha256, announcement_date=announcement,
                            effective_date=effective, extraction_method="PDF_TEXT", extractor_version=extractor_version,
                            confidence="UNRESOLVED", review_status=ReviewStatus.MANUAL_REVIEW,
                            raw_text=section[:4000])]
    return rows


def parse_pdf(
    path: str | Path,
    *,
    source_url: str | None = None,
    announcement_date: date | None = None,
    source_page: int | None = None,
    source_tier: str = "A1",
    extractor_version: str = "nifty200-pit-parser-v1",
    holidays: set[date] | None = None,
) -> list[Observation]:
    source = Path(path)
    text = extract_pdf_text(source)
    return parse_nifty200_text(
        text, source_url=source_url or str(source), source_sha256=sha256_file(source),
        announcement_date=announcement_date or find_document_date(source, text), source_page=source_page,
        source_tier=source_tier, extractor_version=extractor_version, holidays=holidays,
    )


parse_release_text = parse_nifty200_text
