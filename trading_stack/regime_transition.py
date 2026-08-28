"""Deterministic Phase 2.4 operational regime and risk-state transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from typing import Any
import uuid

from trading_stack.market_regime import MarketContextType, MarketRegimeSnapshot, RawMarketRegime


class OperationalMarketRegime(str, Enum):
    """Operational taxonomy; insufficient raw evidence never becomes operational."""

    BULL_LOW_VOL = "BULL_LOW_VOL"
    BULL_HIGH_VOL = "BULL_HIGH_VOL"
    SIDEWAYS_LOW_VOL = "SIDEWAYS_LOW_VOL"
    SIDEWAYS_HIGH_VOL = "SIDEWAYS_HIGH_VOL"
    BEAR_HIGH_VOL = "BEAR_HIGH_VOL"
    RECOVERY = "RECOVERY"


class OperationalRiskState(str, Enum):
    """Risk posture kept separate from the market-regime taxonomy."""

    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    STRESS = "STRESS"


class TransitionDecision(str, Enum):
    """Auditable state-machine decisions."""

    INITIALIZED = "INITIALIZED"
    HELD = "HELD"
    PENDING_STARTED = "PENDING_STARTED"
    PENDING_ADVANCED = "PENDING_ADVANCED"
    PENDING_RESTARTED = "PENDING_RESTARTED"
    CANDIDATE_CANCELLED = "CANDIDATE_CANCELLED"
    TRANSITIONED = "TRANSITIONED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"


class RiskDecision(str, Enum):
    """Independent risk-state decisions."""

    DISABLED = "DISABLED"
    HELD = "HELD"
    ESCALATED = "ESCALATED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"


@dataclass(frozen=True)
class StressThresholds:
    """Operator-supplied positive-severity thresholds for caution and stress."""

    benchmark_loss_caution: float | None = None
    benchmark_loss_stress: float | None = None
    volatility_shock_caution: float | None = None
    volatility_shock_stress: float | None = None
    extreme_gap_caution: float | None = None
    extreme_gap_stress: float | None = None
    liquidity_collapse_caution: float | None = None
    liquidity_collapse_stress: float | None = None
    integrity_failure_state: OperationalRiskState = OperationalRiskState.STRESS

    def __post_init__(self) -> None:
        pairs = (
            (self.benchmark_loss_caution, self.benchmark_loss_stress),
            (self.volatility_shock_caution, self.volatility_shock_stress),
            (self.extreme_gap_caution, self.extreme_gap_stress),
            (self.liquidity_collapse_caution, self.liquidity_collapse_stress),
        )
        if not any(value is not None for pair in pairs for value in pair):
            raise ValueError("stress thresholds must configure at least one numeric trigger")
        for caution, stress in pairs:
            if caution is not None and caution < 0 or stress is not None and stress < 0:
                raise ValueError("stress thresholds must be non-negative")
            if caution is not None and stress is not None and stress < caution:
                raise ValueError("stress threshold cannot be below caution threshold")

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["integrity_failure_state"] = self.integrity_failure_state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StressThresholds:
        values = dict(data)
        values["integrity_failure_state"] = OperationalRiskState(
            values.get("integrity_failure_state", OperationalRiskState.STRESS.value)
        )
        return cls(**values)


@dataclass(frozen=True)
class RegimeTransitionPolicy:
    """Versioned hysteresis and emergency-risk policy."""

    policy_version: str = "2.4.0"
    minimum_confidence: float = 0.70
    minimum_dwell_observations: int = 3
    transition_buffer: float = 0.05
    maximum_pending_duration: timedelta = timedelta(days=7)
    stress_override_enabled: bool = False
    stress_thresholds: StressThresholds | None = None
    stress_release_dwell: int = 3

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("policy_version is required")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if not 0 <= self.transition_buffer <= 1:
            raise ValueError("transition_buffer must be between 0 and 1")
        if self.minimum_confidence + self.transition_buffer > 1:
            raise ValueError("minimum_confidence plus transition_buffer cannot exceed 1")
        if self.minimum_dwell_observations < 1:
            raise ValueError("minimum_dwell_observations must be positive")
        if self.maximum_pending_duration <= timedelta(0):
            raise ValueError("maximum_pending_duration must be positive")
        if self.stress_release_dwell < 1:
            raise ValueError("stress_release_dwell must be positive")
        if self.stress_override_enabled and self.stress_thresholds is None:
            raise ValueError("enabled stress override requires explicit stress_thresholds")

    @property
    def required_transition_confidence(self) -> float:
        return self.minimum_confidence + self.transition_buffer

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "minimum_confidence": self.minimum_confidence,
            "minimum_dwell_observations": self.minimum_dwell_observations,
            "transition_buffer": self.transition_buffer,
            "maximum_pending_duration_seconds": int(self.maximum_pending_duration.total_seconds()),
            "stress_override_enabled": self.stress_override_enabled,
            "stress_thresholds": self.stress_thresholds.to_dict() if self.stress_thresholds else None,
            "stress_release_dwell": self.stress_release_dwell,
        }

    def compute_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, context_type: MarketContextType) -> RegimeTransitionPolicy:
        values = dict(data or {})
        default_seconds = 7 * 24 * 60 * 60 if context_type == MarketContextType.EOD else 60 * 60
        duration = timedelta(seconds=int(values.pop("maximum_pending_duration_seconds", default_seconds)))
        thresholds_data = values.pop("stress_thresholds", None)
        thresholds = StressThresholds.from_dict(thresholds_data) if thresholds_data else None
        return cls(maximum_pending_duration=duration, stress_thresholds=thresholds, **values)

    @classmethod
    def from_config(cls, data: dict[str, Any] | None, *, context_type: MarketContextType) -> RegimeTransitionPolicy:
        """Build a context policy from shared settings plus its context override."""
        values = dict(data or {})
        contexts = values.pop("contexts", {}) or {}
        context_values = contexts.get(context_type.value, {}) or {}
        if not isinstance(context_values, dict):
            raise ValueError(f"regime transition context config must be a mapping: {context_type.value}")
        values.update(context_values)
        return cls.from_dict(values, context_type=context_type)


def _aware_datetime(value: datetime | str, name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class StressEvidence:
    """Causal stress observations expressed as positive severities."""

    observed_at: datetime | str
    benchmark_loss: float | None = None
    volatility_shock: float | None = None
    extreme_gap: float | None = None
    liquidity_collapse: float | None = None
    market_data_integrity_failure: bool = False

    def __post_init__(self) -> None:
        _aware_datetime(self.observed_at, "observed_at")
        for name in ("benchmark_loss", "volatility_shock", "extreme_gap", "liquidity_collapse"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be a non-negative severity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": _aware_datetime(self.observed_at, "observed_at").isoformat(),
            "benchmark_loss": self.benchmark_loss,
            "volatility_shock": self.volatility_shock,
            "extreme_gap": self.extreme_gap,
            "liquidity_collapse": self.liquidity_collapse,
            "market_data_integrity_failure": self.market_data_integrity_failure,
        }

    def compute_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegimeTransitionState:
    market: str
    benchmark: str
    context_type: MarketContextType
    operational_regime: OperationalMarketRegime | None = None
    pending_candidate_regime: OperationalMarketRegime | None = None
    candidate_started_at: datetime | None = None
    candidate_observations: int = 0
    candidate_confidence: float | None = None
    last_raw_regime_id: str | None = None
    last_decision_time: datetime | None = None
    policy_version: str = ""
    policy_hash: str = ""
    revision: int = 0


@dataclass(frozen=True)
class RiskTransitionState:
    market: str
    benchmark: str
    context_type: MarketContextType
    risk_state: OperationalRiskState = OperationalRiskState.NORMAL
    release_candidate_state: OperationalRiskState | None = None
    release_started_at: datetime | None = None
    release_observations: int = 0
    last_stress_evidence_hash: str | None = None
    last_decision_time: datetime | None = None
    policy_version: str = ""
    policy_hash: str = ""
    revision: int = 0


@dataclass(frozen=True)
class RegimeTransitionEvent:
    transition_id: str
    previous_operational_regime: OperationalMarketRegime | None
    raw_candidate_regime: RawMarketRegime
    candidate_started_at: datetime | None
    candidate_observations: int
    candidate_confidence: float
    decision: TransitionDecision
    reason: str
    operational_regime_after: OperationalMarketRegime | None


@dataclass(frozen=True)
class RiskTransitionEvent:
    risk_transition_id: str
    previous_risk_state: OperationalRiskState
    stress_evidence: StressEvidence | None
    decision: RiskDecision
    reason: str
    release_candidate_state: OperationalRiskState | None
    release_observations: int
    risk_state_after: OperationalRiskState


@dataclass(frozen=True)
class RegimeTransitionResult:
    state: RegimeTransitionState
    risk_state: RiskTransitionState
    transition_event: RegimeTransitionEvent
    risk_event: RiskTransitionEvent
    policy: RegimeTransitionPolicy
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "operational_regime": self.state.operational_regime.value if self.state.operational_regime else "UNINITIALIZED",
            "hysteresis": {
                "decision": self.transition_event.decision.value,
                "reason": self.transition_event.reason,
                "pending_candidate": (
                    self.state.pending_candidate_regime.value if self.state.pending_candidate_regime else None
                ),
                "candidate_started_at": (
                    self.state.candidate_started_at.isoformat() if self.state.candidate_started_at else None
                ),
                "candidate_observations": self.state.candidate_observations,
                "required_observations": self.policy.minimum_dwell_observations,
                "required_confidence": self.policy.required_transition_confidence,
            },
            "stress_state": {
                "state": self.risk_state.risk_state.value,
                "decision": self.risk_event.decision.value,
                "reason": self.risk_event.reason,
                "release_observations": self.risk_state.release_observations,
            },
            "policy_version": self.policy.policy_version,
            "policy_hash": self.policy.compute_hash(),
            "replayed": self.replayed,
        }


class RegimeTransitionEngine:
    """Pure reducer for operational market-regime and risk-state transitions."""

    NAMESPACE = uuid.UUID("84fa9632-d2d0-4a96-9489-78d6adb374e4")

    def __init__(self, policy: RegimeTransitionPolicy | None = None) -> None:
        self.policy = policy or RegimeTransitionPolicy()

    def evaluate(
        self,
        snapshot: MarketRegimeSnapshot,
        prior_state: RegimeTransitionState | None = None,
        prior_risk_state: RiskTransitionState | None = None,
        stress_evidence: StressEvidence | None = None,
    ) -> RegimeTransitionResult:
        decision_time = _aware_datetime(snapshot.decision_time, "decision_time")
        key = (snapshot.market, snapshot.benchmark, snapshot.context_type)
        state = prior_state or RegimeTransitionState(*key)
        risk_state = prior_risk_state or RiskTransitionState(*key)
        self._validate_state_key(key, state, risk_state)
        policy_hash = self.policy.compute_hash()
        incoming_stress_hash = stress_evidence.compute_hash() if stress_evidence else None
        policy_changed = bool(
            (state.policy_hash and state.policy_hash != policy_hash)
            or (risk_state.policy_hash and risk_state.policy_hash != policy_hash)
        )
        policy_reassessment = state.last_raw_regime_id == snapshot.regime_id and policy_changed
        if (
            state.last_raw_regime_id == snapshot.regime_id
            and state.policy_hash == policy_hash
            and risk_state.policy_hash == policy_hash
        ):
            if incoming_stress_hash != risk_state.last_stress_evidence_hash:
                raise ValueError("conflicting stress evidence for replayed raw snapshot")
            return self._replay_result(snapshot, state, risk_state)
        if stress_evidence and _aware_datetime(stress_evidence.observed_at, "observed_at") > decision_time:
            raise ValueError("stress evidence from the future is not admissible")
        if (
            state.last_decision_time
            and decision_time <= _aware_datetime(state.last_decision_time, "last_decision_time")
            and not policy_reassessment
        ):
            raise ValueError("distinct raw regime observations require strictly increasing decision times")
        if (
            risk_state.last_decision_time
            and decision_time <= _aware_datetime(risk_state.last_decision_time, "risk last_decision_time")
            and not policy_reassessment
        ):
            raise ValueError("distinct risk observations require strictly increasing decision times")
        if policy_changed:
            state = replace(
                state,
                pending_candidate_regime=None,
                candidate_started_at=None,
                candidate_observations=0,
                candidate_confidence=None,
            )
        next_state, decision, reason = self._evaluate_regime(snapshot, state, decision_time, policy_changed)
        next_risk, risk_decision, risk_reason = self._evaluate_risk(
            snapshot, risk_state, stress_evidence, decision_time, policy_changed
        )
        candidate_started_at = next_state.candidate_started_at
        candidate_observations = next_state.candidate_observations
        if decision == TransitionDecision.TRANSITIONED:
            same_candidate = (
                state.pending_candidate_regime is not None
                and state.pending_candidate_regime.value == snapshot.raw_regime.value
            )
            candidate_started_at = state.candidate_started_at if same_candidate else decision_time
            candidate_observations = state.candidate_observations + 1 if same_candidate else 1
        elif decision in {
            TransitionDecision.CANDIDATE_CANCELLED,
            TransitionDecision.LOW_CONFIDENCE,
            TransitionDecision.INSUFFICIENT_CONTEXT,
        }:
            candidate_started_at = state.candidate_started_at
            candidate_observations = state.candidate_observations
        release_candidate = next_risk.release_candidate_state
        release_observations = next_risk.release_observations
        if risk_decision == RiskDecision.RELEASED:
            release_candidate = risk_state.release_candidate_state
            release_observations = risk_state.release_observations + 1
        transition_id = self._event_id("regime", snapshot.regime_id, policy_hash, decision.value)
        risk_id = self._event_id(
            "risk", snapshot.regime_id, policy_hash, stress_evidence.compute_hash() if stress_evidence else "none"
        )
        return RegimeTransitionResult(
            state=next_state,
            risk_state=next_risk,
            transition_event=RegimeTransitionEvent(
                transition_id=transition_id,
                previous_operational_regime=state.operational_regime,
                raw_candidate_regime=snapshot.raw_regime,
                candidate_started_at=candidate_started_at,
                candidate_observations=candidate_observations,
                candidate_confidence=snapshot.confidence,
                decision=decision,
                reason=reason,
                operational_regime_after=next_state.operational_regime,
            ),
            risk_event=RiskTransitionEvent(
                risk_transition_id=risk_id,
                previous_risk_state=risk_state.risk_state,
                stress_evidence=stress_evidence,
                decision=risk_decision,
                reason=risk_reason,
                release_candidate_state=release_candidate,
                release_observations=release_observations,
                risk_state_after=next_risk.risk_state,
            ),
            policy=self.policy,
        )

    def _evaluate_regime(
        self,
        snapshot: MarketRegimeSnapshot,
        state: RegimeTransitionState,
        decision_time: datetime,
        policy_changed: bool,
    ) -> tuple[RegimeTransitionState, TransitionDecision, str]:
        def advance(**changes: Any) -> RegimeTransitionState:
            return replace(
                state,
                last_raw_regime_id=snapshot.regime_id,
                last_decision_time=decision_time,
                policy_version=self.policy.policy_version,
                policy_hash=self.policy.compute_hash(),
                revision=state.revision + 1,
                **changes,
            )

        if snapshot.raw_regime == RawMarketRegime.INSUFFICIENT_CONTEXT:
            next_state = advance(
                pending_candidate_regime=None, candidate_started_at=None,
                candidate_observations=0, candidate_confidence=None,
            )
            return next_state, TransitionDecision.INSUFFICIENT_CONTEXT, "critical raw evidence is insufficient"
        candidate = OperationalMarketRegime(snapshot.raw_regime.value)
        if state.operational_regime is None:
            if snapshot.confidence < self.policy.required_transition_confidence:
                next_state = advance()
                return next_state, TransitionDecision.LOW_CONFIDENCE, "initial candidate is below buffered confidence"
            next_state = advance(operational_regime=candidate)
            return next_state, TransitionDecision.INITIALIZED, "first eligible raw regime initializes operational state"
        if candidate == state.operational_regime:
            cancelled = state.pending_candidate_regime is not None
            next_state = advance(
                pending_candidate_regime=None, candidate_started_at=None,
                candidate_observations=0, candidate_confidence=None,
            )
            decision = TransitionDecision.CANDIDATE_CANCELLED if cancelled else TransitionDecision.HELD
            return next_state, decision, "raw regime matches operational state"
        if snapshot.confidence < self.policy.required_transition_confidence:
            next_state = advance(
                pending_candidate_regime=None, candidate_started_at=None,
                candidate_observations=0, candidate_confidence=None,
            )
            return next_state, TransitionDecision.LOW_CONFIDENCE, "candidate is below buffered confidence"

        same_candidate = state.pending_candidate_regime == candidate
        expired = bool(
            same_candidate and state.candidate_started_at
            and decision_time - _aware_datetime(state.candidate_started_at, "candidate_started_at")
            > self.policy.maximum_pending_duration
        )
        if not same_candidate or expired or policy_changed:
            observations = 1
            started_at = decision_time
            decision = TransitionDecision.PENDING_RESTARTED if expired else TransitionDecision.PENDING_STARTED
            reason = "candidate dwell restarted after maximum duration" if expired else "new candidate started dwell"
        else:
            observations = state.candidate_observations + 1
            started_at = state.candidate_started_at or decision_time
            decision = TransitionDecision.PENDING_ADVANCED
            reason = "candidate advanced consecutive qualifying dwell"
        if observations >= self.policy.minimum_dwell_observations:
            next_state = advance(
                operational_regime=candidate, pending_candidate_regime=None,
                candidate_started_at=None, candidate_observations=0, candidate_confidence=None,
            )
            return next_state, TransitionDecision.TRANSITIONED, "candidate satisfied confirmation dwell"
        next_state = advance(
            pending_candidate_regime=candidate, candidate_started_at=started_at,
            candidate_observations=observations, candidate_confidence=snapshot.confidence,
        )
        return next_state, decision, reason

    def _evaluate_risk(
        self,
        snapshot: MarketRegimeSnapshot,
        state: RiskTransitionState,
        evidence: StressEvidence | None,
        decision_time: datetime,
        policy_changed: bool,
    ) -> tuple[RiskTransitionState, RiskDecision, str]:
        def advance(**changes: Any) -> RiskTransitionState:
            return replace(
                state,
                last_stress_evidence_hash=evidence.compute_hash() if evidence else None,
                last_decision_time=decision_time,
                policy_version=self.policy.policy_version,
                policy_hash=self.policy.compute_hash(),
                revision=state.revision + 1,
                **changes,
            )

        if not self.policy.stress_override_enabled:
            return advance(
                release_candidate_state=None,
                release_started_at=None, release_observations=0,
            ), RiskDecision.DISABLED, "stress override is disabled; existing risk posture is retained"
        if evidence is None:
            return advance(), RiskDecision.HELD, "no causal stress evidence supplied"

        target = self._stress_target(evidence)
        if self._severity(target) > self._severity(state.risk_state):
            return advance(
                risk_state=target, release_candidate_state=None,
                release_started_at=None, release_observations=0,
            ), RiskDecision.ESCALATED, "stress threshold triggered immediate escalation"
        if target == state.risk_state:
            return advance(
                release_candidate_state=None, release_started_at=None,
                release_observations=0,
            ), RiskDecision.HELD, "stress evidence supports current risk state"

        same_release = state.release_candidate_state == target and not policy_changed
        observations = state.release_observations + 1 if same_release else 1
        started_at = state.release_started_at if same_release else decision_time
        if observations >= self.policy.stress_release_dwell:
            return advance(
                risk_state=target, release_candidate_state=None,
                release_started_at=None, release_observations=0,
            ), RiskDecision.RELEASED, "recovery evidence satisfied release dwell"
        return advance(
            release_candidate_state=target, release_started_at=started_at,
            release_observations=observations,
        ), RiskDecision.RELEASE_PENDING, "lower risk state awaits recovery dwell"

    def _stress_target(self, evidence: StressEvidence) -> OperationalRiskState:
        thresholds = self.policy.stress_thresholds
        assert thresholds is not None
        target = OperationalRiskState.NORMAL
        if evidence.market_data_integrity_failure:
            target = thresholds.integrity_failure_state
        metrics = (
            (evidence.benchmark_loss, thresholds.benchmark_loss_caution, thresholds.benchmark_loss_stress),
            (evidence.volatility_shock, thresholds.volatility_shock_caution, thresholds.volatility_shock_stress),
            (evidence.extreme_gap, thresholds.extreme_gap_caution, thresholds.extreme_gap_stress),
            (evidence.liquidity_collapse, thresholds.liquidity_collapse_caution, thresholds.liquidity_collapse_stress),
        )
        for value, caution, stress in metrics:
            if value is not None and stress is not None and value >= stress:
                target = OperationalRiskState.STRESS
            elif value is not None and caution is not None and value >= caution and target == OperationalRiskState.NORMAL:
                target = OperationalRiskState.CAUTION
        return target

    @staticmethod
    def _severity(state: OperationalRiskState) -> int:
        return {OperationalRiskState.NORMAL: 0, OperationalRiskState.CAUTION: 1, OperationalRiskState.STRESS: 2}[state]

    @staticmethod
    def _validate_state_key(
        key: tuple[str, str, MarketContextType], state: RegimeTransitionState, risk_state: RiskTransitionState
    ) -> None:
        for record in (state, risk_state):
            if (record.market, record.benchmark, record.context_type) != key:
                raise ValueError("persisted transition state does not match raw snapshot context")

    def _replay_result(
        self, snapshot: MarketRegimeSnapshot, state: RegimeTransitionState, risk_state: RiskTransitionState
    ) -> RegimeTransitionResult:
        policy_hash = self.policy.compute_hash()
        return RegimeTransitionResult(
            state=state,
            risk_state=risk_state,
            transition_event=RegimeTransitionEvent(
                self._event_id("regime", snapshot.regime_id, policy_hash, TransitionDecision.IDEMPOTENT_REPLAY.value),
                state.operational_regime, snapshot.raw_regime, state.candidate_started_at,
                state.candidate_observations, snapshot.confidence, TransitionDecision.IDEMPOTENT_REPLAY,
                "raw snapshot was already processed", state.operational_regime,
            ),
            risk_event=RiskTransitionEvent(
                self._event_id("risk", snapshot.regime_id, policy_hash, "replay"), risk_state.risk_state,
                None, RiskDecision.IDEMPOTENT_REPLAY, "raw snapshot was already processed",
                risk_state.release_candidate_state, risk_state.release_observations, risk_state.risk_state,
            ),
            policy=self.policy,
            replayed=True,
        )

    def _event_id(self, *parts: str) -> str:
        return str(uuid.uuid5(self.NAMESPACE, ":".join(parts)))
