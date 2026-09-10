from datetime import date, datetime

from tools.nifty200_pit.models import Action, Observation
from tools.nifty200_pit.reconciliation import reconcile_observations


def _row(**kwargs):
    values = dict(instrument_id="SEC-1", symbol="ABC", announcement_date=date(2024, 1, 1),
                  effective_date=date(2024, 1, 2), action=Action.ADD, known_at=datetime(2024, 1, 2, 9, 15),
                  source_url="https://nse.example/a.pdf", source_sha256="a" * 64,
                  confidence="CERTIFIED", review_status="ACCEPTED", observation_id="o1")
    values.update(kwargs)
    return Observation(**values)


def test_same_event_from_lower_tier_does_not_override_official():
    result = reconcile_observations([_row(), _row(source_tier="B1", source_url="https://mirror.example/a.pdf", source_sha256="b" * 64, observation_id="o2")])
    assert len(result.events) == 1
    assert result.events[0].source_tier == "A1"
    assert not result.blocked


def test_same_priority_conflict_fails_closed():
    result = reconcile_observations([_row(), _row(instrument_id="SEC-2", observation_id="o2")])
    assert result.blocked
    assert result.conflicts[0].severity == "HIGH"
