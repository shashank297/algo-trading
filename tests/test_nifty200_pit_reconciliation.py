from datetime import date, datetime

from tools.nifty200_pit.models import Action, LineageRelation, Observation
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


def test_reconciliation_emits_explicit_corroboration_lineage():
    result = reconcile_observations([
        _row(),
        _row(source_tier="B1", source_url="https://mirror.example/a.pdf", source_sha256="b" * 64, observation_id="o2"),
    ])
    assert any(
        row.observation_id == "o1"
        and row.related_observation_id == "o2"
        and row.relationship_type == "CORROBORATED"
        for row in result.lineage
    )


def test_reconciliation_retains_unresolved_lineage():
    result = reconcile_observations([_row(instrument_id=None, observation_id="unresolved")])
    assert any(
        row.observation_id == "unresolved"
        and row.related_observation_id is None
        and row.relationship_type == "UNRESOLVED"
        for row in result.lineage
    )


def test_company_only_official_row_corroborates_b1_without_promoting_it():
    official = _row(
        instrument_id=None,
        symbol=None,
        company_name="Indian Railway Catering And Tourism Corporation Ltd.",
        announcement_date=None,
        effective_date=date(2020, 3, 27),
        known_at=None,
        known_at_basis=None,
        observation_id="official-company-only",
    )
    challenger = _row(
        instrument_id=None,
        symbol="IRCTC",
        company_name="Indian Railway Catering And Tourism Corp. Ltd.",
        announcement_date=date(2020, 3, 1),
        effective_date=date(2020, 3, 27),
        known_at=datetime(2020, 3, 2, 9, 15),
        source_tier="B1",
        confidence="PROVISIONAL",
        review_status="UNRESOLVED",
        source_url="https://mirror.example/challenger.parquet",
        source_sha256="b" * 64,
        observation_id="challenger-irctc",
    )

    result = reconcile_observations([official, challenger])

    assert any(
        row.observation_id == "challenger-irctc"
        and row.related_observation_id == "official-company-only"
        and row.relationship_type == "CORROBORATED"
        for row in result.lineage
    )
    assert not any(
        conflict.conflict_type == "MISSING_OFFICIAL_EVENT"
        and "challenger-irctc" in conflict.observation_ids
        for conflict in result.conflicts
    )
    assert not result.events


def test_b1_date_mismatch_is_covered_by_exact_official_claim():
    official = _row(
        instrument_id=None,
        symbol="CROMPTON",
        company_name="Crompton Greaves Consumer Electricals Ltd.",
        announcement_date=date(2016, 10, 17),
        effective_date=date(2016, 11, 15),
        known_at=datetime(2016, 10, 18, 9, 15),
        observation_id="official-crompton",
    )
    challenger = _row(
        instrument_id=None,
        symbol="CROMPTON",
        company_name="Crompton Greaves Consumer Electricals Ltd.",
        announcement_date=date(2016, 10, 1),
        effective_date=date(2016, 10, 24),
        known_at=datetime(2016, 10, 2, 9, 15),
        source_tier="B1",
        confidence="PROVISIONAL",
        review_status="UNRESOLVED",
        source_url="https://mirror.example/challenger.parquet",
        source_sha256="b" * 64,
        observation_id="challenger-crompton",
    )

    result = reconcile_observations([official, challenger])

    assert any(
        row.observation_id == "challenger-crompton"
        and row.related_observation_id == "official-crompton"
        and row.relationship_type == LineageRelation.CONFLICTS_WITH
        and "effective date differs" in row.relation_basis
        for row in result.lineage
    )
    assert not any(
        conflict.conflict_type == "MISSING_OFFICIAL_EVENT"
        and "challenger-crompton" in conflict.observation_ids
        for conflict in result.conflicts
    )
    assert not result.events
