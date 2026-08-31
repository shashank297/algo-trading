"""Phase 2.10 whole-system historical meta-selector replay."""

from __future__ import annotations

from dataclasses import dataclass, field
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


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


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
    benchmark_return: float = 0.0
    cash_return: float = 0.0
    correlations: dict[tuple[str, str], float] | None = None
    raw_regime: str | None = None
    operational_regime: str | None = None
    known_at: datetime | None = None
    available_at: datetime | None = None
    future_trial_ids: tuple[str, ...] = ()


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


class MetaSelectorBacktest:
    """Replay adaptive selection as one continuous historical portfolio process."""

    def __init__(self, selector: AdaptiveStrategySelector, *, cost_estimator: SwitchCostEstimator | None = None) -> None:
        self.selector = selector
        self.cost_estimator = cost_estimator or SwitchCostEstimator()

    def run(
        self,
        observations: Iterable[MetaSelectorObservation | dict[str, Any]],
        *,
        initial_equity: float = 100_000.0,
        policy_version: str = "meta-selector-v1",
        meta_split: str = "FINAL_OOS",
        purge_periods: int = 0,
        embargo_periods: int = 0,
        cost_multiplier: float = 1.0,
        delay_periods: int = 0,
        liquidity_multiplier: float = 1.0,
        include_stress: bool = True,
    ) -> MetaSelectorResult:
        items = tuple(sorted((self._coerce(item) for item in observations), key=lambda item: item.decision_time))
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self._validate_causal_inputs(items)
        equity = float(initial_equity)
        current_weights: dict[str, float] = {}
        incumbent: str | None = None
        decisions: list[SelectorDecision] = []
        equity_rows: list[dict[str, Any]] = []
        switches: list[dict[str, Any]] = []
        returns: list[float] = []
        raw_regimes: list[str | None] = []
        operational_regimes: list[str | None] = []

        for index, item in enumerate(items):
            raw_regimes.append(item.raw_regime or item.market_regime)
            operational_regimes.append(item.operational_regime or item.market_regime)
            delayed_item = items[min(index + delay_periods, len(items) - 1)]
            candidate_targets = self._candidate_targets(item)
            winner = self._highest_available_candidate(item)
            target = candidate_targets.get(winner, {}) if winner else {}
            switch_cost = self.cost_estimator.estimate(
                current_holdings=current_weights,
                target_holdings=target,
                portfolio_value=equity,
                participation=max(0.0, 1.0 - liquidity_multiplier),
            )
            decision = self.selector.select(
                decision_time=item.decision_time,
                symbol=item.symbol,
                horizon=item.horizon,
                market_regime=item.market_regime,
                regime_confidence=item.regime_confidence,
                asset_cluster=item.asset_cluster,
                scorecards=item.scorecards,
                incumbent_strategy=incumbent,
                switching_cost=switch_cost.estimated_cost_fraction * cost_multiplier,
                correlations=item.correlations,
                evidence_cutoff_hash=_canonical_hash([card.evidence_hash for card in item.scorecards]),
            )
            selected_target = self._selected_target(decision, candidate_targets)
            selected_return = self._selected_return(decision, delayed_item.strategy_returns)
            realized_switch_cost = decision.estimated_switch_cost if decision.switch_required else 0.0
            net_return = selected_return - realized_switch_cost
            equity *= 1.0 + net_return
            returns.append(net_return)
            decisions.append(decision)
            equity_rows.append(
                {
                    "timestamp": item.decision_time,
                    "equity": equity,
                    "net_return": net_return,
                    "drawdown": 0.0,
                    "position": sum(abs(value) for value in selected_target.values()),
                    "decision": decision.decision,
                }
            )
            if decision.switch_required:
                switches.append(
                    {
                        "decision_time": item.decision_time,
                        "old_strategy": incumbent,
                        "new_strategy": ",".join(decision.selected_strategies),
                        "switching_cost": realized_switch_cost,
                        "sells_first": switch_cost.sells_first,
                        "buys_after_sells": switch_cost.buys_after_sells,
                    }
                )
            if decision.decision != ABSTAIN:
                current_weights = selected_target
                incumbent = decision.selected_strategies[0]

        self._attach_drawdowns(equity_rows, initial_equity)
        metrics = self._metrics(equity_rows, returns, decisions, switches, raw_regimes, operational_regimes, initial_equity)
        baselines = self._baselines(items, initial_equity)
        stress_results = (
            {
                "1.0x_cost": {"total_return": metrics["total_return"]},
                "1.5x_cost": {"total_return": self._stress_total_return(returns, decisions, 1.5)},
                "2.0x_cost": {"total_return": self._stress_total_return(returns, decisions, 2.0)},
                "switch_cost_stress": {"total_return": self._stress_total_return(returns, decisions, 2.0)},
                "delayed_execution": {"total_return": self.run(items, initial_equity=initial_equity, delay_periods=1, include_stress=False).metrics["total_return"]} if delay_periods == 0 and len(items) > 1 else {"total_return": metrics["total_return"]},
                "reduced_liquidity": {"total_return": self.run(items, initial_equity=initial_equity, liquidity_multiplier=0.5, include_stress=False).metrics["total_return"]} if liquidity_multiplier == 1.0 and len(items) > 1 else {"total_return": metrics["total_return"]},
            }
            if include_stress
            else {"1.0x_cost": {"total_return": metrics["total_return"]}}
        )
        verdict = self._verdict(metrics, baselines)
        attribution = {
            "stock_selection": 0.0,
            "strategy_selection": metrics["total_return"] - float(baselines["B3_equal_ensemble"]["total_return"]),
            "allocation": metrics["total_return"] - float(baselines["B4_risk_balanced"]["total_return"]),
            "execution_costs": -metrics["total_execution_cost"],
        }
        payload = {
            "policy_version": policy_version,
            "selector_policy": self.selector.policy.policy_hash,
            "meta_split": meta_split,
            "purge_periods": purge_periods,
            "embargo_periods": embargo_periods,
            "decisions": [decision.evidence_hash for decision in decisions],
            "equity": equity_rows,
            "metrics": metrics,
            "baselines": baselines,
            "stress": stress_results,
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
        )

    def _coerce(self, item: MetaSelectorObservation | dict[str, Any]) -> MetaSelectorObservation:
        if isinstance(item, MetaSelectorObservation):
            return item
        values = dict(item)
        values["scorecards"] = tuple(values.get("scorecards", ()))
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
                    raise ValueError("Future scorecard supplied to historical replay")

    @staticmethod
    def _candidate_targets(item: MetaSelectorObservation) -> dict[str, dict[str, float]]:
        if item.target_portfolios:
            return item.target_portfolios
        return {card.strategy_name: {item.symbol: 1.0} for card in item.scorecards if getattr(card, "is_eligible", False)}

    @staticmethod
    def _highest_available_candidate(item: MetaSelectorObservation) -> str | None:
        eligible = [card for card in item.scorecards if getattr(card, "is_eligible", False)]
        if not eligible:
            return None
        return sorted(eligible, key=lambda card: (-card.overall_score, card.strategy_name))[0].strategy_name

    @staticmethod
    def _selected_target(decision: SelectorDecision, targets: dict[str, dict[str, float]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for strategy, weight in decision.weights.items():
            for symbol, target_weight in targets.get(strategy, {}).items():
                result[symbol] = result.get(symbol, 0.0) + float(weight) * float(target_weight)
        return result

    @staticmethod
    def _selected_return(decision: SelectorDecision, returns: dict[str, float]) -> float:
        if decision.decision == ABSTAIN:
            return 0.0
        return sum(float(returns.get(strategy, 0.0)) * weight for strategy, weight in decision.weights.items())

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
    ) -> dict[str, float]:
        equity = pd.Series([initial_equity] + [float(row["equity"]) for row in rows])
        net_returns = pd.Series(returns, dtype=float)
        drawdown = pd.Series([float(row["drawdown"]) for row in rows], dtype=float)
        var_95 = float(net_returns.quantile(0.05)) if not net_returns.empty else 0.0
        tail = net_returns[net_returns <= var_95] if not net_returns.empty else pd.Series(dtype=float)
        switch_count = float(len(switches))
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
            "turnover": switch_count,
            "total_execution_cost": float(sum(decision.estimated_switch_cost for decision in decisions if decision.switch_required)),
            "slippage": 0.0,
            "switching_cost_drag": float(sum(item["switching_cost"] for item in switches)),
            "switch_count": switch_count,
            "average_strategy_dwell": float(len(rows) / max(switch_count + 1.0, 1.0)) if rows else 0.0,
            "raw_regime_transition_count": float(sum(1 for left, right in zip(raw_regimes, raw_regimes[1:]) if left != right)),
            "operational_regime_transition_count": float(sum(1 for left, right in zip(operational_regimes, operational_regimes[1:]) if left != right)),
            "abstention_periods": float(sum(decision.decision == ABSTAIN for decision in decisions)),
            "profit_factor": _profit_factor(net_returns),
        }

    @staticmethod
    def _baselines(items: tuple[MetaSelectorObservation, ...], initial_equity: float) -> dict[str, dict[str, float | str]]:
        benchmark = [item.benchmark_return for item in items]
        cash = [item.cash_return for item in items]
        eligible_names = sorted({card.strategy_name for item in items for card in item.scorecards if getattr(card, "is_eligible", False)})
        first_train_winner = eligible_names[0] if eligible_names else None
        static_returns = [item.strategy_returns.get(first_train_winner, 0.0) if first_train_winner else 0.0 for item in items]
        equal_returns = [
            sum(item.strategy_returns.get(name, 0.0) for name in eligible_names) / len(eligible_names) if eligible_names else 0.0
            for item in items
        ]
        risk_balanced = equal_returns
        return {
            "B0_benchmark": {"total_return": MetaSelectorBacktest._compound(benchmark), "selection": "benchmark"},
            "B1_cash": {"total_return": MetaSelectorBacktest._compound(cash), "selection": "cash"},
            "B2_static": {"total_return": MetaSelectorBacktest._compound(static_returns), "selection": first_train_winner or "none"},
            "B3_equal_ensemble": {"total_return": MetaSelectorBacktest._compound(equal_returns), "selection": "equal_eligible"},
            "B4_risk_balanced": {"total_return": MetaSelectorBacktest._compound(risk_balanced), "selection": "simple_diversified"},
        }

    @staticmethod
    def _compound(returns: Iterable[float]) -> float:
        equity = 1.0
        for value in returns:
            equity *= 1.0 + float(value)
        return equity - 1.0

    @staticmethod
    def _stress_total_return(returns: list[float], decisions: list[SelectorDecision], multiplier: float) -> float:
        equity = 1.0
        for value, decision in zip(returns, decisions):
            extra_cost = decision.estimated_switch_cost * max(multiplier - 1.0, 0.0) if decision.switch_required else 0.0
            equity *= 1.0 + value - extra_cost
        return equity - 1.0

    @staticmethod
    def _verdict(metrics: dict[str, float], baselines: dict[str, dict[str, float | str]]) -> str:
        simple_best = max(
            float(baselines[name]["total_return"])
            for name in ("B2_static", "B3_equal_ensemble", "B4_risk_balanced")
        )
        if metrics["total_return"] <= simple_best:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        return "ADAPTIVE_SELECTOR_RESEARCH_PASS"
