from dataclasses import replace
import json

from tools.nifty200_pit import build_public_dataset as builder
from tools.nifty200_pit import ocr
from tools.nifty200_pit.models import SourceRecord


DIGEST = "c9b9feef248ca89f7d8c8f12009e3d5c409eb4d6c793eee061fb93bf0af1231e"


def _source(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"test-only scan")
    return SourceRecord(
        "https://www.niftyindices.com/Press_Release/ind_prs23082021.pdf",
        str(path), DIGEST, "now", source_tier="A1",
    )


def test_transcription_requires_matching_parent_bytes_and_first_party_tier(tmp_path, monkeypatch):
    source = _source(tmp_path)
    assert ocr.load_pdf_transcription(source) is None
    monkeypatch.setattr(ocr, "sha256_file", lambda _: DIGEST)
    transcription = ocr.load_pdf_transcription(source)
    assert transcription["parent_sha256"] == DIGEST
    assert transcription["independent_qa"] == "NOT_ASSERTED"
    assert len(transcription["derivative_sha256"]) == 64
    assert ocr.load_pdf_transcription(replace(source, source_tier="B1")) is None
    assert ocr.load_pdf_transcription(replace(source, source_sha256="a" * 64)) is None


def test_scanned_august_2021_notice_preserves_dates_pages_and_extraction_lineage(tmp_path, monkeypatch):
    source = _source(tmp_path)
    monkeypatch.setattr(ocr, "sha256_file", lambda _: DIGEST)
    monkeypatch.setattr(builder, "extract_pdf_pages", lambda _: [""] * 29)
    audit = []
    rows = builder.parse_press_releases([source], transcription_audit=audit)
    assert {(row.symbol, str(row.action)) for row in rows} == {
        ("ABBOTINDIA", "DROP"), ("BBTC", "DROP"), ("CESC", "DROP"),
        ("GODREJAGRO", "DROP"), ("IBULHSGFIN", "DROP"), ("VGUARD", "DROP"),
        ("ASTRAL", "ADD"), ("HINDCOPPER", "ADD"), ("INDIANB", "ADD"),
        ("IRFC", "ADD"), ("NATIONALUM", "ADD"), ("TATACOMM", "ADD"),
    }
    assert len(rows) == 12 and len(audit) == 1
    for row in rows:
        assert row.announcement_date.isoformat() == "2021-08-23"
        assert row.effective_date.isoformat() == "2021-09-30"
        assert row.source_page == 14 and row.source_sha256 == DIGEST
        assert row.extraction_method == "PDF_VISUAL_TRANSCRIPTION"
        assert row.review_status == "UNRESOLVED" and row.confidence == "PROVISIONAL"
        assert row.instrument_id is None and row.isin is None
        lineage = json.loads(row.raw_text)
        assert lineage["date_source_page"] == 1
        assert lineage["derivative_sha256"] == audit[0]["derivative_sha256"]


def test_unknown_scanned_release_cannot_borrow_transcribed_events(tmp_path, monkeypatch):
    source = replace(_source(tmp_path), source_sha256="e" * 64)
    monkeypatch.setattr(builder, "extract_pdf_pages", lambda _: [""] * 29)
    assert builder.parse_press_releases([source]) == []
