from datetime import date

from tools.nifty200_pit.build_public_dataset import parse_press_releases
from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.models import Action
from tools.nifty200_pit.parse_pdf import find_effective_date, parse_nifty200_text


def test_scanned_release_recovers_rows_as_manual_review(monkeypatch):
    from tools.nifty200_pit import build_public_dataset as build

    monkeypatch.setattr(build, 'extract_pdf_pages', lambda _path: ['  ', '\n'])
    monkeypatch.setattr(build, 'extract_ocr_pages', lambda _path: [
        'August 23, 2021\nChanges effective from September 30, 2021.',
        '10) NIFTY 200\nThe following companies are being excluded:\n'
        '1 Abbott India Ltd. ABBOTINDIA\n'
        'The following companies are being included:\n'
        '1 Astral Ltd. ASTRAL\n11) NIFTY LargeMidcap 250\n'
        'The following companies are being included:\n1 Other Ltd. OTHER',
    ], raising=False)
    source = SourceRecord('https://www.niftyindices.com/Press_Release/ind_prs23082021.pdf',
                          'fixture.pdf', 'a' * 64, '2026-11-02T00:00:00Z')
    rows = build.parse_press_releases([source])
    assert [(row.symbol, row.action, row.source_page) for row in rows] == [
        ('ABBOTINDIA', Action.DROP, 2), ('ASTRAL', Action.ADD, 2)]
    assert all(row.review_status == 'MANUAL_REVIEW' and row.confidence == 'UNRESOLVED' for row in rows)
    assert all(row.extraction_method == 'OCR' for row in rows)


def test_scanned_release_without_ocr_is_retained_for_review(monkeypatch):
    from tools.nifty200_pit import build_public_dataset as build
    from tools.nifty200_pit.ocr import OCRUnavailable

    monkeypatch.setattr(build, 'extract_pdf_pages', lambda _path: [''])
    def unavailable(_path):
        raise OCRUnavailable('missing optional engine')
    monkeypatch.setattr(build, 'extract_ocr_pages', unavailable)
    source = SourceRecord('https://www.niftyindices.com/Press_Release/scanned.pdf',
                          'fixture.pdf', 'a' * 64, '2026-11-02T00:00:00Z')
    rows = build.parse_press_releases([source])
    assert len(rows) == 1
    assert rows[0].reason == 'scanned_release_requires_ocr'
    assert rows[0].review_status == 'MANUAL_REVIEW'
    assert rows[0].symbol is None


def test_unrecognized_ocr_document_is_not_silently_dropped(monkeypatch):
    from tools.nifty200_pit import build_public_dataset as build
    monkeypatch.setattr(build, 'extract_pdf_pages', lambda _path, **_kwargs: [''])
    source = SourceRecord('https://www.niftyindices.com/Press_Release/scanned.pdf',
                          'fixture.pdf', 'a' * 64, '2026-11-02T00:00:00Z')
    for text in ['unreadable heading', 'NIFTY 200\nno readable events']:
        monkeypatch.setattr(build, 'extract_ocr_pages', lambda _path: [text])
        rows = build.parse_press_releases([source])
        assert len(rows) == 1
        assert rows[0].review_status == 'MANUAL_REVIEW'
        assert rows[0].extraction_method == 'OCR'


def test_ocr_page_attribution_uses_event_row_not_symbol_in_prose(monkeypatch):
    from tools.nifty200_pit import build_public_dataset as build
    monkeypatch.setattr(build, 'extract_pdf_pages', lambda _path: ['', '', ''])
    monkeypatch.setattr(build, 'extract_ocr_pages', lambda _path: [
        'Changes effective from September 30, 2021.',
        '10) NIFTY 200\nSee ASTRAL discussion elsewhere.',
        '10) NIFTY 200\nThe following companies are being included:\n1 Astral Ltd. ASTRAL',
    ])
    source = SourceRecord('https://www.niftyindices.com/Press_Release/ind_prs23082021.pdf',
                          'fixture.pdf', 'a' * 64, '2026-11-02T00:00:00Z')
    rows = build.parse_press_releases([source])
    assert len(rows) == 1
    assert rows[0].source_page == 3


def test_parser_handles_cnx_name_and_add_drop_rows():
    text = "Index Changes\nCNX 200\nEffective from July 19, 2011\nAdded: ABC Ltd (ABC)\nExcluded: XYZ Ltd (XYZ)"
    observations = parse_nifty200_text(text, source_url="https://nse.example/a.pdf", source_sha256="a" * 64,
                                       announcement_date=date(2011, 7, 18))
    assert find_effective_date(text) == date(2011, 7, 19)
    assert {row.action for row in observations} == {Action.ADD, Action.DROP}
    assert {row.source_index_name for row in observations} == {"CNX 200"}


def test_parser_flags_missing_effective_date_for_review():
    rows = parse_nifty200_text("NIFTY 200 index changes: Added ABC", source_url="https://nse.example/a.pdf", source_sha256="b" * 64)
    assert len(rows) == 1
    assert rows[0].confidence == "UNRESOLVED"
    assert rows[0].effective_date is None


def test_layout_extraction_recovers_2012_cnx200_release_rows():
    text = (
        "The changes shall become effective from April\n27, 2012.\n"
        "(4) CNX 200 Index\n"
        "The following companies are being excluded:\n"
        "Sr. No. Company Name Symbol\n"
        "1 Bombay Rayon Fashions Ltd. BRFL\n"
        "2 CMC Ltd. CMC\n"
        "The following companies are being included:\n"
        "Sr. No. Company Name Symbol\n"
        "1 Bata India Ltd. BATAINDIA\n"
        "2 CRISIL Ltd. CRISIL"
    )
    rows = parse_nifty200_text(
        text,
        source_url="https://www.niftyindices.com/Press_Release/ind_prs14032012.pdf",
        source_sha256="a" * 64,
    )

    assert find_effective_date(text) == date(2012, 4, 27)
    assert len(rows) == 4
    assert {row.symbol for row in rows} == {"BRFL", "CMC", "BATAINDIA", "CRISIL"}


def test_press_parser_handles_action_table_reset_across_page_boundary(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes become effective from June 26, 2020.\n"
        "12) NIFTY 200\nThe following companies are being excluded:\n"
        "Sr. No. Company Name Symbol\n1 Old Co Ltd OLDCO",
        "2 Older Co Ltd OLDERCO\nThe following companies are being included:\n"
        "Sr. No. Company Name Symbol\n1 New Co Ltd NEWCO\n"
        "13) NIFTY Auto\nThe following companies are being included:",
    ])
    source = SourceRecord(
        "https://www.niftyindices.com/Press_Release/ind_prs10062020.pdf",
        "fixture.pdf", "a" * 64, "2026-09-18T00:00:00Z",
    )

    rows = parse_press_releases([source])

    assert [(row.action, row.symbol) for row in rows] == [
        (Action.DROP, "OLDCO"),
        (Action.DROP, "OLDERCO"),
        (Action.ADD, "NEWCO"),
    ]


def test_parser_accepts_symbols_that_start_with_digits():
    rows = parse_nifty200_text(
        "Nifty 200\nThe following companies are being included:\n"
        "Sr. No. Company Name Symbol\n1 360 ONE WAM Ltd. 360ONE",
        source_url="https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf",
        source_sha256="a" * 64,
        effective_date=date(2025, 9, 30),
        announcement_date=date(2025, 8, 22),
    )

    assert [(row.action, row.symbol) for row in rows] == [(Action.ADD, "360ONE")]


def test_parser_rejects_neighboring_index_heading_as_security_row():
    rows = parse_nifty200_text(
        "The changes become effective from 30/09/2024.\n"
        "12) Nifty 200\nThe following companies are being excluded:\n"
        "1 Nifty MidSmall IT\n2 Example Industries Ltd. EXAMPLE\n",
        source_url="https://example.test/Press_Release/ind_prs25092024.pdf",
        source_sha256="e" * 64,
        announcement_date=date(2024, 9, 25),
        effective_date=date(2024, 9, 30),
    )

    assert [row.symbol for row in rows] == ["EXAMPLE"]


def test_numbered_index_heading_regex_discrimination():
    from tools.nifty200_pit.build_public_dataset import _NUMBERED_INDEX_HEADING_RE

    valid_headings = [
        "k) Nifty 200",
        "l) Nifty LargeMidcap 250",
        "(k) Nifty 200",
        "12) NIFTY 200",
        "12. NIFTY 200",
        "(12) NIFTY 200",
        "12 NIFTY 200",
        "(4) CNX 200 Index",
        "A) NIFTY 50",
        "(A) NIFTY 50",
    ]
    for heading in valid_headings:
        assert _NUMBERED_INDEX_HEADING_RE.match(heading) is not None, f"Failed to match valid heading: {heading}"

    invalid_prose_and_headers = [
        "The Index Maintenance Sub -Committee",
        "No changes are being made in Nifty Bank",
        "For detailed guidelines regarding handling of corporate actions",
        "In accordance with the index methodology",
        "Sr. No. Index Name",
        "Sr. No. Company Name Symbol",
        "1 Abbott India Ltd. ABBOTINDIA",
    ]
    for text in invalid_prose_and_headers:
        assert _NUMBERED_INDEX_HEADING_RE.match(text) is None, f"Incorrectly matched prose/header: {text}"


def test_press_parser_handles_lettered_heading_table_across_page_boundary(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes become effective from September 29, 2023.\n"
        "k) Nifty 200\nThe following companies are being excluded:\n"
        "Sr. No. Company Name Symbol\n1 Old One Ltd OLD1\n2 Old Two Ltd OLD2",
        "3 Old Three Ltd OLD3\nThe following companies are being included:\n"
        "Sr. No. Company Name Symbol\n1 New One Ltd NEW1\n"
        "l) Nifty LargeMidcap 250\nThe following companies are being included:\n"
        "1 Unrelated Co UNRELATED",
    ])
    source = SourceRecord(
        "https://www.niftyindices.com/Press_Release/ind_prs17082023.pdf",
        "fixture.pdf", "a" * 64, "2026-09-18T00:00:00Z",
    )

    rows = parse_press_releases([source])

    assert [(row.action, row.symbol, row.source_page) for row in rows] == [
        (Action.DROP, "OLD1", 1),
        (Action.DROP, "OLD2", 1),
        (Action.DROP, "OLD3", 2),
        (Action.ADD, "NEW1", 2),
    ]


def test_press_parser_unassociated_row_retention(monkeypatch, caplog):
    import logging
    from tools.nifty200_pit import build_public_dataset
    from tools.nifty200_pit.models import Confidence, ReviewStatus

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes become effective from September 29, 2023.\n"
        "k) Nifty 200\nThe following companies are being excluded:\n"
        "Sr. No. Company Name Symbol\n1 Old One Ltd OLD1",
        "Sr. No. Company Name Symbol\n5 Rogue Co ROGUE",
    ])
    source = SourceRecord(
        "https://www.niftyindices.com/Press_Release/fixture.pdf",
        "fixture.pdf", "a" * 64, "2026-09-18T00:00:00Z",
    )

    with caplog.at_level(logging.WARNING, logger="tools.nifty200_pit.parser"):
        default_rows = parse_press_releases([source])
        assert [r.symbol for r in default_rows] == ["OLD1"]
        assert any("could not be associated with allowed NIFTY-200" in record.message for record in caplog.records)

    retained_rows = parse_press_releases([source], retain_unassociated=True)
    assert len(retained_rows) == 2
    rogue = next(r for r in retained_rows if r.symbol == "ROGUE")
    assert rogue.confidence == Confidence.UNRESOLVED
    assert rogue.review_status == ReviewStatus.MANUAL_REVIEW
    assert "continuation_page_unassociated" in rogue.reason
