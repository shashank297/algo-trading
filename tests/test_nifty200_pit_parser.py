from datetime import date

from tools.nifty200_pit.build_public_dataset import parse_press_releases
from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.models import Action
from tools.nifty200_pit.parse_pdf import find_effective_date, parse_nifty200_text


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
