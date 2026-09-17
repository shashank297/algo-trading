from datetime import date, datetime
from types import SimpleNamespace
import pytest

from tools.nifty200_pit.build_public_dataset import (
    _annual_coverage,
    _blocker_ledger,
    _coverage,
    _csv_snapshot_rows,
    _event_date_snapshot_rows,
    _monthly_gap_rows,
    _replay_checkpoint_comparison,
    _snapshot_date,
    parse_challenger_events,
    _checkpoint_forensics,
    _historical_master_rows,
    _identity_aliases,
    _anchor_replay_forensics,
    _valid_checkpoint_groups,
    parse_symbol_changes,
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
        "months_with_expected_security_count": "1",
        "status": "BLOCKED", "qa_note": "year contains missing or unexpected-count checkpoints",
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


def test_monthly_gap_analysis_classifies_official_dvr_201_security_checkpoint():
    source = SourceRecord(
        source_url="https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataApr2016.zip",
        local_path="unused.zip", source_sha256="f" * 64,
        retrieved_at="2026-09-06T00:00:00+00:00",
    )
    coverage = [{"period": "2016-04", "snapshot_member_count": "201", "status": "BLOCKED"}]
    snapshots = [{
        "snapshot_date": "2016-04-29", "symbol": "TATAMTRDVR", "source_url": source.source_url,
        "source_sha256": source.source_sha256,
    }]

    rows = _monthly_gap_rows(coverage, snapshots, [], [source])

    assert rows[0]["status"] == "REPLAY_NOT_COMPARED"
    assert rows[0]["source_count_status"] == "PASS"
    assert rows[0]["expected_count"] == 201


def test_coverage_historical_dvr_count_requires_dvr_and_correct_period():
    rows = [{"snapshot_date": "2016-04-29", "symbol": f"S{i}"} for i in range(200)]
    rows.append({"snapshot_date": "2016-04-29", "symbol": "TATAMTRDVR"})
    april = next(row for row in _coverage(rows) if row["period"] == "2016-04")
    assert april["status"] == "PASS"
    assert april["expected_member_count"] == "201"
    rows[-1]["symbol"] = "WRONG"
    assert next(row for row in _coverage(rows) if row["period"] == "2016-04")["status"] == "BLOCKED"
    for row in rows:
        row["snapshot_date"] = "2020-06-30"
    assert next(row for row in _coverage(rows) if row["period"] == "2020-06")["status"] == "BLOCKED"


@pytest.mark.parametrize("case", ["match", "wrong_member", "missing_identity", "alias", "duplicate_identity"])
def test_actual_checkpoint_reconciliation_checks_identities_not_just_counts(case):
    snapshots = [{
        "snapshot_date": "2013-04-18", "symbol": f"S{i}",
        "source_url": _source().source_url, "source_sha256": "a" * 64,
    } for i in range(200)]
    master = [{
        "symbol": f"S{i}", "instrument_id": f"I{i}", "isin": f"ISIN{i}",
        "valid_from": "2013-01-01", "valid_until": "2014-01-01",
    } for i in range(200)]
    intervals = [SimpleNamespace(
        instrument_id=f"I{i}", symbol_at_entry=f"S{i}", company_name=f"Company {i}",
        isin_at_entry=f"ISIN{i}", effective_from=date(2013, 1, 1), effective_until=None,
        entry_event_hash=f"entry-{i}", exit_event_hash=None,
    ) for i in range(200)]
    if case == "wrong_member":
        intervals[0].instrument_id = "WRONG"
    elif case == "missing_identity":
        master[0]["valid_from"] = "2014-01-01"
    elif case == "alias":
        intervals[0].symbol_at_entry = "OLD_SYMBOL"
    elif case == "duplicate_identity":
        master[0]["instrument_id"] = "I1"

    summaries, differences = _replay_checkpoint_comparison(snapshots, intervals, master, [])

    passed = case in {"match", "alias"}
    assert summaries[0]["status"] == ("PASS" if passed else "BLOCKED")
    assert summaries[0]["replay_count"] == summaries[0]["official_count"] == 200
    assert summaries[0]["symbol_alias_match_count"] == (1 if case in {"alias", "duplicate_identity"} else 0)
    if case == "wrong_member":
        assert {row["difference_type"] for row in differences} == {
            "MISSING_FROM_RECONSTRUCTION", "UNEXPECTED_IN_RECONSTRUCTION",
        }
        assert differences[-1]["entry_event_hash"] == "entry-0"
    elif case == "missing_identity":
        assert summaries[0]["unresolved_identity_count"] == 1
        assert differences[0]["difference_type"] == "MISSING_DURABLE_IDENTITY"
    elif case == "duplicate_identity":
        assert summaries[0]["duplicate_identity_count"] == 1
    else:
        assert differences == []
    monthly = _monthly_gap_rows(
        [{"period": "2013-04", "snapshot_member_count": "200"}], snapshots, intervals, [], summaries,
    )
    assert monthly[0]["source_count_status"] == "PASS"
    assert monthly[0]["status"] == ("PASS" if passed else "REPLAY_SNAPSHOT_MISMATCH")


def test_blocker_ledger_classifies_actual_checkpoint_and_calendar_failures():
    conflict = Conflict("calendar", None, "HIGH", "CALENDAR_NOT_CERTIFIED", "Calendar audit incomplete.")
    report = ValidationReport(EvidenceStatus.BLOCKED, [
        "replay_checkpoint:2013-04-18:missing=1,unexpected=1", "unresolved_conflict:calendar",
    ], {}, "2026-09-17T00:00:00+00:00")
    rows = _blocker_ledger(report, conflicts=[conflict], events=[], snapshots=[], coverage=[], sources=[])
    assert [row["blocker_type"] for row in rows] == ["REPLAY_SNAPSHOT_MISMATCH", "CALENDAR_NOT_CERTIFIED"]
    assert rows[0]["date"] == "2013-04-18"


def test_checkpoint_groups_include_historical_dvr_with_normalized_symbol():
    rows = [{"snapshot_date": "2016-04-29", "symbol": f"S{i}"} for i in range(200)]
    rows.append({"snapshot_date": "2016-04-29", "symbol": "TATAMTRDVR"})
    assert _valid_checkpoint_groups(rows) == [(date(2016, 4, 29), rows)]
    rows[-1]["symbol"] = " tatamtrdvr "
    assert _valid_checkpoint_groups(rows) == [(date(2016, 4, 29), rows)]
    rows[-1]["symbol"] = "WRONG"
    assert _valid_checkpoint_groups(rows) == []
    rows[-1]["symbol"] = "TATAMTRDVR"
    for row in rows:
        row["snapshot_date"] = "2020-06-30"
    assert _valid_checkpoint_groups(rows) == []
    assert _valid_checkpoint_groups(rows[:-1]) == [(date(2020, 6, 30), rows[:-1])]


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

    assert [row["blocker_type"] for row in rows] == ["MISSING_MEMBERSHIP_HISTORY", "DUPLICATE_EVENT"]


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


def test_press_release_parser_keeps_index_rows_on_continuation_pages(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    source = SourceRecord(
        source_url="https://www.niftyindices.com/Press_Release/ind_prs22022016_2.pdf",
        local_path="release.pdf", source_sha256="d" * 64, retrieved_at="2026-09-06T00:00:00+00:00",
    )
    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes are effective from 01/04/2016.\n"
        "16) Nifty 200 Index\nThe following scrips are being excluded:\n"
        "1 Drop Industries Ltd. DROP\n",
        "The following scrips are being included:\n"
        "1 Add Industries Ltd. ADD\n",
    ])

    rows = build_public_dataset.parse_press_releases([source])

    assert [(row.action, row.symbol) for row in rows] == [
        ("DROP", "DROP"), ("ADD", "ADD"),
    ]


def test_press_release_date_uses_spatial_text_when_drawing_order_is_broken(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    source = SourceRecord(
        source_url="https://niftyindices.com/Press_Release/ind_prs27022014.pdf",
        local_path="release.pdf", source_sha256="a" * 64, retrieved_at="2026-09-12T00:00:00+00:00",
    )
    def extract(_path, *, layout=False):
        if layout:
            return ["These changes shall become effective from\nMarch 28, 2014 (close of March 27, 2014)."]
        return ["March 28, 2014\nThese changes shall become eff ective from\n"
                "(4) CNX 200 Index\nThe following companies are being included:\n"
                "1 AIA Engineering Ltd. AIAENG"]

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", extract)
    rows = build_public_dataset.parse_press_releases([source])
    assert len(rows) == 1
    assert rows[0].effective_date == date(2014, 3, 28)
    assert rows[0].symbol == "AIAENG"


def test_press_release_layout_recovers_vertically_split_table_rows(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    source = SourceRecord(
        source_url="https://niftyindices.com/Press_Release/ind_prs16052012.pdf",
        local_path="release.pdf", source_sha256="b" * 64, retrieved_at="2026-09-12T00:00:00+00:00",
    )
    def extract(_path, *, layout=False):
        header = "Effective from May 21, 2012\n1) CNX 200 Index\nThe following company is being included:\n"
        return [header + ("1 Britannia Industries Ltd. BRITANNIA" if layout else "1\nBritannia Industries Ltd.\nBRITANNIA")]

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", extract)
    rows = build_public_dataset.parse_press_releases([source])
    assert [(row.symbol, row.action) for row in rows] == [("BRITANNIA", "ADD")]
    assert rows[0].extraction_method == "PDF_TEXT"
    assert rows[0].extractor_version.endswith("layout")


def test_press_release_parser_ignores_index_mentions_without_event_rows(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    source = SourceRecord(
        source_url="https://www.niftyindices.com/Press_Release/ind_prs01092022.pdf",
        local_path="release.pdf", source_sha256="d" * 64, retrieved_at="2026-09-06T00:00:00+00:00",
    )
    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path, **_kwargs: [
        "The changes are effective from 30/09/2022.\n"
        "Sr. No. Index Name\n1 Nifty 200\n2 Nifty 500\n",
    ])

    assert build_public_dataset.parse_press_releases([source]) == []


def test_symbol_change_parser_keeps_official_provenance(tmp_path):
    path = tmp_path / "symbolchange.csv"
    path.write_text(
        "Company Name,Previous Symbol,New Symbol,Date\n"
        "Future Enterprises Limited,PANTALOONR,FRL,11-APR-2013\n",
        encoding="utf-8",
    )
    source = SourceRecord(
        source_url="https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
        local_path=str(path), source_sha256="e" * 64,
        retrieved_at="2026-09-11T00:00:00+00:00", source_tier="A1",
    )

    rows = parse_symbol_changes(source)

    assert rows[0]["previous_symbol"] == "PANTALOONR"
    assert rows[0]["new_symbol"] == "FRL"
    assert rows[0]["changed_on"] == date(2013, 4, 11)
    assert rows[0]["source_url"] == source.source_url
    assert rows[0]["source_sha256"] == source.source_sha256


def test_press_release_parser_uses_explicit_a1_effective_date_override(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    source = SourceRecord(
        source_url="https://www.niftyindices.com/Press_Release/ind_prs14032012.pdf",
        local_path="release.pdf", source_sha256="f" * 64, retrieved_at="2026-09-06T00:00:00+00:00",
    )
    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "(4) CNX 200 Index\nThe following companies are being included:\n"
        "Sr. No. Company Name Symbol\n1 Example Industries Ltd. EXAMPLE\n",
    ])

    rows = build_public_dataset.parse_press_releases(
        [source], effective_date_overrides={source.source_url: date(2012, 4, 27)},
    )

    assert len(rows) == 1
    assert rows[0].symbol == "EXAMPLE"
    assert rows[0].effective_date == date(2012, 4, 27)


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
    assert result["summary"]["anchor_raw_rows"] == 200
    assert result["summary"]["anchor_unique_members"] == 200
    assert result["first_divergence"]["date"] == ""
    assert sum(row["sessions"] for row in result["distribution_rows"]) == 2
    assert all(row["eligible_for_replay"] is False for row in result["candidate_rows"])
    unproven = next(row for row in result["candidate_rows"] if row["symbol"] == "S000")
    assert unproven["instrument_id"] == ""
    assert unproven["effective_date"] == ""
    assert unproven["known_at"] == ""
    reversed_without_source = next(row for row in result["candidate_rows"] if row["symbol"] == "S199")
    assert reversed_without_source["source_url"] == ""
    assert reversed_without_source["source_sha256"] == ""
def test_official_rescheduling_is_hash_bound_and_narrowly_scoped(tmp_path, monkeypatch):
    from dataclasses import replace
    from datetime import date
    from tools.nifty200_pit import build_public_dataset as builder
    from tools.nifty200_pit.models import Observation, SourceRecord

    notice_hash = "2c901efcc5c3af6a8b9d353b2de9c91904bab4b40c8e68ef8540267366c46f20"
    path = tmp_path / "notice.pdf"
    path.write_bytes(b"mock notice")
    source = SourceRecord("https://niftyindices.com/Press_Release/ind_prs29082017.pdf",
                          str(path), notice_hash, "now", source_tier="A1")
    original = Observation(symbol="MFSL", effective_date=date(2017, 9, 29), action="ADD",
                           source_url="https://www.niftyindices.com/Press_Release/ind_prs28082017.pdf")
    # A claimed hash without matching local bytes is not sufficient authority.
    unchanged, audit = builder._apply_official_rescheduling([original], [source])
    assert unchanged == [original] and audit == []
    monkeypatch.setattr(builder, "sha256_file", lambda _: notice_hash)
    unrelated = replace(original, symbol="OTHER")
    wrong_date = replace(original, effective_date=date(2017, 3, 31))
    challenger = replace(original, source_tier="B1")
    rows, audit = builder._apply_official_rescheduling([original, unrelated, wrong_date, challenger], [source])
    assert rows[0].review_status == "SUPERSEDED"
    assert rows[0].effective_date == original.effective_date
    assert rows[1:] == [unrelated, wrong_date, challenger]
    assert len(audit) == 1
    assert audit[0]["resolution_source_sha256"] == notice_hash
def test_event_identity_metrics_count_missing_required_identities():
    from tools.nifty200_pit.build_public_dataset import _event_identity_metrics
    from tools.nifty200_pit.models import Observation

    result = _event_identity_metrics([
        Observation(action="ADD", instrument_id="SEC1", isin="ISIN1"),
        Observation(action="DROP", symbol="UNRESOLVED"),
        Observation(action="ADD", source_tier="B1"),
        Observation(action="ADD", review_status="SUPERSEDED"),
    ])
    assert result["identity_observation_count"] == 2
    assert result["unresolved_identity_count"] == 1
    assert result["durable_id_resolution_percent"] == 50
    assert result["isin_resolution_percent"] == 50


def test_event_date_snapshot_rows_are_event_evidence_not_membership_snapshots():
    event = SimpleNamespace(
        effective_date=date(2024, 3, 28), announcement_date=date(2024, 2, 28),
        known_at=datetime(2024, 2, 29, 0, 0),
        instrument_id="NSE-ISIN:INE1", isin="INE1", symbol="ABC",
        company_name="ABC Ltd", action="ADD", known_at_basis="EXACT_SOURCE_TIMESTAMP",
        source_url="https://example.test/event.pdf", source_sha256="a" * 64,
        source_tier="A1", event_hash="event-1", review_status="ACCEPTED",
        confidence="CERTIFIED",
    )

    rows = _event_date_snapshot_rows([event])

    assert rows[0]["snapshot_kind"] == "EVENT_DATE_EVIDENCE_INDEX"
    assert rows[0]["snapshot_date"] == "2024-03-28"
    assert rows[0]["event_hash"] == "event-1"


def test_covid_deferral_preserves_assertion_without_inventing_replacement_date(tmp_path, monkeypatch):
    from datetime import date
    from tools.nifty200_pit import build_public_dataset as builder
    from tools.nifty200_pit.models import Observation, SourceRecord

    notice_hash = "55a9cd5f11b9036e274b397c1f43f607c632ccb31837339b7ac661de6037ea59"
    path = tmp_path / "notice.pdf"
    path.write_bytes(b"mock notice")
    source = SourceRecord("https://www.niftyindices.com/Press_Release/ind_prs23032020.pdf",
                          str(path), notice_hash, "now")
    monkeypatch.setattr(builder, "sha256_file", lambda _: notice_hash)
    original = Observation(symbol="IRCTC", action="ADD", effective_date=date(2020, 3, 27),
                           source_url="https://www.niftyindices.com/Press_Release/ind_prs18022020.pdf")
    rows, audit = builder._apply_official_rescheduling([original], [source])
    assert len(rows) == 1
    assert rows[0].review_status == "SUPERSEDED"
    assert rows[0].effective_date == date(2020, 3, 27)
    assert audit[0]["resolution_source_sha256"] == notice_hash
def test_withdrawn_challenger_is_audited_without_promotion_or_broad_suppression():
    from dataclasses import replace
    from datetime import date
    from tools.nifty200_pit.build_public_dataset import _exclude_withdrawn_challenger_assertions
    from tools.nifty200_pit.models import Observation

    row = Observation(symbol="MFSL", action="ADD", effective_date=date(2017, 9, 29),
                      source_tier="B1", confidence="PROVISIONAL", review_status="UNRESOLVED")
    unmatched = replace(row, symbol="OTHER")
    wrong_action = replace(row, action="DROP")
    other_index = replace(row, index_id="NIFTY_500")
    official = replace(row, source_tier="A1")
    disposition = {
        "withdrawn_effective_date": "2017-09-29", "symbol": "MFSL", "action": "ADD",
        "disposition": "SUPERSEDED", "resolution_source": "official notice",
        "resolution_source_sha256": "verified hash",
    }
    inputs = [row, unmatched, wrong_action, other_index, official]
    retained, audit = _exclude_withdrawn_challenger_assertions(inputs, [disposition])
    assert retained == inputs[1:]
    assert row.source_tier == "B1" and row.confidence == "PROVISIONAL" and row.review_status == "UNRESOLVED"
    assert audit[0]["disposition"] == "B1_CONTRADICTED"
    assert audit[0]["resolution_source_sha256"] == "verified hash"
    assert _exclude_withdrawn_challenger_assertions(inputs, []) == (inputs, [])
def test_calendar_exceptions_require_verified_first_party_bytes(tmp_path, monkeypatch):
    from datetime import date, time
    from tools.nifty200_pit import build_public_dataset as builder
    from tools.nifty200_pit.models import SourceRecord
    from trading_stack.calendars import build_nse_calendar

    digest = "04b67f39314bae95672d86497c28cbed6cea698ad6f029ba47ef74feb9f6da91"
    path = tmp_path / "circular.pdf"
    path.write_bytes(b"mock circular")
    source = SourceRecord("official", str(path), digest, "now", source_tier="A1")
    assert builder._verified_calendar_overrides([source]) == ()
    monkeypatch.setattr(builder, "sha256_file", lambda _: digest)
    overrides = builder._verified_calendar_overrides([source])
    assert len(overrides) == 2
    assert {row.override_type for row in overrides} == {"SPECIAL_SESSION", "INTERRUPTION"}
    calendar = build_nse_calendar(overrides=overrides)
    day = date(2024, 3, 2)
    assert calendar.iter_trading_days(day, day) == [day]
    minutes = calendar.expected_minute_index(day, day)
    assert len(minutes) == 105
    assert not any(time(10) <= value.time() < time(11, 30) for value in minutes)
def test_calendar_causality_alignment_preserves_exact_and_same_day_evidence():
    from datetime import date, datetime
    from tools.nifty200_pit.build_public_dataset import _align_date_only_causality
    from tools.nifty200_pit.models import Observation
    from trading_stack.calendars import SessionOverride, build_nse_calendar

    calendar = build_nse_calendar(overrides=(SessionOverride(date(2024, 1, 20), "SPECIAL_SESSION", "test evidence"),))
    derived = Observation(announcement_date=date(2024, 1, 19), known_at_basis="DATE_ONLY_CONSERVATIVE_NEXT_SESSION")
    exact = Observation(announcement_date=date(2024, 1, 19), known_at=datetime(2024, 1, 19, 12), known_at_basis="EXACT_SOURCE_TIMESTAMP")
    same_day = Observation(announcement_date=date(2024, 1, 19), effective_date=date(2024, 1, 19), known_at_basis="DATE_ONLY_SAME_DAY_REVIEW")
    rows = _align_date_only_causality([derived, exact, same_day], calendar)
    assert rows[0].known_at.date() == date(2024, 1, 20)
    assert rows[1:] == [exact, same_day]


def test_workbook_variant_link_requires_exact_source_event_and_company():
    from dataclasses import replace
    from tools.nifty200_pit.build_public_dataset import _suppress_redundant_workbook_observations
    from tools.nifty200_pit.models import Observation

    workbook = Observation(company_name="National Buildings Construction Corporation Ltd.",
                           effective_date=date(2016, 4, 1), action="ADD", extraction_method="OFFICIAL_XLS",
                           source_sha256="8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046")
    release = replace(workbook, company_name="National Buildings Construction Corp. Ltd.",
                      symbol="NBCC", instrument_id="test-identity", confidence="CERTIFIED", review_status="ACCEPTED",
                      extraction_method="PDF_TEXT",
                      source_sha256="db2e4802e43b68fcbfbbf2cb03cb59c6d5f9ebf086ab6687d5a15daa45c2525f")
    assert _suppress_redundant_workbook_observations([workbook, release]) == [release]
    for wrong in (replace(release, source_sha256="other"), replace(release, action="DROP"),
                  replace(release, index_id="NIFTY_500"), replace(release, effective_date=date(2016, 4, 2)),
                  replace(release, review_status="SUPERSEDED"), replace(release, source_tier="B1")):
        assert _suppress_redundant_workbook_observations([workbook, wrong]) == [workbook, wrong]
    assert workbook.instrument_id is None and workbook.company_name.endswith("Corporation Ltd.")


def test_wrong_index_schedule_challenger_requires_verified_official_assertion(tmp_path, monkeypatch):
    from dataclasses import replace
    from tools.nifty200_pit import build_public_dataset as builder
    from tools.nifty200_pit.models import Observation, SourceRecord

    digest = "e3ad170876e6278ad7a1e99cc924ba610c3f8be4ef0dc85cd2c146e2152ca4ea"
    path = tmp_path / "notice.pdf"
    path.write_bytes(b"test-only circular")
    source = SourceRecord("official", str(path), digest, "now")
    official = Observation(symbol="CAIRN", action="DROP", effective_date=date(2016, 11, 15), source_sha256=digest)
    challenger = replace(official, effective_date=date(2016, 10, 24), source_tier="B1", source_sha256="b1",
                         confidence="PROVISIONAL", review_status="UNRESOLVED")
    inputs = [official, challenger]
    assert builder._exclude_withdrawn_challenger_assertions(inputs, [], [source]) == (inputs, [])
    monkeypatch.setattr(builder, "sha256_file", lambda _: digest)
    retained, audit = builder._exclude_withdrawn_challenger_assertions(inputs, [], [source])
    assert retained == [official] and audit[0]["disposition"] == "B1_CONTRADICTED"
    assert challenger.confidence == "PROVISIONAL" and challenger.review_status == "UNRESOLVED"
    assert builder._exclude_withdrawn_challenger_assertions([challenger], [], [source]) == ([challenger], [])
    wrong = replace(challenger, action="ADD")
    assert builder._exclude_withdrawn_challenger_assertions([official, wrong], [], [source]) == ([official, wrong], [])
def test_ireda_revocation_only_supersedes_original_add_with_verified_notice(tmp_path, monkeypatch):
    from dataclasses import replace
    from tools.nifty200_pit import build_public_dataset as builder
    from tools.nifty200_pit.models import Observation, SourceRecord

    digest = "1bef44dabdf594b9390b15329de1d9f38a8ab96af2abea243e99311b6d61587e"
    path = tmp_path / "correction.pdf"
    path.write_bytes(b"test-only correction")
    notice = SourceRecord("https://www.niftyindices.com/Press_Release/ind_prs19032024.pdf",
                          str(path), digest, "now")
    original = Observation(symbol="IREDA", action="ADD", effective_date=date(2024, 3, 28),
                           source_url="https://www.niftyindices.com/Press_Release/ind_prs28022024.pdf")
    assert builder._apply_official_rescheduling([original], [notice]) == ([original], [])
    monkeypatch.setattr(builder, "sha256_file", lambda _: digest)
    untouched = [replace(original, symbol="BSE"), replace(original, action="DROP"),
                 replace(original, effective_date=date(2024, 9, 30)), replace(original, index_id="NIFTY_500"),
                 replace(original, source_tier="B1")]
    rows, audit = builder._apply_official_rescheduling([original, *untouched], [notice])
    assert rows[0].review_status == "SUPERSEDED"
    assert rows[0].effective_date == original.effective_date
    assert rows[1:] == untouched
    assert audit[0]["resolution_source_sha256"] == digest
    assert len(audit) == 1
