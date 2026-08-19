"""Source-level data contracts, bar semantics, and institutional corporate action continuity validation."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from data_platform.contracts import PriceAdjustment


class VolumeAdjustment(str, Enum):
    """Whether trading volume in a series has been scaled for stock splits."""

    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"


class SourceBasisDetection(str, Enum):
    """Action-level classification result from corporate action discontinuity inspection."""

    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SourceValidationStatus(str, Enum):
    """Dataset-level validation and admission status for research and trading pipelines."""

    VERIFIED = "VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    MIXED_BASIS = "MIXED_BASIS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRACT_CONFLICT = "CONTRACT_CONFLICT"
    OVERRIDDEN = "OVERRIDDEN"
    UNRESOLVED = "UNRESOLVED"


class BasisEvidenceCode(str, Enum):
    """Stable machine-readable forensic codes for evidence classification."""

    RAW_RATIO_MATCH = "RAW_RATIO_MATCH"
    ADJUSTED_RATIO_MATCH = "ADJUSTED_RATIO_MATCH"
    BOTH_RATIO_MATCH = "BOTH_RATIO_MATCH"
    NEITHER_RATIO_MATCH = "NEITHER_RATIO_MATCH"
    POOR_HYPOTHESIS_SEPARATION = "POOR_HYPOTHESIS_SEPARATION"
    SESSION_GAP_EXCEEDED = "SESSION_GAP_EXCEEDED"
    TURNOVER_DISCONTINUITY = "TURNOVER_DISCONTINUITY"
    VOLUME_BASIS_CONFLICT = "VOLUME_BASIS_CONFLICT"
    PROVIDER_CONTRACT_CONFLICT = "PROVIDER_CONTRACT_CONFLICT"
    NO_OBSERVABLE_ACTIONS = "NO_OBSERVABLE_ACTIONS"


class UnsupportedAdjustmentConversion(RuntimeError):
    """Raised when an invalid or lossy price adjustment conversion is requested."""


class AmbiguousSourceBasisError(RuntimeError):
    """Raised when provider data basis cannot be established with institutional confidence and fail_closed is True."""


class InvalidCorporateActionError(ValueError):
    """Raised when corporate action metadata contains invalid numerical or domain values (R <= 0, NaN, inf)."""


class CorporateActionEvidenceInsufficientError(RuntimeError):
    """Raised when market session gaps prevent establishing a reliable continuity boundary."""


class CorporateActionBasisWarning(UserWarning):
    """Emitted when vendor price continuity suggests historical data is already adjusted."""


@dataclass(frozen=True)
class SourceSemanticsPolicy:
    """Configurable criteria for corporate action discontinuity validation and basis inference."""

    adjusted_log_tolerance: float = 0.15  # +/- 0.15 natural-log distance (+16.2% / -13.9% deviation)
    raw_log_tolerance: float = 0.15
    max_missing_trading_sessions: int = 0  # 0 missing business days = strictly adjacent sessions
    max_calendar_gap_days: int = 7
    volume_window_sessions: int = 5
    min_evidence_strength: float = 0.80
    fail_closed: bool = True
    policy_version: str = "source-semantics-v2"
    detector_version: str = "2.0.0"
    supported_actions: tuple[str, ...] = ("SPLIT", "BONUS", "CONSOLIDATION", "COMPOSITE")

    @property
    def max_trading_session_gap(self) -> int:
        """Backward-compatible alias for max_missing_trading_sessions + 1."""
        return self.max_missing_trading_sessions + 1


@dataclass(frozen=True)
class BasisDetectionResult:
    """Comprehensive audit-grade inspection report for a single corporate action boundary."""

    instrument_id: str
    symbol: str | None
    action_ids: tuple[str, ...]
    action_types: tuple[str, ...]
    ex_date: date
    expected_multiplier: float
    pre_close: float
    ex_open: float
    ex_close: float
    observed_ratio: float | None
    log_distance_raw: float | None
    log_distance_adjusted: float | None
    hypothesis_separation: float
    turnover_ratio: float | None
    volume_ratio: float | None
    pre_session_ts: pd.Timestamp | None
    post_session_ts: pd.Timestamp | None
    missing_trading_sessions: int | None
    calendar_gap_days: int | None
    detection: SourceBasisDetection
    inferred_basis: PriceAdjustment
    evidence_strength: float
    evidence_codes: tuple[BasisEvidenceCode, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def action_id(self) -> str:
        """Backward-compatible single action ID accessor."""
        return self.action_ids[0] if self.action_ids else "UNKNOWN"

    @property
    def confidence(self) -> float:
        """Backward-compatible alias for evidence_strength."""
        return self.evidence_strength

    @property
    def trading_session_distance(self) -> int | None:
        """Distance in trading sessions (1 = adjacent sessions)."""
        return (self.missing_trading_sessions + 1) if self.missing_trading_sessions is not None else None

    @property
    def trading_session_gap(self) -> int | None:
        """Backward-compatible alias for trading_session_distance."""
        return self.trading_session_distance

    @property
    def session_gap_days(self) -> int:
        """Backward-compatible alias for calendar_gap_days."""
        return self.calendar_gap_days or 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to a dictionary."""
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "action_ids": list(self.action_ids),
            "action_types": list(self.action_types),
            "action_id": self.action_id,
            "ex_date": str(self.ex_date),
            "expected_multiplier": self.expected_multiplier,
            "pre_close": self.pre_close,
            "ex_open": self.ex_open,
            "ex_close": self.ex_close,
            "observed_ratio": self.observed_ratio,
            "log_distance_raw": self.log_distance_raw,
            "log_distance_adjusted": self.log_distance_adjusted,
            "hypothesis_separation": self.hypothesis_separation,
            "turnover_ratio": self.turnover_ratio,
            "volume_ratio": self.volume_ratio,
            "pre_session_ts": str(self.pre_session_ts) if self.pre_session_ts is not None else None,
            "post_session_ts": str(self.post_session_ts) if self.post_session_ts is not None else None,
            "missing_trading_sessions": self.missing_trading_sessions,
            "trading_session_distance": self.trading_session_distance,
            "trading_session_gap": self.trading_session_gap,
            "calendar_gap_days": self.calendar_gap_days,
            "detection": self.detection.value,
            "inferred_basis": self.inferred_basis.value,
            "evidence_strength": self.evidence_strength,
            "confidence": self.evidence_strength,
            "evidence_codes": [c.value for c in self.evidence_codes],
            "reasons": list(self.reasons),
        }

    def __getitem__(self, item: str) -> Any:
        """Dict-like subscript access for backward compatibility."""
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        """Dict-like get access for backward compatibility."""
        return getattr(self, item, default)


def calculate_semantics_hash(
    provider_name: str,
    price_adj: PriceAdjustment,
    vol_adj: VolumeAdjustment,
    validation_status: SourceValidationStatus,
    policy_version: str,
    detector_version: str,
    reports: tuple[BasisDetectionResult, ...],
) -> str:
    """Calculate a deterministic SHA-256 fingerprint for admission evidence."""
    payload = {
        "provider": provider_name,
        "price_adj": price_adj.value,
        "vol_adj": vol_adj.value,
        "status": validation_status.value,
        "policy": policy_version,
        "detector": detector_version,
        "reports": [
            {
                "inst": r.instrument_id,
                "actions": list(r.action_ids),
                "ex": str(r.ex_date),
                "det": r.detection.value,
                "obs": round(r.observed_ratio, 6) if r.observed_ratio is not None else None,
                "d_raw": round(r.log_distance_raw, 6) if r.log_distance_raw is not None else None,
                "d_adj": round(r.log_distance_adjusted, 6) if r.log_distance_adjusted is not None else None,
            }
            for r in reports
        ],
    }
    dumped = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceBarSemantics:
    """Source-level basis contract for market data received from a provider or cache."""

    price_adjustment: PriceAdjustment
    volume_adjustment: VolumeAdjustment = VolumeAdjustment.UNADJUSTED
    validation_status: SourceValidationStatus = SourceValidationStatus.VERIFIED
    pre_override_status: SourceValidationStatus | None = None
    override_reason: str | None = None
    price_includes_dividend_adjustment: bool = False
    timezone: str = "Asia/Kolkata"
    provider_name: str = "unknown"
    evidence_strength: float = 1.0
    evidence_reports: tuple[BasisDetectionResult, ...] = field(default_factory=tuple)
    policy_version: str = "source-semantics-v2"
    semantics_hash: str = ""

    def __init__(
        self,
        price_adjustment: PriceAdjustment,
        volume_adjustment: VolumeAdjustment = VolumeAdjustment.UNADJUSTED,
        validation_status: SourceValidationStatus | None = None,
        pre_override_status: SourceValidationStatus | None = None,
        override_reason: str | None = None,
        price_includes_dividend_adjustment: bool = False,
        timezone: str = "Asia/Kolkata",
        provider_name: str = "unknown",
        evidence_strength: float = 1.0,
        evidence_reports: tuple[BasisDetectionResult, ...] = (),
        policy_version: str = "source-semantics-v2",
        semantics_hash: str | None = None,
        # Backward compatibility kwargs:
        dividends_included: bool | None = None,
        basis_detection_status: Any = None,
        detection_confidence: float | None = None,
    ) -> None:
        object.__setattr__(self, "price_adjustment", price_adjustment)
        object.__setattr__(self, "volume_adjustment", volume_adjustment)

        # Map validation status
        if validation_status is not None:
            resolved_status = validation_status
        elif basis_detection_status is not None:
            if isinstance(basis_detection_status, SourceValidationStatus):
                resolved_status = basis_detection_status
            elif str(basis_detection_status).upper() in ("SPLIT_ADJUSTED", "UNADJUSTED"):
                resolved_status = SourceValidationStatus.VERIFIED
            elif str(basis_detection_status).upper() == "MIXED_BASIS":
                resolved_status = SourceValidationStatus.MIXED_BASIS
            elif str(basis_detection_status).upper() == "INSUFFICIENT_EVIDENCE":
                resolved_status = SourceValidationStatus.INSUFFICIENT_EVIDENCE
            else:
                resolved_status = SourceValidationStatus.AMBIGUOUS
        else:
            resolved_status = SourceValidationStatus.VERIFIED
        object.__setattr__(self, "validation_status", resolved_status)
        object.__setattr__(self, "pre_override_status", pre_override_status)
        object.__setattr__(self, "override_reason", override_reason)

        div_included = dividends_included if dividends_included is not None else price_includes_dividend_adjustment
        object.__setattr__(self, "price_includes_dividend_adjustment", bool(div_included))
        object.__setattr__(self, "timezone", str(timezone))
        object.__setattr__(self, "provider_name", str(provider_name))

        conf = detection_confidence if detection_confidence is not None else evidence_strength
        object.__setattr__(self, "evidence_strength", float(conf))
        object.__setattr__(self, "evidence_reports", tuple(evidence_reports))
        object.__setattr__(self, "policy_version", str(policy_version))

        if semantics_hash is not None:
            resolved_hash = semantics_hash
        else:
            resolved_hash = calculate_semantics_hash(
                provider_name=provider_name,
                price_adj=price_adjustment,
                vol_adj=volume_adjustment,
                validation_status=resolved_status,
                policy_version=policy_version,
                detector_version="2.0.0",
                reports=tuple(evidence_reports),
            )
        object.__setattr__(self, "semantics_hash", resolved_hash)

    def require_admitted(self) -> None:
        """Enforce ground-truth admission invariant: data must be VERIFIED or OVERRIDDEN."""
        if self.validation_status not in (SourceValidationStatus.VERIFIED, SourceValidationStatus.OVERRIDDEN):
            raise AmbiguousSourceBasisError(
                f"Ground-truth admission gateway rejected dataset: validation status is '{self.validation_status.value}' "
                f"(pre_override_status={self.pre_override_status.value if self.pre_override_status else None}). "
                f"Only VERIFIED or OVERRIDDEN datasets are admitted to canonical processing."
            )

    @property
    def dividends_included(self) -> bool:
        """Backward-compatible alias for price_includes_dividend_adjustment."""
        return self.price_includes_dividend_adjustment

    @property
    def basis_detection_status(self) -> SourceBasisDetection:
        """Backward-compatible alias for detection status mapping."""
        if self.validation_status == SourceValidationStatus.VERIFIED:
            return (
                SourceBasisDetection.SPLIT_ADJUSTED
                if self.price_adjustment == PriceAdjustment.SPLIT_ADJUSTED
                else SourceBasisDetection.UNADJUSTED
            )
        elif self.validation_status == SourceValidationStatus.INSUFFICIENT_EVIDENCE:
            return SourceBasisDetection.INSUFFICIENT_EVIDENCE
        return SourceBasisDetection.AMBIGUOUS

    @property
    def detection_confidence(self) -> float:
        """Backward-compatible alias for evidence_strength."""
        return self.evidence_strength

    def to_dict(self) -> dict[str, Any]:
        """Convert semantics to a serializable dictionary."""
        return {
            "price_adjustment": self.price_adjustment.value,
            "volume_adjustment": self.volume_adjustment.value,
            "validation_status": self.validation_status.value,
            "pre_override_status": self.pre_override_status.value if self.pre_override_status else None,
            "override_reason": self.override_reason,
            "price_includes_dividend_adjustment": self.price_includes_dividend_adjustment,
            "dividends_included": self.dividends_included,
            "timezone": self.timezone,
            "provider_name": self.provider_name,
            "evidence_strength": self.evidence_strength,
            "basis_detection_status": self.basis_detection_status.value,
            "detection_confidence": self.detection_confidence,
            "policy_version": self.policy_version,
            "semantics_hash": self.semantics_hash,
            "evidence_reports": [r.to_dict() for r in self.evidence_reports],
        }


def compose_same_day_share_actions(corporate_actions: pd.DataFrame) -> pd.DataFrame:
    """Compose multiple pure multiplicative share-count actions occurring on the same symbol and ex-date.

    Restricted strictly to: {"SPLIT", "BONUS", "CONSOLIDATION"}.
    Composite share_multiplier = product of share_multipliers.
    Preserves all original action IDs and action types in action_ids and action_types fields.

    Args:
        corporate_actions: Input corporate actions DataFrame.

    Returns:
        pd.DataFrame: Composed corporate actions with 1 consolidated row per (symbol, ex_date).

    Raises:
        InvalidCorporateActionError: If composed multiplier is non-finite or non-positive (overflow protection).
    """
    if corporate_actions.empty:
        return corporate_actions.copy()

    ca = corporate_actions.copy()
    if "ex_date" in ca.columns:
        ca["ex_date"] = pd.to_datetime(ca["ex_date"]).dt.date

    mult_col = "share_multiplier" if "share_multiplier" in ca.columns else "split_factor"

    splits = ca[
        ca["action_type"].isin(["SPLIT", "BONUS", "CONSOLIDATION"])
        & (ca[mult_col] > 0)
    ].copy()

    if splits.empty:
        return ca

    group_cols = ["symbol", "ex_date"] if "symbol" in splits.columns else ["ex_date"]

    composed_rows: list[dict[str, Any]] = []
    for keys, group in splits.groupby(group_cols, as_index=False):
        first_row = group.iloc[0].to_dict()
        comp_mult = float(np.prod(np.asarray(group[mult_col], dtype=np.float64)))

        # Adversarial overflow protection
        if not np.isfinite(comp_mult) or comp_mult <= 0:

            raise InvalidCorporateActionError(
                f"Composed share_multiplier {comp_mult} is non-finite or invalid for {keys}."
            )

        action_ids = tuple(str(r.get("action_id", "ACT")) for _, r in group.iterrows())
        action_types = tuple(str(r.get("action_type", "SPLIT")) for _, r in group.iterrows())

        first_row["action_ids"] = action_ids
        first_row["action_types"] = action_types
        first_row["action_id"] = "+".join(action_ids)
        first_row[mult_col] = comp_mult
        first_row["action_type"] = action_types[0] if len(set(action_types)) == 1 else "COMPOSITE"
        first_row["purpose"] = "; ".join(str(r.get("purpose", "")) for _, r in group.iterrows() if r.get("purpose"))
        composed_rows.append(first_row)

    return pd.DataFrame(composed_rows)


def compose_same_day_corporate_actions(corporate_actions: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for compose_same_day_share_actions."""
    return compose_same_day_share_actions(corporate_actions)


class SourceSemanticsAdapter:
    """Detect and validate provider adjustment semantics against corporate action boundaries."""

    @classmethod
    def detect_corporate_action_discontinuity(
        cls,
        bars: pd.DataFrame,
        corporate_actions: pd.DataFrame,
        tolerance_pct: float | None = None,
        policy: SourceSemanticsPolicy | None = None,
    ) -> list[BasisDetectionResult]:
        """Inspect price and volume continuity across corporate action ex-dates using log-space distances.

        For a share multiplier R (e.g. 10.0 for 10:1 split, 0.1 for 1:10 consolidation):
        - Raw unadjusted source: pre_close / ex_open ≈ R (log distance d_R ≈ 0).
        - Split-adjusted source: pre_close / ex_open ≈ 1.0 (log distance d_1 ≈ 0).

        Args:
            bars: Input OHLCV DataFrame with 'timestamp', 'open', 'close', and optional 'volume', 'symbol'.
            corporate_actions: Corporate actions table with 'ex_date' and 'share_multiplier'.
            tolerance_pct: Optional legacy tolerance percentage (overrides policy log tolerances if provided).
            policy: Optional SourceSemanticsPolicy for threshold and validation rules.

        Returns:
            list[BasisDetectionResult]: Audit-grade inspection results for each corporate action.

        Raises:
            InvalidCorporateActionError: If corporate action multiplier is non-positive or non-finite.
        """
        if bars.empty or corporate_actions.empty:
            return []

        active_policy = policy or SourceSemanticsPolicy()
        tau_adj = tolerance_pct if tolerance_pct is not None else active_policy.adjusted_log_tolerance
        tau_raw = tolerance_pct if tolerance_pct is not None else active_policy.raw_log_tolerance

        composed_actions = compose_same_day_share_actions(corporate_actions)
        mult_col = "share_multiplier" if "share_multiplier" in composed_actions.columns else "split_factor"

        splits = composed_actions[
            composed_actions["action_type"].isin(active_policy.supported_actions)
        ].copy()

        reports: list[BasisDetectionResult] = []

        for _, row in splits.iterrows():
            action_ids = row.get("action_ids")
            if not action_ids:
                single_id = str(row.get("action_id", "UNKNOWN"))
                action_ids = (single_id,)
            action_types = row.get("action_types")
            if not action_types:
                single_type = str(row.get("action_type", "SPLIT"))
                action_types = (single_type,)

            action_symbol = row.get("symbol")
            instrument_id = str(row.get("instrument_id") or action_symbol or "UNKNOWN")
            ex_date_val = row["ex_date"]
            ex_d = ex_date_val if isinstance(ex_date_val, date) else pd.Timestamp(ex_date_val).date()
            raw_mult_float = float(row[mult_col])

            # Domain validation: Multiplier must be strictly positive and finite
            if pd.isna(raw_mult_float) or not np.isfinite(raw_mult_float) or raw_mult_float <= 0:
                raise InvalidCorporateActionError(
                    f"Invalid corporate action share_multiplier {raw_mult_float} for {action_symbol} on {ex_d} "
                    f"(action_ids={action_ids}). Corporate actions must specify finite R > 0."
                )

            expected_multiplier = float(raw_mult_float)
            if expected_multiplier == 1.0:
                continue

            # Hypothesis separation check: |ln(R)|
            hypothesis_separation = abs(math.log(max(expected_multiplier, 1e-12)))

            # Symbol isolation
            if "symbol" in bars.columns and action_symbol and not pd.isna(action_symbol):
                sym_bars = bars[bars["symbol"] == action_symbol].copy()
                if sym_bars.empty:
                    continue
            else:
                sym_bars = bars.copy()

            sym_bars = sym_bars.sort_values(by=["timestamp"]).reset_index(drop=True)


            # Convert timestamps to local IST session timestamps
            ts = pd.to_datetime(sym_bars["timestamp"])
            if ts.dt.tz is None:
                ts = ts.dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata")
            else:
                ts = ts.dt.tz_convert("Asia/Kolkata")

            bar_dates_list = ts.dt.date.tolist()
            pre_ex_indices = np.flatnonzero(np.array([d < ex_d for d in bar_dates_list], dtype=bool))
            ex_post_indices = np.flatnonzero(np.array([d >= ex_d for d in bar_dates_list], dtype=bool))

            # Missing boundary data
            if len(pre_ex_indices) == 0 or len(ex_post_indices) == 0:
                reports.append(
                    BasisDetectionResult(
                        instrument_id=instrument_id,
                        symbol=str(action_symbol) if action_symbol else None,
                        action_ids=action_ids,
                        action_types=action_types,
                        ex_date=ex_d,
                        expected_multiplier=expected_multiplier,
                        pre_close=0.0,
                        ex_open=0.0,
                        ex_close=0.0,
                        observed_ratio=None,
                        log_distance_raw=None,
                        log_distance_adjusted=None,
                        hypothesis_separation=hypothesis_separation,
                        turnover_ratio=None,
                        volume_ratio=None,
                        pre_session_ts=None,
                        post_session_ts=None,
                        missing_trading_sessions=None,
                        calendar_gap_days=None,
                        detection=SourceBasisDetection.INSUFFICIENT_EVIDENCE,
                        inferred_basis=PriceAdjustment.UNADJUSTED,
                        evidence_strength=0.0,
                        evidence_codes=(BasisEvidenceCode.SESSION_GAP_EXCEEDED,),
                        reasons=("No pre-ex or post-ex price bars present in dataset.",),
                    )
                )
                continue

            last_pre_idx = pre_ex_indices[-1]
            first_ex_idx = ex_post_indices[0]

            pre_session_ts = ts.iloc[last_pre_idx]
            post_session_ts = ts.iloc[first_ex_idx]
            calendar_gap_days = (post_session_ts.date() - pre_session_ts.date()).days

            # Calculate missing trading sessions:
            # Friday -> Monday (3 calendar days, 0 business days between) -> missing_trading_sessions = 0 (strictly adjacent).
            bus_days_between = len(pd.bdate_range(pre_session_ts.date() + pd.Timedelta(days=1), post_session_ts.date() - pd.Timedelta(days=1)))
            missing_trading_sessions = bus_days_between

            evidence_codes: list[BasisEvidenceCode] = []
            reasons: list[str] = []

            # Check for poor hypothesis separation (R approx 1)
            if hypothesis_separation <= (tau_raw + tau_adj):
                evidence_codes.append(BasisEvidenceCode.POOR_HYPOTHESIS_SEPARATION)
                reasons.append(
                    f"Multiplier R={expected_multiplier:.4f} has poor hypothesis separation (|ln(R)|={hypothesis_separation:.4f} <= {tau_raw + tau_adj:.4f})."
                )

            # Check trading session gap constraint
            if missing_trading_sessions > active_policy.max_missing_trading_sessions or calendar_gap_days > active_policy.max_calendar_gap_days:
                evidence_codes.append(BasisEvidenceCode.SESSION_GAP_EXCEEDED)
                reasons.append(
                    f"Session gap of {missing_trading_sessions} missing trading sessions ({calendar_gap_days} calendar days) "
                    f"between {pre_session_ts.date()} and {post_session_ts.date()} exceeds limit."
                )
                reports.append(
                    BasisDetectionResult(
                        instrument_id=instrument_id,
                        symbol=str(action_symbol) if action_symbol else None,
                        action_ids=action_ids,
                        action_types=action_types,
                        ex_date=ex_d,
                        expected_multiplier=expected_multiplier,
                        pre_close=float(sym_bars["close"].iloc[last_pre_idx]),
                        ex_open=float(sym_bars["open"].iloc[first_ex_idx]),
                        ex_close=float(sym_bars["close"].iloc[first_ex_idx]),
                        observed_ratio=None,
                        log_distance_raw=None,
                        log_distance_adjusted=None,
                        hypothesis_separation=hypothesis_separation,
                        turnover_ratio=None,
                        volume_ratio=None,
                        pre_session_ts=pre_session_ts,
                        post_session_ts=post_session_ts,
                        missing_trading_sessions=missing_trading_sessions,
                        calendar_gap_days=calendar_gap_days,
                        detection=SourceBasisDetection.INSUFFICIENT_EVIDENCE,
                        inferred_basis=PriceAdjustment.UNADJUSTED,
                        evidence_strength=0.0,
                        evidence_codes=tuple(evidence_codes),
                        reasons=tuple(reasons),
                    )
                )
                continue

            pre_close = float(sym_bars["close"].iloc[last_pre_idx])
            ex_open = float(sym_bars["open"].iloc[first_ex_idx])
            ex_close = float(sym_bars["close"].iloc[first_ex_idx])

            if pre_close <= 0 or ex_open <= 0:
                evidence_codes.append(BasisEvidenceCode.NEITHER_RATIO_MATCH)
                reasons.append(f"Non-positive boundary prices observed (pre_close={pre_close}, ex_open={ex_open}).")
                reports.append(
                    BasisDetectionResult(
                        instrument_id=instrument_id,
                        symbol=str(action_symbol) if action_symbol else None,
                        action_ids=action_ids,
                        action_types=action_types,
                        ex_date=ex_d,
                        expected_multiplier=expected_multiplier,
                        pre_close=pre_close,
                        ex_open=ex_open,
                        ex_close=ex_close,
                        observed_ratio=None,
                        log_distance_raw=None,
                        log_distance_adjusted=None,
                        hypothesis_separation=hypothesis_separation,
                        turnover_ratio=None,
                        volume_ratio=None,
                        pre_session_ts=pre_session_ts,
                        post_session_ts=post_session_ts,
                        missing_trading_sessions=missing_trading_sessions,
                        calendar_gap_days=calendar_gap_days,
                        detection=SourceBasisDetection.AMBIGUOUS,
                        inferred_basis=PriceAdjustment.UNADJUSTED,
                        evidence_strength=0.0,
                        evidence_codes=tuple(evidence_codes),
                        reasons=tuple(reasons),
                    )
                )
                continue

            observed_ratio = pre_close / ex_open

            # Compute symmetric log-space distances:
            # d_R = |ln(expected_R / observed_ratio)|  (0 if exactly unadjusted raw jump)
            # d_1 = |ln(observed_ratio)|               (0 if exactly split-adjusted continuous)
            log_dist_raw = abs(math.log(max(expected_multiplier, 1e-12) / max(observed_ratio, 1e-12)))
            log_dist_adj = abs(math.log(max(observed_ratio, 1e-12)))

            # Supporting evidence: Multi-session volume & turnover continuity
            win = active_policy.volume_window_sessions
            pre_start_idx = max(0, last_pre_idx - win + 1)
            post_end_idx = min(len(sym_bars), first_ex_idx + win)

            turnover_ratio = None
            volume_ratio = None

            if "volume" in sym_bars.columns and "close" in sym_bars.columns:
                pre_vols = np.asarray(sym_bars["volume"].iloc[pre_start_idx : last_pre_idx + 1], dtype=np.float64)
                post_vols = np.asarray(sym_bars["volume"].iloc[first_ex_idx:post_end_idx], dtype=np.float64)
                pre_turnover = np.asarray(
                    sym_bars["close"].iloc[pre_start_idx : last_pre_idx + 1] * sym_bars["volume"].iloc[pre_start_idx : last_pre_idx + 1],
                    dtype=np.float64,
                )
                post_turnover = np.asarray(
                    sym_bars["close"].iloc[first_ex_idx:post_end_idx] * sym_bars["volume"].iloc[first_ex_idx:post_end_idx],
                    dtype=np.float64,
                )

                med_pre_vol = float(np.median(pre_vols)) if pre_vols.size > 0 else 0.0
                med_post_vol = float(np.median(post_vols)) if post_vols.size > 0 else 0.0
                med_pre_to = float(np.median(pre_turnover)) if pre_turnover.size > 0 else 0.0
                med_post_to = float(np.median(post_turnover)) if post_turnover.size > 0 else 0.0


                if med_post_vol > 0:
                    volume_ratio = med_pre_vol / med_post_vol
                if med_post_to > 0:
                    turnover_ratio = med_pre_to / med_post_to
                    if abs(math.log(max(turnover_ratio, 1e-12))) > 1.2:
                        evidence_codes.append(BasisEvidenceCode.TURNOVER_DISCONTINUITY)
                        reasons.append(f"Turnover ratio {turnover_ratio:.2f} exhibits discontinuity across boundary.")

            # Decision Matrix:
            raw_match = log_dist_raw <= tau_raw
            adjusted_match = log_dist_adj <= tau_adj

            if adjusted_match and not raw_match:
                detection = SourceBasisDetection.SPLIT_ADJUSTED
                inferred_basis = PriceAdjustment.SPLIT_ADJUSTED
                conf_denom = max(log_dist_adj + log_dist_raw, 1e-12)
                evidence_strength = max(0.0, min(1.0, 1.0 - (log_dist_adj / conf_denom)))
                evidence_codes.append(BasisEvidenceCode.ADJUSTED_RATIO_MATCH)
                warning_msg = (
                    f"CorporateActionBasisWarning: Expected raw split discontinuity near {expected_multiplier:.2f}x "
                    f"for {action_symbol} around {ex_d}, but observed price ratio is {observed_ratio:.2f}x "
                    f"(log-distance={log_dist_adj:.4f}). Provider history is already split-adjusted."
                )
                logger.warning("{}", warning_msg)
                warnings.warn(warning_msg, CorporateActionBasisWarning, stacklevel=2)
                reasons.append(f"Observed ratio {observed_ratio:.2f}x matches split-adjusted continuity (d_1={log_dist_adj:.3f} <= {tau_adj:.3f}).")
            elif raw_match and not adjusted_match:
                detection = SourceBasisDetection.UNADJUSTED
                inferred_basis = PriceAdjustment.UNADJUSTED
                conf_denom = max(log_dist_adj + log_dist_raw, 1e-12)
                evidence_strength = max(0.0, min(1.0, 1.0 - (log_dist_raw / conf_denom)))
                evidence_codes.append(BasisEvidenceCode.RAW_RATIO_MATCH)
                reasons.append(f"Observed ratio {observed_ratio:.2f}x matches raw split discontinuity (d_R={log_dist_raw:.3f} <= {tau_raw:.3f}).")
            elif raw_match and adjusted_match:
                detection = SourceBasisDetection.AMBIGUOUS
                inferred_basis = PriceAdjustment.UNADJUSTED
                evidence_strength = 0.50
                evidence_codes.append(BasisEvidenceCode.BOTH_RATIO_MATCH)
                reasons.append(f"Ambiguous: observed ratio {observed_ratio:.2f}x matches both hypotheses (d_R={log_dist_raw:.3f}, d_1={log_dist_adj:.3f}).")
            else:
                detection = SourceBasisDetection.AMBIGUOUS
                inferred_basis = PriceAdjustment.UNADJUSTED
                evidence_strength = 0.0
                evidence_codes.append(BasisEvidenceCode.NEITHER_RATIO_MATCH)
                reasons.append(f"Ambiguous: observed ratio {observed_ratio:.2f}x matches neither hypothesis (d_R={log_dist_raw:.3f}, d_1={log_dist_adj:.3f}).")

            reports.append(
                BasisDetectionResult(
                    instrument_id=instrument_id,
                    symbol=str(action_symbol) if action_symbol else None,
                    action_ids=action_ids,
                    action_types=action_types,
                    ex_date=ex_d,
                    expected_multiplier=expected_multiplier,
                    pre_close=pre_close,
                    ex_open=ex_open,
                    ex_close=ex_close,
                    observed_ratio=observed_ratio,
                    log_distance_raw=log_dist_raw,
                    log_distance_adjusted=log_dist_adj,
                    hypothesis_separation=hypothesis_separation,
                    turnover_ratio=turnover_ratio,
                    volume_ratio=volume_ratio,
                    pre_session_ts=pre_session_ts,
                    post_session_ts=post_session_ts,
                    missing_trading_sessions=missing_trading_sessions,
                    calendar_gap_days=calendar_gap_days,
                    detection=detection,
                    inferred_basis=inferred_basis,
                    evidence_strength=evidence_strength,
                    evidence_codes=tuple(evidence_codes),
                    reasons=tuple(reasons),
                )
            )

        return reports

    @classmethod
    def infer_semantics(
        cls,
        bars: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
        provider_name: str = "unknown",
        declared_adjustment: PriceAdjustment | str | None = None,
        override_reason: str | None = None,
        policy: SourceSemanticsPolicy | None = None,
    ) -> SourceBarSemantics:
        """Infer source bar semantics using declared metadata and institutional dataset-level evidence aggregation.

        Args:
            bars: Input OHLCV DataFrame.
            corporate_actions: Optional corporate actions DataFrame.
            provider_name: Provider or source identifier.
            declared_adjustment: Explicitly declared adjustment if known.
            override_reason: Optional human or system audit reason if applying an override.
            policy: Optional SourceSemanticsPolicy for threshold and validation rules.

        Returns:
            SourceBarSemantics: Inferred, validated, and provenance-tracked source semantics.

        Raises:
            AmbiguousSourceBasisError: If basis cannot be established with confidence and policy.fail_closed is True.
        """
        active_policy = policy or SourceSemanticsPolicy()

        # 1. Resolve explicit declared adjustment if provided
        declared_explicitly = False
        declared_target: PriceAdjustment | None = None
        if declared_adjustment is not None:
            if isinstance(declared_adjustment, PriceAdjustment):
                declared_target = declared_adjustment
            else:
                declared_target = PriceAdjustment(declared_adjustment.upper())
            declared_explicitly = True
        elif "adjustment" in bars.columns and not bars["adjustment"].isna().all():
            val = str(bars["adjustment"].dropna().iloc[0]).upper()
            try:
                declared_target = PriceAdjustment(val)
                declared_explicitly = True
            except ValueError:
                declared_target = PriceAdjustment.UNADJUSTED
        else:
            declared_target = PriceAdjustment.UNADJUSTED

        inferred_price_adj = declared_target if declared_explicitly else PriceAdjustment.UNADJUSTED
        evidence_strength = 1.0
        reports: list[BasisDetectionResult] = []
        empirical_status = SourceValidationStatus.VERIFIED

        # 2. If corporate actions exist, collect complete forensic evidence
        if corporate_actions is not None and not corporate_actions.empty:
            reports = cls.detect_corporate_action_discontinuity(bars, corporate_actions, policy=active_policy)
            if reports:
                scores = [r.evidence_strength for r in reports]
                conclusive_basis = {
                    r.detection
                    for r in reports
                    if r.detection in (SourceBasisDetection.UNADJUSTED, SourceBasisDetection.SPLIT_ADJUSTED)
                }

                # Deterministic Precedence 1: Mixed basis across boundaries (always highest precedence)
                if len(conclusive_basis) > 1:
                    empirical_status = SourceValidationStatus.MIXED_BASIS
                    evidence_strength = float(np.mean(scores))
                    err_msg = (
                        f"Dataset exhibits MIXED_BASIS across corporate action boundaries: "
                        f"{[r.to_dict() for r in reports]}. Some boundaries appear split-adjusted while others are unadjusted."
                    )
                    logger.error("{}", err_msg)
                # Deterministic Precedence 2: Single conclusive basis with possible noise or contract conflict
                elif len(conclusive_basis) == 1:
                    single_det = next(iter(conclusive_basis))
                    inferred_price_adj = (
                        PriceAdjustment.SPLIT_ADJUSTED
                        if single_det == SourceBasisDetection.SPLIT_ADJUSTED
                        else PriceAdjustment.UNADJUSTED
                    )

                    if any(r.detection == SourceBasisDetection.AMBIGUOUS for r in reports):
                        empirical_status = SourceValidationStatus.AMBIGUOUS
                        evidence_strength = float(np.mean(scores))
                    elif any(r.detection == SourceBasisDetection.INSUFFICIENT_EVIDENCE for r in reports):
                        empirical_status = SourceValidationStatus.INSUFFICIENT_EVIDENCE
                        evidence_strength = float(np.mean(scores))
                    else:
                        empirical_status = SourceValidationStatus.VERIFIED
                        evidence_strength = float(np.min(scores))
                # Deterministic Precedence 3: Inconclusive across all boundaries
                else:
                    if any(r.detection == SourceBasisDetection.AMBIGUOUS for r in reports):
                        empirical_status = SourceValidationStatus.AMBIGUOUS
                        evidence_strength = float(np.mean(scores))
                    elif any(r.detection == SourceBasisDetection.INSUFFICIENT_EVIDENCE for r in reports):
                        empirical_status = SourceValidationStatus.INSUFFICIENT_EVIDENCE
                        evidence_strength = float(np.mean(scores))
                    else:
                        empirical_status = SourceValidationStatus.VERIFIED
                        evidence_strength = 1.0

        # 3. Apply override governance and contract conflict checks
        if declared_explicitly and declared_target is not None:
            if empirical_status == SourceValidationStatus.VERIFIED:
                if declared_target == inferred_price_adj:
                    validation_status = SourceValidationStatus.VERIFIED
                    pre_override_status = None
                    override_reason = None
                else:
                    validation_status = SourceValidationStatus.CONTRACT_CONFLICT
                    pre_override_status = empirical_status
                    err_msg = (
                        f"Contract conflict: Declared {declared_target.value} but empirical evidence "
                        f"conclusively proves {inferred_price_adj.value}."
                    )
                    logger.error("{}", err_msg)
                    if active_policy.fail_closed:
                        raise AmbiguousSourceBasisError(err_msg)
            else:
                validation_status = SourceValidationStatus.OVERRIDDEN
                pre_override_status = empirical_status
                inferred_price_adj = declared_target
        else:
            validation_status = empirical_status
            pre_override_status = None
            if active_policy.fail_closed and validation_status not in (SourceValidationStatus.VERIFIED, SourceValidationStatus.OVERRIDDEN):
                err_msg = (
                    f"Dataset corporate action admission rejected with status '{validation_status.value}': "
                    f"{[r.to_dict() for r in reports]}."
                )
                logger.error("{}", err_msg)
                raise AmbiguousSourceBasisError(err_msg)


        vol_adj = (
            VolumeAdjustment.SPLIT_ADJUSTED
            if inferred_price_adj == PriceAdjustment.SPLIT_ADJUSTED
            else VolumeAdjustment.UNADJUSTED
        )

        return SourceBarSemantics(
            price_adjustment=inferred_price_adj,
            volume_adjustment=vol_adj,
            validation_status=validation_status,
            pre_override_status=pre_override_status,
            override_reason=override_reason,
            price_includes_dividend_adjustment=False,
            timezone="Asia/Kolkata",
            provider_name=provider_name,
            evidence_strength=evidence_strength,
            evidence_reports=tuple(reports),
            policy_version=active_policy.policy_version,
        )

    @classmethod
    def persist_detections(
        cls,
        conn: Any,
        dataset_id: str,
        semantics: SourceBarSemantics,
        instrument_id: str | None = None,
        symbol: str | None = None,
    ) -> None:
        """Persist forensic detection and admission records to DuckDB.

        Args:
            conn: DuckDB connection or DuckDBManager instance.
            dataset_id: Canonical dataset identifier.
            semantics: Validated SourceBarSemantics instance.
            instrument_id: Optional instrument identifier.
            symbol: Optional trading symbol.
        """
        if conn is None:
            raise ValueError("Database connection or manager instance must not be None.")
        raw_conn = getattr(conn, "conn", conn)
        if raw_conn is None or not hasattr(raw_conn, "execute"):
            raise ValueError("Resolved database connection must support .execute().")
        target_inst = instrument_id or (semantics.evidence_reports[0].instrument_id if semantics.evidence_reports else symbol or "UNKNOWN")

        now_str = datetime.now(timezone.utc).isoformat()



        # 1. Persist action-level boundary detections
        for r in semantics.evidence_reports:
            det_id = f"det_{uuid.uuid4().hex[:12]}"
            raw_conn.execute(
                """
                INSERT OR REPLACE INTO source_basis_detections (
                    detection_id, dataset_id, instrument_id, symbol,
                    action_ids, action_types, ex_date, expected_multiplier,
                    pre_close, ex_open, ex_close, observed_ratio,
                    log_distance_raw, log_distance_adjusted, hypothesis_separation,
                    missing_trading_sessions, calendar_gap_days,
                    turnover_ratio, volume_ratio, detection, inferred_basis,
                    evidence_strength, evidence_codes, reasons,
                    policy_version, detector_version, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    det_id,
                    dataset_id,
                    r.instrument_id,
                    r.symbol,
                    ",".join(r.action_ids),
                    ",".join(r.action_types),
                    r.ex_date,
                    r.expected_multiplier,
                    r.pre_close,
                    r.ex_open,
                    r.ex_close,
                    r.observed_ratio,
                    r.log_distance_raw,
                    r.log_distance_adjusted,
                    r.hypothesis_separation,
                    r.missing_trading_sessions,
                    r.calendar_gap_days,
                    r.turnover_ratio,
                    r.volume_ratio,
                    r.detection.value,
                    r.inferred_basis.value,
                    r.evidence_strength,
                    ",".join(c.value for c in r.evidence_codes),
                    "; ".join(r.reasons),
                    semantics.policy_version,
                    "2.0.0",
                    now_str,
                ],
            )

        # 2. Persist dataset-level admission record
        num_raw = sum(1 for r in semantics.evidence_reports if r.detection == SourceBasisDetection.UNADJUSTED)
        num_adj = sum(1 for r in semantics.evidence_reports if r.detection == SourceBasisDetection.SPLIT_ADJUSTED)
        num_amb = sum(1 for r in semantics.evidence_reports if r.detection == SourceBasisDetection.AMBIGUOUS)
        num_ins = sum(1 for r in semantics.evidence_reports if r.detection == SourceBasisDetection.INSUFFICIENT_EVIDENCE)

        adm_id = f"adm_{uuid.uuid4().hex[:12]}"
        raw_conn.execute(
            """
            INSERT OR REPLACE INTO source_semantics_admissions (
                admission_id, dataset_id, instrument_id, provider_name,
                price_adjustment, volume_adjustment, validation_status,
                pre_override_status, override_reason, evidence_strength,
                num_raw, num_adjusted, num_ambiguous, num_insufficient,
                semantics_hash, policy_version, detector_version, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                adm_id,
                dataset_id,
                target_inst,
                semantics.provider_name,
                semantics.price_adjustment.value,
                semantics.volume_adjustment.value,
                semantics.validation_status.value,
                semantics.pre_override_status.value if semantics.pre_override_status else None,
                semantics.override_reason,
                semantics.evidence_strength,
                num_raw,
                num_adj,
                num_amb,
                num_ins,
                semantics.semantics_hash,
                semantics.policy_version,
                "2.0.0",
                now_str,
            ],
        )
