"""Pure, deterministic controls for the FAB-27 candidate universe.

This module contains no network, broker, database, or trading-workflow code.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Iterable, Mapping
from urllib.parse import urlparse

START = date(2012, 1, 2)
END = date(2026, 8, 20)
ALLOWED_SECURITY_TYPES = frozenset({"EQUITY"})
EXCLUDED_SECURITY_TYPES = frozenset({"ETF", "REIT", "INVIT", "DEBT", "PREFERENCE", "WARRANT", "MUTUAL_FUND"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _as_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _as_finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_source_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def in_horizon(as_of: date) -> bool:
    return START <= as_of <= END


def eligible_security(row: Mapping[str, object]) -> bool:
    """Return eligibility only when all required identity/type flags are proven."""
    return (
        row.get("security_type") in ALLOWED_SECURITY_TYPES
        and bool(row.get("nse_listed"))
        and bool(row.get("isin_verified"))
        and not bool(row.get("suspended_or_delisted"))
    )


def eligible_liquidity(row: Mapping[str, object], *, min_turnover: float, min_trading_days: int) -> bool:
    """Apply PIT liquidity thresholds to observations available before rebalance."""
    turnover = _as_finite_number(row.get("median_daily_turnover"))
    trading_days = _as_finite_number(row.get("trading_days"))
    window_end = _as_date(row.get("turnover_window_end"))
    return (
        row.get("observation_complete") is True
        and window_end is not None
        and turnover is not None
        and trading_days is not None
        and trading_days.is_integer()
        and turnover >= min_turnover
        and trading_days >= min_trading_days
    )


def fail_closed_reasons(row: Mapping[str, object], *, min_turnover: float, min_trading_days: int) -> list[str]:
    reasons: list[str] = []
    as_of = _as_date(row.get("as_of"))
    if as_of is None:
        reasons.append("missing_as_of" if "as_of" not in row else "invalid_as_of")
    elif not in_horizon(as_of):
        reasons.append("outside_required_horizon")
    effective_from = _as_date(row.get("effective_from"))
    if effective_from is None:
        reasons.append("missing_effective_date" if row.get("effective_from") is None else "invalid_effective_date")
    if _as_finite_number(row.get("median_daily_turnover")) is None:
        reasons.append("invalid_median_daily_turnover")
    trading_days = _as_finite_number(row.get("trading_days"))
    if trading_days is None or not trading_days.is_integer() or trading_days < 0:
        reasons.append("invalid_trading_days")
    if row.get("turnover_window_end") is not None and _as_date(row.get("turnover_window_end")) is None:
        reasons.append("invalid_turnover_window_end")
    if not eligible_security(row):
        reasons.append("security_identity_or_type_not_proven")
    if not eligible_liquidity(row, min_turnover=min_turnover, min_trading_days=min_trading_days):
        reasons.append("liquidity_or_observation_incomplete")
    if not row.get("source_url"):
        reasons.append("missing_source_url")
    elif not _valid_source_url(row.get("source_url")):
        reasons.append("invalid_source_url")
    if not row.get("source_sha256"):
        reasons.append("missing_source_hash")
    elif not _valid_sha256(row.get("source_sha256")):
        reasons.append("invalid_source_hash")
    return reasons


def validate_rows(rows: Iterable[Mapping[str, object]], *, min_turnover: float, min_trading_days: int) -> dict[str, object]:
    rows = list(rows)
    rejected = [{"symbol": r.get("symbol"), "reasons": fail_closed_reasons(r, min_turnover=min_turnover, min_trading_days=min_trading_days)} for r in rows]
    accepted = [r for r, result in zip(rows, rejected) if not result["reasons"]]
    return {"input_rows": len(rows), "accepted_rows": len(accepted), "rejected_rows": len(rows) - len(accepted), "rejections": rejected}
