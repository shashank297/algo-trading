from datetime import date

from tools.nifty200_pit.instrument_resolver import resolve_observation, resolve_observations
from tools.nifty200_pit.models import Observation


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


def test_merger_successor_is_not_implicitly_merged():
    result = resolve_observation(_observation(symbol="HDFC", company_name="HDFC Ltd"), [{"instrument_id": "BANK", "symbol": "HDFCBANK", "company_name": "HDFC Bank"}])
    assert result.instrument_id is None


def test_resolved_b1_identity_does_not_certify_membership():
    result = resolve_observations(
        [_observation(source_tier="B1", confidence="PROVISIONAL", review_status="UNRESOLVED")],
        [{"instrument_id": "SEC-1", "isin": "INE123", "symbol": "OLD"}],
    )[0]
    assert result.instrument_id == "SEC-1"
    assert result.confidence == "PROVISIONAL"
    assert result.review_status == "UNRESOLVED"


def test_institutional_series_does_not_conflict_with_normal_equity_identity():
    master = [
        {"instrument_id": "EQ-SEC", "isin": "INE092A01019", "symbol": "TATACHEM", "series": "EQ"},
        {"instrument_id": "IL-SEC", "isin": "INE344201012", "symbol": "TATACHEM", "series": "IL"},
    ]
    result = resolve_observation(_observation(symbol="TATACHEM"), master)
    assert result.instrument_id == "EQ-SEC"
    assert result.isin == "INE092A01019"
    assert resolve_observation(_observation(symbol="TATACHEM"), master[1:]).instrument_id is None


def test_unresolved_snapshot_alias_cannot_create_a_certified_none_instrument():
    alias = {"alias_symbol": "OLD", "instrument_id": None, "isin": None,
             "confidence": "MANUAL_REVIEW", "resolution_status": "MANUAL_REVIEW"}
    result = resolve_observation(_observation(), [], aliases=[alias])
    assert result.instrument_id is None
    assert result.confidence != "CERTIFIED"


def test_manual_review_alias_is_not_certified_even_when_it_has_an_identifier():
    alias = {"alias_symbol": "OLD", "instrument_id": "CANDIDATE", "isin": "INE123",
             "confidence": "MANUAL_REVIEW", "resolution_status": "MANUAL_REVIEW"}
    result = resolve_observation(_observation(), [], aliases=[alias])
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"
    assert result.candidates == ("CANDIDATE",)


def test_certified_alias_still_requires_a_real_identifier_and_valid_period():
    alias = {"alias_symbol": "OLD", "instrument_id": "SEC-1", "isin": "INE123",
             "confidence": "CERTIFIED", "resolution_status": "ACCEPTED",
             "valid_from": "2013-01-01", "valid_until": "2015-01-01"}
    assert resolve_observation(_observation(), [], aliases=[alias]).instrument_id == "SEC-1"
    for invalid in (None, "", "None"):
        result = resolve_observation(_observation(), [], aliases=[alias | {"instrument_id": invalid}])
        assert result.instrument_id is None
        assert result.confidence != "CERTIFIED"
    assert resolve_observation(_observation(effective_date=date(2015, 1, 1)), [], aliases=[alias]).instrument_id is None


def test_shared_durable_identity_does_not_choose_an_arbitrary_historical_isin():
    master = [
        {"instrument_id": "SAME-EQUITY", "symbol": "OLD", "isin": "NEW-ISIN", "snapshot_date": "2020-01-01"},
        {"instrument_id": "SAME-EQUITY", "symbol": "OLD", "isin": "OLD-ISIN", "snapshot_date": "2013-01-01"},
    ]
    result = resolve_observation(_observation(), master)
    assert result.isin == "OLD-ISIN"
    assert resolve_observation(_observation(effective_date=date(2021, 1, 1)), master).isin == "NEW-ISIN"
    early = resolve_observation(_observation(effective_date=date(2012, 1, 1)), master)
    assert early.instrument_id is None and early.confidence == "MANUAL_REVIEW"
