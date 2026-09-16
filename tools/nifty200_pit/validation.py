"""Fail-closed validation and certification gates for reconstructed PIT data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Iterable, Mapping

from tools.nifty200_pit.intervals import active_intervals
from tools.nifty200_pit.models import CanonicalEvent, Conflict, ConstituentInterval, EvidenceStatus, SourceRecord, ValidationReport
from tools.nifty200_pit.source_catalogue import sha256_file


class CertificationError(ValueError):
    pass


def nifty200_expected_security_count(as_of: date) -> int:
    """Count securities under the documented additional-DVR methodology.

    ind_prs22022016_2.pdf (2016-02-22), section 16, explicitly establishes
    201 securities from 2016-04-01. ind_prs10062020.pdf, section 12, removes
    TATAMTRDVR with ten exclusions and nine inclusions from 2020-06-26.
    Both first-party documents are retained in the public source catalogue.
    """
    if date(2016, 4, 1) <= as_of < date(2020, 6, 26):
        return 201
    if date(2023, 9, 29) <= as_of < date(2025, 9, 30):
        return 201
    return 200


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1) if (start + timedelta(days=offset)).weekday() < 5]


def verify_source_hashes(sources: Iterable[SourceRecord | Mapping[str, object]]) -> list[str]:
    errors = []
    for source in sources:
        row = source.to_dict() if isinstance(source, SourceRecord) else source
        path, expected = Path(str(row.get("local_path", ""))), str(row.get("source_sha256", ""))
        if not path.is_file():
            errors.append(f"missing_source:{expected}")
        elif sha256_file(path) != expected:
            errors.append(f"hash_mismatch:{expected}")
    return errors


def _overlap_errors(intervals: list[ConstituentInterval]) -> list[str]:
    errors = []
    by_instrument: dict[str, list[ConstituentInterval]] = {}
    for row in intervals:
        by_instrument.setdefault(row.instrument_id, []).append(row)
    for instrument_id, rows in by_instrument.items():
        rows.sort(key=lambda row: row.effective_from)
        for previous, current in zip(rows, rows[1:]):
            previous_end = previous.effective_until or date.max
            if current.effective_from < previous_end:
                errors.append(f"interval_overlap:{instrument_id}")
    return errors


def validate_campaign(
    intervals: Iterable[ConstituentInterval],
    events: Iterable[CanonicalEvent],
    *,
    campaign_from: date = date(2012, 1, 1),
    campaign_to: date = date(2026, 8, 31),
    trading_days: Iterable[date] | None = None,
    required_member_count: int = 200,
    expected_member_counts: Mapping[date, int] | None = None,
    conflicts: Iterable[Conflict] = (),
    source_hash_errors: Iterable[str] = (),
    anchor_differences: Iterable[str] = (),
) -> ValidationReport:
    rows, event_rows, conflict_rows = list(intervals), list(events), list(conflicts)
    source_hash_errors = list(source_hash_errors)
    anchor_differences = list(anchor_differences)
    reasons: list[str] = []
    days = list(trading_days) if trading_days is not None else _days(campaign_from, campaign_to)
    counts: dict[str, int] = {}
    for as_of in days:
        active = active_intervals(rows, as_of)
        unique = {row.instrument_id for row in active}
        counts[as_of.isoformat()] = len(unique)
        expected = expected_member_counts.get(as_of, required_member_count) if expected_member_counts else required_member_count
        if len(unique) != expected:
            reasons.append(f"member_count:{as_of.isoformat()}:{len(unique)}")
        if len(active) != len(unique):
            reasons.append(f"duplicate_active_instrument:{as_of.isoformat()}")
    reasons.extend(_overlap_errors(rows))
    reasons.extend(str(error) for error in source_hash_errors)
    reasons.extend(str(error) for error in anchor_differences)
    for event in event_rows:
        if str(event.source_tier).upper() not in {"A1", "A2"}:
            reasons.append(f"unconfirmed_membership_evidence:{event.event_hash}")
        if not event.instrument_id:
            reasons.append(f"missing_instrument_id:{event.event_hash}")
        if not event.effective_date or not event.known_at:
            reasons.append(f"missing_event_causality:{event.event_hash}")
        if not re.fullmatch(r"[0-9a-f]{64}", event.source_sha256 or ""):
            reasons.append(f"missing_source_sha:{event.event_hash}")
        if event.synthetic or str(event.source_tier).upper() == "E":
            reasons.append(f"synthetic_canonical_event:{event.event_hash}")
    for row in rows:
        if not row.instrument_id or not row.known_at or row.synthetic or row.confidence.value != "CERTIFIED":
            reasons.append(f"non_certifiable_interval:{row.interval_id}")
    for conflict in conflict_rows:
        if conflict.severity in {"HIGH", "CRITICAL"}:
            reasons.append(f"unresolved_conflict:{conflict.conflict_id}")
    deduped = list(dict.fromkeys(reasons))
    metrics = {
        "campaign_from": campaign_from.isoformat(), "campaign_to": campaign_to.isoformat(),
        "trading_days_checked": len(days),
        "count_check_failures": sum(
            count != (expected_member_counts.get(date.fromisoformat(day), required_member_count)
                      if expected_member_counts else required_member_count)
            for day, count in counts.items()
        ),
        "interval_count": len(rows), "event_count": len(event_rows), "conflict_count": len(conflict_rows),
        "high_critical_conflicts": sum(conflict.severity in {"HIGH", "CRITICAL"} for conflict in conflict_rows),
        "source_hash_errors": len(source_hash_errors), "anchor_difference_count": len(anchor_differences),
        "daily_member_counts": counts,
        "daily_expected_member_counts": {
            day.isoformat(): expected_member_counts.get(day, required_member_count)
            if expected_member_counts else required_member_count for day in days
        },
    }
    return ValidationReport(EvidenceStatus.PASS if not deduped else EvidenceStatus.BLOCKED, deduped,
                            metrics, datetime.now(timezone.utc).isoformat())


def require_certified(report: ValidationReport) -> None:
    if not report.passed:
        raise CertificationError("NIFTY-200 PIT certification blocked: " + "; ".join(report.reasons[:10]))
