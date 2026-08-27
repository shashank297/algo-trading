"""Session-aware OHLCV resampler for certified multi-timeframe bar derivation.

Phase 2.2 — Certified Multi-Timeframe Data Platform.

Every derived bar is cryptographically bound to its exact certified 1m source dataset.
The same source + calendar + resampler version + timeframe deterministically produces
identical OHLCV output and identical content hash.

Rules enforced:
- Never crosses NSE (or any market) session boundaries.
- Never combines different trading days.
- Drops incomplete trailing buckets.
- Rejects quarantined or untrusted 1m intervals.
- Rejects mixed adjustment basis.
- Rejects mixed symbol/exchange identity across source bars.
- No forward-fill, no synthetic prices, no interpolation.
- Preserves all OHLCV aggregation invariants:
    open   = first authoritative open
    high   = max authoritative high
    low    = min authoritative low
    close  = last authoritative close
    volume = sum authoritative volume
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd
from loguru import logger


if TYPE_CHECKING:
    from storage.duckdb_manager import DuckDBManager
    from trading_stack.calendars import MarketCalendar


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESAMPLER_VERSION = "session-resampler-v1"
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "30m", "60m")
_TIMEFRAME_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
}

# NSE timezone
_IST = "Asia/Kolkata"


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResampledBar:
    """Single derived OHLCV bar produced from N consecutive 1m source bars."""

    timestamp: datetime  # UTC open timestamp of this bucket
    open: float
    high: float
    low: float
    close: float
    volume: int
    bucket_bar_count: int  # number of 1m source bars aggregated into this bar


@dataclass(frozen=True)
class DerivedDatasetCertification:
    """Immutable lineage + DQ certification record for one derived dataset.

    Persisted to ``derived_datasets`` table. Provides full traceability from
    a derived 15m bar back to the exact certified 1m source dataset_id(s).
    """

    derived_dataset_id: str
    source_dataset_ids: list[str]
    source_content_hashes: list[str]
    symbol: str
    exchange: str
    timeframe: str
    adjustment_basis: str
    resampler_version: str
    calendar_version: str
    start_ts: datetime
    end_ts: datetime
    row_count: int
    content_hash: str
    dq_status: str  # PENDING | CERTIFIED | DQ_FAILED
    dq_report: dict[str, Any] = field(default_factory=dict)

    def to_storage_row(self) -> dict[str, Any]:
        """Return a dict suitable for insertion into ``derived_datasets``."""
        return {
            "derived_dataset_id": self.derived_dataset_id,
            "source_dataset_ids": json.dumps(self.source_dataset_ids, sort_keys=True),
            "source_content_hashes": json.dumps(self.source_content_hashes, sort_keys=True),
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "adjustment_basis": self.adjustment_basis,
            "resampler_version": self.resampler_version,
            "calendar_version": self.calendar_version,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "row_count": self.row_count,
            "content_hash": self.content_hash,
            "dq_status": self.dq_status,
            "dq_report_json": json.dumps(self.dq_report, sort_keys=True, default=str),
            "created_at": datetime.now(timezone.utc),
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ResamplingError(ValueError):
    """Raised when source bars cannot be safely resampled."""


class MixedAdjustmentBasisError(ResamplingError):
    """Raised when source bars contain mixed price adjustment states."""


class MixedSymbolIdentityError(ResamplingError):
    """Raised when source bars contain mixed symbol or exchange identities."""


class QuarantinedSourceError(ResamplingError):
    """Raised when source bars contain quarantined or untrusted intervals."""


class UnsupportedTimeframeError(ResamplingError):
    """Raised when the requested target timeframe is not supported."""


class UncertifiedSourceError(ResamplingError):
    """Raised when attempting to derive bars from an uncertified source dataset."""


# ---------------------------------------------------------------------------
# Core resampler
# ---------------------------------------------------------------------------


class SessionBarResampler:
    """Derives N-minute OHLCV bars from certified 1m canonical bars.

    This class is the authoritative derivation engine for Phase 2.2. It produces
    deterministic, session-boundary-aware OHLCV bars at 5m, 15m, 30m, and 60m
    granularities. Every output is cryptographically traceable to its source.

    Usage::

        resampler = SessionBarResampler()
        bars_15m = resampler.resample(df_1m, "15m", calendar, "SPLIT_ADJUSTED")

        # With full lineage registration:
        cert = resampler.derive_and_certify(
            source_dataset_id="ds_abc",
            bars_1m=df_1m,
            target_timeframe="15m",
            calendar=calendar,
            source_adjustment="SPLIT_ADJUSTED",
            source_content_hash="sha256...",
            db=db,
        )
    """

    RESAMPLER_VERSION: str = RESAMPLER_VERSION
    SUPPORTED_TIMEFRAMES: tuple[str, ...] = SUPPORTED_TIMEFRAMES

    def resample(
        self,
        bars_1m: pd.DataFrame,
        target_timeframe: str,
        calendar: "MarketCalendar",
        source_adjustment: str,
    ) -> list[ResampledBar]:
        """Resample certified 1m bars into ``target_timeframe`` bars.

        Args:
            bars_1m: DataFrame with columns {timestamp (UTC), open, high, low, close, volume}.
                     Any extra columns are ignored.
            target_timeframe: One of ``SUPPORTED_TIMEFRAMES``.
            calendar: Market calendar providing session bounds and holiday logic.
            source_adjustment: Price adjustment basis of the source bars (e.g. 'SPLIT_ADJUSTED').
                               All bars must share this basis; mixed basis raises.

        Returns:
            Sorted list of :class:`ResampledBar` objects (UTC timestamps).

        Raises:
            UnsupportedTimeframeError: If ``target_timeframe`` is not in SUPPORTED_TIMEFRAMES.
            ResamplingError: If ``bars_1m`` is empty.
            MixedAdjustmentBasisError: If source bars carry more than one adjustment basis.
            MixedSymbolIdentityError: If source bars span more than one symbol or exchange.
            QuarantinedSourceError: If any source bar is flagged as quarantined/untrusted.
        """
        self._validate_timeframe(target_timeframe)
        self._validate_input(bars_1m, source_adjustment)

        target_minutes = _TIMEFRAME_MINUTES[target_timeframe]
        import zoneinfo  # noqa: PLC0415 — lazy import to avoid import-time dependency

        tz = zoneinfo.ZoneInfo(calendar.spec.timezone)

        # Normalise timestamps to UTC-aware
        ts_series = pd.to_datetime(bars_1m["timestamp"], utc=True)
        # Convert to local market timezone for session boundary arithmetic
        ts_local = ts_series.dt.tz_convert(tz)

        trading_dates = ts_local.dt.date.unique()
        result: list[ResampledBar] = []

        for trading_date in sorted(trading_dates):
            if not calendar.is_trading_day(trading_date):
                # Market holiday — zero bars for this date (not NaN gaps)
                logger.debug(
                    "Skipping non-trading day {} during resampling.",
                    trading_date,
                )
                continue

            window = calendar.session_bounds(trading_date)
            session_open_local = window.start  # tz-aware local datetime
            session_close_local = window.end

            # Compute session duration in minutes
            session_minutes = int(
                (session_close_local - session_open_local).total_seconds() / 60
            )

            session_open_utc = session_open_local.astimezone(timezone.utc)

            # Filter bars strictly within session [open, close)
            date_mask = ts_local.dt.date == trading_date
            in_session_mask = (ts_local >= session_open_local) & (ts_local < session_close_local)
            day_bars_utc = ts_series[date_mask & in_session_mask]
            day_df = bars_1m.loc[date_mask & in_session_mask].copy()
            day_df["_ts_utc"] = day_bars_utc

            if day_df.empty:
                continue

            # Compute bucket index for each 1m bar via elapsed minutes from session open
            elapsed_minutes = ((day_df["_ts_utc"] - session_open_utc).dt.total_seconds() // 60).astype(int)
            day_df["_bucket_idx"] = elapsed_minutes // target_minutes

            # Number of complete buckets: only emit buckets that fully close within session
            # A bucket is complete if (bucket_idx + 1) * target_minutes <= session_minutes
            max_complete_bucket_idx = (session_minutes // target_minutes) - 1

            # Drop bars in incomplete trailing bucket
            day_df = day_df[day_df["_bucket_idx"] <= max_complete_bucket_idx]

            if day_df.empty:
                continue

            # Aggregate each bucket
            grouped = day_df.groupby("_bucket_idx")

            for bucket_idx, group in grouped:
                group_sorted = group.sort_values("_ts_utc")

                from datetime import timedelta  # noqa: PLC0415
                # Compute UTC open timestamp for this bucket
                bucket_open_utc = session_open_utc + timedelta(minutes=int(bucket_idx) * target_minutes)
                expected = pd.date_range(bucket_open_utc, periods=target_minutes, freq="min", tz="UTC")
                if len(group_sorted) != target_minutes or not pd.DatetimeIndex(group_sorted["_ts_utc"]).equals(expected):
                    raise ResamplingError(
                        f"Incomplete or misaligned source bucket at {bucket_open_utc.isoformat()}: "
                        f"expected {target_minutes} consecutive 1m bars, got {len(group_sorted)}."
                    )

                result.append(
                    ResampledBar(
                        timestamp=bucket_open_utc,
                        open=float(group_sorted["open"].iloc[0]),
                        high=float(group_sorted["high"].max()),
                        low=float(group_sorted["low"].min()),
                        close=float(group_sorted["close"].iloc[-1]),
                        volume=int(group_sorted["volume"].sum()),
                        bucket_bar_count=len(group_sorted),
                    )
                )

        result.sort(key=lambda b: b.timestamp)
        logger.debug(
            "Resampled {} 1m bars → {} {} bars.",
            len(bars_1m),
            len(result),
            target_timeframe,
        )
        return result

    def derive_and_certify(
        self,
        *,
        source_dataset_id: str,
        target_timeframe: str,
        calendar: "MarketCalendar",
        db: "DuckDBManager",
        symbol: str,
        exchange: str,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> DerivedDatasetCertification:
        """Resample, run DQ, compute content hash, register lineage, and persist derived bars.

        This is the authoritative entry point for Phase 2.2 derivation. It:
        1. Resamples 1m → N-minute bars.
        2. Runs DQ certification (fail-closed).
        3. Computes a deterministic content hash.
        4. Persists bars to ``historical_candles`` tagged with the derived_dataset_id.
        5. Persists lineage to ``derived_datasets``.

        Args:
            source_dataset_id: ``dataset_id`` of the CANONICAL_PROMOTED 1m source.
            bars_1m: Raw 1m bar DataFrame (pre-filtered to the desired date range).
            target_timeframe: '5m', '15m', '30m', or '60m'.
            calendar: Market calendar.
            source_adjustment: Adjustment basis of source bars.
            source_content_hash: Content hash of the source dataset (from ``market_datasets``).
            db: DuckDB connection.
            symbol: Canonical symbol.
            exchange: Exchange segment.

        Returns:
            :class:`DerivedDatasetCertification` with ``dq_status='CERTIFIED'`` on success.

        Raises:
            ResamplingError: On any resampling invariant violation.
            RuntimeError: If DQ certification fails (dq_status='DQ_FAILED').
        """
        from data_platform.dq_derived import DerivedBarDQCertifier  # avoid circular import

        source = db.load_certified_1m_source(
            source_dataset_id=source_dataset_id, symbol=symbol, exchange=exchange,
            start_ts=start_ts, end_ts=end_ts,
        )
        bars_1m = source["bars"]
        source_adjustment = source["adjustment"]
        source_content_hash = source["content_hash"]
        derived_dataset_id = str(uuid.uuid4())
        try:
            resampled = self.resample(bars_1m, target_timeframe, calendar, source_adjustment)
        except Exception as exc:
            db.persist_failed_derived_dataset(self._failed_certification(
                derived_dataset_id, source_dataset_id, source_content_hash, symbol, exchange,
                target_timeframe, calendar, source_adjustment, start_ts, end_ts, str(exc),
            ))
            raise

        if not resampled:
            raise ResamplingError(
                f"Resampling produced zero bars for {symbol}/{exchange} {target_timeframe}."
            )

        # Build DataFrame of derived bars
        from trading_stack.bar_availability import bar_available_at

        source_availability = {
            pd.Timestamp(row.timestamp): pd.Timestamp(row.available_at).to_pydatetime()
            for row in bars_1m.itertuples(index=False)
        }
        derived_df = pd.DataFrame(
            [
                {
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "available_at": max(
                        bar_available_at(pd.Timestamp(bar.timestamp).to_pydatetime(), target_timeframe, calendar),
                        max(
                            available_at for source_timestamp, available_at in source_availability.items()
                            if pd.Timestamp(bar.timestamp) <= source_timestamp
                            < pd.Timestamp(bar_available_at(pd.Timestamp(bar.timestamp).to_pydatetime(), target_timeframe, calendar))
                        ),
                    ),
                }
                for bar in resampled
            ]
        )

        # DQ certification — fail closed
        certifier = DerivedBarDQCertifier(calendar=calendar, target_timeframe=target_timeframe)
        dq_report = certifier.certify(
            derived_df, symbol=symbol, exchange=exchange, derived_dataset_id=derived_dataset_id
        )

        dq_status = "CERTIFIED" if dq_report.certified else "DQ_FAILED"
        if not dq_report.certified:
            logger.error(
                "DQ certification FAILED for derived {} {} {}: {}",
                symbol,
                target_timeframe,
                source_dataset_id,
                dq_report.issues,
            )
            db.persist_failed_derived_dataset(self._failed_certification(
                derived_dataset_id, source_dataset_id, source_content_hash, symbol, exchange,
                target_timeframe, calendar, source_adjustment, start_ts, end_ts,
                "; ".join(dq_report.issues), dq_report.to_dict(), len(derived_df),
            ))
            raise RuntimeError(
                f"DQ certification failed for derived {symbol} {target_timeframe}: "
                f"{'; '.join(dq_report.issues)}"
            )

        # Compute deterministic content hash
        content_hash = _compute_derived_content_hash(derived_df, {
            "source_dataset_id": source_dataset_id,
            "source_content_hash": source_content_hash,
            "symbol": symbol, "exchange": exchange, "adjustment_basis": source_adjustment,
            "target_timeframe": target_timeframe, "calendar_version": calendar.version,
            "resampler_version": self.RESAMPLER_VERSION,
            "requested_start": start_ts, "requested_end": end_ts,
        })

        start_ts = derived_df["timestamp"].min()
        end_ts = derived_df["timestamp"].max()
        if hasattr(start_ts, "to_pydatetime"):
            start_ts = start_ts.to_pydatetime()
        if hasattr(end_ts, "to_pydatetime"):
            end_ts = end_ts.to_pydatetime()

        certification = DerivedDatasetCertification(
            derived_dataset_id=derived_dataset_id,
            source_dataset_ids=[source_dataset_id],
            source_content_hashes=[source_content_hash],
            symbol=symbol,
            exchange=exchange,
            timeframe=target_timeframe,
            adjustment_basis=source_adjustment,
            resampler_version=self.RESAMPLER_VERSION,
            calendar_version=calendar.version,
            start_ts=start_ts,
            end_ts=end_ts,
            row_count=len(derived_df),
            content_hash=content_hash,
            dq_status=dq_status,
            dq_report=dq_report.to_dict(),
        )

        db.persist_certified_derived_dataset(
            certification=certification, derived_bars=derived_df,
            source_provider_token=source["provider_token"],
        )

        logger.info(
            "Derived & certified: {} {} {} — {} bars, hash={}, id={}",
            symbol,
            exchange,
            target_timeframe,
            len(resampled),
            content_hash[:12],
            derived_dataset_id[:8],
        )
        return certification

    def _failed_certification(
        self, derived_dataset_id: str, source_dataset_id: str, source_content_hash: str,
        symbol: str, exchange: str, timeframe: str, calendar: "MarketCalendar",
        adjustment: str, start_ts: datetime | None, end_ts: datetime | None, issue: str,
        dq_report: dict[str, Any] | None = None, row_count: int = 0,
    ) -> DerivedDatasetCertification:
        now = datetime.now(timezone.utc)
        return DerivedDatasetCertification(
            derived_dataset_id=derived_dataset_id, source_dataset_ids=[source_dataset_id],
            source_content_hashes=[source_content_hash], symbol=symbol, exchange=exchange,
            timeframe=timeframe, adjustment_basis=adjustment,
            resampler_version=self.RESAMPLER_VERSION, calendar_version=calendar.version,
            start_ts=start_ts or now, end_ts=end_ts or now, row_count=row_count,
            content_hash="", dq_status="DQ_FAILED",
            dq_report=dq_report or {"derived_dataset_id": derived_dataset_id, "certified": False, "issues": [issue]},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_timeframe(self, timeframe: str) -> None:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise UnsupportedTimeframeError(
                f"Unsupported target timeframe '{timeframe}'. "
                f"Supported: {SUPPORTED_TIMEFRAMES}."
            )

    def _validate_input(self, bars: pd.DataFrame, source_adjustment: str) -> None:
        """Validate source bars before resampling."""
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required.difference(bars.columns)
        if missing:
            raise ResamplingError(
                f"Source bars are missing required columns: {sorted(missing)}."
            )

        if bars.empty:
            raise ResamplingError("Source bars DataFrame is empty — cannot resample.")

        timestamps = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
        if timestamps.isna().any() or timestamps.duplicated().any():
            raise ResamplingError("Source timestamps must be valid UTC instants and unique.")
        numeric = bars[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any() or not numeric.apply(lambda c: c.map(lambda v: abs(float(v)) != float("inf")).all()).all():
            raise ResamplingError("Source OHLCV values must be finite numeric values.")
        if (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric["volume"] < 0).any():
            raise ResamplingError("Source prices must be positive and volume must be non-negative.")

        # Reject mixed adjustment basis
        if "adjustment" in bars.columns:
            unique_adj = bars["adjustment"].dropna().unique().tolist()
            if len(unique_adj) > 1:
                raise MixedAdjustmentBasisError(
                    f"Source bars contain mixed adjustment basis: {unique_adj}. "
                    "All source bars must share the same adjustment basis."
                )
            if len(unique_adj) == 1 and unique_adj[0] != source_adjustment:
                raise MixedAdjustmentBasisError(
                    f"Source bars declare adjustment '{unique_adj[0]}' but "
                    f"'{source_adjustment}' was specified as source_adjustment."
                )

        # Reject mixed symbol identity
        if "symbol" in bars.columns:
            unique_sym = bars["symbol"].dropna().unique().tolist()
            if len(unique_sym) > 1:
                raise MixedSymbolIdentityError(
                    f"Source bars contain multiple symbols: {unique_sym}."
                )

        # Reject mixed exchange identity
        if "exchange" in bars.columns:
            unique_exc = bars["exchange"].dropna().unique().tolist()
            if len(unique_exc) > 1:
                raise MixedSymbolIdentityError(
                    f"Source bars contain multiple exchanges: {unique_exc}."
                )

        # Reject quarantined/untrusted intervals
        if "quarantined" in bars.columns:
            n_quarantined = int(bars["quarantined"].fillna(False).sum())
            if n_quarantined > 0:
                raise QuarantinedSourceError(
                    f"{n_quarantined} source bar(s) are quarantined/untrusted. "
                    "Resampling fails closed."
                )

        if "trusted" in bars.columns:
            n_untrusted = int((~bars["trusted"].fillna(True)).sum())
            if n_untrusted > 0:
                raise QuarantinedSourceError(
                    f"{n_untrusted} source bar(s) are marked untrusted. "
                    "Resampling fails closed."
                )


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------


def _compute_derived_content_hash(derived_df: pd.DataFrame, lineage: dict[str, Any] | None = None) -> str:
    """Compute a deterministic SHA256 hash of derived OHLCV content.

    Uses the same canonical JSON representation pattern as
    ``data_platform.contracts.compute_raw_provider_hash``.

    The hash is invariant to row order (rows are sorted by timestamp before hashing).
    """
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    clean = derived_df[cols].copy()
    # Normalise timestamps to ISO strings for canonical JSON
    clean["timestamp"] = pd.to_datetime(clean["timestamp"], utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    clean = clean.sort_values("timestamp")
    payload = json.dumps(
        {"bars": clean.to_dict(orient="records"), "lineage": lineage or {}},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_derived_content_hash(derived_df: pd.DataFrame) -> str:
    """Public alias for :func:`_compute_derived_content_hash`."""
    return _compute_derived_content_hash(derived_df)
