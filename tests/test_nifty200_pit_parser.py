from datetime import date

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


def test_parser_bounds_parenthesized_index_heading_to_nifty200_table():
    rows = parse_nifty200_text(
        "(3) CNX 100 Index\nThe following companies are being included:\n"
        "1 Wrong Index Ltd. WRONG\n(4) CNX 200 Index\n"
        "The following companies are being excluded:\n"
        "Sr. No. Company Name Symbol\n1 Example Industries Ltd. EXAMPLE\n"
        "(5) CNX 500 Index\nThe following companies are being included:\n"
        "1 Another Index Ltd. ANOTHER\n",
        source_url="https://nse.example/a.pdf", source_sha256="c" * 64,
        announcement_date=date(2012, 3, 14), effective_date=date(2012, 4, 27),
    )

    assert len(rows) == 1
    assert rows[0].action == Action.DROP
    assert rows[0].symbol == "EXAMPLE"
    assert rows[0].company_name == "Example Industries Ltd."


def test_parser_accepts_compact_rows_and_pdf_split_symbols():
    rows = parse_nifty200_text(
        "1) CNX 200 Index\nThe following companies are being excluded:\n"
        "Patni Computer Systems Ltd. PATNI\n"
        "2 Gujarat Mineral Development Corp. GMDCLT D\n",
        source_url="https://nse.example/Press_Release/ind_prs16052012.pdf",
        source_sha256="d" * 64,
        announcement_date=date(2012, 5, 16),
        effective_date=date(2012, 5, 21),
    )

    assert [(row.symbol, row.company_name) for row in rows] == [
        ("PATNI", "Patni Computer Systems Ltd."),
        ("GMDCLTD", "Gujarat Mineral Development Corp."),
    ]
