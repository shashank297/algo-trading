from datetime import date

from tools.nifty200_pit.causality import derive_known_at
from tools.nifty200_pit.parse_html import extract_links, is_index_change_candidate
from tools.nifty200_pit.source_catalogue import SourceCatalogue


def test_source_catalogue_is_content_addressed_and_immutable(tmp_path):
    catalogue = SourceCatalogue(tmp_path)
    first = catalogue.add_bytes(b"official", source_url="https://nse.example/release.pdf", extension=".pdf")
    second = catalogue.add_bytes(b"official", source_url="https://nse.example/release-copy.pdf", extension=".pdf")
    assert first.source_sha256 == second.source_sha256
    assert first.local_path == second.local_path
    assert catalogue.verify() == []


def test_html_parser_keeps_generic_index_change_links():
    links = extract_links('<a href="/a.pdf">Index Changes</a><a href="/b.pdf">Other</a>', base_url="https://nse.example")
    assert ("Index Changes", "https://nse.example/a.pdf") in links
    assert is_index_change_candidate("Index Changes")


def test_date_only_knowledge_time_is_conservative():
    known_at, basis, review = derive_known_at(date(2024, 8, 15), effective_date=date(2024, 8, 16))
    assert known_at.isoformat().startswith("2024-08-16T09:15:00")
    assert basis == "DATE_ONLY_CONSERVATIVE_NEXT_SESSION"
    assert review is None
