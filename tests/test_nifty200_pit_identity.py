from datetime import date, datetime

from tools.nifty200_pit.build_public_dataset import _certified_official_symbol_change_rows
from tools.nifty200_pit.instrument_resolver import resolve_observation, resolve_observations
from tools.nifty200_pit.models import Action, Confidence, Observation


def _observation(**kwargs):
    values = {"symbol": "OLD", "effective_date": date(2014, 1, 1)}
    values.update(kwargs)
    return Observation(**values)


def test_identity_prefers_period_valid_isin():
    result = resolve_observation(_observation(isin="INE123"), [{"instrument_id": "SEC-1", "isin": "INE123", "symbol": "OLD"}])
    assert result.instrument_id == "SEC-1"
    assert result.confidence == "CERTIFIED"


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


def test_merger_successor_is_not_implicitly_merged():
    result = resolve_observation(_observation(symbol="HDFC", company_name="HDFC Ltd"), [{"instrument_id": "BANK", "symbol": "HDFCBANK", "company_name": "HDFC Bank"}])
    assert result.instrument_id is None


def _event_observation(**kwargs):
    values = {
        "company_name": "Example Industries Ltd",
        "announcement_date": date(2014, 1, 1),
        "effective_date": date(2014, 1, 3),
        "known_at": datetime(2014, 1, 1, 12, 0),
        "action": Action.ADD,
        "source_tier": "A1",
        "source_url": "https://official.example/event.pdf",
    }
    values.update(kwargs)
    return Observation(**values)


def _event_master():
    return [{
        "instrument_id": "SEC-1",
        "isin": "INE123",
        "symbol": "EXAMPLE",
        "valid_from": "2010-01-01",
        "source_tier": "A1",
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
    }]


def test_exact_date_company_event_linkage_uses_only_one_official_identity():
    identity = _event_observation(symbol="EXAMPLE")
    company_only = _event_observation()

    resolved = resolve_observations([identity, company_only], _event_master())

    assert resolved[1].instrument_id == "SEC-1"
    assert resolved[1].isin == "INE123"
    assert resolved[1].symbol == "EXAMPLE"
    assert resolved[1].confidence == "CERTIFIED"
    assert "exact date, action, and company" in (resolved[1].reason or "")


def test_exact_date_company_event_linkage_rejects_b1_and_action_or_date_changes():
    identity = _event_observation(symbol="EXAMPLE", isin="INE123")
    b1_company_only = _event_observation(source_tier="B1", confidence=Confidence.PROVISIONAL)
    wrong_action = _event_observation(action=Action.DROP)
    wrong_date = _event_observation(effective_date=date(2014, 1, 4))

    resolved = resolve_observations(
        [identity, b1_company_only, wrong_action, wrong_date], _event_master()
    )

    assert resolved[1].instrument_id is None
    assert resolved[1].confidence == "PROVISIONAL"
    assert resolved[2].instrument_id is None
    assert resolved[3].instrument_id is None


def _symbol_change_candidate(**kwargs):
    values = {
        "identity_event_type": "OFFICIAL_SYMBOL_CHANGE_CANDIDATE",
        "identity_candidate_basis": "official symbol change OLD->NEW",
        "valid_until": "2020-01-10",
        "symbol_change_source_url": "https://official.example/symbolchange.csv",
        "symbol_change_source_sha256": "s" * 64,
        "source_tier": "A1",
    }
    values.update(kwargs)
    return values


def _dated_identity(symbol, snapshot_date, *, isin="INE123", source_sha256="b" * 64):
    return {
        "instrument_id": f"NSE-ISIN:{isin}",
        "isin": isin,
        "symbol": symbol,
        "company_name": f"{symbol} Company",
        "snapshot_date": snapshot_date,
        "valid_from": snapshot_date,
        "source_url": f"https://official.example/{snapshot_date}.csv",
        "source_sha256": source_sha256,
        "source_tier": "A1",
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
    }


def test_official_symbol_change_is_certified_from_period_valid_identity_on_both_sides():
    rows = _certified_official_symbol_change_rows(
        [_symbol_change_candidate()],
        [
            _dated_identity("OLD", "2018-01-01"),
            _dated_identity("OLD", "2020-01-09"),
            _dated_identity("NEW", "2020-01-11"),
        ],
    )

    assert len(rows) == 2
    old, new = rows
    assert (old["alias_symbol"], old["valid_from"], old["valid_until"]) == (
        "OLD", "2018-01-01", "2020-01-10"
    )
    assert (new["alias_symbol"], new["valid_from"], new["valid_until"]) == (
        "NEW", "2020-01-10", None
    )
    assert {row["identity_event_type"] for row in rows} == {"OFFICIAL_SYMBOL_CHANGE_CERTIFIED"}
    assert {row["instrument_id"] for row in rows} == {"NSE-ISIN:INE123"}
    assert {row["symbol_change_source_sha256"] for row in rows} == {"s" * 64}


def test_official_symbol_change_stays_unresolved_when_identity_differs():
    rows = _certified_official_symbol_change_rows(
        [_symbol_change_candidate()],
        [_dated_identity("OLD", "2020-01-09"), _dated_identity("NEW", "2020-01-11", isin="INE999")],
    )

    assert rows == []


def test_symbol_change_certification_can_be_scoped_to_forensic_transitions():
    rows = _certified_official_symbol_change_rows(
        [_symbol_change_candidate()],
        [_dated_identity("OLD", "2020-01-09"), _dated_identity("NEW", "2020-01-11")],
        target_transitions={frozenset(("OLD", "OTHER"))},
    )

    assert rows == []


def test_chained_symbol_changes_produce_non_overlapping_alias_periods():
    candidates = [
        _symbol_change_candidate(
            identity_candidate_basis="official symbol change OLD->MID",
            valid_until="2020-01-10",
        ),
        _symbol_change_candidate(
            identity_candidate_basis="official symbol change MID->NEW",
            valid_until="2020-02-10",
        ),
    ]
    rows = _certified_official_symbol_change_rows(
        candidates,
        [
            _dated_identity("OLD", "2020-01-09"),
            _dated_identity("MID", "2020-01-11"),
            _dated_identity("MID", "2020-02-01"),
            _dated_identity("NEW", "2020-02-11"),
        ],
    )

    mid_periods = {
        (row["valid_from"], row["valid_until"])
        for row in rows
        if row["alias_symbol"] == "MID"
    }
    assert mid_periods == {("2020-01-10", "2020-02-10")}
