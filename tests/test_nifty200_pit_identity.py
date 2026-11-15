from datetime import date

from tools.nifty200_pit.instrument_resolver import resolve_observation, resolve_observations
from tools.nifty200_pit.models import (
    Action, EvidenceStatus, Observation, ValidationReport,
)
from tools.nifty200_pit.reconciliation import reconcile_observations
from tools.nifty200_pit.build_public_dataset import _blocker_ledger


def _observation(**kwargs):
    values = {"symbol": "OLD", "effective_date": date(2014, 1, 1)}
    values.update(kwargs)
    return Observation(**values)


def test_identity_prefers_period_valid_isin():
    result = resolve_observation(_observation(isin="INE123"), [{"instrument_id": "SEC-1", "isin": "INE123", "symbol": "OLD"}])
    assert result.instrument_id == "SEC-1"
    assert result.confidence == "CERTIFIED"


def test_identity_resolution_does_not_approve_unreviewed_ocr():
    from datetime import datetime
    row = Observation(symbol='RDEL', company_name='Reliance Defence and Engineering Ltd.',
                      effective_date=date(2016, 4, 1), announcement_date=date(2016, 2, 22),
                      known_at=datetime.fromisoformat('2016-02-23T09:15:00+05:30'),
                      action=Action.DROP, source_tier='A1', extraction_method='OCR',
                      confidence='UNRESOLVED', review_status='MANUAL_REVIEW')
    resolved = resolve_observations([row], _rdel_master())[0]
    assert resolved.instrument_id == _RDEL_IDENTITY
    assert resolved.review_status == 'MANUAL_REVIEW'
    assert resolved.confidence == 'UNRESOLVED'
    assert reconcile_observations([resolved]).events == []


def test_fuzzy_identity_never_auto_certifies():
    result = resolve_observation(_observation(company_name="Example Industries"), [{"instrument_id": "SEC-1", "company_name": "Example Industriez"}])
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_exact_period_valid_company_name_can_resolve_missing_symbol():
    result = resolve_observation(
        _observation(symbol=None, company_name="Central Bank of India", effective_date=date(2014, 3, 28)),
        [{
            "instrument_id": "NSE-ISIN:INE483A01010", "isin": "INE483A01010",
            "company_name": "Central Bank of India", "valid_from": "1995-01-01",
        }],
    )

    assert result.instrument_id == "NSE-ISIN:INE483A01010"
    assert result.isin == "INE483A01010"
    assert result.method == "PERIOD_VALID_COMPANY_NAME"
    assert result.confidence == "CERTIFIED"


_RDEL_IDENTITY = "NSE-ISIN:INE542F01012"
_RDEL_ISIN = "INE542F01012"


def _rdel_master():
    return [
        {
            "instrument_id": _RDEL_IDENTITY, "isin": _RDEL_ISIN, "symbol": "PIPAVAVDOC",
            "company_name": "Pipavav Defence and Offshore Engineering Company Ltd.",
            "valid_from": "2009-10-09", "snapshot_date": "2015-03-25",
            "has_explicit_historical_interval": False,
            "confidence": "CERTIFIED", "review_status": "ACCEPTED",
        },
        {
            "instrument_id": _RDEL_IDENTITY, "isin": _RDEL_ISIN, "symbol": "RDEL",
            "company_name": "Reliance Defence and Engineering Ltd.",
            "valid_from": "2016-03-18", "valid_until": "2017-09-18",
            "has_explicit_historical_interval": True,
            "confidence": "CERTIFIED", "review_status": "ACCEPTED",
        },
        {
            "instrument_id": _RDEL_IDENTITY, "isin": _RDEL_ISIN, "symbol": "RNAVAL",
            "company_name": "Reliance Defence and Engineering Ltd.",
            "valid_from": "2017-09-18", "valid_until": None,
            "has_explicit_historical_interval": True,
            "confidence": "CERTIFIED", "review_status": "ACCEPTED",
        },
    ]


def test_rdel_company_only_observation_resolves_and_materializes_event_date_symbol():
    observation = Observation(
        symbol=None, company_name="Reliance Defence and Engineering Ltd.",
        effective_date=date(2016, 4, 1), action=Action.DROP,
    )

    resolved = resolve_observations([observation], _rdel_master())[0]

    assert resolved.instrument_id == _RDEL_IDENTITY
    assert resolved.isin == _RDEL_ISIN
    assert resolved.symbol == "RDEL"


def test_rdel_company_only_observation_does_not_create_missing_identity_blocker():
    observation = Observation(
        symbol=None, company_name="Reliance Defence and Engineering Ltd.",
        effective_date=date(2016, 4, 1), action=Action.DROP,
        source_tier="A1", confidence="UNRESOLVED", review_status="MANUAL_REVIEW",
        source_url="https://archives.nseindia.com/content/indices/IndexInclExcl.xls",
        source_sha256="a" * 64,
    )
    official_event = Observation(
        symbol="RDEL", company_name="Reliance Defence and Engineering Ltd.",
        instrument_id=_RDEL_IDENTITY, isin=_RDEL_ISIN,
        announcement_date=date(2016, 2, 22), effective_date=date(2016, 4, 1),
        action=Action.DROP, source_tier="A1", confidence="CERTIFIED",
        review_status="ACCEPTED",
        source_url="https://www.niftyindices.com/Press_Release/example.pdf",
        source_sha256="b" * 64,
    )
    master = _rdel_master()
    resolved = resolve_observations([observation, official_event], master)
    reconciliation = reconcile_observations(resolved)
    report = ValidationReport(EvidenceStatus.PASS, [], {}, "2016-04-01T00:00:00+00:00")

    blockers = _blocker_ledger(
        report, conflicts=reconciliation.conflicts, events=reconciliation.events,
        observations=resolved, snapshots=[], coverage=[], sources=[],
    )

    assert not [row for row in blockers if row["blocker_type"] == "MISSING_DURABLE_IDENTITY"]


def test_company_name_match_rejects_multiple_period_valid_instruments():
    rows = [
        {
            "instrument_id": f"NSE-ISIN:INE{i}", "isin": f"INE{i}",
            "company_name": "Shared Company Ltd.", "valid_from": "2010-01-01",
            "has_explicit_historical_interval": True,
        }
        for i in (1, 2)
    ]

    result = resolve_observation(
        _observation(symbol=None, company_name="Shared Company Ltd.", effective_date=date(2016, 4, 1)),
        rows,
    )

    assert result.instrument_id is None
    assert result.isin is None
    assert result.confidence == "MANUAL_REVIEW"


def test_rdel_symbol_interval_boundary_is_materialized_in_resolved_observations():
    master = _rdel_master()

    before_change = resolve_observations([
        Observation(symbol=None, company_name="Reliance Defence and Engineering Ltd.", effective_date=date(2017, 9, 17)),
    ], master)[0]
    on_change = resolve_observations([
        Observation(symbol=None, company_name="Reliance Defence and Engineering Ltd.", effective_date=date(2017, 9, 18)),
    ], master)[0]

    assert before_change.symbol == "RDEL"
    assert on_change.symbol == "RNAVAL"


def test_lauruslabs_mcx_and_cochinship_multi_isin_symbols_remain_unresolved():
    cases = [
        ("LAURUSLABS", "Laurus Labs Ltd.", "INE947Q01010", "INE947Q01028"),
        ("MCX", "Multi Commodity Exchange of India Ltd.", "INE745G01035", "INE745G01043"),
        ("COCHINSHIP", "Cochin Shipyard Ltd.", "INE704P01017", "INE704P01025"),
    ]
    for symbol, company, isin_a, isin_b in cases:
        rows = [
            {
                "instrument_id": f"NSE-ISIN:{isin}", "isin": isin, "symbol": symbol,
                "company_name": company, "valid_from": "2020-01-01",
                "has_explicit_historical_interval": True,
            }
            for isin in (isin_a, isin_b)
        ]
        result = resolve_observation(
            _observation(symbol=symbol, company_name=company, effective_date=date(2026, 3, 30)),
            rows,
        )
        assert result.instrument_id is None
        assert result.confidence == "MANUAL_REVIEW"


def test_merger_successor_is_not_implicitly_merged():
    result = resolve_observation(_observation(symbol="HDFC", company_name="HDFC Ltd"), [{"instrument_id": "BANK", "symbol": "HDFCBANK", "company_name": "HDFC Bank"}])
    assert result.instrument_id is None


def test_explicit_isin_does_not_override_contradictory_symbol_and_company():
    row = {
        "instrument_id": "NSE-ISIN:INE123456789", "isin": "INE123456789",
        "symbol": "RIGHT", "company_name": "Right Company Ltd.",
        "valid_from": "2020-01-01", "valid_until": None,
        "has_explicit_historical_interval": True, "source_tier": "A1",
        "confidence": "CERTIFIED", "review_status": "ACCEPTED",
    }
    observation = Observation(
        symbol="WRONG", company_name="Wrong Company Ltd.", isin="INE123456789",
        effective_date=date(2021, 1, 1),
    )

    result = resolve_observation(observation, [row])

    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"
    assert result.method == "CONTRADICTORY_EXPLICIT_ISIN"


def _identity_row(
    symbol, company, isin, *, instrument_id=None, valid_from="2020-01-01",
    valid_until=None, snapshot_date=None, explicit=True, event_type=None,
    source_tier="A1", confidence="CERTIFIED", review_status="ACCEPTED",
):
    return {
        "instrument_id": instrument_id or f"NSE-ISIN:{isin}",
        "isin": isin,
        "symbol": symbol,
        "company_name": company,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "snapshot_date": snapshot_date,
        "has_explicit_historical_interval": explicit,
        "identity_event_type": event_type,
        "source_tier": source_tier,
        "confidence": confidence,
        "review_status": review_status,
    }


def test_single_isin_histories_keep_existing_certification():
    safe_symbols = [
        ("BANDHANBNK", "Bandhan Bank Ltd."),
        ("ICICIPRULI", "ICICI Prudential Life Insurance Company Ltd."),
        ("LALPATHLAB", "Dr. Lal Path Labs Ltd."),
        ("GLAND", "Gland Pharma Ltd."),
        ("LTTS", "L&T Technology Services Ltd."),
        ("SYNGENE", "Syngene International Ltd."),
        ("HUDCO", "Housing & Urban Development Corporation Ltd."),
    ]
    for index, (symbol, company) in enumerate(safe_symbols, start=1):
        isin = f"INE{index:010d}"
        result = resolve_observation(
            _observation(symbol=symbol, company_name=company, effective_date=date(2025, 9, 30)),
            [_identity_row(symbol, company, isin, explicit=False, snapshot_date="2025-09-29")],
        )
        assert result.instrument_id == f"NSE-ISIN:{isin}"
        assert result.isin == isin
        assert result.confidence == "CERTIFIED"


def test_competing_snapshot_histories_fail_closed_for_required_rows():
    cases = [
        ("LAURUSLABS", "Laurus Labs Ltd.", "INE947Q01010", "INE947Q01028", date(2024, 9, 30), "2024-09-27"),
        ("LAURUSLABS", "Laurus Labs Ltd.", "INE947Q01010", "INE947Q01028", date(2026, 3, 30), "2026-03-27"),
        ("MCX", "Multi Commodity Exchange of India Ltd.", "INE745G01035", "INE745G01043", date(2026, 3, 30), "2026-09-19"),
        ("COCHINSHIP", "Cochin Shipyard Ltd.", "INE704P01017", "INE704P01025", date(2024, 9, 30), "2024-10-01"),
    ]
    for symbol, company, old_isin, new_isin, when, new_snapshot in cases:
        rows = [
            _identity_row(
                symbol, company, old_isin, explicit=False,
                snapshot_date="2024-03-28" if when.year == 2024 else "2025-01-02",
            ),
            _identity_row(symbol, company, new_isin, explicit=False, snapshot_date=new_snapshot),
        ]
        result = resolve_observation(
            _observation(symbol=symbol, company_name=company, effective_date=when), rows,
        )
        assert result.instrument_id is None, symbol
        assert result.isin is None, symbol
        assert result.confidence == "MANUAL_REVIEW", symbol


def test_tmcv_company_only_history_stays_ambiguous():
    rows = [
        _identity_row("TATAMOTORS", "Tata Motors Ltd.", "INE155A01022", explicit=False, snapshot_date="2025-11-10"),
        _identity_row("TATAMTRDVR", "Tata Motors Ltd.", "IN9155A01020", explicit=False, snapshot_date="2025-11-10"),
    ]
    result = resolve_observation(
        _observation(symbol=None, company_name="Tata Motors Ltd.", effective_date=date(2026, 3, 30)),
        rows,
    )
    assert result.instrument_id is None
    assert result.isin is None
    assert result.confidence == "MANUAL_REVIEW"


def test_explicit_isin_single_coherent_scope_resolves():
    rows = [
        _identity_row("OLDCO", "Example Company Ltd.", "INE123456789", valid_from="2010-01-01", valid_until="2020-01-01"),
        _identity_row("NEWCO", "Example Company Ltd.", "INE123456789", valid_from="2020-01-01", event_type="OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD"),
    ]
    result = resolve_observation(
        _observation(symbol=None, company_name=None, isin="INE123456789", effective_date=date(2021, 1, 1)),
        rows,
    )
    assert result.instrument_id == "NSE-ISIN:INE123456789"
    assert result.isin == "INE123456789"
    assert result.confidence == "CERTIFIED"


def test_explicit_isin_discovers_competing_history_in_derived_scope():
    rows = [
        _identity_row("ABC", "Example Company Ltd.", "INE123456789", explicit=False, snapshot_date="2025-01-01"),
        _identity_row("ABC", "Example Company Ltd.", "INE987654321", explicit=False, snapshot_date="2025-01-02"),
    ]
    result = resolve_observation(
        _observation(symbol=None, company_name=None, isin="INE123456789", effective_date=date(2025, 2, 1)),
        rows,
    )
    assert result.instrument_id is None
    assert result.isin is None
    assert result.confidence == "MANUAL_REVIEW"


def test_explicit_isin_with_incompatible_derived_scopes_fails_closed():
    rows = [
        _identity_row("ABC", "Example Company Ltd.", "INE123456789", instrument_id="SEC-A"),
        _identity_row("ABCDVR", "Example Company DVR Ltd.", "INE123456789", instrument_id="SEC-A"),
    ]
    result = resolve_observation(
        _observation(symbol=None, company_name=None, isin="INE123456789", effective_date=date(2021, 1, 1)),
        rows,
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_explicit_isin_with_no_derivable_scope_fails_closed():
    result = resolve_observation(
        _observation(symbol=None, company_name=None, isin="INE123456789", effective_date=date(2021, 1, 1)),
        [{"instrument_id": "SEC-A", "isin": "INE123456789"}],
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_explicit_isin_present_only_in_review_row_cannot_certify():
    result = resolve_observation(
        _observation(symbol=None, company_name=None, isin="INE123456789", effective_date=date(2021, 1, 1)),
        [_identity_row("ABC", "Example Company Ltd.", "INE123456789", source_tier="B1", confidence="MANUAL_REVIEW", review_status="MANUAL_REVIEW")],
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_weak_competing_history_vetoes_certification_but_cannot_certify():
    rows = [
        _identity_row("ABC", "Example Company Ltd.", "INE123456789", valid_from="2020-01-01", valid_until="2030-01-01"),
        _identity_row("ABC", "Example Company Ltd.", "INE987654321", explicit=False, snapshot_date="2024-01-01", source_tier="B1", confidence="MANUAL_REVIEW", review_status="MANUAL_REVIEW"),
    ]
    result = resolve_observation(
        _observation(symbol="ABC", company_name="Example Company Ltd.", effective_date=date(2025, 1, 1)),
        rows,
    )
    assert result.instrument_id is None
    assert result.isin is None
    assert result.confidence == "MANUAL_REVIEW"


def test_competing_non_overlapping_segments_resolve_on_half_open_boundaries():
    rows = [
        _identity_row("ABC", "Example Company Ltd.", "INE123456789", valid_from="2020-01-01", valid_until="2021-01-01"),
        _identity_row("ABC", "Example Company Ltd.", "INE987654321", valid_from="2021-01-01", event_type="OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD"),
    ]
    before = resolve_observation(
        _observation(symbol="ABC", company_name="Example Company Ltd.", effective_date=date(2020, 12, 31)), rows,
    )
    at_start = resolve_observation(
        _observation(symbol="ABC", company_name="Example Company Ltd.", effective_date=date(2021, 1, 1)), rows,
    )
    at_old_until = at_start
    assert before.isin == "INE123456789"
    assert at_start.isin == "INE987654321"
    assert at_old_until.isin == "INE987654321"
    assert before.confidence == at_start.confidence == "CERTIFIED"


def test_competing_segment_gap_and_overlap_fail_closed():
    gap_rows = [
        _identity_row("ABC", "Example Company Ltd.", "INE123456789", valid_from="2020-01-01", valid_until="2021-01-01"),
        _identity_row("ABC", "Example Company Ltd.", "INE987654321", valid_from="2021-01-02", event_type="OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD"),
    ]
    overlap_rows = [
        _identity_row("ABC", "Example Company Ltd.", "INE123456789", valid_from="2020-01-01", valid_until="2021-01-03"),
        _identity_row("ABC", "Example Company Ltd.", "INE987654321", valid_from="2021-01-02", event_type="OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD"),
    ]
    for rows, when in ((gap_rows, date(2021, 1, 1)), (overlap_rows, date(2021, 1, 2))):
        result = resolve_observation(
            _observation(symbol="ABC", company_name="Example Company Ltd.", effective_date=when),
            rows,
        )
        assert result.instrument_id is None
        assert result.confidence == "MANUAL_REVIEW"


def test_explicit_name_transition_with_isin_change_resolves_new_segment():
    rows = [
        _identity_row("ABC", "Example Former Ltd.", "INE123456789", valid_from="2010-01-01", valid_until="2020-01-01"),
        _identity_row("ABC", "Example Holdings Ltd.", "INE987654321", valid_from="2020-01-01", event_type="OFFICIAL_NAME_CHANGE_CERTIFIED_FORWARD"),
    ]
    result = resolve_observation(
        _observation(symbol="ABC", company_name="Example Holdings Ltd.", effective_date=date(2020, 1, 1)),
        rows,
    )
    assert result.instrument_id == "NSE-ISIN:INE987654321"
    assert result.isin == "INE987654321"
    assert result.confidence == "CERTIFIED"
