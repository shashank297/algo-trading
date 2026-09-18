"""Evidence-priority reconciliation; no majority voting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import hashlib
import json
import re
import unicodedata
from typing import Iterable

from tools.nifty200_pit.causality import derive_known_at
from tools.nifty200_pit.models import (
    Action,
    CanonicalEvent,
    Conflict,
    Confidence,
    LineageRelation,
    Observation,
    ObservationLineage,
    ReviewStatus,
    stable_observation_id,
)

_TIER_RANK = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5, "D": 6, "E": 7}


def _normalise_company_name(value: object) -> str:
    """Create a conservative comparison key for corroborating legal names.

    This key is used only to connect an official company-only assertion to a
    B1 search-index assertion.  It never creates an identity mapping or
    promotes a B1 row to canonical status.
    """
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = text.replace("&", " and ").casefold()
    text = re.sub(r"^\s*\d+\s+", "", text)
    text = re.sub(r"\bcorp\.?\b", "corporation", text)
    text = re.sub(r"\bco\.?\b", "company", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _corroboration_key(row: Observation) -> tuple[object, ...] | None:
    company = _normalise_company_name(row.company_name)
    effective = _as_date(row.effective_date)
    action = _as_action(row.action)
    if not company or not effective or not action:
        return None
    return row.index_id, effective, action, company


def _normalise_symbol(value: object) -> str:
    """Normalize an exchange symbol for exact evidence cross-referencing."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _authority_match_key(row: Observation) -> tuple[object, ...] | None:
    """Return an exact non-date claim key for B1/A1 event comparison.

    This is deliberately narrower than fuzzy entity matching.  It is used to
    recognize a B1 effective-date discrepancy when an A1/A2 source already
    covers the same indexed symbol/company and action.
    """
    action = _as_action(row.action)
    symbol = _normalise_symbol(row.symbol)
    company = _normalise_company_name(row.company_name)
    if not action or not (symbol or company):
        return None
    return row.index_id, action, symbol, company


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
    """Return the stable raw-evidence ID for compatibility with old callers."""
    return stable_observation_id(observation)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    events: list[CanonicalEvent]
    conflicts: list[Conflict]
    superseded_observation_ids: list[str]
    lineage: list[ObservationLineage]

    @property
    def blocked(self) -> bool:
        return any(conflict.severity in {"HIGH", "CRITICAL"} for conflict in self.conflicts)


def _event_key(row: Observation) -> tuple[object, ...]:
    return (row.index_id, _as_date(row.effective_date), row.instrument_id or row.symbol or row.company_name, _as_action(row.action))


def _canonical(row: Observation, *, holidays: set[date] | None = None) -> CanonicalEvent | None:
    effective = _as_date(row.effective_date)
    announcement = _as_date(row.announcement_date)
    action = _as_action(row.action)
    if (
        not effective or not announcement or not action or not row.instrument_id or not row.symbol
        or str(row.source_tier).upper() not in {"A1", "A2"}
        or str(row.confidence).upper() != "CERTIFIED"
        or str(row.review_status).upper() != "ACCEPTED"
    ):
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
    rows = [
        row if row.observation_id else replace(row, observation_id=stable_observation_id(row))
        for row in observations
    ]
    groups: dict[tuple[object, ...], list[Observation]] = {}
    conflicts: list[Conflict] = []
    superseded: list[str] = []
    lineage: list[ObservationLineage] = []

    official_by_claim: dict[tuple[object, ...], list[Observation]] = {}
    official_by_authority_match: dict[tuple[object, ...], list[Observation]] = {}
    for row in rows:
        if str(row.source_tier).upper() in {"A1", "A2"}:
            claim = _corroboration_key(row)
            if claim is not None:
                official_by_claim.setdefault(claim, []).append(row)
            authority_match = _authority_match_key(row)
            if authority_match is not None:
                official_by_authority_match.setdefault(authority_match, []).append(row)
    corroborated_b1: dict[str, Observation] = {}
    authority_covered_b1: dict[str, Observation] = {}

    def observation_id(row: Observation) -> str:
        return row.observation_id or observation_hash(row)

    def add_lineage(
        row: Observation,
        related: Observation | None,
        relation: LineageRelation,
        basis: str,
    ) -> None:
        lineage.append(ObservationLineage(
            observation_id=observation_id(row),
            related_observation_id=observation_id(related) if related else None,
            relationship_type=relation,
            relation_basis=basis,
            source_url=row.source_url,
            source_sha256=row.source_sha256,
            source_tier=str(row.source_tier),
            review_status=row.review_status,
        ))

    # A1/A2 workbook rows often contain only a legal company name while the
    # B1 search index contains the symbol.  Connect those assertions by exact
    # normalized name/date/action only.  This is evidence corroboration, not
    # historical identity resolution and not B1 promotion.
    for row in rows:
        if str(row.source_tier).upper() != "B1":
            continue
        claim = _corroboration_key(row)
        matches = official_by_claim.get(claim, []) if claim is not None else []
        if matches:
            official = matches[0]
            corroborated_b1[observation_id(row)] = official
            add_lineage(
                row,
                official,
                LineageRelation.CORROBORATED,
                "exact normalized company name, effective date, and action match to A1/A2 evidence",
            )
        else:
            # A B1 reconstruction can carry a stale or differently-defined
            # effective date.  If exactly one authoritative source has the
            # same indexed symbol/company and action, retain the discrepancy
            # as lineage but do not misclassify the B1 search-index row as a
            # missing official event.  The B1 row remains provisional and is
            # never promoted to a canonical event.
            authority_key = _authority_match_key(row)
            authority_matches = (
                official_by_authority_match.get(authority_key, [])
                if authority_key is not None
                else []
            )
            if len(authority_matches) == 1:
                official = authority_matches[0]
                authority_covered_b1[observation_id(row)] = official
                basis = (
                    "exact normalized symbol/company and action match to A1/A2 evidence; "
                    f"effective date differs (B1={_as_date(row.effective_date)}, "
                    f"official={_as_date(official.effective_date)})"
                )
                add_lineage(row, official, LineageRelation.CONFLICTS_WITH, basis)
                add_lineage(official, row, LineageRelation.CONFLICTS_WITH, basis)
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
            for row in top:
                if row is not winner:
                    add_lineage(winner, row, LineageRelation.SUPERSEDES, "explicit correction or supersedes assertion")
                    add_lineage(row, winner, LineageRelation.SUPERSEDED_BY, "selected correction or superseding assertion")
        # A corroborating workbook row may omit a symbol while resolving to
        # the same durable instrument.  Missing descriptive metadata is not a
        # semantic contradiction; only explicit identity/action/date changes
        # at the same evidence tier are conflicts.
        semantic = {
            (row.instrument_id, _as_action(row.action), _as_date(row.effective_date))
            for row in top
        }
        if len(semantic) > 1:
            for row in top:
                for related in top:
                    if row is not related:
                        add_lineage(row, related, LineageRelation.CONFLICTS_WITH, "same-priority evidence asserts different event semantics")
            conflicts.append(Conflict(
                conflict_id=hashlib.sha256(json.dumps([row.to_dict() for row in top], sort_keys=True, default=str).encode()).hexdigest(),
                date=_as_date(key[1]), severity="HIGH" if top_rank <= 1 else "MEDIUM", conflict_type="OFFICIAL_SOURCE_CONFLICT",
                message="Same-priority evidence asserts different membership events; fail closed.",
                observation_ids=[row.observation_id or observation_hash(row) for row in top],
                source_urls=[row.source_url for row in top],
            ))
        else:
            for row in group:
                if row is winner:
                    continue
                relation = LineageRelation.REDUNDANT if (
                    row.source_url == winner.source_url and row.source_sha256 == winner.source_sha256
                ) else LineageRelation.CORROBORATED
                add_lineage(winner, row, relation, "same event key and equivalent semantic assertion")
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
            for row in group:
                for related in group:
                    if row is not related and row.instrument_id != related.instrument_id:
                        add_lineage(row, related, LineageRelation.CONFLICTS_WITH, "same symbol maps to different durable identities")
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
            if str(row.source_tier).upper() == "B1" and (
                observation_id(row) in corroborated_b1 or observation_id(row) in authority_covered_b1
            ):
                # The official row will retain the identity/causality blocker;
                # the B1 assertion itself is no longer a missing-authority
                # claim, but remains non-canonical and provisional.  A date
                # mismatch is retained in lineage above.
                continue
            if str(row.source_tier).upper() not in {"A1", "A2"}:
                unresolved_type = "MISSING_OFFICIAL_EVENT"
                unresolved_message = "Non-first-party challenger evidence is retained as a search index and cannot become a canonical event without corroborating A1/A2 evidence."
            elif not row.instrument_id:
                unresolved_type = "MISSING_DURABLE_IDENTITY"
                unresolved_message = "Official observation lacks a durable historical instrument identity."
            elif not row.announcement_date or not row.effective_date or not row.known_at:
                unresolved_type = "MISSING_EVENT_CAUSALITY"
                unresolved_message = "Official observation lacks a complete announcement, effective-date, or known-at chain."
            else:
                unresolved_type = "UNRESOLVED_OBSERVATION"
                unresolved_message = "Official observation is not certifiable under the evidence policy."
            add_lineage(row, None, LineageRelation.UNRESOLVED, unresolved_message)
            conflicts.append(Conflict(
                conflict_id=observation_hash(row), date=_as_date(row.effective_date), severity="HIGH",
                conflict_type=unresolved_type, message=unresolved_message,
                observation_ids=[row.observation_id or observation_hash(row)], source_urls=[row.source_url],
            ))
        else:
            events.append(event)
    if not fail_on_official_conflict:
        conflicts = [conflict for conflict in conflicts if conflict.conflict_type != "OFFICIAL_SOURCE_CONFLICT"]
    return ReconciliationResult(
        sorted(events, key=lambda event: (event.effective_date, event.instrument_id, event.action.value)),
        conflicts,
        superseded,
        lineage,
    )
