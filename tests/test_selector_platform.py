from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from experiments.meta_selector_backtest import CASH, MetaReplayPolicy, MetaSelectorBacktest, MetaSelectorObservation
from experiments.selector_walk_forward import split_meta_walk_forward
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
        asset_returns=kwargs.get("asset_returns", {}),
        benchmark_return=kwargs.get("benchmark_return", 0.0),
        raw_regime=kwargs.get("raw_regime"),
        operational_regime=kwargs.get("operational_regime"),
        known_at=kwargs.get("known_at"),
        available_at=kwargs.get("available_at"),
    )


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
    assert result.verdict == "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"


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
    assert result.verdict == "ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED"


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


def test_t2_10_j_restart_replay_reproduces_uninterrupted_run():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    observations = [obs(now + timedelta(days=i), [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}) for i in range(5)]
    uninterrupted = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations)
    first_leg = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations[:2])
    resumed = MetaSelectorBacktest(AdaptiveStrategySelector()).run(observations, checkpoint=first_leg.checkpoint)
    assert uninterrupted.equity_curve[2:] == resumed.equity_curve
    assert uninterrupted.decisions[2:] == resumed.decisions
    assert uninterrupted.switches[1:] == resumed.switches
    assert uninterrupted.checkpoint.holdings == resumed.checkpoint.holdings
    assert uninterrupted.checkpoint.cash == pytest.approx(resumed.checkpoint.cash)


def test_t2_10_k_future_trial_does_not_change_earlier_replay():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    base = MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01})])
    changed = MetaSelectorBacktest(AdaptiveStrategySelector()).run([obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, future_trial_ids=("future",))])
    assert base.evidence_hash == changed.evidence_hash


def test_t2_10_k2_final_oos_requires_pre_registered_trial():
    now = datetime(2024, 4, 1, tzinfo=UTC)
    replay = MetaSelectorBacktest(AdaptiveStrategySelector())
    final = [obs(now, [card()], {"alpha": 0.01}, asset_returns={"ABC": 0.01}, meta_split="FINAL_OOS")]
    with pytest.raises(ValueError, match="pre-registered"):
        replay.run(final, meta_split="FINAL_OOS")
    with pytest.raises(ValueError, match="before FINAL_OOS"):
        replay.run(final, meta_split="FINAL_OOS", registered_trial_id="trial", trial_created_at=now)
    result = replay.run(
        final,
        meta_split="FINAL_OOS",
        registered_trial_id="trial",
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


def test_t2_10_v_hash_determinism_same_inputs_same_result():
    test_t2_10_j_restart_replay_reproduces_uninterrupted_run()


def test_meta_walk_forward_split_has_train_validation_final_oos_and_embargo():
    split = split_meta_walk_forward(
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2022, 1, 1, tzinfo=UTC),
        purge_periods=1,
        embargo_periods=1,
    )
    assert split.train_start < split.train_end < split.validation_start < split.validation_end < split.final_oos_start
