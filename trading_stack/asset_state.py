"""Causal, deterministic per-asset state snapshots for Phase 2.5."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Sequence

import numpy as np
import pandas as pd

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from trading_stack.market_regime import MarketContextType


class AssetBehaviorCluster(str, Enum):
    """Interpretable Phase 2.5 stock behavior groups."""

    HIGH_BETA_TRENDING = "HIGH_BETA_TRENDING"
    LOW_VOL_TRENDING = "LOW_VOL_TRENDING"
    HIGH_VOL_MEAN_REVERTING = "HIGH_VOL_MEAN_REVERTING"
    LIQUID_LARGE_CAP = "LIQUID_LARGE_CAP"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    MIXED_UNCLASSIFIED = "MIXED_UNCLASSIFIED"


class AssetEligibility(str, Enum):
    """Whether an asset has sufficient evidence for future selection."""

    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class EligibilityReason(str, Enum):
    """Ordered, deterministic fail-closed eligibility reasons."""

    DATA_INTEGRITY_FAILURE = "DATA_INTEGRITY_FAILURE"
    UNCERTIFIED_DATA = "UNCERTIFIED_DATA"
    MISSING_PIT_EVIDENCE = "MISSING_PIT_EVIDENCE"
    MISSING_CAUSAL_BARS = "MISSING_CAUSAL_BARS"
    MISSING_BENCHMARK_EVIDENCE = "MISSING_BENCHMARK_EVIDENCE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INVALID_PRICE = "INVALID_PRICE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"


@dataclass(frozen=True)
class AssetStatePolicy:
    """Complete versioned policy for feature normalization and classification."""

    policy_version: str = "2.5.0"
    minimum_history_sessions: int = 121
    momentum_windows: tuple[int, int, int] = (20, 60, 120)
    momentum_weights: tuple[float, float, float] = (0.25, 0.35, 0.40)
    momentum_targets: tuple[float, float, float] = (0.10, 0.20, 0.30)
    trend_window: int = 60
    trend_annualized_target: float = 0.30
    volatility_window: int = 20
    volatility_low: float = 0.15
    volatility_high: float = 0.45
    atr_window: int = 14
    normalized_atr_low: float = 0.015
    normalized_atr_high: float = 0.060
    beta_window: int = 60
    relative_strength_window: int = 60
    relative_strength_target: float = 0.15
    liquidity_window: int = 20
    minimum_median_traded_value: float = 50_000_000.0
    full_liquidity_traded_value: float = 500_000_000.0
    volume_recent_window: int = 5
    volume_baseline_window: int = 20
    gap_window: int = 60
    gap_return_threshold: float = 0.02
    gap_frequency_target: float = 0.20
    mean_reversion_window: int = 60
    high_beta_threshold: float = 1.20
    high_beta_trend_threshold: float = 0.50
    high_beta_momentum_threshold: float = 0.40
    high_beta_persistence_threshold: float = 0.60
    low_volatility_score_threshold: float = 0.35
    low_vol_trend_threshold: float = 0.40
    low_vol_momentum_threshold: float = 0.30
    low_vol_persistence_threshold: float = 0.55
    high_volatility_score_threshold: float = 0.65
    mean_reversion_score_threshold: float = 0.35
    mean_reversion_max_persistence: float = 0.45
    cluster_rule_order: tuple[str, ...] = (
        AssetBehaviorCluster.LOW_LIQUIDITY.value,
        AssetBehaviorCluster.HIGH_BETA_TRENDING.value,
        AssetBehaviorCluster.LOW_VOL_TRENDING.value,
        AssetBehaviorCluster.HIGH_VOL_MEAN_REVERTING.value,
        AssetBehaviorCluster.LIQUID_LARGE_CAP.value,
        AssetBehaviorCluster.MIXED_UNCLASSIFIED.value,
    )

    def __post_init__(self) -> None:
        if self.minimum_history_sessions < 121:
            raise ValueError("minimum_history_sessions must support 120-session momentum")
        if len(self.momentum_windows) != 3 or len(self.momentum_weights) != 3:
            raise ValueError("momentum windows and weights must each contain three values")
        if len(self.momentum_targets) != 3 or not np.isclose(sum(self.momentum_weights), 1.0):
            raise ValueError("momentum targets must contain three values and weights must sum to one")
        if self.minimum_median_traded_value <= 0:
            raise ValueError("minimum_median_traded_value must be positive")
        if self.full_liquidity_traded_value < self.minimum_median_traded_value:
            raise ValueError("full liquidity target must not be below the eligibility minimum")
        if self.cluster_rule_order != tuple(cluster.value for cluster in (
            AssetBehaviorCluster.LOW_LIQUIDITY,
            AssetBehaviorCluster.HIGH_BETA_TRENDING,
            AssetBehaviorCluster.LOW_VOL_TRENDING,
            AssetBehaviorCluster.HIGH_VOL_MEAN_REVERTING,
            AssetBehaviorCluster.LIQUID_LARGE_CAP,
            AssetBehaviorCluster.MIXED_UNCLASSIFIED,
        )):
            raise ValueError("cluster_rule_order must retain the Phase 2.5 precedence contract")

    def to_dict(self) -> dict[str, Any]:
        return _canonical_value(asdict(self))

    def compute_hash(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class CertifiedBarEvidence:
    """Provenance returned by the existing certified causal bar loader."""

    dataset_id: str | None
    content_hash: str | None
    certification_id: str | None
    timeframe: str | None
    dataset_available_at: str | None
    last_bar_timestamp: str | None
    last_bar_available_at: str | None
    cutoff_applied: str
    integrity_failure: bool = False
    integrity_failure_reason: str | None = None

    @property
    def is_certified(self) -> bool:
        return bool(
            self.dataset_id
            and self.content_hash
            and self.certification_id
            and self.timeframe
            and self.dataset_available_at
            and self.last_bar_timestamp
            and self.last_bar_available_at
        )

    def is_causal(self, decision_time: datetime) -> bool:
        if not self.is_certified:
            return False
        try:
            timestamps = (
                _aware_datetime(str(self.dataset_available_at), "dataset_available_at"),
                _aware_datetime(str(self.last_bar_timestamp), "last_bar_timestamp"),
                _aware_datetime(str(self.last_bar_available_at), "last_bar_available_at"),
            )
        except (TypeError, ValueError):
            return False
        return all(timestamp <= decision_time for timestamp in timestamps)

    def to_dict(self) -> dict[str, Any]:
        return _canonical_value(asdict(self))

    @classmethod
    def from_loader_result(cls, result: dict[str, Any]) -> "CertifiedBarEvidence":
        return cls(
            dataset_id=_optional_str(result.get("dataset_id")),
            content_hash=_optional_str(result.get("content_hash")),
            certification_id=_optional_str(result.get("certification_id")),
            timeframe=_optional_str(result.get("timeframe")),
            dataset_available_at=_optional_str(result.get("dataset_available_at")),
            last_bar_timestamp=_optional_str(result.get("last_bar_timestamp")),
            last_bar_available_at=_optional_str(result.get("last_bar_available_at")),
            cutoff_applied=str(result.get("cutoff_applied") or ""),
            integrity_failure=bool(result.get("integrity_failure", False)),
            integrity_failure_reason=_optional_str(result.get("integrity_failure_reason")),
        )


@dataclass(frozen=True)
class PITMetadataEvidence:
    """Optional, authoritative point-in-time descriptive metadata."""

    metadata_id: str
    field: str
    value: str
    content_hash: str
    certification_id: str
    effective_from: date
    effective_until: date | None
    known_at: datetime

    def is_causal(self, as_of: date, decision_time: datetime, expected_field: str) -> bool:
        return bool(
            self.field == expected_field
            and self.metadata_id
            and self.content_hash
            and self.certification_id
            and self.known_at.tzinfo is not None
            and self.known_at <= decision_time
            and self.effective_from <= as_of
            and (self.effective_until is None or self.effective_until > as_of)
        )

    def to_dict(self) -> dict[str, Any]:
        return _canonical_value(asdict(self))


@dataclass(frozen=True)
class PITEarningsEventEvidence:
    """Optional earnings event that was publicly known by the decision time."""

    event_id: str
    event_at: datetime
    known_at: datetime
    content_hash: str
    certification_id: str

    def is_causal(self, decision_time: datetime) -> bool:
        return bool(
            self.event_id
            and self.content_hash
            and self.certification_id
            and self.event_at.tzinfo is not None
            and self.known_at.tzinfo is not None
            and self.known_at <= decision_time
        )

    def to_dict(self) -> dict[str, Any]:
        return _canonical_value(asdict(self))


@dataclass(frozen=True)
class AssetStateFeatures:
    """Raw causal asset evidence and normalized interpretable scores."""

    trend_strength: float | None = None
    momentum_20: float | None = None
    momentum_60: float | None = None
    momentum_120: float | None = None
    relative_strength: float | None = None
    realized_volatility: float | None = None
    atr: float | None = None
    normalized_atr: float | None = None
    beta: float | None = None
    latest_traded_value: float | None = None
    median_traded_value_20: float | None = None
    total_turnover_20: float | None = None
    volume_behavior: float | None = None
    gap_frequency: float | None = None
    mean_reversion_tendency: float | None = None
    trend_persistence: float | None = None
    trend_score: float | None = None
    momentum_score: float | None = None
    volatility_score: float | None = None
    liquidity_score: float | None = None
    gap_risk_score: float | None = None
    mean_reversion_score: float | None = None
    relative_strength_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _canonical_value(asdict(self))


@dataclass(frozen=True)
class AssetStateSnapshot:
    """Immutable, reproducible Phase 2.5 stock state."""

    asset_state_id: str
    symbol: str
    exchange: str
    context_type: MarketContextType
    as_of: str
    decision_time: str
    trend_score: float | None
    momentum_score: float | None
    volatility_score: float | None
    liquidity_score: float | None
    gap_risk_score: float | None
    mean_reversion_score: float | None
    relative_strength_score: float | None
    beta: float | None
    atr: float | None
    normalized_atr: float | None
    sector: str | None
    market_cap_bucket: str | None
    earnings_proximity: int | None
    behavior_cluster: AssetBehaviorCluster
    cluster_confidence: float
    eligibility: AssetEligibility
    eligibility_reasons: tuple[str, ...]
    features: AssetStateFeatures
    input_evidence: dict[str, Any]
    input_evidence_hash: str
    input_hashes: dict[str, str]
    model_version: str
    policy_version: str
    policy_hash: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_state_id": self.asset_state_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "context_type": self.context_type.value,
            "as_of": self.as_of,
            "decision_time": self.decision_time,
            "trend_score": self.trend_score,
            "momentum_score": self.momentum_score,
            "volatility_score": self.volatility_score,
            "liquidity_score": self.liquidity_score,
            "gap_risk_score": self.gap_risk_score,
            "mean_reversion_score": self.mean_reversion_score,
            "relative_strength_score": self.relative_strength_score,
            "beta": self.beta,
            "atr": self.atr,
            "normalized_atr": self.normalized_atr,
            "sector": self.sector,
            "market_cap_bucket": self.market_cap_bucket,
            "earnings_proximity": self.earnings_proximity,
            "behavior_cluster": self.behavior_cluster.value,
            "cluster_confidence": self.cluster_confidence,
            "eligibility": self.eligibility.value,
            "eligibility_reasons_json": _canonical_json(self.eligibility_reasons),
            "features_json": _canonical_json(self.features.to_dict()),
            "input_evidence_manifest_json": _canonical_json(self.input_evidence),
            "input_evidence_hash": self.input_evidence_hash,
            "input_hashes_json": _canonical_json(self.input_hashes),
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "created_at": self.created_at,
        }


class AssetStateEngine:
    """Pure deterministic calculation over already admitted evidence."""

    def __init__(
        self,
        policy: AssetStatePolicy | None = None,
        *,
        model_version: str = "asset-state-v1",
    ) -> None:
        self.policy = policy or AssetStatePolicy()
        self.model_version = model_version

    def evaluate(
        self,
        *,
        symbol: str,
        exchange: str,
        universe_name: str,
        benchmark_symbol: str,
        as_of: date | str,
        decision_time: datetime | str,
        context_type: MarketContextType | str,
        asset_bars: pd.DataFrame,
        benchmark_bars: pd.DataFrame,
        asset_evidence: CertifiedBarEvidence,
        benchmark_evidence: CertifiedBarEvidence,
        constituent: PointInTimeConstituent | None,
        sector_metadata: PITMetadataEvidence | None = None,
        market_cap_metadata: PITMetadataEvidence | None = None,
        earnings_events: Sequence[PITEarningsEventEvidence] | None = None,
        policy: AssetStatePolicy | None = None,
        model_version: str | None = None,
    ) -> AssetStateSnapshot:
        active_policy = policy or self.policy
        active_model = model_version or self.model_version
        decision = _aware_datetime(decision_time, "decision_time")
        snapshot_date = pd.Timestamp(as_of).date()
        context = context_type if isinstance(context_type, MarketContextType) else MarketContextType(str(context_type))

        causal_asset = self._causal_bars(asset_bars, snapshot_date, decision, context)
        causal_benchmark = self._causal_bars(benchmark_bars, snapshot_date, decision, context)
        features = self._calculate_features(causal_asset, causal_benchmark, active_policy)

        sector = self._metadata_value(sector_metadata, "sector", snapshot_date, decision)
        market_cap = self._metadata_value(
            market_cap_metadata, "market_cap_bucket", snapshot_date, decision
        )
        causal_events = sorted(
            (event for event in (earnings_events or ()) if event.is_causal(decision)),
            key=lambda event: (abs((event.event_at.date() - snapshot_date).days), event.event_id),
        )
        earnings_proximity = (
            (causal_events[0].event_at.date() - snapshot_date).days if causal_events else None
        )

        cluster, cluster_confidence, cluster_detail = self.classify(features, market_cap, active_policy)
        reasons = self._eligibility_reasons(
            causal_asset,
            causal_benchmark,
            features,
            asset_evidence,
            benchmark_evidence,
            constituent,
            active_policy,
            snapshot_date,
            decision,
        )
        eligibility = AssetEligibility.ELIGIBLE if not reasons else AssetEligibility.INELIGIBLE

        asset_slice_hash = _bars_hash(causal_asset)
        benchmark_slice_hash = _bars_hash(causal_benchmark)
        metadata_manifest = {
            "sector": sector_metadata.to_dict() if sector is not None and sector_metadata else None,
            "market_cap_bucket": (
                market_cap_metadata.to_dict()
                if market_cap is not None and market_cap_metadata
                else None
            ),
            "earnings_events": [event.to_dict() for event in causal_events],
        }
        membership = _constituent_manifest(constituent)
        evidence_manifest = _canonical_value(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "universe_name": universe_name.upper(),
                "benchmark_symbol": benchmark_symbol.upper(),
                "context_type": context.value,
                "as_of": snapshot_date,
                "decision_time": decision,
                "stock": {
                    "provenance": asset_evidence.to_dict(),
                    "causal_bar_count": len(causal_asset),
                    "causal_bars_hash": asset_slice_hash,
                },
                "benchmark": {
                    "provenance": benchmark_evidence.to_dict(),
                    "causal_bar_count": len(causal_benchmark),
                    "causal_bars_hash": benchmark_slice_hash,
                },
                "pit_membership": membership,
                "metadata": metadata_manifest,
                "features": features.to_dict(),
                "cluster_evidence": cluster_detail,
                "eligibility": eligibility.value,
                "eligibility_reasons": [reason.value for reason in reasons],
                "model_version": active_model,
                "policy": active_policy.to_dict(),
            }
        )
        evidence_hash = _sha256_json(evidence_manifest)
        policy_hash = active_policy.compute_hash()
        identity = {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "context_type": context.value,
            "as_of": snapshot_date.isoformat(),
            "decision_time": _utc_iso(decision),
            "input_evidence_hash": evidence_hash,
            "model_version": active_model,
            "policy_version": active_policy.policy_version,
            "policy_hash": policy_hash,
        }
        asset_state_id = _sha256_json(identity)
        input_hashes = {
            "asset_causal_bars": asset_slice_hash,
            "benchmark_causal_bars": benchmark_slice_hash,
            "asset_dataset": asset_evidence.content_hash or "",
            "benchmark_dataset": benchmark_evidence.content_hash or "",
        }
        if sector is not None and sector_metadata:
            input_hashes["sector_metadata"] = sector_metadata.content_hash
        if market_cap is not None and market_cap_metadata:
            input_hashes["market_cap_metadata"] = market_cap_metadata.content_hash
        if causal_events:
            input_hashes["earnings_events"] = _sha256_json(
                [event.to_dict() for event in causal_events]
            )

        return AssetStateSnapshot(
            asset_state_id=asset_state_id,
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            context_type=context,
            as_of=snapshot_date.isoformat(),
            decision_time=_utc_iso(decision),
            trend_score=features.trend_score,
            momentum_score=features.momentum_score,
            volatility_score=features.volatility_score,
            liquidity_score=features.liquidity_score,
            gap_risk_score=features.gap_risk_score,
            mean_reversion_score=features.mean_reversion_score,
            relative_strength_score=features.relative_strength_score,
            beta=features.beta,
            atr=features.atr,
            normalized_atr=features.normalized_atr,
            sector=sector,
            market_cap_bucket=market_cap,
            earnings_proximity=earnings_proximity,
            behavior_cluster=cluster,
            cluster_confidence=cluster_confidence,
            eligibility=eligibility,
            eligibility_reasons=tuple(reason.value for reason in reasons),
            features=features,
            input_evidence=evidence_manifest,
            input_evidence_hash=evidence_hash,
            input_hashes=input_hashes,
            model_version=active_model,
            policy_version=active_policy.policy_version,
            policy_hash=policy_hash,
        )

    def classify(
        self,
        features: AssetStateFeatures,
        market_cap_bucket: str | None = None,
        policy: AssetStatePolicy | None = None,
    ) -> tuple[AssetBehaviorCluster, float, dict[str, Any]]:
        """Apply the fixed Phase 2.5 rule order and return auditable support."""
        active = policy or self.policy
        coverage = sum(value is not None for value in features.to_dict().values()) / len(
            features.to_dict()
        )
        selected = AssetBehaviorCluster.MIXED_UNCLASSIFIED
        support = 0.0

        if (
            features.median_traded_value_20 is not None
            and features.median_traded_value_20 < active.minimum_median_traded_value
        ):
            selected = AssetBehaviorCluster.LOW_LIQUIDITY
            support = 1.0 - _clip01(
                features.median_traded_value_20 / active.minimum_median_traded_value
            )
        elif _all_available(
            features.beta,
            features.trend_score,
            features.momentum_score,
            features.trend_persistence,
        ) and (
            features.beta >= active.high_beta_threshold  # type: ignore[operator]
            and features.trend_score >= active.high_beta_trend_threshold  # type: ignore[operator]
            and features.momentum_score >= active.high_beta_momentum_threshold  # type: ignore[operator]
            and features.trend_persistence >= active.high_beta_persistence_threshold  # type: ignore[operator]
        ):
            selected = AssetBehaviorCluster.HIGH_BETA_TRENDING
            support = min(
                _clip01(features.beta / active.high_beta_threshold),  # type: ignore[operator]
                _positive_support(features.trend_score, active.high_beta_trend_threshold),
                _positive_support(features.momentum_score, active.high_beta_momentum_threshold),
                _positive_support(features.trend_persistence, active.high_beta_persistence_threshold),
            )
        elif _all_available(
            features.volatility_score,
            features.trend_score,
            features.momentum_score,
            features.trend_persistence,
        ) and (
            features.volatility_score <= active.low_volatility_score_threshold  # type: ignore[operator]
            and features.trend_score >= active.low_vol_trend_threshold  # type: ignore[operator]
            and features.momentum_score >= active.low_vol_momentum_threshold  # type: ignore[operator]
            and features.trend_persistence >= active.low_vol_persistence_threshold  # type: ignore[operator]
        ):
            selected = AssetBehaviorCluster.LOW_VOL_TRENDING
            support = min(
                _negative_support(features.volatility_score, active.low_volatility_score_threshold),
                _positive_support(features.trend_score, active.low_vol_trend_threshold),
                _positive_support(features.momentum_score, active.low_vol_momentum_threshold),
                _positive_support(features.trend_persistence, active.low_vol_persistence_threshold),
            )
        elif _all_available(
            features.volatility_score,
            features.mean_reversion_score,
            features.trend_persistence,
        ) and (
            features.volatility_score >= active.high_volatility_score_threshold  # type: ignore[operator]
            and features.mean_reversion_score >= active.mean_reversion_score_threshold  # type: ignore[operator]
            and features.trend_persistence <= active.mean_reversion_max_persistence  # type: ignore[operator]
        ):
            selected = AssetBehaviorCluster.HIGH_VOL_MEAN_REVERTING
            support = min(
                _positive_support(features.volatility_score, active.high_volatility_score_threshold),
                _positive_support(features.mean_reversion_score, active.mean_reversion_score_threshold),
                _negative_support(features.trend_persistence, active.mean_reversion_max_persistence),
            )
        elif (
            market_cap_bucket == "LARGE"
            and features.median_traded_value_20 is not None
            and features.median_traded_value_20 >= active.full_liquidity_traded_value
        ):
            selected = AssetBehaviorCluster.LIQUID_LARGE_CAP
            support = _clip01(
                features.median_traded_value_20 / active.full_liquidity_traded_value
            )
        else:
            support = 1.0

        confidence = round(_clip01(support * coverage), 6)
        return selected, confidence, {
            "selected": selected.value,
            "confidence": confidence,
            "required_feature_coverage": round(coverage, 6),
            "rule_order": list(active.cluster_rule_order),
            "inputs": features.to_dict(),
        }

    def _causal_bars(
        self,
        bars: pd.DataFrame,
        as_of: date,
        decision_time: datetime,
        context: MarketContextType,
    ) -> pd.DataFrame:
        required = {
            "timestamp", "open", "high", "low", "close", "volume", "candle_available_at"
        }
        if bars.empty or not required.issubset(bars.columns):
            return pd.DataFrame(columns=sorted(required))
        frame = bars[list(required)].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame["candle_available_at"] = pd.to_datetime(
            frame["candle_available_at"], utc=True, errors="coerce"
        )
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        decision_utc = pd.Timestamp(decision_time).tz_convert("UTC")
        frame = frame[
            frame["timestamp"].notna()
            & frame["candle_available_at"].notna()
            & (frame["timestamp"] <= decision_utc)
            & (frame["candle_available_at"] <= decision_utc)
        ]
        session_dates = frame["timestamp"].dt.date
        if context is MarketContextType.INTRADAY:
            frame = frame[session_dates < as_of]
        else:
            frame = frame[session_dates <= as_of]
        return frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)

    def _calculate_features(
        self,
        asset: pd.DataFrame,
        benchmark: pd.DataFrame,
        policy: AssetStatePolicy,
    ) -> AssetStateFeatures:
        if asset.empty:
            return AssetStateFeatures()
        close = asset["close"].astype(float)
        volume = asset["volume"].astype(float)
        momenta = [_return_over(close, window) for window in policy.momentum_windows]
        momentum_score = None
        if all(value is not None for value in momenta):
            momentum_score = float(sum(
                weight * _clip_signed(value / target)
                for value, weight, target in zip(
                    momenta, policy.momentum_weights, policy.momentum_targets
                )
                if value is not None
            ))

        trend_strength = None
        trend_persistence = None
        trend_score = None
        if len(close) >= policy.trend_window and (close.iloc[-policy.trend_window:] > 0).all():
            values = np.log(close.iloc[-policy.trend_window:].to_numpy(dtype=float))
            index = np.arange(policy.trend_window, dtype=float)
            slope, intercept = np.polyfit(index, values, 1)
            fitted = intercept + slope * index
            total = float(np.sum((values - values.mean()) ** 2))
            residual = float(np.sum((values - fitted) ** 2))
            r_squared = 1.0 if total == 0.0 else _clip01(1.0 - residual / total)
            annualized_slope = float(np.expm1(slope * 252.0))
            trend_strength = annualized_slope * r_squared
            trend_persistence = r_squared
            trend_score = _clip_signed(trend_strength / policy.trend_annualized_target)

        safe_close = close.where(close > 0)
        returns = np.log(safe_close / safe_close.shift(1)).dropna()
        realized_volatility = None
        if len(returns) >= policy.volatility_window:
            realized_volatility = float(
                returns.iloc[-policy.volatility_window:].std(ddof=1) * np.sqrt(252.0)
            )

        atr = None
        normalized_atr = None
        if len(asset) >= policy.atr_window + 1:
            previous_close = close.shift(1)
            true_range = pd.concat(
                [
                    asset["high"].astype(float) - asset["low"].astype(float),
                    (asset["high"].astype(float) - previous_close).abs(),
                    (asset["low"].astype(float) - previous_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = float(true_range.iloc[-policy.atr_window:].mean())
            if close.iloc[-1] > 0:
                normalized_atr = atr / float(close.iloc[-1])

        volatility_score = None
        if realized_volatility is not None and normalized_atr is not None:
            volatility_score = (
                _range_score(realized_volatility, policy.volatility_low, policy.volatility_high)
                + _range_score(
                    normalized_atr, policy.normalized_atr_low, policy.normalized_atr_high
                )
            ) / 2.0

        aligned = _aligned_returns(asset, benchmark)
        beta = None
        if len(aligned) >= policy.beta_window:
            sample = aligned.iloc[-policy.beta_window:]
            benchmark_variance = float(sample["benchmark"].var(ddof=1))
            if benchmark_variance > 0 and np.isfinite(benchmark_variance):
                beta = float(sample[["asset", "benchmark"]].cov().iloc[0, 1] / benchmark_variance)

        asset_rs = _return_over(close, policy.relative_strength_window)
        benchmark_rs = (
            _return_over(benchmark["close"].astype(float), policy.relative_strength_window)
            if not benchmark.empty
            else None
        )
        relative_strength = (
            asset_rs - benchmark_rs
            if asset_rs is not None and benchmark_rs is not None
            else None
        )
        relative_strength_score = (
            _clip_signed(relative_strength / policy.relative_strength_target)
            if relative_strength is not None
            else None
        )

        traded_value = close * volume
        latest_traded_value = _finite_or_none(traded_value.iloc[-1])
        median_traded_value = None
        total_turnover = None
        liquidity_score = None
        if len(traded_value) >= policy.liquidity_window:
            liquidity_slice = traded_value.iloc[-policy.liquidity_window:]
            median_traded_value = _finite_or_none(liquidity_slice.median())
            total_turnover = _finite_or_none(liquidity_slice.sum())
            if median_traded_value is not None:
                liquidity_score = _clip01(
                    median_traded_value / policy.full_liquidity_traded_value
                )

        volume_behavior = None
        required_volume = policy.volume_recent_window + policy.volume_baseline_window
        if len(volume) >= required_volume:
            recent = float(volume.iloc[-policy.volume_recent_window:].median())
            baseline = float(
                volume.iloc[-required_volume:-policy.volume_recent_window].median()
            )
            if baseline > 0:
                volume_behavior = recent / baseline

        gap_frequency = None
        gap_risk_score = None
        if len(asset) >= policy.gap_window + 1:
            gaps = (asset["open"].astype(float) / close.shift(1) - 1.0).abs().dropna()
            gap_frequency = float(
                (gaps.iloc[-policy.gap_window:] >= policy.gap_return_threshold).mean()
            )
            gap_risk_score = _clip01(gap_frequency / policy.gap_frequency_target)

        mean_reversion = None
        if len(returns) >= policy.mean_reversion_window + 1:
            autocorrelation = returns.iloc[-(policy.mean_reversion_window + 1):].autocorr(lag=1)
            if pd.notna(autocorrelation):
                mean_reversion = _clip01(max(0.0, -float(autocorrelation)))

        return AssetStateFeatures(
            trend_strength=_finite_or_none(trend_strength),
            momentum_20=momenta[0],
            momentum_60=momenta[1],
            momentum_120=momenta[2],
            relative_strength=_finite_or_none(relative_strength),
            realized_volatility=_finite_or_none(realized_volatility),
            atr=_finite_or_none(atr),
            normalized_atr=_finite_or_none(normalized_atr),
            beta=_finite_or_none(beta),
            latest_traded_value=latest_traded_value,
            median_traded_value_20=median_traded_value,
            total_turnover_20=total_turnover,
            volume_behavior=_finite_or_none(volume_behavior),
            gap_frequency=_finite_or_none(gap_frequency),
            mean_reversion_tendency=_finite_or_none(mean_reversion),
            trend_persistence=_finite_or_none(trend_persistence),
            trend_score=_finite_or_none(trend_score),
            momentum_score=_finite_or_none(momentum_score),
            volatility_score=_finite_or_none(volatility_score),
            liquidity_score=_finite_or_none(liquidity_score),
            gap_risk_score=_finite_or_none(gap_risk_score),
            mean_reversion_score=_finite_or_none(mean_reversion),
            relative_strength_score=_finite_or_none(relative_strength_score),
        )

    def _eligibility_reasons(
        self,
        asset: pd.DataFrame,
        benchmark: pd.DataFrame,
        features: AssetStateFeatures,
        asset_evidence: CertifiedBarEvidence,
        benchmark_evidence: CertifiedBarEvidence,
        constituent: PointInTimeConstituent | None,
        policy: AssetStatePolicy,
        as_of: date,
        decision_time: datetime,
    ) -> list[EligibilityReason]:
        observed: set[EligibilityReason] = set()
        if asset_evidence.integrity_failure or benchmark_evidence.integrity_failure:
            observed.add(EligibilityReason.DATA_INTEGRITY_FAILURE)
        if not asset_evidence.is_causal(decision_time) or not benchmark_evidence.is_causal(decision_time):
            observed.add(EligibilityReason.UNCERTIFIED_DATA)
        if not _constituent_is_causal(constituent, as_of, decision_time):
            observed.add(EligibilityReason.MISSING_PIT_EVIDENCE)
        if asset.empty:
            observed.add(EligibilityReason.MISSING_CAUSAL_BARS)
        if benchmark.empty or not benchmark_evidence.is_certified:
            observed.add(EligibilityReason.MISSING_BENCHMARK_EVIDENCE)
        if len(asset) < policy.minimum_history_sessions or len(benchmark) < policy.minimum_history_sessions:
            observed.add(EligibilityReason.INSUFFICIENT_HISTORY)
        if not asset.empty:
            prices = asset[["open", "high", "low", "close"]].tail(
                min(len(asset), policy.minimum_history_sessions)
            )
            if not np.isfinite(prices.to_numpy(dtype=float)).all() or (prices <= 0).any().any():
                observed.add(EligibilityReason.INVALID_PRICE)
        if (
            features.median_traded_value_20 is not None
            and features.median_traded_value_20 < policy.minimum_median_traded_value
        ):
            observed.add(EligibilityReason.INSUFFICIENT_LIQUIDITY)
        return [reason for reason in EligibilityReason if reason in observed]

    @staticmethod
    def _metadata_value(
        evidence: PITMetadataEvidence | None,
        field_name: str,
        as_of: date,
        decision_time: datetime,
    ) -> str | None:
        if evidence is None or not evidence.is_causal(as_of, decision_time, field_name):
            return None
        return evidence.value


class AssetStateService:
    """Authoritative storage-backed orchestration for a single asset snapshot."""

    def __init__(
        self,
        db: Any,
        *,
        policy: AssetStatePolicy | None = None,
        model_version: str = "asset-state-v1",
    ) -> None:
        self.db = db
        self.engine = AssetStateEngine(policy, model_version=model_version)

    def evaluate(
        self,
        *,
        symbol: str,
        exchange: str,
        universe_name: str,
        benchmark_symbol: str,
        as_of: date | str,
        decision_time: datetime | str,
        context_type: MarketContextType | str,
        sector_metadata: PITMetadataEvidence | None = None,
        market_cap_metadata: PITMetadataEvidence | None = None,
        earnings_events: Sequence[PITEarningsEventEvidence] | None = None,
        persist: bool = False,
    ) -> AssetStateSnapshot:
        decision = _aware_datetime(decision_time, "decision_time")
        snapshot_date = pd.Timestamp(as_of).date()
        context = context_type if isinstance(context_type, MarketContextType) else MarketContextType(str(context_type))
        constituents = PointInTimeUniverseManager.get_constituents(
            getattr(self.db, "conn", self.db),
            universe_name,
            snapshot_date,
            as_of_knowledge=decision,
        )
        constituent = next(
            (
                member
                for member in constituents
                if member.symbol.upper() == symbol.upper()
                and member.exchange.upper() == exchange.upper()
            ),
            None,
        )
        loader_arguments = {
            "timeframe": "1d",
            "decision_time": decision.isoformat(),
            "exchange": exchange,
            "intraday": False,
            "context_type": context.value,
        }
        asset_result = self.db.load_regime_bars(symbol=symbol, **loader_arguments)
        benchmark_result = self.db.load_regime_bars(
            symbol=benchmark_symbol, **loader_arguments
        )
        snapshot = self.engine.evaluate(
            symbol=symbol,
            exchange=exchange,
            universe_name=universe_name,
            benchmark_symbol=benchmark_symbol,
            as_of=snapshot_date,
            decision_time=decision,
            context_type=context,
            asset_bars=asset_result.get("bars", pd.DataFrame()),
            benchmark_bars=benchmark_result.get("bars", pd.DataFrame()),
            asset_evidence=CertifiedBarEvidence.from_loader_result(asset_result),
            benchmark_evidence=CertifiedBarEvidence.from_loader_result(benchmark_result),
            constituent=constituent,
            sector_metadata=sector_metadata,
            market_cap_metadata=market_cap_metadata,
            earnings_events=earnings_events,
        )
        if persist:
            self.db.persist_asset_state_snapshot(snapshot)
        return snapshot


def _aligned_returns(asset: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    if asset.empty or benchmark.empty:
        return pd.DataFrame(columns=["asset", "benchmark"])
    asset_values = pd.DataFrame(
        {
            "session": pd.to_datetime(asset["timestamp"], utc=True).dt.date,
            "asset": np.log(
                asset["close"].astype(float).where(asset["close"].astype(float) > 0)
                / asset["close"].astype(float).where(asset["close"].astype(float) > 0).shift(1)
            ),
        }
    )
    benchmark_values = pd.DataFrame(
        {
            "session": pd.to_datetime(benchmark["timestamp"], utc=True).dt.date,
            "benchmark": np.log(
                benchmark["close"].astype(float).where(benchmark["close"].astype(float) > 0)
                / benchmark["close"].astype(float).where(benchmark["close"].astype(float) > 0).shift(1)
            ),
        }
    )
    return asset_values.merge(benchmark_values, on="session", how="inner").dropna()


def _bars_hash(bars: pd.DataFrame) -> str:
    if bars.empty:
        return _sha256_json([])
    rows = []
    for row in bars.sort_values("timestamp").itertuples(index=False):
        values = row._asdict()
        rows.append({key: _canonical_value(value) for key, value in sorted(values.items())})
    return _sha256_json(rows)


def _constituent_manifest(constituent: PointInTimeConstituent | None) -> dict[str, Any] | None:
    if constituent is None:
        return None
    return _canonical_value(
        {
            "universe_name": constituent.universe_name,
            "instrument_id": constituent.instrument_id,
            "symbol": constituent.symbol,
            "token": constituent.token,
            "exchange": constituent.exchange,
            "effective_from": constituent.effective_from,
            "effective_until": constituent.effective_until,
            "known_from": constituent.known_from,
            "known_at": constituent.known_at,
            "weight": constituent.weight,
            "inclusion_reason": constituent.inclusion_reason,
            "exclusion_reason": constituent.exclusion_reason,
        }
    )


def _constituent_is_causal(
    constituent: PointInTimeConstituent | None,
    as_of: date,
    decision_time: datetime,
) -> bool:
    if constituent is None or constituent.known_from is None:
        return False
    if constituent.effective_from > as_of:
        return False
    if constituent.effective_until is not None and constituent.effective_until <= as_of:
        return False
    if constituent.known_from < decision_time.date():
        return True
    return bool(
        constituent.known_from == decision_time.date()
        and constituent.known_at is not None
        and constituent.known_at.tzinfo is not None
        and constituent.known_at <= decision_time
    )


def _return_over(values: pd.Series, window: int) -> float | None:
    if len(values) <= window:
        return None
    start = float(values.iloc[-window - 1])
    end = float(values.iloc[-1])
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return None
    return _finite_or_none(end / start - 1.0)


def _range_score(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("score range high must exceed low")
    return _clip01((value - low) / (high - low))


def _positive_support(value: float | None, threshold: float) -> float:
    if value is None:
        return 0.0
    if threshold == 0:
        return 1.0 if value >= 0 else 0.0
    return _clip01(value / threshold)


def _negative_support(value: float | None, threshold: float) -> float:
    if value is None:
        return 0.0
    if threshold >= 1.0:
        return 1.0
    return _clip01((1.0 - value) / (1.0 - threshold))


def _all_available(*values: float | None) -> bool:
    return all(value is not None and np.isfinite(value) for value in values)


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _clip_signed(value: float) -> float:
    return float(np.clip(value, -1.0, 1.0))


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _aware_datetime(value: datetime | str, field_name: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return timestamp.to_pydatetime()


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _optional_str(value: Any) -> str | None:
    return None if value is None or str(value) == "" else str(value)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical datetime values must be timezone-aware")
        return _utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        return value.tz_convert("UTC").isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else round(float(value), 12)
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "AssetBehaviorCluster",
    "AssetEligibility",
    "AssetStateEngine",
    "AssetStateFeatures",
    "AssetStatePolicy",
    "AssetStateService",
    "AssetStateSnapshot",
    "CertifiedBarEvidence",
    "EligibilityReason",
    "PITEarningsEventEvidence",
    "PITMetadataEvidence",
]
