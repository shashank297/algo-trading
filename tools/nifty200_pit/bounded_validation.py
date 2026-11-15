"""Consume a hash-bound bounded evidence package without promoting evidence."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from tools.nifty200_pit.intervals import active_intervals
from tools.nifty200_pit.models import Action, EvidenceStatus, ValidationReport
from tools.nifty200_pit.source_catalogue import sha256_file
from tools.nifty200_pit.validation import validate_campaign, verify_source_hashes


class BoundedInputError(ValueError):
    """The package cannot establish the requested validation inputs."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise BoundedInputError(reason)


def _stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    _require(stamp.utcoffset() is not None, "timezone_required")
    return stamp


def _read(path: Path) -> Any:
    _require(path.suffix.lower() == ".json", "json_artifact_required")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_bounded_package(
    package_path: Path, *, campaign_from: date, campaign_to: date,
) -> ValidationReport:
    """Verify package evidence, exact replay, then execute the production validator.

    This consumes reviewed evidence; it neither certifies raw source semantics nor
    creates identity, membership, calendar, or conflict-disposition assertions.
    """
    try:
        return _validate(package_path.resolve(), campaign_from, campaign_to)
    except (BoundedInputError, OSError, ValueError, KeyError, TypeError) as exc:
        return ValidationReport(
            EvidenceStatus.BLOCKED, [f"bounded_input:{exc}"],
            {"campaign_from": campaign_from.isoformat(), "campaign_to": campaign_to.isoformat(),
             "bounded_inputs_evaluable": False, "actual_validator_executed": False},
            datetime.now(timezone.utc).isoformat(),
        )


def _validate(package_path: Path, start: date, end: date) -> ValidationReport:
    # Import only at execution: the CLI also dispatches to this module.
    from tools.nifty200_pit.cli import _conflict, _event, _interval

    _require(start <= end, "invalid_campaign_range")
    package = _read(package_path)
    _require(package["schema_version"] == 1 and package["index_id"] == "NIFTY_200", "package_schema")
    _require(package["campaign_from"] == start.isoformat() and package["campaign_to"] == end.isoformat(), "package_range")
    artifacts = package["artifacts"]
    required = {"source_catalogue", "anchor", "calendar", "identities", "continuity", "events", "intervals", "checkpoints", "conflicts"}
    _require(not (required - set(artifacts)), "missing_artifacts:" + ",".join(sorted(required - set(artifacts))))

    def artifact(name: str) -> Any:
        spec = artifacts[name]
        path = package_path.parent / spec["path"]
        _require(path.suffix.lower() == ".json", f"json_artifact_required:{name}")
        _require(sha256_file(path) == spec["sha256"], f"artifact_hash:{name}")
        return _read(path)

    sources = artifact("source_catalogue")
    _require(isinstance(sources, list) and bool(sources), "source_catalogue_empty")
    _require(all(Path(r["local_path"]).suffix.lower() not in {".duckdb", ".wal"} for r in sources), "database_source_forbidden")
    hash_errors = verify_source_hashes(sources)
    _require(not hash_errors, "source_hashes:" + ";".join(hash_errors))
    source_by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in sources:
        source_by_hash.setdefault(row["source_sha256"], []).append(row)

    def source(digest: str, url: str | None = None) -> None:
        rows = source_by_hash.get(digest, [])
        _require(any(r.get("source_tier") in {"A1", "A2"} and
                     (url is None or r["source_url"] == url) for r in rows), f"unregistered_authority:{digest}")

    def proof(row: dict[str, Any]) -> None:
        _require(row["confidence"] == "CERTIFIED" and row["review_status"] == "ACCEPTED", "evidence_not_accepted")
        source(row["source_sha256"], row["source_url"])

    def causal_source(digest: str, url: str, stamp: datetime, *, publication_date: date | None = None, exact: bool = False) -> None:
        matches = [r for r in source_by_hash.get(digest, [])
                   if r.get("source_tier") in {"A1", "A2"} and r["source_url"] == url]
        _require(len({r["document_date"] for r in matches if r.get("document_date")}) <= 1 and
                 len({r["publication_timestamp"] for r in matches if r.get("publication_timestamp")}) <= 1,
                 "conflicting_source_publication")
        for record in matches:
            if not record.get("document_date") or len(str(record["document_date"])) < 10:
                continue
            try:
                published = date.fromisoformat(str(record["document_date"])[:10])
            except ValueError:
                try:
                    published = datetime.strptime(str(record["document_date"]).strip(), "%d-%b-%Y").date()
                except ValueError:
                    continue
            if publication_date is not None and publication_date != published:
                continue
            if record.get("publication_timestamp"):
                available = _stamp(record["publication_timestamp"])
                if available.astimezone(ist).date() == published and (available == stamp if exact else available <= stamp):
                    return
            elif not exact:
                later = [d for d in opens if d > published]
                if later and opens[min(later)] <= stamp:
                    return
        raise BoundedInputError("source_publication_not_established")

    def member_ids(rows: list[dict[str, Any]], day: date) -> set[str]:
        for row in rows:
            proof(row)
            _require(bool(row["instrument_id"]) and bool(row["isin"]), "member_identity_missing")
            _require(identity_valid(row, day), "member_identity_not_period_valid")
        ids = {r["instrument_id"] for r in rows}
        _require(len(ids) == len(rows) and len({r["isin"] for r in rows}) == len(rows), "duplicate_member_identity")
        return ids

    def identity_valid(row: dict[str, Any], day: date) -> bool:
        return (row.get("has_explicit_historical_interval") is True and
                bool(row.get("valid_from")) and date.fromisoformat(row["valid_from"]) <= day and
                (not row.get("valid_until") or day < date.fromisoformat(row["valid_until"])))

    calendar = artifact("calendar")
    proof(calendar)
    # Count admission is separate from calendar admission. Coverage is inclusive;
    # a registered holiday source hash alone is never a membership-count proof.
    count_evidence = calendar.get("count_evidence")
    _require(isinstance(count_evidence, list) and bool(count_evidence), "member_count_evidence_missing")
    count_periods = []
    for evidence in count_evidence:
        _require(isinstance(evidence, dict), "member_count_evidence_schema")
        _require(evidence["evidence_type"] == "MEMBERSHIP_COUNT" and
                 evidence["index_id"] == "NIFTY_200", "member_count_evidence_semantics")
        proof(evidence)
        count = evidence["expected_member_count"]
        _require(type(count) is int and count in {200, 201}, "unsupported_member_count")
        count_from = date.fromisoformat(evidence["coverage_from"])
        count_to = date.fromisoformat(evidence["coverage_to"])
        _require(count_from <= count_to, "member_count_evidence_range")
        count_periods.append((count_from, count_to, evidence))
    first, last = date.fromisoformat(calendar["coverage_from"]), date.fromisoformat(calendar["coverage_to"])
    _require(first <= start <= end <= last, "calendar_coverage_range")
    records = calendar["records"]
    calendar_rows = {date.fromisoformat(r["date"]): r for r in records}
    required_dates = {first + timedelta(days=i) for i in range((last - first).days + 1)}
    _require(len(calendar_rows) == len(records) and set(calendar_rows) == required_dates, "calendar_coverage_incomplete")
    opens: dict[date, datetime] = {}
    expected_counts: dict[date, int] = {}
    ist = timezone(timedelta(hours=5, minutes=30))
    for day, row in sorted(calendar_rows.items()):
        source(row["source_sha256"])
        _require(type(row["is_session"]) is bool, "calendar_session_flag")
        if row["is_session"]:
            opening = _stamp(row["open_at"])
            _require(opening.astimezone(ist).date() == day, "session_open_date")
            opens[day] = opening
            if start <= day <= end:
                count = row["expected_member_count"]
                _require(type(count) is int and count in {200, 201}, "unsupported_member_count")
                covering = [e for lo, hi, e in count_periods if lo <= day <= hi]
                _require(bool(covering) and
                         all(e["expected_member_count"] == count for e in covering),
                         f"member_count_evidence_coverage_or_conflict:{day}")
                _require(any(e["source_sha256"] == row["count_source_sha256"] for e in covering),
                         f"member_count_evidence_source:{day}")
                expected_counts[day] = count
    days = [d for d in sorted(opens) if start <= d <= end]
    _require(bool(days) and start in opens, "anchor_start_not_session")

    anchor = artifact("anchor")
    proof(anchor)
    _require(not anchor.get("missing_evidence"), "anchor_derivation_evidence_unresolved")
    _require(anchor["date"] == start.isoformat(), "anchor_date")
    _require(_stamp(anchor["known_at"]) <= opens[start], "anchor_causality")
    causal_source(anchor["source_sha256"], anchor["source_url"], _stamp(anchor["known_at"]))
    seed = member_ids(anchor["members"], start)
    _require(len(seed) == expected_counts[start], "anchor_member_count")

    links = artifact("continuity")
    for link in links:
        proof(link)
        rename = bool(link.get("from_symbol")) and bool(link.get("to_symbol")) and link["from_symbol"] != link["to_symbol"]
        _require(link["from_instrument_id"] != link["to_instrument_id"] or (rename and bool(link.get("isin"))), "continuity_self_link")
        effective = date.fromisoformat(link["effective_date"])
        _require(effective in opens and _stamp(link["known_at"]) <= opens[effective], "continuity_causality")
        causal_source(link["source_sha256"], link["source_url"], _stamp(link["known_at"]))

    def normalize(identity: str, day: date) -> str:
        mapping: dict[str, str] = {}
        for link in links:
            if date.fromisoformat(link["effective_date"]) <= day:
                old, new = link["from_instrument_id"], link["to_instrument_id"]
                if old == new:
                    continue
                _require(old not in mapping or mapping[old] == new, "competing_continuity")
                mapping[old] = new
        seen = set()
        while identity in mapping:
            _require(identity not in seen, "continuity_cycle")
            seen.add(identity)
            identity = mapping[identity]
        return identity

    def normalize_symbol(symbol: str, identity: str, day: date) -> str:
        mapping: dict[str, str] = {}
        for link in links:
            if (link.get("from_symbol") and link.get("to_symbol") and
                    date.fromisoformat(link["effective_date"]) <= day and
                    normalize(link["from_instrument_id"], day) == normalize(identity, day)):
                old, new = link["from_symbol"], link["to_symbol"]
                _require(old not in mapping or mapping[old] == new, "competing_symbol_transition")
                mapping[old] = new
        seen = set()
        while symbol in mapping:
            _require(symbol not in seen, "symbol_transition_cycle")
            seen.add(symbol)
            symbol = mapping[symbol]
        return symbol

    def normalized(ids: set[str], day: date) -> set[str]:
        value = {normalize(i, day) for i in ids}
        _require(len(value) == len(ids), "continuity_collapses_members")
        return value

    identities = artifact("identities")
    identities_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for identity_row in identities:
        identities_by_symbol.setdefault(identity_row["symbol"], []).append(identity_row)

    def identity_proof(symbol: str, identity: str, isin: str | None, day: date) -> None:
        _require(bool(identity) and identity.upper() not in {"NONE", "NULL", "NAN", "UNKNOWN", "UNRESOLVED"}
                 and (isin is None or bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin))), "invalid_durable_identity")
        candidates = [r for r in identities_by_symbol.get(symbol, []) if
                      (not r.get("valid_until") or day < date.fromisoformat(r["valid_until"])) and
                      (not r.get("valid_from") or date.fromisoformat(r["valid_from"]) <= day)]
        _require(bool(candidates), f"identity_evidence_missing:{symbol}:{day}")
        for candidate in candidates:
            proof(candidate)
            _require(identity_valid(candidate, day), f"identity_interval_unproven:{symbol}:{day}")
            _require(normalize(candidate["instrument_id"], day) == normalize(identity, day) and
                     bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", candidate["isin"] or "")) and
                     (isin is None or candidate["isin"] == isin),
                     f"competing_identity:{symbol}:{day}")
        _require(len({c["isin"] for c in candidates}) == 1, f"competing_identity:{symbol}:{day}")

    for member in anchor["members"]:
        identity_proof(member["symbol"], member["instrument_id"], member["isin"], start)
    for link in links:
        if link["from_instrument_id"] == link["to_instrument_id"]:
            effective = date.fromisoformat(link["effective_date"])
            previous = [d for d in opens if d < effective]
            _require(bool(previous), "symbol_transition_prior_session_required")
            identity_proof(link["from_symbol"], link["from_instrument_id"], link["isin"], max(previous))
            identity_proof(link["to_symbol"], link["to_instrument_id"], link["isin"], effective)

    events = [_event(r) for r in artifact("events")]
    intervals = [_interval(r) for r in artifact("intervals")]
    conflicts = [_conflict(r) for r in artifact("conflicts")]
    _require(all(e.index_id == "NIFTY_200" for e in events) and all(r.index_id == "NIFTY_200" for r in intervals), "mixed_index_package")
    _require(all(e.effective_date <= end for e in events), "future_event_in_bounded_package")
    event_by_hash = {e.event_hash: e for e in events}
    _require(len(event_by_hash) == len(events), "duplicate_event_hash")
    event_keys = Counter((normalize(e.instrument_id, e.effective_date), e.effective_date) for e in events)
    _require(all(n == 1 for n in event_keys.values()), "same_day_event_collision")
    for event in events:
        source(event.source_sha256, event.source_url)
        identity_proof(event.symbol, event.instrument_id, event.isin, event.effective_date)
        _require(event.effective_date in opens, f"event_effective_session:{event.event_hash}")
        _require(_stamp(event.known_at.isoformat()) <= opens[event.effective_date], f"event_causality:{event.event_hash}")
        if event.known_at_basis == "DATE_ONLY_CONSERVATIVE_NEXT_SESSION":
            _require(event.announcement_date < event.effective_date, f"event_chronology:{event.event_hash}")
            causal_source(event.source_sha256, event.source_url, event.known_at, publication_date=event.announcement_date)
            _require(first <= event.announcement_date, "publication_calendar_coverage")
            later = [d for d in opens if d > event.announcement_date]
            _require(bool(later) and event.known_at == opens[min(later)], f"event_known_at_session:{event.event_hash}")
        else:
            _require(event.known_at_basis == "EXACT_SOURCE_TIMESTAMP", "unsupported_known_at_basis")
            _require(event.known_at.astimezone(ist).date() == event.announcement_date <= event.effective_date,
                     f"event_chronology:{event.event_hash}")
            causal_source(event.source_sha256, event.source_url, event.known_at,
                          publication_date=event.announcement_date, exact=True)

    # A seed is a source-backed state, never a fabricated INITIAL_MEMBER event.
    seed_reference = "ANCHOR:" + artifacts["anchor"]["sha256"]
    post_bound_exits = []
    for row in intervals:
        _require(row.effective_until is None or row.effective_until > row.effective_from, "non_positive_interval")
        _require(_stamp(row.known_at.isoformat()) <= opens.get(row.effective_from, opens[start]), "interval_causality")
        _require(row.known_from <= row.known_at.astimezone(ist).date(), "interval_knowledge_dates")
        if row.entry_event_hash == seed_reference:
            _require(row.effective_from == start and row.instrument_id in seed and row.known_at == _stamp(anchor["known_at"]), "seed_interval_lineage")
            member = next(m for m in anchor["members"] if m["instrument_id"] == row.instrument_id)
            _require(row.symbol_at_entry == member["symbol"] and row.isin_at_entry == member["isin"], "seed_interval_identity")
        else:
            entry = event_by_hash.get(row.entry_event_hash)
            _require(entry is not None, "interval_entry_event_missing")
            assert entry is not None
            _require(entry.action in {Action.ADD, Action.INITIAL_MEMBER} and
                     entry.instrument_id == row.instrument_id and entry.effective_date == row.effective_from and
                     entry.known_at == row.known_at and entry.announcement_date == row.known_from and
                     entry.symbol == row.symbol_at_entry and entry.isin == row.isin_at_entry, "interval_entry_lineage")
        if row.exit_event_hash:
            _require(row.effective_until is not None, "interval_exit_date_missing")
            assert row.effective_until is not None
            if row.effective_until > end:
                post_bound_exits.append(row.interval_id)
            else:
                exit_event = event_by_hash.get(row.exit_event_hash)
                _require(exit_event is not None and exit_event.action == Action.DROP and exit_event.effective_date == row.effective_until and
                         normalize(exit_event.instrument_id, exit_event.effective_date) == normalize(row.instrument_id, exit_event.effective_date), "interval_exit_lineage")
        elif row.effective_until is not None and row.effective_until <= end:
            raise BoundedInputError("interval_exit_event_missing")

    checkpoints = artifact("checkpoints")
    by_date = {date.fromisoformat(r["date"]): r for r in checkpoints}
    monthly = {(d.year, d.month): d for d in days}
    required_checkpoints = {start, *monthly.values()}
    _require(len(by_date) == len(checkpoints) and required_checkpoints <= set(by_date) <= set(days), "checkpoint_coverage")
    targets = {}
    for day, checkpoint in by_date.items():
        proof(checkpoint)
        targets[day] = normalized(member_ids(checkpoint["members"], day), day)
        for member in checkpoint["members"]:
            identity_proof(member["symbol"], member["instrument_id"], member["isin"], day)

    errors: list[str] = []
    at_start = {e.event_hash for e in events if e.effective_date == start}
    _require(set(anchor["applied_event_hashes"]) == at_start, "anchor_event_linkage")
    initial = normalized(seed, start)
    for event in events:
        if event.effective_date == start:
            included = normalize(event.instrument_id, start) in initial
            _require(included == (event.action != Action.DROP), "anchor_event_postcondition")
    state = seed
    for day in days:
        state = normalized(state, day)
        for event in sorted((e for e in events if e.effective_date == day and day > start), key=lambda e: e.event_hash):
            identity = normalize(event.instrument_id, day)
            if event.action == Action.DROP:
                if identity not in state:
                    errors.append(f"bounded_absent_drop:{event.event_hash}")
                state.discard(identity)
            else:
                if identity in state:
                    errors.append(f"bounded_duplicate_add:{event.event_hash}")
                state.add(identity)
        active = active_intervals(intervals, day)
        for row in active:
            identity_proof(normalize_symbol(row.symbol_at_entry, row.instrument_id, day), row.instrument_id, None, day)
        ids = normalized({r.instrument_id for r in active}, day)
        if len(active) != len(ids) or ids != state:
            errors.append(f"interval_replay_members:{day}")
        if day in targets and (state != targets[day] or ids != targets[day]):
            errors.append(f"checkpoint_members:{day}")

    # Preserve pre-bound and undated blockers: their effect on the seed is unproven.
    applicable = [c for c in conflicts if c.date is None or c.date <= end]
    report = validate_campaign(
        intervals, events, campaign_from=start, campaign_to=end, trading_days=days,
        expected_member_counts=expected_counts, initial_anchor_established=True,
        conflicts=applicable, source_hash_errors=hash_errors, anchor_differences=errors,
        calendar_provenance=artifacts["calendar"]["sha256"], calendar_certified=True,
    )
    report.metrics.update({
        "bounded_inputs_evaluable": True, "actual_validator_executed": True,
        "package_sha256": sha256_file(package_path), "artifact_hashes": {n: r["sha256"] for n, r in artifacts.items()},
        "checkpoint_count": len(checkpoints), "exact_checkpoint_failures": sum(r.startswith("checkpoint_members:") for r in errors),
        "post_bound_conflict_ids": [c.conflict_id for c in conflicts if c.date is not None and c.date > end],
        "post_bound_interval_exit_ids": post_bound_exits,
    })
    return report
