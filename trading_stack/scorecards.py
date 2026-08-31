"""Phase 2.8 eligibility-first, versioned strategy scorecards."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from typing import Any

from trading_stack.conditional_evidence import StrategyConditionalEvidence


ELIGIBLE = "ELIGIBLE"
INELIGIBLE = "INELIGIBLE"


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _bounded(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True)
class ScorecardPolicy:
    version: str = "scorecard-v1"
    minimum_folds: int = 2
    minimum_oos_observations: int = 30
    minimum_oos_trades: int = 10
    minimum_temporal_span_days: int = 30
    max_drawdown: float = 0.25
    min_net_expectancy: float = 0.0
    max_turnover: float = 5.0
    max_correlation: float = 0.75
    min_shrinkage_weight_for_boost: float = 0.35
    max_evidence_age_days: int | None = None
    require_lineage_certified: bool = True
    require_dq_certified: bool = True
    require_causality_certified: bool = True
    require_pit_certified: bool = True
    require_oos_certified: bool = True
    require_cost_stress_pass: bool = True
    require_parameter_robustness_pass: bool = True
    require_capacity_pass: bool = True
    require_paper_evidence: bool = False
    require_zero_reconciliation_drift: bool = True
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "performance": 0.18,
            "downside": 0.14,
            "fold_consistency": 0.12,
            "parameter_robustness": 0.12,
            "cost_robustness": 0.12,
            "breadth": 0.08,
            "paper": 0.06,
            "regime_compatibility": 0.09,
            "asset_compatibility": 0.09,
        }
    )

    def __post_init__(self) -> None:
        if any(value < 0 or value > 1 for value in self.weights.values()):
            raise ValueError("score weights must be bounded in [0, 1]")
        total = sum(self.weights.values())
        if total <= 0 or total > 1.000001:
            raise ValueError("score weights must have positive total <= 1")
        if self.max_drawdown <= 0:
            raise ValueError("max_drawdown must be positive")

    @property
    def policy_hash(self) -> str:
        return _canonical_hash(asdict(self))


@dataclass(frozen=True)
class ScorecardInputs:
    lineage_certified: bool = True
    dq_certified: bool = True
    causality_certified: bool = True
    pit_certified: bool = True
    oos_certified: bool = True
    cost_stress_pass: bool = True
    parameter_robustness_pass: bool = True
    capacity_pass: bool = True
    paper_evidence_pass: bool = True
    zero_reconciliation_drift: bool = True
    fold_consistency: float | None = None
    parameter_robustness_score: float | None = None
    cost_robustness_score: float | None = None
    breadth_score: float = 1.0
    paper_score: float = 0.0
    correlation: float = 0.0
    capacity_score: float = 1.0
    trial_id: str | None = None
    run_id: str | None = None
    robustness_evaluation_id: str | None = None
    dq_certification_id: str | None = None
    pit_certification_id: str | None = None
    cost_model_version: str | None = None
    cost_model_hash: str | None = None
    data_hash: str | None = None
    paper_evidence_id: str | None = None
    rca_evidence_id: str | None = None
    policy_configuration_hash: str | None = None


@dataclass(frozen=True)
class StrategyScorecard:
    scorecard_id: str
    strategy_name: str
    strategy_version: str
    horizon: str
    timeframe: str
    global_evidence_id: str | None
    conditional_evidence_id: str | None
    eligibility_status: str
    rejection_reasons: tuple[str, ...]
    performance_score: float
    downside_score: float
    fold_consistency_score: float
    parameter_robustness_score: float
    cost_robustness_score: float
    breadth_score: float
    paper_score: float
    regime_compatibility_score: float
    asset_compatibility_score: float
    drawdown_penalty: float
    turnover_penalty: float
    correlation_penalty: float
    capacity_penalty: float
    uncertainty_penalty: float
    overall_score: float
    available_at: datetime
    scorecard_version: str
    scorecard_policy_version: str
    scorecard_policy_hash: str
    evidence_hash: str
    evidence_ids: dict[str, str | None]
    explanation: dict[str, Any]

    @property
    def components(self) -> dict[str, float]:
        return {
            "performance": self.performance_score,
            "downside": self.downside_score,
            "fold_consistency": self.fold_consistency_score,
            "parameter_robustness": self.parameter_robustness_score,
            "cost_robustness": self.cost_robustness_score,
            "breadth": self.breadth_score,
            "paper": self.paper_score,
            "regime_compatibility": self.regime_compatibility_score,
            "asset_compatibility": self.asset_compatibility_score,
        }

    @property
    def penalties(self) -> dict[str, float]:
        return {
            "drawdown": self.drawdown_penalty,
            "turnover": self.turnover_penalty,
            "correlation": self.correlation_penalty,
            "capacity": self.capacity_penalty,
            "uncertainty": self.uncertainty_penalty,
        }

    @property
    def is_eligible(self) -> bool:
        return self.eligibility_status == ELIGIBLE


class ScorecardBuilder:
    """Build deterministic scorecards where mandatory eligibility gates precede ranking."""

    def __init__(self, policy: ScorecardPolicy | None = None) -> None:
        self.policy = policy or ScorecardPolicy()

    def build(
        self,
        *,
        evidence: StrategyConditionalEvidence,
        horizon: str,
        inputs: ScorecardInputs | None = None,
        certifications: dict[str, bool] | None = None,
        available_at: datetime | None = None,
        global_evidence_id: str | None = None,
        conditional_evidence_id: str | None = None,
        parameter_robust: bool | None = None,
        cost_stress_pass: bool | None = None,
        capacity_pass: bool | None = None,
        correlation_penalty: float | None = None,
    ) -> StrategyScorecard:
        score_inputs = self._coerce_inputs(
            inputs=inputs,
            certifications=certifications,
            parameter_robust=parameter_robust,
            cost_stress_pass=cost_stress_pass,
            capacity_pass=capacity_pass,
            correlation_penalty=correlation_penalty,
        )
        available = available_at or evidence.available_at
        if available.tzinfo is None:
            raise ValueError("scorecard available_at must be timezone-aware")
        if evidence.available_at > available:
            raise ValueError("scorecard cannot predate its evidence")

        failures = self._eligibility_failures(evidence, score_inputs, available)
        performance_score = _bounded((evidence.expectancy + 0.05) / 0.10)
        downside_score = _bounded(1.0 - abs(min(evidence.max_drawdown, 0.0)) / self.policy.max_drawdown)
        fold_consistency_score = _bounded(
            score_inputs.fold_consistency
            if score_inputs.fold_consistency is not None
            else evidence.fold_count / max(self.policy.minimum_folds, 1)
        )
        parameter_score = _bounded(
            score_inputs.parameter_robustness_score
            if score_inputs.parameter_robustness_score is not None
            else float(score_inputs.parameter_robustness_pass)
        )
        cost_score = _bounded(
            score_inputs.cost_robustness_score
            if score_inputs.cost_robustness_score is not None
            else float(score_inputs.cost_stress_pass)
        )
        conditional_boost = (
            _bounded((evidence.shrunk_metric + 0.05) / 0.10)
            if evidence.shrinkage_weight >= self.policy.min_shrinkage_weight_for_boost
            else 0.5
        )
        regime_score = conditional_boost if evidence.market_regime else 0.5
        asset_score = conditional_boost if evidence.asset_cluster else 0.5
        drawdown_penalty = _bounded(abs(min(evidence.max_drawdown, 0.0)) / self.policy.max_drawdown)
        turnover_penalty = _bounded(evidence.turnover / max(self.policy.max_turnover, 1e-12))
        corr_penalty = _bounded(score_inputs.correlation / max(self.policy.max_correlation, 1e-12))
        capacity_penalty = _bounded(1.0 - score_inputs.capacity_score)
        uncertainty_penalty = _bounded(1.0 - evidence.shrinkage_weight)

        components = {
            "performance": performance_score,
            "downside": downside_score,
            "fold_consistency": fold_consistency_score,
            "parameter_robustness": parameter_score,
            "cost_robustness": cost_score,
            "breadth": _bounded(score_inputs.breadth_score),
            "paper": _bounded(score_inputs.paper_score),
            "regime_compatibility": regime_score,
            "asset_compatibility": asset_score,
        }
        raw_score = sum(components[name] * self.policy.weights[name] for name in self.policy.weights)
        total_penalty = (
            drawdown_penalty + turnover_penalty + corr_penalty + capacity_penalty + uncertainty_penalty
        ) / 5.0
        overall_score = 0.0 if failures else _bounded(raw_score - 0.25 * total_penalty)

        evidence_ids = {
            "trial_id": score_inputs.trial_id,
            "run_id": score_inputs.run_id or evidence.run_id,
            "robustness_evaluation_id": score_inputs.robustness_evaluation_id,
            "phase2_7_evidence_id": evidence.evidence_id,
            "dq_certification_id": score_inputs.dq_certification_id,
            "pit_certification_id": score_inputs.pit_certification_id,
            "cost_model_version": score_inputs.cost_model_version,
            "cost_model_hash": score_inputs.cost_model_hash,
            "data_hash": score_inputs.data_hash,
            "paper_evidence_id": score_inputs.paper_evidence_id,
            "rca_evidence_id": score_inputs.rca_evidence_id,
            "policy_configuration_hash": score_inputs.policy_configuration_hash,
        }
        explanation = {
            "eligible": not failures,
            "rejection_reasons": tuple(failures),
            "helped": tuple(name for name, value in components.items() if value >= 0.6),
            "hurt": tuple(name for name, value in {
                "drawdown": drawdown_penalty,
                "turnover": turnover_penalty,
                "correlation": corr_penalty,
                "capacity": capacity_penalty,
                "uncertainty": uncertainty_penalty,
            }.items() if value > 0.25),
            "policy_version": self.policy.version,
            "evidence_ids": evidence_ids,
        }
        payload = {
            "strategy": evidence.strategy_name,
            "strategy_version": evidence.strategy_version,
            "horizon": horizon,
            "timeframe": evidence.timeframe,
            "evidence_hash": evidence.evidence_hash,
            "available_at": available.isoformat(),
            "policy_hash": self.policy.policy_hash,
            "inputs": asdict(score_inputs),
            "failures": failures,
            "components": components,
            "penalties": {
                "drawdown": drawdown_penalty,
                "turnover": turnover_penalty,
                "correlation": corr_penalty,
                "capacity": capacity_penalty,
                "uncertainty": uncertainty_penalty,
            },
        }
        digest = _canonical_hash(payload)
        return StrategyScorecard(
            scorecard_id=digest[:32],
            strategy_name=evidence.strategy_name,
            strategy_version=evidence.strategy_version,
            horizon=horizon,
            timeframe=evidence.timeframe,
            global_evidence_id=global_evidence_id,
            conditional_evidence_id=conditional_evidence_id or evidence.evidence_id,
            eligibility_status=ELIGIBLE if not failures else INELIGIBLE,
            rejection_reasons=tuple(failures),
            performance_score=performance_score,
            downside_score=downside_score,
            fold_consistency_score=fold_consistency_score,
            parameter_robustness_score=parameter_score,
            cost_robustness_score=cost_score,
            breadth_score=components["breadth"],
            paper_score=components["paper"],
            regime_compatibility_score=regime_score,
            asset_compatibility_score=asset_score,
            drawdown_penalty=drawdown_penalty,
            turnover_penalty=turnover_penalty,
            correlation_penalty=corr_penalty,
            capacity_penalty=capacity_penalty,
            uncertainty_penalty=uncertainty_penalty,
            overall_score=overall_score,
            available_at=available,
            scorecard_version="phase2.8",
            scorecard_policy_version=self.policy.version,
            scorecard_policy_hash=self.policy.policy_hash,
            evidence_hash=digest,
            evidence_ids=evidence_ids,
            explanation=explanation,
        )

    def _coerce_inputs(
        self,
        *,
        inputs: ScorecardInputs | None,
        certifications: dict[str, bool] | None,
        parameter_robust: bool | None,
        cost_stress_pass: bool | None,
        capacity_pass: bool | None,
        correlation_penalty: float | None,
    ) -> ScorecardInputs:
        values = asdict(inputs or ScorecardInputs())
        if certifications:
            values.update(
                {
                    "lineage_certified": certifications.get("lineage", values["lineage_certified"]),
                    "dq_certified": certifications.get("dq", values["dq_certified"]),
                    "causality_certified": certifications.get("causality", values["causality_certified"]),
                    "pit_certified": certifications.get("pit", values["pit_certified"]),
                    "oos_certified": certifications.get("oos", values["oos_certified"]),
                }
            )
        if parameter_robust is not None:
            values["parameter_robustness_pass"] = parameter_robust
        if cost_stress_pass is not None:
            values["cost_stress_pass"] = cost_stress_pass
        if capacity_pass is not None:
            values["capacity_pass"] = capacity_pass
        if correlation_penalty is not None:
            values["correlation"] = correlation_penalty
        return ScorecardInputs(**values)

    def _eligibility_failures(
        self, evidence: StrategyConditionalEvidence, inputs: ScorecardInputs, available_at: datetime
    ) -> list[str]:
        checks = (
            ("LINEAGE_NOT_CERTIFIED", self.policy.require_lineage_certified, inputs.lineage_certified),
            ("DQ_NOT_CERTIFIED", self.policy.require_dq_certified, inputs.dq_certified),
            ("CAUSALITY_NOT_CERTIFIED", self.policy.require_causality_certified, inputs.causality_certified),
            ("PIT_NOT_CERTIFIED", self.policy.require_pit_certified, inputs.pit_certified),
            ("OOS_NOT_CERTIFIED", self.policy.require_oos_certified, inputs.oos_certified),
            ("COST_STRESS_FAILED", self.policy.require_cost_stress_pass, inputs.cost_stress_pass),
            (
                "PARAMETER_ROBUSTNESS_FAILED",
                self.policy.require_parameter_robustness_pass,
                inputs.parameter_robustness_pass,
            ),
            ("CAPACITY_FAILED", self.policy.require_capacity_pass, inputs.capacity_pass),
            ("PAPER_EVIDENCE_REQUIRED", self.policy.require_paper_evidence, inputs.paper_evidence_pass),
            (
                "RECONCILIATION_DRIFT",
                self.policy.require_zero_reconciliation_drift,
                inputs.zero_reconciliation_drift,
            ),
        )
        failures = [reason for reason, required, passed in checks if required and not passed]
        if evidence.evidence_status != "SUFFICIENT":
            failures.append("INSUFFICIENT_EVIDENCE")
        if evidence.observation_count < self.policy.minimum_oos_observations:
            failures.append("INSUFFICIENT_OOS_OBSERVATIONS")
        if evidence.trade_count < self.policy.minimum_oos_trades:
            failures.append("INSUFFICIENT_OOS_TRADES")
        if evidence.fold_count < self.policy.minimum_folds:
            failures.append("INSUFFICIENT_FOLDS")
        if (evidence.last_observation - evidence.first_observation).days < self.policy.minimum_temporal_span_days:
            failures.append("INSUFFICIENT_TEMPORAL_SPAN")
        if evidence.max_drawdown < -self.policy.max_drawdown:
            failures.append("EXCESSIVE_DRAWDOWN")
        if evidence.expectancy <= self.policy.min_net_expectancy:
            failures.append("NON_POSITIVE_NET_EXPECTANCY")
        if inputs.correlation > self.policy.max_correlation:
            failures.append("CORRELATION_TOO_HIGH")
        if self.policy.max_evidence_age_days is not None:
            age_days = (available_at - evidence.available_at).days
            if age_days > self.policy.max_evidence_age_days:
                failures.append("STALE_EVIDENCE")
        return sorted(set(failures))
