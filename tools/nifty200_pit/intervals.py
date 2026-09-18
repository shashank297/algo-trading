"""Replay canonical add/drop events into exclusive membership intervals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Iterable

from tools.nifty200_pit.models import Action, CanonicalEvent, Conflict, ConstituentInterval


_INVALID_INSTRUMENT_IDS = frozenset({"", "NAN", "NONE", "NULL", "UNKNOWN", "UNRESOLVED"})


def _has_durable_identity(instrument_id: object) -> bool:
    value = str(instrument_id or "").strip()
    return value.upper() not in _INVALID_INSTRUMENT_IDS


@dataclass(frozen=True, slots=True)
class IntervalBuildResult:
    intervals: list[ConstituentInterval]
    conflicts: list[Conflict]


def _conflict(event: CanonicalEvent, kind: str, message: str) -> Conflict:
    return Conflict(
        conflict_id=hashlib.sha256(f"{event.event_hash}:{kind}".encode()).hexdigest(), date=event.effective_date,
        severity="CRITICAL", conflict_type=kind, message=message, observation_ids=[event.observation_id],
        source_urls=[event.source_url],
    )


def build_intervals(
    events: Iterable[CanonicalEvent],
    *,
    horizon_start: date = date(2011, 7, 19),
    horizon_end: date = date(2026, 8, 31),
    dataset_version: str = "NIFTY200_PIT_V1",
) -> IntervalBuildResult:
    """Replay events and fail closed on duplicate adds/removal of absent members."""
    candidates = [event for event in events if event.effective_date <= horizon_end]
    ordered = sorted(candidates, key=lambda event: (event.effective_date, event.event_hash))
    active: dict[str, ConstituentInterval] = {}
    closed: list[ConstituentInterval] = []
    conflicts: list[Conflict] = []
    same_day: dict[tuple[str, date], list[CanonicalEvent]] = {}
    for event in ordered:
        if _has_durable_identity(event.instrument_id):
            same_day.setdefault((event.instrument_id, event.effective_date), []).append(event)
    ambiguous_same_day = {
        key for key, rows in same_day.items()
        if len(rows) > 1
    }
    for event in ordered:
        if event.effective_date < horizon_start:
            continue
        if not _has_durable_identity(event.instrument_id):
            conflicts.append(_conflict(event, "MISSING_DURABLE_IDENTITY", "Cannot construct a membership interval without a durable instrument identity."))
            continue
        if (event.instrument_id, event.effective_date) in ambiguous_same_day:
            conflicts.append(_conflict(event, "SAME_DAY_EVENT_COLLISION", "Multiple membership assertions for one instrument on one effective date require manual ordering evidence."))
            continue
        if event.action in (Action.ADD, Action.INITIAL_MEMBER):
            if event.instrument_id in active:
                conflicts.append(_conflict(event, "DUPLICATE_ADD", "Cannot add an already active instrument."))
                continue
            active[event.instrument_id] = ConstituentInterval(
                interval_id=hashlib.sha256(f"{event.event_hash}:interval".encode()).hexdigest(),
                index_id=event.index_id, instrument_id=event.instrument_id, symbol_at_entry=event.symbol,
                isin_at_entry=event.isin, company_name=event.company_name, effective_from=event.effective_date,
                effective_until=None, known_from=event.announcement_date, known_at=event.known_at,
                reason=event.reason, entry_event_hash=event.event_hash, exit_event_hash=None,
                confidence=event.confidence, dataset_version=dataset_version, synthetic=event.synthetic,
            )
        elif event.action == Action.DROP:
            prior = active.pop(event.instrument_id, None)
            if prior is None:
                conflicts.append(_conflict(event, "REMOVAL_OF_ABSENT_MEMBER", "Cannot remove an inactive instrument."))
                continue
            if event.effective_date <= prior.effective_from:
                conflicts.append(_conflict(event, "NON_POSITIVE_INTERVAL", "A DROP cannot close an interval on or before its ADD date."))
                active[event.instrument_id] = prior
                continue
            closed.append(ConstituentInterval(
                interval_id=prior.interval_id, index_id=prior.index_id, instrument_id=prior.instrument_id,
                symbol_at_entry=prior.symbol_at_entry, isin_at_entry=prior.isin_at_entry, company_name=prior.company_name,
                effective_from=prior.effective_from, effective_until=event.effective_date, known_from=prior.known_from,
                known_at=prior.known_at, reason=prior.reason, entry_event_hash=prior.entry_event_hash,
                exit_event_hash=event.event_hash, confidence=prior.confidence, dataset_version=prior.dataset_version,
                synthetic=prior.synthetic,
            ))
    result = closed + list(active.values())
    return IntervalBuildResult(sorted(result, key=lambda row: (row.effective_from, row.instrument_id)), conflicts)


def active_intervals(intervals: Iterable[ConstituentInterval], as_of: date) -> list[ConstituentInterval]:
    return [row for row in intervals if row.effective_from <= as_of and (row.effective_until is None or as_of < row.effective_until)]


def build_snapshots(intervals: Iterable[ConstituentInterval], dates: Iterable[date]) -> list[dict[str, object]]:
    rows = list(intervals)
    snapshots = []
    for as_of in sorted(set(dates)):
        members = active_intervals(rows, as_of)
        snapshots.append({"date": as_of.isoformat(), "member_count": len(members),
                          "instrument_ids": sorted(row.instrument_id for row in members),
                          "symbols": sorted(row.symbol_at_entry for row in members)})
    return snapshots


def monthly_snapshot_dates(start: date, end: date) -> list[date]:
    current = date(start.year, start.month, 1)
    result = []
    while current <= end:
        result.append(current)
        current = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
    return result
