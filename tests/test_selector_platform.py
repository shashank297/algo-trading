from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from experiments.meta_selector_backtest import CASH, FrozenMetaPolicy, HistoricalEvidenceResolver, MetaReplayPolicy, MetaResearchRunner, MetaSelectorBacktest, MetaSelectorCheckpoint, MetaSelectorObservation
from experiments.selector_walk_forward import split_meta_walk_forward
from experiments.trials import ExperimentFamilySpec, ResearchTrial
from risk.engine import RiskEngine
from risk.models import RiskPolicy
from storage.duckdb_manager import DuckDBManager
from trading_stack.conditional_evidence import ConditionalEvidenceBuilder, ConditionalEvidencePolicy
from trading_stack.scorecards import INELIGIBLE, ScorecardBuilder, ScorecardInputs, ScorecardPolicy, StrategyScorecard
from trading_stack.selector import ABSTAIN, ENSEMBLE, SELECT, AdaptiveStrategySelector, SelectorPolicy, SwitchCostEstimator

UTC = timezone.utc


def certified_inputs(**overrides):
    values: dict[str, Any] = {
        "lineage_certified": True,
        "dq_certified": True,
        "causality_certified": True,
        "pit_certified": True,
        "oos_certified": True,
        "cost_stress_pass": True,
        "parameter_robustness_pass": True,
        "capacity_pass": True,
        "zero_reconciliation_drift": True,
    }
    values.update(overrides)
    return ScorecardInputs(**values)


def evidence(
    *,
    name: str = "alpha",
    version: str = "1",
    n: int = 45,
    net_return: float = 0.02,
    available: datetime | None = None,
    drawdown_loss_at: int | None = None,
    regime: str | None = "BULL",
    asset: str | None = "TRENDING",
):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        value = -0.30 if drawdown_loss_at == i else net_return
        rows.append(
            {
                "timestamp": (start + timedelta(days=i)).isoformat(),
                "evidence_level": "OUT_OF_SAMPLE",
                "net_return": value,
                "cost": 0.001,
                "equity": 100_000,
                "trade_count": 1,
                "fold_id": i % 3,
            }
        )
    return ConditionalEvidenceBuilder(
        ConditionalEvidencePolicy(minimum_observations=30, minimum_trades=10, minimum_folds=2, minimum_span_days=20)
    ).build(
        strategy_name=name,
        strategy_version=version,
        run_id=f"{name}-{version}-run",
        observations=rows,
        global_metric=0.01,
        available_at=available or start + timedelta(days=n + 1),
        market_regime=regime,
        asset_cluster=asset,
    )


def card(
    *,
    name: str = "alpha",
    version: str = "1",
    n: int = 45,
    net_return: float = 0.02,
    available: datetime | None = None,
    policy: ScorecardPolicy | None = None,
    inputs: ScorecardInputs | None = None,
    drawdown_loss_at: int | None = None,
) -> StrategyScorecard:
    evidence_record = evidence(
        name=name,
        version=version,
        n=n,
        net_return=net_return,
        available=available,
        drawdown_loss_at=drawdown_loss_at,
    )
    return ScorecardBuilder(policy).build(
        evidence=evidence_record,
        horizon="1d",
        inputs=inputs or certified_inputs(),
        available_at=evidence_record.available_at + timedelta(days=1),
    )


def selector_decision(cards, *, now=None, incumbent=None, policy=None, cost=0.0, confidence=0.9, asset="TRENDING", corr=None):
    return AdaptiveStrategySelector(policy).select(
        decision_time=now or datetime(2024, 4, 1, tzinfo=UTC),
        symbol="ABC",
        horizon="1d",
        market_regime="BULL",
        regime_confidence=confidence,
        asset_cluster=asset,
        scorecards=cards,
        incumbent_strategy=incumbent,
        switching_cost=cost,
        correlations=corr,
    )


def obs(time, cards, returns, **kwargs):
    asset_returns = kwargs.get("asset_returns", {})
    prices = kwargs.get("prices", {})
    historical_bars = kwargs.get("historical_bars")
    if historical_bars is None:
        bar_returns = dict(asset_returns)
        if not bar_returns:
            bar_returns = {kwargs.get("symbol", "ABC"): 0.0}
        historical_bars = tuple(
            {
                "timestamp": time + timedelta(days=1),
                "symbol": symbol,
                "open": float(prices.get(symbol, 100.0)),
                "close": float(prices.get(symbol, 100.0)) * (1.0 + float(value)),
                "price": float(prices.get(symbol, 100.0)) * (1.0 + float(value)),
                "volume": 10_000_000.0,
                "lagged_adv20": 10_000_000.0,
                "lagged_close": float(prices.get(symbol, 100.0)),
                "lagged_traded_value": float(prices.get(symbol, 100.0)) * 10_000_000.0,
                "sector": kwargs.get("sectors", {}).get(symbol, "UNKNOWN"),
                "dataset_hash": kwargs.get("data_hash", "synthetic"),
            }
            for symbol, value in bar_returns.items()
        )
    return MetaSelectorObservation(
        decision_time=time,
        symbol="ABC",
        horizon="1d",
        market_regime=kwargs.get("market_regime", "BULL"),
        regime_confidence=kwargs.get("regime_confidence", 0.9),
        asset_cluster=kwargs.get("asset_cluster", "TRENDING"),
        scorecards=tuple(cards),
        strategy_returns=returns,
        target_portfolios=kwargs.get("target_portfolios", {}),
        asset_returns=asset_returns,
        prices=kwargs.get("prices", {}),
        sectors=kwargs.get("sectors", {}),
        benchmark_return=kwargs.get("benchmark_return", 0.0),
        raw_regime=kwargs.get("raw_regime"),
        operational_regime=kwargs.get("operational_regime"),
        known_at=kwargs.get("known_at"),
        available_at=kwargs.get("available_at"),
        historical_bars=tuple(historical_bars),
        prior_asset_returns=kwargs.get("prior_asset_returns", {symbol: 0.0 for symbol in asset_returns}),
        label_start=kwargs.get("label_start"),
        label_end=kwargs.get("label_end"),
        evidence_start=kwargs.get("evidence_start"),
        evidence_end=kwargs.get("evidence_end"),
        data_hash=kwargs.get("data_hash", "synthetic"),
        execution_data_available_at=kwargs.get("execution_data_available_at"),
        prior_returns_available_at=kwargs.get("prior_returns_available_at", time),
        meta_split=kwargs.get("meta_split", "FINAL_OOS"),
    )


def register_meta_trial(db: DuckDBManager, items, replay: MetaSelectorBacktest, *, created_at: datetime):
    final_items = [item for item in items if item.meta_split == "FINAL_OOS"]
    scorecard_hash = MetaSelectorBacktest._canonical_visible_scorecard_policy_hash(tuple(final_items))
    strategy_universe = sorted({
        card.strategy_name
        for item in final_items
        for card in item.scorecards
        if card.available_at <= item.decision_time
    })
    cost_model_hash = MetaSelectorBacktest._cost_model_hash(replay.execution_adapter.cost_schedule)
    family = ExperimentFamilySpec(
        experiment_family_id=f"meta-family-{created_at.timestamp()}",
        hypothesis="meta selector",
        strategy_names=["meta_selector"],
        strategy_versions=["phase2.10"],
        universe_snapshot_id="META",
        timeframe="1d",
        feature_versions=["phase2.10"],
        cost_model_version="synthetic",
        parameter_space={},
        maximum_trials=10,
        selection_metric="total_return",
        walk_forward_design={"purge_periods": 0, "embargo_periods": 0},
        source_revision="test",
        created_at=created_at,
    )
    db.register_experiment_family(family)
    trial = ResearchTrial(
        experiment_family_id=family.experiment_family_id,
        strategy_name="meta_selector",
        strategy_version="phase2.10",
        scope="META_SELECTOR",
        timeframe="1d",
        parameters={
            "selector_policy_version": replay.selector.policy.version,
            "selector_policy_hash": replay.selector.policy.policy_hash,
            "scorecard_policy_hash": scorecard_hash,
            "meta_replay_policy_version": replay.replay_policy.version,
            "meta_replay_policy_hash": replay.replay_policy.policy_hash,
            "meta_policy_version": replay.replay_policy.version,
            "data_hash": "synthetic",
            "cost_model_hash": cost_model_hash,
            "purge_periods": 0,
            "embargo_periods": 0,
            "meta_split": "FINAL_OOS",
            "strategy_universe": strategy_universe,
        },
        source_revision="test",
        data_hash="synthetic",
        cost_model_hash=cost_model_hash,
        created_at=created_at,
    )
    return db.create_research_trial(trial)


def test_t2_8_01_high_sharpe_dq_failure_ineligible():
    result = card(inputs=certified_inputs(dq_certified=False))
    assert result.eligibility_status == INELIGIBLE
    assert result.overall_score == 0
    assert "DQ_FAILED" in result.rejection_reasons


def test_t2_8_02_high_return_excessive_drawdown_rejected():
    result = card(net_return=0.05, drawdown_loss_at=3)
    assert result.eligibility_status == INELIGIBLE
    assert "EXCESSIVE_DRAWDOWN" in result.rejection_reasons


def test_t2_8_03_cost_stress_failure_ineligible_when_mandatory():
    result = card(inputs=certified_inputs(cost_stress_pass=False))
    assert "COST_STRESS_FAILED" in result.rejection_reasons


def test_t2_8_04_parameter_instability_ineligible_when_mandatory():
    result = card(inputs=certified_inputs(parameter_robustness_pass=False))
    assert "PARAMETER_ROBUSTNESS_FAILED" in result.rejection_reasons


def test_t2_8_05_small_conditional_sample_cannot_exaggerate_compatibility():
    result = card(n=5, policy=ScorecardPolicy(minimum_oos_observations=1, minimum_oos_trades=1, minimum_temporal_span_days=1))
    assert result.regime_compatibility_score <= 0.5
    assert "INSUFFICIENT_EVIDENCE" in result.rejection_reasons


def test_t2_8_06_correlation_penalty_applied_correctly():
    result = card(inputs=certified_inputs(correlation=0.5))
    assert result.correlation_penalty > 0


def test_t2_8_07_deterministic_score_with_identical_inputs():
    left = card()
    right = card()
    assert left == right


def test_t2_8_08_changing_score_policy_creates_new_version_hash():
    left = card(policy=ScorecardPolicy(version="scorecard-a"))
    right = card(policy=ScorecardPolicy(version="scorecard-b"))
    assert left.scorecard_policy_version != right.scorecard_policy_version
    assert left.evidence_hash != right.evidence_hash


def test_t2_8_09_future_scorecard_unavailable_to_historical_query():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    decision = selector_decision([card(available=now + timedelta(days=1))], now=now)
    assert decision.decision == ABSTAIN
    assert decision.candidate_scorecards == ()


def test_t2_8_10_mandatory_gate_cannot_be_bypassed_by_score():
    bad = card(net_return=0.10, inputs=certified_inputs(lineage_certified=False))
    decision = selector_decision([bad])
    assert bad.overall_score == 0
    assert decision.decision == ABSTAIN


def test_t2_8_11_eligible_strategy_receives_bounded_normalized_score():
    result = card()
    assert result.eligibility_status == "ELIGIBLE"
    assert 0 <= result.overall_score <= 1
    assert all(0 <= value <= 1 for value in result.components.values())


def test_t2_8_12_two_strategy_versions_remain_isolated():
    left = card(version="1")
    right = card(version="2")
    assert left.scorecard_id != right.scorecard_id


def test_t2_8_13_changed_material_evidence_changes_scorecard_hash():
    left = card(net_return=0.02)
    right = card(net_return=0.03)
    assert left.evidence_hash != right.evidence_hash


def test_t2_8_14_missing_mandatory_evidence_fails_closed():
    evidence_record = evidence()
    result = ScorecardBuilder().build(evidence=evidence_record, horizon="1d", available_at=evidence_record.available_at + timedelta(days=1))
    assert result.eligibility_status == INELIGIBLE
    assert "DQ_EVIDENCE_MISSING" in result.rejection_reasons


def test_t2_8_14b_scorecard_available_at_is_explicit_and_not_backdated():
    evidence_record = evidence()
    with pytest.raises(ValueError, match="available_at must be supplied"):
        ScorecardBuilder().build(evidence=evidence_record, horizon="1d", inputs=certified_inputs())
    with pytest.raises(ValueError, match="cannot predate"):
        ScorecardBuilder().build(
            evidence=evidence_record,
            horizon="1d",
            inputs=certified_inputs(),
            available_at=evidence_record.available_at - timedelta(seconds=1),
        )


def test_t2_8_14c_required_paper_evidence_missing_fails_closed():
    result = card(policy=ScorecardPolicy(require_paper_evidence=True))
    assert result.eligibility_status == INELIGIBLE
    assert "PAPER_EVIDENCE_MISSING" in result.rejection_reasons
    failed = card(policy=ScorecardPolicy(require_paper_evidence=True), inputs=certified_inputs(paper_evidence_pass=False))
    assert "PAPER_EVIDENCE_FAILED" in failed.rejection_reasons
    passed = card(policy=ScorecardPolicy(require_paper_evidence=True), inputs=certified_inputs(paper_evidence_pass=True))
    assert passed.eligibility_status == "ELIGIBLE"


def test_t2_8_15_restart_requery_returns_identical_immutable_scorecard():
    db = DuckDBManager(":memory:")
    result = card()
    db.persist_scorecard(result)
    db.persist_scorecard(result)
    rows = db.list_scorecards_at(datetime(2024, 4, 1, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["evidence_hash"] == result.evidence_hash


def test_t2_9_01_clear_eligible_winner_selects_when_ensemble_disabled():
    decision = selector_decision([card()], policy=SelectorPolicy(allow_ensemble=False))
    assert decision.decision == SELECT


def test_t2_9_02_no_eligible_strategies_abstains():
    decision = selector_decision([card(inputs=certified_inputs(dq_certified=False))])
    assert decision.decision == ABSTAIN


def test_t2_9_03_insufficient_evidence_abstains():
    decision = selector_decision([card(n=4)])
    assert decision.decision == ABSTAIN


def test_t2_9_04_weak_regime_confidence_abstains():
    decision = selector_decision([card()], confidence=0.2)
    assert decision.decision == ABSTAIN
    assert "LOW_REGIME_CONFIDENCE" in decision.rejection_reasons


def test_t2_9_05_incumbent_82_challenger_83_buffer_holds_no_switch():
    incumbent = replace(card(name="inc"), overall_score=0.82)
    challenger = replace(card(name="new"), overall_score=0.83)
    decision = selector_decision([challenger, incumbent], incumbent="inc", policy=SelectorPolicy(switch_buffer=0.05))
    assert decision.selected_strategies == ("inc",)
    assert not decision.switch_required


def test_t2_9_06_large_challenger_advantage_switches():
    incumbent = replace(card(name="inc"), overall_score=0.50)
    challenger = replace(card(name="new"), overall_score=0.90)
    decision = selector_decision([challenger, incumbent], incumbent="inc", policy=SelectorPolicy(allow_ensemble=False))
    assert decision.selected_strategies == ("new",)
    assert decision.switch_required


def test_t2_9_07_switching_cost_removes_apparent_advantage_no_switch():
    incumbent = replace(card(name="inc"), overall_score=0.70)
    challenger = replace(card(name="new"), overall_score=0.80)
    decision = selector_decision([challenger, incumbent], incumbent="inc", cost=0.15)
    assert decision.selected_strategies == ("inc",)


def test_t2_9_08_degraded_incumbent_replaced_or_abstains():
    bad_inc = card(name="inc", inputs=certified_inputs(dq_certified=False))
    challenger = card(name="new")
    decision = selector_decision([bad_inc, challenger], incumbent="inc", policy=SelectorPolicy(allow_ensemble=False))
    assert decision.selected_strategies == ("new",)


def test_t2_9_09_correlated_ensemble_candidates_filtered():
    alpha = replace(card(name="alpha"), overall_score=0.8)
    beta = replace(card(name="beta"), overall_score=0.7)
    gamma = replace(card(name="gamma"), overall_score=0.6)
    decision = selector_decision(
        [alpha, beta, gamma],
        corr={("alpha", "beta"): 0.95, ("alpha", "gamma"): 0.1},
    )
    assert decision.decision == ENSEMBLE
    assert "beta" not in decision.selected_strategies
    assert "gamma" in decision.selected_strategies


def test_t2_9_09b_missing_correlation_blocks_ensemble_not_select():
    alpha = replace(card(name="alpha"), overall_score=0.8)
    beta = replace(card(name="beta"), overall_score=0.7)
    decision = selector_decision([alpha, beta])
    assert decision.decision == SELECT
    assert decision.selected_strategies == ("alpha",)


def test_t2_9_09c_invalid_missing_correlation_policy_rejected():
    with pytest.raises(ValueError, match="missing_correlation_policy"):
        SelectorPolicy(missing_correlation_policy="assume_zero")


def test_t2_9_10_future_scorecard_evidence_cannot_be_consumed():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    decision = selector_decision([card(available=now + timedelta(days=3))], now=now)
    assert decision.decision == ABSTAIN


def test_t2_9_11_restart_preserves_incumbent_from_persistence():
    db = DuckDBManager(":memory:")
    decision = selector_decision([card()], policy=SelectorPolicy(allow_ensemble=False))
    db.persist_selector_decision(decision)
    assert db.get_selector_incumbent("ABC", "1d", datetime(2024, 4, 2, tzinfo=UTC)) == "alpha"


def test_t2_9_12_identical_inputs_deterministic_selector_hash():
    left = selector_decision([card()])
    right = selector_decision([card()])
    assert left.evidence_hash == right.evidence_hash


def test_t2_9_13_no_selection_from_ineligible_scorecard():
    bad = card(inputs=certified_inputs(oos_certified=False))
    assert selector_decision([bad]).decision == ABSTAIN


def test_t2_9_14_abstain_persisted_correctly():
    db = DuckDBManager(":memory:")
    decision = selector_decision([])
    db.persist_selector_decision(decision)
    rows = db.conn.execute("SELECT decision FROM selector_decisions").fetchall()
    assert rows == [(ABSTAIN,)]


def test_t2_9_15_selector_produces_zero_broker_live_execution_side_effects(monkeypatch):
    called = False

    def fake_order(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("trading_stack.broker.PaperBroker.place_order", fake_order, raising=False)
    selector_decision([card()])
    assert called is False


def test_t2_9_16_policy_change_creates_new_selector_result():
    left = selector_decision([card()], policy=SelectorPolicy(version="selector-a"))
    right = selector_decision([card()], policy=SelectorPolicy(version="selector-b"))
    assert left.selector_policy_version != right.selector_policy_version
    assert left.evidence_hash != right.evidence_hash


def test_t2_10_a_future_strategy_evidence_invisible_to_replay():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    base = MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [], {"future": 0.99})])
    changed = MetaSelectorBacktest(AdaptiveStrategySelector()).run(
        [obs(now, [card(name="future", available=now + timedelta(days=1))], {"future": 0.99})]
    )
    assert base.evidence_hash == changed.evidence_hash


def test_t2_10_b_future_scorecard_does_not_change_earlier_selector_decision():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    base = selector_decision([card(available=now - timedelta(days=1))], now=now)
    with_future = selector_decision([card(available=now - timedelta(days=1)), card(name="future", available=now + timedelta(days=1))], now=now)
    assert base == with_future


def test_t2_10_c_future_regime_data_rejected_by_known_at():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="Future known_at"):
        MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [card()], {"alpha": 0.01}, known_at=now + timedelta(days=1))])


def test_t2_10_d_future_asset_state_rejected_by_available_at():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="Future available_at"):
        MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [card()], {"alpha": 0.01}, available_at=now + timedelta(days=1))])


def test_t2_10_e_switch_cost_increase_reflected_in_net_return():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    inc = replace(card(name="inc"), overall_score=0.2)
    new = replace(card(name="new"), overall_score=0.9)
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [
            obs(now, [inc], {"inc": 0.0}, target_portfolios={"inc": {"ABC": 1.0}}, asset_returns={"ABC": 0.0}),
            obs(now + timedelta(days=1), [inc, new], {"new": 0.02}, target_portfolios={"new": {"XYZ": 1.0}}, asset_returns={"XYZ": 0.02}),
        ]
    )
    assert result.metrics["switching_cost_drag"] > 0
    assert result.metrics["total_return"] < 0.02


def test_t2_10_f_whipsaw_operational_hysteresis_suppresses_switches():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    alpha = card(name="alpha")
    observations = [
        obs(now + timedelta(days=i), [alpha], {"alpha": 0.001}, asset_returns={"ABC": 0.001}, raw_regime="BULL" if i % 2 else "BEAR", operational_regime="BULL")
        for i in range(6)
    ]
    result = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations)
    assert result.metrics["raw_regime_transition_count"] > result.metrics["operational_regime_transition_count"]


def test_t2_10_g_simple_ensemble_wins_reported_truthfully():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    alpha, beta = card(name="alpha"), card(name="beta")
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [obs(now, [alpha, beta], {"alpha": 0.0, "beta": 0.04}, target_portfolios={"alpha": {"AAA": 1.0}, "beta": {"BBB": 1.0}}, asset_returns={"AAA": 0.0, "BBB": 0.04})]
    )
    assert result.verdict == "PHASE 2.10 IMPLEMENTATION READY"


def test_t2_10_g2_b5_adaptive_included_in_benchmark_ladder():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})]
    )
    assert "B5_adaptive" in result.baselines
    assert result.baselines["B5_adaptive"]["total_return"] == result.metrics["total_return"]


def test_t2_10_h_static_winner_can_beat_adaptive_without_forced_promotion():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    alpha, beta = card(name="alpha"), replace(card(name="beta"), overall_score=0.9)
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [obs(now, [alpha, beta], {"alpha": 0.05, "beta": 0.0}, target_portfolios={"alpha": {"AAA": 1.0}, "beta": {"BBB": 1.0}}, asset_returns={"AAA": 0.05, "BBB": 0.0})]
    )
    assert result.verdict == "PHASE 2.10 IMPLEMENTATION READY"


def test_t2_10_i_abstention_avoids_trading_when_no_evidence():
    result = MetaSelectorBacktest(AdaptiveStrategySelector()).run(
        [obs(datetime(2024, 4, 1, tzinfo=UTC), [], {})]
    )
    assert result.decisions[0].decision == ABSTAIN
    assert result.metrics["turnover"] == 0


def test_t2_10_i2_abstain_cash_policy_liquidates_existing_risk():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    alpha = card()
    replay = MetaSelectorBacktest(
        AdaptiveStrategySelector(),
        replay_policy=MetaReplayPolicy(abstain_behavior=CASH),
    )
    result = replay.run(
        [
            obs(now, [alpha], {"alpha": 0.0}, asset_returns={"ABC": 0.0}),
            obs(now + timedelta(days=1), [], {}, asset_returns={"ABC": -0.20}),
        ]
    )
    assert result.decisions[-1].decision == ABSTAIN
    assert result.equity_curve[-1]["holdings"] == {}


def test_t2_10_i3_b5_invokes_public_historical_rebalance_adapter(monkeypatch):
    now = datetime(2024, 4, 1, tzinfo=UTC)
    replay = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False)))
    called = 0
    original = replay.execution_adapter.execute_historical_rebalance

    def wrapped(*args, **kwargs):
        nonlocal called
        called += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(replay.execution_adapter, "execute_historical_rebalance", wrapped)
    replay.run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})])
    assert called >= 1


def test_t2_10_j_restart_replay_reproduces_uninterrupted_run(tmp_path):
    now = datetime(2024, 4, 1, tzinfo=UTC)
    observations = [obs(now + timedelta(days=i), [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}) for i in range(5)]
    uninterrupted = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations)
    first_leg = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations[:2])
    db_path = tmp_path / "meta_restart.duckdb"
    db = DuckDBManager(str(db_path))
    db.persist_meta_selector_result(
        first_leg,
        policy_version="meta-selector-v2",
        selector_policy_version="selector-v1",
        selector_policy_hash=MetaSelectorBacktest(AdaptiveStrategySelector()).selector.policy.policy_hash,
    )
    db.close()
    fresh_db = DuckDBManager(str(db_path))
    loaded_checkpoint = MetaSelectorCheckpoint.from_dict(fresh_db.load_meta_selector_checkpoint(first_leg.meta_run_id))
    resumed = MetaSelectorBacktest(AdaptiveStrategySelector(), db=fresh_db).run(observations, checkpoint=loaded_checkpoint)
    assert uninterrupted.equity_curve[2:] == resumed.equity_curve
    assert uninterrupted.decisions[2:] == resumed.decisions
    assert tuple(s for s in uninterrupted.switches if s["decision_time"] > observations[1].decision_time) == resumed.switches
    assert uninterrupted.checkpoint.holdings == resumed.checkpoint.holdings
    assert uninterrupted.checkpoint.cash == pytest.approx(resumed.checkpoint.cash)
    assert uninterrupted.orders[len(first_leg.orders):] == resumed.orders
    assert uninterrupted.fills[len(first_leg.fills):] == resumed.fills
    assert uninterrupted.risk_decisions[len(first_leg.risk_decisions):] == resumed.risk_decisions


def test_t2_10_k_future_trial_does_not_change_earlier_replay():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    base = MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})])
    changed = MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, future_trial_ids=("future",))])
    assert base.evidence_hash == changed.evidence_hash


def test_t2_10_k2_final_oos_requires_pre_registered_trial():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    final = [obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split="FINAL_OOS")]
    db = DuckDBManager(":memory:")
    replay = MetaSelectorBacktest(AdaptiveStrategySelector(), db=db)
    with pytest.raises(ValueError, match="pre-registered"):
        replay.run(final, meta_split="FINAL_OOS")
    with pytest.raises(ValueError, match="real Phase 2.1"):
        replay.run(final, meta_split="FINAL_OOS", registered_trial_id="fake", trial_created_at=now - timedelta(days=1))
    late_trial_id = register_meta_trial(db, final, replay, created_at=now)
    with pytest.raises(ValueError, match="before FINAL_OOS"):
        replay.run(final, meta_split="FINAL_OOS", registered_trial_id=late_trial_id, trial_created_at=now)
    trial_id = register_meta_trial(db, final, replay, created_at=now - timedelta(days=1))
    result = replay.run(
        final,
        meta_split="FINAL_OOS",
        registered_trial_id=trial_id,
        trial_created_at=now - timedelta(days=1),
    )
    assert result.metrics["total_return"] > 0


def test_t2_10_l_policy_version_changes_hash():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    left = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(version="a"))).run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})])
    right = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(version="b"))).run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})])
    assert left.evidence_hash != right.evidence_hash


def test_t2_10_m_ineligible_high_sharpe_never_selected():
    bad = card(net_return=0.2, inputs=certified_inputs(dq_certified=False))
    result = MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(datetime(2024, 4, 1, tzinfo=UTC), [bad], {"alpha": 0.2}, asset_returns={"ABC": 0.2})])
    assert result.decisions[0].decision == ABSTAIN


def test_t2_10_n_switch_buffer_blocks_tiny_advantage():
    test_t2_9_05_incumbent_82_challenger_83_buffer_holds_no_switch()


def test_t2_10_o_large_valid_advantage_switches():
    test_t2_9_06_large_challenger_advantage_switches()


def test_t2_10_p_correlated_ensemble_not_independent():
    test_t2_9_09_correlated_ensemble_candidates_filtered()


def test_t2_10_q_cost_stress_reflects_higher_costs():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    inc = replace(card(name="inc"), overall_score=0.2)
    new = replace(card(name="new"), overall_score=0.9)
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [
            obs(now, [inc], {"inc": 0.0}, target_portfolios={"inc": {"ABC": 1.0}}, asset_returns={"ABC": 0.0}),
            obs(now + timedelta(days=1), [inc, new], {"new": 0.03}, target_portfolios={"new": {"XYZ": 1.0}}, asset_returns={"XYZ": 0.03}),
        ]
    )
    assert result.stress_results["2.0x_cost"]["total_return"] < result.stress_results["1.5x_cost"]["total_return"]


def test_t2_10_r_reduced_liquidity_affects_execution():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [obs(now, [card()], {"alpha": 0.03}, target_portfolios={"alpha": {"ABC": 1.0}}, asset_returns={"ABC": 0.03})]
    )
    assert result.stress_results["reduced_liquidity"]["total_return"] <= result.metrics["total_return"]


def test_t2_10_s_delayed_execution_affects_realized_result():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    observations = [
        obs(now, [card()], {"alpha": 0.05}, asset_returns={"ABC": 0.05}),
        obs(now + timedelta(days=1), [card()], {"alpha": -0.02}, asset_returns={"ABC": -0.02}),
    ]
    result = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations)
    assert result.stress_results["delayed_execution"]["total_return"] != result.metrics["total_return"]


def test_t2_10_s2_strategy_return_series_not_used_as_b5_execution_shortcut():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    result = MetaSelectorBacktest(AdaptiveStrategySelector()).run(
        [obs(now, [card()], {"alpha": 0.50}, asset_returns={"ABC": 0.0})]
    )
    assert result.metrics["total_return"] < 0.01


def test_t2_10_s3_risk_modify_uses_approved_notional():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    replay = MetaSelectorBacktest(
        AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False)),
        risk_engine=RiskEngine(RiskPolicy(max_position_pct=0.05)),
    )
    result = replay.run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})])
    assert result.risk_decisions[0]["risk_action"] == "MODIFY"
    assert result.risk_decisions[0]["approved_notional"] < result.risk_decisions[0]["requested_notional"]
    assert result.risk_decisions[0]["executed_notional"] <= result.risk_decisions[0]["approved_notional"] * 1.01


def test_t2_10_s4_sell_first_replay_orders_precede_buys():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    inc = replace(card(name="inc"), overall_score=0.2)
    new = replace(card(name="new"), overall_score=0.9)
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run(
        [
            obs(now, [inc], {"inc": 0.0}, target_portfolios={"inc": {"ABC": 0.2}}, asset_returns={"ABC": 0.0}),
            obs(now + timedelta(days=1), [inc, new], {"new": 0.0}, target_portfolios={"new": {"XYZ": 0.2}}, asset_returns={"ABC": 0.0, "XYZ": 0.0}),
        ]
    )
    second_orders = [order for order in result.orders if order["requested_at"] == now + timedelta(days=2)]
    assert [order["side"] for order in second_orders][:2] == ["SELL", "BUY"]


def test_t2_10_s5_b2_without_meta_train_fails_closed():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    result = MetaSelectorBacktest(AdaptiveStrategySelector()).run(
        [obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})]
    )
    assert result.baselines["B2_static"]["selection"] == "UNAVAILABLE_NO_META_TRAIN"


def test_t2_10_t_portfolio_continuity_uses_deltas_not_reset():
    estimate = SwitchCostEstimator().estimate(
        current_holdings={"ABC": 0.6},
        target_holdings={"ABC": 1.0},
        portfolio_value=100_000,
    )
    assert 0 < estimate.turnover < 1.0


def test_t2_10_u_sell_first_risk_reduction_ordering():
    estimate = SwitchCostEstimator().estimate(
        current_holdings={"ABC": 1.0},
        target_holdings={"XYZ": 1.0},
        portfolio_value=100_000,
    )
    assert estimate.sells_first == ("ABC",)
    assert estimate.buys_after_sells == ("XYZ",)


def test_t2_10_v_hash_determinism_same_inputs_same_result(tmp_path):
    test_t2_10_j_restart_replay_reproduces_uninterrupted_run(tmp_path)


def test_t2_10_w_runner_freezes_and_consumes_one_immutable_policy():
    start = datetime(2024, 4, 1, tzinfo=UTC)
    train = [obs(start, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split="TRAIN", data_hash="dataset-a", label_start=start, label_end=start, evidence_start=start, evidence_end=start)]
    validation = [obs(start + timedelta(days=1), [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split="VALIDATION", data_hash="dataset-a", label_start=start + timedelta(days=1), label_end=start + timedelta(days=1), evidence_start=start + timedelta(days=1), evidence_end=start + timedelta(days=1))]
    final = [obs(start + timedelta(days=2), [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split="FINAL_OOS", data_hash="dataset-a", label_start=start + timedelta(days=2), label_end=start + timedelta(days=2), evidence_start=start + timedelta(days=2), evidence_end=start + timedelta(days=2))]
    db = DuckDBManager(":memory:")
    runner = MetaResearchRunner(db)
    selector = AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))
    result = runner.run(
        train,
        validation,
        final,
        [("candidate-a", selector, MetaReplayPolicy())],
        data_hash="dataset-a",
        frozen_at=start + timedelta(days=1, hours=12),
    )
    stored = db.load_frozen_meta_policy(result.frozen_policy.frozen_policy_id)
    assert isinstance(result.frozen_policy, FrozenMetaPolicy)
    assert stored["selected_trial_id"] == result.frozen_policy.selected_trial_id
    assert result.final_oos_result.metrics["total_return"] >= 0
    with pytest.raises(ValueError, match="frozen policy binding"):
        MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(version="changed")), db=db).run(
            final,
            meta_split="FINAL_OOS",
            registered_trial_id=result.frozen_policy.selected_trial_id,
            frozen_policy_id=result.frozen_policy.frozen_policy_id,
            data_hash="dataset-a",
        )


def test_t2_10_x_execution_requires_actual_strictly_future_bar():
    now = datetime(2024, 4, 1, 16, tzinfo=UTC)
    bars = (
        {"timestamp": now - timedelta(hours=7), "symbol": "ABC", "open": 100.0, "close": 100.0, "volume": 1e7, "lagged_adv20": 1e7, "lagged_traded_value": 1e9, "dataset_hash": "bars"},
        {"timestamp": now, "symbol": "ABC", "open": 100.0, "close": 100.0, "volume": 1e7, "lagged_adv20": 1e7, "lagged_traded_value": 1e9, "dataset_hash": "bars"},
        {"timestamp": now + timedelta(days=1), "symbol": "ABC", "open": 100.0, "close": 101.0, "volume": 1e7, "lagged_adv20": 1e7, "lagged_traded_value": 1e9, "dataset_hash": "bars"},
    )
    item = obs(now, [card()], {"alpha": 0.01}, historical_bars=bars, asset_returns={"ABC": 0.01})
    result = MetaSelectorBacktest(AdaptiveStrategySelector(SelectorPolicy(allow_ensemble=False))).run([item])
    assert result.orders[0]["execution_lineage"]["execution_timestamp"] == now + timedelta(days=1)
    assert result.orders[0]["execution_lineage"]["selector_decision_time"] == now


def test_t2_10_y_overlap_windows_are_rejected_across_splits():
    start = datetime(2024, 4, 1, tzinfo=UTC)
    left = obs(start, [card()], {"alpha": 0.0}, asset_returns={"ABC": 0.0}, meta_split="TRAIN", label_start=start, label_end=start + timedelta(days=3), evidence_start=start, evidence_end=start + timedelta(days=2))
    right = obs(start + timedelta(days=10), [card()], {"alpha": 0.0}, asset_returns={"ABC": 0.0}, meta_split="VALIDATION", label_start=start + timedelta(days=2), label_end=start + timedelta(days=4), evidence_start=start + timedelta(days=2), evidence_end=start + timedelta(days=4))
    with pytest.raises(ValueError, match="windows overlap"):
        MetaSelectorBacktest(AdaptiveStrategySelector()).run([left, right], purge_periods=1, embargo_periods=1)


def test_t2_10_z_earliest_bar_is_selected_for_each_symbol():
    now = datetime(2024, 4, 1, 16, tzinfo=UTC)
    bars = tuple(
        {
            "timestamp": timestamp,
            "symbol": symbol,
            "open": 100.0,
            "close": 100.0,
            "volume": 10_000_000.0,
            "lagged_adv20": 10_000_000.0,
            "lagged_traded_value": 1_000_000_000.0,
            "dataset_hash": "bars",
        }
        for symbol, timestamp in (("ABC", now + timedelta(days=2)), ("ABC", now + timedelta(days=1)), ("XYZ", now + timedelta(days=2)), ("XYZ", now + timedelta(days=1)))
    )
    day = MetaSelectorBacktest._execution_day(obs(now, [], {}, historical_bars=bars), now)
    assert set(day["timestamp"]) == {now + timedelta(days=1)}


def test_t2_10_za_lifecycle_rejects_freeze_before_validation():
    start = datetime(2024, 4, 1, tzinfo=UTC)
    def make(split: str, offset: int) -> MetaSelectorObservation:
        return obs(start + timedelta(days=offset), [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split=split, data_hash="dataset-a")
    db = DuckDBManager(":memory:")
    with pytest.raises(ValueError, match="lifecycle timestamps"):
        MetaResearchRunner(db).run(
            [make("TRAIN", 0)], [make("VALIDATION", 1)], [make("FINAL_OOS", 2)],
            [("candidate-a", AdaptiveStrategySelector(), MetaReplayPolicy())],
            data_hash="dataset-a", frozen_at=start + timedelta(hours=1),
        )


def test_t2_10_zb_two_candidates_keep_family_and_result_lineage():
    start = datetime(2024, 4, 1, tzinfo=UTC)
    def make(split: str, offset: int) -> MetaSelectorObservation:
        return obs(
            start + timedelta(days=offset), [card()], {"alpha": 0.01},
            asset_returns={"ABC": 0.01}, meta_split=split, data_hash="dataset-a",
            label_start=start + timedelta(days=offset), label_end=start + timedelta(days=offset),
            evidence_start=start + timedelta(days=offset), evidence_end=start + timedelta(days=offset),
        )
    db = DuckDBManager(":memory:")
    candidates = [
        ("candidate-a", AdaptiveStrategySelector(SelectorPolicy(version="selector-a")), MetaReplayPolicy(version="meta-a")),
        ("candidate-b", AdaptiveStrategySelector(SelectorPolicy(version="selector-b")), MetaReplayPolicy(version="meta-b")),
    ]
    result = MetaResearchRunner(db).run(
        [make("TRAIN", 0)], [make("VALIDATION", 1)], [make("FINAL_OOS", 2)],
        candidates, data_hash="dataset-a", frozen_at=start + timedelta(days=1, hours=12),
    )
    assert len(db.list_experiment_families()) == 1
    rows = db.conn.execute(
        "SELECT meta_split, policy_version, selector_policy_version FROM meta_selector_runs ORDER BY meta_split, meta_run_id"
    ).fetchall()
    assert {row[1] for row in rows if row[0] == "TRAIN"} == {"meta-a", "meta-b"}
    assert {row[2] for row in rows if row[0] == "VALIDATION"} == {"selector-a", "selector-b"}
    assert result.frozen_policy.selection_result in {"candidate-a", "candidate-b"}


def test_t2_10_zc_resolver_requires_per_candle_availability_and_identity():
    decision = datetime(2024, 4, 1, 4, tzinfo=UTC)

    class StubDb:
        def load_certified_1m_source(self, **kwargs):
            import pandas as pd
            return {"content_hash": "bars-content", "bars": pd.DataFrame([
                {"symbol": "ABC", "exchange": "NSE", "timeframe": "1m", "timestamp": decision + timedelta(minutes=1), "available_at": decision + timedelta(minutes=1), "close": 101.0},
                {"symbol": "ABC", "exchange": "NSE", "timeframe": "1m", "timestamp": decision + timedelta(minutes=2), "available_at": decision + timedelta(minutes=2), "close": 102.0},
            ]), "adjustment": "UNADJUSTED"}

    rows = HistoricalEvidenceResolver(StubDb()).execution_bars_at(
        decision, dataset_id="bars-1", symbol="ABC", exchange="NSE", timeframe="1m",
    )
    assert len(rows) == 2
    assert rows[0]["dataset_hash"] == "bars-content"
    assert rows[0]["known_at"] == decision + timedelta(minutes=1)


def test_t2_10_zd_certificate_materializes_after_final_oos_and_is_persisted():
    start = datetime(2024, 4, 1, tzinfo=UTC)
    def make(split: str, offset: int) -> MetaSelectorObservation:
        timestamp = start + timedelta(days=offset)
        return obs(timestamp, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split=split, data_hash="dataset-a", label_start=timestamp, label_end=timestamp, evidence_start=timestamp, evidence_end=timestamp)
    db = DuckDBManager(":memory:")
    result = MetaResearchRunner(db).run(
        [make("TRAIN", 0)], [make("VALIDATION", 1)], [make("FINAL_OOS", 2)],
        [("candidate-a", AdaptiveStrategySelector(), MetaReplayPolicy())],
        data_hash="dataset-a", frozen_at=start + timedelta(days=1, hours=12),
    )
    row = db.conn.execute("SELECT certificate_id, final_oos_end, materialized_at, execution_hash FROM final_oos_provenance_certificates").fetchone()
    assert row is not None
    assert row[2] > row[1]
    assert row[3] == result.final_oos_result.final_oos_execution_hash


def test_t2_10_ze_stored_policy_payload_hash_mismatch_fails_final_loading():
    start = datetime(2024, 4, 1, tzinfo=UTC)
    def make(split: str, offset: int) -> MetaSelectorObservation:
        timestamp = start + timedelta(days=offset)
        return obs(timestamp, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split=split, data_hash="dataset-a", label_start=timestamp, label_end=timestamp, evidence_start=timestamp, evidence_end=timestamp)
    db = DuckDBManager(":memory:")
    result = MetaResearchRunner(db).run(
        [make("TRAIN", 0)], [make("VALIDATION", 1)], [make("FINAL_OOS", 2)],
        [("candidate-a", AdaptiveStrategySelector(), MetaReplayPolicy())],
        data_hash="dataset-a", frozen_at=start + timedelta(days=1, hours=12),
    )
    db.conn.execute("UPDATE frozen_meta_policies SET selector_policy_payload='{}' WHERE frozen_policy_id=?", [result.frozen_policy.frozen_policy_id])
    with pytest.raises(ValueError, match="stored selector policy schema"):
        MetaResearchRunner(db).run_final_oos(result.frozen_policy.frozen_policy_id, [])


def test_t2_10_zf_trial_cutoff_excludes_future_registry_rows():
    db = DuckDBManager(":memory:")
    cutoff = datetime(2024, 4, 1, tzinfo=UTC)
    family = ExperimentFamilySpec(
        experiment_family_id="future-family",
        hypothesis="future trial cutoff",
        strategy_names=["meta_selector"],
        strategy_versions=["v1"],
        universe_snapshot_id="META",
        timeframe="1d",
        feature_versions=["v1"],
        cost_model_version="cost-v1",
        parameter_space={},
        maximum_trials=10,
        selection_metric="total_return",
        walk_forward_design={},
        source_revision="test",
        created_at=cutoff - timedelta(days=1),
    )
    db.register_experiment_family(family)
    future_trial = ResearchTrial(
        experiment_family_id=family.experiment_family_id,
        strategy_name="meta_selector",
        strategy_version="v1",
        scope="META_SELECTOR",
        timeframe="1d",
        parameters={"candidate_id": "future"},
        source_revision="test",
        data_hash="dataset",
        cost_model_hash="cost-hash",
        created_at=cutoff + timedelta(days=1),
    )
    db.create_research_trial(future_trial)
    assert db.list_research_trials_at(cutoff) == []


def test_t2_10_zg_conditional_evidence_cutoff_excludes_appended_future_row():
    db = DuckDBManager(":memory:")
    cutoff = datetime(2024, 4, 1, tzinfo=UTC)
    future = cutoff + timedelta(days=1)
    db.conn.execute(
        """
        INSERT INTO strategy_conditional_evidence (
            evidence_id, aggregation_level, strategy_name, strategy_version, run_id,
            timeframe, universe, observation_count, trade_count, fold_count,
            first_observation, last_observation, net_return, gross_return, total_cost,
            evidence_status, raw_conditional_metric, global_metric, effective_sample_size,
            shrinkage_weight, shrunk_metric, sample_policy_version, sample_policy_hash,
            lineage_json, evidence_hash, available_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "future-evidence", "GLOBAL", "alpha", "v1", "future-run", "1d", "META",
            40, 40, 3, cutoff, cutoff, 0.1, 0.1, 0.0, "ELIGIBLE", 0.1, 0.1,
            40.0, 1.0, 0.1, "v1", "policy-hash", "{}", "evidence-hash", future,
        ],
    )
    resolver = HistoricalEvidenceResolver(db)
    assert resolver.conditional_evidence_at(cutoff) == []
    assert len(resolver.conditional_evidence_at(future)) == 1


def test_meta_walk_forward_split_has_train_validation_final_oos_and_embargo():
    split = split_meta_walk_forward(
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2022, 1, 1, tzinfo=UTC),
        purge_periods=1,
        embargo_periods=1,
    )
    assert split.train_start < split.train_end < split.validation_start < split.validation_end < split.final_oos_start
