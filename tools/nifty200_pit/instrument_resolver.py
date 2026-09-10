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
    return (start is None or when >= start) and (end is None or when < end)


def resolve_observation(
    observation: Observation | dict[str, Any],
    instrument_master: Iterable[dict[str, Any]],
    *,
    aliases: Iterable[dict[str, Any]] = (),
    fuzzy_threshold: float = 0.92,
) -> Resolution:
    """Resolve by period-valid evidence; fuzzy matches are never certified."""
    obs = observation.to_dict() if isinstance(observation, Observation) else observation
    rows = [dict(row) for row in instrument_master]
    when = _date(obs.get("effective_date"))
    isin = _norm(obs.get("isin"))
    if isin:
        exact = [row for row in rows if _norm(row.get("isin")) == isin and _valid_on(row, when)]
        if len(exact) == 1:
            return Resolution(str(exact[0]["instrument_id"]), str(exact[0].get("isin") or obs.get("isin")), "PERIOD_VALID_ISIN", "CERTIFIED")
        if len(exact) > 1:
            return Resolution(None, None, "AMBIGUOUS_ISIN", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in exact))

    symbol = _norm(obs.get("symbol"))
    exact = [row for row in rows if _norm(row.get("symbol")) == symbol and _valid_on(row, when)] if symbol else []
    if len(exact) == 1:
        row = exact[0]
        return Resolution(str(row["instrument_id"]), str(row.get("isin") or obs.get("isin") or "") or None,
                          "HISTORICAL_SYMBOL_DATE", "CERTIFIED")
    if len(exact) > 1:
        return Resolution(None, None, "AMBIGUOUS_SYMBOL_DATE", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in exact))

    alias_matches = []
    for alias in aliases:
        if _norm(alias.get("alias_symbol")) == symbol or _norm(alias.get("symbol")) == symbol:
            if _valid_on(alias, when):
                alias_matches.append(alias)
    if len(alias_matches) == 1:
        row = alias_matches[0]
        return Resolution(str(row["instrument_id"]), row.get("isin"), "EXPLICIT_SYMBOL_ALIAS", "CERTIFIED")
    if len(alias_matches) > 1:
        return Resolution(None, None, "AMBIGUOUS_ALIAS", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in alias_matches))

    target = _norm(obs.get("company_name"))
    scored = sorted(((SequenceMatcher(None, target, _norm(row.get("company_name"))).ratio(), row) for row in rows if target),
                    key=lambda value: value[0], reverse=True)
    if scored and scored[0][0] >= fuzzy_threshold:
        top = [row for score, row in scored if score == scored[0][0]]
        return Resolution(None, None, "FUZZY_CANDIDATE", "MANUAL_REVIEW", tuple(str(r.get("instrument_id")) for r in top),
                          "fuzzy identity cannot be auto-certified")
    return Resolution(None, None, "UNRESOLVED", "UNRESOLVED", (), "no period-valid identity evidence")


def resolve_observations(observations: Iterable[Observation], instrument_master: Iterable[dict[str, Any]], *, aliases: Iterable[dict[str, Any]] = ()) -> list[Observation]:
    rows = list(instrument_master)
    alias_rows = list(aliases)
    result = []
    for observation in observations:
        resolution = resolve_observation(observation, rows, aliases=alias_rows)
        payload = observation.to_dict() | {
            "instrument_id": resolution.instrument_id,
            "isin": resolution.isin or observation.isin,
            "confidence": resolution.confidence,
            "review_status": "ACCEPTED" if resolution.confidence == "CERTIFIED" else resolution.confidence,
            "reason": observation.reason or resolution.reason,
        }
        payload["announcement_date"] = _date(payload.get("announcement_date"))
        payload["effective_date"] = _date(payload.get("effective_date"))
        payload["known_at"] = datetime.fromisoformat(str(payload["known_at"])) if payload.get("known_at") else None
        result.append(Observation(**payload))
    return result
