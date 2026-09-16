"""Conservative parser for NIFTY/CNX-200 source text."""

from __future__ import annotations

from dataclasses import replace
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
ROW_RE = re.compile(
    r"^\s*(?:(\d{1,3})\s+)?(.+?)\s+([A-Z][A-Z0-9&.-]{1,19}(?:\s+[A-Z])?)\s*$"
)
PDF_DATE_RE = re.compile(r"ind_prs(\d{2})(\d{2})(\d{4})", re.I)
INDEX_HEADING_RE = re.compile(
    r"^\s*\(?(?:\d{1,3}|[A-Za-z])\)?[.)]\s+(?:NIFTY|CNX)\s*[- ]?200"
    r"(?:\s+Index)?\s*:?\s*$", re.I,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_pdf_text(path: str | Path) -> str:
    """Extract native PDF text; OCR is intentionally a separate operation."""
    return "\n".join(extract_pdf_pages(path))


def extract_pdf_pages(source: str | Path | bytes | BytesIO, *, layout: bool = False) -> list[str]:
    """Return native text page-by-page so evidence can retain source pages."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF extraction; use the OCR command for scanned evidence") from exc
    if isinstance(source, (bytes, BytesIO)):
        reader = PdfReader(BytesIO(source) if isinstance(source, bytes) else source)
    else:
        reader = PdfReader(str(source))
    if layout:
        return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
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
    # A rescheduling notice can quote the old effective date before stating
    # the revised one (e.g. Reliance Capital, 2017-08-29).
    reschedule = re.search(r"\breschedul(?:e|ed|ing)\b", text, re.I)
    if reschedule:
        correction_text = text[reschedule.end():]
        for pattern in DATE_PATTERNS:
            correction = pattern.search(correction_text)
            if correction:
                parsed = _parse_date(correction.group(1))
                if parsed:
                    return parsed
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
    """Extract bounded numbered/lettered sections, avoiding neighboring indices."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    starts = [index for index, line in enumerate(lines) if INDEX_HEADING_RE.search(line)]
    sections: list[tuple[int, str]] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if re.match(r"^\s*\(?(?:\d{1,3}|[A-Za-z])\)?[.)]\s+", lines[index]):
                end = index
                break
        sections.append((start, "\n".join(lines[start:end])))
    return sections


def _action_for_line(line: str) -> Action | None:
    if re.search(r"\b(add(?:ed|ition)?|inclusion|included|replacement)\b", line, re.I):
        return Action.ADD
    if re.search(r"\b(drop(?:ped)?|deletion|exclusion|excluded|removed)\b", line, re.I):
        return Action.DROP
    return None


def _parse_narrative_nifty200_change(
    text: str,
    *,
    source_url: str,
    source_sha256: str,
    announcement_date: date | None,
    effective_date: date | None,
    source_page: int | None,
    source_tier: str,
    extractor_version: str,
    holidays: set[date] | None,
) -> list[Observation]:
    """Parse a first-party single-security change described outside a table."""
    if not re.search(r"Nifty\s*[- ]?200", text, re.I):
        return []
    match = re.search(
        r"\b(Exclusion|Inclusion)\s+of\s+(.+?)\s*\(Symbol:\s*"
        r"([A-Z][A-Z0-9&.-]{1,19})\)",
        text,
        re.I | re.S,
    )
    if not match:
        return []
    action_name, company_name, symbol = match.groups()
    action = Action.DROP if action_name.casefold() == "exclusion" else Action.ADD
    known_at = basis = review_reason = None
    if announcement_date is not None:
        known_at, basis, review_reason = derive_known_at(
            announcement_date, effective_date=effective_date, holidays=holidays,
        )
    confidence = "PROVISIONAL" if announcement_date and known_at and effective_date else "MANUAL_REVIEW"
    review_status = ReviewStatus.UNRESOLVED if confidence == "PROVISIONAL" else ReviewStatus.MANUAL_REVIEW
    return [Observation(
        source_index_name="NIFTY 200", symbol=symbol,
        company_name=" ".join(company_name.split()).strip(" :-"),
        announcement_date=announcement_date, known_at=known_at, known_at_basis=basis,
        effective_date=effective_date, action=action, reason=review_reason or "INDEX_CHANGE",
        source_url=source_url, source_sha256=source_sha256, source_page=source_page,
        source_tier=source_tier, extraction_method="PDF_TEXT_NARRATIVE",
        extractor_version=extractor_version, confidence=confidence,
        review_status=review_status, raw_text=match.group(0),
    )]


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
    # A release can assign different dates to lettered groups of indices.
    # For example, the 2015-03-18 notice uses March 24 in section A and
    # March 27 for CNX 200 in section B. Never borrow the first group's date.
    dated_groups = list(re.finditer(
        r"^[ \t]*[A-Z]\.\s+(?:Replacements|Changes)\s+effective[^\n]*",
        text, re.I | re.M,
    ))
    if dated_groups:
        grouped_rows: list[Observation] = []
        for position, heading in enumerate(dated_groups):
            end = dated_groups[position + 1].start() if position + 1 < len(dated_groups) else len(text)
            block = text[heading.end():end]
            group_date = find_effective_date(re.sub(
                r"\beffective\s+(?!from\b)", "effective from ", heading.group(), flags=re.I,
            ))
            grouped_rows.extend(parse_nifty200_text(
                block, source_url=source_url, source_sha256=source_sha256,
                announcement_date=announcement_date, effective_date=group_date,
                source_page=source_page, source_tier=source_tier,
                extractor_version=extractor_version, holidays=holidays,
            ))
        return grouped_rows
    effective = effective_date if effective_date is not None else find_effective_date(text)
    # Some corrections use a multi-index grid rather than separate included /
    # excluded tables. Native drawing order puts the index before its rows.
    # Revoked assertions are not new ADD/DROP events; dispositions are handled
    # separately against the original, source-bound announcement.
    if effective and re.search(r"Index\s+Name\s+Security\s+Name\s+Symbol\s+Remarks", text, re.I):
        lines = [" ".join(line.split()) for line in text.splitlines()]
        starts = [i for i, line in enumerate(lines) if re.fullmatch(
            r"\d+\s+(?:NIFTY|CNX)\s*[- ]?200", line, re.I,
        )]
        grid_rows: list[Observation] = []
        for start in starts:
            end = next((i for i in range(start + 1, len(lines)) if re.match(
                r"\d+\s+(?:NIFTY|CNX)\b", lines[i], re.I,
            )), len(lines))
            block = "\n".join(lines[start:end])
            pending: list[str] = []
            for line in lines[start + 1:end]:
                match = re.fullmatch(r"(.+?)\s+([A-Z][A-Z0-9&.-]{1,19})\s+(Inclusion|Exclusion)( revoked)?", line)
                if not match:
                    if line:
                        pending.append(line)
                    continue
                company, symbol, action, revoked = match.groups()
                company = " ".join([*pending, company])
                pending = []
                if revoked:
                    continue
                normalized = ("1) Nifty 200\nThe following company is being "
                              + ("included" if action == "Inclusion" else "excluded")
                              + f":\n1 {company} {symbol}")
                parsed = parse_nifty200_text(
                    normalized, source_url=source_url, source_sha256=source_sha256,
                    announcement_date=announcement_date, effective_date=effective,
                    source_page=source_page, source_tier=source_tier,
                    extractor_version=extractor_version, holidays=holidays,
                )
                grid_rows.extend(replace(row, extraction_method="PDF_TEXT_INDEX_GRID", raw_text=block) for row in parsed)
        if starts:
            return grid_rows
    narrative_rows = _parse_narrative_nifty200_change(
        text, source_url=source_url, source_sha256=source_sha256,
        announcement_date=announcement_date, effective_date=effective,
        source_page=source_page, source_tier=source_tier,
        extractor_version=extractor_version, holidays=holidays,
    )
    if narrative_rows:
        return narrative_rows
    sections = extract_nifty200_sections(text)
    section = "\n---SECTION---\n".join(value for _, value in sections) or extract_nifty200_section(text)
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
        pending_name: list[str] = []
        for line_offset, line in enumerate(section_text.splitlines()):
            action_heading = _action_for_line(line)
            if action_heading is not None and not ROW_RE.match(line):
                current_action = action_heading
                pending_name = []
                continue
            row_match = ROW_RE.match(line)
            if current_action is None:
                continue
            if row_match is None:
                # Native PDF drawing order can put the serial number and
                # company prefix on separate lines before the symbol row.
                if re.match(r"^\d{1,3}(?:\s|$)", line):
                    pending_name = [line]
                elif pending_name and line and not re.search(r"\b(?:Sr\.|Symbol|Company Name)\b", line):
                    pending_name.append(line)
                else:
                    pending_name = []
                continue
            serial, company_name, symbol = row_match.groups()
            raw_text = line
            if pending_name and serial is None:
                raw_text = "\n".join([*pending_name, line])
                prefix = re.sub(r"^\d{1,3}\s*", "", " ".join(pending_name))
                company_name = f"{prefix} {company_name}".strip()
            pending_name = []
            # Native PDF extraction occasionally inserts a space inside a
            # one-character suffix (for example ``ORCHIDCHE M``).  This is a
            # layout artefact, not a distinct exchange symbol.
            symbol = re.sub(r"\s+", "", symbol)
            if symbol == "DVR" and re.search(r"Tata Motors\s+Ltd\.?\s*\(DVR\)", text, re.I):
                symbol = "TATAMTRDVR"
                company_name = "Tata Motors Limited"
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
            symbol = symbol_match.group(1)
            company_name = None
            if symbol == "DVR" and re.search(r"Tata Motors\s+Ltd\.?\s*\(DVR\)", text, re.I):
                symbol = "TATAMTRDVR"
                company_name = "Tata Motors Limited"
            rows.append(Observation(
                source_index_name=source_index_name, symbol=symbol,
                company_name=company_name,
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
