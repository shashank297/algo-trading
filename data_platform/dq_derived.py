"""Data quality certification for derived (resampled) OHLCV bar datasets.

Phase 2.2 — Certified Multi-Timeframe Data Platform.

Implements fail-closed DQ certification for derived bars before they are
admitted into the research pipeline. Certification must pass all checks
before a derived dataset receives CANONICAL_PROMOTED (CERTIFIED) status.

Checks performed:
1. Schema: all required columns present with correct dtype coercibility.
2. OHLC integrity: high >= max(open, close), low <= min(open, close), high >= low.
3. No duplicate timestamps within the same symbol+timeframe.
4. Session alignment: every bar's UTC timestamp falls within the declared
   market session for its trading date.
5. Missing expected buckets: compare actual bar count to expected bucket count
   from session duration / target timeframe minutes.
6. Timestamp monotonicity: timestamps are strictly ascending.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd
from loguru import logger

if TYPE_CHECKING:
    from trading_stack.calendars import MarketCalendar


_TIMEFRAME_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
}


@dataclass
class DerivedDQReport:
    """DQ certification report for one derived dataset.

    All boolean fields default to False (fail-closed): a derived dataset is
    only certified when ``certified=True`` and all sub-checks are True.
    """

    derived_dataset_id: str
    certified: bool
    schema_ok: bool = False
    ohlc_integrity_ok: bool = False
    no_duplicates: bool = False
    session_aligned: bool = False
    timestamp_monotonic: bool = False
    missing_buckets: list[str] = field(default_factory=list)  # descriptions of missing sessions
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dictionary for storage."""
        return {
            "derived_dataset_id": self.derived_dataset_id,
            "certified": self.certified,
            "schema_ok": self.schema_ok,
            "ohlc_integrity_ok": self.ohlc_integrity_ok,
            "no_duplicates": self.no_duplicates,
            "session_aligned": self.session_aligned,
            "timestamp_monotonic": self.timestamp_monotonic,
            "missing_buckets": self.missing_buckets,
            "issues": self.issues,
        }


class DerivedBarDQCertifier:
    """Certifies derived OHLCV bars before admission into the research pipeline.

    Fails closed: any single check failure marks ``certified=False`` and
    prevents the derived dataset from being stored as CERTIFIED.

    Usage::

        certifier = DerivedBarDQCertifier(calendar=calendar, target_timeframe="15m")
        report = certifier.certify(derived_df, symbol="RELIANCE", exchange="NSE")
        if not report.certified:
            raise RuntimeError(report.issues)
    """

    _REQUIRED_COLUMNS: frozenset[str] = frozenset(
        {"timestamp", "open", "high", "low", "close", "volume"}
    )

    def __init__(
        self,
        *,
        calendar: "MarketCalendar",
        target_timeframe: str,
    ) -> None:
        self._calendar = calendar
        self._target_timeframe = target_timeframe
        self._target_minutes = _TIMEFRAME_MINUTES.get(target_timeframe)

    def certify(
        self,
        derived_df: pd.DataFrame,
        *,
        symbol: str,
        exchange: str,
        derived_dataset_id: str | None = None,
    ) -> DerivedDQReport:
        """Run all DQ checks on ``derived_df`` and return a :class:`DerivedDQReport`.

        Args:
            derived_df: DataFrame of derived OHLCV bars (UTC timestamps).
            symbol: Instrument symbol (for logging and report context).
            exchange: Exchange segment.
            derived_dataset_id: Optional ID to embed in the report.

        Returns:
            :class:`DerivedDQReport` with ``certified=True`` iff all checks pass.
        """
        report_id = derived_dataset_id or "PENDING"
        report = DerivedDQReport(derived_dataset_id=report_id, certified=False)

        if derived_df is None or derived_df.empty:
            report.issues.append("Derived bar DataFrame is empty — cannot certify.")
            return report

        # ----------------------------------------------------------------
        # Check 1: Schema
        # ----------------------------------------------------------------
        missing_cols = self._REQUIRED_COLUMNS.difference(derived_df.columns)
        if missing_cols:
            report.issues.append(
                f"Schema check FAILED: missing columns {sorted(missing_cols)}."
            )
        else:
            report.schema_ok = True

        if not report.schema_ok:
            # Cannot run subsequent checks without schema
            return report

        # Work on a copy with normalised timestamps
        df = derived_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

        invalid_values = df[["timestamp", "open", "high", "low", "close", "volume"]].isna().any(axis=1)
        non_finite = ~df[["open", "high", "low", "close", "volume"]].apply(
            lambda column: column.map(lambda value: pd.notna(value) and float(value) == float(value) and abs(float(value)) != float("inf"))
        ).all(axis=1)
        negative_volume = df["volume"].notna() & (df["volume"] < 0)
        non_positive_prices = df[["open", "high", "low", "close"]].notna().all(axis=1) & (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        if invalid_values.any() or non_finite.any() or negative_volume.any() or non_positive_prices.any():
            report.issues.append(
                "Schema check FAILED: timestamps and OHLCV values must be finite; prices must be positive and volume non-negative."
            )
            report.schema_ok = False
            return report

        # ----------------------------------------------------------------
        # Check 2: OHLC integrity
        # ----------------------------------------------------------------
        ohlc_failures: list[str] = []
        high_lt_open_close = df["high"] < df[["open", "close"]].max(axis=1)
        low_gt_open_close = df["low"] > df[["open", "close"]].min(axis=1)
        high_lt_low = df["high"] < df["low"]

        if high_lt_open_close.any():
            ohlc_failures.append(
                f"{high_lt_open_close.sum()} bar(s) where high < max(open, close)."
            )
        if low_gt_open_close.any():
            ohlc_failures.append(
                f"{low_gt_open_close.sum()} bar(s) where low > min(open, close)."
            )
        if high_lt_low.any():
            ohlc_failures.append(
                f"{high_lt_low.sum()} bar(s) where high < low."
            )

        if ohlc_failures:
            report.issues.extend(ohlc_failures)
        else:
            report.ohlc_integrity_ok = True

        # ----------------------------------------------------------------
        # Check 3: No duplicate timestamps
        # ----------------------------------------------------------------
        n_dups = int(df["timestamp"].duplicated().sum())
        if n_dups > 0:
            report.issues.append(
                f"Duplicate timestamp check FAILED: {n_dups} duplicate timestamp(s)."
            )
        else:
            report.no_duplicates = True

        # ----------------------------------------------------------------
        # Check 4: Session alignment
        # ----------------------------------------------------------------
        import zoneinfo  # noqa: PLC0415

        tz = zoneinfo.ZoneInfo(self._calendar.spec.timezone)
        ts_local = df["timestamp"].dt.tz_convert(tz)
        out_of_session_count = 0

        for trading_date in sorted(ts_local.dt.date.unique()):
            if not self._calendar.is_trading_day(trading_date):
                out_of_session_bars = (ts_local.dt.date == trading_date).sum()
                if out_of_session_bars > 0:
                    out_of_session_count += out_of_session_bars
                    report.issues.append(
                        f"Session alignment: {out_of_session_bars} bar(s) on "
                        f"non-trading day {trading_date}."
                    )
                continue

            window = self._calendar.session_bounds(trading_date)
            day_mask = ts_local.dt.date == trading_date
            day_ts = ts_local[day_mask]

            before_session = (day_ts < window.start).sum()
            after_session = (day_ts >= window.end).sum()
            if before_session or after_session:
                out_of_session_count += int(before_session) + int(after_session)
                report.issues.append(
                    f"Session alignment: {before_session} bar(s) before session open "
                    f"and {after_session} bar(s) after session close on {trading_date}."
                )

        if out_of_session_count == 0:
            report.session_aligned = True

        # ----------------------------------------------------------------
        # Check 5: Missing expected buckets.  This is an integrity failure: a
        # certified derived dataset may not silently omit a complete bucket.
        # ----------------------------------------------------------------
        if self._target_minutes is not None:
            for trading_date in sorted(ts_local.dt.date.unique()):
                if not self._calendar.is_trading_day(trading_date):
                    continue
                window = self._calendar.session_bounds(trading_date)
                session_minutes = int(
                    (window.end - window.start).total_seconds() / 60
                )
                expected_buckets = session_minutes // self._target_minutes
                actual_buckets = int((ts_local.dt.date == trading_date).sum())
                if actual_buckets < expected_buckets:
                    msg = (
                        f"Missing buckets on {trading_date}: "
                        f"expected {expected_buckets}, got {actual_buckets} "
                        f"({expected_buckets - actual_buckets} missing)."
                    )
                    report.missing_buckets.append(msg)
                    report.issues.append(msg)
                    logger.error(
                        "DQ missing buckets: {} {} {} — {}",
                        symbol,
                        exchange,
                        self._target_timeframe,
                        msg,
                    )

        # ----------------------------------------------------------------
        # Check 6: Timestamp monotonicity
        # ----------------------------------------------------------------
        sorted_ts = df["timestamp"].sort_values()
        if not (sorted_ts.values == df["timestamp"].values).all():
            report.issues.append(
                "Timestamp monotonicity check FAILED: timestamps are not strictly ascending."
            )
        elif df["timestamp"].is_monotonic_increasing:
            report.timestamp_monotonic = True
        else:
            report.issues.append(
                "Timestamp monotonicity check FAILED: non-monotonic timestamp sequence."
            )
        # Only mark monotonic True if no existing issue
        if "Timestamp monotonicity check FAILED" not in " ".join(report.issues):
            report.timestamp_monotonic = True

        # ----------------------------------------------------------------
        # Final certification decision
        # ----------------------------------------------------------------
        report.certified = (
            report.schema_ok
            and report.ohlc_integrity_ok
            and report.no_duplicates
            and report.session_aligned
            and report.timestamp_monotonic
            and not report.missing_buckets
        )

        log_level = "info" if report.certified else "error"
        getattr(logger, log_level)(
            "DQ certification {} for derived {} {} {}: issues={}",
            "PASSED" if report.certified else "FAILED",
            symbol,
            exchange,
            self._target_timeframe,
            report.issues or "none",
        )
        return report
