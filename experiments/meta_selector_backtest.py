"""Phase 2.10 causal historical meta-selector replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, cast

import pandas as pd

from data_platform.contracts import OrderSide
from risk.engine import RiskEngine
from risk.models import RiskAction, RiskPolicy, TradeProposal
from trading_stack.costs import IndianDeliveryCostSchedule
from trading_stack.backtest import (
    _annualized_return,
    _max_drawdown_duration,
    _profit_factor,
    _sharpe_ratio,
    _sortino_ratio,
)
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.scorecards import StrategyScorecard
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
    max_drawdown: float = 0.25
    min_net_edge: float = 0.0

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
    prices: dict[str, float] = field(default_factory=dict)
    sectors: dict[str, str] = field(default_factory=dict)
    benchmark_return: float = 0.0
    cash_return: float = 0.0
    correlations: dict[tuple[str, str], float] | None = None
    raw_regime: str | None = None
    operational_regime: str | None = None
    known_at: datetime | None = None
    available_at: datetime | None = None
    meta_split: str = "FINAL_OOS"
    future_trial_ids: tuple[str, ...] = ()
    historical_bars: tuple[dict[str, Any], ...] = ()
    prior_asset_returns: dict[str, float] = field(default_factory=dict)
    label_start: datetime | None = None
    label_end: datetime | None = None
    evidence_start: datetime | None = None
    evidence_end: datetime | None = None
    data_hash: str = "synthetic"
    execution_data_available_at: datetime | None = None


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
    market_prices: dict[str, float] = field(default_factory=dict)
    pending_orders: tuple[dict[str, Any], ...] = ()
    pending_fills: tuple[dict[str, Any], ...] = ()
    peak_equity: float | None = None

    @property
    def checkpoint_hash(self) -> str:
        return _canonical_hash(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MetaSelectorCheckpoint:
        values = dict(payload)
        timestamp = values.get("last_processed_timestamp")
        values["last_processed_timestamp"] = pd.Timestamp(timestamp).to_pydatetime() if timestamp else None
        values["holdings"] = {str(key): float(value) for key, value in dict(values.get("holdings") or {}).items()}
        values["cost_basis"] = {str(key): float(value) for key, value in dict(values.get("cost_basis") or {}).items()}
        values["market_prices"] = {str(key): float(value) for key, value in dict(values.get("market_prices") or {}).items()}
        values["policy_versions"] = {str(key): str(value) for key, value in dict(values.get("policy_versions") or {}).items()}
        values["pending_orders"] = tuple(values.get("pending_orders") or ())
        values["pending_fills"] = tuple(values.get("pending_fills") or ())
        if values.get("peak_equity") is not None:
            values["peak_equity"] = float(values["peak_equity"])
        return cls(**values)


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
    orders: tuple[dict[str, Any], ...] = ()
    fills: tuple[dict[str, Any], ...] = ()
    risk_decisions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class FrozenMetaPolicy:
    """Immutable policy artifact consumed by FINAL_OOS replay."""

    frozen_policy_id: str
    selector_policy_version: str
    selector_policy_hash: str
    scorecard_policy_hash: str
    meta_policy_version: str
    meta_policy_hash: str
    candidate_trial_ids: tuple[str, ...]
    selected_trial_id: str
    data_hash: str
    universe_lineage: tuple[str, ...]
    cost_model_version: str
    cost_model_hash: str
    purge_periods: int
    embargo_periods: int
    frozen_at: datetime
    artifact_hash: str

    @classmethod
    def create(
        cls,
        *,
        selector_policy_version: str,
        selector_policy_hash: str,
        scorecard_policy_hash: str,
        meta_policy_version: str,
        meta_policy_hash: str,
        candidate_trial_ids: Iterable[str],
        selected_trial_id: str,
        data_hash: str,
        universe_lineage: Iterable[str],
        cost_model_version: str,
        cost_model_hash: str,
        purge_periods: int,
        embargo_periods: int,
        frozen_at: datetime,
    ) -> FrozenMetaPolicy:
        if frozen_at.tzinfo is None:
            raise ValueError("frozen_at must be timezone-aware")
        candidate_ids = tuple(sorted(candidate_trial_ids))
        universe_ids = tuple(sorted(universe_lineage))
        values = {
            "selector_policy_version": selector_policy_version, "selector_policy_hash": selector_policy_hash,
            "scorecard_policy_hash": scorecard_policy_hash, "meta_policy_version": meta_policy_version,
            "meta_policy_hash": meta_policy_hash, "candidate_trial_ids": candidate_ids,
            "selected_trial_id": selected_trial_id, "data_hash": data_hash,
            "universe_lineage": universe_ids, "cost_model_version": cost_model_version,
            "cost_model_hash": cost_model_hash, "purge_periods": purge_periods,
            "embargo_periods": embargo_periods, "frozen_at": frozen_at,
        }
        artifact_hash = _canonical_hash(values)
        return cls(
            frozen_policy_id=artifact_hash[:32],
            selector_policy_version=selector_policy_version,
            selector_policy_hash=selector_policy_hash,
            scorecard_policy_hash=scorecard_policy_hash,
            meta_policy_version=meta_policy_version,
            meta_policy_hash=meta_policy_hash,
            candidate_trial_ids=candidate_ids,
            selected_trial_id=selected_trial_id,
            data_hash=data_hash,
            universe_lineage=universe_ids,
            cost_model_version=cost_model_version,
            cost_model_hash=cost_model_hash,
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
            frozen_at=frozen_at,
            artifact_hash=artifact_hash,
        )


@dataclass(frozen=True)
class MetaResearchResult:
    frozen_policy: FrozenMetaPolicy
    train_results: dict[str, MetaSelectorResult]
    validation_results: dict[str, MetaSelectorResult]
    final_oos_result: MetaSelectorResult


class MetaResearchRunner:
    """Run and persist the TRAIN, VALIDATION, and FINAL_OOS lifecycle."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def run(
        self,
        train: Iterable[MetaSelectorObservation | dict[str, Any]],
        validation: Iterable[MetaSelectorObservation | dict[str, Any]],
        final_oos: Iterable[MetaSelectorObservation | dict[str, Any]],
        candidates: Iterable[tuple[str, AdaptiveStrategySelector, MetaReplayPolicy]],
        *,
        data_hash: str,
        purge_periods: int = 0,
        embargo_periods: int = 0,
        frozen_at: datetime | None = None,
    ) -> MetaResearchResult:
        if self.db is None:
            raise ValueError("MetaResearchRunner requires a Phase 2.1 trial registry")
        candidate_list = tuple(candidates)
        if not candidate_list:
            raise ValueError("at least one candidate policy is required")
        normalizer = MetaSelectorBacktest(candidate_list[0][1], replay_policy=candidate_list[0][2], db=self.db)
        train_items = tuple(normalizer._coerce(item) for item in train)
        validation_items = tuple(normalizer._coerce(item) for item in validation)
        final_items = tuple(normalizer._coerce(item) for item in final_oos)
        if frozen_at is None or frozen_at.tzinfo is None:
            raise ValueError("MetaResearchRunner requires an explicit timezone-aware frozen_at")
        train_results: dict[str, MetaSelectorResult] = {}
        validation_results: dict[str, MetaSelectorResult] = {}
        trial_ids: dict[str, str] = {}
        for candidate_id, selector, replay_policy in candidate_list:
            trial_ids[candidate_id] = self._register_candidate(candidate_id, selector, replay_policy, data_hash, purge_periods, embargo_periods, frozen_at)
            replay = MetaSelectorBacktest(selector, replay_policy=replay_policy, db=self.db)
            train_results[candidate_id] = replay.run(train_items, meta_split="TRAIN", include_stress=False, data_hash=data_hash, purge_periods=purge_periods, embargo_periods=embargo_periods)
            validation_results[candidate_id] = replay.run(validation_items, meta_split="VALIDATION", include_stress=False, data_hash=data_hash, purge_periods=purge_periods, embargo_periods=embargo_periods)
        winner = min(candidate_list, key=lambda candidate: (-validation_results[candidate[0]].metrics["total_return"], candidate[0]))
        winner_id, selector, replay_policy = winner
        frozen = FrozenMetaPolicy.create(
            selector_policy_version=selector.policy.version,
            selector_policy_hash=selector.policy.policy_hash,
            scorecard_policy_hash=MetaSelectorBacktest._canonical_visible_scorecard_policy_hash(tuple(train_items + validation_items)),
            meta_policy_version=replay_policy.version,
            meta_policy_hash=replay_policy.policy_hash,
            candidate_trial_ids=trial_ids.values(),
            selected_trial_id=trial_ids[winner_id],
            data_hash=data_hash,
            universe_lineage=sorted({card.strategy_name for item in train_items + validation_items for card in item.scorecards}),
            cost_model_version=MetaSelectorBacktest(selector, replay_policy=replay_policy).execution_adapter.cost_schedule.version,
            cost_model_hash=MetaSelectorBacktest._cost_model_hash(MetaSelectorBacktest(selector, replay_policy=replay_policy).execution_adapter.cost_schedule),
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
            frozen_at=frozen_at,
        )
        self.db.persist_frozen_meta_policy(frozen)
        final_result = MetaSelectorBacktest(selector, replay_policy=replay_policy, db=self.db).run(
            final_items,
            meta_split="FINAL_OOS",
            registered_trial_id=frozen.selected_trial_id,
            trial_created_at=frozen.frozen_at,
            frozen_policy_id=frozen.frozen_policy_id,
            data_hash=data_hash,
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
        )
        return MetaResearchResult(frozen, train_results, validation_results, final_result)

    def _register_candidate(self, candidate_id: str, selector: AdaptiveStrategySelector, replay_policy: MetaReplayPolicy, data_hash: str, purge_periods: int, embargo_periods: int, created_at: datetime | None) -> str:
        from experiments.trials import ExperimentFamilySpec, ResearchTrial
        timestamp = created_at or datetime.now(timezone.utc)
        family = ExperimentFamilySpec(
            experiment_family_id=f"meta-selector-{candidate_id}", hypothesis="causal meta selector policy", strategy_names=["meta_selector"], strategy_versions=[replay_policy.version], universe_snapshot_id="META", timeframe="1d", feature_versions=[replay_policy.version], cost_model_version="authoritative", parameter_space={}, maximum_trials=100, selection_metric="total_return", walk_forward_design={"purge_periods": purge_periods, "embargo_periods": embargo_periods}, source_revision="phase2-10", created_at=timestamp,
        )
        self.db.register_experiment_family(family)
        trial = ResearchTrial(
            experiment_family_id=family.experiment_family_id, strategy_name="meta_selector", strategy_version=replay_policy.version, scope="META_SELECTOR", timeframe="1d", parameters={"candidate_id": candidate_id, "selector_policy_version": selector.policy.version, "selector_policy_hash": selector.policy.policy_hash, "meta_replay_policy_version": replay_policy.version, "meta_replay_policy_hash": replay_policy.policy_hash, "data_hash": data_hash, "purge_periods": purge_periods, "embargo_periods": embargo_periods}, source_revision="phase2-10", data_hash=data_hash, cost_model_hash=MetaSelectorBacktest._cost_model_hash(MetaSelectorBacktest(selector, replay_policy=replay_policy).execution_adapter.cost_schedule), created_at=timestamp,
        )
        return self.db.create_research_trial(trial)


class HistoricalEvidenceResolver:
    """Explicit point-in-time resolver; deliberately exposes no latest fallback."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def scorecards_at(self, decision_time: datetime, *, horizon: str | None = None) -> list[StrategyScorecard]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return [self._scorecard_from_row(row) for row in self.db.list_scorecards_at(decision_time, horizon=horizon)]

    def conditional_evidence_at(self, decision_time: datetime, *, strategy_name: str | None = None) -> list[dict[str, Any]]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return self.db.list_phase2_7_conditional_evidence_at(decision_time, strategy_name=strategy_name)

    def observation_at(self, decision_time: datetime, *, template: MetaSelectorObservation) -> MetaSelectorObservation:
        cards = tuple(self.scorecards_at(decision_time, horizon=template.horizon))
        return replace(template, scorecards=cards)

    @staticmethod
    def _scorecard_from_row(row: dict[str, Any]) -> StrategyScorecard:
        return StrategyScorecard(
            scorecard_id=str(row["scorecard_id"]),
            strategy_name=str(row["strategy_name"]),
            strategy_version=str(row["strategy_version"]),
            horizon=str(row["horizon"]),
            timeframe=str(row["timeframe"]),
            global_evidence_id=row.get("global_evidence_id"),
            conditional_evidence_id=row.get("conditional_evidence_id"),
            eligibility_status=str(row["eligibility_status"]),
            rejection_reasons=tuple(json.loads(str(row.get("rejection_reasons_json") or "[]"))),
            performance_score=float(row["performance_score"]),
            downside_score=float(row["downside_score"]),
            fold_consistency_score=float(row["fold_consistency_score"]),
            parameter_robustness_score=float(row["parameter_robustness_score"]),
            cost_robustness_score=float(row["cost_robustness_score"]),
            breadth_score=float(row["breadth_score"]),
            paper_score=float(row["paper_score"]),
            regime_compatibility_score=float(row["regime_compatibility_score"]),
            asset_compatibility_score=float(row["asset_compatibility_score"]),
            drawdown_penalty=float(row["drawdown_penalty"]),
            turnover_penalty=float(row["turnover_penalty"]),
            correlation_penalty=float(row["correlation_penalty"]),
            capacity_penalty=float(row["capacity_penalty"]),
            uncertainty_penalty=float(row["uncertainty_penalty"]),
            overall_score=float(row["overall_score"]),
            available_at=pd.Timestamp(row["available_at"]).to_pydatetime(),
            scorecard_version=str(row["scorecard_version"]),
            scorecard_policy_version=str(row["scorecard_policy_version"]),
            scorecard_policy_hash=str(row["scorecard_policy_hash"]),
            evidence_hash=str(row["evidence_hash"]),
            evidence_ids=json.loads(str(row.get("evidence_ids_json") or "{}")),
            explanation=json.loads(str(row.get("explanation_json") or "{}")),
        )


class MetaSelectorBacktest:
    """Replay adaptive selection as one continuous historical portfolio process."""

    def __init__(
        self,
        selector: AdaptiveStrategySelector,
        *,
        cost_estimator: SwitchCostEstimator | None = None,
        replay_policy: MetaReplayPolicy | None = None,
        resolver: HistoricalEvidenceResolver | None = None,
        execution_adapter: PortfolioEventBacktester | None = None,
        risk_engine: RiskEngine | None = None,
        db: Any | None = None,
    ) -> None:
        self.selector = selector
        self.cost_estimator = cost_estimator or SwitchCostEstimator()
        self.replay_policy = replay_policy or MetaReplayPolicy()
        self.resolver = resolver
        self.execution_adapter = execution_adapter or PortfolioEventBacktester(
            max_position_weight=1.0,
            max_gross_exposure=1.0,
            max_sector_exposure=1.0,
            db=db,
        )
        self.risk_engine = risk_engine or RiskEngine(RiskPolicy())
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
        data_hash: str = "synthetic",
        cost_model_hash: str | None = None,
        checkpoint: MetaSelectorCheckpoint | None = None,
        frozen_policy_id: str | None = None,
        _skip_final_oos_validation: bool = False,
    ) -> MetaSelectorResult:
        items = tuple(sorted((self._coerce(item) for item in observations), key=lambda item: item.decision_time))
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if cost_multiplier <= 0 or liquidity_multiplier <= 0:
            raise ValueError("cost and liquidity multipliers must be positive")
        if self.resolver is not None:
            items = tuple(self.resolver.observation_at(item.decision_time, template=item) for item in items)
        effective_policy_version = policy_version or self.replay_policy.version
        self._validate_causal_inputs(items)
        if any(item.data_hash != data_hash for item in items):
            raise ValueError("observation data_hash must match replay data_hash")
        self._validate_future_trials(items)
        effective_cost_model_hash = cost_model_hash or self._cost_model_hash(self._stressed_cost_schedule(cost_multiplier, items[0].decision_time if items else datetime.now(timezone.utc)))
        if not _skip_final_oos_validation:
            self._validate_final_oos_trial_binding(
                items,
                meta_split,
                registered_trial_id,
                trial_created_at,
                data_hash=data_hash,
                cost_model_hash=effective_cost_model_hash,
                purge_periods=purge_periods,
                embargo_periods=embargo_periods,
                policy_version=effective_policy_version,
                frozen_policy_id=frozen_policy_id,
            )
        self._validate_purge_embargo(items, purge_periods, embargo_periods)
        cash = float(initial_equity if checkpoint is None else checkpoint.cash)
        quantities: dict[str, float] = dict(checkpoint.holdings) if checkpoint else {}
        cost_basis: dict[str, float] = dict(checkpoint.cost_basis) if checkpoint else {}
        entry_timestamps: dict[str, pd.Timestamp] = {}
        entry_reasons: dict[str, str] = {}
        entry_cost_pools: dict[str, float] = {}
        entry_execution_cost_pools: dict[str, float] = {}
        last_prices: dict[str, float] = dict(checkpoint.market_prices) if checkpoint else {symbol: 100.0 for symbol in quantities}
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
        previous_equity = cash + sum(quantity * last_prices.get(symbol, 100.0) for symbol, quantity in quantities.items())
        peak_equity = float(checkpoint.peak_equity) if checkpoint and checkpoint.peak_equity is not None else previous_equity
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        risk_rows: list[dict[str, Any]] = []
        last_period_pnl = 0.0

        for index, item in enumerate(items):
            raw_regimes.append(item.raw_regime or item.market_regime)
            operational_regimes.append(item.operational_regime or item.market_regime)
            execution_item = items[min(index + delay_periods, len(items) - 1)]
            day = self._execution_day(execution_item, item.decision_time, liquidity_multiplier=liquidity_multiplier)
            current_weights = self._weights_from_quantities(quantities, last_prices, previous_equity)
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
            gated_targets, risk_batch = self._risk_gate_targets(
                current_weights=current_weights,
                target_weights=target_weights,
                portfolio_value=max(previous_equity, 1e-12),
                item=execution_item,
                day=day,
                prior_returns=tuple(returns) + tuple(item.prior_asset_returns.values()),
                daily_pnl=last_period_pnl,
                current_drawdown=max(0.0, 1.0 - previous_equity / max(peak_equity, 1e-12)),
            )
            risk_rows.extend(risk_batch)
            cash, generated = self.execution_adapter.execute_historical_rebalance(
                run_id=f"meta-{effective_policy_version}",
                date=pd.Timestamp(day["timestamp"].iloc[0]),
                day=day,
                targets=self._targets_frame(gated_targets, execution_item.decision_time),
                cash=cash,
                quantities=quantities,
                average_cost=cost_basis,
                entry_timestamps=entry_timestamps,
                entry_reasons=entry_reasons,
                entry_cost_pools=entry_cost_pools,
                entry_execution_cost_pools=entry_execution_cost_pools,
                last_prices=last_prices,
                mode="event-driven",
                cost_schedule=self._stressed_cost_schedule(cost_multiplier, execution_item.decision_time),
            )
            self._determinize_execution_ids(generated, item.decision_time)
            self._attach_execution_lineage(generated, item, execution_item, day)
            orders.extend(generated["orders"])
            fills.extend(generated["fills"])
            for risk_row in risk_batch:
                risk_row["order_ids"] = tuple(order["order_id"] for order in generated["orders"] if order["symbol"] == risk_row["symbol"])
                risk_row["fill_ids"] = tuple(fill["fill_id"] for fill in generated["fills"] if fill["symbol"] == risk_row["symbol"])
                risk_row["executed_notional"] = float(sum(fill["quantity"] * fill["price"] for fill in generated["fills"] if fill["symbol"] == risk_row["symbol"]))
            for symbol, row in day.iterrows():
                last_prices[str(symbol)] = float(row["close"])
            market_value = sum(quantity * last_prices.get(symbol, 0.0) for symbol, quantity in quantities.items())
            ending_equity = cash + market_value
            period_cost = float(sum(row.get("total_cost", 0.0) for row in generated["costs"]))
            period_slippage = float(sum(order.get("slippage_bps", 0.0) for order in generated["orders"]))
            period_turnover = abs(float(generated.get("rebalance", {}).get("buy_turnover", 0.0))) + abs(float(generated.get("rebalance", {}).get("sell_turnover", 0.0)))
            cumulative_costs += period_cost
            turnover += period_turnover / max(previous_equity, 1e-12)
            slippage += period_slippage
            realized_costs += period_cost
            net_return = float(ending_equity / previous_equity - 1.0) if previous_equity else 0.0
            returns.append(net_return)
            decisions.append(decision)
            if decision.decision == ABSTAIN:
                best_return = self._target_return(provisional_target, execution_item.asset_returns)
                abstain_return += net_return
                skipped_opportunities += max(best_return, 0.0)
                risk_avoided += max(-best_return, 0.0)
            if period_turnover > 0:
                switches.append(
                    {
                        "decision_time": item.decision_time,
                        "old_strategy": incumbent,
                        "new_strategy": ",".join(decision.selected_strategies),
                        "switching_cost": float(period_cost / max(previous_equity, 1e-12)),
                        "sells_first": tuple(order["symbol"] for order in generated["orders"] if order["side"] == "SELL"),
                        "buys_after_sells": tuple(order["symbol"] for order in generated["orders"] if order["side"] == "BUY"),
                        "turnover": float(period_turnover / max(previous_equity, 1e-12)),
                        "slippage": float(period_slippage),
                    }
                )
            if decision.decision != ABSTAIN and decision.selected_strategies:
                incumbent = decision.selected_strategies[0]
            previous_decision_id = decision.selector_decision_id
            current_weights = self._weights_from_quantities(quantities, last_prices, ending_equity)
            equity_rows.append(
                {
                    "timestamp": item.decision_time,
                    "cash": cash,
                    "holdings": dict(quantities),
                    "equity": ending_equity,
                    "net_return": net_return,
                    "drawdown": 0.0,
                    "position": sum(abs(value) for value in current_weights.values()),
                    "decision": decision.decision,
                    "turnover": float(period_turnover / max(previous_equity, 1e-12)),
                    "execution_cost": float(period_cost),
                    "slippage": float(period_slippage),
                }
            )
            period_pnl = ending_equity - previous_equity
            previous_equity = ending_equity
            last_period_pnl = period_pnl
            peak_equity = max(peak_equity, ending_equity)

        self._attach_drawdowns(equity_rows, initial_equity, peak_equity=max(peak_equity, initial_equity))
        checkpoint_out = MetaSelectorCheckpoint(
            cash=cash,
            holdings=dict(quantities),
            cost_basis=cost_basis,
            incumbent_strategy=incumbent,
            previous_selector_decision_id=previous_decision_id,
            last_processed_timestamp=equity_rows[-1]["timestamp"] if equity_rows else last_processed,
            policy_versions={
                "meta_replay": self.replay_policy.version,
                "selector": self.selector.policy.version,
                "scorecard_policy_hash": self._canonical_visible_scorecard_policy_hash(items),
            },
            cumulative_costs=cumulative_costs,
            market_prices=dict(last_prices),
            pending_orders=tuple(checkpoint.pending_orders if checkpoint else ()),
            pending_fills=tuple(checkpoint.pending_fills if checkpoint else ()),
            peak_equity=peak_equity,
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
        metrics["decision_count"] = float(len(decisions))
        metrics["trade_count"] = float(len(fills))
        metrics["evidence_coverage"] = float(sum(any(card.available_at <= item.decision_time for card in item.scorecards) for item in items) / max(len(items), 1))
        baselines = self._baselines(items, initial_equity, metrics)
        stress_results = (
            {
                "1.0x_cost": {"total_return": metrics["total_return"]},
                "1.5x_cost": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, cost_multiplier=1.5, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at, data_hash=data_hash, cost_model_hash=cost_model_hash, _skip_final_oos_validation=True).metrics["total_return"]},
                "2.0x_cost": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, cost_multiplier=2.0, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at, data_hash=data_hash, cost_model_hash=cost_model_hash, _skip_final_oos_validation=True).metrics["total_return"]},
                "switch_cost_stress": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, cost_multiplier=2.0, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at, data_hash=data_hash, cost_model_hash=cost_model_hash, _skip_final_oos_validation=True).metrics["total_return"]},
                "delayed_execution": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, delay_periods=1, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at, data_hash=data_hash, cost_model_hash=cost_model_hash, _skip_final_oos_validation=True).metrics["total_return"]} if len(items) > 1 else {"total_return": metrics["total_return"]},
                "reduced_liquidity": {"total_return": self.run(items, initial_equity=initial_equity, meta_split=meta_split, liquidity_multiplier=0.5, include_stress=False, registered_trial_id=registered_trial_id, trial_created_at=trial_created_at, data_hash=data_hash, cost_model_hash=cost_model_hash, _skip_final_oos_validation=True).metrics["total_return"]},
            }
            if include_stress
            else {"1.0x_cost": {"total_return": metrics["total_return"]}}
        )
        baselines["B5_adaptive"] = {"total_return": metrics["total_return"], "selection": "adaptive_selector"}
        verdict = self._verdict(metrics, baselines, len(items), stress_results, meta_split)
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
            "data_hash": data_hash,
            "cost_model_hash": effective_cost_model_hash,
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
            orders=tuple(orders),
            fills=tuple(fills),
            risk_decisions=tuple(risk_rows),
        )

    def _coerce(self, item: MetaSelectorObservation | dict[str, Any]) -> MetaSelectorObservation:
        if isinstance(item, MetaSelectorObservation):
            return item
        values = dict(item)
        values["scorecards"] = tuple(values.get("scorecards", ()))
        values["asset_returns"] = dict(values.get("asset_returns", {}))
        values["prices"] = dict(values.get("prices", {}))
        values["sectors"] = dict(values.get("sectors", {}))
        values["historical_bars"] = tuple(values.get("historical_bars", ()))
        values["prior_asset_returns"] = dict(values.get("prior_asset_returns", {}))
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
            if item.execution_data_available_at is not None and item.execution_data_available_at > item.decision_time:
                raise ValueError("execution data availability cannot be after selector decision")

    def _validate_future_trials(self, items: tuple[MetaSelectorObservation, ...]) -> None:
        if self.db is None:
            return
        for item in items:
            for trial_id in item.future_trial_ids:
                trial = self.db.get_research_trial(trial_id)
                if trial is None:
                    continue
                created_at = cast(datetime, trial["created_at"])
                if created_at <= item.decision_time:
                    raise ValueError("historical replay cannot consume a trial available at decision time")

    def _validate_final_oos_trial_binding(
        self,
        items: tuple[MetaSelectorObservation, ...],
        meta_split: str,
        registered_trial_id: str | None,
        trial_created_at: datetime | None,
        *,
        data_hash: str,
        cost_model_hash: str,
        purge_periods: int,
        embargo_periods: int,
        policy_version: str,
        frozen_policy_id: str | None = None,
    ) -> None:
        if meta_split != "FINAL_OOS":
            return
        final_items = [item for item in items if item.meta_split == "FINAL_OOS"]
        if not final_items:
            return
        if registered_trial_id is None or (trial_created_at is None and frozen_policy_id is None):
            raise ValueError("FINAL_OOS requires pre-registered meta-selector trial")
        if self.db is None:
            raise ValueError("FINAL_OOS requires Phase 2.1 trial registry access")
        trial = self.db.get_research_trial(registered_trial_id) if self.db is not None else None
        if trial is None:
            raise ValueError("FINAL_OOS requires a real Phase 2.1 research trial")
        trial_created_at = cast(datetime, trial["created_at"])
        first_final = min(item.decision_time for item in final_items)
        if frozen_policy_id is not None:
            artifact = self.db.load_frozen_meta_policy(frozen_policy_id)
            expected_artifact = {
                "selected_trial_id": registered_trial_id,
                "selector_policy_version": self.selector.policy.version,
                "selector_policy_hash": self.selector.policy.policy_hash,
                "meta_policy_version": self.replay_policy.version,
                "meta_policy_hash": self.replay_policy.policy_hash,
                "data_hash": data_hash,
                "cost_model_hash": cost_model_hash,
                "purge_periods": purge_periods,
                "embargo_periods": embargo_periods,
            }
            for key, value in expected_artifact.items():
                if artifact.get(key) != value:
                    raise ValueError(f"FINAL_OOS frozen policy binding mismatch: {key}")
            frozen_timestamp = pd.Timestamp(artifact["frozen_at"]).to_pydatetime()
            if frozen_timestamp >= first_final or trial_created_at >= first_final:
                raise ValueError("frozen meta policy must be registered before FINAL_OOS begins")
            return
        parameters = dict(trial.get("parameters") or {})
        scorecard_policy_hash = _canonical_hash(
            sorted({card.scorecard_policy_hash for item in final_items for card in item.scorecards if card.available_at <= item.decision_time})
        )
        expected = {
                "selector_policy_version": self.selector.policy.version,
                "selector_policy_hash": self.selector.policy.policy_hash,
                "scorecard_policy_hash": scorecard_policy_hash,
                "meta_replay_policy_version": self.replay_policy.version,
                "meta_replay_policy_hash": self.replay_policy.policy_hash,
                "meta_policy_version": policy_version,
                "data_hash": data_hash,
                "cost_model_hash": cost_model_hash,
                "purge_periods": purge_periods,
                "embargo_periods": embargo_periods,
                "meta_split": meta_split,
                "strategy_universe": sorted({
                    card.strategy_name
                    for item in final_items
                    for card in item.scorecards
                    if card.available_at <= item.decision_time
                }),
        }
        for key, value in expected.items():
            if parameters.get(key) != value:
                raise ValueError(f"FINAL_OOS trial binding mismatch: {key}")
        if trial_created_at.tzinfo is None:
            raise ValueError("trial_created_at must be timezone-aware")
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
                left_windows = (left.label_start, left.label_end, left.evidence_start, left.evidence_end)
                right_windows = (right.label_start, right.label_end, right.evidence_start, right.evidence_end)
                if any(value is None for value in (*left_windows, *right_windows)):
                    raise ValueError("explicit label and evidence windows are required for split purge/embargo")
                left_label_end = cast(datetime, left.label_end)
                right_label_start = cast(datetime, right.label_start)
                left_evidence_end = cast(datetime, left.evidence_end)
                right_evidence_start = cast(datetime, right.evidence_start)
                if left_label_end > right_label_start or left_evidence_end > right_evidence_start:
                    raise ValueError("purge/embargo windows overlap across meta splits")

    @staticmethod
    def _canonical_visible_scorecard_policy_hash(items: tuple[MetaSelectorObservation, ...]) -> str:
        return _canonical_hash(
            sorted({
                card.scorecard_policy_hash
                for item in items
                for card in item.scorecards
                if card.available_at <= item.decision_time
            })
        )

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

    def _risk_gate_targets(
        self,
        *,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        portfolio_value: float,
        item: MetaSelectorObservation,
        day: pd.DataFrame,
        prior_returns: tuple[float, ...],
        daily_pnl: float,
        current_drawdown: float,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        adjusted = dict(current_weights)
        rows: list[dict[str, Any]] = []
        symbols = sorted(set(current_weights) | set(target_weights))
        symbols.sort(key=lambda symbol: float(target_weights.get(symbol, 0.0)) - float(current_weights.get(symbol, 0.0)))
        daily_turnover_crore = 0.0
        current_gross_exposure = sum(abs(value) * portfolio_value for value in adjusted.values())
        for symbol in symbols:
            current_weight = float(adjusted.get(symbol, 0.0))
            target_weight = float(target_weights.get(symbol, 0.0))
            delta_weight = target_weight - current_weight
            requested_notional = abs(delta_weight) * portfolio_value
            if requested_notional <= 1e-9:
                continue
            side = OrderSide.BUY if delta_weight > 0 else OrderSide.SELL
            proposal = TradeProposal(
                symbol=symbol,
                sector=item.sectors.get(symbol, "UNKNOWN"),
                requested_notional=requested_notional,
                capital=portfolio_value,
                current_position_notional=current_weight * portfolio_value,
                order_side=side,
                current_gross_exposure=current_gross_exposure,
                current_sector_exposure=sum(abs(value) * portfolio_value for key, value in adjusted.items() if item.sectors.get(key, "UNKNOWN") == item.sectors.get(symbol, "UNKNOWN")),
                daily_pnl=daily_pnl,
                current_drawdown=current_drawdown,
                open_position_count=sum(1 for value in adjusted.values() if abs(value) > 1e-12),
                daily_turnover_crore=daily_turnover_crore,
                estimated_portfolio_var_pct=(float(pd.Series(prior_returns, dtype=float).std(ddof=0) * 2.33) if prior_returns else None),
            )
            decision = self.risk_engine.evaluate(proposal)
            approved_notional = float(decision.approved_notional)
            if decision.action == RiskAction.REJECT:
                executable_weight = current_weight
            else:
                signed = approved_notional / max(portfolio_value, 1e-12)
                executable_weight = current_weight + signed if side == OrderSide.BUY else current_weight - signed
            adjusted[symbol] = max(executable_weight, 0.0)
            liquidity_row = day.loc[symbol] if symbol in day.index else {}
            daily_turnover_crore = float(liquidity_row.get("lagged_traded_value", 0.0) or 0.0) / 10_000_000.0
            rows.append(
                {
                    "timestamp": item.decision_time,
                    "symbol": symbol,
                    "side": side.value,
                    "requested_notional": requested_notional,
                    "approved_notional": approved_notional,
                    "risk_action": decision.action.value,
                    "risk_reasons": tuple(decision.reasons),
                    "executed_notional": 0.0,
                    "order_ids": (),
                    "fill_ids": (),
                }
            )
        return {symbol: weight for symbol, weight in adjusted.items() if weight > 1e-12}, rows

    @staticmethod
    def _targets_frame(target_weights: dict[str, float], timestamp: datetime) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"timestamp": pd.Timestamp(timestamp), "symbol": symbol, "target_weight": weight, "reason": "meta_selector"}
                for symbol, weight in sorted(target_weights.items())
            ],
            columns=["timestamp", "symbol", "target_weight", "reason"],
        )

    @staticmethod
    def _execution_day(item: MetaSelectorObservation, decision_time: datetime, *, liquidity_multiplier: float = 1.0) -> pd.DataFrame:
        if not item.historical_bars:
            raise ValueError("meta replay requires authoritative historical execution bars")
        if item.execution_data_available_at is not None and item.execution_data_available_at > decision_time:
            raise ValueError("execution data is not point-in-time available at selector decision")
        rows = [dict(row) for row in item.historical_bars if pd.Timestamp(row["timestamp"]).to_pydatetime() > decision_time]
        if not rows:
            raise ValueError("no historical execution bar strictly after selector decision")
        if any("dataset_hash" not in row and "data_hash" not in row for row in rows):
            raise ValueError("execution bars require historical dataset lineage")
        for row in rows:
            known_at = row.get("known_at")
            if known_at is not None and pd.Timestamp(known_at).to_pydatetime() > decision_time:
                raise ValueError("historical execution bar was not known at selector decision")
        for row in rows:
            for field_name in ("volume", "lagged_adv20", "lagged_traded_value"):
                if field_name in row and row[field_name] is not None:
                    row[field_name] = float(row[field_name]) * liquidity_multiplier
        return pd.DataFrame(rows).set_index("symbol", drop=False)

    @staticmethod
    def _cost_model_hash(schedule: IndianDeliveryCostSchedule) -> str:
        return _canonical_hash(asdict(schedule))

    def _stressed_cost_schedule(self, multiplier: float, decision_time: datetime) -> IndianDeliveryCostSchedule:
        base = self.execution_adapter.cost_schedule
        if multiplier == 1.0:
            return base
        values = asdict(base)
        values["version"] = f"{base.version}-stress-{multiplier:g}x"
        for key in ("brokerage_rate_bps", "stt_buy_bps", "stt_sell_bps", "exchange_transaction_bps", "sebi_bps", "ipft_bps", "stamp_duty_buy_bps", "spread_bps", "slippage_bps", "impact_bps_at_full_participation"):
            values[key] = float(values[key]) * multiplier
        values["effective_from"] = base.effective_from
        return IndianDeliveryCostSchedule(**values)

    @staticmethod
    def _weights_from_quantities(
        quantities: dict[str, float],
        prices: dict[str, float],
        equity: float,
    ) -> dict[str, float]:
        return {
            symbol: quantity * prices.get(symbol, 100.0) / max(equity, 1e-12)
            for symbol, quantity in quantities.items()
            if abs(quantity) > 1e-12
        }

    @staticmethod
    def _determinize_execution_ids(generated: dict[str, Any], timestamp: datetime) -> None:
        order_map: dict[str, str] = {}
        fill_map: dict[str, str] = {}
        for index, order in enumerate(generated["orders"]):
            old_order_id = str(order["order_id"])
            new_order_id = _canonical_hash(["meta-order", timestamp.isoformat(), index, order["symbol"], order["side"]])[:32]
            order["order_id"] = new_order_id
            order_map[old_order_id] = new_order_id
        for index, fill in enumerate(generated["fills"]):
            old_fill_id = str(fill["fill_id"])
            new_fill_id = _canonical_hash(["meta-fill", timestamp.isoformat(), index, fill["symbol"], fill["side"]])[:32]
            fill["fill_id"] = new_fill_id
            fill["order_id"] = order_map.get(str(fill["order_id"]), str(fill["order_id"]))
            fill_map[old_fill_id] = new_fill_id
        for cost in generated["costs"]:
            cost["fill_id"] = fill_map.get(str(cost.get("fill_id")), str(cost.get("fill_id")))

    @staticmethod
    def _attach_execution_lineage(
        generated: dict[str, Any],
        decision_item: MetaSelectorObservation,
        execution_item: MetaSelectorObservation,
        day: pd.DataFrame,
    ) -> None:
        execution_timestamp = pd.Timestamp(day["timestamp"].iloc[0]).to_pydatetime()
        dataset_hashes = sorted({str(row.get("dataset_hash", row.get("data_hash", execution_item.data_hash))) for row in day.to_dict("records")})
        records = day.to_dict("records")
        lineage = {
            "selector_decision_time": decision_item.decision_time,
            "execution_timestamp": execution_timestamp,
            "symbol": None,
            "historical_dataset_hash": _canonical_hash(dataset_hashes),
            "historical_bar_hash": _canonical_hash(records),
            "data_hash": execution_item.data_hash,
            "execution_data_available_at": execution_item.execution_data_available_at,
            "execution_data_known_at": max((row.get("known_at") for row in records if row.get("known_at") is not None), default=None),
        }
        for record in (*generated.get("orders", []), *generated.get("fills", [])):
            record["execution_lineage"] = {**lineage, "symbol": record.get("symbol")}

    @staticmethod
    def _target_return(target_weights: dict[str, float], asset_returns: dict[str, float]) -> float:
        return sum(float(weight) * float(asset_returns.get(symbol, 0.0)) for symbol, weight in target_weights.items())

    @staticmethod
    def _attach_drawdowns(rows: list[dict[str, Any]], initial_equity: float, *, peak_equity: float | None = None) -> None:
        peak = max(initial_equity, peak_equity or initial_equity)
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
        train_items = [item for item in items if item.meta_split == "TRAIN"]
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
            "B2_static": {
                "total_return": MetaSelectorBacktest._compound(static_returns) if static_winner else 0.0,
                "selection": static_winner or "UNAVAILABLE_NO_META_TRAIN",
            },
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

    def _verdict(
        self,
        metrics: dict[str, float],
        baselines: dict[str, dict[str, float | str]],
        observation_count: int,
        stress_results: dict[str, dict[str, float]],
        meta_split: str,
    ) -> str:
        if meta_split != "FINAL_OOS":
            return "PHASE 2.10 IMPLEMENTATION READY"
        simple_best = max(
            float(baselines[name]["total_return"])
            for name in ("B2_static", "B3_equal_ensemble", "B4_risk_balanced")
        )
        if metrics.get("decision_count", 0.0) < 1 or metrics.get("trade_count", 0.0) < 1 or metrics.get("evidence_coverage", 0.0) < 1.0:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if metrics["total_return"] <= simple_best:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if observation_count < self.replay_policy.min_final_oos_observations:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if metrics["switch_count"] / max(observation_count, 1) > self.replay_policy.max_switch_rate:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if metrics["max_drawdown"] < -self.replay_policy.max_drawdown:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if metrics["total_return"] - simple_best <= self.replay_policy.min_net_edge:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        if stress_results.get("2.0x_cost", {}).get("total_return", metrics["total_return"]) < simple_best:
            return "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"
        return "ADAPTIVE_SELECTOR_RESEARCH_PASS"
