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


def test_b1_only_membership_is_not_canonical_even_with_certified_identity():
    result = reconcile_observations([_row(source_tier="B1")])
    assert result.events == []
    assert result.blocked
    assert "first-party confirmation" in result.conflicts[0].message


def test_same_priority_conflict_fails_closed():
    result = reconcile_observations([_row(), _row(instrument_id="SEC-2", observation_id="o2")])
    assert result.blocked
    assert result.conflicts[0].severity == "HIGH"


def test_same_identity_symbol_aliases_are_corroborating_evidence():
    result = reconcile_observations([
        _row(symbol="OLDNAME", source_url="https://nse.example/old.pdf", observation_id="o1"),
        _row(symbol="NEWNAME", source_url="https://nse.example/new.pdf", observation_id="o2"),
    ])

    assert len(result.events) == 1
    assert not any(conflict.conflict_type == "OFFICIAL_SOURCE_CONFLICT" for conflict in result.conflicts)


def test_withdrawn_schedule_is_retained_in_audit_not_replayed():
    original = _row(review_status="SUPERSEDED", reason="OFFICIAL_SCHEDULE_WITHDRAWN")
    replacement = _row(observation_id="new", effective_date=date(2024, 1, 3))
    result = reconcile_observations([original, replacement])
    assert result.superseded_observation_ids == ["o1"]
    assert len(result.events) == 1
    assert result.events[0].effective_date == date(2024, 1, 3)
    assert not result.blocked
