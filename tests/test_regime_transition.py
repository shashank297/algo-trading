from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from storage import DuckDBManager
from trading_stack.market_regime import (
    MarketContextType,
    MarketRegimeComponentScores,
    MarketRegimeEvidence,
    MarketRegimeFeatures,
    MarketRegimeSnapshot,
    RawMarketRegime,
)
from trading_stack.regime_transition import (
    OperationalMarketRegime,
    OperationalRiskState,
    RegimeTransitionEngine,
    RegimeTransitionPolicy,
    RiskDecision,
    StressEvidence,
    StressThresholds,
    TransitionDecision,
)


IST = ZoneInfo("Asia/Kolkata")


def _snapshot(
    regime: RawMarketRegime,
    observation: int,
    *,
    confidence: float = 0.90,
    context: MarketContextType = MarketContextType.EOD,
) -> MarketRegimeSnapshot:
    decision_time = datetime(2026, 8, 1, 15, 30, tzinfo=IST) + timedelta(days=observation)
    evidence = MarketRegimeEvidence(
        benchmark_dataset_id="benchmark-dataset",
        benchmark_content_hash=f"hash-{observation}",
        decision_time=decision_time.isoformat(),
        cutoff_timestamp=decision_time.isoformat(),
    )
    return MarketRegimeSnapshot(
        regime_id=f"raw-{context.value}-{observation}",
        market="NSE",
        benchmark="NIFTY200",
        context_type=context,
        as_of=decision_time.date().isoformat(),
        decision_time=decision_time.isoformat(),
        raw_regime=regime,
        confidence=confidence,
        component_scores=MarketRegimeComponentScores(),
        features=MarketRegimeFeatures(),
        input_evidence=evidence,
        input_evidence_hash=evidence.compute_hash(),
        model_version="1.0.0",
        policy_version="2.3.2",
        policy_hash="raw-policy",
        calendar_version="test-calendar",
        missing_evidence=[],
    )


def _stress_policy(**overrides: object) -> RegimeTransitionPolicy:
    values: dict[str, object] = {
        "stress_override_enabled": True,
        "stress_thresholds": StressThresholds(
            benchmark_loss_caution=0.02,
            benchmark_loss_stress=0.05,
            volatility_shock_caution=1.5,
            volatility_shock_stress=2.0,
        ),
        "stress_release_dwell": 3,
    }
    values.update(overrides)
    return RegimeTransitionPolicy(**values)


def test_single_noisy_classification_does_not_switch_and_persistent_candidate_does() -> None:
    engine = RegimeTransitionEngine()
    first = engine.evaluate(_snapshot(RawMarketRegime.BULL_LOW_VOL, 0))
    noisy = engine.evaluate(_snapshot(RawMarketRegime.BULL_HIGH_VOL, 1), first.state, first.risk_state)
    assert noisy.state.operational_regime == OperationalMarketRegime.BULL_LOW_VOL
    assert noisy.state.candidate_observations == 1

    second = engine.evaluate(_snapshot(RawMarketRegime.BULL_HIGH_VOL, 2), noisy.state, noisy.risk_state)
    third = engine.evaluate(_snapshot(RawMarketRegime.BULL_HIGH_VOL, 3), second.state, second.risk_state)
    assert second.transition_event.decision == TransitionDecision.PENDING_ADVANCED
    assert third.transition_event.decision == TransitionDecision.TRANSITIONED
    assert third.transition_event.candidate_observations == 3
    assert third.state.operational_regime == OperationalMarketRegime.BULL_HIGH_VOL


def test_confidence_buffer_and_candidate_cancellation() -> None:
    engine = RegimeTransitionEngine(RegimeTransitionPolicy(minimum_confidence=0.70, transition_buffer=0.05))
    current = engine.evaluate(_snapshot(RawMarketRegime.BULL_LOW_VOL, 0))
    below = engine.evaluate(
        _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 1, confidence=0.7499), current.state, current.risk_state
    )
    assert below.transition_event.decision == TransitionDecision.LOW_CONFIDENCE
    assert below.state.pending_candidate_regime is None

    pending = engine.evaluate(_snapshot(RawMarketRegime.BEAR_HIGH_VOL, 2), below.state, below.risk_state)
    cancelled = engine.evaluate(_snapshot(RawMarketRegime.BULL_LOW_VOL, 3), pending.state, pending.risk_state)
    assert cancelled.transition_event.decision == TransitionDecision.CANDIDATE_CANCELLED
    assert cancelled.state.pending_candidate_regime is None


def test_repeated_oscillation_never_accumulates_nonconsecutive_dwell() -> None:
    engine = RegimeTransitionEngine()
    result = engine.evaluate(_snapshot(RawMarketRegime.SIDEWAYS_LOW_VOL, 0))
    for index, regime in enumerate(
        [RawMarketRegime.BULL_LOW_VOL, RawMarketRegime.BEAR_HIGH_VOL] * 4,
        start=1,
    ):
        result = engine.evaluate(_snapshot(regime, index), result.state, result.risk_state)
        assert result.state.operational_regime == OperationalMarketRegime.SIDEWAYS_LOW_VOL
        assert result.state.candidate_observations == 1


def test_restart_mid_pending_and_exact_replay_are_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "transition.duckdb"
    db = DuckDBManager(str(db_path))
    engine = RegimeTransitionEngine()
    first = engine.evaluate(_snapshot(RawMarketRegime.BULL_LOW_VOL, 0))
    db.persist_regime_transition(_snapshot(RawMarketRegime.BULL_LOW_VOL, 0), first)
    pending_snapshot = _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 1)
    pending = engine.evaluate(pending_snapshot, first.state, first.risk_state)
    db.persist_regime_transition(pending_snapshot, pending)
    db.close()

    restarted = DuckDBManager(str(db_path))
    state = restarted.get_regime_transition_state("NSE", "NIFTY200", MarketContextType.EOD)
    risk_state = restarted.get_operational_risk_state("NSE", "NIFTY200", MarketContextType.EOD)
    assert state is not None and state.candidate_observations == 1
    assert risk_state is not None
    advanced_snapshot = _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 2)
    advanced = engine.evaluate(advanced_snapshot, state, risk_state)
    restarted.persist_regime_transition(advanced_snapshot, advanced)
    assert advanced.state.candidate_observations == 2

    replay = engine.evaluate(advanced_snapshot, advanced.state, advanced.risk_state)
    restarted.persist_regime_transition(advanced_snapshot, replay)
    assert replay.replayed
    assert len(restarted.list_regime_transition_events(market="NSE")) == 3
    restarted.close()


def test_pending_duration_expiry_restarts_count() -> None:
    policy = RegimeTransitionPolicy(maximum_pending_duration=timedelta(hours=12))
    engine = RegimeTransitionEngine(policy)
    current = engine.evaluate(_snapshot(RawMarketRegime.BULL_LOW_VOL, 0))
    pending = engine.evaluate(_snapshot(RawMarketRegime.BEAR_HIGH_VOL, 1), current.state, current.risk_state)
    expired = engine.evaluate(_snapshot(RawMarketRegime.BEAR_HIGH_VOL, 2), pending.state, pending.risk_state)
    assert expired.transition_event.decision == TransitionDecision.PENDING_RESTARTED
    assert expired.state.candidate_observations == 1


def test_emergency_stress_is_immediate_and_release_requires_dwell() -> None:
    engine = RegimeTransitionEngine(_stress_policy())
    snapshot = _snapshot(RawMarketRegime.BULL_LOW_VOL, 0)
    stressed = engine.evaluate(
        snapshot,
        stress_evidence=StressEvidence(snapshot.decision_time, benchmark_loss=0.06),
    )
    assert stressed.risk_event.decision == RiskDecision.ESCALATED
    assert stressed.risk_state.risk_state == OperationalRiskState.STRESS

    result = stressed
    for index in range(1, 3):
        snap = _snapshot(RawMarketRegime.BULL_LOW_VOL, index)
        result = engine.evaluate(
            snap,
            result.state,
            result.risk_state,
            StressEvidence(snap.decision_time, benchmark_loss=0.0),
        )
        assert result.risk_state.risk_state == OperationalRiskState.STRESS
        assert result.risk_event.decision == RiskDecision.RELEASE_PENDING
    snap = _snapshot(RawMarketRegime.BULL_LOW_VOL, 3)
    released = engine.evaluate(
        snap, result.state, result.risk_state, StressEvidence(snap.decision_time, benchmark_loss=0.0)
    )
    assert released.risk_event.decision == RiskDecision.RELEASED
    assert released.risk_event.release_observations == 3
    assert released.risk_state.risk_state == OperationalRiskState.NORMAL


def test_integrity_failure_escalates_without_conflating_market_regime() -> None:
    engine = RegimeTransitionEngine(_stress_policy())
    snapshot = _snapshot(RawMarketRegime.INSUFFICIENT_CONTEXT, 0, confidence=0.0)
    result = engine.evaluate(
        snapshot,
        stress_evidence=StressEvidence(snapshot.decision_time, market_data_integrity_failure=True),
    )
    assert result.state.operational_regime is None
    assert result.transition_event.decision == TransitionDecision.INSUFFICIENT_CONTEXT
    assert result.risk_state.risk_state == OperationalRiskState.STRESS


def test_future_and_out_of_order_inputs_fail_closed() -> None:
    engine = RegimeTransitionEngine(_stress_policy())
    snapshot = _snapshot(RawMarketRegime.BULL_LOW_VOL, 2)
    with pytest.raises(ValueError, match="future"):
        engine.evaluate(
            snapshot,
            stress_evidence=StressEvidence(
                datetime.fromisoformat(snapshot.decision_time) + timedelta(seconds=1), benchmark_loss=0.10
            ),
        )
    current = engine.evaluate(snapshot)
    with pytest.raises(ValueError, match="strictly increasing"):
        engine.evaluate(_snapshot(RawMarketRegime.BULL_LOW_VOL, 1), current.state, current.risk_state)

    same_time = _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 2)
    same_time.regime_id = "different-evidence-at-same-time"
    with pytest.raises(ValueError, match="strictly increasing"):
        engine.evaluate(same_time, current.state, current.risk_state)


def test_eod_and_intraday_persistence_are_distinct(tmp_path: Path) -> None:
    db = DuckDBManager(str(tmp_path / "contexts.duckdb"))
    engine = RegimeTransitionEngine()
    eod_snapshot = _snapshot(RawMarketRegime.BULL_LOW_VOL, 0, context=MarketContextType.EOD)
    intraday_snapshot = _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 0, context=MarketContextType.INTRADAY)
    db.persist_regime_transition(eod_snapshot, engine.evaluate(eod_snapshot))
    db.persist_regime_transition(intraday_snapshot, engine.evaluate(intraday_snapshot))
    eod = db.get_regime_transition_state("NSE", "NIFTY200", MarketContextType.EOD)
    intraday = db.get_regime_transition_state("NSE", "NIFTY200", MarketContextType.INTRADAY)
    assert eod is not None and eod.operational_regime == OperationalMarketRegime.BULL_LOW_VOL
    assert intraday is not None and intraday.operational_regime == OperationalMarketRegime.BEAR_HIGH_VOL
    db.close()


def test_raw_snapshot_persistence_is_immutable_and_replay_idempotent(tmp_path: Path) -> None:
    db = DuckDBManager(str(tmp_path / "immutable.duckdb"))
    snapshot = _snapshot(RawMarketRegime.BULL_LOW_VOL, 0)
    db.persist_market_regime_snapshot(snapshot)
    db.persist_market_regime_snapshot(snapshot)
    conflicting = _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 0)
    conflicting.regime_id = snapshot.regime_id
    with pytest.raises(ValueError, match="immutable raw regime snapshot"):
        db.persist_market_regime_snapshot(conflicting)
    assert db.conn.execute("SELECT COUNT(*) FROM market_regime_snapshots").fetchone()[0] == 1
    db.close()


def test_policy_requires_explicit_stress_thresholds() -> None:
    with pytest.raises(ValueError, match="explicit stress_thresholds"):
        RegimeTransitionPolicy(stress_override_enabled=True)


def test_exact_reproducibility_and_context_policy_defaults() -> None:
    policy = RegimeTransitionPolicy.from_config(
        {
            "minimum_dwell_observations": 2,
            "contexts": {
                "EOD": {"maximum_pending_duration_seconds": 86400},
                "INTRADAY": {"maximum_pending_duration_seconds": 900},
            },
        },
        context_type=MarketContextType.INTRADAY,
    )
    assert policy.maximum_pending_duration == timedelta(minutes=15)
    snapshot = _snapshot(RawMarketRegime.BULL_LOW_VOL, 0)
    left = RegimeTransitionEngine(policy).evaluate(snapshot)
    right = RegimeTransitionEngine(policy).evaluate(snapshot)
    assert left.to_dict() == right.to_dict()
    assert left.transition_event.transition_id == right.transition_event.transition_id
    assert left.risk_event.risk_transition_id == right.risk_event.risk_transition_id


def test_transition_persistence_rolls_back_raw_snapshot_on_revision_conflict(tmp_path: Path) -> None:
    db = DuckDBManager(str(tmp_path / "rollback.duckdb"))
    engine = RegimeTransitionEngine()
    initial_snapshot = _snapshot(RawMarketRegime.BULL_LOW_VOL, 0)
    initial = engine.evaluate(initial_snapshot)
    db.persist_regime_transition(initial_snapshot, initial)

    next_snapshot = _snapshot(RawMarketRegime.BEAR_HIGH_VOL, 1)
    pending = engine.evaluate(next_snapshot, initial.state, initial.risk_state)
    conflicting = replace(pending, state=replace(pending.state, revision=99))
    with pytest.raises(ValueError, match="revision conflict"):
        db.persist_regime_transition(next_snapshot, conflicting)
    assert db.get_market_regime_snapshot(next_snapshot.regime_id) is None
    assert len(db.list_regime_transition_events(market="NSE")) == 1
    db.close()
