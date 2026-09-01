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
from trading_stack.calendars import build_nse_calendar
from trading_stack.backtest import (
    _annualized_return,
    _max_drawdown_duration,
    _profit_factor,
    _sharpe_ratio,
    _sortino_ratio,
)
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.scorecards import StrategyScorecard
from trading_stack.selector import ABSTAIN, AdaptiveStrategySelector, SelectorDecision, SelectorPolicy, SwitchCostEstimator


HOLD_CURRENT = "HOLD_CURRENT"
REDUCE_RISK = "REDUCE_RISK"
CASH = "CASH"
ABSTAIN_BEHAVIORS = frozenset({HOLD_CURRENT, REDUCE_RISK, CASH})
IMPLEMENTATION_READY_VERDICT = "PHASE 2.10 IMPLEMENTATION READY"
CAUSALLY_VERIFIED_VERDICT = "PHASE 2.10 COMPLETE \u2014 META-SELECTOR CAUSALLY VERIFIED"
SIMPLER_BASELINE_VERDICT = "PHASE 2.10 COMPLETE \u2014 ADAPTIVE COMPLEXITY NOT JUSTIFIED; USE SIMPLER BASELINE"


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _acceptance_policy_hash(policy: MetaReplayPolicy) -> str:
    return _canonical_hash({"acceptance_policy_version": "phase2-10-acceptance-v1", "gates": {
        "min_final_oos_duration_days": policy.min_final_oos_duration_days,
        "min_final_oos_observations": policy.min_final_oos_observations,
        "min_independent_trades": policy.min_independent_trades,
        "max_switch_rate": policy.max_switch_rate,
        "max_drawdown": policy.max_drawdown,
        "min_net_edge": policy.min_net_edge,
        "require_robustness_certification": policy.require_robustness_certification,
        "require_selector_stability": policy.require_selector_stability,
        "require_causal_verification": policy.require_causal_verification,
    }})


@dataclass(frozen=True)
class MetaReplayPolicy:
    version: str = "meta-selector-v2"
    abstain_behavior: str = HOLD_CURRENT
    risk_reduction_factor: float = 0.5
    min_final_oos_observations: int = 1
    max_switch_rate: float = 1.0
    max_drawdown: float = 0.25
    min_net_edge: float = 0.0
    min_final_oos_duration_days: float = 1.0
    min_independent_trades: int = 1
    require_robustness_certification: bool = True
    require_selector_stability: bool = True
    require_causal_verification: bool = True

    def __post_init__(self) -> None:
        if self.abstain_behavior not in ABSTAIN_BEHAVIORS:
            raise ValueError("abstain_behavior must be HOLD_CURRENT, REDUCE_RISK, or CASH")
        if not 0 <= self.risk_reduction_factor <= 1:
            raise ValueError("risk_reduction_factor must be bounded in [0, 1]")
        if not (self.require_robustness_certification and self.require_selector_stability and self.require_causal_verification):
            raise ValueError("FINAL_OOS robustness, selector stability, and causal verification gates are mandatory")
        if self.min_final_oos_duration_days <= 0 or self.min_final_oos_observations <= 0 or self.min_independent_trades <= 0:
            raise ValueError("FINAL_OOS duration and sample gates must be positive")
        if not 0 <= self.max_switch_rate <= 1 or not 0 < self.max_drawdown < 1:
            raise ValueError("FINAL_OOS switch and drawdown gates are out of bounds")

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
    outcome_series_bindings: tuple[tuple[str, str], ...] = ()
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
    execution_dataset_id: str | None = None
    execution_timeframe: str = "1m"
    execution_exchange: str = "NSE"
    risk_state_as_of: datetime | None = None
    prior_returns_available_at: datetime | None = None
    risk_snapshot_id: str | None = None
    risk_snapshot_hash: str | None = None
    risk_snapshot: dict[str, Any] = field(default_factory=dict)
    risk_batch_id: str | None = None
    batch_start_snapshot_id: str | None = None
    knowledge_cutoff: datetime | None = None


@dataclass(frozen=True)
class FinalDatasetReference:
    """Trusted identifiers used to reconstruct FINAL_OOS observations."""

    dataset_id: str
    symbol: str
    exchange: str
    timeframe: str
    decision_times: tuple[datetime, ...]
    universe_snapshot_id: str
    dataset_content_hash: str = "synthetic"
    regime_snapshot_ids: tuple[str, ...] = ()
    asset_state_snapshot_ids: tuple[str, ...] = ()
    risk_snapshot_ids: tuple[str, ...] = ()
    benchmark_series_id: str | None = None
    strategy_series_ids: tuple[str, ...] = ()
    outcome_materialization_cutoff: datetime | None = None
    knowledge_cutoff: datetime | None = None

    def __post_init__(self) -> None:
        if not self.decision_times or any(timestamp.tzinfo is None for timestamp in self.decision_times):
            raise ValueError("FINAL dataset reference requires timezone-aware decision times")
        if self.timeframe != "1m":
            raise ValueError("FINAL dataset reference requires canonical 1m data")
        if self.outcome_materialization_cutoff is not None and self.outcome_materialization_cutoff.tzinfo is None:
            raise ValueError("outcome_materialization_cutoff must be timezone-aware")
        if self.knowledge_cutoff is not None and self.knowledge_cutoff.tzinfo is None:
            raise ValueError("knowledge_cutoff must be timezone-aware")
        if self.dataset_id != "synthetic" and self.knowledge_cutoff is None:
            raise ValueError("non-synthetic FINAL references require an explicit knowledge_cutoff")
        if self.dataset_id != "synthetic" and self.dataset_content_hash in {"", "synthetic"}:
            raise ValueError("non-synthetic FINAL references require a certified dataset content hash")


@dataclass(frozen=True)
class CausalRiskSnapshot:
    snapshot_id: str
    as_of: datetime
    exposure: float
    sector_exposure: dict[str, float]
    daily_pnl: float
    drawdown: float
    var_inputs: tuple[float, ...]
    var_result: float
    open_positions: dict[str, float]
    instrument_liquidity: dict[str, float]
    rolling_returns: tuple[float, ...]
    rolling_volatility: float
    data_hash: str
    snapshot_hash: str

    @classmethod
    def create(cls, *, snapshot_id: str, as_of: datetime, exposure: float,
               sector_exposure: dict[str, float], daily_pnl: float, drawdown: float,
               var_inputs: Iterable[float], var_result: float,
               open_positions: dict[str, float], instrument_liquidity: dict[str, float],
               rolling_returns: Iterable[float], rolling_volatility: float,
               data_hash: str) -> "CausalRiskSnapshot":
        if as_of.tzinfo is None:
            raise ValueError("risk snapshot as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
        values: dict[str, Any] = {
            "snapshot_id": snapshot_id, "as_of": as_of, "exposure": exposure,
            "sector_exposure": dict(sorted(sector_exposure.items())), "daily_pnl": daily_pnl,
            "drawdown": drawdown, "var_inputs": tuple(var_inputs), "var_result": var_result,
            "open_positions": dict(sorted(open_positions.items())),
            "instrument_liquidity": dict(sorted(instrument_liquidity.items())),
            "rolling_returns": tuple(rolling_returns), "rolling_volatility": rolling_volatility,
            "data_hash": data_hash,
        }
        return cls(snapshot_hash=_canonical_hash(values), **values)


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
    stress_results: dict[str, dict[str, Any]]
    verdict: str
    evidence_hash: str
    checkpoint: MetaSelectorCheckpoint
    orders: tuple[dict[str, Any], ...] = ()
    fills: tuple[dict[str, Any], ...] = ()
    costs: tuple[dict[str, Any], ...] = ()
    risk_decisions: tuple[dict[str, Any], ...] = ()
    final_oos_execution_hash: str = ""
    execution_payload: dict[str, Any] = field(default_factory=dict)
    pre_verdict_result_hash: str = ""
    pre_verdict_result_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalOOSProvenanceCertificate:
    certificate_id: str
    meta_run_id: str
    frozen_policy_id: str
    frozen_policy_hash: str
    selected_trial_id: str
    experiment_family_id: str
    selector_policy_hash: str
    meta_policy_hash: str
    scorecard_policy_hash: str
    dataset_ids: tuple[str, ...]
    dataset_content_hashes: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    resolver_hash: str
    execution_hash: str
    final_oos_start: datetime
    final_oos_end: datetime
    materialized_at: datetime
    cost_model_version: str
    cost_model_hash: str
    purge_periods: int
    embargo_periods: int
    certificate_hash: str
    acceptance_policy_version: str = "phase2-10-acceptance-v1"
    acceptance_policy_hash: str = ""
    universe_snapshot_id: str = ""
    regime_snapshot_ids: tuple[str, ...] = ()
    asset_state_snapshot_ids: tuple[str, ...] = ()
    risk_snapshot_ids: tuple[str, ...] = ()
    risk_snapshot_hashes: tuple[str, ...] = ()
    dataset_certification_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    outcome_series_ids: tuple[str, ...] = ()
    outcome_series_bindings: tuple[tuple[str, str], ...] = ()
    execution_bar_hashes: tuple[str, ...] = ()
    execution_bar_ids: tuple[str, ...] = ()
    scorecard_ids: tuple[str, ...] = ()
    conditional_evidence_ids: tuple[str, ...] = ()
    dataset_certification_bindings: tuple[tuple[str, str], ...] = ()
    dataset_bindings: tuple[tuple[str, str], ...] = ()
    knowledge_cutoff: datetime | None = None

    @classmethod
    def create(cls, *, meta_run_id: str, frozen_policy_id: str, frozen_policy_hash: str, selected_trial_id: str, selector_policy_hash: str, meta_policy_hash: str, scorecard_policy_hash: str, dataset_ids: Iterable[str], dataset_content_hashes: Iterable[str], evidence_hashes: Iterable[str], resolver_hash: str, execution_hash: str, final_oos_start: datetime, final_oos_end: datetime, materialized_at: datetime, cost_model_version: str, cost_model_hash: str, purge_periods: int, embargo_periods: int, acceptance_policy_version: str = "phase2-10-acceptance-v1", acceptance_policy_hash: str = "", experiment_family_id: str = "meta-selector-phase2-10", universe_snapshot_id: str = "", regime_snapshot_ids: Iterable[str] = (), asset_state_snapshot_ids: Iterable[str] = (), risk_snapshot_ids: Iterable[str] = (), risk_snapshot_hashes: Iterable[str] = (), dataset_certification_ids: Iterable[str] = (), evidence_ids: Iterable[str] = (), outcome_series_ids: Iterable[str] = (), outcome_series_bindings: Iterable[tuple[str, str]] = (), execution_bar_hashes: Iterable[str] = (), execution_bar_ids: Iterable[str] = (), scorecard_ids: Iterable[str] = (), conditional_evidence_ids: Iterable[str] = (), dataset_certification_bindings: Iterable[tuple[str, str]] = (), dataset_bindings: Iterable[tuple[str, str]] = (), knowledge_cutoff: datetime | None = None) -> FinalOOSProvenanceCertificate:
        final_oos_start = final_oos_start.astimezone(timezone.utc)
        final_oos_end = final_oos_end.astimezone(timezone.utc)
        materialized_at = materialized_at.astimezone(timezone.utc)
        if knowledge_cutoff is not None:
            if knowledge_cutoff.tzinfo is None:
                raise ValueError("knowledge_cutoff must be timezone-aware")
            knowledge_cutoff = knowledge_cutoff.astimezone(timezone.utc)
        if materialized_at <= final_oos_end:
            raise ValueError("provenance certificate must materialize after FINAL_OOS")
        values: dict[str, Any] = {"meta_run_id": meta_run_id, "frozen_policy_id": frozen_policy_id, "frozen_policy_hash": frozen_policy_hash, "selected_trial_id": selected_trial_id, "experiment_family_id": experiment_family_id, "selector_policy_hash": selector_policy_hash, "meta_policy_hash": meta_policy_hash, "scorecard_policy_hash": scorecard_policy_hash, "dataset_ids": tuple(sorted(dataset_ids)), "dataset_content_hashes": tuple(sorted(dataset_content_hashes)), "evidence_hashes": tuple(sorted(evidence_hashes)), "resolver_hash": resolver_hash, "execution_hash": execution_hash, "materialized_at": materialized_at, "final_oos_start": final_oos_start, "final_oos_end": final_oos_end, "cost_model_version": cost_model_version, "cost_model_hash": cost_model_hash, "purge_periods": purge_periods, "embargo_periods": embargo_periods, "acceptance_policy_version": acceptance_policy_version, "acceptance_policy_hash": acceptance_policy_hash, "universe_snapshot_id": universe_snapshot_id, "regime_snapshot_ids": tuple(sorted(regime_snapshot_ids)), "asset_state_snapshot_ids": tuple(sorted(asset_state_snapshot_ids)), "risk_snapshot_ids": tuple(sorted(risk_snapshot_ids)), "risk_snapshot_hashes": tuple(sorted(risk_snapshot_hashes)), "dataset_certification_ids": tuple(sorted(dataset_certification_ids)), "evidence_ids": tuple(sorted(evidence_ids)), "outcome_series_ids": tuple(sorted(outcome_series_ids)), "outcome_series_bindings": tuple(sorted((str(series_id), str(content_hash)) for series_id, content_hash in outcome_series_bindings)), "execution_bar_hashes": tuple(sorted(execution_bar_hashes)), "execution_bar_ids": tuple(sorted(execution_bar_ids)), "scorecard_ids": tuple(sorted(scorecard_ids)), "conditional_evidence_ids": tuple(sorted(conditional_evidence_ids)), "dataset_certification_bindings": tuple(sorted((str(dataset_id), str(certification_id)) for dataset_id, certification_id in dataset_certification_bindings)), "dataset_bindings": tuple(sorted((str(dataset_id), str(content_hash)) for dataset_id, content_hash in dataset_bindings)), "knowledge_cutoff": knowledge_cutoff}
        certificate_hash = _canonical_hash(values)
        return cls(certificate_id=certificate_hash[:32], certificate_hash=certificate_hash, **values)


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
    b2_strategy: str | None
    data_hash: str
    universe_lineage: tuple[str, ...]
    cost_model_version: str
    cost_model_hash: str
    purge_periods: int
    embargo_periods: int
    frozen_at: datetime
    artifact_hash: str
    selection_rule: str = "max_validation_total_return_then_candidate_id"
    selection_result: str | None = None
    selector_policy_payload: dict[str, Any] = field(default_factory=dict)
    meta_policy_payload: dict[str, Any] = field(default_factory=dict)
    scorecard_policy_payload: dict[str, Any] = field(default_factory=dict)
    acceptance_policy_version: str = "phase2-10-acceptance-v1"
    acceptance_policy_hash: str = ""
    experiment_family_id: str = "meta-selector-phase2-10"
    universe_snapshot_id: str = ""

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
        b2_strategy: str | None,
        data_hash: str,
        universe_lineage: Iterable[str],
        cost_model_version: str,
        cost_model_hash: str,
        purge_periods: int,
        embargo_periods: int,
        frozen_at: datetime,
        selection_rule: str = "max_validation_total_return_then_candidate_id",
        selection_result: str | None = None,
        selector_policy_payload: dict[str, Any] | None = None,
        meta_policy_payload: dict[str, Any] | None = None,
        scorecard_policy_payload: dict[str, Any] | None = None,
        acceptance_policy_version: str = "phase2-10-acceptance-v1",
        acceptance_policy_hash: str | None = None,
        experiment_family_id: str = "meta-selector-phase2-10",
        universe_snapshot_id: str = "",
    ) -> FrozenMetaPolicy:
        if frozen_at.tzinfo is None:
            raise ValueError("frozen_at must be timezone-aware")
        frozen_at = frozen_at.astimezone(timezone.utc)
        candidate_ids = tuple(sorted(candidate_trial_ids))
        universe_ids = tuple(sorted(universe_lineage))
        values = {
            "selector_policy_version": selector_policy_version, "selector_policy_hash": selector_policy_hash,
            "scorecard_policy_hash": scorecard_policy_hash, "meta_policy_version": meta_policy_version,
            "meta_policy_hash": meta_policy_hash, "candidate_trial_ids": candidate_ids,
            "selected_trial_id": selected_trial_id, "data_hash": data_hash,
            "b2_strategy": b2_strategy,
            "universe_lineage": universe_ids, "cost_model_version": cost_model_version,
            "cost_model_hash": cost_model_hash, "purge_periods": purge_periods,
            "embargo_periods": embargo_periods, "frozen_at": frozen_at,
            "selection_rule": selection_rule, "selection_result": selection_result,
            "selector_policy_payload": selector_policy_payload or {}, "meta_policy_payload": meta_policy_payload or {}, "scorecard_policy_payload": scorecard_policy_payload or {},
            "acceptance_policy_version": acceptance_policy_version,
            "acceptance_policy_hash": acceptance_policy_hash or _canonical_hash({"version": acceptance_policy_version, "min_final_oos_observations": 1, "min_independent_trades": 1}),
            "experiment_family_id": experiment_family_id,
            "universe_snapshot_id": universe_snapshot_id,
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
            b2_strategy=b2_strategy,
            data_hash=data_hash,
            universe_lineage=universe_ids,
            cost_model_version=cost_model_version,
            cost_model_hash=cost_model_hash,
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
            frozen_at=frozen_at,
            artifact_hash=artifact_hash,
            selection_rule=selection_rule,
            selection_result=selection_result,
            selector_policy_payload=selector_policy_payload or {},
            meta_policy_payload=meta_policy_payload or {},
            scorecard_policy_payload=scorecard_policy_payload or {},
            acceptance_policy_version=acceptance_policy_version,
            acceptance_policy_hash=acceptance_policy_hash or _canonical_hash({"version": acceptance_policy_version, "min_final_oos_observations": 1, "min_independent_trades": 1}),
            experiment_family_id=experiment_family_id,
            universe_snapshot_id=universe_snapshot_id,
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
        final_oos: FinalDatasetReference,
        candidates: Iterable[tuple[str, AdaptiveStrategySelector, MetaReplayPolicy]],
        *,
        data_hash: str,
        purge_periods: int = 0,
        embargo_periods: int = 0,
        frozen_at: datetime | None = None,
        materialized_at: datetime | None = None,
    ) -> MetaResearchResult:
        if self.db is None:
            raise ValueError("MetaResearchRunner requires a Phase 2.1 trial registry")
        candidate_list = tuple(candidates)
        if not candidate_list:
            raise ValueError("at least one candidate policy is required")
        normalizer = MetaSelectorBacktest(candidate_list[0][1], replay_policy=candidate_list[0][2], db=self.db)
        train_items = tuple(normalizer._coerce(item) for item in train)
        validation_items = tuple(normalizer._coerce(item) for item in validation)
        if not isinstance(final_oos, FinalDatasetReference):
            raise ValueError("FINAL_OOS requires a FinalDatasetReference")
        final_items = HistoricalEvidenceResolver(self.db).final_observations(final_oos)
        if frozen_at is None or frozen_at.tzinfo is None:
            raise ValueError("MetaResearchRunner requires an explicit timezone-aware frozen_at")
        if not train_items or not validation_items or not final_items:
            raise ValueError("TRAIN, VALIDATION, and FINAL_OOS must all contain observations")
        train_start = min(item.decision_time for item in train_items)
        validation_end = max(item.decision_time for item in validation_items)
        final_start = min(item.decision_time for item in final_items)
        final_end = max(item.decision_time for item in final_items)
        if frozen_at <= validation_end or frozen_at >= final_start or frozen_at <= train_start:
            raise ValueError("lifecycle timestamps must satisfy TRAIN < VALIDATION < frozen_at < FINAL_OOS")
        if materialized_at is None:
            materialized_at = final_end + pd.Timedelta(microseconds=1).to_pytimedelta()
        if materialized_at.tzinfo is None or materialized_at <= final_end:
            raise ValueError("materialized_at must be timezone-aware and after FINAL_OOS")
        for item in train_items + validation_items + final_items:
            if any(getattr(item, field_name) is None for field_name in ("label_start", "label_end", "evidence_start", "evidence_end")):
                raise ValueError("MetaResearchRunner requires explicit label and evidence windows")
        MetaSelectorBacktest._validate_purge_embargo(
            train_items + validation_items + final_items, purge_periods, embargo_periods,
        )
        registration_at = train_start - pd.Timedelta(microseconds=1).to_pytimedelta()
        b2_strategy = MetaSelectorBacktest._static_train_winner(train_items)
        scorecard_policy_hash = MetaSelectorBacktest._canonical_visible_scorecard_policy_hash(tuple(train_items + validation_items))
        universe_lineage = sorted({card.strategy_name for item in train_items + validation_items for card in item.scorecards})
        train_results: dict[str, MetaSelectorResult] = {}
        validation_results: dict[str, MetaSelectorResult] = {}
        trial_ids: dict[str, str] = {}
        for candidate_id, selector, replay_policy in candidate_list:
            trial_ids[candidate_id] = self._register_candidate(
                candidate_id, selector, replay_policy, data_hash, purge_periods, embargo_periods,
                registration_at, scorecard_policy_hash, b2_strategy, universe_lineage,
                universe_snapshot_id=final_oos.universe_snapshot_id,
            )
            replay = MetaSelectorBacktest(selector, replay_policy=replay_policy, db=self.db)
            self.db.transition_research_trial(trial_ids[candidate_id], "RUNNING")
            try:
                train_results[candidate_id] = replay.run(train_items, meta_split="TRAIN", include_stress=False, data_hash=data_hash, purge_periods=purge_periods, embargo_periods=embargo_periods)
                validation_results[candidate_id] = replay.run(validation_items, meta_split="VALIDATION", include_stress=False, data_hash=data_hash, purge_periods=purge_periods, embargo_periods=embargo_periods)
                success_time = validation_end + pd.Timedelta(microseconds=1).to_pytimedelta()
                self.db.transition_research_trial(
                    trial_ids[candidate_id], "SUCCEEDED", metrics=validation_results[candidate_id].metrics,
                    effective_at=success_time,
                )
            except Exception as exc:
                self.db.transition_research_trial(trial_ids[candidate_id], "FAILED", error_message=str(exc))
                raise
        winner = min(candidate_list, key=lambda candidate: (-validation_results[candidate[0]].metrics["total_return"], candidate[0]))
        winner_id, selector, replay_policy = winner
        frozen = FrozenMetaPolicy.create(
            selector_policy_version=selector.policy.version,
            selector_policy_hash=selector.policy.policy_hash,
            scorecard_policy_hash=scorecard_policy_hash,
            meta_policy_version=replay_policy.version,
            meta_policy_hash=replay_policy.policy_hash,
            candidate_trial_ids=trial_ids.values(),
            selected_trial_id=trial_ids[winner_id],
            b2_strategy=b2_strategy,
            data_hash=data_hash,
            universe_lineage=universe_lineage,
            cost_model_version=MetaSelectorBacktest(selector, replay_policy=replay_policy).execution_adapter.cost_schedule.version,
            cost_model_hash=MetaSelectorBacktest._cost_model_hash(MetaSelectorBacktest(selector, replay_policy=replay_policy).execution_adapter.cost_schedule),
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
            frozen_at=frozen_at,
            selection_result=winner_id,
            selector_policy_payload={"schema_version": "selector-policy-v1", **asdict(selector.policy)},
            meta_policy_payload={"schema_version": "meta-replay-policy-v1", **asdict(replay_policy)},
            scorecard_policy_payload={"schema_version": "scorecard-policy-v1", "policy_hash": scorecard_policy_hash},
            acceptance_policy_hash=_acceptance_policy_hash(replay_policy),
            experiment_family_id="meta-selector-phase2-10",
            universe_snapshot_id=final_oos.universe_snapshot_id,
        )
        self.db.persist_frozen_meta_policy(frozen)
        candidate_by_id = {candidate_id: (candidate_selector, candidate_policy) for candidate_id, candidate_selector, candidate_policy in candidate_list}
        for candidate_id, result in train_results.items():
            candidate_selector, candidate_policy = candidate_by_id[candidate_id]
            self.db.persist_meta_selector_result(result, policy_version=candidate_policy.version, selector_policy_version=candidate_selector.policy.version, selector_policy_hash=candidate_selector.policy.policy_hash, meta_split="TRAIN", purge_periods=purge_periods, embargo_periods=embargo_periods, available_at=max(item.decision_time for item in train_items) + pd.Timedelta(microseconds=1).to_pytimedelta())
        for candidate_id, result in validation_results.items():
            candidate_selector, candidate_policy = candidate_by_id[candidate_id]
            self.db.persist_meta_selector_result(result, policy_version=candidate_policy.version, selector_policy_version=candidate_selector.policy.version, selector_policy_hash=candidate_selector.policy.policy_hash, meta_split="VALIDATION", purge_periods=purge_periods, embargo_periods=embargo_periods, available_at=max(item.decision_time for item in validation_items) + pd.Timedelta(microseconds=1).to_pytimedelta())
        final_result = MetaSelectorBacktest(
            selector, replay_policy=replay_policy, resolver=HistoricalEvidenceResolver(self.db), db=self.db,
        ).run(
            final_items,
            meta_split="FINAL_OOS",
            registered_trial_id=frozen.selected_trial_id,
            trial_created_at=frozen.frozen_at,
            frozen_policy_id=frozen.frozen_policy_id,
            frozen_b2_strategy=frozen.b2_strategy,
            data_hash=data_hash,
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
        )
        self.db.persist_meta_selector_result(final_result, policy_version=replay_policy.version, selector_policy_version=selector.policy.version, selector_policy_hash=selector.policy.policy_hash, meta_split="FINAL_OOS", purge_periods=purge_periods, embargo_periods=embargo_periods, available_at=materialized_at)
        certificate_materialized_at = materialized_at + pd.Timedelta(microseconds=1).to_pytimedelta()
        certificate = FinalOOSProvenanceCertificate.create(
            meta_run_id=final_result.meta_run_id,
            frozen_policy_id=frozen.frozen_policy_id,
            frozen_policy_hash=frozen.artifact_hash,
            selected_trial_id=frozen.selected_trial_id,
            selector_policy_hash=frozen.selector_policy_hash,
            meta_policy_hash=frozen.meta_policy_hash,
            scorecard_policy_hash=frozen.scorecard_policy_hash,
            dataset_ids={item.execution_dataset_id for item in final_items if item.execution_dataset_id is not None},
            dataset_content_hashes={str(row.get("dataset_hash")) for item in final_items for row in item.historical_bars if row.get("dataset_hash")},
            evidence_hashes=[decision.evidence_hash for decision in final_result.decisions],
            resolver_hash=_canonical_hash({"resolver": "HistoricalEvidenceResolver", "version": "phase2-10-v2"}),
            execution_hash=final_result.final_oos_execution_hash,
            final_oos_start=min(item.decision_time for item in final_items),
            final_oos_end=max(item.decision_time for item in final_items),
            materialized_at=certificate_materialized_at,
            cost_model_version=frozen.cost_model_version,
            cost_model_hash=frozen.cost_model_hash,
            purge_periods=purge_periods,
            embargo_periods=embargo_periods,
            acceptance_policy_version=frozen.acceptance_policy_version,
            acceptance_policy_hash=frozen.acceptance_policy_hash,
            experiment_family_id="meta-selector-phase2-10",
            universe_snapshot_id=final_oos.universe_snapshot_id,
            knowledge_cutoff=final_oos.knowledge_cutoff,
            regime_snapshot_ids=final_oos.regime_snapshot_ids,
            asset_state_snapshot_ids=final_oos.asset_state_snapshot_ids,
            risk_snapshot_ids=final_oos.risk_snapshot_ids,
            risk_snapshot_hashes=[item.risk_snapshot_hash for item in final_items if item.risk_snapshot_hash],
            dataset_certification_ids=[str(row["dataset_certification_id"]) for item in final_items for row in item.historical_bars if row.get("dataset_certification_id")],
            evidence_ids=[
                str(card.conditional_evidence_id) for item in final_items for card in item.scorecards
                if card.available_at <= item.decision_time and card.conditional_evidence_id
            ],
            outcome_series_ids=tuple(series_id for series_id in (final_oos.benchmark_series_id, *final_oos.strategy_series_ids) if series_id),
            execution_bar_hashes=[
                str(order["execution_lineage"]["historical_bar_hash"])
                for order in final_result.orders if order.get("execution_lineage")
            ],
            execution_bar_ids=[
                str(order["execution_lineage"]["historical_bar_id"])
                for order in final_result.orders
                if order.get("execution_lineage", {}).get("historical_bar_id")
            ],
            scorecard_ids=[
                str(card.scorecard_id) for item in final_items for card in item.scorecards
                if card.available_at <= item.decision_time
            ],
            conditional_evidence_ids=[
                str(card.conditional_evidence_id) for item in final_items for card in item.scorecards
                if card.available_at <= item.decision_time and card.conditional_evidence_id
            ],
            outcome_series_bindings=[
                binding for item in final_items for binding in item.outcome_series_bindings
            ],
            dataset_certification_bindings=[
                (str(row["dataset_id"]), str(row["dataset_certification_id"]))
                for item in final_items for row in item.historical_bars
                if row.get("dataset_id") and row.get("dataset_certification_id")
            ],
            dataset_bindings=[
                (str(row.get("dataset_id")), str(row.get("dataset_hash")))
                for item in final_items for row in item.historical_bars
                if row.get("dataset_id") and row.get("dataset_hash")
            ],
        )
        self.db.persist_final_oos_provenance_certificate(certificate)
        return MetaResearchResult(frozen, train_results, validation_results, final_result)

    def run_final_oos(
        self, frozen_policy_id: str, final_dataset_reference: FinalDatasetReference,
    ) -> MetaSelectorResult:
        artifact = self.db.load_frozen_meta_policy(frozen_policy_id)
        artifact_check = FrozenMetaPolicy.create(
            selector_policy_version=str(artifact["selector_policy_version"]),
            selector_policy_hash=str(artifact["selector_policy_hash"]),
            scorecard_policy_hash=str(artifact["scorecard_policy_hash"]),
            meta_policy_version=str(artifact["meta_policy_version"]),
            meta_policy_hash=str(artifact["meta_policy_hash"]),
            candidate_trial_ids=artifact["candidate_trial_ids"],
            selected_trial_id=str(artifact["selected_trial_id"]),
            b2_strategy=artifact.get("b2_strategy"), data_hash=str(artifact["data_hash"]),
            universe_lineage=artifact["universe_lineage"],
            cost_model_version=str(artifact["cost_model_version"]),
            cost_model_hash=str(artifact["cost_model_hash"]),
            purge_periods=int(artifact["purge_periods"]), embargo_periods=int(artifact["embargo_periods"]),
            frozen_at=pd.Timestamp(artifact["frozen_at"]).to_pydatetime(),
            selection_rule=str(artifact["selection_rule"]), selection_result=artifact.get("selection_result"),
            selector_policy_payload=artifact.get("selector_policy_payload") or {},
            meta_policy_payload=artifact.get("meta_policy_payload") or {},
            scorecard_policy_payload=artifact.get("scorecard_policy_payload") or {},
            acceptance_policy_version=str(artifact.get("acceptance_policy_version") or "phase2-10-acceptance-v1"),
            acceptance_policy_hash=str(artifact.get("acceptance_policy_hash") or ""),
            experiment_family_id=str(artifact.get("experiment_family_id") or "meta-selector-phase2-10"),
            universe_snapshot_id=str(artifact.get("universe_snapshot_id") or ""),
        )
        if artifact_check.artifact_hash != artifact["artifact_hash"]:
            raise ValueError("frozen policy artifact hash mismatch")
        if artifact.get("universe_snapshot_id") != final_dataset_reference.universe_snapshot_id:
            raise ValueError("FINAL universe snapshot does not match frozen policy")
        if str(artifact.get("data_hash")) != str(final_dataset_reference.dataset_content_hash) and final_dataset_reference.dataset_id != "synthetic":
            raise ValueError("FINAL dataset content hash does not match frozen policy")
        selector_payload = dict(artifact.get("selector_policy_payload") or {})
        meta_payload = dict(artifact.get("meta_policy_payload") or {})
        if selector_payload.pop("schema_version", None) != "selector-policy-v1":
            raise ValueError("unsupported stored selector policy schema")
        if meta_payload.pop("schema_version", None) != "meta-replay-policy-v1":
            raise ValueError("unsupported stored meta policy schema")
        selector_policy = SelectorPolicy(**selector_payload)
        replay_policy = MetaReplayPolicy(**meta_payload)
        if selector_policy.policy_hash != artifact["selector_policy_hash"]:
            raise ValueError("stored selector policy hash does not match frozen artifact")
        if replay_policy.policy_hash != artifact["meta_policy_hash"]:
            raise ValueError("stored meta policy hash does not match frozen artifact")
        final_cutoff = min(final_dataset_reference.decision_times)
        knowledge_cutoff = final_dataset_reference.knowledge_cutoff or final_cutoff
        historical_trials = (
            [self.db.get_research_trial(str(artifact["selected_trial_id"]))]
            if final_dataset_reference.dataset_id == "synthetic"
            else self.db.list_research_trials_at(
                final_cutoff,
                family_id=str(artifact.get("experiment_family_id") or "meta-selector-phase2-10"),
                knowledge_cutoff=knowledge_cutoff,
            )
        )
        historical_trials = [trial for trial in historical_trials if trial is not None]
        trial = next((candidate for candidate in historical_trials if candidate["trial_id"] == str(artifact["selected_trial_id"])), None)
        if trial is None:
            raise ValueError("frozen policy selected trial is unavailable")
        if trial.get("status") != "SUCCEEDED" or pd.Timestamp(trial.get("status_effective_at")).to_pydatetime() >= final_cutoff:
            raise ValueError("frozen policy selected trial is not SUCCEEDED")
        if trial.get("parameters", {}).get("candidate_id") != artifact.get("selection_result"):
            raise ValueError("frozen policy selected trial candidate binding mismatch")
        family = self.db.get_experiment_family(str(trial["experiment_family_id"]))
        if family is None or family.get("universe_snapshot_id") != final_dataset_reference.universe_snapshot_id:
            raise ValueError("FINAL universe snapshot does not match registered experiment family")
        resolver = HistoricalEvidenceResolver(self.db)
        items = resolver.final_observations(final_dataset_reference)
        resolved_strategies = {card.strategy_name for item in items for card in item.scorecards}
        if not resolved_strategies.issubset(set(artifact.get("universe_lineage") or ())):
            raise ValueError("FINAL scorecard strategy is outside frozen universe lineage")
        replay = MetaSelectorBacktest(
            AdaptiveStrategySelector(selector_policy), replay_policy=replay_policy,
            resolver=resolver, db=self.db,
        )
        result = replay.run(
            items,
            meta_split="FINAL_OOS",
            registered_trial_id=str(artifact["selected_trial_id"]),
            frozen_policy_id=frozen_policy_id,
            data_hash=str(artifact["data_hash"]),
            frozen_b2_strategy=artifact.get("b2_strategy"),
            purge_periods=int(artifact["purge_periods"]),
            embargo_periods=int(artifact["embargo_periods"]),
        )
        if not items:
            raise ValueError("FINAL_OOS requires observations")
        execution_materialized_at = max(
            [item.decision_time for item in items]
            + [pd.Timestamp(row["timestamp"]).to_pydatetime() for item in items for row in item.historical_bars]
        ) + pd.Timedelta(microseconds=1).to_pytimedelta()
        self.db.persist_meta_selector_result(
            result, policy_version=replay_policy.version,
            selector_policy_version=selector_policy.version,
            selector_policy_hash=selector_policy.policy_hash,
            meta_split="FINAL_OOS", purge_periods=int(artifact["purge_periods"]),
            embargo_periods=int(artifact["embargo_periods"]), available_at=execution_materialized_at,
        )
        certificate_materialized_at = execution_materialized_at + pd.Timedelta(microseconds=1).to_pytimedelta()
        certificate = FinalOOSProvenanceCertificate.create(
            meta_run_id=result.meta_run_id,
            frozen_policy_id=frozen_policy_id,
            frozen_policy_hash=str(artifact["artifact_hash"]),
            selected_trial_id=str(artifact["selected_trial_id"]),
            selector_policy_hash=str(artifact["selector_policy_hash"]),
            meta_policy_hash=str(artifact["meta_policy_hash"]),
            scorecard_policy_hash=str(artifact["scorecard_policy_hash"]),
            dataset_ids={item.execution_dataset_id for item in items if item.execution_dataset_id},
            dataset_content_hashes={str(row["dataset_hash"]) for item in items for row in item.historical_bars if row.get("dataset_hash")},
            evidence_hashes=[decision.evidence_hash for decision in result.decisions],
            resolver_hash=_canonical_hash({"resolver": "HistoricalEvidenceResolver", "version": "phase2-10-v2"}),
            execution_hash=result.final_oos_execution_hash,
            final_oos_start=min(item.decision_time for item in items),
            final_oos_end=max(item.decision_time for item in items),
            materialized_at=certificate_materialized_at,
            cost_model_version=str(artifact["cost_model_version"]),
            cost_model_hash=str(artifact["cost_model_hash"]),
            purge_periods=int(artifact["purge_periods"]),
            embargo_periods=int(artifact["embargo_periods"]),
            acceptance_policy_version=str(artifact.get("acceptance_policy_version") or "phase2-10-acceptance-v1"),
            acceptance_policy_hash=str(artifact.get("acceptance_policy_hash") or ""),
            experiment_family_id=str(trial["experiment_family_id"]),
            universe_snapshot_id=final_dataset_reference.universe_snapshot_id,
            knowledge_cutoff=final_dataset_reference.knowledge_cutoff,
            regime_snapshot_ids=final_dataset_reference.regime_snapshot_ids,
            asset_state_snapshot_ids=final_dataset_reference.asset_state_snapshot_ids,
            risk_snapshot_ids=final_dataset_reference.risk_snapshot_ids,
            risk_snapshot_hashes=[item.risk_snapshot_hash for item in items if item.risk_snapshot_hash],
            dataset_certification_ids=[str(row["dataset_certification_id"]) for item in items for row in item.historical_bars if row.get("dataset_certification_id")],
            evidence_ids=[
                str(card.conditional_evidence_id) for item in items for card in item.scorecards
                if card.available_at <= item.decision_time and card.conditional_evidence_id
            ],
            outcome_series_ids=tuple(series_id for series_id in (final_dataset_reference.benchmark_series_id, *final_dataset_reference.strategy_series_ids) if series_id),
            execution_bar_hashes=[
                str(order["execution_lineage"]["historical_bar_hash"])
                for order in result.orders if order.get("execution_lineage")
            ],
            execution_bar_ids=[
                str(order["execution_lineage"]["historical_bar_id"])
                for order in result.orders
                if order.get("execution_lineage", {}).get("historical_bar_id")
            ],
            scorecard_ids=[
                str(card.scorecard_id) for item in items for card in item.scorecards
                if card.available_at <= item.decision_time
            ],
            conditional_evidence_ids=[
                str(card.conditional_evidence_id) for item in items for card in item.scorecards
                if card.available_at <= item.decision_time and card.conditional_evidence_id
            ],
            outcome_series_bindings=[
                binding for item in items for binding in item.outcome_series_bindings
            ],
            dataset_certification_bindings=[
                (str(row["dataset_id"]), str(row["dataset_certification_id"]))
                for item in items for row in item.historical_bars
                if row.get("dataset_id") and row.get("dataset_certification_id")
            ],
            dataset_bindings=[
                (str(row.get("dataset_id")), str(row.get("dataset_hash")))
                for item in items for row in item.historical_bars
                if row.get("dataset_id") and row.get("dataset_hash")
            ],
        )
        self.db.persist_final_oos_provenance_certificate(certificate)
        self.db.validate_final_oos_provenance_certificate(certificate.certificate_id)
        return result

    def evaluate_final_oos_acceptance(self, certificate_id: str) -> str:
        """Reload persisted FINAL artifacts and issue the sole empirical verdict."""
        certificate = self.db.validate_final_oos_provenance_certificate(certificate_id)
        artifact = self.db.load_frozen_meta_policy(str(certificate["frozen_policy_id"]))
        if str(artifact["acceptance_policy_version"]) != str(certificate["acceptance_policy_version"]):
            raise ValueError("acceptance policy version does not match certificate")
        if str(artifact["acceptance_policy_hash"]) != str(certificate["acceptance_policy_hash"]):
            raise ValueError("acceptance policy hash does not match certificate")
        result = self.db.validate_meta_selector_result_execution_hash(str(certificate["meta_run_id"]))
        if result["final_oos_execution_hash"] != certificate["execution_hash"]:
            raise ValueError("certificate result binding mismatch")
        if not certificate["dataset_ids"] or any(str(value).lower() == "synthetic" for value in certificate["dataset_content_hashes"]):
            return "PHASE 2.10 IMPLEMENTATION READY"
        if not all(
            certificate.get(field)
            for field in (
                "universe_snapshot_id", "dataset_certification_ids", "risk_snapshot_ids",
                "risk_snapshot_hashes", "evidence_ids", "outcome_series_ids",
                "execution_bar_hashes",
            )
        ):
            return "PHASE 2.10 IMPLEMENTATION READY"
        payload = dict(artifact.get("meta_policy_payload") or {})
        if payload.pop("schema_version", None) != "meta-replay-policy-v1":
            raise ValueError("unsupported stored acceptance policy payload")
        policy = MetaReplayPolicy(**payload)
        policy_hash = artifact["acceptance_policy_hash"]
        if not policy_hash or policy_hash != _acceptance_policy_hash(policy):
            raise ValueError("frozen artifact has no acceptance policy hash")
        metrics = dict(result["metrics"])
        baselines = dict(result["baselines"])
        stress = dict(result["stress_results"])
        simple_best = max(float(baselines[name]["total_return"]) for name in ("B2_static", "B3_equal_ensemble", "B4_risk_balanced"))
        validity_gates_pass = (
            metrics.get("final_oos_duration_days", 0.0) >= policy.min_final_oos_duration_days
            and metrics.get("decision_count", 0.0) >= policy.min_final_oos_observations
            and metrics.get("trade_count", 0.0) >= policy.min_independent_trades
            and metrics.get("evidence_coverage", 0.0) >= 1.0
            and metrics.get("robustness_certified", 0.0) >= 1.0
            and metrics.get("selector_stable", 0.0) >= 1.0
            and metrics.get("causal_verification", 0.0) >= 1.0
            and all(scenario in stress for scenario in ("1.5x_cost", "2.0x_cost", "reduced_liquidity", "delayed_execution"))
        )
        if not validity_gates_pass:
            return "PHASE 2.10 IMPLEMENTATION READY"
        gates_pass = (
            metrics.get("switch_count", 0.0) / max(metrics.get("decision_count", 0.0), 1.0) <= policy.max_switch_rate
            and metrics.get("max_drawdown", 0.0) >= -policy.max_drawdown
            and metrics.get("total_return", 0.0) - simple_best > policy.min_net_edge
            and float(stress.get("2.0x_cost", {}).get("total_return", -1.0)) >= simple_best
        )
        verdict = (
            CAUSALLY_VERIFIED_VERDICT
            if gates_pass
            else SIMPLER_BASELINE_VERDICT
        )
        acceptance_payload = {
            "meta_run_id": certificate["meta_run_id"], "certificate_id": certificate_id,
            "certificate_hash": certificate["certificate_hash"], "execution_hash": certificate["execution_hash"],
            "acceptance_policy_version": certificate["acceptance_policy_version"],
            "acceptance_policy_hash": certificate["acceptance_policy_hash"], "verdict": verdict,
        }
        self.db.persist_phase2_10_empirical_acceptance(
            acceptance_id=_canonical_hash(acceptance_payload)[:32],
            meta_run_id=str(certificate["meta_run_id"]), certificate_id=certificate_id,
            certificate_hash=str(certificate["certificate_hash"]), execution_hash=str(certificate["execution_hash"]),
            verdict=verdict, accepted_at=pd.Timestamp(certificate["materialized_at"]).to_pydatetime() + pd.Timedelta(microseconds=1).to_pytimedelta(),
            acceptance_hash=_canonical_hash(acceptance_payload),
            acceptance_policy_version=str(certificate["acceptance_policy_version"]),
            acceptance_policy_hash=str(certificate["acceptance_policy_hash"]),
        )
        return verdict

    def _derive_empirical_provenance(
        self, items: tuple[MetaSelectorObservation, ...], trial_id: str, frozen_policy_id: str, data_hash: str,
    ) -> dict[str, bool]:
        trial = self.db.get_research_trial(trial_id)
        artifact = self.db.load_frozen_meta_policy(frozen_policy_id)
        return {
            "non_synthetic_dataset": data_hash != "synthetic" and all(item.execution_dataset_id is not None for item in items),
            "registered_trial": trial is not None and trial.get("experiment_family_id") == "meta-selector-phase2-10",
            "frozen_policy": artifact.get("selected_trial_id") == trial_id,
            "causal_inputs": all(item.risk_state_as_of is not None for item in items),
            "isolated_final_oos": all(item.meta_split == "FINAL_OOS" for item in items),
        }

    def _register_candidate(self, candidate_id: str, selector: AdaptiveStrategySelector, replay_policy: MetaReplayPolicy, data_hash: str, purge_periods: int, embargo_periods: int, created_at: datetime | None, scorecard_policy_hash: str, b2_strategy: str | None, universe_lineage: list[str], *, universe_snapshot_id: str = "META") -> str:
        from experiments.trials import ExperimentFamilySpec, ResearchTrial
        timestamp = created_at or datetime.now(timezone.utc)
        schedule = MetaSelectorBacktest(selector, replay_policy=replay_policy).execution_adapter.cost_schedule
        cost_model_hash = MetaSelectorBacktest._cost_model_hash(schedule)
        family = ExperimentFamilySpec(
            experiment_family_id="meta-selector-phase2-10", hypothesis="causal meta selector policy", strategy_names=["meta_selector"], strategy_versions=["meta-selector-candidate"], universe_snapshot_id=universe_snapshot_id, timeframe="1d", feature_versions=["meta-selector-candidate"], cost_model_version=schedule.version, parameter_space={}, maximum_trials=100, selection_metric="total_return", walk_forward_design={"purge_periods": purge_periods, "embargo_periods": embargo_periods}, source_revision="phase2-10", created_at=timestamp,
        )
        self.db.register_experiment_family(family)
        trial = ResearchTrial(
            experiment_family_id=family.experiment_family_id, strategy_name="meta_selector", strategy_version=replay_policy.version, scope="META_SELECTOR", timeframe="1d", parameters={"candidate_id": candidate_id, "selector_policy_version": selector.policy.version, "selector_policy_hash": selector.policy.policy_hash, "scorecard_policy_hash": scorecard_policy_hash, "meta_replay_policy_version": replay_policy.version, "meta_replay_policy_hash": replay_policy.policy_hash, "data_hash": data_hash, "purge_periods": purge_periods, "embargo_periods": embargo_periods, "b2_strategy": b2_strategy, "strategy_universe": universe_lineage, "cost_model_version": schedule.version, "meta_split": "FINAL_OOS"}, source_revision="phase2-10", data_hash=data_hash, cost_model_hash=cost_model_hash, cost_model_version=schedule.version, frame_certification_id="meta-selector-certified", universe_snapshot_id=universe_snapshot_id, created_at=timestamp,
        )
        return self.db.create_research_trial(trial)


class HistoricalEvidenceResolver:
    """Explicit point-in-time resolver; deliberately exposes no latest fallback."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def final_observations(self, reference: FinalDatasetReference) -> tuple[MetaSelectorObservation, ...]:
        """Construct FINAL observations from immutable identifiers only."""
        if not isinstance(reference, FinalDatasetReference):
            raise ValueError("FINAL_OOS requires a FinalDatasetReference")
        has_snapshots = reference.regime_snapshot_ids or reference.asset_state_snapshot_ids or reference.risk_snapshot_ids
        if has_snapshots and (len(reference.decision_times) != len(reference.regime_snapshot_ids) or len(reference.decision_times) != len(reference.asset_state_snapshot_ids) or len(reference.decision_times) != len(reference.risk_snapshot_ids)):
            raise ValueError("FINAL dataset reference snapshot identifiers must align with decision times")
        observations: list[MetaSelectorObservation] = []
        for index, decision_time in enumerate(reference.decision_times):
            knowledge_cutoff = reference.knowledge_cutoff or decision_time
            regime_id = reference.regime_snapshot_ids[index] if reference.regime_snapshot_ids else ""
            asset_id = reference.asset_state_snapshot_ids[index] if reference.asset_state_snapshot_ids else ""
            risk_id = reference.risk_snapshot_ids[index] if reference.risk_snapshot_ids else ""
            regime = self.db.get_market_regime_snapshot(regime_id) if regime_id else None
            asset = self.db.get_asset_state_snapshot(asset_id) if asset_id else None
            risk = self.db.load_phase2_10_causal_risk_snapshot(risk_id) if risk_id else None
            if reference.dataset_id != "synthetic" and (regime is None or asset is None or risk is None):
                raise ValueError("FINAL PIT regime, asset-state, and risk snapshots are required")
            if reference.dataset_id != "synthetic" and (reference.benchmark_series_id is None or not reference.strategy_series_ids):
                raise ValueError("FINAL outcome series identifiers are required")
            if reference.dataset_id != "synthetic" and reference.outcome_materialization_cutoff is None:
                raise ValueError("FINAL outcome materialization cutoff is required")
            if regime is None:
                regime = {}
            if asset is None:
                asset = {}
            if risk is None:
                risk = {"as_of": decision_time}
            if pd.Timestamp(regime.get("decision_time")).to_pydatetime() > decision_time or pd.Timestamp(asset.get("decision_time")).to_pydatetime() > decision_time:
                raise ValueError("FINAL PIT selector snapshot is after the decision cutoff")
            if reference.dataset_id != "synthetic":
                for snapshot, label in ((regime, "regime"), (asset, "asset-state")):
                    created_at = snapshot.get("created_at")
                    if created_at is not None and pd.Timestamp(created_at).to_pydatetime() > knowledge_cutoff:
                        raise ValueError(f"FINAL {label} snapshot was recorded after the decision cutoff")
                if str(asset.get("symbol")) != reference.symbol or str(asset.get("exchange")) != reference.exchange:
                    raise ValueError("FINAL asset-state snapshot identity mismatch")
                if str(regime.get("market")) not in {reference.exchange, "NSE"}:
                    raise ValueError("FINAL regime snapshot market identity mismatch")
            if pd.Timestamp(risk["as_of"]).to_pydatetime() > decision_time:
                raise ValueError("FINAL risk snapshot is after the decision cutoff")
            if risk.get("recorded_at") is not None and pd.Timestamp(risk["recorded_at"]).to_pydatetime() > knowledge_cutoff:
                raise ValueError("FINAL risk snapshot was recorded after the knowledge cutoff")
            outcome_rows = self.db.list_phase2_10_outcome_series_at(
                decision_time,
                evaluation_cutoff=reference.outcome_materialization_cutoff or max(reference.decision_times),
                benchmark_series_id=reference.benchmark_series_id,
                strategy_series_ids=reference.strategy_series_ids,
            )
            if reference.dataset_id != "synthetic":
                returned_series = {str(row["series_id"]) for row in outcome_rows}
                required_series = {reference.benchmark_series_id, *reference.strategy_series_ids}
                if not required_series.issubset(returned_series):
                    raise ValueError("FINAL outcome series are unavailable at the evaluation cutoff")
                for row in outcome_rows:
                    if pd.Timestamp(row["observation_time"]).to_pydatetime() != decision_time:
                        raise ValueError("FINAL outcome series observation is misaligned")
                    if pd.Timestamp(row["holding_end"]).to_pydatetime() <= decision_time:
                        raise ValueError("FINAL outcome series holding interval is invalid")
            strategy_returns = {
                str(row["strategy_name"]): float(row["value"])
                for row in outcome_rows if row.get("series_type") == "STRATEGY" and row.get("strategy_name")
            }
            benchmark_return = next(
                (float(row["value"]) for row in outcome_rows if row.get("series_type") == "BENCHMARK"), 0.0
            )
            template = MetaSelectorObservation(
                decision_time=decision_time, symbol=reference.symbol, horizon="1d",
                market_regime=regime.get("raw_regime"), regime_confidence=float(regime.get("confidence", 1.0) or 1.0),
                asset_cluster=asset.get("behavior_cluster"), scorecards=(), strategy_returns=strategy_returns,
                outcome_series_bindings=tuple(sorted((str(row["series_id"]), str(row["content_hash"])) for row in outcome_rows)),
                benchmark_return=benchmark_return,
                meta_split="FINAL_OOS", data_hash=str(reference.dataset_content_hash),
                execution_dataset_id=None if reference.dataset_id == "synthetic" else reference.dataset_id,
                execution_timeframe=reference.timeframe,
                execution_exchange=reference.exchange, risk_state_as_of=pd.Timestamp(risk["as_of"]).to_pydatetime(),
                risk_snapshot_id=risk.get("snapshot_id"), risk_snapshot_hash=risk.get("snapshot_hash"),
                risk_snapshot=dict(risk),
                risk_batch_id=_canonical_hash({"decision_time": decision_time, "snapshot_id": risk.get("snapshot_id")})[:32] if risk.get("snapshot_id") else None,
                batch_start_snapshot_id=risk.get("snapshot_id"),
                knowledge_cutoff=knowledge_cutoff,
                label_start=decision_time, label_end=decision_time,
                evidence_start=decision_time, evidence_end=decision_time,
            )
            if reference.dataset_id == "synthetic":
                template = replace(
                    template,
                    historical_bars=(
                        {
                            "timestamp": decision_time + pd.Timedelta(minutes=1).to_pytimedelta(),
                            "symbol": reference.symbol, "open": 100.0, "high": 100.0,
                            "low": 100.0, "close": 100.0, "volume": 1_000_000.0,
                            "lagged_adv20": 1_000_000.0, "lagged_traded_value": 100_000_000.0,
                            "dataset_hash": reference.dataset_content_hash,
                        },
                    ),
                )
            resolved = self.observation_at(decision_time, template=template)
            if reference.dataset_id != "synthetic":
                if not resolved.historical_bars:
                    raise ValueError("FINAL certified execution source returned no bars")
                if any(str(row.get("dataset_hash")) != reference.dataset_content_hash for row in resolved.historical_bars):
                    raise ValueError("FINAL dataset content hash does not match certified execution source")
                for row in outcome_rows:
                    if row.get("symbol") != reference.symbol or row.get("universe_snapshot_id") != reference.universe_snapshot_id or row.get("timeframe") != reference.timeframe:
                        raise ValueError("FINAL outcome series identity mismatch")
            observations.append(resolved)
        return tuple(observations)

    def scorecards_at(self, decision_time: datetime, *, horizon: str | None = None, knowledge_cutoff: datetime | None = None) -> list[StrategyScorecard]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return [self._scorecard_from_row(row) for row in self.db.list_scorecards_at(decision_time, horizon=horizon, knowledge_cutoff=knowledge_cutoff)]

    def conditional_evidence_at(self, decision_time: datetime, *, strategy_name: str | None = None, knowledge_cutoff: datetime | None = None) -> list[dict[str, Any]]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return self.db.list_phase2_7_conditional_evidence_at(decision_time, strategy_name=strategy_name, knowledge_cutoff=knowledge_cutoff)

    def observation_at(self, decision_time: datetime, *, template: MetaSelectorObservation) -> MetaSelectorObservation:
        knowledge_cutoff = template.knowledge_cutoff or template.known_at or decision_time
        evidence = self.conditional_evidence_at(decision_time, knowledge_cutoff=knowledge_cutoff)
        visible_evidence_ids = {str(row.get("evidence_id")) for row in evidence}
        cards = tuple(
            card for card in self.scorecards_at(decision_time, horizon=template.horizon, knowledge_cutoff=knowledge_cutoff)
            if card.conditional_evidence_id is None or str(card.conditional_evidence_id) in visible_evidence_ids
        )
        if template.execution_dataset_id is not None:
            bars = self.execution_bars_at(
                decision_time,
                dataset_id=template.execution_dataset_id,
                timeframe=template.execution_timeframe,
                symbol=template.symbol,
                exchange=template.execution_exchange,
                knowledge_cutoff=knowledge_cutoff,
            )
            return replace(template, scorecards=cards, historical_bars=tuple(bars))
        return replace(template, scorecards=cards)

    def execution_bars_at(self, decision_time: datetime, *, dataset_id: str, timeframe: str, symbol: str | None = None, exchange: str | None = None, knowledge_cutoff: datetime | None = None) -> list[dict[str, Any]]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if timeframe != "1m":
            raise ValueError("only canonical 1m execution data is supported")
        if symbol is None or exchange is None:
            raise ValueError("execution resolver requires symbol and exchange identity")
        if exchange != "NSE":
            raise ValueError(f"no authoritative calendar is configured for exchange {exchange}")
        source = self.db.load_certified_1m_source(
            source_dataset_id=dataset_id, symbol=symbol, exchange=exchange,
            knowledge_cutoff=knowledge_cutoff,
        )
        bars = source["bars"].copy()
        if "timestamp" not in bars.columns:
            raise ValueError("certified execution source lacks timestamp identity")
        bars = bars.sort_values("timestamp").reset_index(drop=True)
        if "lagged_adv20" not in bars.columns and "volume" in bars.columns:
            bars["lagged_adv20"] = bars["volume"].shift(1).rolling(20, min_periods=1).mean()
        if "lagged_close" not in bars.columns and "close" in bars.columns:
            bars["lagged_close"] = bars["close"].shift(1)
        if "lagged_traded_value" not in bars.columns and {"lagged_close", "lagged_adv20"}.issubset(bars.columns):
            bars["lagged_traded_value"] = bars["lagged_close"] * bars["lagged_adv20"]
        calendar = build_nse_calendar()
        validation = calendar.validate_bars(pd.to_datetime(bars["timestamp"], utc=True), timeframe)
        if not validation.valid:
            raise ValueError("execution bars are outside the authoritative exchange calendar")
        resolved: list[dict[str, Any]] = []
        for row in bars.to_dict(orient="records"):
            timestamp = pd.Timestamp(row["timestamp"]).to_pydatetime()
            if timestamp <= decision_time:
                continue
            if str(row.get("symbol")) != symbol or str(row.get("exchange")) != exchange or str(row.get("timeframe")) != timeframe:
                raise ValueError("execution bar identity does not match the FINAL reference")
            row["dataset_id"] = dataset_id
            row["dataset_hash"] = source["content_hash"]
            row["dataset_certification_id"] = source.get("certification_id")
            row["dataset_available_at"] = source.get("dataset_available_at")
            row["known_at"] = row.get("available_at")
            if row.get("adjustment") is not None and str(row["adjustment"]) != str(source.get("adjustment")):
                raise ValueError("execution bar adjustment identity does not match the certified source")
            if hasattr(self.db, "get_historical_candle_availability"):
                authoritative_available_at = self.db.get_historical_candle_availability(
                    dataset_id, symbol, exchange, timeframe, timestamp,
                )
                if authoritative_available_at is None:
                    raise ValueError("execution bar lacks immutable candle availability")
                if row["known_at"] is not None and pd.Timestamp(row["known_at"]) != pd.Timestamp(authoritative_available_at):
                    raise ValueError("execution bar availability has conflicting lineage")
                row["known_at"] = authoritative_available_at
            row["timeframe"] = timeframe
            row["exchange"] = exchange
            if row["known_at"] is None:
                raise ValueError("execution bar lacks immutable candle availability")
            if pd.Timestamp(row["known_at"]).to_pydatetime() > timestamp:
                raise ValueError("execution bar became available after its execution timestamp")
            resolved.append(row)
        if not resolved:
            raise ValueError("no authoritative execution bar exists strictly after the decision cutoff")
        return resolved

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
        frozen_b2_strategy: str | None = None,
        empirical_provenance: dict[str, Any] | None = None,
        _skip_final_oos_validation: bool = False,
    ) -> MetaSelectorResult:
        if empirical_provenance is not None:
            raise ValueError("caller-supplied empirical provenance is not accepted")
        if isinstance(observations, FinalDatasetReference):
            raise ValueError("MetaSelectorBacktest requires resolved observations; use MetaResearchRunner.run_final_oos")
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
        costs: list[dict[str, Any]] = []
        risk_rows: list[dict[str, Any]] = []
        target_records: list[dict[str, Any]] = []
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
            target_records.append(
                {
                    "decision_time": item.decision_time,
                    "target_weights": dict(sorted(gated_targets.items())),
                }
            )
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
            costs.extend(generated.get("costs", []))
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
        metrics["final_oos_duration_days"] = float((items[-1].decision_time - items[0].decision_time).total_seconds() / 86400.0) if len(items) > 1 else 0.0
        metrics["evidence_coverage"] = float(sum(any(card.available_at <= item.decision_time for card in item.scorecards) for item in items) / max(len(items), 1))
        baselines = self._baselines(items, initial_equity, metrics, frozen_b2_strategy=frozen_b2_strategy)
        def stress_result(scenario_id: str, **kwargs: Any) -> dict[str, Any]:
            scenario = self.run(
                items, initial_equity=initial_equity, meta_split=meta_split,
                include_stress=False, registered_trial_id=registered_trial_id,
                trial_created_at=trial_created_at, data_hash=data_hash,
                cost_model_hash=None, _skip_final_oos_validation=True, **kwargs,
            )
            multiplier = float(kwargs.get("cost_multiplier", 1.0))
            schedule = self._stressed_cost_schedule(multiplier, items[0].decision_time if items else datetime.now(timezone.utc))
            return {
                "scenario_id": scenario_id,
                "scenario_config": dict(kwargs),
                "total_return": scenario.metrics["total_return"],
                "cost_model_version": schedule.version,
                "cost_model_hash": self._cost_model_hash(schedule),
                "execution_hash": scenario.final_oos_execution_hash,
                "fill_count": float(len(scenario.fills)),
                "execution_cost": scenario.metrics["total_execution_cost"],
                "orders": scenario.orders,
                "fills": scenario.fills,
                "costs": scenario.costs,
                "risk_decisions": scenario.risk_decisions,
                "attribution": scenario.attribution,
                "execution_lineage": [order.get("execution_lineage") for order in scenario.orders],
                "result_hash": scenario.final_oos_execution_hash,
            }

        stress_results = {
            "1.0x_cost": {"scenario_id": "1.0x_cost", "scenario_config": {"cost_multiplier": 1.0}, "total_return": metrics["total_return"], "cost_model_version": self.execution_adapter.cost_schedule.version, "cost_model_hash": self._cost_model_hash(self.execution_adapter.cost_schedule), "execution_hash": _canonical_hash({"orders": orders, "fills": fills, "costs": costs, "risk_decisions": risk_rows, "equity_curve": equity_rows}), "result_hash": _canonical_hash({"orders": orders, "fills": fills, "costs": costs, "risk_decisions": risk_rows, "equity_curve": equity_rows}), "fill_count": float(len(fills)), "execution_cost": metrics["total_execution_cost"], "orders": tuple(orders), "fills": tuple(fills), "costs": tuple(costs), "risk_decisions": tuple(risk_rows), "execution_lineage": [order.get("execution_lineage") for order in orders]},
        }
        if include_stress:
            stress_results.update({
                "1.5x_cost": stress_result("1.5x_cost", cost_multiplier=1.5),
                "2.0x_cost": stress_result("2.0x_cost", cost_multiplier=2.0),
                "switch_cost_stress": stress_result("switch_cost_stress", cost_multiplier=2.0),
                "delayed_execution": stress_result("delayed_execution", delay_periods=1),
                "reduced_liquidity": stress_result("reduced_liquidity", liquidity_multiplier=0.5),
            })
        required_stress_scenarios = ("1.5x_cost", "2.0x_cost", "reduced_liquidity", "delayed_execution")
        metrics["robustness_certified"] = float(all(
            stress_results.get(scenario, {}).get("scenario_id") == scenario
            and stress_results.get(scenario, {}).get("result_hash")
            and stress_results.get(scenario, {}).get("execution_hash")
            and "orders" in stress_results.get(scenario, {})
            and "fills" in stress_results.get(scenario, {})
            and "costs" in stress_results.get(scenario, {})
            for scenario in required_stress_scenarios
        ))
        metrics["selector_stable"] = float(
            metrics.get("switch_count", 0.0) / max(metrics.get("decision_count", 0.0), 1.0) <= self.replay_policy.max_switch_rate
        )
        metrics["causal_verification"] = float(all(
            row.get("risk_state_as_of") is not None for row in risk_rows
        ) and all(order.get("execution_lineage") for order in orders))
        baselines["B5_adaptive"] = {"total_return": metrics["total_return"], "selection": "adaptive_selector"}
        verdict = IMPLEMENTATION_READY_VERDICT
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
        stress_results["1.0x_cost"]["attribution"] = attribution
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
            "costs": costs,
        }
        evidence_hash = _canonical_hash(payload)
        execution_payload = {
            "decisions": [asdict(decision) for decision in decisions],
            "targets": [
                record for record in target_records
            ],
            "orders": orders,
            "fills": fills,
            "costs": costs,
            "risk_decisions": risk_rows,
            "cost_model_version": self._stressed_cost_schedule(cost_multiplier, items[0].decision_time if items else datetime.now(timezone.utc)).version,
            "cost_model_hash": effective_cost_model_hash,
            "equity_curve": equity_rows,
            "dataset_ids": sorted({item.execution_dataset_id for item in items if item.execution_dataset_id}),
            "dataset_hashes": sorted({item.data_hash for item in items}),
            "evidence_ids": sorted({
                card.evidence_hash for item in items for card in item.scorecards
                if card.available_at <= item.decision_time
            }),
            "risk_snapshot_ids": sorted({item.risk_snapshot_id for item in items if item.risk_snapshot_id}),
            "risk_snapshot_hashes": sorted({item.risk_snapshot_hash for item in items if item.risk_snapshot_hash}),
            "outcome_series_bindings": [binding for item in items for binding in item.outcome_series_bindings],
            "scorecard_ids": sorted({
                str(card.scorecard_id)
                for item in items for card in item.scorecards
                if card.available_at <= item.decision_time
            }),
            "conditional_evidence_ids": sorted({
                str(card.conditional_evidence_id)
                for item in items for card in item.scorecards
                if card.available_at <= item.decision_time and card.conditional_evidence_id
            }),
            "dataset_certification_ids": sorted({
                str(row.get("dataset_certification_id"))
                for item in items for row in item.historical_bars
                if row.get("dataset_certification_id")
            }),
            "execution_bar_lineage": [
                {key: row.get(key) for key in ("symbol", "timestamp", "dataset_id", "dataset_hash", "known_at")}
                for item in items for row in item.historical_bars
            ],
        }
        final_oos_execution_hash = _canonical_hash(execution_payload)
        pre_verdict_result_payload = {
            **payload,
            "execution_payload": execution_payload,
            "final_oos_execution_hash": final_oos_execution_hash,
        }
        pre_verdict_result_hash = _canonical_hash(pre_verdict_result_payload)
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
            costs=tuple(costs),
            risk_decisions=tuple(risk_rows),
            final_oos_execution_hash=final_oos_execution_hash,
            execution_payload=execution_payload,
            pre_verdict_result_hash=pre_verdict_result_hash,
            pre_verdict_result_payload=pre_verdict_result_payload,
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
            if item.risk_state_as_of is not None and item.risk_state_as_of > item.decision_time:
                raise ValueError("risk state cannot be known after selector decision")
            if item.prior_returns_available_at is not None and item.prior_returns_available_at > item.decision_time:
                raise ValueError("prior returns cannot be known after selector decision")
            if item.prior_asset_returns and item.prior_returns_available_at is None:
                raise ValueError("prior returns require point-in-time availability provenance")

    def _validate_future_trials(self, items: tuple[MetaSelectorObservation, ...]) -> None:
        if self.db is None:
            return
        for item in items:
            visible_trials = self.db.list_research_trials_at(item.decision_time)
            if any(pd.Timestamp(trial["created_at"]).to_pydatetime() >= item.decision_time for trial in visible_trials):
                raise ValueError("historical replay registry query returned a future trial")

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
        first_final = min(item.decision_time for item in final_items)
        if any(item.execution_dataset_id is not None for item in final_items):
            knowledge_cutoff = next(
                (item.knowledge_cutoff for item in final_items if item.knowledge_cutoff is not None),
                first_final,
            )
            trial = next(
                (
                    candidate for candidate in self.db.list_research_trials_at(
                        first_final,
                        knowledge_cutoff=knowledge_cutoff,
                    )
                    if candidate.get("trial_id") == registered_trial_id
                ),
                None,
            )
        else:
            trial = self.db.get_research_trial(registered_trial_id) if self.db is not None else None
        if trial is None:
            raise ValueError("FINAL_OOS requires a real Phase 2.1 research trial")
        trial_created_at = cast(datetime, trial["created_at"])
        if frozen_policy_id is not None:
            artifact = self.db.load_frozen_meta_policy(frozen_policy_id)
            expected_artifact = {
                "selected_trial_id": registered_trial_id,
                "selector_policy_version": self.selector.policy.version,
                "selector_policy_hash": self.selector.policy.policy_hash,
                "meta_policy_version": self.replay_policy.version,
                "meta_policy_hash": self.replay_policy.policy_hash,
                "scorecard_policy_hash": artifact["scorecard_policy_hash"],
                "data_hash": data_hash,
                "cost_model_hash": cost_model_hash,
                "purge_periods": purge_periods,
                "embargo_periods": embargo_periods,
            }
            for key, value in expected_artifact.items():
                if artifact.get(key) != value:
                    raise ValueError(f"FINAL_OOS frozen policy binding mismatch: {key}")
            trial_parameters = dict(trial.get("parameters") or {})
            if artifact.get("selection_result") != trial_parameters.get("candidate_id"):
                raise ValueError("FINAL_OOS frozen policy binding mismatch: selection_result")
            if artifact.get("selection_rule") != "max_validation_total_return_then_candidate_id":
                raise ValueError("FINAL_OOS frozen policy binding mismatch: selection_rule")
            if registered_trial_id not in set(artifact.get("candidate_trial_ids") or ()):
                raise ValueError("FINAL_OOS selected trial is not part of frozen candidate set")
            if trial.get("experiment_family_id") != "meta-selector-phase2-10":
                raise ValueError("FINAL_OOS trial belongs to the wrong experiment family")
            for key, value in {
                "selector_policy_version": artifact["selector_policy_version"],
                "selector_policy_hash": artifact["selector_policy_hash"],
                "scorecard_policy_hash": artifact["scorecard_policy_hash"],
                "meta_replay_policy_version": artifact["meta_policy_version"],
                "meta_replay_policy_hash": artifact["meta_policy_hash"],
                "data_hash": artifact["data_hash"],
                "purge_periods": artifact["purge_periods"],
                "embargo_periods": artifact["embargo_periods"],
                "b2_strategy": artifact.get("b2_strategy"),
                "strategy_universe": list(artifact.get("universe_lineage") or ()),
                "meta_split": "FINAL_OOS",
            }.items():
                if trial_parameters.get(key) != value:
                    raise ValueError(f"FINAL_OOS trial binding mismatch: {key}")
            if trial.get("cost_model_version") != artifact["cost_model_version"]:
                raise ValueError("FINAL_OOS trial binding mismatch: cost_model_version")
            if trial.get("cost_model_hash") != artifact["cost_model_hash"]:
                raise ValueError("FINAL_OOS trial binding mismatch: cost_model_hash")
            if trial.get("universe_snapshot_id") != artifact.get("universe_snapshot_id"):
                raise ValueError("FINAL_OOS trial binding mismatch: universe_snapshot_id")
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
        if not items:
            return
        split_order = {"TRAIN": 0, "VALIDATION": 1, "FINAL_OOS": 2}
        ordered = sorted(items, key=lambda item: item.decision_time)
        split_positions = [split_order.get(item.meta_split, 2) for item in ordered]
        if split_positions != sorted(split_positions):
            raise ValueError("meta observations must not move backward across split lifecycle")
        for left in ordered:
            for right in ordered:
                left_split = split_order.get(left.meta_split, 2)
                right_split = split_order.get(right.meta_split, 2)
                if left_split >= right_split:
                    continue
                if (right.decision_time - left.decision_time).total_seconds() / 86400.0 < purge_periods + embargo_periods:
                    raise ValueError("purge/embargo gap is not enforced between meta splits")
                windows = (left.label_start, left.label_end, left.evidence_start, left.evidence_end, right.label_start, right.label_end, right.evidence_start, right.evidence_end)
                if all(value is None for value in windows):
                    raise ValueError("explicit label and evidence windows are required for split purge/embargo")
                if any(value is None for value in windows):
                    raise ValueError("explicit label and evidence windows are required for split purge/embargo")
                left_ends = (cast(datetime, left.label_end), cast(datetime, left.evidence_end))
                right_starts = (cast(datetime, right.label_start), cast(datetime, right.evidence_start))
                if any(left_end >= right_start for left_end in left_ends for right_start in right_starts):
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
    def _static_train_winner(items: tuple[MetaSelectorObservation, ...]) -> str | None:
        scores: dict[str, float] = {}
        for item in items:
            if item.meta_split != "TRAIN":
                continue
            for card in item.scorecards:
                if getattr(card, "is_eligible", False) and card.available_at <= item.decision_time:
                    scores[card.strategy_name] = scores.get(card.strategy_name, 0.0) + float(card.overall_score)
        return sorted(scores, key=lambda name: (-scores[name], name))[0] if scores else None

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
        current_gross_exposure = sum(abs(value) * portfolio_value for value in adjusted.values())
        risk_snapshot = dict(item.risk_snapshot)
        strict_final = item.meta_split == "FINAL_OOS" and item.execution_dataset_id is not None
        if strict_final:
            required_snapshot_fields = (
                "snapshot_id", "snapshot_hash", "as_of", "exposure", "sector_exposure",
                "daily_pnl", "drawdown", "var_inputs", "var_result", "open_positions",
                "instrument_liquidity", "rolling_returns", "rolling_volatility", "data_hash",
            )
            missing = [field_name for field_name in required_snapshot_fields if field_name not in risk_snapshot]
            if missing:
                raise ValueError(f"FINAL risk snapshot is incomplete: {', '.join(missing)}")
            if item.risk_snapshot_id != risk_snapshot["snapshot_id"] or item.risk_snapshot_hash != risk_snapshot["snapshot_hash"]:
                raise ValueError("FINAL risk snapshot identifier/hash binding mismatch")
            snapshot_payload = {
                "snapshot_id": risk_snapshot["snapshot_id"],
                "as_of": pd.Timestamp(risk_snapshot["as_of"]).tz_convert("UTC").to_pydatetime(),
                "exposure": float(risk_snapshot["exposure"]),
                "sector_exposure": dict(sorted((str(key), float(value)) for key, value in dict(risk_snapshot["sector_exposure"]).items())),
                "daily_pnl": float(risk_snapshot["daily_pnl"]),
                "drawdown": float(risk_snapshot["drawdown"]),
                "var_inputs": tuple(float(value) for value in risk_snapshot["var_inputs"]),
                "var_result": float(risk_snapshot["var_result"]),
                "open_positions": dict(sorted((str(key), float(value)) for key, value in dict(risk_snapshot["open_positions"]).items())),
                "instrument_liquidity": dict(sorted((str(key), float(value)) for key, value in dict(risk_snapshot["instrument_liquidity"]).items())),
                "rolling_returns": tuple(float(value) for value in risk_snapshot["rolling_returns"]),
                "rolling_volatility": float(risk_snapshot["rolling_volatility"]),
                "data_hash": str(risk_snapshot["data_hash"]),
            }
            if _canonical_hash(snapshot_payload) != str(risk_snapshot["snapshot_hash"]):
                raise ValueError("FINAL risk snapshot content hash does not match consumed inputs")
            if item.batch_start_snapshot_id not in (None, risk_snapshot["snapshot_id"]):
                raise ValueError("FINAL risk batch start snapshot binding mismatch")
            snapshot_as_of = pd.Timestamp(risk_snapshot["as_of"]).to_pydatetime()
            if snapshot_as_of.tzinfo is None or snapshot_as_of > item.decision_time:
                raise ValueError("FINAL risk snapshot is not causally available")
            snapshot_exposure = float(risk_snapshot["exposure"])
            if abs(snapshot_exposure - current_gross_exposure) > max(portfolio_value * 1e-9, 1e-6):
                raise ValueError("FINAL risk snapshot does not match authoritative portfolio exposure")
            snapshot_positions = {str(key): float(value) for key, value in dict(risk_snapshot["open_positions"]).items()}
            actual_positions = {str(key): float(value) * portfolio_value for key, value in adjusted.items()}
            for symbol in set(snapshot_positions) | set(actual_positions):
                if abs(snapshot_positions.get(symbol, 0.0) - actual_positions.get(symbol, 0.0)) > max(portfolio_value * 1e-9, 1e-6):
                    raise ValueError("FINAL risk snapshot does not match authoritative open positions")
            snapshot_sectors = {str(key): float(value) for key, value in dict(risk_snapshot["sector_exposure"]).items()}
            actual_sectors: dict[str, float] = {}
            for symbol, weight in adjusted.items():
                sector = item.sectors.get(symbol, "UNKNOWN")
                actual_sectors[sector] = actual_sectors.get(sector, 0.0) + abs(float(weight)) * portfolio_value
            for sector in set(snapshot_sectors) | set(actual_sectors):
                if abs(snapshot_sectors.get(sector, 0.0) - actual_sectors.get(sector, 0.0)) > max(portfolio_value * 1e-9, 1e-6):
                    raise ValueError("FINAL risk snapshot does not match authoritative sector exposure")
            if item.risk_batch_id is None:
                raise ValueError("FINAL risk batch identity is required")
        risk_batch_id = item.risk_batch_id or _canonical_hash({"decision_time": item.decision_time, "symbol": item.symbol})[:32]
        batch_start_snapshot_id = item.batch_start_snapshot_id or item.risk_snapshot_id
        for symbol in symbols:
            current_weight = float(adjusted.get(symbol, 0.0))
            target_weight = float(target_weights.get(symbol, 0.0))
            delta_weight = target_weight - current_weight
            requested_notional = abs(delta_weight) * portfolio_value
            if requested_notional <= 1e-9:
                continue
            side = OrderSide.BUY if delta_weight > 0 else OrderSide.SELL
            liquidity_row = day.loc[symbol] if symbol in day.index else {}
            if strict_final and symbol not in risk_snapshot["instrument_liquidity"]:
                raise ValueError("FINAL risk snapshot lacks instrument liquidity for proposed symbol")
            liquidity_value = risk_snapshot.get("instrument_liquidity", {}).get(symbol, liquidity_row.get("lagged_traded_value", 0.0))
            daily_turnover_crore = float(liquidity_value or 0.0) / 10_000_000.0
            prior_state_hash = _canonical_hash({
                "risk_batch_id": risk_batch_id,
                "weights": adjusted,
                "gross_exposure": current_gross_exposure,
                "sector_exposure": {
                    sector: sum(abs(value) * portfolio_value for key, value in adjusted.items() if item.sectors.get(key, "UNKNOWN") == sector)
                    for sector in sorted({item.sectors.get(key, "UNKNOWN") for key in adjusted})
                },
                "open_positions": sorted(key for key, value in adjusted.items() if abs(value) > 1e-12),
            })
            var_result = risk_snapshot.get("var_result")
            if strict_final and var_result is None:
                raise ValueError("FINAL risk snapshot lacks causal VaR result")
            proposal = TradeProposal(
                symbol=symbol,
                sector=item.sectors.get(symbol, "UNKNOWN"),
                requested_notional=requested_notional,
                capital=portfolio_value,
                current_position_notional=current_weight * portfolio_value,
                order_side=side,
                current_gross_exposure=current_gross_exposure,
                current_sector_exposure=sum(abs(value) * portfolio_value for key, value in adjusted.items() if item.sectors.get(key, "UNKNOWN") == item.sectors.get(symbol, "UNKNOWN")),
                daily_pnl=float(risk_snapshot.get("daily_pnl", daily_pnl)),
                current_drawdown=float(risk_snapshot.get("drawdown", current_drawdown)),
                open_position_count=len([value for value in adjusted.values() if abs(value) > 1e-12]),
                daily_turnover_crore=daily_turnover_crore,
                estimated_portfolio_var_pct=(
                    float(cast(float, var_result))
                    if var_result is not None
                    else (float(pd.Series(prior_returns, dtype=float).std(ddof=0) * 2.33) if prior_returns else None)
                ),
            )
            decision = self.risk_engine.evaluate(proposal)
            approved_notional = float(decision.approved_notional)
            if decision.action == RiskAction.REJECT:
                executable_weight = current_weight
            else:
                signed = approved_notional / max(portfolio_value, 1e-12)
                executable_weight = current_weight + signed if side == OrderSide.BUY else current_weight - signed
            adjusted[symbol] = max(executable_weight, 0.0)
            current_gross_exposure = sum(abs(value) * portfolio_value for value in adjusted.values())
            rows.append(
                {
                    "timestamp": item.decision_time,
                    "symbol": symbol,
                    "side": side.value,
                    "requested_notional": requested_notional,
                    "approved_notional": approved_notional,
                    "current_gross_exposure": current_gross_exposure,
                    "current_sector_exposure": sum(
                        abs(value) * portfolio_value
                        for key, value in adjusted.items()
                        if item.sectors.get(key, "UNKNOWN") == item.sectors.get(symbol, "UNKNOWN")
                    ),
                    "open_position_count": len([value for value in adjusted.values() if abs(value) > 1e-12]),
                    "risk_action": decision.action.value,
                    "risk_reasons": tuple(decision.reasons),
                    "executed_notional": 0.0,
                    "order_ids": (),
                    "fill_ids": (),
                    "risk_batch_id": risk_batch_id,
                    "batch_start_snapshot_id": batch_start_snapshot_id,
                    "prior_state_hash": prior_state_hash,
                    "risk_snapshot_id": item.risk_snapshot_id,
                    "risk_snapshot_hash": item.risk_snapshot_hash,
                    "risk_state_as_of": risk_snapshot.get("as_of", item.risk_state_as_of or item.decision_time),
                    "risk_snapshot_data_hash": risk_snapshot.get("data_hash"),
                    "risk_decision_id": _canonical_hash([
                        "meta-risk", risk_batch_id, item.decision_time, symbol, side.value, prior_state_hash,
                    ])[:32],
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
        rows = [dict(row) for row in item.historical_bars if pd.Timestamp(row["timestamp"]).to_pydatetime() > decision_time]
        if not rows:
            raise ValueError("no historical execution bar strictly after selector decision")
        if any("dataset_hash" not in row and "data_hash" not in row for row in rows):
            raise ValueError("execution bars require historical dataset lineage")
        selected: list[dict[str, Any]] = []
        for symbol, symbol_rows in pd.DataFrame(rows).groupby("symbol", sort=True):
            earliest = min(symbol_rows.to_dict("records"), key=lambda row: pd.Timestamp(row["timestamp"]))
            selected.append(earliest)
        timestamps = {pd.Timestamp(row["timestamp"]) for row in selected}
        if len(timestamps) != 1:
            raise ValueError("heterogeneous execution timestamps require a calendar-aware rebalance adapter")
        rows = selected
        for row in rows:
            known_at = row.get("known_at")
            execution_timestamp = pd.Timestamp(row["timestamp"]).to_pydatetime()
            if known_at is not None and pd.Timestamp(known_at).to_pydatetime() > execution_timestamp:
                raise ValueError("historical execution bar was not available by execution time")
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
            symbol = str(record.get("symbol"))
            symbol_records = [row for row in records if str(row.get("symbol")) == symbol]
            if not symbol_records:
                raise ValueError("execution result symbol has no authoritative bar lineage")
            first = symbol_records[0]
            symbol_bar_hash = _canonical_hash(symbol_records)
            symbol_bar_id = str(first.get("historical_bar_id") or _canonical_hash({
                "dataset_id": first.get("dataset_id"),
                "dataset_hash": first.get("dataset_hash"),
                "symbol": symbol,
                "timestamp": first.get("timestamp"),
            })[:32])
            record["execution_lineage"] = {
                **lineage,
                "symbol": symbol,
                "historical_bar_id": symbol_bar_id,
                "historical_bar_hash": symbol_bar_hash,
                "historical_dataset_id": first.get("dataset_id"),
                "historical_dataset_content_hash": first.get("dataset_hash"),
                "dataset_certification_id": first.get("dataset_certification_id"),
            }

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
        *,
        frozen_b2_strategy: str | None = None,
    ) -> dict[str, dict[str, float | str]]:
        benchmark = [item.benchmark_return for item in items]
        cash = [item.cash_return for item in items]
        train_items = [item for item in items if item.meta_split == "TRAIN"]
        train_scores: dict[str, float] = {}
        for item in train_items:
            for card in item.scorecards:
                if getattr(card, "is_eligible", False) and card.available_at <= item.decision_time:
                    train_scores[card.strategy_name] = train_scores.get(card.strategy_name, 0.0) + float(card.overall_score)
        static_winner = frozen_b2_strategy or (sorted(train_scores, key=lambda name: (-train_scores[name], name))[0] if train_scores else None)
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
        stress_results: dict[str, dict[str, Any]],
        meta_split: str,
        *,
        empirical_provenance: dict[str, Any] | None = None,
    ) -> str:
        return "PHASE 2.10 IMPLEMENTATION READY"
