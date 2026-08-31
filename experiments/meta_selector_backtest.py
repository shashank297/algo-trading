"""Phase 2.10 causal historical meta-selector replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable

import pandas as pd

from trading_stack.backtest import (
    _annualized_return,
    _max_drawdown_duration,
    _profit_factor,
    _sharpe_ratio,
    _sortino_ratio,
)
from trading_stack.selector import ABSTAIN, AdaptiveStrategySelector, SelectorDecision, SwitchCostEstimator


HOLD_CURRENT = "HOLD_CURRENT"
REDUCE_RISK = "REDUCE_RISK"
CASH = "CASH"
ABSTAIN_BEHAVIORS = frozenset({HOLD_CURRENT, REDUCE_RISK, CASH})


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class MetaReplayPolicy:
    version: str = "meta-selector-v2"
    abstain_behavior: str = HOLD_CURRENT
    risk_reduction_factor: float = 0.5
    min_final_oos_observations: int = 1
    max_switch_rate: float = 1.0

    def __post_init__(self) -> None:
        if self.abstain_behavior not in ABSTAIN_BEHAVIORS:
            raise ValueError("abstain_behavior must be HOLD_CURRENT, REDUCE_RISK, or CASH")
        if not 0 <= self.risk_reduction_factor <= 1:
            raise ValueError("risk_reduction_factor must be bounded in [0, 1]")

    @property
    def policy_hash(self) -> str:
        return _canonical_hash(asdict(self))


@dataclass(frozen=True)
class MetaSelectorObservation:
    decision_time: datetime
    symbol: str
    horizon: str
    market_regime: str | None
    regime_confidence: float
    asset_cluster: str | None
    scorecards: tuple[Any, ...]
    strategy_returns: dict[str, float]
    target_portfolios: dict[str, dict[str, float]] = field(default_factory=dict)
    asset_returns: dict[str, float] = field(default_factory=dict)
    benchmark_return: float = 0.0
    cash_return: float = 0.0
    correlations: dict[tuple[str, str], float] | None = None
    raw_regime: str | None = None
    operational_regime: str | None = None
    known_at: datetime | None = None
    available_at: datetime | None = None
    meta_split: str = "FINAL_OOS"
    future_trial_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetaSelectorCheckpoint:
    cash: float
    holdings: dict[str, float]
    cost_basis: dict[str, float]
    incumbent_strategy: str | None
    previous_selector_decision_id: str | None
    last_processed_timestamp: datetime | None
    policy_versions: dict[str, str]
    cumulative_costs: float
    pending_orders: tuple[dict[str, Any], ...] = ()
    pending_fills: tuple[dict[str, Any], ...] = ()

    @property
    def checkpoint_hash(self) -> str:
        return _canonical_hash(asdict(self))


@dataclass(frozen=True)
class MetaSelectorResult:
    meta_run_id: str
    decisions: tuple[SelectorDecision, ...]
    equity_curve: tuple[dict[str, Any], ...]
    switches: tuple[dict[str, Any], ...]
    attribution: dict[str, float]
    metrics: dict[str, float]
    baselines: dict[str, dict[str, float | str]]
    stress_results: dict[str, dict[str, float]]
    verdict: str
    evidence_hash: str
    checkpoint: MetaSelectorCheckpoint


class HistoricalEvidenceResolver:
    """Explicit point-in-time resolver; deliberately exposes no latest fallback."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def scorecards_at(self, decision_time: datetime, *, horizon: str | None = None) -> list[dict[str, Any]]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return self.db.list_scorecards_at(decision_time, horizon=horizon)

    def conditional_evidence_at(self, decision_time: datetime, *, strategy_name: str | None = None) -> list[dict[str, Any]]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return self.db.list_phase2_7_conditional_evidence_at(decision_time, strategy_name=strategy_name)

    def observation_at(self, decision_time: datetime, *, template: MetaSelectorObservation) -> MetaSelectorObservation:
        cards = tuple(self.scorecards_at(decision_time, horizon=template.horizon))
        return replace(template, scorecards=cards)


class MetaSelectorBacktest:
    """Replay adaptive selection as one continuous historical portfolio process."""

    def __init__(
        self,
        selector: AdaptiveStrategySelector,
        *,
        cost_estimator: SwitchCostEstimator | None = None,
        replay_policy: MetaReplayPolicy | None = None,
        resolver: HistoricalEvidenceResolver | None = None,
        db: Any | None = None,
    ) -> None:
        self.selector = selector
        self.cost_estimator = cost_estimator or SwitchCostEstimator()
        self.replay_policy = replay_policy or MetaReplayPolicy()
        self.resolver = resolver
        self.db = db

    def run(
        self,
        observations: Iterable[MetaSelectorObservation | dict[str, Any]],
        *,
        initial_equity: float = 100_000.0,
        policy_version: str | None = None,
        meta_split: str = "RESEARCH",
        purge_periods: int = 0,
        embargo_periods: int = 0,
        cost_multiplier: float = 1.0,
        delay_periods: int = 0,
        liquidity_multiplier: float = 1.0,
        include_stress: bool = True,
        registered_trial_id: str | None = None,
        trial_created_at: datetime | None = None,
        checkpoint: MetaSelectorCheckpoint | None = None,
    ) -> MetaSelectorResult:
        items = tuple(sorted((self._coerce(item) for item in observations), key=lambda item: item.decision_time))
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if cost_multiplier <= 0 or liquidity_multiplier <= 0:
            raise ValueError("cost and liquidity multipliers must be positive")
        if self.resolver is not None:
            items = tuple(self.resolver.observation_at(item.decision_time, template=item) for item in items)
        self._validate_causal_inputs(items)
        self._validate_final_oos_trial_binding(items, meta_split, registered_trial_id, trial_created_at)
        self._validate_purge_embargo(items, purge_periods, embargo_periods)

        effective_policy_version = policy_version or self.replay_policy.version
        cash = float(initial_equity if checkpoint is None else checkpoint.cash)
        current_weights: dict[str, float] = dict(checkpoint.holdings) if checkpoint else {}
        cost_basis: dict[str, float] = dict(checkpoint.cost_basis) if checkpoint else {}
        incumbent: str | None = checkpoint.incumbent_strategy if checkpoint else None
        previous_decision_id = checkpoint.previous_selector_decision_id if checkpoint else None
        cumulative_costs = float(checkpoint.cumulative_costs) if checkpoint else 0.0
        last_processed = checkpoint.last_processed_timestamp if checkpoint else None
        if last_processed is not None:
            items = tuple(item for item in items if item.decision_time > last_processed)

        decisions: list[SelectorDecision] = []
        equity_rows: list[dict[str, Any]] = []
        switches: list[dict[str, Any]] = []
        returns: list[float] = []
        raw_regimes: list[str | None] = []
        operational_regimes: list[str | None] = []
        skipped_opportunities = 0.0
        abstain_return = 0.0
        risk_avoided = 0.0
        turnover = 0.0
        slippage = 0.0
        realized_costs = 0.0
        previous_equity = cash

        for index, item in enumerate(items):
            raw_regimes.append(item.raw_regime or item.market_regime)
            operational_regimes.append(item.operational_regime or item.market_regime)
            execution_item = items[min(index + delay_periods, len(items) - 1)]
            visible_cards = tuple(card for card in item.scorecards if card.available_at <= item.decision_time)
            candidate_targets = self._candidate_targets(replace(item, scorecards=visible_cards))
            provisional_target = self._target_for_best_visible_card(visible_cards, candidate_targets)
            provisional_cost = self.cost_estimator.estimate(
                current_holdings=current_weights,
                target_holdings=provisional_target,
                portfolio_value=max(previous_equity, 1e-12),
                participation=max(0.0, 1.0 - liquidity_multiplier),
            )
            cutoff_hash = _canonical_hash([card.evidence_hash for card in visible_cards])
            decision = self.selector.select(
                decision_time=item.decision_time,
                symbol=item.symbol,
                horizon=item.horizon,
                market_regime=item.market_regime,
                regime_confidence=item.regime_confidence,
                asset_cluster=item.asset_cluster,
                scorecards=visible_cards,
                incumbent_strategy=incumbent,
                switching_cost=provisional_cost.estimated_cost_fraction * cost_multiplier,
                correlations=item.correlations,
                evidence_cutoff_hash=cutoff_hash,
            )
            selected_target = self._selected_target(decision, candidate_targets)
            target_weights = self._apply_abstain_policy(decision, current_weights, selected_target)
            execution = self._execute_rebalance(
                current_weights=current_weights,
                target_weights=target_weights,
                asset_returns=execution_item.asset_returns,
                portfolio_value=max(previous_equity, 1e-12),
                cost_multiplier=cost_multiplier,
                liquidity_multiplier=liquidity_multiplier,
            )
            current_weights = dict(execution["post_return_weights"])
            cost_basis = {symbol: current_weights[symbol] for symbol in current_weights}
            cash = float(execution["ending_equity"])
            cumulative_costs += float(execution["cost"])
            turnover += float(execution["turnover"])
            slippage += float(execution["slippage"])
            realized_costs += float(execution["cost"])
            net_return = float(cash / previous_equity - 1.0) if previous_equity else 0.0
            returns.append(net_return)
            decisions.append(decision)
            if decision.decision == ABSTAIN:
                best_return = self._target_return(provisional_target, execution_item.asset_returns)
                abstain_return += net_return
                skipped_opportunities += max(best_return, 0.0)
                risk_avoided += max(-best_return, 0.0)
            if execution["turnover"] > 0:
                switches.append(
                    {
                        "decision_time": item.decision_time,
                        "old_strategy": incumbent,
                        "new_strategy": ",".join(decision.selected_strategies),
                        "switching_cost": float(execution["cost"] / max(previous_equity, 1e-12)),
                        "sells_first": tuple(execution["sells_first"]),
                        "buys_after_sells": tuple(execution["buys_after_sells"]),
                        "turnover": float(execution["turnover"]),
                        "slippage": float(execution["slippage"]),
                    }
                )
            if decision.decision != ABSTAIN and decision.selected_strategies:
                incumbent = decision.selected_strategies[0]
            previous_decision_id = decision.selector_decision_id
            equity_rows.append(
                {
                    "timestamp": item.decision_time,
                    "cash": cash,
                    "holdings": dict(current_weights),
                    "equity": cash,
                    "net_return": net_return,
                    "drawdown": 0.0,
                    "position": sum(abs(value) for value in current_weights.values()),
                    "decision": decision.decision,
                    "turnover": float(execution["turnover"]),
                    "execution_cost": float(execution["cost"]),
                    "slippage": float(execution["slippage"]),
                }
            )
            previous_equity = cash

        self._attach_drawdowns(equity_rows, initial_equity)
        checkpoint_out = MetaSelectorCheckpoint(
            cash=cash,
            holdings=current_weights,
            cost_basis=cost_basis,
            incumbent_strategy=incumbent,
            previous_selector_decision_id=previous_decision_id,
            last_processed_timestamp=equity_rows[-1]["timestamp"] if equity_rows else last_processed,
            policy_versions={
                "meta_replay": self.replay_policy.version,
                "selector": self.selector.policy.version,
                "scorecard_policy_hash": _canonical_hash(
                    sorted({
                        card.scorecard_policy_hash
                        for item in items
                        for card in item.scorecards
                        if card.available_at <= item.decision_time
                    })
                ),
            },
            cumulative_costs=cumulative_costs,
        )
        metrics = self._metrics(
            equity_rows,
            returns,
            decisions,
            switches,
            raw_regimes,
            operational_regimes,
            initial_equity,
            turnover,
            realized_costs,
            slippage,
            abstain_return,
            skipped_opportunities,
            risk_avoided,
        )
        baselines = self._baselines(items, initial_equity, metrics)
        stress_results = (
            {
                "1.0x_cost": {"total_return": metrics["total_return"]},
                "1.5x_cost": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, cost_multiplier=1.5, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at).metrics["total_return"]},
                "2.0x_cost": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, cost_multiplier=2.0, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at).metrics["total_return"]},
                "switch_cost_stress": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, cost_multiplier=2.0, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at).metrics["total_return"]},
                "delayed_execution": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, delay_periods=1, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at).metrics["total_return"]} if len(items) > 1 else {"total_return": metrics["total_return"]},
                "reduced_liquidity": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, liquidity_multiplier=0.5, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at).metrics["total_return"]},
            }
            if include_stress
            else {"1.0x_cost": {"total_return": metrics["total_return"]}}
        )
        baselines["B5_adaptive"] = {"total_return": metrics["total_return"], "selection": "adaptive_selector"}
        verdict = self._verdict(metrics, baselines, len(items), stress_results)
        attribution = {
            "stock_selection": metrics["total_return"] - float(baselines["B0_benchmark"]["total_return"]),
            "strategy_selection": metrics["total_return"] - float(baselines["B3_equal_ensemble"]["total_return"]),
            "allocation": metrics["total_return"] - float(baselines["B4_risk_balanced"]["total_return"]),
            "execution_costs": -metrics["total_execution_cost"],
            "slippage": -metrics["slippage"],
            "abstention_return": metrics["abstention_return"],
            "skipped_opportunities": metrics["skipped_opportunities"],
            "risk_avoided": metrics["risk_avoided"],
        }
        payload = {
            "policy_version": effective_policy_version,
            "replay_policy_hash": self.replay_policy.policy_hash,
            "selector_policy": self.selector.policy.policy_hash,
            "meta_split": meta_split,
            "registered_trial_id": registered_trial_id,
            "purge_periods": purge_periods,
            "embargo_periods": embargo_periods,
            "decisions": [decision.evidence_hash for decision in decisions],
            "equity": equity_rows,
            "metrics": metrics,
            "baselines": baselines,
            "stress": stress_results,
            "checkpoint": checkpoint_out.checkpoint_hash,
        }
        evidence_hash = _canonical_hash(payload)
        return MetaSelectorResult(
            meta_run_id=evidence_hash[:32],
            decisions=tuple(decisions),
            equity_curve=tuple(equity_rows),
            switches=tuple(switches),
            attribution=attribution,
            metrics=metrics,
            baselines=baselines,
            stress_results=stress_results,
            verdict=verdict,
            evidence_hash=evidence_hash,
            checkpoint=checkpoint_out,
        )

    def _coerce(self, item: MetaSelectorObservation | dict[str, Any]) -> MetaSelectorObservation:
        if isinstance(item, MetaSelectorObservation):
            return item
        values = dict(item)
        values["scorecards"] = tuple(values.get("scorecards", ()))
        values["asset_returns"] = dict(values.get("asset_returns", {}))
        return MetaSelectorObservation(**values)

    @staticmethod
    def _validate_causal_inputs(items: tuple[MetaSelectorObservation, ...]) -> None:
        for item in items:
            if item.decision_time.tzinfo is None:
                raise ValueError("decision_time must be timezone-aware")
            for timestamp_name in ("known_at", "available_at"):
                timestamp = getattr(item, timestamp_name)
                if timestamp is not None and timestamp > item.decision_time:
                    raise ValueError(f"Future {timestamp_name} supplied to historical replay")
            for card in item.scorecards:
                if card.available_at > item.decision_time:
                    continue
                if getattr(card, "available_at").tzinfo is None:
                    raise ValueError("scorecard available_at must be timezone-aware")

    @staticmethod
    def _validate_final_oos_trial_binding(
        items: tuple[MetaSelectorObservation, ...],
        meta_split: str,
        registered_trial_id: str | None,
        trial_created_at: datetime | None,
    ) -> None:
        if meta_split != "FINAL_OOS":
            return
        final_items = [item for item in items if item.meta_split == "FINAL_OOS"]
        if not final_items:
            return
        if registered_trial_id is None or trial_created_at is None:
            raise ValueError("FINAL_OOS requires pre-registered meta-selector trial")
        if trial_created_at.tzinfo is None:
            raise ValueError("trial_created_at must be timezone-aware")
        first_final = min(item.decision_time for item in final_items)
        if trial_created_at >= first_final:
            raise ValueError("meta-selector trial must be registered before FINAL_OOS begins")

    @staticmethod
    def _validate_purge_embargo(items: tuple[MetaSelectorObservation, ...], purge_periods: int, embargo_periods: int) -> None:
        if purge_periods < 0 or embargo_periods < 0:
            raise ValueError("purge_periods and embargo_periods must be non-negative")
        if not items or (purge_periods == 0 and embargo_periods == 0):
            return
        split_order = {"TRAIN": 0, "VALIDATION": 1, "FINAL_OOS": 2}
        ordered = sorted(items, key=lambda item: item.decision_time)
        split_positions = [split_order.get(item.meta_split, 2) for item in ordered]
        if split_positions != sorted(split_positions):
            raise ValueError("meta observations must not move backward across split lifecycle")
        for left, right in zip(ordered, ordered[1:]):
            if split_order.get(left.meta_split, 2) != split_order.get(right.meta_split, 2):
                gap_days = (right.decision_time - left.decision_time).days
                if gap_days < purge_periods + embargo_periods:
                    raise ValueError("purge/embargo gap is not enforced between meta splits")

    @staticmethod
    def _candidate_targets(item: MetaSelectorObservation) -> dict[str, dict[str, float]]:
        if item.target_portfolios:
            return item.target_portfolios
        return {card.strategy_name: {item.symbol: 1.0} for card in item.scorecards if getattr(card, "is_eligible", False)}

    @staticmethod
    def _target_for_best_visible_card(cards: tuple[Any, ...], targets: dict[str, dict[str, float]]) -> dict[str, float]:
        eligible = [card for card in cards if getattr(card, "is_eligible", False)]
        if not eligible:
            return {}
        winner = sorted(eligible, key=lambda card: (-card.overall_score, card.strategy_name))[0]
        return targets.get(winner.strategy_name, {})

    @staticmethod
    def _selected_target(decision: SelectorDecision, targets: dict[str, dict[str, float]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for strategy, weight in decision.weights.items():
            for symbol, target_weight in targets.get(strategy, {}).items():
                result[symbol] = result.get(symbol, 0.0) + float(weight) * float(target_weight)
        return {symbol: weight for symbol, weight in result.items() if abs(weight) > 1e-12}

    def _apply_abstain_policy(
        self,
        decision: SelectorDecision,
        current_weights: dict[str, float],
        selected_target: dict[str, float],
    ) -> dict[str, float]:
        if decision.decision != ABSTAIN:
            return selected_target
        if self.replay_policy.abstain_behavior == HOLD_CURRENT:
            return dict(current_weights)
        if self.replay_policy.abstain_behavior == REDUCE_RISK:
            return {symbol: weight * self.replay_policy.risk_reduction_factor for symbol, weight in current_weights.items()}
        return {}

    def _execute_rebalance(
        self,
        *,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        asset_returns: dict[str, float],
        portfolio_value: float,
        cost_multiplier: float,
        liquidity_multiplier: float,
    ) -> dict[str, Any]:
        estimate = self.cost_estimator.estimate(
            current_holdings=current_weights,
            target_holdings=target_weights,
            portfolio_value=portfolio_value,
            participation=max(0.0, 1.0 - liquidity_multiplier),
        )
        base_cost = estimate.estimated_cost * cost_multiplier
        slippage = float(estimate.breakdown.get("slippage", 0.0)) * cost_multiplier
        tradable_value = max(portfolio_value - base_cost, 0.0)
        gross_return = self._target_return(target_weights, asset_returns)
        ending_equity = tradable_value * (1.0 + gross_return)
        post_return_weights = {
            symbol: weight * (1.0 + float(asset_returns.get(symbol, 0.0))) / max(1.0 + gross_return, 1e-12)
            for symbol, weight in target_weights.items()
        }
        return {
            "ending_equity": ending_equity,
            "turnover": estimate.turnover,
            "cost": base_cost,
            "slippage": slippage,
            "sells_first": estimate.sells_first,
            "buys_after_sells": estimate.buys_after_sells,
            "post_return_weights": post_return_weights,
        }

    @staticmethod
    def _target_return(target_weights: dict[str, float], asset_returns: dict[str, float]) -> float:
        return sum(float(weight) * float(asset_returns.get(symbol, 0.0)) for symbol, weight in target_weights.items())

    @staticmethod
    def _attach_drawdowns(rows: list[dict[str, Any]], initial_equity: float) -> None:
        peak = initial_equity
        for row in rows:
            peak = max(peak, float(row["equity"]))
            row["drawdown"] = float(row["equity"] / peak - 1.0)

    @staticmethod
    def _metrics(
        rows: list[dict[str, Any]],
        returns: list[float],
        decisions: list[SelectorDecision],
        switches: list[dict[str, Any]],
        raw_regimes: list[str | None],
        operational_regimes: list[str | None],
        initial_equity: float,
        turnover: float,
        realized_costs: float,
        slippage: float,
        abstain_return: float,
        skipped_opportunities: float,
        risk_avoided: float,
    ) -> dict[str, float]:
        equity = pd.Series([initial_equity] + [float(row["equity"]) for row in rows])
        net_returns = pd.Series(returns, dtype=float)
        drawdown = pd.Series([float(row["drawdown"]) for row in rows], dtype=float)
        var_95 = float(net_returns.quantile(0.05)) if not net_returns.empty else 0.0
        tail = net_returns[net_returns <= var_95] if not net_returns.empty else pd.Series(dtype=float)
        switch_count = float(len(switches))
        abstentions = [decision for decision in decisions if decision.decision == ABSTAIN]
        return {
            "total_return": float(equity.iloc[-1] / initial_equity - 1.0),
            "cagr": _annualized_return(equity, "1d", initial_equity),
            "volatility": float(net_returns.std(ddof=0) * (252.0**0.5)) if len(net_returns) else 0.0,
            "sharpe": _sharpe_ratio(net_returns, "1d"),
            "sortino": _sortino_ratio(net_returns, "1d"),
            "calmar": float(_annualized_return(equity, "1d", initial_equity) / abs(drawdown.min())) if len(drawdown) and drawdown.min() < 0 else 0.0,
            "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
            "drawdown_duration": float(_max_drawdown_duration(drawdown)) if len(drawdown) else 0.0,
            "var": var_95,
            "cvar": float(tail.mean()) if not tail.empty else var_95,
            "turnover": float(turnover),
            "total_execution_cost": float(realized_costs),
            "slippage": float(slippage),
            "switching_cost_drag": float(sum(item["switching_cost"] for item in switches)),
            "switch_count": switch_count,
            "average_strategy_dwell": float(len(rows) / max(switch_count + 1.0, 1.0)) if rows else 0.0,
            "raw_regime_transition_count": float(sum(1 for left, right in zip(raw_regimes, raw_regimes[1:]) if left != right)),
            "operational_regime_transition_count": float(sum(1 for left, right in zip(operational_regimes, operational_regimes[1:]) if left != right)),
            "abstention_periods": float(len(abstentions)),
            "abstention_duration": float(len(abstentions)),
            "abstention_return": float(abstain_return),
            "skipped_opportunities": float(skipped_opportunities),
            "risk_avoided": float(risk_avoided),
            "drawdown_effect": float(drawdown.min()) if len(drawdown) else 0.0,
            "profit_factor": _profit_factor(net_returns),
        }

    @staticmethod
    def _baselines(
        items: tuple[MetaSelectorObservation, ...],
        initial_equity: float,
        adaptive_metrics: dict[str, float],
    ) -> dict[str, dict[str, float | str]]:
        benchmark = [item.benchmark_return for item in items]
        cash = [item.cash_return for item in items]
        train_items = [item for item in items if item.meta_split == "TRAIN"] or list(items[: max(1, len(items) // 3)])
        train_scores: dict[str, float] = {}
        for item in train_items:
            for card in item.scorecards:
                if getattr(card, "is_eligible", False) and card.available_at <= item.decision_time:
                    train_scores[card.strategy_name] = train_scores.get(card.strategy_name, 0.0) + float(card.overall_score)
        static_winner = sorted(train_scores, key=lambda name: (-train_scores[name], name))[0] if train_scores else None
        static_returns = [
            MetaSelectorBacktest._strategy_realized_return(item, static_winner) if static_winner else 0.0
            for item in items
        ]
        equal_returns = []
        risk_balanced = []
        trailing: dict[str, list[float]] = {}
        for item in items:
            eligible = sorted(
                {
                    card.strategy_name
                    for card in item.scorecards
                    if getattr(card, "is_eligible", False) and card.available_at <= item.decision_time
                }
            )
            equal_returns.append(
                sum(MetaSelectorBacktest._strategy_realized_return(item, name) for name in eligible) / len(eligible)
                if eligible
                else 0.0
            )
            inv_vol_weights = MetaSelectorBacktest._inverse_vol_weights(eligible, trailing)
            risk_balanced.append(
                sum(MetaSelectorBacktest._strategy_realized_return(item, name) * weight for name, weight in inv_vol_weights.items())
            )
            for name in eligible:
                trailing.setdefault(name, []).append(MetaSelectorBacktest._strategy_realized_return(item, name))
        return {
            "B0_benchmark": {"total_return": MetaSelectorBacktest._compound(benchmark), "selection": "benchmark"},
            "B1_cash": {"total_return": MetaSelectorBacktest._compound(cash), "selection": "cash"},
            "B2_static": {"total_return": MetaSelectorBacktest._compound(static_returns), "selection": static_winner or "none"},
            "B3_equal_ensemble": {"total_return": MetaSelectorBacktest._compound(equal_returns), "selection": "pit_equal_eligible"},
            "B4_risk_balanced": {"total_return": MetaSelectorBacktest._compound(risk_balanced), "selection": "pit_inverse_vol"},
            "B5_adaptive": {"total_return": adaptive_metrics["total_return"], "selection": "adaptive_selector"},
        }

    @staticmethod
    def _strategy_realized_return(item: MetaSelectorObservation, strategy_name: str | None) -> float:
        if not strategy_name:
            return 0.0
        target = item.target_portfolios.get(strategy_name, {item.symbol: 1.0})
        if item.asset_returns:
            return MetaSelectorBacktest._target_return(target, item.asset_returns)
        return float(item.strategy_returns.get(strategy_name, 0.0))

    @staticmethod
    def _inverse_vol_weights(eligible: list[str], trailing: dict[str, list[float]]) -> dict[str, float]:
        if not eligible:
            return {}
        raw = {}
        for name in eligible:
            series = pd.Series(trailing.get(name, []), dtype=float)
            vol = float(series.std(ddof=0)) if len(series) > 1 else 1.0
            raw[name] = 1.0 / max(vol, 1e-6)
        total = sum(raw.values())
        return {name: value / total for name, value in raw.items()}

    @staticmethod
    def _compound(returns: Iterable[float]) -> float:
        equity = 1.0
        for value in returns:
            equity *= 1.0 + float(value)
        return equity - 1.0

    @staticmethod
    def _verdict(
        metrics: dict[str, float],
        baselines: dict[str, dict[str, float | str]],
        observation_count: int,
        stress_results: dict[str, dict[str, float]],
    ) -> str:
        simple_best = max(
            float(baselines[name]["total_return"])
            for name in ("B2_static", "B3_equal_ensemble", "B4_risk_balanced")
        )
        if metrics["total_return"] <= simple_best:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if observation_count < 1 or metrics["switch_count"] / max(observation_count, 1) > 1.0:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if stress_results.get("2.0x_cost", {}).get("total_return", metrics["total_return"]) < simple_best:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        return "ADAPTIVE_SELECTOR_RESEARCH_PASS"
