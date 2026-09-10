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
