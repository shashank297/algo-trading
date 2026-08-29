"""Statistically defensible research framework and robustness evaluation.

Implements nested walk-forward with sealed final OOS, parameter plateau selection,
multi-tiered cost stress, swing execution stress, trial-registry linkage, and persistence.
"""

from __future__ import annotations

import copy
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field

from experiments.manager import source_revision
from experiments.models import ExperimentSpec
from experiments.statistical_tests import (
    BootstrapConfidenceIntervals,
    DSRResult,
    EvidenceStatus,
    MonteCarloRobustnessResult,
    PSRResult,
    compute_bootstrap_confidence_intervals,
    compute_dsr,
    compute_monte_carlo_robustness,
    compute_psr,
)
from experiments.trials import (
    ResearchIntegrityError,
    ResearchTrial,
    TrialStatus,
    canonical_hash,
    is_research_governance_error,
)
from storage.duckdb_manager import DuckDBManager
from trading_stack.backtest import EventDrivenBacktester, ExecutionModel, _compute_metrics
from trading_stack.calendars import MarketCalendar
from trading_stack.costs import IndianDeliveryCostSchedule
from trading_stack.datasets import ResearchDataset, SynchronizedPanelBuilder
from trading_stack.domain import AssetClass, StrategyScope
from trading_stack.features import FeatureFactory
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.pipeline import StrategyPipeline
from trading_stack.strategies import StrategyRegistry


class RobustnessPolicy(BaseModel):
    """Configuration policy governing statistical robustness evaluation."""
    policy_version: str = "2.6.0"
    plateau_min_ratio: float = 0.80
    sensitivity_weight: float = 0.30
    stability_weight: float = 0.20
    plateau_weight: float = 0.30
    raw_score_weight: float = 0.20
    min_performance_threshold: float = 0.0
    neighborhood_step: int = 1
    cost_multipliers: list[float] = Field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0])
    slippage_stress_bps: float = 10.0
    liquidity_stress_factor: float = 1.5
    overnight_gap_bps: float = 25.0
    stop_slippage_bps: float = 15.0
    execution_delay_bars: int = 1
    missed_fill_rate: float = 0.05
    bootstrap_resamples: int = 1000
    bootstrap_confidence: float = 0.95
    bootstrap_block_size: int = 10
    bootstrap_seed: int = 42
    monte_carlo_simulations: int = 1000
    monte_carlo_drawdown_threshold: float = 0.20
    monte_carlo_ruin_threshold: float = 0.50
    monte_carlo_seed: int = 42
    psr_benchmark_sharpe: float = 0.0
    annualization_factor: float = 252.0
    minimum_observations: int = 30
    purge_window: int = 5
    embargo_window: int = 5

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class ParameterRobustnessCandidate(BaseModel):
    """Candidate evaluation with neighborhood stability and plateau metrics."""
    parameters: dict[str, Any]
    parameter_hash: str
    train_score: float
    val_score: float | None = None
    neighbor_parameters: list[dict[str, Any]] = Field(default_factory=list)
    neighbor_scores: list[float] = Field(default_factory=list)
    neighbor_mean: float = 0.0
    neighbor_std: float = 0.0
    plateau_score: float = 0.0
    sensitivity_score: float = 0.0
    rank_stability: float = 1.0
    aggregate_robustness_score: float = 0.0
    selected: bool = False
    selection_reason: str | None = None


class NestedFoldEvidence(BaseModel):
    """Detailed evidence for a 3-stage nested walk-forward fold."""
    fold_id: str
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime
    test_start: datetime
    test_end: datetime
    purge_window: int
    embargo_window: int
    train_data_hash: str
    val_data_hash: str
    test_data_hash: str
    frame_certification_id: str | None = None
    selected_parameters: dict[str, Any]
    selected_trial_id: str | None = None
    train_metrics: dict[str, float] = Field(default_factory=dict)
    val_metrics: dict[str, float] = Field(default_factory=dict)
    final_oos_metrics: dict[str, float] = Field(default_factory=dict)
    evidence_hash: str


class CostStressResult(BaseModel):
    """Evaluated performance under an independent transaction-cost scenario."""
    multiplier: float
    slippage_bps_override: float | None = None
    liquidity_stress_factor: float | None = None
    metrics: dict[str, float]
    cost_schedule_summary: dict[str, Any]


class ExecutionStressResult(BaseModel):
    """Evaluated performance under an independent swing execution stress scenario."""
    scenario_name: str
    perturbation_params: dict[str, Any]
    metrics: dict[str, float]
    seed: int | None = None


class RobustnessBundle(BaseModel):
    """Comprehensive, immutable Phase 2.6 strategy robustness bundle."""
    robustness_id: str
    run_id: str
    experiment_family_id: str | None = None
    strategy_name: str
    strategy_version: str
    selected_trial_id: str | None = None
    evidence_status: EvidenceStatus
    nested_folds: list[NestedFoldEvidence]
    parameter_robustness: list[ParameterRobustnessCandidate]
    psr: PSRResult
    dsr: DSRResult
    bootstrap_intervals: dict[str, BootstrapConfidenceIntervals]
    monte_carlo: MonteCarloRobustnessResult
    cost_stress: list[CostStressResult]
    execution_stress: list[ExecutionStressResult]
    policy_version: str
    policy_hash: str
    data_hash: str
    evidence_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NestedWalkForwardSplitter:
    """Deterministic generator of 3-stage (Train, Validation, Sealed Test) nested walk-forward folds."""

    def split(
        self,
        total_bars: int,
        *,
        train_size: int,
        val_size: int,
        test_size: int,
        purge_window: int = 0,
        embargo_window: int = 0,
    ) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Generate integer index arrays for (train, val, test) across rolling nested folds."""
        if train_size <= 0 or val_size <= 0 or test_size <= 0:
            raise ValueError("train_size, val_size, and test_size must be positive integers.")
        if purge_window < 0 or embargo_window < 0:
            raise ValueError("purge_window and embargo_window must be non-negative.")

        min_required = train_size + val_size + test_size
        if total_bars < min_required:
            return []

        splits: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        cursor = train_size + val_size

        while cursor + test_size <= total_bars:
            # 1. Train indices: 0 to cursor - val_size, minus purge
            train_end = cursor - val_size
            if purge_window > 0 and train_end > purge_window:
                train_idx = np.arange(0, train_end - purge_window)
            else:
                train_idx = np.arange(0, train_end)

            # 2. Validation indices: cursor - val_size to cursor
            val_idx = np.arange(cursor - val_size, cursor)

            # 3. Test indices: cursor + embargo to cursor + test_size
            test_start = cursor + embargo_window if embargo_window > 0 else cursor
            test_end = cursor + test_size
            if test_start >= total_bars or test_start >= test_end:
                test_idx = np.arange(cursor, test_end)
            else:
                test_idx = np.arange(test_start, test_end)

            splits.append((train_idx, val_idx, test_idx))
            cursor += test_size

        return splits


class ParameterRobustnessSelector:

    """Selects parameters preferring broad, stable plateaus over isolated spikes."""

    def __init__(self, policy: RobustnessPolicy) -> None:
        self.policy = policy

    def define_neighbors(
        self,
        candidate: dict[str, Any],
        grid: dict[str, tuple[Any, ...]],
    ) -> list[dict[str, Any]]:
        """Identify immediate 1-step neighbors on numeric grid dimensions."""
        neighbors: list[dict[str, Any]] = []
        for key, values in grid.items():
            if key not in candidate:
                continue
            val = candidate[key]
            if val not in values:
                continue
            idx = values.index(val)
            # Step -1
            if idx > 0:
                neighbor_minus = dict(candidate)
                neighbor_minus[key] = values[idx - 1]
                neighbors.append(neighbor_minus)
            # Step +1
            if idx < len(values) - 1:
                neighbor_plus = dict(candidate)
                neighbor_plus[key] = values[idx + 1]
                neighbors.append(neighbor_plus)
        return neighbors

    def evaluate_candidates(
        self,
        scores_by_param: dict[str, float],
        candidates: list[dict[str, Any]],
        grid: dict[str, tuple[Any, ...]],
        val_scores_by_param: dict[str, float] | None = None,
    ) -> list[ParameterRobustnessCandidate]:
        """Compute neighborhood statistics, plateau scores, sensitivity, and aggregate ranking."""
        evaluated: list[ParameterRobustnessCandidate] = []

        for param in candidates:
            pkey = canonical_hash(param)
            train_score = scores_by_param.get(pkey, -999.0)
            val_score = val_scores_by_param.get(pkey) if val_scores_by_param else None

            neighbors = self.define_neighbors(param, grid)
            neighbor_scores: list[float] = []
            for n_param in neighbors:
                n_key = canonical_hash(n_param)
                if n_key in scores_by_param:
                    neighbor_scores.append(scores_by_param[n_key])

            if neighbor_scores:
                n_mean = float(np.mean(neighbor_scores))
                n_std = float(np.std(neighbor_scores))
                # Plateau score: fraction of neighbors within plateau_min_ratio or ratio of mean to center
                if train_score > 0:
                    plateau_ratio = max(0.0, min(2.0, n_mean / train_score))
                else:
                    plateau_ratio = 1.0 if n_mean >= train_score else 0.0

                # Sensitivity: drop-off between center and neighbor mean + neighbor standard deviation
                drop_off = max(0.0, train_score - n_mean) / (abs(train_score) + 1e-6)
                sensitivity = float(drop_off + (n_std / (abs(train_score) + 1e-6)))
            else:
                n_mean = train_score
                n_std = 0.0
                plateau_ratio = 1.0
                sensitivity = 0.0


            # Rank stability between train and val
            rank_stability = 1.0
            if val_score is not None and train_score > 0:
                rank_stability = max(0.0, min(1.0, 1.0 - abs(train_score - val_score) / (abs(train_score) + 1e-6)))

            # Composite aggregate robustness score
            # Higher plateau + lower sensitivity + higher stability + solid raw score
            agg_score = (
                self.policy.raw_score_weight * max(-2.0, min(5.0, train_score))
                + self.policy.plateau_weight * (plateau_ratio * max(0.0, train_score))
                - self.policy.sensitivity_weight * sensitivity
                + self.policy.stability_weight * rank_stability
            )

            evaluated.append(
                ParameterRobustnessCandidate(
                    parameters=param,
                    parameter_hash=pkey,
                    train_score=train_score,
                    val_score=val_score,
                    neighbor_parameters=neighbors,
                    neighbor_scores=neighbor_scores,
                    neighbor_mean=n_mean,
                    neighbor_std=n_std,
                    plateau_score=plateau_ratio,
                    sensitivity_score=sensitivity,
                    rank_stability=rank_stability,
                    aggregate_robustness_score=float(agg_score),
                    selected=False,
                )
            )

        if not evaluated:
            raise RuntimeError("No candidate evaluations available for parameter robustness selection.")

        # Sort deterministically by aggregate robustness score, then train score, then parameter hash
        evaluated.sort(key=lambda c: (c.aggregate_robustness_score, c.train_score, c.parameter_hash), reverse=True)
        evaluated[0].selected = True
        evaluated[0].selection_reason = (
            f"Selected by RobustnessPolicy v{self.policy.policy_version}: "
            f"aggregate_score={evaluated[0].aggregate_robustness_score:.4f}, "
            f"train_score={evaluated[0].train_score:.4f}, "
            f"plateau_score={evaluated[0].plateau_score:.4f}, "
            f"sensitivity={evaluated[0].sensitivity_score:.4f}"
        )

        return evaluated


class StressScenarioEngine:
    """Evaluates transaction-cost and swing execution stress scenarios deterministically."""

    def __init__(self, policy: RobustnessPolicy) -> None:
        self.policy = policy

    def evaluate_cost_stress(
        self,
        strategy_run: Any,
        base_cost_model: dict[str, Any],
        timeframe: str,
        starting_capital: float,
    ) -> list[CostStressResult]:
        """Recompute net performance across cost multipliers without modifying baseline."""
        results: list[CostStressResult] = []
        fills = getattr(strategy_run, "fills", pd.DataFrame())
        raw_curve = getattr(strategy_run, "equity_curve", pd.DataFrame())
        if raw_curve.empty:
            return results


        for mult in self.policy.cost_multipliers:
            stressed_cost_model = copy.deepcopy(base_cost_model)
            # Scale brokerage and statutory costs proportionally
            for key in ["fee_bps", "brokerage_rate_bps", "stt_buy_bps", "stt_sell_bps", "spread_bps"]:
                if key in stressed_cost_model:
                    stressed_cost_model[key] = float(stressed_cost_model[key]) * mult
            if "indian_delivery_costs" in stressed_cost_model and isinstance(stressed_cost_model["indian_delivery_costs"], dict):
                for key in ["brokerage_rate_bps", "stt_buy_bps", "stt_sell_bps", "spread_bps", "exchange_transaction_bps"]:
                    if key in stressed_cost_model["indian_delivery_costs"]:
                        stressed_cost_model["indian_delivery_costs"][key] = (
                            float(stressed_cost_model["indian_delivery_costs"][key]) * mult
                        )

            # Re-evaluate net return from curve and fills with cost scaling
            stressed_curve = raw_curve.copy()
            if not fills.empty and "cost" in fills.columns and not stressed_curve.empty:
                extra_cost_factor = mult - 1.0
                total_extra_cost = float((fills["cost"] * extra_cost_factor).sum())
                # Distribute extra cost across fill dates
                if total_extra_cost > 0:
                    net_ret = stressed_curve["net_return"].fillna(0.0).copy()
                    # Apply drag proportionally
                    per_bar_drag = total_extra_cost / (len(stressed_curve) * starting_capital)
                    stressed_net_ret = net_ret - per_bar_drag
                    stressed_curve["net_return"] = stressed_net_ret
                    stressed_curve["equity"] = starting_capital * (1.0 + stressed_net_ret).cumprod()
                    stressed_curve["drawdown"] = stressed_curve["equity"] / stressed_curve["equity"].cummax() - 1.0
                else:
                    stressed_net_ret = stressed_curve["net_return"].fillna(0.0)
            else:
                stressed_net_ret = stressed_curve["net_return"].fillna(0.0) if not stressed_curve.empty else pd.Series()

            metrics = _compute_metrics(
                equity_curve=stressed_curve,
                net_returns=stressed_net_ret,
                fills=fills,
                execution_model=ExecutionModel(),
                timeframe=timeframe,
                starting_capital=starting_capital,
            )

            metrics_dict = {
                "sharpe": float(metrics.sharpe) if metrics.sharpe is not None else 0.0,
                "cagr": float(metrics.cagr) if metrics.cagr is not None else 0.0,
                "max_drawdown": float(metrics.max_drawdown) if metrics.max_drawdown is not None else 0.0,
                "total_return": float(metrics.total_return) if metrics.total_return is not None else 0.0,
                "profit_factor": float(metrics.profit_factor) if metrics.profit_factor is not None else 0.0,
                "win_rate": float(metrics.win_rate) if metrics.win_rate is not None else 0.0,
            }

            results.append(
                CostStressResult(
                    multiplier=mult,
                    slippage_bps_override=None,
                    liquidity_stress_factor=None,
                    metrics=metrics_dict,
                    cost_schedule_summary={"multiplier": mult, "base_keys": list(stressed_cost_model.keys())},
                )
            )

        return results

    def evaluate_execution_stress(
        self,
        strategy_run: Any,
        timeframe: str,
        starting_capital: float,
    ) -> list[ExecutionStressResult]:
        """Evaluate overnight gap, stop slippage, delay, and missed fills."""
        results: list[ExecutionStressResult] = []
        raw_curve = getattr(strategy_run, "equity_curve", pd.DataFrame())
        fills = getattr(strategy_run, "fills", pd.DataFrame())

        if raw_curve.empty:
            return results

        # 1. Overnight Gap Stress
        gap_curve = raw_curve.copy()
        gap_drag_bps = self.policy.overnight_gap_bps / 10000.0
        # Perturb daily returns where position was held overnight
        gap_net_ret = gap_curve["net_return"].fillna(0.0) - (gap_drag_bps / max(1, len(gap_curve)))
        gap_curve["equity"] = starting_capital * (1.0 + gap_net_ret).cumprod()
        gap_curve["drawdown"] = gap_curve["equity"] / gap_curve["equity"].cummax() - 1.0
        gap_mets = _compute_metrics(
            equity_curve=gap_curve,
            net_returns=gap_net_ret,
            fills=fills,
            execution_model=ExecutionModel(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        results.append(
            ExecutionStressResult(
                scenario_name="overnight_gap_stress",
                perturbation_params={"gap_bps": self.policy.overnight_gap_bps},
                metrics={
                    "sharpe": float(gap_mets.sharpe) if gap_mets.sharpe is not None else 0.0,
                    "cagr": float(gap_mets.cagr) if gap_mets.cagr is not None else 0.0,
                    "max_drawdown": float(gap_mets.max_drawdown) if gap_mets.max_drawdown is not None else 0.0,
                    "total_return": float(gap_mets.total_return) if gap_mets.total_return is not None else 0.0,
                },
                seed=None,
            )
        )

        # 2. Stop Slippage Stress
        slip_curve = raw_curve.copy()
        slip_drag = (self.policy.stop_slippage_bps / 10000.0) * (len(fills) / max(1, len(slip_curve)))
        slip_net_ret = slip_curve["net_return"].fillna(0.0) - (slip_drag / max(1, len(slip_curve)))
        slip_curve["equity"] = starting_capital * (1.0 + slip_net_ret).cumprod()
        slip_curve["drawdown"] = slip_curve["equity"] / slip_curve["equity"].cummax() - 1.0
        slip_mets = _compute_metrics(
            equity_curve=slip_curve,
            net_returns=slip_net_ret,
            fills=fills,
            execution_model=ExecutionModel(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        results.append(
            ExecutionStressResult(
                scenario_name="stop_slippage_stress",
                perturbation_params={"stop_slippage_bps": self.policy.stop_slippage_bps},
                metrics={
                    "sharpe": float(slip_mets.sharpe) if slip_mets.sharpe is not None else 0.0,
                    "cagr": float(slip_mets.cagr) if slip_mets.cagr is not None else 0.0,
                    "max_drawdown": float(slip_mets.max_drawdown) if slip_mets.max_drawdown is not None else 0.0,
                    "total_return": float(slip_mets.total_return) if slip_mets.total_return is not None else 0.0,
                },
                seed=None,
            )
        )

        # 3. Execution Delay (1-bar lag simulation)
        delay_curve = raw_curve.copy()
        lagged_ret = delay_curve["net_return"].fillna(0.0).shift(self.policy.execution_delay_bars).fillna(0.0)
        delay_curve["equity"] = starting_capital * (1.0 + lagged_ret).cumprod()
        delay_curve["drawdown"] = delay_curve["equity"] / delay_curve["equity"].cummax() - 1.0
        delay_mets = _compute_metrics(
            equity_curve=delay_curve,
            net_returns=lagged_ret,
            fills=fills,
            execution_model=ExecutionModel(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        results.append(
            ExecutionStressResult(
                scenario_name="execution_delay",
                perturbation_params={"delay_bars": self.policy.execution_delay_bars},
                metrics={
                    "sharpe": float(delay_mets.sharpe) if delay_mets.sharpe is not None else 0.0,
                    "cagr": float(delay_mets.cagr) if delay_mets.cagr is not None else 0.0,
                    "max_drawdown": float(delay_mets.max_drawdown) if delay_mets.max_drawdown is not None else 0.0,
                    "total_return": float(delay_mets.total_return) if delay_mets.total_return is not None else 0.0,
                },
                seed=None,
            )
        )

        # 4. Missed Fills (Deterministic seeded omission)
        rng = np.random.default_rng(self.policy.monte_carlo_seed)
        missed_curve = raw_curve.copy()
        mask = rng.random(len(missed_curve)) < self.policy.missed_fill_rate
        missed_ret = missed_curve["net_return"].fillna(0.0).copy()
        # Zero out returns on missed fill bars
        missed_ret.loc[mask] = 0.0
        missed_curve["equity"] = starting_capital * (1.0 + missed_ret).cumprod()
        missed_curve["drawdown"] = missed_curve["equity"] / missed_curve["equity"].cummax() - 1.0
        missed_mets = _compute_metrics(
            equity_curve=missed_curve,
            net_returns=missed_ret,
            fills=fills,
            execution_model=ExecutionModel(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        results.append(
            ExecutionStressResult(
                scenario_name="missed_fills",
                perturbation_params={"missed_fill_rate": self.policy.missed_fill_rate},
                metrics={
                    "sharpe": float(missed_mets.sharpe) if missed_mets.sharpe is not None else 0.0,
                    "cagr": float(missed_mets.cagr) if missed_mets.cagr is not None else 0.0,
                    "max_drawdown": float(missed_mets.max_drawdown) if missed_mets.max_drawdown is not None else 0.0,
                    "total_return": float(missed_mets.total_return) if missed_mets.total_return is not None else 0.0,
                },
                seed=self.policy.monte_carlo_seed,
            )
        )

        return results


class RobustnessEvaluator:
    """Orchestrates end-to-end Phase 2.6 nested walk-forward robustness evaluation."""

    def __init__(
        self,
        db: DuckDBManager,
        *,
        policy: RobustnessPolicy | None = None,
        india_calendar: MarketCalendar | None = None,
        maximum_candidates: int = 32,
    ) -> None:
        self.db = db
        self.policy = policy or RobustnessPolicy()
        self.india_calendar = india_calendar
        self.maximum_candidates = maximum_candidates
        self.selector = ParameterRobustnessSelector(self.policy)
        self.stress_engine = StressScenarioEngine(self.policy)

    def evaluate(
        self,
        parent_run_id: str,
        spec: ExperimentSpec,
        *,
        train_size: int = 252,
        val_size: int = 63,
        test_size: int = 63,
        purge_window: int | None = None,
        embargo_window: int | None = None,
        starting_capital: float = 100_000.0,
    ) -> RobustnessBundle:
        """Execute full nested walk-forward evaluation, statistical tests, and persistence."""
        purge_w = purge_window if purge_window is not None else self.policy.purge_window
        embargo_w = embargo_window if embargo_window is not None else self.policy.embargo_window

        if purge_w < 0:
            raise ValueError(f"purge_window must be non-negative, got {purge_w}")
        if embargo_w < 0:
            raise ValueError(f"embargo_window must be non-negative, got {embargo_w}")

        metadata = StrategyRegistry.metadata(spec.strategy_name)
        source = self._source(spec, metadata.scope, metadata.required_lookback)
        dates = pd.DatetimeIndex(
            pd.to_datetime(source.panel["timestamp"], utc=True).drop_duplicates().sort_values()
        )

        candidates = self._candidates(spec.parameters, metadata.parameter_grid)
        nested_folds: list[NestedFoldEvidence] = []
        all_evaluated_candidates: list[ParameterRobustnessCandidate] = []
        final_test_returns_list: list[pd.Series] = []

        fold_step = test_size
        cursor = train_size + val_size

        while cursor + test_size <= len(dates):
            fold_idx = len(nested_folds) + 1
            fold_id = f"nfold-{fold_idx:03d}"

            # 1. Train slice: [0 : cursor - val_size]
            raw_train_dates = dates[: cursor - val_size]
            # Purge: remove observations at end of train overlapping with validation
            if purge_w > 0 and len(raw_train_dates) > purge_w:
                train_dates = raw_train_dates[:-purge_w]
            else:
                train_dates = raw_train_dates

            # 2. Validation slice: [cursor - val_size : cursor]
            val_dates = dates[cursor - val_size : cursor]

            # 3. Final OOS Test slice: [cursor : cursor + test_size]
            # Embargo: skip embargo_w bars after validation if configured
            test_start_idx = cursor + embargo_w if embargo_w > 0 else cursor
            test_end_idx = cursor + test_size
            if test_start_idx >= len(dates) or test_start_idx >= test_end_idx:
                test_dates = dates[cursor:test_end_idx]
            else:
                test_dates = dates[test_start_idx:test_end_idx]

            train_source = self._slice(source, train_dates[0], train_dates[-1])
            val_source = self._slice(source, val_dates[0], val_dates[-1])
            test_source = self._slice(source, test_dates[0], test_dates[-1])

            # Selection on TRAIN + VALIDATION only
            selected, train_mets, val_mets, fold_candidates = self._select_nested(
                spec, metadata.scope, train_source, val_source, candidates, metadata.parameter_grid, starting_capital, fold_id=fold_id,
            )
            all_evaluated_candidates.extend(fold_candidates)

            # FINAL OOS TEST is evaluated ONLY ONCE after candidate is frozen!
            final_replay = self._run(spec, metadata.scope, test_source, selected, starting_capital)
            final_run = getattr(final_replay, "run", final_replay)
            final_curve = getattr(final_run, "equity_curve", pd.DataFrame())
            final_ret = final_curve["net_return"].fillna(0.0) if not final_curve.empty else pd.Series()
            final_test_returns_list.append(final_ret)

            final_metrics_obj = _compute_metrics(
                equity_curve=final_curve,
                net_returns=final_ret,
                fills=getattr(final_run, "fills", pd.DataFrame()),
                execution_model=ExecutionModel(),
                timeframe=spec.timeframe,
                starting_capital=starting_capital,
            )
            final_mets = {
                "sharpe": float(final_metrics_obj.sharpe) if final_metrics_obj.sharpe is not None else 0.0,
                "cagr": float(final_metrics_obj.cagr) if final_metrics_obj.cagr is not None else 0.0,
                "max_drawdown": float(final_metrics_obj.max_drawdown) if final_metrics_obj.max_drawdown is not None else 0.0,
                "total_return": float(final_metrics_obj.total_return) if final_metrics_obj.total_return is not None else 0.0,
            }

            fold_evidence_payload = {
                "fold_id": fold_id,
                "train_start": train_dates[0].isoformat(),
                "train_end": train_dates[-1].isoformat(),
                "val_start": val_dates[0].isoformat(),
                "val_end": val_dates[-1].isoformat(),
                "test_start": test_dates[0].isoformat(),
                "test_end": test_dates[-1].isoformat(),
                "train_hash": train_source.data_hash,
                "val_hash": val_source.data_hash,
                "test_hash": test_source.data_hash,
                "selected_parameters": selected,
                "final_metrics": final_mets,
            }

            nested_folds.append(
                NestedFoldEvidence(
                    fold_id=fold_id,
                    train_start=train_dates[0].to_pydatetime(),
                    train_end=train_dates[-1].to_pydatetime(),
                    val_start=val_dates[0].to_pydatetime(),
                    val_end=val_dates[-1].to_pydatetime(),
                    test_start=test_dates[0].to_pydatetime(),
                    test_end=test_dates[-1].to_pydatetime(),
                    purge_window=purge_w,
                    embargo_window=embargo_w,
                    train_data_hash=train_source.data_hash,
                    val_data_hash=val_source.data_hash,
                    test_data_hash=test_source.data_hash,
                    frame_certification_id=source.frame_certification_id,
                    selected_parameters=selected,
                    selected_trial_id=getattr(fold_candidates[0], "parameter_hash", None),
                    train_metrics=train_mets,
                    val_metrics=val_mets,
                    final_oos_metrics=final_mets,
                    evidence_hash=canonical_hash(fold_evidence_payload),
                )
            )

            cursor += fold_step

        if not nested_folds:
            raise ValueError(
                f"Dataset length ({len(dates)}) insufficient for nested walk-forward "
                f"with train_size={train_size}, val_size={val_size}, test_size={test_size}."
            )

        # Concatenate out-of-sample returns across all folds
        combined_final_returns = pd.concat(final_test_returns_list, ignore_index=True) if final_test_returns_list else pd.Series(dtype=float)

        # Full run replay with selected candidate from final fold for stress tests
        selected_winner = nested_folds[-1].selected_parameters
        full_replay = self._run(spec, metadata.scope, source, selected_winner, starting_capital)
        strategy_run = getattr(full_replay, "run", full_replay)

        # 1. Probabilistic Sharpe Ratio (PSR)
        psr_result = compute_psr(
            combined_final_returns,
            benchmark_sharpe=self.policy.psr_benchmark_sharpe,
            annualization_factor=self.policy.annualization_factor,
            minimum_observations=self.policy.minimum_observations,
        )

        # 2. Deflated Sharpe Ratio (DSR) derived from Trial Registry
        registry_sharpes: list[float] = []
        registry_trial_ids: list[str] = []
        invalidated_count = 0
        effective_trial_count = len(candidates)

        if spec.experiment_family_id:
            try:
                trials_log = self.db.list_research_trials(family_id=spec.experiment_family_id)
                for tr in trials_log:
                    t_id = tr.get("trial_id")
                    st = tr.get("status")
                    if t_id:
                        registry_trial_ids.append(str(t_id))
                    if st in (TrialStatus.SUCCEEDED.value, TrialStatus.FAILED.value):
                        metrics_val = tr.get("metrics") or tr.get("metrics_json") or {}
                        if isinstance(metrics_val, str):
                            try:
                                metrics_val = json.loads(metrics_val)
                            except Exception:
                                metrics_val = {}
                        sh_val = metrics_val.get("sharpe") if isinstance(metrics_val, dict) else None
                        if sh_val is not None:
                            registry_sharpes.append(float(sh_val))
                    elif st == TrialStatus.INVALIDATED.value:
                        invalidated_count += 1

                if registry_sharpes:
                    effective_trial_count = len(registry_sharpes)
            except Exception as exc:
                logger.warning(f"Could not retrieve registry trials for family {spec.experiment_family_id}: {exc}")

        if not registry_sharpes:
            # Fallback to current evaluated candidates if registry empty
            for cand in all_evaluated_candidates:
                if cand.train_score > -900:
                    registry_sharpes.append(cand.train_score)

        dsr_result = compute_dsr(
            combined_final_returns,
            registry_sharpes,
            effective_trials=effective_trial_count,
            annualization_factor=self.policy.annualization_factor,
            minimum_observations=self.policy.minimum_observations,
            experiment_family_id=spec.experiment_family_id,
            trial_ids=registry_trial_ids,
            invalidated_count=invalidated_count,
        )

        # 3. Deterministic Seeded Bootstrap
        bootstrap_cis = compute_bootstrap_confidence_intervals(
            combined_final_returns,
            confidence_level=self.policy.bootstrap_confidence,
            n_resamples=self.policy.bootstrap_resamples,
            method="MOVING_BLOCK",
            block_size=self.policy.bootstrap_block_size,
            seed=self.policy.bootstrap_seed,
            minimum_observations=self.policy.minimum_observations,
            annualization_factor=self.policy.annualization_factor,
        )

        # 4. Monte Carlo Robustness
        monte_carlo_res = compute_monte_carlo_robustness(
            combined_final_returns,
            n_simulations=self.policy.monte_carlo_simulations,
            drawdown_threshold=self.policy.monte_carlo_drawdown_threshold,
            ruin_threshold=self.policy.monte_carlo_ruin_threshold,
            seed=self.policy.monte_carlo_seed,
            minimum_observations=self.policy.minimum_observations,
            annualization_factor=self.policy.annualization_factor,
        )

        # 5. Cost Stress Testing
        cost_stress_res = self.stress_engine.evaluate_cost_stress(
            strategy_run=strategy_run,
            base_cost_model=spec.cost_model,
            timeframe=spec.timeframe,
            starting_capital=starting_capital,
        )

        # 6. Swing Execution Stress Testing
        exec_stress_res = self.stress_engine.evaluate_execution_stress(
            strategy_run=strategy_run,
            timeframe=spec.timeframe,
            starting_capital=starting_capital,
        )

        overall_status = EvidenceStatus.VALID
        if psr_result.status != EvidenceStatus.VALID or dsr_result.status != EvidenceStatus.VALID:
            overall_status = EvidenceStatus.INSUFFICIENT_EVIDENCE

        # Compute deterministic evidence bundle identity
        bundle_identity_payload = {
            "run_id": parent_run_id,
            "strategy_name": spec.strategy_name,
            "strategy_version": metadata.version,
            "data_hash": source.data_hash,
            "policy_hash": self.policy.policy_hash,
            "folds_count": len(nested_folds),
            "selected_parameters": selected_winner,
        }
        robustness_id = canonical_hash(bundle_identity_payload)

        evidence_hash_payload = {
            "robustness_id": robustness_id,
            "folds": [f.evidence_hash for f in nested_folds],
            "psr": psr_result.model_dump(mode="json"),
            "dsr": dsr_result.model_dump(mode="json"),
            "cost_stress": [c.model_dump(mode="json") for c in cost_stress_res],
            "exec_stress": [e.model_dump(mode="json") for e in exec_stress_res],
        }
        evidence_hash = canonical_hash(evidence_hash_payload)

        bundle = RobustnessBundle(
            robustness_id=robustness_id,
            run_id=parent_run_id,
            experiment_family_id=spec.experiment_family_id,
            strategy_name=spec.strategy_name,
            strategy_version=metadata.version,
            selected_trial_id=nested_folds[-1].selected_trial_id,
            evidence_status=overall_status,
            nested_folds=nested_folds,
            parameter_robustness=all_evaluated_candidates,
            psr=psr_result,
            dsr=dsr_result,
            bootstrap_intervals=bootstrap_cis,
            monte_carlo=monte_carlo_res,
            cost_stress=cost_stress_res,
            execution_stress=exec_stress_res,
            policy_version=self.policy.policy_version,
            policy_hash=self.policy.policy_hash,
            data_hash=source.data_hash,
            evidence_hash=evidence_hash,
            created_at=datetime.now(timezone.utc),
        )

        # Save to DuckDB immutably
        self.db.save_robustness_evaluation(bundle)

        return bundle

    def _select_nested(
        self,
        spec: ExperimentSpec,
        scope: StrategyScope,
        train_source: ResearchDataset,
        val_source: ResearchDataset,
        candidates: list[dict[str, Any]],
        parameter_grid: dict[str, tuple[Any, ...]],
        capital: float,
        fold_id: str,
    ) -> tuple[dict[str, Any], dict[str, float], dict[str, float], list[ParameterRobustnessCandidate]]:
        """Evaluate candidates on TRAIN and VALIDATION and select using ParameterRobustnessSelector."""
        metadata = StrategyRegistry.metadata(spec.strategy_name)
        revision = source_revision(Path(__file__).resolve().parent.parent)
        train_start = pd.to_datetime(train_source.panel["timestamp"], utc=True).min() if not train_source.panel.empty else None
        train_end = pd.to_datetime(train_source.panel["timestamp"], utc=True).max() if not train_source.panel.empty else None

        scores_by_param: dict[str, float] = {}
        val_scores_by_param: dict[str, float] = {}
        candidate_trial_ids: dict[str, str] = {}
        train_metrics_map: dict[str, dict[str, float]] = {}
        val_metrics_map: dict[str, dict[str, float]] = {}

        for parameters in candidates:
            pkey = canonical_hash(parameters)
            trial_id: str | None = None
            existing_trial = None

            if self.db and spec.experiment_family_id:
                trial = ResearchTrial(
                    experiment_family_id=spec.experiment_family_id,
                    strategy_name=spec.strategy_name,
                    strategy_version=metadata.version,
                    scope=scope.value,
                    symbol=spec.universe[0] if scope == StrategyScope.SINGLE_ASSET else None,
                    universe_snapshot_id=spec.universe_snapshot_id,
                    timeframe=spec.timeframe,
                    parameters=parameters,
                    source_revision=revision,
                    data_hash=train_source.data_hash,
                    cost_model_hash=canonical_hash(spec.cost_model),
                    cost_model_version=spec.cost_model_version,
                    feature_version=spec.feature_version,
                    frame_certification_id=train_source.frame_certification_id,
                    fold_id=fold_id,
                    train_start=train_start.to_pydatetime() if train_start is not None and hasattr(train_start, "to_pydatetime") else None,
                    train_end=train_end.to_pydatetime() if train_end is not None and hasattr(train_end, "to_pydatetime") else None,
                    status=TrialStatus.PLANNED,
                )
                existing_trial = self.db.get_research_trial(trial.trial_id)
                if existing_trial and existing_trial.get("status") in {"SUCCEEDED", "FAILED", "INVALIDATED", "CANCELLED"}:
                    trial_id = trial.trial_id
                else:
                    trial_id = self.db.create_research_trial(trial)
                    self.db.transition_research_trial(trial_id, "RUNNING")

            try:
                # 1. Train replay
                train_replay = self._run(spec, scope, train_source, parameters, capital)
                t_run = getattr(train_replay, "run", train_replay)
                t_sh = float(t_run.metrics.sharpe) if getattr(t_run.metrics, "sharpe", None) is not None else 0.0
                scores_by_param[pkey] = t_sh
                train_metrics_map[pkey] = {
                    "sharpe": t_sh,
                    "cagr": float(t_run.metrics.cagr) if getattr(t_run.metrics, "cagr", None) is not None else 0.0,
                    "max_drawdown": float(t_run.metrics.max_drawdown) if getattr(t_run.metrics, "max_drawdown", None) is not None else 0.0,
                }

                # 2. Validation replay
                val_replay = self._run(spec, scope, val_source, parameters, capital)
                v_run = getattr(val_replay, "run", val_replay)
                v_sh = float(v_run.metrics.sharpe) if getattr(v_run.metrics, "sharpe", None) is not None else 0.0
                val_scores_by_param[pkey] = v_sh
                val_metrics_map[pkey] = {
                    "sharpe": v_sh,
                    "cagr": float(v_run.metrics.cagr) if getattr(v_run.metrics, "cagr", None) is not None else 0.0,
                    "max_drawdown": float(v_run.metrics.max_drawdown) if getattr(v_run.metrics, "max_drawdown", None) is not None else 0.0,
                }

                if self.db and trial_id:
                    candidate_trial_ids[pkey] = trial_id
                    if not existing_trial or existing_trial.get("status") not in {"SUCCEEDED", "FAILED", "INVALIDATED", "CANCELLED"}:
                        self.db.transition_research_trial(
                            trial_id,
                            "SUCCEEDED",
                            metrics={
                                "sharpe": t_sh,
                                "val_sharpe": v_sh,
                                "cagr": train_metrics_map[pkey]["cagr"],
                                "max_drawdown": train_metrics_map[pkey]["max_drawdown"],
                            },
                        )
            except Exception as exc:
                if self.db and trial_id and (not existing_trial or existing_trial.get("status") not in {"SUCCEEDED", "FAILED", "INVALIDATED", "CANCELLED"}):
                    self.db.transition_research_trial(trial_id, "FAILED", error_message=str(exc))
                if is_research_governance_error(exc):
                    raise ResearchIntegrityError(
                        f"Governed nested candidate {parameters} failed: {exc}"
                    ) from exc
                logger.warning(f"Nested candidate {parameters} failed: {exc}")


        evaluated_candidates = self.selector.evaluate_candidates(
            scores_by_param=scores_by_param,
            candidates=candidates,
            grid=parameter_grid,
            val_scores_by_param=val_scores_by_param,
        )

        winning_cand = evaluated_candidates[0]
        win_key = winning_cand.parameter_hash
        if spec.experiment_family_id and win_key in candidate_trial_ids:
            self.db.mark_trial_selected(candidate_trial_ids[win_key], True)

        return (
            dict(winning_cand.parameters),
            train_metrics_map.get(win_key, {}),
            val_metrics_map.get(win_key, {}),
            evaluated_candidates,
        )

    def _source(self, spec: ExperimentSpec, scope: StrategyScope, lookback: int) -> ResearchDataset:
        if scope == StrategyScope.CROSS_SECTIONAL:
            return SynchronizedPanelBuilder(
                self.db,
                calendar=self.india_calendar,
                strict_calendar=self.india_calendar is not None,
                require_authoritative_certification=spec.require_authoritative_certification,
            ).build(
                spec.universe,
                spec.timeframe,
                universe_snapshot_id=spec.universe_snapshot_id,
                benchmark_symbol=spec.benchmark_symbol,
                minimum_lookback=lookback,
            )
        pipeline = StrategyPipeline(
            self.db,
            require_authoritative_certification=spec.require_authoritative_certification,
            strict_calendar=self.india_calendar is not None,
        )
        symbol = spec.universe[0]
        bars = pipeline.load_candles(symbol, spec.timeframe)
        if bars.empty:
            raise ValueError(f"No candles found for {symbol} {spec.timeframe}.")
        if self.india_calendar is not None:
            validation = self.india_calendar.validate_bars(bars["timestamp"], spec.timeframe)
            if validation.out_of_session_count:
                raise ValueError("Source contains bars outside the verified NSE calendar.")
        panel = FeatureFactory().build(bars, timezone_name="Asia/Kolkata")
        panel["symbol"] = symbol
        frame_cert_id = getattr(pipeline, "_last_frame_certification_id", None)
        contributing_dataset_ids = tuple(
            str(x).strip() for x in bars["dataset_id"].dropna().unique() if str(x).strip()
        ) if "dataset_id" in bars.columns else ()
        dq_certs: list[str] = []
        dataset_hashes: dict[str, str] = {}
        pit_hash: str | None = None
        if frame_cert_id:
            row = self.db.conn.execute(
                "SELECT dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash FROM research_frame_certifications WHERE frame_certification_id = ?",
                [frame_cert_id],
            ).fetchone()
            if row:
                if row[0]:
                    try:
                        dataset_hashes = json.loads(str(row[0]))
                    except Exception:
                        pass
                if row[1]:
                    try:
                        dq_certs = json.loads(str(row[1]))
                    except Exception:
                        pass
                pit_hash = str(row[2]) if row[2] else None
        return ResearchDataset(
            universe_snapshot_id=spec.universe_snapshot_id,
            dataset_snapshot_ids={symbol: contributing_dataset_ids[0] if contributing_dataset_ids else None},
            panel=panel,
            frame_certification_id=frame_cert_id,
            contributing_dataset_ids=contributing_dataset_ids,
            dq_certification_ids=tuple(dq_certs),
            dataset_content_hashes=dataset_hashes,
            pit_evidence_hash=pit_hash,
        )

    def _candidates(
        self,
        explicit: dict[str, Any],
        parameter_grid: dict[str, tuple[Any, ...]],
    ) -> list[dict[str, Any]]:
        variable = {key: values for key, values in parameter_grid.items() if key not in explicit}
        if not variable:
            return [dict(explicit)]
        keys = sorted(variable)
        combinations = itertools.product(*(variable[key] for key in keys))
        candidates = [
            {**explicit, **dict(zip(keys, values))}
            for values in itertools.islice(combinations, self.maximum_candidates)
        ]
        return candidates or [dict(explicit)]

    def _run(
        self,
        spec: ExperimentSpec,
        scope: StrategyScope,
        source: ResearchDataset,
        parameters: dict[str, Any],
        capital: float,
    ) -> Any:
        strategy = StrategyRegistry.create(spec.strategy_name, **parameters)
        if scope == StrategyScope.CROSS_SECTIONAL:
            allowed = set(IndianDeliveryCostSchedule.__dataclass_fields__)
            schedule_values: dict[str, Any] = {
                key: value for key, value in spec.cost_model.items() if key in allowed
            }
            schedule = IndianDeliveryCostSchedule(**schedule_values)
            return PortfolioEventBacktester(schedule).run(
                strategy,
                source,
                starting_capital=capital,
                timeframe=spec.timeframe,
                parameters=parameters,
                mode="event-driven",
            )
        allowed = set(ExecutionModel.__dataclass_fields__)
        execution_values: dict[str, Any] = {
            key: value for key, value in spec.cost_model.items() if key in allowed
        }
        indian = {
            key: value for key, value in spec.cost_model.items()
            if key in IndianDeliveryCostSchedule.__dataclass_fields__
        }
        if indian:
            execution_values["indian_delivery_costs"] = indian
        return EventDrivenBacktester(ExecutionModel(**execution_values)).run(
            strategy,
            source.panel,
            starting_capital=capital,
            market_asset_class=AssetClass.INDIA_EQUITY,
            symbol=spec.universe[0],
            timeframe=spec.timeframe,
            parameters=parameters,
        )

    @staticmethod
    def _slice(source: ResearchDataset, start: pd.Timestamp, end: pd.Timestamp) -> ResearchDataset:
        timestamps = pd.to_datetime(source.panel["timestamp"], utc=True)
        panel = source.panel.loc[(timestamps >= start) & (timestamps <= end)].copy()
        return ResearchDataset(
            universe_snapshot_id=source.universe_snapshot_id,
            dataset_snapshot_ids=dict(source.dataset_snapshot_ids),
            panel=panel,
            benchmark_symbol=source.benchmark_symbol,
            benchmark_provider_symbol=source.benchmark_provider_symbol,
            benchmark_relationship=source.benchmark_relationship,
            exclusions=source.exclusions.copy(),
            survivorship_bias=source.survivorship_bias,
            universe_name=source.universe_name,
            source_basis=source.source_basis,
            canonical_basis=source.canonical_basis,
            research_basis=source.research_basis,
            corporate_action_version=source.corporate_action_version,
            frame_certification_id=source.frame_certification_id,
            contributing_dataset_ids=source.contributing_dataset_ids,
            dq_certification_ids=source.dq_certification_ids,
            dataset_content_hashes=dict(source.dataset_content_hashes),
            pit_evidence_hash=source.pit_evidence_hash,
        )
