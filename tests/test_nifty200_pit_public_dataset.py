from datetime import date
from types import SimpleNamespace

from tools.nifty200_pit.build_public_dataset import (
    _annual_coverage,
    _blocker_ledger,
    _coverage,
    _csv_snapshot_rows,
    _monthly_gap_rows,
    _snapshot_date,
    parse_challenger_events,
    _checkpoint_forensics,
    _historical_master_rows,
    _identity_aliases,
    _anchor_replay_forensics,
)
from tools.nifty200_pit.models import Conflict, EvidenceStatus, SourceRecord, ValidationReport
from tools.nifty200_pit.parse_pdf import parse_nifty200_text


def _source() -> SourceRecord:
    return SourceRecord(
        source_url="https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataApr2013.zip",
        local_path="unused", source_sha256="a" * 64, retrieved_at="2026-09-06T00:00:00+00:00",
    )


def test_snapshot_date_uses_explicit_report_date_before_fallback():
    assert _snapshot_date("Constituents of CNX 200\nApril 30, 2014", date(2014, 4, 1)) == date(2014, 4, 30)


def test_csv_snapshot_parser_retains_source_member_and_company_name():
    rows = _csv_snapshot_rows(
        b"18-04-2013,CNX 200,MCDOWELL-N,United Spirits Ltd.,BREW/DISTILLERIES,2095.75\n",
        _source(), "indices_dataApr2013/cnx200_Apr2013.csv", date(2013, 4, 1),
    )
    assert rows[0]["snapshot_date"] == "2013-04-18"
    assert rows[0]["symbol"] == "MCDOWELL-N"
    assert rows[0]["company_name"] == "United Spirits Ltd."
    assert rows[0]["source_member"].endswith("cnx200_Apr2013.csv")


def test_pdf_snapshot_parser_does_not_promote_sector_continuation_to_symbol(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _data: [
        "Constituents of NIFTY 200 March 31, 2021\n"
        "SUNTV Sun TV Network Ltd. MEDIA, ENTERTAINMENT &\n"
        "PUBLICATION 470.30 0.064633\n"
        "SYNGENE Syngene International Ltd. HEALTHCARE SERVICES 543.45 0.076304"
    ])
    rows = build_public_dataset._pdf_snapshot_rows(b"pdf", _source(), "checkpoint.pdf")

    assert [row["symbol"] for row in rows] == ["SUNTV", "SYNGENE"]


def test_coverage_is_blocked_for_missing_or_non_200_months():
    rows = _coverage([
        {"snapshot_date": "2013-04-18", "symbol": f"S{i}"} for i in range(200)
    ])
    april = next(row for row in rows if row["period"] == "2013-04")
    may = next(row for row in rows if row["period"] == "2013-05")
    assert april["status"] == "PASS"
    assert may["status"] == "BLOCKED"


def test_annual_coverage_aggregates_monthly_status_without_certifying_gaps():
    rows = _annual_coverage([
        {"period": "2012-01", "status": "BLOCKED"},
        {"period": "2012-02", "status": "PASS"},
    ])
    assert rows == [{
        "year": "2012", "months_expected": "2", "months_with_200_members": "1",
        "status": "BLOCKED", "qa_note": "year contains missing or non-200 checkpoints",
    }]


def test_monthly_gap_analysis_distinguishes_missing_and_non_200_sources():
    source = SourceRecord(
        source_url="https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJun2013.zip",
        local_path="unused.zip", source_sha256="e" * 64,
        retrieved_at="2026-09-06T00:00:00+00:00",
    )
    coverage = [
        {"period": "2013-05", "snapshot_member_count": "0", "status": "BLOCKED"},
        {"period": "2013-06", "snapshot_member_count": "201", "status": "BLOCKED"},
    ]
    snapshots = [{
        "snapshot_date": "2013-06-28", "symbol": "ABC", "source_url": source.source_url,
        "source_sha256": source.source_sha256,
    }]

    rows = _monthly_gap_rows(coverage, snapshots, [], [source])

    assert rows[0]["status"] == "A_NO_SNAPSHOT_EVIDENCE"
    assert rows[1]["status"] == "B_SNAPSHOT_NON_200"
    assert rows[1]["official_snapshot_found"] == "TRUE"


def test_blocker_ledger_keeps_validation_reasons_typed():
    report = ValidationReport(
        EvidenceStatus.BLOCKED,
        ["member_count:2012-01-02:0", "2012-01:0"],
        {},
        "2026-09-11T00:00:00+00:00",
    )
    rows = _blocker_ledger(
        report, conflicts=[], events=[], snapshots=[],
        coverage=[{"period": "2012-01", "snapshot_member_count": "0", "status": "BLOCKED"}],
        sources=[],
    )

    assert [row["blocker_type"] for row in rows] == ["COUNT_NOT_200", "MONTHLY_SNAPSHOT_MISSING"]
    assert set(rows[0]) == {
        "blocker_id", "blocker_type", "date", "year", "symbol", "company",
        "instrument_id", "isin", "expected_value", "observed_value", "source_tier",
        "source_url", "source_sha256", "severity", "root_cause", "resolution_status",
        "resolution_source", "notes",
    }


def test_blocker_ledger_classifies_reconciliation_conflicts():
    conflicts = [
        Conflict("missing-anchor", date(2012, 1, 2), "CRITICAL", "REMOVAL_OF_ABSENT_MEMBER", "drop had no active predecessor"),
        Conflict("duplicate", date(2015, 1, 2), "HIGH", "DUPLICATE_ADD", "duplicate add"),
    ]
    report = ValidationReport(
        EvidenceStatus.BLOCKED,
        ["unresolved_conflict:missing-anchor", "unresolved_conflict:duplicate"],
        {},
        "2026-09-11T00:00:00+00:00",
    )

    rows = _blocker_ledger(report, conflicts=conflicts, events=[], snapshots=[], coverage=[], sources=[])

    assert [row["blocker_type"] for row in rows] == ["MISSING_INITIAL_ANCHOR", "DUPLICATE_EVENT"]


def test_challenger_events_are_filtered_to_nifty_200_and_remain_unresolved(monkeypatch):
    import pandas as pd

    source = SourceRecord(
        source_url="https://example.test/events.parquet",
        archive_url="https://example.test/blob/events.parquet",
        local_path="unused.parquet", source_sha256="b" * 64,
        retrieved_at="2026-09-06T00:00:00+00:00", source_tier="B1",
    )
    frame = pd.DataFrame([
        {"announce": "2012-04-20", "effective": "2012-04-27", "index": "nifty 200", "action": "add", "symbol": "ABC", "company": "ABC Ltd", "pdf": "x.pdf"},
        {"announce": "2012-04-20", "effective": "2012-04-27", "index": "nifty 50", "action": "drop", "symbol": "NIFTY", "company": "Index", "pdf": "x.pdf"},
        {"announce": "2012-04-20", "effective": "2012-04-27", "index": "nifty 200", "action": "add", "symbol": "ISIN", "company": "junk", "pdf": "x.pdf"},
    ])
    monkeypatch.setattr(pd, "read_parquet", lambda _path: frame)

    rows = parse_challenger_events(source)

    assert len(rows) == 1
    assert rows[0].symbol == "ABC"
    assert rows[0].source_tier == "B1"
    assert rows[0].instrument_id is None
    assert rows[0].review_status == "UNRESOLVED"


def test_pdf_parser_uses_document_effective_date_when_page_header_is_missing():
    rows = parse_nifty200_text(
        "12) Nifty 200\nThe following companies are being included:\n"
        "Sr. No. Company Name Symbol\n1 Example Industries Ltd. EXAMPLE\n",
        source_url="https://example.test/Press_Release/ind_prs01092022.pdf",
        source_sha256="c" * 64,
        announcement_date=date(2022, 9, 1),
        effective_date=date(2022, 9, 30),
    )
    assert len(rows) == 1
    assert rows[0].symbol == "EXAMPLE"
    assert rows[0].effective_date == date(2022, 9, 30)


def test_press_release_parser_propagates_document_effective_date(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    source = SourceRecord(
        source_url="https://www.niftyindices.com/Press_Release/ind_prs01092022.pdf",
        local_path="release.pdf", source_sha256="d" * 64, retrieved_at="2026-09-06T00:00:00+00:00",
    )
    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes will be effective from 30/09/2022.",
        "12) Nifty 200\nThe following companies are being included:\n"
        "Sr. No. Company Name Symbol\n1 Example Industries Ltd. EXAMPLE\n",
    ])

    rows = build_public_dataset.parse_press_releases([source])

    assert len(rows) == 1
    assert rows[0].symbol == "EXAMPLE"
    assert rows[0].effective_date == date(2022, 9, 30)


def test_identity_aliases_do_not_duplicate_exact_current_symbols():
    master = [{
        "instrument_id": "NSE-ISIN:INE1", "isin": "INE1", "symbol": "ABC",
        "company_name": "ABC Ltd", "valid_from": "2010-01-01", "valid_until": None,
        "source_url": "https://nse.example/master.csv", "source_sha256": "a" * 64,
        "source_tier": "A1",
    }]
    snapshots = [{"snapshot_date": "2016-04-01", "symbol": "ABC", "company_name": None,
                  "source_url": "https://nse.example/checkpoint.zip", "source_sha256": "b" * 64}]

    aliases = _identity_aliases(snapshots, master)

    assert len(aliases) == 1
    assert aliases[0]["confidence"] == "CERTIFIED"


def test_historical_master_keeps_unresolved_snapshot_aliases_manual_review():
    aliases = _identity_aliases([
        {"snapshot_date": "2016-04-01", "symbol": "OLD", "company_name": "Old Ltd",
         "source_url": "https://nse.example/checkpoint.zip", "source_sha256": "b" * 64},
    ], [])

    rows = _historical_master_rows([], aliases)

    assert rows[0]["symbol"] == "OLD"
    assert rows[0]["confidence"] == "MANUAL_REVIEW"
    assert rows[0]["review_status"] == "MANUAL_REVIEW"


def test_checkpoint_forensics_retains_a_valid_201_row_source_count():
    rows = [{
        "snapshot_date": "2016-04-29", "symbol": f"S{i:03d}", "company_name": None,
        "raw_text": f"S{i:03d} Company {i} 10.00 0.01", "source_member": "checkpoint.pdf",
        "source_page": 1, "source_url": "https://nse.example/checkpoint.zip",
        "source_sha256": "c" * 64, "source_tier": "A1",
    } for i in range(201)]
    summary, debug = _checkpoint_forensics(rows, [_source()], [])

    assert summary[0]["raw_rows_extracted"] == 201
    assert summary[0]["unique_symbols"] == 201
    assert summary[0]["post_fix_count"] == 201
    assert summary[0]["duplicate_symbols"] == ""
    assert len(debug) == 201


def test_anchor_replay_reverses_canonical_events_without_certifying_anchor():
    symbols = [f"S{i:03d}" for i in range(199)] + ["NEW"]
    snapshots = [{
        "snapshot_date": "2013-04-18", "symbol": symbol, "company_name": None,
        "source_url": "https://example.test/checkpoint.zip", "source_sha256": "e" * 64,
        "source_member": "checkpoint.csv", "source_tier": "A1",
    } for symbol in symbols]
    events = [
        SimpleNamespace(effective_date=date(2012, 6, 1), symbol="NEW", action="ADD"),
        SimpleNamespace(effective_date=date(2012, 6, 1), symbol="S199", action="DROP"),
    ]

    result = _anchor_replay_forensics(snapshots, events, [], [date(2012, 1, 2), date(2013, 4, 18)])

    assert result["summary"]["candidate_member_count"] == 200
    assert result["summary"]["status"] == "NOT_ESTABLISHED"
    assert result["summary"]["checkpoint_set_matches"] == 1
    assert all(row["eligible_for_replay"] is False for row in result["candidate_rows"])
