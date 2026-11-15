"""Historical instrument identity resolution with fail-closed fuzzy matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
import re
from typing import Any, Iterable

from tools.nifty200_pit.models import Observation, stable_observation_id


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"", "nan", "nat", "none", "null", "na", "n/a", "unknown", "unresolved"}:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _norm(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in {"", "nan", "nat", "none", "null", "na", "n/a", "unknown", "unresolved"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _norm_company(value: object) -> str:
    normalized = _norm(str(value or "").replace("&", " AND "))
    for suffix in ("LIMITED", "LTD", "COMPANY", "CO", "CORPORATION", "CORP"):
        while normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    return normalized


def _snapshot_choice(rows: list[dict[str, Any]], when: date | None) -> dict[str, Any] | None:
    if when is None:
        return None
    dated = [
        row for row in rows
        if (snapshot_date := _date(row.get("snapshot_date"))) is not None and snapshot_date <= when
    ]
    if not dated:
        return None
    snapshot_dates = [value for row in dated if (value := _date(row.get("snapshot_date"))) is not None]
    latest = max(snapshot_dates)
    candidates = [row for row in dated if _date(row.get("snapshot_date")) == latest]
    instruments = {(str(row.get("instrument_id")), str(row.get("isin") or "")) for row in candidates}
    return candidates[0] if len(instruments) == 1 else None


def _unique_instrument_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate repeated snapshots without collapsing distinct ISINs."""
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        instrument_id = str(row.get("instrument_id") or "")
        key = (instrument_id, str(row.get("isin") or ""))
        if instrument_id and key not in unique:
            unique[key] = row
    return list(unique.values())


def _build_indexes(
    rows: Iterable[dict[str, Any]], aliases: Iterable[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]
]:
    filtered = [dict(row) for row in rows if str(row.get("series") or "").upper() != "IL"]
    by_isin: dict[str, list[dict[str, Any]]] = {}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    by_company: dict[str, list[dict[str, Any]]] = {}
    by_alias: dict[str, list[dict[str, Any]]] = {}
    for row in filtered:
        if key := _norm(row.get("isin")):
            by_isin.setdefault(key, []).append(row)
        if key := _norm(row.get("symbol")):
            by_symbol.setdefault(key, []).append(row)
        if key := _norm_company(row.get("company_name")):
            by_company.setdefault(key, []).append(row)
    for alias in aliases:
        if str(alias.get("series") or "").upper() != "IL":
            if key := _norm(alias.get("alias_symbol") or alias.get("symbol")):
                by_alias.setdefault(key, []).append(alias)
    return filtered, by_isin, by_symbol, by_company, by_alias


def _durable_id(value: object) -> str | None:
    normalized = _norm(value)
    if not normalized or normalized in {"NAN", "NONE", "NULL", "UNKNOWN", "UNRESOLVED"}:
        return None
    return str(value).strip()


def _candidate_ids(rows: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        candidate
        for row in rows
        if (candidate := _durable_id(row.get("instrument_id"))) is not None
    ))


def _evidence_admissible(row: dict[str, Any]) -> bool:
    """Return whether an identity row is allowed to produce certification."""
    source_tier = str(row.get("source_tier") or "A1").upper()
    confidence = str(row.get("confidence") or "CERTIFIED").upper()
    review_status = str(row.get("review_status") or "ACCEPTED").upper()
    return (
        source_tier in {"A1", "A2"}
        and confidence == "CERTIFIED"
        and review_status == "ACCEPTED"
    )


def _identity_value(value: object) -> str | None:
    """Return a persisted identity value only when it is not a sentinel."""
    normalized = _norm(value)
    return normalized or None


def _date_field_is_invalid(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, date):
        return False
    text = str(value).strip().casefold()
    if text in {"", "nan", "nat", "none", "null", "na", "n/a", "unknown", "unresolved"}:
        return False
    return _date(value) is None


@dataclass(frozen=True, slots=True)
class Resolution:
    instrument_id: str | None
    isin: str | None
    method: str
    confidence: str
    candidates: tuple[str, ...] = ()
    reason: str | None = None


def _valid_on(row: dict[str, Any], when: date | None) -> bool:
    if _date_field_is_invalid(row.get("valid_from")) or _date_field_is_invalid(row.get("valid_until")):
        return False
    start, end = _date(row.get("valid_from")), _date(row.get("valid_until"))
    if end is not None and start is None:
        return False
    if start is not None and end is not None and start >= end:
        return False
    if when is None:
        return True
    snapshot = _date(row.get("snapshot_date") or row.get("observed_snapshot_date"))
    effective_start: date | None = start
    # A snapshot-only observation proves the identity at the observed snapshot
    # date, not continuously back to the listing date.  The same lower bound
    # applies to the current security master: listing date alone cannot prove
    # that the symbol/ISIN relationship was unchanged before the snapshot.
    # Explicit historical intervals are the only exception because their
    # period validity is established by separate evidence.
    if snapshot is not None and not row.get("has_explicit_historical_interval"):
        effective_start = snapshot if (start is None or start < snapshot) else start
    return (effective_start is None or when >= effective_start) and (end is None or when < end)


_OPEN_ENDED_TRANSITION_TYPES = {
    "OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD",
    "OFFICIAL_NAME_CHANGE_CERTIFIED_FORWARD",
}


def _is_dvr_row(row: dict[str, Any]) -> bool:
    return (
        _norm(row.get("symbol")).endswith("DVR")
        or bool(re.search(r"\bDVR\b", str(row.get("company_name") or ""), re.I))
    )


def _company_scope_rows(
    company_name: object, rows_by_company: dict[str, list[dict[str, Any]]], *, dvr_only: bool | None = None,
) -> list[dict[str, Any]]:
    raw_company = str(company_name or "")
    company_for_match = re.sub(r"\s+DVR\s*$", "", raw_company, flags=re.I)
    company = _norm_company(company_for_match)
    if not company:
        return []
    rows = rows_by_company.get(company, [])
    require_dvr = bool(re.search(r"\bDVR\b", raw_company, re.I)) if dvr_only is None else dvr_only
    if require_dvr:
        return [row for row in rows if _norm(row.get("symbol")).endswith("DVR")]
    return rows


def _explicit_identity_segment(row: dict[str, Any]) -> bool:
    """Whether row dates establish a segment rather than an open snapshot."""
    if not row.get("has_explicit_historical_interval"):
        return False
    if _date_field_is_invalid(row.get("valid_from")) or _date_field_is_invalid(row.get("valid_until")):
        return False
    start = _date(row.get("valid_from"))
    end = _date(row.get("valid_until"))
    if start is None or (end is not None and start >= end):
        return False
    if end is not None:
        return True
    return str(row.get("identity_event_type") or "").upper() in _OPEN_ENDED_TRANSITION_TYPES


def _competing_isin_resolution(
    scope_rows: list[dict[str, Any]], when: date,
) -> Resolution | None:
    """Resolve only a uniquely dated identity when a scope contains ISIN changes."""
    isins = {_norm(row.get("isin")) for row in scope_rows if _norm(row.get("isin"))}
    if len(isins) <= 1:
        return None

    candidate_pairs: set[tuple[str | None, str]] = set()
    admissible_pairs: set[tuple[str, str]] = set()
    unresolved_rows: list[dict[str, Any]] = []
    for row in scope_rows:
        isin = _norm(row.get("isin"))
        if not isin:
            continue
        if _date_field_is_invalid(row.get("valid_from")) or _date_field_is_invalid(row.get("valid_until")):
            unresolved_rows.append(row)
            continue
        if not _valid_on(row, when):
            continue
        if not _explicit_identity_segment(row):
            unresolved_rows.append(row)
            continue

        pair = (_durable_id(row.get("instrument_id")), isin)
        candidate_pairs.add(pair)
        if pair[0] is not None and _evidence_admissible(row):
            admissible_pairs.add((pair[0], pair[1]))

    if len(candidate_pairs) != 1 or len(admissible_pairs) != 1:
        return Resolution(
            None, None, "AMBIGUOUS_COMPETING_ISIN_HISTORY", "MANUAL_REVIEW",
            _candidate_ids(scope_rows),
            "competing ISIN history lacks one admissible dated identity segment",
        )

    chosen_id, chosen_isin = next(iter(admissible_pairs))
    if any(
        _norm(row.get("isin")) != chosen_isin
        or _durable_id(row.get("instrument_id")) not in {None, chosen_id}
        for row in unresolved_rows
    ):
        return Resolution(
            None, None, "AMBIGUOUS_COMPETING_ISIN_HISTORY", "MANUAL_REVIEW",
            _candidate_ids(scope_rows),
            "an open snapshot or unproven competing row may cover the event date",
        )

    return Resolution(
        chosen_id, chosen_isin, "DATED_COMPETING_ISIN_SEGMENT", "CERTIFIED",
        (chosen_id,),
    )


def _exact_isin_scope_rows(
    isin_rows: list[dict[str, Any]],
    rows_by_symbol: dict[str, list[dict[str, Any]]],
    rows_by_company: dict[str, list[dict[str, Any]]],
) -> tuple[list[list[dict[str, Any]]], bool]:
    """Derive coherent symbol/company scopes from an exact-ISIN history."""
    if not isin_rows or any(not (_norm(row.get("symbol")) or _norm_company(row.get("company_name"))) for row in isin_rows):
        return [], False

    durable_ids = {_durable_id(row.get("instrument_id")) for row in isin_rows}
    share_classes = {_is_dvr_row(row) for row in isin_rows}
    if None in durable_ids or len(durable_ids) != 1 or len(share_classes) != 1:
        return [], False

    scopes: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for row in isin_rows:
        if symbol := _norm(row.get("symbol")):
            scopes.setdefault(("symbol", symbol), rows_by_symbol.get(symbol, []))
        if row.get("company_name"):
            dvr = _is_dvr_row(row)
            company_rows = _company_scope_rows(row.get("company_name"), rows_by_company, dvr_only=dvr)
            company_key = _norm_company(re.sub(r"\s+DVR\s*$", "", str(row.get("company_name") or ""), flags=re.I))
            if company_key:
                scopes.setdefault(("company", company_key, dvr), company_rows)
    return list(scopes.values()), bool(scopes)


def resolve_observation(
    observation: Observation | dict[str, Any],
    instrument_master: Iterable[dict[str, Any]],
    *,
    aliases: Iterable[dict[str, Any]] = (),
    fuzzy_threshold: float = 0.92,
    _indexes: tuple[
        list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]],
        dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]
    ] | None = None,
) -> Resolution:
    """Resolve by period-valid evidence; fuzzy matches are never certified."""
    obs = observation.to_dict() if isinstance(observation, Observation) else observation
    if _indexes is None:
        rows, rows_by_isin, rows_by_symbol, rows_by_company, aliases_by_symbol = _build_indexes(instrument_master, aliases)
    else:
        rows, rows_by_isin, rows_by_symbol, rows_by_company, aliases_by_symbol = _indexes
    when = _date(obs.get("effective_date"))
    if when is None:
        return Resolution(None, None, "MISSING_EFFECTIVE_DATE", "MANUAL_REVIEW", (),
                          "period-valid identity requires an effective date")
    isin = _norm(obs.get("isin"))
    if isin:
        exact_history = rows_by_isin.get(isin, [])
        if exact_history:
            dated_identity_rows = [
                row for row in exact_history
                if _valid_on(row, when) and _evidence_admissible(row)
            ]
            observed_symbol = _norm(obs.get("symbol"))
            valid_symbols = {_norm(row.get("symbol")) for row in dated_identity_rows if row.get("symbol")}
            observed_company = _norm_company(obs.get("company_name"))
            valid_companies = {
                _norm_company(row.get("company_name"))
                for row in dated_identity_rows if row.get("company_name")
            }
            if (
                (observed_symbol and observed_symbol not in valid_symbols)
                or (observed_company and valid_companies and observed_company not in valid_companies)
            ):
                return Resolution(
                    None, None, "CONTRADICTORY_EXPLICIT_ISIN", "MANUAL_REVIEW",
                    _candidate_ids(exact_history),
                    "the supplied symbol or company contradicts the event-date ISIN identity",
                )
            scopes, coherent = _exact_isin_scope_rows(exact_history, rows_by_symbol, rows_by_company)
            if not coherent:
                return Resolution(
                    None, None, "UNSCOPED_EXPLICIT_ISIN", "MANUAL_REVIEW",
                    _candidate_ids(exact_history),
                    "exact ISIN history has no coherent symbol/company/share-class scope",
                )
            scoped_resolutions = [
                result for scope_rows in scopes
                if (result := _competing_isin_resolution(scope_rows, when)) is not None
            ]
            if any(result.confidence != "CERTIFIED" for result in scoped_resolutions):
                unresolved = next(result for result in scoped_resolutions if result.confidence != "CERTIFIED")
                return unresolved
            if scoped_resolutions:
                identities = {(result.instrument_id, result.isin) for result in scoped_resolutions}
                if len(identities) != 1:
                    return Resolution(
                        None, None, "AMBIGUOUS_EXPLICIT_ISIN_SCOPES", "MANUAL_REVIEW",
                        _candidate_ids(exact_history),
                        "derived scopes do not agree on one event-date identity",
                    )
                resolved_id, resolved_isin = next(iter(identities))
                if resolved_isin != isin:
                    return Resolution(
                        None, None, "CONTRADICTORY_EXPLICIT_ISIN", "MANUAL_REVIEW",
                        _candidate_ids(exact_history),
                        "the supplied ISIN is not the uniquely dated identity for its scope",
                    )
                return Resolution(
                    resolved_id, resolved_isin, "DATED_COMPETING_ISIN_SEGMENT", "CERTIFIED",
                    (resolved_id,) if resolved_id else (),
                )
        exact = [
            row for row in exact_history
            if _valid_on(row, when) and _evidence_admissible(row)
        ]
        exact = _unique_instrument_rows(exact)
        exact = [row for row in exact if _durable_id(row.get("instrument_id"))]
        if len(exact) == 1:
            return Resolution(
                _durable_id(exact[0]["instrument_id"]),
                _identity_value(exact[0].get("isin") or obs.get("isin")),
                "PERIOD_VALID_ISIN",
                "CERTIFIED",
            )
        if len(exact) > 1:
            return Resolution(
                None, None, "AMBIGUOUS_ISIN", "MANUAL_REVIEW",
                tuple(
                    candidate
                    for row in exact
                    if (candidate := _durable_id(row.get("instrument_id"))) is not None
                ),
            )
        return Resolution(None, None, "CONTRADICTORY_EXPLICIT_ISIN", "MANUAL_REVIEW", (),
                          "explicit ISIN did not match one admissible period-valid identity")

    symbol = _norm(obs.get("symbol"))
    symbol_history = rows_by_symbol.get(symbol, []) if symbol else []
    if symbol_history:
        competing = _competing_isin_resolution(symbol_history, when)
        if competing is not None:
            return competing
    exact = [
        row for row in symbol_history
        if _valid_on(row, when) and _evidence_admissible(row)
    ] if symbol else []
    unique_exact = _unique_instrument_rows(exact)
    if len(unique_exact) == 1:
        row = unique_exact[0]
        instrument_id = _durable_id(row.get("instrument_id"))
        if instrument_id is None:
            return Resolution(None, None, "UNRESOLVED", "UNRESOLVED", (), "identity row has no durable instrument id")
        return Resolution(
            instrument_id,
            _identity_value(row.get("isin") or obs.get("isin")),
            "HISTORICAL_SYMBOL_DATE",
            "CERTIFIED",
        )
    if len(unique_exact) > 1:
        snapshot = _snapshot_choice(exact, when)
        if snapshot is not None:
            return Resolution(
                _durable_id(snapshot.get("instrument_id")),
                _identity_value(snapshot.get("isin") or obs.get("isin")),
                "HISTORICAL_SNAPSHOT_SYMBOL_DATE",
                "CERTIFIED",
            )
        return Resolution(
            None, None, "AMBIGUOUS_SYMBOL_DATE", "MANUAL_REVIEW",
            tuple(
                candidate
                for row in exact
                if (candidate := _durable_id(row.get("instrument_id"))) is not None
            ),
        )

    raw_company = str(obs.get("company_name") or "")
    exact_company = _company_scope_rows(raw_company, rows_by_company)
    competing = _competing_isin_resolution(exact_company, when)
    if competing is not None:
        return competing
    exact_company = [
        row for row in exact_company
        if _valid_on(row, when) and _evidence_admissible(row)
    ]
    unique_company = _unique_instrument_rows(exact_company)
    if len(unique_company) == 1:
        row = unique_company[0]
        return Resolution(
            _durable_id(row.get("instrument_id")),
            _identity_value(row.get("isin") or obs.get("isin")),
            "PERIOD_VALID_COMPANY_NAME",
            "CERTIFIED",
        )
    if len(unique_company) > 1:
        snapshot = _snapshot_choice(exact_company, when)
        if snapshot is not None:
            return Resolution(
                _durable_id(snapshot.get("instrument_id")),
                _identity_value(snapshot.get("isin") or obs.get("isin")),
                "HISTORICAL_SNAPSHOT_COMPANY_DATE",
                "CERTIFIED",
            )
        return Resolution(
            None, None, "AMBIGUOUS_COMPANY_NAME_DATE", "MANUAL_REVIEW",
            _candidate_ids(exact_company),
        )

    alias_matches = []
    for alias in aliases_by_symbol.get(symbol, []) if symbol else []:
        if _valid_on(alias, when):
            alias_matches.append(alias)
    has_uncertified_alias = any(
        not _durable_id(row.get("instrument_id"))
        or str(row.get("confidence", "")).upper() != "CERTIFIED"
        or str(row.get("resolution_status", "ACCEPTED")).upper() != "ACCEPTED"
        for row in alias_matches
    )
    unique_aliases: dict[str, dict[str, Any]] = {}
    for row in alias_matches:
        if (instrument_id := _durable_id(row.get("instrument_id"))) is not None:
            unique_aliases.setdefault(instrument_id, row)
    if has_uncertified_alias and len(rows) > 1000:
        candidates = tuple(sorted({
            str(row["instrument_id"]) for row in alias_matches
            if _durable_id(row.get("instrument_id"))
        }))
        return Resolution(
            None, None, "UNCERTIFIED_ALIAS", "MANUAL_REVIEW", candidates,
            "alias identity requires review; a symbol alone is not durable identity evidence",
        )
    alias_history = list(rows_by_symbol.get(symbol, [])) + list(aliases_by_symbol.get(symbol, [])) if symbol else []
    alias_competition = _competing_isin_resolution(alias_history, when) if alias_history else None
    if alias_competition is not None:
        if alias_competition.confidence != "CERTIFIED":
            return alias_competition
        alias_identity = next(iter(unique_aliases.values()), None)
        if alias_identity is None or (
            _durable_id(alias_identity.get("instrument_id")) != alias_competition.instrument_id
            or _norm(alias_identity.get("isin")) != alias_competition.isin
        ):
            return Resolution(
                None, None, "AMBIGUOUS_COMPETING_ISIN_HISTORY", "MANUAL_REVIEW",
                _candidate_ids(alias_history),
                "dated competing identity does not match the certified symbol alias",
            )
        return alias_competition
    if not has_uncertified_alias and len(unique_aliases) == 1:
        row = next(iter(unique_aliases.values()))
        return Resolution(
            _durable_id(row.get("instrument_id")),
            _identity_value(row.get("isin")),
            "EXPLICIT_SYMBOL_ALIAS",
            "CERTIFIED",
        )
    if len(unique_aliases) > 1:
        return Resolution(
            None, None, "AMBIGUOUS_ALIAS", "MANUAL_REVIEW",
            tuple(sorted(unique_aliases)),
        )

    if symbol and len(rows) > 1000:
        symbol_candidates = [row for row in rows if _norm(row.get("symbol")) == symbol]
        candidate_ids = _candidate_ids(symbol_candidates)
        has_snapshot = any(r.get("snapshot_date") or r.get("observed_snapshot_date") for r in symbol_candidates)
        confidence = "MANUAL_REVIEW" if has_snapshot else "UNRESOLVED"
        reason = "historical symbol observed outside period validity" if has_snapshot else "no period-valid identity evidence"
        return Resolution(None, None, "UNRESOLVED", confidence, candidate_ids, reason)

    target = _norm(obs.get("company_name"))
    if len(rows) > 1000:
        return Resolution(
            None, None, "FUZZY_SEARCH_DEFERRED", "MANUAL_REVIEW", (),
            "large historical master requires a bounded manual identity search",
        )
    scored = sorted(((SequenceMatcher(None, target, _norm(row.get("company_name"))).ratio(), row) for row in rows if target),
                    key=lambda value: value[0], reverse=True)
    if scored and scored[0][0] >= fuzzy_threshold:
        top = [row for score, row in scored if score == scored[0][0]]
        return Resolution(
            None, None, "FUZZY_CANDIDATE", "MANUAL_REVIEW",
            tuple(
                candidate
                for row in top
                if (candidate := _durable_id(row.get("instrument_id"))) is not None
            ),
            "fuzzy identity cannot be auto-certified",
        )

    if symbol:
        symbol_candidates = [row for row in rows if _norm(row.get("symbol")) == symbol]
        if symbol_candidates:
            candidates = _candidate_ids(symbol_candidates)
            has_snapshot = any(r.get("snapshot_date") or r.get("observed_snapshot_date") for r in symbol_candidates)
            confidence = "MANUAL_REVIEW" if has_snapshot else "UNRESOLVED"
            reason = "historical symbol observed outside period validity" if has_snapshot else "no period-valid identity evidence"
            return Resolution(None, None, "UNRESOLVED", confidence, candidates, reason)

    return Resolution(None, None, "UNRESOLVED", "UNRESOLVED", (), "no period-valid identity evidence")


def resolve_observations(observations: Iterable[Observation], instrument_master: Iterable[dict[str, Any]], *, aliases: Iterable[dict[str, Any]] = ()) -> list[Observation]:
    rows = list(instrument_master)
    indexes = _build_indexes(rows, aliases)
    rows_by_instrument: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("instrument_id"):
            rows_by_instrument.setdefault(str(row["instrument_id"]), []).append(row)
    alias_rows = list(aliases)
    result = []
    for observation in observations:
        resolution = resolve_observation(observation, rows, aliases=alias_rows, _indexes=indexes)
        source_tier = str(observation.source_tier or "").upper()
        identity_certified = resolution.confidence == "CERTIFIED"
        event_evidence_certified = (
            identity_certified
            and str(observation.review_status) != "MANUAL_REVIEW"
            and source_tier in {"A1", "A2"}
            and observation.announcement_date is not None
            and observation.effective_date is not None
            and observation.known_at is not None
            and observation.action is not None
        )
        if event_evidence_certified:
            event_confidence = "CERTIFIED"
            event_review_status = "ACCEPTED"
        else:
            # Identity resolution must never upgrade a provisional challenger
            # event or a date-only workbook assertion into event authority.
            event_confidence = str(observation.confidence)
            event_review_status = str(observation.review_status)
        payload = observation.to_dict() | {
            "instrument_id": resolution.instrument_id,
            "isin": resolution.isin or _identity_value(observation.isin),
            "confidence": event_confidence,
            "review_status": event_review_status,
            "reason": observation.reason or resolution.reason,
            "observation_id": observation.observation_id or stable_observation_id(observation),
        }
        if not payload.get("symbol") and resolution.instrument_id:
            observation_date = _date(observation.effective_date)
            valid_rows = [
                row for row in rows_by_instrument.get(resolution.instrument_id, [])
                if row.get("symbol") and row.get("has_explicit_historical_interval")
                and _valid_on(row, observation_date) and _evidence_admissible(row)
            ]
            if not valid_rows:
                valid_rows = [
                    row for row in rows_by_instrument.get(resolution.instrument_id, [])
                    if row.get("symbol") and _valid_on(row, observation_date) and _evidence_admissible(row)
                ]
            symbols: dict[str, object] = {}
            for row in valid_rows:
                symbols.setdefault(_norm(row.get("symbol")), row.get("symbol"))
            if len(symbols) == 1:
                payload["symbol"] = next(iter(symbols.values()))
        payload["announcement_date"] = _date(payload.get("announcement_date"))
        payload["effective_date"] = _date(payload.get("effective_date"))
        payload["known_at"] = datetime.fromisoformat(str(payload["known_at"])) if payload.get("known_at") else None
        result.append(Observation(**payload))
    return result


def validate_alias_intervals(aliases: Iterable[dict[str, Any]]) -> list[str]:
    """Reject inverted or overlapping accepted identity aliases."""
    rows = [dict(row) for row in aliases]
    eligible = [
        row for row in rows
        if str(row.get("confidence", "")).upper() == "CERTIFIED"
        and str(row.get("resolution_status", "")).upper() == "ACCEPTED"
    ]
    errors: list[str] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in eligible:
        alias_id = row.get("alias_id", row.get("alias_symbol", "unknown"))
        if _durable_id(row.get("instrument_id")) is None:
            errors.append(f"invalid_alias_identity:{alias_id}")
            continue
        alias_symbol = _norm(row.get("alias_symbol") or row.get("symbol"))
        if not alias_symbol:
            errors.append(f"invalid_alias_symbol:{alias_id}")
            continue
        if _date_field_is_invalid(row.get("valid_from")) or _date_field_is_invalid(row.get("valid_until")):
            errors.append(f"invalid_alias_period:{alias_id}")
            continue
        start, end = _date(row.get("valid_from")), _date(row.get("valid_until"))
        if end is not None and start is None:
            errors.append(f"invalid_alias_period:{alias_id}")
            continue
        if start is not None and end is not None and start >= end:
            errors.append(f"invalid_alias_period:{alias_id}")
            continue
        exchange = _norm(row.get("exchange") or "NSE")
        key = (exchange, alias_symbol)
        grouped.setdefault(key, []).append(row)
    for key, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: _date(row.get("valid_from")) or date.min)
        for previous, current in zip(ordered, ordered[1:]):
            previous_end = _date(previous.get("valid_until")) or date.max
            current_start = _date(current.get("valid_from")) or date.min
            if current_start < previous_end:
                errors.append(f"alias_interval_overlap:{key[0]}:{key[1]}")
    return sorted(set(errors))
