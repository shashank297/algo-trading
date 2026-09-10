from datetime import date

from tools.nifty200_pit.instrument_resolver import resolve_observation
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
