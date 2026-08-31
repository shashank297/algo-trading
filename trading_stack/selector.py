"""Phase 2.9 deterministic adaptive selector.

The selector emits strategy intent only.  It never talks to brokers and never
creates live or paper orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable

from data_platform.contracts import OrderSide
from trading_stack.costs import IndianDeliveryCostSchedule, get_cost_schedule
from trading_stack.scorecards import ELIGIBLE, StrategyScorecard


SELECT = "SELECT"
ENSEMBLE = "ENSEMBLE"
ABSTAIN = "ABSTAIN"
DECISIONS = frozenset({SELECT, ENSEMBLE, ABSTAIN})


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _bounded(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True)
class SelectorPolicy:
    version: str = "selector-v1"
    min_regime_confidence: float = 0.60
    min_score: float = 0.01
    min_expected_net_benefit: float = 0.0
    switch_buffer: float = 0.05
    uncertainty_margin: float = 0.02
    max_uncertainty: float = 0.80
    ensemble_max_correlation: float = 0.75
    max_ensemble_size: int = 3
    allow_ensemble: bool = True
    missing_correlation_policy: str = "select_only"

    @property
    def policy_hash(self) -> str:
        return _canonical_hash(asdict(self))


@dataclass(frozen=True)
class SwitchCostEstimate:
    estimated_cost: float
    estimated_cost_fraction: float
    turnover: float
    sells_first: tuple[str, ...]
    buys_after_sells: tuple[str, ...]
    cost_model_version: str
    cost_model_hash: str
    breakdown: dict[str, float]


@dataclass(frozen=True)
class SelectorDecision:
    selector_decision_id: str
    decision_time: datetime
    symbol: str
    horizon: str
    market_regime: str | None
    regime_confidence: float
    asset_cluster: str | None
    decision: str
    selected_strategies: tuple[str, ...]
    weights: dict[str, float]
    candidate_scorecards: tuple[str, ...]
    current_incumbent_strategy: str | None
    expected_benefit_estimate: float
    uncertainty: float
    switch_required: bool
    estimated_switch_cost: float
    switch_buffer: float
    decision_reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    selector_policy_version: str
    selector_policy_hash: str
    evidence_hash: str
    available_at: datetime
    evidence_ids: dict[str, Any]

    @property
    def incumbent_strategy(self) -> str | None:
        return self.current_incumbent_strategy

    @property
    def expected_benefit(self) -> float:
        return self.expected_benefit_estimate


class SwitchCostEstimator:
    """Estimate switching drag from actual portfolio deltas."""

    def __init__(self, schedule: IndianDeliveryCostSchedule | None = None) -> None:
        self.schedule = schedule or get_cost_schedule()

    def estimate(
        self,
        *,
        current_holdings: dict[str, float],
        target_holdings: dict[str, float],
        portfolio_value: float,
        participation: float = 0.0,
    ) -> SwitchCostEstimate:
        symbols = sorted(set(current_holdings) | set(target_holdings))
        total_cost = 0.0
        turnover = 0.0
        breakdown = {
            "brokerage": 0.0,
            "statutory": 0.0,
            "spread": 0.0,
            "slippage": 0.0,
            "market_impact": 0.0,
        }
        sells: list[str] = []
        buys: list[str] = []
        for symbol in symbols:
            delta = float(target_holdings.get(symbol, 0.0)) - float(current_holdings.get(symbol, 0.0))
            if abs(delta) <= 1e-12:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            if side == OrderSide.SELL:
                sells.append(symbol)
            else:
                buys.append(symbol)
            notional = abs(delta) * portfolio_value
            costs = self.schedule.calculate(notional, side, participation=participation)
            total_cost += costs.total
            turnover += abs(delta)
            breakdown["brokerage"] += costs.brokerage
            breakdown["statutory"] += costs.statutory_and_broker_fees - costs.brokerage
            breakdown["spread"] += costs.spread
            breakdown["slippage"] += costs.slippage
            breakdown["market_impact"] += costs.market_impact
        payload = {"schedule": asdict(self.schedule), "breakdown": breakdown}
        return SwitchCostEstimate(
            estimated_cost=total_cost,
            estimated_cost_fraction=total_cost / portfolio_value if portfolio_value > 0 else 0.0,
            turnover=turnover,
            sells_first=tuple(sorted(sells)),
            buys_after_sells=tuple(sorted(buys)),
            cost_model_version=self.schedule.version,
            cost_model_hash=_canonical_hash(payload),
            breakdown={key: float(value) for key, value in breakdown.items()},
        )


class AdaptiveStrategySelector:
    """Causal, restart-safe selector.  Callers persist every returned decision."""

    def __init__(self, policy: SelectorPolicy | None = None) -> None:
        self.policy = policy or SelectorPolicy()

    def select(
        self,
        *,
        decision_time: datetime,
        symbol: str,
        horizon: str,
        market_regime: str | None,
        regime_confidence: float,
        asset_cluster: str | None,
        scorecards: Iterable[StrategyScorecard],
        incumbent_strategy: str | None = None,
        switching_cost: float = 0.0,
        correlations: dict[tuple[str, str], float] | None = None,
        stale_scorecard_ids: Iterable[str] = (),
        evidence_cutoff_hash: str | None = None,
    ) -> SelectorDecision:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        cards = tuple(sorted(scorecards, key=lambda item: (-item.overall_score, item.strategy_name, item.strategy_version)))
        visible_cards = tuple(card for card in cards if card.available_at <= decision_time)
        stale_ids = set(stale_scorecard_ids)
        candidates = tuple(
            card
            for card in visible_cards
            if card.eligibility_status == ELIGIBLE
            and card.scorecard_id not in stale_ids
        )
        rejected = [
            f"{card.strategy_name}:{card.strategy_version}:INELIGIBLE"
            for card in visible_cards
            if card.eligibility_status != ELIGIBLE
        ]
        rejected.extend(f"{card_id}:STALE_EVIDENCE" for card_id in sorted(stale_ids))
        reasons: list[str] = []
        decision = ABSTAIN
        selected: tuple[str, ...] = ()
        weights: dict[str, float] = {}
        switch_required = False
        expected_benefit = max((card.overall_score for card in candidates), default=0.0)
        uncertainty = max((card.uncertainty_penalty for card in candidates), default=1.0)

        if regime_confidence < self.policy.min_regime_confidence:
            rejected.append("LOW_REGIME_CONFIDENCE")
            reasons.append("ABSTAIN_LOW_REGIME_CONFIDENCE")
        elif not asset_cluster:
            rejected.append("ASSET_STATE_UNCLEAR")
            reasons.append("ABSTAIN_ASSET_STATE_UNCLEAR")
        elif not candidates:
            rejected.append("NO_ELIGIBLE_STRATEGY")
            reasons.append("ABSTAIN_NO_ELIGIBLE_STRATEGY")
        elif expected_benefit <= self.policy.min_score:
            rejected.append("NO_POSITIVE_NET_EDGE")
            reasons.append("ABSTAIN_NO_POSITIVE_NET_EDGE")
        elif uncertainty > self.policy.max_uncertainty:
            rejected.append("UNCERTAINTY_TOO_HIGH")
            reasons.append("ABSTAIN_UNCERTAINTY_TOO_HIGH")
        else:
            winner = candidates[0]
            incumbent = next(
                (
                    card
                    for card in candidates
                    if card.strategy_name == incumbent_strategy or f"{card.strategy_name}:{card.strategy_version}" == incumbent_strategy
                ),
                None,
            )
            if incumbent and winner.scorecard_id != incumbent.scorecard_id:
                net_advantage = winner.overall_score - incumbent.overall_score
                required_advantage = self.policy.switch_buffer + switching_cost + self.policy.uncertainty_margin
                if net_advantage <= required_advantage:
                    decision = SELECT
                    selected = (incumbent.strategy_name,)
                    weights = {incumbent.strategy_name: 1.0}
                    expected_benefit = incumbent.overall_score
                    uncertainty = incumbent.uncertainty_penalty
                    reasons.append("HYSTERESIS_RETAINS_INCUMBENT")
                else:
                    decision, selected, weights = self._choose_winner_or_ensemble(candidates, correlations)
                    switch_required = incumbent_strategy not in selected
                    reasons.append("SWITCH_ADVANTAGE_EXCEEDS_BUFFER_AND_COST")
            else:
                decision, selected, weights = self._choose_winner_or_ensemble(candidates, correlations)
                switch_required = bool(incumbent_strategy and incumbent_strategy not in selected)
                reasons.append("CLEAR_ELIGIBLE_EDGE")
            if expected_benefit - switching_cost <= self.policy.min_expected_net_benefit and switch_required:
                decision = SELECT if incumbent else ABSTAIN
                selected = (incumbent.strategy_name,) if incumbent else ()
                weights = {incumbent.strategy_name: 1.0} if incumbent else {}
                switch_required = False
                rejected.append("SWITCHING_COST_REMOVES_EDGE")
                reasons.append("NO_SWITCH_AFTER_COST")

        payload = {
            "decision_time": decision_time.isoformat(),
            "symbol": symbol,
            "horizon": horizon,
            "market_regime": market_regime,
            "regime_confidence": regime_confidence,
            "asset_cluster": asset_cluster,
            "cards": [(card.scorecard_id, card.evidence_hash, card.available_at.isoformat()) for card in visible_cards],
            "incumbent": incumbent_strategy,
            "switching_cost": switching_cost,
            "policy_hash": self.policy.policy_hash,
            "decision": decision,
            "selected": selected,
            "weights": weights,
            "evidence_cutoff_hash": evidence_cutoff_hash,
        }
        digest = _canonical_hash(payload)
        return SelectorDecision(
            selector_decision_id=digest[:32],
            decision_time=decision_time,
            symbol=symbol,
            horizon=horizon,
            market_regime=market_regime,
            regime_confidence=float(regime_confidence),
            asset_cluster=asset_cluster,
            decision=decision,
            selected_strategies=selected,
            weights=weights,
            candidate_scorecards=tuple(card.scorecard_id for card in visible_cards),
            current_incumbent_strategy=incumbent_strategy,
            expected_benefit_estimate=float(expected_benefit),
            uncertainty=float(_bounded(uncertainty)),
            switch_required=switch_required,
            estimated_switch_cost=float(switching_cost),
            switch_buffer=self.policy.switch_buffer,
            decision_reasons=tuple(dict.fromkeys(reasons)),
            rejection_reasons=tuple(dict.fromkeys(rejected)),
            selector_policy_version=self.policy.version,
            selector_policy_hash=self.policy.policy_hash,
            evidence_hash=digest,
            available_at=decision_time,
            evidence_ids={
                "scorecard_ids": tuple(card.scorecard_id for card in visible_cards),
                "conditional_evidence_ids": tuple(card.conditional_evidence_id for card in visible_cards),
                "evidence_cutoff_hash": evidence_cutoff_hash,
            },
        )

    def _choose_winner_or_ensemble(
        self,
        candidates: tuple[StrategyScorecard, ...],
        correlations: dict[tuple[str, str], float] | None,
    ) -> tuple[str, tuple[str, ...], dict[str, float]]:
        independent = [candidates[0]]
        for card in candidates[1:]:
            if len(independent) >= self.policy.max_ensemble_size:
                break
            pairwise = [
                self._correlation(card.strategy_name, other.strategy_name, correlations)
                for other in independent
            ]
            if any(value is None for value in pairwise):
                continue
            if all(value < self.policy.ensemble_max_correlation for value in pairwise if value is not None):
                independent.append(card)
        if self.policy.allow_ensemble and len(independent) > 1:
            total = sum(max(card.overall_score, 0.0) for card in independent)
            weights = (
                {card.strategy_name: max(card.overall_score, 0.0) / total for card in independent}
                if total > 0
                else {card.strategy_name: 1.0 / len(independent) for card in independent}
            )
            return ENSEMBLE, tuple(card.strategy_name for card in independent), weights
        winner = candidates[0]
        return SELECT, (winner.strategy_name,), {winner.strategy_name: 1.0}

    @staticmethod
    def _correlation(
        left: str, right: str, correlations: dict[tuple[str, str], float] | None
    ) -> float | None:
        if left == right:
            return 1.0
        table = correlations or {}
        key = (min(left, right), max(left, right))
        if key not in table:
            return None
        return abs(float(table[key]))
