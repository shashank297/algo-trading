"""Cross-provider observational verification — no data blending.

Phase 2.2 — Certified Multi-Timeframe Data Platform.

This module compares a secondary (observational) provider's bars against the
canonical primary provider's bars for the same symbol, timeframe, and date range.

Design invariant: The primary canonical data is NEVER modified. Any disagreement
between providers is surfaced as a DATA_VERIFICATION_WARNING or causes the
research admission gate to fail, depending on configured severity. Provider data
is NEVER blended (averaged, interpolated, or combined).

Per-bar outcomes:
  MATCH            — primary and secondary agree within exact equality
  TOLERANCE_MATCH  — primary and secondary agree within configured tolerance
  DISAGREEMENT     — primary and secondary differ beyond tolerance
  UNAVAILABLE      — secondary bar is missing for this timestamp

Persistence: results are written to ``cross_provider_reconciliations`` via
``DuckDBManager.persist_reconciliation()``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

import pandas as pd
from loguru import logger

if TYPE_CHECKING:
    from storage.duckdb_manager import DuckDBManager


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ProviderReconciliationResult(str, Enum):
    """Per-bar outcome of a cross-provider price comparison."""

    MATCH = "MATCH"
    TOLERANCE_MATCH = "TOLERANCE_MATCH"
    DISAGREEMENT = "DISAGREEMENT"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationSeverity(str, Enum):
    """Governs what happens when a DISAGREEMENT is detected."""

    WARNING = "WARNING"    # Log a warning; research admission continues.
    BLOCKING = "BLOCKING"  # Raise an exception; research admission is blocked.


COMPARISON_VERSION = "cross-provider-v1"

# Default price tolerance: relative difference ≤ 0.01% (0.0001)
DEFAULT_PRICE_TOLERANCE = 0.0001
# Default volume tolerance: exact match (0)
DEFAULT_VOLUME_TOLERANCE = 0.0


@dataclass(frozen=True)
class BarComparisonOutcome:
    """Per-bar comparison result between primary and secondary provider."""

    timestamp: datetime
    result: ProviderReconciliationResult
    primary_ohlcv: dict[str, float]
    secondary_ohlcv: dict[str, float] | None  # None when secondary bar is UNAVAILABLE
    field_deltas: dict[str, float]  # relative differences per field (empty on UNAVAILABLE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "result": self.result.value,
            "primary_ohlcv": self.primary_ohlcv,
            "secondary_ohlcv": self.secondary_ohlcv,
            "field_deltas": self.field_deltas,
        }


@dataclass(frozen=True)
class ProviderVerificationReport:
    """Aggregated cross-provider verification report for one reconciliation run."""

    reconciliation_id: str
    symbol: str
    exchange: str
    timeframe: str
    primary_provider: str
    secondary_provider: str
    primary_dataset_id: str
    secondary_dataset_id: str | None
    total_bars_primary: int
    total_bars_secondary: int | None
    bars_match: int
    bars_tolerance_match: int
    bars_disagreement: int
    bars_unavailable: int
    overall_status: str  # MATCH | PARTIAL_MATCH | DISAGREEMENT | UNAVAILABLE
    bar_outcomes: list[BarComparisonOutcome]
    tolerance_config: dict[str, float] = field(default_factory=dict)

    def to_storage_row(self, comparison_date: "datetime | None" = None) -> dict[str, Any]:
        """Return a dict suitable for insertion into ``cross_provider_reconciliations``."""
        date_val = (comparison_date or datetime.now(timezone.utc)).date() if comparison_date else datetime.now(timezone.utc).date()
        return {
            "reconciliation_id": self.reconciliation_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "primary_provider": self.primary_provider,
            "secondary_provider": self.secondary_provider,
            "comparison_version": COMPARISON_VERSION,
            "comparison_date": date_val,
            "primary_dataset_id": self.primary_dataset_id,
            "secondary_dataset_id": self.secondary_dataset_id,
            "total_bars_primary": self.total_bars_primary,
            "total_bars_secondary": self.total_bars_secondary,
            "bars_match": self.bars_match,
            "bars_tolerance_match": self.bars_tolerance_match,
            "bars_disagreement": self.bars_disagreement,
            "bars_unavailable": self.bars_unavailable,
            "tolerance_config_json": json.dumps(self.tolerance_config, sort_keys=True),
            "bar_outcomes_json": json.dumps(
                [o.to_dict() for o in self.bar_outcomes],
                sort_keys=True,
                default=str,
            ),
            "overall_status": self.overall_status,
            "created_at": datetime.now(timezone.utc),
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderDataVerificationWarning(UserWarning):
    """Emitted when provider disagreements are detected (severity=WARNING)."""


class ProviderDataVerificationError(RuntimeError):
    """Raised when provider disagreements are detected and severity=BLOCKING."""


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class CrossProviderVerifier:
    """Compare a secondary (observational) provider against a canonical primary.

    This verifier is purely observational: it reads primary bars, reads secondary
    bars, compares them bar-by-bar, and records the outcome. The primary data is
    NEVER modified — no averaging, no substitution, no blending.

    Usage::

        verifier = CrossProviderVerifier()
        report = verifier.verify(
            primary_bars=primary_df,
            secondary_bars=secondary_df,
            symbol="RELIANCE",
            exchange="NSE",
            timeframe="5m",
            primary_provider="angel_one",
            secondary_provider="nse_feed",
            severity=VerificationSeverity.WARNING,
            tolerance=None,  # use defaults
            db=db,
            primary_dataset_id="ds_abc",
        )
    """

    COMPARISON_VERSION: str = COMPARISON_VERSION

    def verify(
        self,
        *,
        primary_bars: pd.DataFrame,
        secondary_bars: pd.DataFrame | None,
        symbol: str,
        exchange: str,
        timeframe: str,
        primary_provider: str,
        secondary_provider: str,
        severity: VerificationSeverity = VerificationSeverity.WARNING,
        tolerance: dict[str, float] | None = None,
        db: "DuckDBManager",
        primary_dataset_id: str | None = None,
        secondary_dataset_id: str | None = None,
    ) -> ProviderVerificationReport:
        """Run cross-provider comparison and persist results.

        Args:
            primary_bars: Canonical primary provider DataFrame (never modified).
            secondary_bars: Observational secondary provider DataFrame, or None
                            if the secondary is entirely unavailable.
            symbol: Instrument symbol.
            exchange: Exchange segment.
            timeframe: Timeframe label (e.g. '5m').
            primary_provider: Name of the primary (canonical) data provider.
            secondary_provider: Name of the secondary (observational) provider.
            severity: What to do on DISAGREEMENT — WARNING or BLOCKING.
            tolerance: Per-field relative tolerance overrides.
                       Defaults: price fields 0.0001, volume 0.0.
            db: DuckDB connection for persisting results.
            primary_dataset_id: dataset_id of the primary dataset.
            secondary_dataset_id: dataset_id of the secondary dataset (if available).

        Returns:
            :class:`ProviderVerificationReport` with all per-bar outcomes.

        Raises:
            ProviderDataVerificationError: If ``severity=BLOCKING`` and any bar
                                           produces a DISAGREEMENT result.
        """
        if not primary_dataset_id or not secondary_dataset_id:
            raise ValueError("Provider verification requires explicit primary and secondary dataset IDs.")
        active_tolerance = _build_tolerance(tolerance)
        reconciliation_id = str(uuid.uuid4())

        # Make a defensive copy — primary bars MUST NOT be modified
        primary_df = primary_bars.copy()
        primary_df["timestamp"] = pd.to_datetime(primary_df["timestamp"], utc=True)
        primary_df = primary_df.sort_values("timestamp").reset_index(drop=True)

        secondary_df: pd.DataFrame | None = None
        if secondary_bars is not None and not secondary_bars.empty:
            secondary_df = secondary_bars.copy()
            secondary_df["timestamp"] = pd.to_datetime(secondary_df["timestamp"], utc=True)
            secondary_df = secondary_df.sort_values("timestamp").reset_index(drop=True)

        # Verify the primary hasn't been accidentally mutated
        assert primary_bars.shape == primary_df.shape, (
            "PRIMARY DATA INTEGRITY VIOLATION: primary_bars was mutated."
        )

        bar_outcomes: list[BarComparisonOutcome] = []
        bars_match = 0
        bars_tolerance_match = 0
        bars_disagreement = 0
        bars_unavailable = 0

        secondary_idx: dict[pd.Timestamp, pd.Series] = {}
        if secondary_df is not None:
            for _, row in secondary_df.iterrows():
                secondary_idx[row["timestamp"]] = row

        for _, primary_row in primary_df.iterrows():
            ts = primary_row["timestamp"]
            primary_ohlcv = _extract_ohlcv(primary_row)

            if ts not in secondary_idx:
                bar_outcomes.append(
                    BarComparisonOutcome(
                        timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                        result=ProviderReconciliationResult.UNAVAILABLE,
                        primary_ohlcv=primary_ohlcv,
                        secondary_ohlcv=None,
                        field_deltas={},
                    )
                )
                bars_unavailable += 1
                continue

            secondary_row = secondary_idx[ts]
            secondary_ohlcv = _extract_ohlcv(secondary_row)

            field_deltas, outcome = _compare_ohlcv(
                primary_ohlcv, secondary_ohlcv, active_tolerance
            )

            bar_outcomes.append(
                BarComparisonOutcome(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    result=outcome,
                    primary_ohlcv=primary_ohlcv,
                    secondary_ohlcv=secondary_ohlcv,
                    field_deltas=field_deltas,
                )
            )

            if outcome == ProviderReconciliationResult.MATCH:
                bars_match += 1
            elif outcome == ProviderReconciliationResult.TOLERANCE_MATCH:
                bars_tolerance_match += 1
            elif outcome == ProviderReconciliationResult.DISAGREEMENT:
                bars_disagreement += 1
                _handle_disagreement(
                    symbol=symbol,
                    exchange=exchange,
                    timeframe=timeframe,
                    timestamp=ts,
                    primary_ohlcv=primary_ohlcv,
                    secondary_ohlcv=secondary_ohlcv,
                    field_deltas=field_deltas,
                    severity=severity,
                    defer_blocking=True,
                )

        overall_status = _compute_overall_status(
            bars_match, bars_tolerance_match, bars_disagreement, bars_unavailable
        )

        report = ProviderVerificationReport(
            reconciliation_id=reconciliation_id,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            primary_provider=primary_provider,
            secondary_provider=secondary_provider,
            primary_dataset_id=primary_dataset_id,
            secondary_dataset_id=secondary_dataset_id,
            total_bars_primary=len(primary_df),
            total_bars_secondary=len(secondary_df) if secondary_df is not None else None,
            bars_match=bars_match,
            bars_tolerance_match=bars_tolerance_match,
            bars_disagreement=bars_disagreement,
            bars_unavailable=bars_unavailable,
            overall_status=overall_status,
            bar_outcomes=bar_outcomes,
            tolerance_config=active_tolerance,
        )

        # Persist to storage — primary data untouched
        comparison_date = primary_df["timestamp"].iloc[0] if len(primary_df) > 0 else None
        db.persist_reconciliation(report, comparison_date=comparison_date)

        if severity == VerificationSeverity.BLOCKING and bars_disagreement:
            raise ProviderDataVerificationError(
                f"DATA_VERIFICATION_WARNING: provider disagreement persisted in blocking reconciliation {reconciliation_id} "
                f"with {bars_disagreement} disagreement(s)."
            )

        logger.info(
            "Provider verification {} {} {}: match={} tol_match={} disagree={} unavail={} → {}",
            symbol,
            exchange,
            timeframe,
            bars_match,
            bars_tolerance_match,
            bars_disagreement,
            bars_unavailable,
            overall_status,
        )

        # Verify primary data integrity after the operation
        assert primary_bars.shape == primary_df.shape, (
            "POST-VERIFICATION INTEGRITY VIOLATION: primary_bars was modified during verification."
        )

        return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_tolerance(override: dict[str, float] | None) -> dict[str, float]:
    """Build the active tolerance configuration."""
    base = {
        "open": DEFAULT_PRICE_TOLERANCE,
        "high": DEFAULT_PRICE_TOLERANCE,
        "low": DEFAULT_PRICE_TOLERANCE,
        "close": DEFAULT_PRICE_TOLERANCE,
        "volume": DEFAULT_VOLUME_TOLERANCE,
    }
    if override:
        base.update({k: float(v) for k, v in override.items()})
    return base


def _extract_ohlcv(row: pd.Series) -> dict[str, float]:
    return {
        "open": float(row.get("open", float("nan"))),
        "high": float(row.get("high", float("nan"))),
        "low": float(row.get("low", float("nan"))),
        "close": float(row.get("close", float("nan"))),
        "volume": float(row.get("volume", 0.0)),
    }


def _compare_ohlcv(
    primary: dict[str, float],
    secondary: dict[str, float],
    tolerance: dict[str, float],
) -> tuple[dict[str, float], ProviderReconciliationResult]:
    """Compare two OHLCV dicts; return (field_deltas, outcome)."""
    deltas: dict[str, float] = {}
    any_beyond_tolerance = False
    any_within_tolerance_but_not_exact = False

    for col in ("open", "high", "low", "close", "volume"):
        p_val = primary.get(col, 0.0)
        s_val = secondary.get(col, 0.0)

        if p_val == 0.0 and s_val == 0.0:
            rel_delta = 0.0
        elif p_val == 0.0:
            rel_delta = abs(s_val)
        else:
            rel_delta = abs(p_val - s_val) / abs(p_val)

        deltas[col] = rel_delta
        tol = tolerance.get(col, 0.0)

        if rel_delta > tol:
            any_beyond_tolerance = True
        elif rel_delta > 0.0:
            any_within_tolerance_but_not_exact = True

    if any_beyond_tolerance:
        return deltas, ProviderReconciliationResult.DISAGREEMENT
    if any_within_tolerance_but_not_exact:
        return deltas, ProviderReconciliationResult.TOLERANCE_MATCH
    return deltas, ProviderReconciliationResult.MATCH


def _handle_disagreement(
    *,
    symbol: str,
    exchange: str,
    timeframe: str,
    timestamp: "pd.Timestamp",
    primary_ohlcv: dict[str, float],
    secondary_ohlcv: dict[str, float],
    field_deltas: dict[str, float],
    severity: VerificationSeverity,
    defer_blocking: bool = False,
) -> None:
    """Log or raise on a DISAGREEMENT — never blend the values."""
    msg = (
        f"DATA_VERIFICATION_WARNING: provider disagreement for "
        f"{symbol}/{exchange} {timeframe} @ {timestamp}: "
        f"primary={primary_ohlcv}, secondary={secondary_ohlcv}, "
        f"relative_deltas={field_deltas}. "
        f"Primary data is NOT modified."
    )
    if severity == VerificationSeverity.BLOCKING and not defer_blocking:
        raise ProviderDataVerificationError(msg)
    else:
        import warnings  # noqa: PLC0415
        if severity == VerificationSeverity.WARNING:
            warnings.warn(msg, ProviderDataVerificationWarning, stacklevel=6)
        logger.warning(msg)


def _compute_overall_status(
    bars_match: int,
    bars_tolerance_match: int,
    bars_disagreement: int,
    bars_unavailable: int,
) -> str:
    total = bars_match + bars_tolerance_match + bars_disagreement + bars_unavailable
    if total == 0:
        return "UNAVAILABLE"
    if bars_disagreement > 0:
        return "DISAGREEMENT"
    if bars_unavailable == total:
        return "UNAVAILABLE"
    if bars_unavailable > 0 or bars_tolerance_match > 0:
        return "PARTIAL_MATCH"
    return "MATCH"
