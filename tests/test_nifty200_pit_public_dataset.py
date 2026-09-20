from datetime import date
import hashlib
from types import SimpleNamespace

from tools.nifty200_pit.build_public_dataset import (
    _annual_coverage,
    _blocker_ledger,
    _coverage,
    _expected_member_count,
    _csv_snapshot_rows,
    _monthly_gap_rows,
    _monthly_source_issue,
    _snapshot_date,
    parse_challenger_events,
    parse_archived_index_constituent_snapshot,
    _checkpoint_forensics,
    _historical_master_rows,
    _identity_aliases,
    _anchor_replay_forensics,
    parse_official_identity_change_candidates,
    _certified_official_name_change_rows,
    _raw_unresolved_observations,
    parse_press_releases,
    _exclude_withdrawn_challenger_assertions,
    _suppress_redundant_workbook_observations,
    _enrich_bhavcopy_company_names,
    _numbered_continuation_prefix,
)
from tools.nifty200_pit.models import Conflict, EvidenceStatus, Observation, SourceRecord, ValidationReport, stable_observation_id
from tools.nifty200_pit.parse_pdf import parse_nifty200_text
from tools.nifty200_pit.instrument_resolver import resolve_observation, resolve_observations, validate_alias_intervals


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


def test_press_parser_carries_cnx200_table_rows_across_page_boundary(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes become effective from April 1, 2013.\n"
        "(4) CNX 200 Index\nThe following companies are being included:\n"
        "7 First Ltd. FIRST\n8 Second Ltd. SECOND",
        "9 Ninth Ltd. NINTH\n10 Tenth Ltd. TENTH\n11 Eleventh Ltd. ELEVENTH\n"
        "(5) CNX 500 Index\nThe following companies are being included:",
    ])
    source = SourceRecord(
        "https://www.niftyindices.com/Press_Release/ind_prs13022013.pdf",
        "fixture.pdf", "a" * 64, "2026-09-18T00:00:00Z",
    )

    rows = parse_press_releases([source])

    assert [row.symbol for row in rows] == ["FIRST", "SECOND", "NINTH", "TENTH", "ELEVENTH"]


def test_press_parser_rejects_unrelated_next_index_rows(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes become effective from April 1, 2013.\n"
        "(4) CNX 200 Index\nThe following companies are being included:\n"
        "1 First Ltd. FIRST\n2 Second Ltd. SECOND",
        "1 Unrelated Ltd. UNRELATED\n(5) CNX 500 Index\nThe following companies are being included:",
    ])
    source = SourceRecord(
        "https://www.niftyindices.com/Press_Release/ind_prs13022013.pdf",
        "fixture.pdf", "a" * 64, "2026-09-18T00:00:00Z",
    )

    rows = parse_press_releases([source])

    assert [row.symbol for row in rows] == ["FIRST", "SECOND"]


def test_press_parser_retains_symbols_split_by_pdf_spacing(monkeypatch):
    from tools.nifty200_pit import build_public_dataset

    monkeypatch.setattr(build_public_dataset, "extract_pdf_pages", lambda _path: [
        "The changes become effective from April 27, 2012.\n"
        "(4) CNX 200 Index\nThe following companies are being excluded:\n"
        "9 Orchid Chemicals & Pharmaceuticals Ltd. ORCHIDCHE M\n"
        "The following companies are being included:\n"
        "4 Gujarat Mineral Development Corporation Ltd. GMDCLT D",
    ])
    source = SourceRecord(
        "https://www.niftyindices.com/Press_Release/ind_prs14032012.pdf",
        "fixture.pdf", "a" * 64, "2026-09-18T00:00:00Z",
    )

    rows = parse_press_releases([source])

    assert [(row.symbol, row.action.value) for row in rows] == [
        ("ORCHIDCHEM", "DROP"),
        ("GMDCLTD", "ADD"),
    ]


def test_numbered_continuation_accepts_wrapped_rows_and_action_table_reset():
    page = (
        "The following companies are being included:\n"
        "1 Aarti Industries Ltd. AARTIIND\n"
        "2 Abbott India Ltd. ABBOTINDIA\n"
        "3 Adani Gas Ltd. ADANIGAS\n"
        "4 Dr. Lal Path Labs Ltd. LALPATHLAB\n"
        "5 Gujarat Gas Ltd. GUJGASLTD\n"
        "6\nIndian Railway Catering And Tourism\n"
        "Corporation Ltd. IRCTC\n"
        "7 NIIT Technologies Ltd. NIITTECH\n"
        "8 Polycab India Ltd. POLYCAB\n"
        "9 Trent Ltd. TRENT\n"
        "13) NIFTY Auto\n"
    )

    prefix = _numbered_continuation_prefix(page, expected_first_row=11)

    assert prefix is not None
    assert "IRCTC" in prefix


def test_numbered_continuation_accepts_prior_page_table_reset_without_heading():
    page = (
        "35 Va Tech Wabag Ltd. WABAG\n"
        "The following scrips are being included:\n"
        "1 Adani Enterprises Ltd. ADANIENT\n"
        "2 Arvind Ltd. ARVIND\n"
        "3 BEML Ltd. BEML\n"
    )

    prefix = _numbered_continuation_prefix(page, expected_first_row=35)

    assert prefix is not None


def test_coverage_is_blocked_for_missing_or_non_200_months():
    rows = _coverage([
        {"snapshot_date": "2013-04-18", "symbol": f"S{i}"} for i in range(200)
    ])
    april = next(row for row in rows if row["period"] == "2013-04")
    may = next(row for row in rows if row["period"] == "2013-05")
    assert april["status"] == "PASS"
    assert may["status"] == "BLOCKED"


def test_official_tata_dvr_policy_accepts_201_member_checkpoint():
    sources = [
        SourceRecord(
            "https://www.niftyindices.com/Press_Release/ind_prs22022016_2.pdf",
            "unused-2016.pdf",
            "db2e4802e43b68fcbfbbf2cb03cb59c6d5f9ebf086ab6687d5a15daa45c2525f",
            "2026-09-18T00:00:00Z",
        ),
        SourceRecord(
            "https://www.niftyindices.com/Press_Release/ind_prs10062020.pdf",
            "unused-2020.pdf",
            "ea83ae30ff9e8d80892e143ebd8f16fedd04c974e77d673539bb663a9f9de49e",
            "2026-09-18T00:00:00Z",
        ),
    ]

    expected, basis, source_urls, source_shas = _expected_member_count(date(2016, 4, 29), sources)

    assert expected == 201
    assert "Tata Motors DVR" in basis
    assert "ind_prs22022016_2.pdf" in source_urls
    assert "ind_prs10062020.pdf" in source_urls
    assert source_shas.count(";") == 1


def test_annual_coverage_aggregates_monthly_status_without_certifying_gaps():
    rows = _annual_coverage([
        {"period": "2012-01", "status": "BLOCKED"},
        {"period": "2012-02", "status": "PASS"},
    ])
    assert rows == [{
        "year": "2012", "months_expected": "2", "months_with_200_members": "1",
        "months_with_expected_members": "1",
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
    assert rows[1]["status"] == "B_SNAPSHOT_NON_EXPECTED_COUNT"
    assert rows[1]["official_snapshot_found"] == "TRUE"


def test_monthly_source_issue_classifies_cached_html_as_download_failure(tmp_path):
    path = tmp_path / "indices_dataMay2012.zip"
    payload = b"<!doctype html><title>Error 404</title>"
    path.write_bytes(payload)
    source = SourceRecord(
        source_url="https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMay2012.zip",
        local_path=str(path), source_sha256=hashlib.sha256(payload).hexdigest(),
        retrieved_at="2026-09-06T00:00:00+00:00",
    )

    assert _monthly_source_issue(source)[0] == "E_HTML_RESPONSE_NOT_ARCHIVE"


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
        Conflict("same-day", date(2016, 4, 1), "CRITICAL", "SAME_DAY_EVENT_COLLISION", "same-day ordering required"),
    ]
    report = ValidationReport(
        EvidenceStatus.BLOCKED,
        [
            "unresolved_conflict:missing-anchor", "unresolved_conflict:duplicate",
            "unresolved_conflict:same-day",
        ],
        {},
        "2026-09-11T00:00:00+00:00",
    )

    rows = _blocker_ledger(report, conflicts=conflicts, events=[], snapshots=[], coverage=[], sources=[])

    assert [row["blocker_type"] for row in rows] == [
        "MISSING_INITIAL_ANCHOR", "DUPLICATE_EVENT", "CONFLICTING_OFFICIAL_EVENTS",
    ]


def test_blocker_ledger_carries_observation_identity_context():
    observation = Observation(
        observation_id="obs-1",
        symbol="OLDCO",
        company_name="Old Company",
        instrument_id=None,
        effective_date=date(2012, 1, 2),
        source_url="https://example.test/oldco",
    )
    conflict = Conflict(
        "unresolved",
        date(2012, 1, 2),
        "HIGH",
        "UNRESOLVED_OBSERVATION",
        "identity missing",
        observation_ids=["obs-1"],
    )
    report = ValidationReport(
        EvidenceStatus.BLOCKED,
        ["unresolved_conflict:unresolved"],
        {},
        "2026-09-11T00:00:00+00:00",
    )

    rows = _blocker_ledger(
        report,
        conflicts=[conflict],
        events=[],
        observations=[observation],
        snapshots=[],
        coverage=[],
        sources=[],
    )

    assert rows[0]["symbol"] == "OLDCO"
    assert rows[0]["company"] == "Old Company"


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
    assert aliases[0]["exchange"] == "NSE"


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


def test_resolved_observations_get_stable_raw_evidence_ids():
    observation = Observation(
        symbol="ABC", company_name="ABC Ltd", action="ADD",
        announcement_date=date(2024, 1, 1), effective_date=date(2024, 1, 2),
        source_url="https://nse.example/event.pdf", source_sha256="a" * 64,
    )
    master = [{
        "instrument_id": "NSE-ISIN:INEABC", "isin": "INEABC", "symbol": "ABC",
        "company_name": "ABC Ltd", "valid_from": "2020-01-01", "valid_until": None,
    }]

    first = resolve_observations([observation], master)[0]
    second = resolve_observations([observation], master)[0]
    changed = resolve_observations([Observation(
        symbol=observation.symbol, company_name=observation.company_name, action=observation.action,
        announcement_date=observation.announcement_date, effective_date=observation.effective_date,
        source_url=observation.source_url, source_sha256="b" * 64,
    )], master)[0]

    assert first.observation_id
    assert first.observation_id == second.observation_id
    assert changed.observation_id != first.observation_id


def test_raw_unresolved_report_uses_post_resolution_identity_state():
    raw = Observation(
        symbol="ABC", company_name="ABC Ltd", action="ADD",
        announcement_date=date(2024, 1, 1), effective_date=date(2024, 1, 2),
        source_url="https://nse.example/event.pdf", source_sha256="a" * 64,
    )
    raw_id = stable_observation_id(raw)
    resolved = Observation(**(raw.to_dict() | {
        "observation_id": raw_id,
        "instrument_id": "NSE-ISIN:INE000A01000",
        "isin": "INE000A01000",
    }))
    assert _raw_unresolved_observations([raw], [resolved], []) == []

    unresolved = Observation(**(raw.to_dict() | {"observation_id": raw_id}))
    rows = _raw_unresolved_observations([raw], [unresolved], [])
    assert len(rows) == 1
    assert rows[0]["resolution_status"] == "UNRESOLVED_AFTER_ID_RESOLUTION"


def test_certified_alias_interval_validation_rejects_overlap_and_inversion():
    rows = [
        {"alias_id": "a", "instrument_id": "SEC-1", "alias_symbol": "ABC",
         "valid_from": "2020-01-01", "valid_until": "2022-01-01",
         "confidence": "CERTIFIED", "resolution_status": "ACCEPTED"},
        {"alias_id": "b", "instrument_id": "SEC-1", "alias_symbol": "ABC",
         "valid_from": "2021-01-01", "valid_until": None,
         "confidence": "CERTIFIED", "resolution_status": "ACCEPTED"},
        {"alias_id": "c", "instrument_id": "SEC-2", "alias_symbol": "XYZ",
         "valid_from": "2023-01-01", "valid_until": "2022-01-01",
         "confidence": "CERTIFIED", "resolution_status": "ACCEPTED"},
    ]

    errors = validate_alias_intervals(rows)

    assert any(error.startswith("alias_interval_overlap:") for error in errors)
    assert "invalid_alias_period:c" in errors


def test_current_snapshot_alias_is_bounded_by_observation_date():
    aliases = _identity_aliases(
        [{"symbol": "ABC", "snapshot_date": "2026-09-09", "source_url": "snapshot", "source_sha256": "a" * 64}],
        [{
            "instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC",
            "company_name": "ABC Ltd", "listing_date": "2012-01-01", "valid_from": "2012-01-01",
            "valid_until": None, "snapshot_date": "2026-09-09", "observed_snapshot_date": "2026-09-09",
            "validity_basis": "CURRENT_SNAPSHOT_ONLY", "has_explicit_historical_interval": False,
            "source_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            "source_sha256": "b" * 64, "source_tier": "A1", "confidence": "CERTIFIED",
            "review_status": "ACCEPTED",
        }],
    )
    assert aliases[0]["valid_from"] == "2026-09-09"
    assert aliases[0]["listing_date"] == "2012-01-01"
    assert aliases[0]["validity_basis"] == "CURRENT_SNAPSHOT_ONLY"


def test_manual_alias_candidate_is_not_used_as_certified_identity():
    observation = Observation(symbol="OLD", effective_date=date(2020, 1, 2))
    resolution = resolve_observation(
        observation,
        [],
        aliases=[{
            "instrument_id": "SEC-1", "alias_symbol": "OLD", "valid_from": "2010-01-01",
            "valid_until": None, "confidence": "MANUAL_REVIEW", "resolution_status": "MANUAL_REVIEW",
        }],
    )

    assert resolution.instrument_id is None
    assert resolution.confidence == "UNRESOLVED"


def test_duplicate_certified_alias_rows_for_one_instrument_are_deduplicated():
    resolution = resolve_observation(
        Observation(symbol="OLD", effective_date=date(2020, 1, 2)),
        [],
        aliases=[
            {"instrument_id": "SEC-1", "alias_symbol": "OLD", "valid_from": "2010-01-01",
             "valid_until": None, "confidence": "CERTIFIED", "resolution_status": "ACCEPTED"},
            {"instrument_id": "SEC-1", "alias_symbol": "OLD", "valid_from": "2015-01-01",
             "valid_until": None, "confidence": "CERTIFIED", "resolution_status": "ACCEPTED"},
        ],
    )
    assert resolution.instrument_id == "SEC-1"
    assert resolution.confidence == "CERTIFIED"


def test_official_identity_change_tables_remain_manual_without_historical_isin(tmp_path):
    symbol_path = tmp_path / "symbolchange.csv"
    symbol_path.write_text("Old Name,OLD,NEW,30-OCT-2019\n", encoding="utf-8")
    name_path = tmp_path / "namechange.csv"
    name_path.write_text(
        "NCH_SYMBOL,NCH_PREV_NAME,NCH_NEW_NAME,NCH_DT\nNEW,Old Name,New Name,30-OCT-2019\n",
        encoding="utf-8",
    )
    records = [
        SourceRecord("https://nsearchives.nseindia.com/content/equities/symbolchange.csv", str(symbol_path), "a" * 64, "2026-09-18T00:00:00Z"),
        SourceRecord("https://nsearchives.nseindia.com/content/equities/namechange.csv", str(name_path), "b" * 64, "2026-09-18T00:00:00Z"),
    ]
    master = [{
        "instrument_id": "NSE-ISIN:INE1", "isin": "INE1", "symbol": "NEW",
        "company_name": "New Name", "valid_from": "2020-01-01", "valid_until": None,
    }]

    rows = parse_official_identity_change_candidates(records, master)

    assert {row["identity_event_type"] for row in rows} == {
        "OFFICIAL_SYMBOL_CHANGE_CANDIDATE", "OFFICIAL_NAME_CHANGE_EVIDENCE",
    }
    assert all(row["confidence"] == "MANUAL_REVIEW" for row in rows)
    name_row = next(row for row in rows if row["identity_event_type"] == "OFFICIAL_NAME_CHANGE_EVIDENCE")
    assert name_row["name_evidence_confidence"] == "CERTIFIED"
    assert name_row["historical_identity_status"] == "MANUAL_REVIEW"
    assert name_row["has_explicit_historical_interval"] is False


def test_name_change_does_not_certify_historical_isin_from_current_master():
    rows = _certified_official_name_change_rows([{
        "identity_event_type": "OFFICIAL_NAME_CHANGE_EVIDENCE",
        "instrument_id": "NSE-ISIN:INE1",
        "isin": "INE1",
        "symbol": "ATGL",
        "company_name": "Adani Gas Limited",
        "listing_date": "2018-11-05",
        "valid_until": "2021-01-13",
        "source_tier": "A1",
        "source_url": "https://nsearchives.nseindia.com/content/equities/namechange.csv",
        "source_sha256": "b" * 64,
        "identity_master_source_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
        "identity_master_source_sha256": "c" * 64,
    }])

    assert rows == []


def test_explicit_historical_name_interval_can_certify_with_separate_identity_source():
    rows = _certified_official_name_change_rows([{
        "identity_event_type": "OFFICIAL_NAME_CHANGE_EVIDENCE",
        "instrument_id": "NSE-ISIN:INE1",
        "isin": "INE1",
        "symbol": "ATGL",
        "company_name": "Adani Gas Limited",
        "valid_until": "2021-01-13",
        "identity_valid_from": "2018-11-05",
        "has_explicit_historical_interval": True,
        "source_tier": "A1",
        "source_url": "https://nsearchives.nseindia.com/content/equities/namechange.csv",
        "source_sha256": "b" * 64,
        "identity_source_url": "https://nse.example/historical/ATGL-identity.pdf",
        "identity_source_sha256": "d" * 64,
        "identity_validity_basis": "OFFICIAL_PERIOD_VALID_IDENTITY_DOCUMENT",
    }])

    assert len(rows) == 1
    assert rows[0]["confidence"] == "CERTIFIED"
    assert rows[0]["valid_from"] == "2018-11-05"
    assert rows[0]["valid_until"] == "2021-01-13"
    assert rows[0]["name_change_source_url"].endswith("namechange.csv")
    assert rows[0]["identity_source_url"].endswith("ATGL-identity.pdf")


def test_identity_change_prefers_dated_historical_master_over_current_master(tmp_path):
    name_path = tmp_path / "namechange.csv"
    name_path.write_text(
        "NCH_SYMBOL,NCH_PREV_NAME,NCH_NEW_NAME,NCH_DT\n"
        "ATGL,Adani Gas Limited,Adani Total Gas Limited,13-JAN-2021\n",
        encoding="utf-8",
    )
    records = [SourceRecord(
        "https://nsearchives.nseindia.com/content/equities/namechange.csv",
        str(name_path), "b" * 64, "2026-09-18T00:00:00Z",
    )]
    master = [
        {
            "instrument_id": "NSE-ISIN:INE399L01023", "isin": "INE399L01023",
            "symbol": "ATGL", "company_name": "Adani Total Gas Limited",
            "listing_date": "2018-11-05", "valid_from": "2018-11-05",
            "source_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            "snapshot_date": "2026-09-19",
        },
        {
            "instrument_id": "NSE-ISIN:INE399L01099", "isin": "INE399L01099",
            "symbol": "ATGL", "company_name": "Adani Gas Limited",
            "valid_from": "2021-01-13", "snapshot_date": "2021-01-13",
            "source_url": "https://archives.nseindia.com/content/historical/EQUITIES/2021/JAN/cm13JAN2021bhav.csv.zip",
        },
    ]

    rows = parse_official_identity_change_candidates(records, master)

    name_row = next(row for row in rows if row["identity_event_type"] == "OFFICIAL_NAME_CHANGE_EVIDENCE")
    assert name_row["isin"] == "INE399L01099"
    assert name_row["identity_master_source_url"].endswith("cm13JAN2021bhav.csv.zip")
    assert name_row["identity_observation_date"] == "2021-01-13"


def test_symbol_change_candidate_does_not_create_historical_interval(tmp_path):
    symbol_path = tmp_path / "symbolchange.csv"
    symbol_path.write_text("Old Name,OLD,NEW,30-OCT-2019\n", encoding="utf-8")
    records = [SourceRecord(
        "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
        str(symbol_path), "a" * 64, "2026-09-18T00:00:00Z",
    )]
    master = [{
        "instrument_id": "NSE-ISIN:INE1", "isin": "INE1", "symbol": "NEW",
        "company_name": "New Name", "valid_from": "2020-01-01", "snapshot_date": "2026-09-19",
    }]

    rows = parse_official_identity_change_candidates(records, master)

    assert rows[0]["has_explicit_historical_interval"] is False
    assert rows[0]["historical_identity_status"] == "MANUAL_REVIEW"


def test_identity_aliases_prefer_dated_historical_source_for_checkpoint():
    aliases = _identity_aliases(
        [{"snapshot_date": "2021-01-13", "symbol": "ATGL", "company_name": "Adani Gas Limited"}],
        [
            {
                "instrument_id": "NSE-ISIN:INE399L01023", "isin": "INE399L01023",
                "symbol": "ATGL", "valid_from": "2018-11-05",
                "snapshot_date": "2026-09-19",
                "source_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
                "source_sha256": "c" * 64,
            },
            {
                "instrument_id": "NSE-ISIN:INE399L01099", "isin": "INE399L01099",
                "symbol": "ATGL", "valid_from": "2021-01-13",
                "snapshot_date": "2021-01-13",
                "source_url": "https://archives.nseindia.com/content/historical/EQUITIES/2021/JAN/cm13JAN2021bhav.csv.zip",
                "source_sha256": "d" * 64,
            },
        ],
    )

    assert len(aliases) == 1
    assert aliases[0]["instrument_id"] == "NSE-ISIN:INE399L01099"
    assert aliases[0]["source_url"].endswith("cm13JAN2021bhav.csv.zip")


def test_superseded_official_assertion_is_audited_but_not_reconciled():
    observation = Observation(
        observation_id="old-event", symbol="ABC", action="ADD",
        effective_date=date(2024, 1, 2), source_tier="A1",
        source_url="https://nse.example/old.pdf", source_sha256="a" * 64,
    )
    retained, audit = _exclude_withdrawn_challenger_assertions(
        [observation], [{
            "observation_id": "old-event", "symbol": "ABC", "action": "ADD",
            "withdrawn_effective_date": "2024-01-02", "disposition": "SUPERSEDED",
            "resolution_source": "https://nse.example/correction.pdf",
            "resolution_source_sha256": "b" * 64,
        }],
    )

    assert retained == []
    assert audit[0]["disposition"] == "OFFICIAL_SUPERSEDED"


def test_workbook_assertion_is_suppressed_by_exact_release_name_normalization():
    workbook = Observation(
        source_url="https://nse.example/IndexInclExcl.xls", source_sha256="a" * 64,
        extraction_method="OFFICIAL_XLS", source_tier="A1", index_id="NIFTY_200",
        company_name="Example Corporation Limited", effective_date=date(2024, 1, 2),
        action="ADD",
    )
    release = Observation(
        source_url="https://niftyindices.example/release.pdf", source_sha256="b" * 64,
        extraction_method="PDF_TEXT", source_tier="A1", index_id="NIFTY_200",
        company_name="Example Corp Ltd", symbol="EXAMPLE", instrument_id="NSE-ISIN:INE000A01000",
        effective_date=date(2024, 1, 2), action="ADD", confidence="CERTIFIED",
        review_status="ACCEPTED",
    )

    assert _suppress_redundant_workbook_observations([workbook, release]) == [release]


def test_workbook_assertion_is_suppressed_by_exact_release_identity():
    workbook = Observation(
        source_url="https://nse.example/IndexInclExcl.xls", source_sha256="a" * 64,
        extraction_method="OFFICIAL_XLS", source_tier="A1", index_id="NIFTY_200",
        company_name="Name from workbook", symbol="WABAG", isin="INE956G01038",
        instrument_id="NSE-ISIN:INE956G01038", effective_date=date(2016, 4, 1),
        action="ADD",
    )
    release = Observation(
        source_url="https://niftyindices.example/release.pdf", source_sha256="b" * 64,
        extraction_method="PDF_TEXT", source_tier="A1", index_id="NIFTY_200",
        company_name="35 Va Tech Wabag Ltd.", symbol="WABAG", isin="INE956G01038",
        instrument_id="NSE-ISIN:INE956G01038", effective_date=date(2016, 4, 1),
        action="ADD", confidence="CERTIFIED", review_status="ACCEPTED",
    )

    assert _suppress_redundant_workbook_observations([workbook, release]) == [release]


def test_official_scrip_continuation_table_is_admitted():
    page_with_heading = """16) Nifty 200 Index
The following scrips are being excluded:
34 Unitech Ltd. UNITECH
"""
    page_continuation = """9
35 Va Tech Wabag Ltd. WABAG
The following scrips are being included:
1 Adani Enterprises Ltd. ADANIENT
"""

    from tools.nifty200_pit.build_public_dataset import (
        _nifty200_final_section_context,
        _numbered_continuation_prefix,
    )

    context = _nifty200_final_section_context(page_with_heading)
    assert context == (34, "The following scrips are being excluded:")
    assert _numbered_continuation_prefix(page_continuation, 35) == page_continuation.rstrip()


def test_official_continuation_table_allows_visual_row_order_variation():
    page_continuation = """9
The following companies are being included:
1 Dalmia Bharat Ltd. DALMIABHA
2 Edelweiss Financial Services Ltd. EDELWEISS
3 Endurance Technologies Ltd. ENDURANCE
5 Dr. Lal Path Labs Ltd. LALPATHLAB
4 ICICI Prudential Life Insurance Company Ltd. ICICIPRULI
6 L&T Technology Services Ltd. LTTS
7 Manappuram Finance Ltd. MANAPPURAM
8 Quess Corp Ltd. QUESS
11) NIFTY Smallcap 50
"""

    from tools.nifty200_pit.build_public_dataset import _numbered_continuation_prefix

    assert _numbered_continuation_prefix(page_continuation, 9) == page_continuation.split("11) NIFTY", 1)[0].rstrip()


def test_bhavcopy_company_name_join_requires_exact_symbol_and_isin():
    rows = _enrich_bhavcopy_company_names(
        [{"symbol": "ABC", "isin": "INE1", "snapshot_date": "2016-04-01", "company_name": None}],
        [{"symbol": "ABC", "isin": "INE1", "snapshot_date": "2017-01-01", "company_name": "ABC Limited",
          "source_url": "https://nse.example/master.csv", "source_sha256": "a" * 64}],
    )

    assert rows[0]["company_name"] == "ABC Limited"
    assert rows[0]["company_name_resolution_basis"] == "EXACT_SYMBOL_ISIN_CROSS_SOURCE"


def test_bhavcopy_company_name_join_can_use_exact_isin_after_symbol_change():
    rows = _enrich_bhavcopy_company_names(
        [{"symbol": "ADANIGAS", "isin": "INE1", "snapshot_date": "2020-06-26", "company_name": None}],
        [{"symbol": "ATGL", "isin": "INE1", "snapshot_date": "2021-01-01", "company_name": "Adani Gas Limited",
          "source_url": "https://nse.example/master.csv", "source_sha256": "a" * 64}],
    )

    assert rows[0]["company_name"] == "Adani Gas Limited"


def test_archived_index_constituent_parser_requires_dated_official_identity(tmp_path):
    path = tmp_path / "cnx200.csv"
    path.write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Example Ltd.,Industry,EXAMPLE,EQ,INE123A01010\n"
        "Example DVR,Industry,EXAMPLE-DVR,DR,IN0000000000\n",
        encoding="utf-8",
    )
    source = SourceRecord(
        source_url="https://web.archive.org/web/20140122091713id_/http%3A%2F%2Fnseindia.com%2Fcontent%2Findices%2Find_cnx200list.csv",
        local_path=str(path), source_sha256="a" * 64, retrieved_at="2014-01-13T00:00:00Z",
        document_date="2014-01-13", source_tier="A2",
    )

    rows = parse_archived_index_constituent_snapshot(source)

    assert len(rows) == 1
    assert rows[0]["instrument_id"] == "NSE-ISIN:INE123A01010"
    assert rows[0]["valid_from"] == "2014-01-13"
    assert rows[0]["identity_event_type"] == "ARCHIVED_OFFICIAL_INDEX_CONSTITUENT_SNAPSHOT"
