"""Evidence-priority reconciliation; no majority voting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Iterable

from tools.nifty200_pit.causality import derive_known_at
from tools.nifty200_pit.models import Action, CanonicalEvent, Conflict, Confidence, Observation, ReviewStatus

_TIER_RANK = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5, "D": 6, "E": 7}


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _as_action(value: object) -> Action | None:
    try:
        return Action(str(value).upper())
    except ValueError:
        return None


def observation_hash(observation: Observation) -> str:
    payload = json.dumps(observation.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    events: list[CanonicalEvent]
    conflicts: list[Conflict]
    superseded_observation_ids: list[str]

    @property
    def blocked(self) -> bool:
        return any(conflict.severity in {"HIGH", "CRITICAL"} for conflict in self.conflicts)


def _event_key(row: Observation) -> tuple[object, ...]:
    return (row.index_id, _as_date(row.effective_date), row.instrument_id or row.symbol or row.company_name, _as_action(row.action))


def _canonical(row: Observation, *, holidays: set[date] | None = None) -> CanonicalEvent | None:
    effective = _as_date(row.effective_date)
    announcement = _as_date(row.announcement_date)
    action = _as_action(row.action)
    if not effective or not announcement or not action or not row.instrument_id or not row.symbol:
        return None
    known_at = row.known_at
    basis = row.known_at_basis
    if known_at is None:
        known_at, basis, same_day_reason = derive_known_at(announcement, effective_date=effective, holidays=holidays)
        if same_day_reason:
            return None
    if known_at is None:
        return None
    event_payload = {
        "index_id": row.index_id, "instrument_id": row.instrument_id, "isin": row.isin,
        "symbol": row.symbol, "announcement_date": announcement.isoformat(), "effective_date": effective.isoformat(),
        "action": action.value, "source_sha256": row.source_sha256, "source_url": row.source_url,
    }
    event_hash = hashlib.sha256(json.dumps(event_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CanonicalEvent(
        index_id=row.index_id, instrument_id=row.instrument_id, isin=row.isin, symbol=row.symbol,
        company_name=row.company_name, announcement_date=announcement, known_at=known_at, known_at_basis=basis or "",
        effective_date=effective, action=action, reason=row.reason, source_url=row.source_url,
        archive_url=row.archive_url, source_sha256=row.source_sha256, source_page=row.source_page,
        source_tier=row.source_tier, extraction_method=row.extraction_method, extractor_version=row.extractor_version,
        confidence=Confidence(row.confidence), review_status=ReviewStatus(row.review_status), event_hash=event_hash,
        observation_id=row.observation_id or observation_hash(row), synthetic=row.synthetic,
    )


def reconcile_observations(
    observations: Iterable[Observation],
    *,
    fail_on_official_conflict: bool = True,
    holidays: set[date] | None = None,
) -> ReconciliationResult:
    rows = list(observations)
    groups: dict[tuple[object, ...], list[Observation]] = {}
    conflicts: list[Conflict] = []
    superseded: list[str] = []
    for row in rows:
        groups.setdefault(_event_key(row), []).append(row)

    chosen: list[Observation] = []
    for key, group in groups.items():
        ranked = sorted(group, key=lambda row: (_TIER_RANK.get(str(row.source_tier), 99), -(row.announcement_date.toordinal() if row.announcement_date else 0)))
        top_rank = _TIER_RANK.get(str(ranked[0].source_tier), 99)
        top = [row for row in ranked if _TIER_RANK.get(str(row.source_tier), 99) == top_rank]
        correction = [row for row in top if row.supersedes_observation_id or "correction" in str(row.reason).lower() or "revision" in str(row.reason).lower()]
        winner = correction[-1] if correction else top[0]
        if correction:
            superseded.extend(row.observation_id or observation_hash(row) for row in top if row is not winner)
        semantic = {(row.instrument_id, row.symbol, _as_action(row.action), _as_date(row.effective_date)) for row in top}
        if len(semantic) > 1:
            conflicts.append(Conflict(
                conflict_id=hashlib.sha256(json.dumps([row.to_dict() for row in top], sort_keys=True, default=str).encode()).hexdigest(),
                date=_as_date(key[1]), severity="HIGH" if top_rank <= 1 else "MEDIUM", conflict_type="OFFICIAL_SOURCE_CONFLICT",
                message="Same-priority evidence asserts different membership events; fail closed.",
                observation_ids=[row.observation_id or observation_hash(row) for row in top],
                source_urls=[row.source_url for row in top],
            ))
        chosen.append(winner)

    # A symbol/company that resolves to different durable identities on the same
    # date is a real identity conflict even though the normal event keys differ.
    identity_groups: dict[tuple[object, ...], list[Observation]] = {}
    for row in rows:
        identity_groups.setdefault((row.index_id, _as_date(row.effective_date), row.symbol or row.company_name), []).append(row)
    for key, group in identity_groups.items():
        identities = {row.instrument_id for row in group if row.instrument_id}
        tiers = {_TIER_RANK.get(str(row.source_tier), 99) for row in group}
        if len(identities) > 1 and len(tiers) == 1 and min(tiers, default=99) <= 1:
            conflicts.append(Conflict(
                conflict_id=hashlib.sha256(json.dumps([row.to_dict() for row in group], sort_keys=True, default=str).encode()).hexdigest(),
                date=_as_date(key[1]), severity="HIGH", conflict_type="OFFICIAL_IDENTITY_CONFLICT",
                message="Same-priority official evidence maps one historical symbol to different securities.",
                observation_ids=[row.observation_id or observation_hash(row) for row in group],
                source_urls=[row.source_url for row in group],
            ))

    events = []
    for row in chosen:
        event = _canonical(row, holidays=holidays)
        if event is None:
            conflicts.append(Conflict(
                conflict_id=observation_hash(row), date=_as_date(row.effective_date), severity="HIGH",
                conflict_type="UNRESOLVED_OBSERVATION", message="Observation lacks dates, durable identity, or known_at evidence.",
                observation_ids=[row.observation_id or observation_hash(row)], source_urls=[row.source_url],
            ))
        else:
            events.append(event)
    if not fail_on_official_conflict:
        conflicts = [conflict for conflict in conflicts if conflict.conflict_type != "OFFICIAL_SOURCE_CONFLICT"]
    return ReconciliationResult(sorted(events, key=lambda event: (event.effective_date, event.instrument_id, event.action.value)), conflicts, superseded)
