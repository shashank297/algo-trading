"""Historical instrument identity resolution with fail-closed fuzzy matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
import re
from typing import Any, Iterable

from tools.nifty200_pit.models import Observation


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


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
    dated_with_values = [(row, _date(row.get("snapshot_date"))) for row in dated]
    latest = max(snapshot_date for _, snapshot_date in dated_with_values if snapshot_date is not None)
    candidates = [row for row, snapshot_date in dated_with_values if snapshot_date == latest]
    instruments = {(str(row.get("instrument_id")), str(row.get("isin") or "")) for row in candidates}
    return candidates[0] if len(instruments) == 1 else None


def _unique_instrument_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A durable equity identity can retain multiple historical ISINs after a
    # split. Do not let root-ID deduplication select a future ISIN arbitrarily.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        instrument_id = str(row.get("instrument_id") or "")
        key = (instrument_id, str(row.get("isin") or ""))
        if instrument_id and key not in unique:
            unique[key] = row
    return list(unique.values())


def _build_indexes(
    rows: Iterable[dict[str, Any]], aliases: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
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


@dataclass(frozen=True, slots=True)
class Resolution:
    instrument_id: str | None
    isin: str | None
    method: str
    confidence: str
    candidates: tuple[str, ...] = ()
    reason: str | None = None


def _valid_on(row: dict[str, Any], when: date | None) -> bool:
    if when is None:
        return True
    start, end = _date(row.get("valid_from")), _date(row.get("valid_until"))
    snapshot = _date(row.get("snapshot_date"))
    if snapshot is not None and not row.get("has_explicit_historical_interval"):
        effective_start = snapshot if (start is None or start < snapshot) else start
    else:
        effective_start = start
    return (effective_start is None or when >= effective_start) and (end is None or when < end)


def resolve_observation(
    observation: Observation | dict[str, Any],
    instrument_master: Iterable[dict[str, Any]],
    *,
    aliases: Iterable[dict[str, Any]] = (),
    fuzzy_threshold: float = 0.92,
    _indexes: tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]] | None = None,
) -> Resolution:
    """Resolve by period-valid evidence; fuzzy matches are never certified."""
    obs = observation.to_dict() if isinstance(observation, Observation) else observation
    # IL is the separate inter-institutional market, not the normal equity
    # security represented by an index constituent. Preserve it in the master
    # for provenance but exclude it from normal constituent identity matching.
    if _indexes is None:
        rows, rows_by_isin, rows_by_symbol, rows_by_company, aliases_by_symbol = _build_indexes(instrument_master, aliases)
    else:
        rows, rows_by_isin, rows_by_symbol, rows_by_company, aliases_by_symbol = _indexes
    when = _date(obs.get("effective_date"))
    isin = _norm(obs.get("isin"))
    if isin:
        exact = [row for row in rows_by_isin.get(isin, []) if _valid_on(row, when)]
        if len(exact) == 1:
            return Resolution(str(exact[0]["instrument_id"]), str(exact[0].get("isin") or obs.get("isin")), "PERIOD_VALID_ISIN", "CERTIFIED")
        if len(exact) > 1:
            return Resolution(None, None, "AMBIGUOUS_ISIN", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in exact))

    symbol = _norm(obs.get("symbol"))
    exact = [row for row in rows_by_symbol.get(symbol, []) if _valid_on(row, when)] if symbol else []
    unique_exact = _unique_instrument_rows(exact)
    if len(unique_exact) == 1:
        row = unique_exact[0]
        return Resolution(str(row["instrument_id"]), str(row.get("isin") or obs.get("isin") or "") or None,
                          "HISTORICAL_SYMBOL_DATE", "CERTIFIED")
    if len(unique_exact) > 1:
        snapshot = _snapshot_choice(exact, when)
        if snapshot is not None:
            return Resolution(str(snapshot["instrument_id"]), str(snapshot.get("isin") or obs.get("isin") or "") or None,
                              "HISTORICAL_SNAPSHOT_SYMBOL_DATE", "CERTIFIED")
        return Resolution(None, None, "AMBIGUOUS_SYMBOL_DATE", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in exact))

    raw_company = str(obs.get("company_name") or "")
    company_for_match = re.sub(r"\s+DVR\s*$", "", raw_company, flags=re.I)
    company = _norm_company(company_for_match)
    exact_company = [
        row for row in rows_by_company.get(company, []) if _valid_on(row, when)
    ]
    if re.search(r"\bDVR\b", raw_company, re.I):
        exact_company = [row for row in exact_company if _norm(row.get("symbol")).endswith("DVR")]
    unique_company = _unique_instrument_rows(exact_company)
    if len(unique_company) == 1:
        row = unique_company[0]
        return Resolution(str(row["instrument_id"]), str(row.get("isin") or obs.get("isin") or "") or None,
                          "EXACT_COMPANY_NAME_DATE", "CERTIFIED")
    if len(unique_company) > 1:
        snapshot = _snapshot_choice(exact_company, when)
        if snapshot is not None:
            return Resolution(str(snapshot["instrument_id"]), str(snapshot.get("isin") or obs.get("isin") or "") or None,
                              "HISTORICAL_SNAPSHOT_COMPANY_DATE", "CERTIFIED")
        return Resolution(None, None, "AMBIGUOUS_COMPANY_NAME_DATE", "MANUAL_REVIEW",
                          tuple(str(r.get("instrument_id")) for r in exact_company))

    alias_matches = []
    for alias in aliases_by_symbol.get(symbol, []) if symbol else []:
        if _valid_on(alias, when):
            alias_matches.append(alias)
    if any(
        not str(row.get("instrument_id") or "").strip()
        or str(row.get("instrument_id")).casefold() == "none"
        or row.get("confidence") != "CERTIFIED"
        or row.get("resolution_status", "ACCEPTED") != "ACCEPTED"
        for row in alias_matches
    ):
        candidates = tuple(sorted({
            str(row["instrument_id"]) for row in alias_matches
            if row.get("instrument_id") and str(row["instrument_id"]).casefold() != "none"
        }))
        return Resolution(None, None, "UNCERTIFIED_ALIAS", "MANUAL_REVIEW", candidates,
                          "alias identity requires review; a symbol alone is not durable identity evidence")
    if len(alias_matches) == 1:
        row = alias_matches[0]
        return Resolution(str(row["instrument_id"]), row.get("isin"), "EXPLICIT_SYMBOL_ALIAS", "CERTIFIED")
    if len(alias_matches) > 1:
        return Resolution(None, None, "AMBIGUOUS_ALIAS", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in alias_matches))

    # A supplied symbol that failed exact/alias resolution is not a reason to
    # compare the company name against every historical security. Fuzzy output
    # is manual-review only and is not needed to certify a durable identity.
    if symbol:
        symbol_candidates = [row for row in rows if _norm(row.get("symbol")) == symbol]
        if symbol_candidates:
            candidates = tuple(dict.fromkeys(str(r.get("instrument_id")) for r in symbol_candidates if r.get("instrument_id")))
            has_snapshot = any(r.get("snapshot_date") for r in symbol_candidates)
            confidence = "MANUAL_REVIEW" if has_snapshot else "UNRESOLVED"
            reason = "historical symbol observed outside period validity" if has_snapshot else "no period-valid identity evidence"
            return Resolution(None, None, "UNRESOLVED", confidence, candidates, reason)
        return Resolution(None, None, "UNRESOLVED", "UNRESOLVED", (), "no period-valid identity evidence")

    target = _norm(obs.get("company_name"))
    if len(rows) > 1000:
        return Resolution(None, None, "FUZZY_SEARCH_DEFERRED", "MANUAL_REVIEW", (),
                          "large historical master requires a bounded manual identity search")
    scored = sorted(((SequenceMatcher(None, target, _norm(row.get("company_name"))).ratio(), row) for row in rows if target),
                    key=lambda value: value[0], reverse=True)
    if scored and scored[0][0] >= fuzzy_threshold:
        top = [row for score, row in scored if score == scored[0][0]]
        return Resolution(None, None, "FUZZY_CANDIDATE", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in top),
                          "fuzzy identity cannot be auto-certified")
    return Resolution(None, None, "UNRESOLVED", "UNRESOLVED", (), "no period-valid identity evidence")


def resolve_observations(observations: Iterable[Observation], instrument_master: Iterable[dict[str, Any]], *, aliases: Iterable[dict[str, Any]] = ()) -> list[Observation]:
    rows = list(instrument_master)
    indexes = _build_indexes(rows, aliases)
    rows_by_instrument = {str(row.get("instrument_id")): row for row in rows if row.get("instrument_id")}
    alias_rows = list(aliases)
    result = []
    for observation in observations:
        resolution = resolve_observation(observation, rows, aliases=alias_rows, _indexes=indexes)
        payload = observation.to_dict() | {
            "instrument_id": resolution.instrument_id,
            "isin": resolution.isin or observation.isin,
            "confidence": resolution.confidence,
            "review_status": "ACCEPTED" if resolution.confidence == "CERTIFIED" else resolution.confidence,
            "reason": observation.reason or resolution.reason,
        }
        # A security master establishes identity, not the truth of a third-party
        # membership assertion. Keep challenger events provisional after mapping.
        if str(observation.source_tier) not in {"A1", "A2"}:
            payload["confidence"] = "PROVISIONAL"
            payload["review_status"] = "UNRESOLVED"
        if not payload.get("symbol") and resolution.instrument_id:
            resolved_row = rows_by_instrument.get(resolution.instrument_id)
            if resolved_row and resolved_row.get("symbol"):
                payload["symbol"] = resolved_row["symbol"]
        payload["announcement_date"] = _date(payload.get("announcement_date"))
        payload["effective_date"] = _date(payload.get("effective_date"))
        payload["known_at"] = datetime.fromisoformat(str(payload["known_at"])) if payload.get("known_at") else None
        result.append(Observation(**payload))
    return result
