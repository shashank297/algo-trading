import json
from datetime import date

from tools.nifty200_pit.causality import derive_known_at
from tools.nifty200_pit.corpus import CorpusIncompleteError, assert_corpus_complete
from tools.nifty200_pit.parse_html import extract_links, is_index_change_candidate
from tools.nifty200_pit.source_catalogue import SourceCatalogue


def test_source_catalogue_is_content_addressed_and_immutable(tmp_path):
    catalogue = SourceCatalogue(tmp_path)
    first = catalogue.add_bytes(b"official", source_url="https://nse.example/release.pdf", extension=".pdf")
    second = catalogue.add_bytes(b"official", source_url="https://nse.example/release-copy.pdf", extension=".pdf")
    assert first.source_sha256 == second.source_sha256
    assert first.local_path == second.local_path
    assert catalogue.verify() == []


def test_source_catalogue_loads_existing_records_before_adding_targeted_evidence(tmp_path):
    catalogue = SourceCatalogue(tmp_path)
    catalogue.add_bytes(b"existing", source_url="https://nse.example/existing.pdf", extension=".pdf")
    catalogue.save()

    loaded = SourceCatalogue.from_json(tmp_path)
    loaded.add_bytes(b"targeted", source_url="https://nse.example/targeted.pdf", extension=".pdf")
    loaded.save()

    persisted = SourceCatalogue.from_json(tmp_path)
    assert {record.source_url for record in persisted.records} == {
        "https://nse.example/existing.pdf",
        "https://nse.example/targeted.pdf",
    }
    assert persisted.verify() == []


def test_html_parser_keeps_generic_index_change_links():
    links = extract_links('<a href="/a.pdf">Index Changes</a><a href="/b.pdf">Other</a>', base_url="https://nse.example")
    assert ("Index Changes", "https://nse.example/a.pdf") in links
    assert is_index_change_candidate("Index Changes")


def test_date_only_knowledge_time_is_conservative():
    known_at, basis, review = derive_known_at(date(2024, 8, 15), effective_date=date(2024, 8, 16))
    assert known_at.isoformat().startswith("2024-08-16T09:15:00")
    assert basis == "DATE_ONLY_CONSERVATIVE_NEXT_SESSION"
    assert review is None


def test_corpus_preflight_reports_missing_source_bytes(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "nifty200_pit_corpus_requirements.json").write_text(
        '{"records": [{"source_url": "https://nse.example/missing.pdf", '
        '"source_sha256": "' + "a" * 64 + '", '
        '"relative_path": "data/raw/missing.pdf"}]}',
        encoding="utf-8",
    )

    try:
        assert_corpus_complete(tmp_path, [])
    except CorpusIncompleteError as exc:
        assert "CORPUS_INCOMPLETE" in str(exc)
        assert "missing_source_bytes" in str(exc)
    else:
        raise AssertionError("missing raw evidence must fail closed")


def test_corpus_preflight_accepts_hash_verified_source(tmp_path):
    source = SourceCatalogue(tmp_path / "sources").add_bytes(
        b"official", source_url="https://nse.example/source.pdf", extension=".pdf"
    )
    relative = source.local_path.replace(str(tmp_path) + "\\", "").replace("\\", "/")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "nifty200_pit_corpus_requirements.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_url": source.source_url,
                        "source_sha256": source.source_sha256,
                        "relative_path": relative,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert_corpus_complete(tmp_path, [source])


def test_corpus_preflight_reports_hash_mismatch(tmp_path):
    (tmp_path / "config").mkdir()
    required = tmp_path / "data" / "raw" / "required.pdf"
    required.parent.mkdir(parents=True)
    required.write_bytes(b"changed")
    (tmp_path / "config" / "nifty200_pit_corpus_requirements.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_url": "https://nse.example/required.pdf",
                        "source_sha256": "a" * 64,
                        "relative_path": "data/raw/required.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        assert_corpus_complete(tmp_path, [])
    except CorpusIncompleteError as exc:
        assert "source_hash_mismatch" in str(exc)
    else:
        raise AssertionError("a changed raw source must fail closed")


def test_unregistered_extra_file_does_not_satisfy_required_source(tmp_path):
    (tmp_path / "config").mkdir()
    extra = tmp_path / "data" / "raw" / "extra.pdf"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"required bytes")
    (tmp_path / "config" / "nifty200_pit_corpus_requirements.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_url": "https://nse.example/required.pdf",
                        "source_sha256": "a" * 64,
                        "relative_path": "data/raw/required.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        assert_corpus_complete(tmp_path, [])
    except CorpusIncompleteError as exc:
        assert "missing_source_bytes" in str(exc)
    else:
        raise AssertionError("an unregistered extra file must not satisfy a requirement")


def test_source_provenance_is_required_for_a_complete_corpus(tmp_path):
    source = SourceCatalogue(tmp_path / "sources").add_bytes(
        b"official", source_url="https://nse.example/actual.pdf", extension=".pdf"
    )
    relative = source.local_path.replace(str(tmp_path) + "\\", "").replace("\\", "/")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "nifty200_pit_corpus_requirements.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_url": "https://nse.example/unregistered.pdf",
                        "source_sha256": source.source_sha256,
                        "relative_path": relative,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        assert_corpus_complete(tmp_path, [source])
    except CorpusIncompleteError as exc:
        assert "missing_catalogue_record" in str(exc)
    else:
        raise AssertionError("unregistered source provenance must fail closed")
