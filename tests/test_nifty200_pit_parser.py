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


def test_parser_maps_explicit_tata_motors_dvr_label_to_exchange_symbol():
    rows = parse_nifty200_text(
        "1) Nifty 200 Index\nThe following company is being included:\n"
        "1 Tata Motors Ltd. (DVR) DVR\n",
        source_url="https://nse.example/Press_Release/ind_prs22022016_2.pdf",
        source_sha256="e" * 64,
        announcement_date=date(2016, 2, 22),
        effective_date=date(2016, 4, 1),
    )
    assert [(row.symbol, row.company_name) for row in rows] == [("TATAMTRDVR", "Tata Motors Limited")]


def test_parser_extracts_narrative_nifty200_exclusion_with_explicit_symbol():
    rows = parse_nifty200_text(
        "PRESS RELEASE\nMumbai, August 23, 2024\n"
        "A. Exclusion of Tata Motors Ltd. A Ordinary Shares - DVR:\n"
        "Tata Motors Ltd. (Symbol: TATAMTRDVR) shall be excluded from the following indices:\n"
        "1 Nifty 200\n",
        source_url="https://www.niftyindices.com/Press_Release/ind_prs23082024_1.pdf",
        source_sha256="f" * 64, announcement_date=date(2024, 8, 23),
        effective_date=date(2024, 8, 30),
    )
    assert len(rows) == 1
    assert rows[0].action == Action.DROP
    assert rows[0].symbol == "TATAMTRDVR"
    assert rows[0].effective_date == date(2024, 8, 30)
    assert rows[0].extraction_method == "PDF_TEXT_NARRATIVE"


def test_nifty200_derivative_index_tables_are_not_historical_nifty200_events():

    text = (
        "Effective from December 27, 2019\n"
        "8) NIFTY 200\nThe following companies are being included:\n"
        "1 Fortis Healthcare Ltd. FORTIS\n"
        "9) NIFTY LargeMidcap 250\nThe following companies are being included:\n"
        "1 Other Company Ltd. OTHER\n"
        "6) NIFTY200 Quality 30\nThe following companies are being included:\n"
        "1 Bosch Ltd. BOSCHLTD\n"
        "7) NIFTY200 Momentum 30\nThe following companies are being excluded:\n"
        "1 Example Ltd. EXAMPLE\n"
    )
    rows = parse_nifty200_text(text, source_url="https://niftyindices.com/Press_Release/ind_prs16122019.pdf",
                              source_sha256="a" * 64, announcement_date=date(2019, 12, 16))
    assert [(row.symbol, row.action) for row in rows] == [("FORTIS", "ADD")]


def test_explicit_reschedule_does_not_reuse_quoted_old_effective_date():
    text = (
        "On August 28, 2017 IISL announced changes effective from September 29, 2017.\n"
        "The committee has decided to reschedule replacement of Reliance Capital\n"
        "in the indices listed hereunder effective from September 05, 2017.\n"
        "6) NIFTY 200\n"
    )
    assert find_effective_date(text) == date(2017, 9, 5)
def test_lettered_index_groups_keep_their_own_effective_dates():
    from datetime import date
    from tools.nifty200_pit.parse_pdf import parse_nifty200_text

    text = """
A. Replacements effective March 24, 2015 (close of March 23, 2015):
(1) CNX 500 Index
The following company is being included:
1 ITD Cementation Ltd. ITDCEM
B. Replacements effective March 27, 2015 (close of March 26, 2015):
(1) CNX 200 Index
The following company is being excluded:
1 CMC Ltd. CMC
The following company is being included:
1 Cox & Kings Ltd. COX&KINGS
(2) CNX 500 Index
The following company is being included:
1 Suven Ltd. SUVEN
"""
    rows = parse_nifty200_text(
        text, source_url="official", source_sha256="hash",
        announcement_date=date(2015, 3, 18), effective_date=date(2015, 3, 24),
    )
    assert {(row.symbol, row.effective_date) for row in rows} == {
        ("CMC", date(2015, 3, 27)), ("COX&KINGS", date(2015, 3, 27)),
    }


def test_wrapped_company_name_keeps_all_native_pdf_lines():
    # Native extraction of ind_prs10062020.pdf separates the row number,
    # first company-name line and final company-name/symbol line.
    text = (
        "1) Nifty 200 Index\nThe following companies are being included:\n"
        "5 Gujarat Gas Ltd. GUJGASLTD\n6\n"
        "Indian Railway Catering And Tourism\nCorporation Ltd. IRCTC\n"
        "7 NIIT Technologies Ltd. NIITTECH\n"
        "8 Unfinished company name\n"
        "The following companies are being excluded:\n"
        "1 Separate Company Ltd. SEPARATE\n"
    )
    rows = parse_nifty200_text(text, source_url="official", source_sha256="hash",
                              announcement_date=date(2020, 6, 10), effective_date=date(2020, 6, 26))
    assert [(row.symbol, row.company_name) for row in rows] == [
        ("GUJGASLTD", "Gujarat Gas Ltd."),
        ("IRCTC", "Indian Railway Catering And Tourism Corporation Ltd."),
        ("NIITTECH", "NIIT Technologies Ltd."),
        ("SEPARATE", "Separate Company Ltd."),
    ]
    assert "Indian Railway Catering And Tourism" in rows[1].raw_text


def test_lettered_nifty200_heading_is_bounded_by_neighboring_index():
    # ind_prs23082024.pdf uses l), m), n) for broad-market tables.
    text = (
        "Effective from September 30, 2024\n"
        "k) Nifty Midcap 150\nThe following companies are being included:\n"
        "1 Wrong Neighbor Ltd. WRONG\n"
        "l) Nifty 200\nThe following companies are being excluded:\n"
        "5 Fortis Healthcare Ltd. FORTIS\n10 Laurus Labs Ltd. LAURUSLABS\n"
        "The following companies are being included:\n"
        "1 Bharti Hexacom Ltd. BHARTIHEXA\n"
        "m) Nifty LargeMidcap 250\nThe following companies are being excluded:\n"
        "1 Another Neighbor Ltd. ANOTHER\n"
        "n) Nifty200 Quality 30\nThe following companies are being included:\n"
        "1 Derivative Index Ltd. DERIVATIVE\n"
    )
    rows = parse_nifty200_text(text, source_url="official", source_sha256="hash", announcement_date=date(2024, 8, 23))
    assert [(row.symbol, row.action) for row in rows] == [
        ("FORTIS", "DROP"), ("LAURUSLABS", "DROP"), ("BHARTIHEXA", "ADD"),
    ]
    assert all(row.effective_date == date(2024, 9, 30) for row in rows)
def test_multi_index_correction_grid_does_not_turn_revocation_into_membership():
    from datetime import date
    from tools.nifty200_pit.parse_pdf import parse_nifty200_text

    text = (
        "Changes effective from March 28, 2024.\n"
        "No. Index Name Security Name Symbol Remarks\n"
        "4 Nifty Midcap 100\nWrong Company Ltd. WRONG Inclusion\n"
        "5 Nifty 200\nIndian Renewable Energy Dev.\n"
        "Agency Ltd. IREDA Inclusion revoked\nBSE Ltd. BSE Inclusion\n"
        "6 Nifty LargeMidcap\n250\nOther Company Ltd. OTHER Inclusion\n"
    )
    rows = parse_nifty200_text(text, source_url="official", source_sha256="a" * 64,
                               announcement_date=date(2024, 3, 19))
    assert [(row.symbol, str(row.action)) for row in rows] == [("BSE", "ADD")]
    assert rows[0].effective_date == date(2024, 3, 28)
    assert rows[0].company_name == "BSE Ltd."
    assert rows[0].extraction_method == "PDF_TEXT_INDEX_GRID"
    assert "IREDA Inclusion revoked" in rows[0].raw_text
    revoked_only = text.replace("BSE Ltd. BSE Inclusion\n", "")
    assert parse_nifty200_text(
        revoked_only, source_url="official", source_sha256="a" * 64,
        announcement_date=date(2024, 3, 19),
    ) == []
