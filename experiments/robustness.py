"""Statistically defensible research framework and robustness evaluation.

Implements nested walk-forward with sealed final OOS, parameter plateau selection,
multi-tiered cost stress, swing execution stress, trial-registry linkage, and persistence.
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field
import scipy.stats

from experiments.manager import source_revision
from experiments.models import ExperimentSpec
from experiments.statistical_tests import (
    BootstrapConfidenceIntervals,
    DSRResult,
    EvidenceStatus,
    MonteCarloRobustnessResult,
    PSRResult,
    TrialCountSource,
    compute_bootstrap_confidence_intervals,
    compute_monte_carlo_robustness,
    compute_psr,
    resolve_authoritative_dsr,
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
    """Candidate evaluation with neighborhood stability, plateau metrics, and fold ranks."""
    parameters: dict[str, Any]
    parameter_hash: str
    train_score: float
    val_score: float | None = None
    neighbor_parameters: list[dict[str, Any]] = Field(default_factory=list)
    neighbor_scores: list[float] = Field(default_factory=list)
    neighbor_mean: float = 0.0
    neighbor_std: float = 0.0
    neighbor_min: float = 0.0
    plateau_neighbor_count: int = 0
    neighbor_count: int = 0
    plateau_fraction: float = 0.0
    plateau_width: float = 0.0
    plateau_score: float = 0.0
    sensitivity_score: float = 0.0
    train_rank: int = 1
    val_rank: int | None = None
    rank_delta: int | None = None
    rank_stability: float = 1.0
    aggregate_robustness_score: float = 0.0
    selected: bool = False
    selection_reason: str | None = None


class NestedFoldEvidence(BaseModel):
    """Detailed evidence for a 3-stage nested walk-forward fold with complete dataset lineage."""
    fold_id: str
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime
    test_start: datetime
    test_end: datetime
    purge_window: int
    embargo_window: int
    purged_train_range: list[str] = Field(default_factory=list)
    purged_val_range: list[str] = Field(default_factory=list)
    embargoed_ranges: list[str] = Field(default_factory=list)
    dataset_snapshot_ids: dict[str, str | None] = Field(default_factory=dict)
    contributing_dataset_ids: list[str] = Field(default_factory=list)
    dataset_content_hashes: dict[str, str] = Field(default_factory=dict)
    train_data_hash: str
    val_data_hash: str
    test_data_hash: str
    frame_certification_id: str | None = None
    selected_parameters: dict[str, Any]
    selected_parameter_hash: str = ""
    selected_trial_id: str | None = None
    train_metrics: dict[str, float] = Field(default_factory=dict)
    val_metrics: dict[str, float] = Field(default_factory=dict)
    final_oos_metrics: dict[str, float] = Field(default_factory=dict)
    evidence_hash: str


class CostStressResult(BaseModel):
    """Evaluated performance under an independent transaction-cost scenario."""
    multiplier: float
    slippage_bps_override: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    cost_schedule_summary: dict[str, Any] = Field(default_factory=dict)
    status: EvidenceStatus = EvidenceStatus.VALID
    reason: str | None = None


class ExecutionStressResult(BaseModel):
    """Evaluated performance under an independent swing execution stress scenario."""
    scenario_name: str
    perturbation_params: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    seed: int | None = None
    status: EvidenceStatus = EvidenceStatus.VALID
    reason: str | None = None


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


class FoldSplitPlan(BaseModel):
    """Authoritative fold partition plan with dual-boundary purge and post-test embargo."""
    fold_id: str
    train_indices: list[int]
    val_indices: list[int]
    test_indices: list[int]
    purged_train_indices: list[int] = Field(default_factory=list)
    purged_val_indices: list[int] = Field(default_factory=list)
    embargoed_indices: list[int] = Field(default_factory=list)


class NestedWalkForwardSplitter:
    """Deterministic, authoritative generator of 3-stage nested walk-forward folds."""

    def split_plans(
        self,
        total_bars: int,
        *,
        train_size: int,
        val_size: int,
        test_size: int,
        purge_window: int = 0,
        embargo_window: int = 0,
    ) -> list[FoldSplitPlan]:
        """Generate structured fold plans with dual-boundary purge and post-test embargo."""
        if train_size <= 0 or val_size <= 0 or test_size <= 0:
            raise ValueError("train_size, val_size, and test_size must be positive integers.")
        if purge_window < 0 or embargo_window < 0:
            raise ValueError("purge_window and embargo_window must be non-negative.")

        min_required = train_size + val_size + test_size
        if total_bars < min_required:
            return []

        plans: list[FoldSplitPlan] = []
        cursor = train_size + val_size
        fold_idx = 1
        previous_test_end: int | None = None

        while cursor + test_size <= total_bars:
            fold_id = f"nfold-{fold_idx:03d}"

            # 1. Train interval: [0 : cursor - val_size]
            raw_train_end = cursor - val_size
            if purge_window > 0:
                if purge_window >= raw_train_end:
                    raise ValueError("PURGE_WINDOW_EXHAUSTS_TRAIN")
                train_idx = list(range(0, raw_train_end - purge_window))
                purged_train = list(range(raw_train_end - purge_window, raw_train_end))
            else:
                train_idx = list(range(0, raw_train_end))
                purged_train = []

            # 2. Validation interval: [cursor - val_size : cursor]
            raw_val_start = cursor - val_size
            raw_val_end = cursor
            val_len = raw_val_end - raw_val_start
            if purge_window > 0:
                if purge_window >= val_len:
                    raise ValueError("PURGE_WINDOW_EXHAUSTS_VALIDATION")
                val_idx = list(range(raw_val_start, raw_val_end - purge_window))
                purged_val = list(range(raw_val_end - purge_window, raw_val_end))
            else:
                val_idx = list(range(raw_val_start, raw_val_end))
                purged_val = []

            # 3. Final OOS Test interval: strictly [cursor : cursor + test_size]
            test_start = cursor
            test_end = cursor + test_size
            test_idx = list(range(test_start, test_end))

            # 4. Post-test Embargo: [test_end : test_end + embargo_window]
            embargoed = []
            if embargo_window > 0 and test_end < total_bars:
                emb_end = min(total_bars, test_end + embargo_window)
                embargoed = list(range(test_end, emb_end))

            # In expanding folds, if previous test completed, exclude its post-test embargo from current train if overlapping
            if previous_test_end is not None and embargo_window > 0:
                past_embargo_set = set(range(previous_test_end, min(total_bars, previous_test_end + embargo_window)))
                train_idx = [i for i in train_idx if i not in past_embargo_set]
                if len(train_idx) == 0:
                    raise ValueError("PURGE_WINDOW_EXHAUSTS_TRAIN")

            plans.append(
                FoldSplitPlan(
                    fold_id=fold_id,
                    train_indices=train_idx,
                    val_indices=val_idx,
                    test_indices=test_idx,
                    purged_train_indices=purged_train,
                    purged_val_indices=purged_val,
                    embargoed_indices=embargoed,
                )
            )

            previous_test_end = test_end
            cursor += test_size
            fold_idx += 1

        return plans

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
        plans = self.split_plans(
            total_bars,
            train_size=train_size,
            val_size=val_size,
            test_size=test_size,
            purge_window=purge_window,
            embargo_window=embargo_window,
        )
        return [
            (np.array(p.train_indices), np.array(p.val_indices), np.array(p.test_indices))
            for p in plans
        ]


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
        """Compute neighborhood statistics, plateau scores, sensitivity, and fold rank stability."""
        if not candidates:
            raise RuntimeError("No candidate evaluations available for parameter robustness selection.")

        # Compute TRAIN ranks (1-based, descending by score)
        sorted_train = sorted(
            candidates,
            key=lambda c: (scores_by_param.get(canonical_hash(c), -999.0), -len(canonical_hash(c))),
            reverse=True,
        )
        train_ranks = {canonical_hash(c): idx + 1 for idx, c in enumerate(sorted_train)}

        # Compute VALIDATION ranks if available
        val_ranks: dict[str, int] = {}
        if val_scores_by_param:
            sorted_val = sorted(
                candidates,
                key=lambda c: (val_scores_by_param.get(canonical_hash(c), -999.0), -len(canonical_hash(c))),
                reverse=True,
            )
            val_ranks = {canonical_hash(c): idx + 1 for idx, c in enumerate(sorted_val)}

        # Overall fold rank correlation between TRAIN and VALIDATION ranks
        spearman_corr = 1.0
        if len(candidates) >= 2 and val_ranks:
            t_r = [train_ranks[canonical_hash(c)] for c in candidates]
            v_r = [val_ranks[canonical_hash(c)] for c in candidates]
            try:
                res, _ = scipy.stats.spearmanr(t_r, v_r)
                spearman_corr = float(res) if not math.isnan(float(res)) else 1.0
            except Exception:
                spearman_corr = 1.0

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

            n_count = len(neighbors)
            if neighbor_scores:
                n_mean = float(np.mean(neighbor_scores))
                n_std = float(np.std(neighbor_scores))
                n_min = float(np.min(neighbor_scores))

                # Plateau membership: % of neighbors meeting performance threshold
                if train_score > 0:
                    threshold = self.policy.plateau_min_ratio * train_score
                    plateau_neighbors = sum(1 for s in neighbor_scores if s >= threshold)
                else:
                    plateau_neighbors = sum(1 for s in neighbor_scores if s >= train_score)

                plateau_fraction = float(plateau_neighbors / max(1, n_count))
                plateau_width = float(plateau_neighbors)

                # Normalized sensitivity / drop-off
                denom = abs(train_score) + 1e-6
                drop_off = max(0.0, train_score - n_mean) / denom
                sensitivity = float(drop_off + (n_std / denom))
            else:
                n_mean = train_score
                n_std = 0.0
                n_min = train_score
                plateau_neighbors = 1
                plateau_fraction = 1.0
                plateau_width = 1.0
                sensitivity = 0.0

            t_rank = train_ranks.get(pkey, 1)
            v_rank = val_ranks.get(pkey)
            rank_delta = abs(t_rank - v_rank) if v_rank is not None else None

            # Rank stability: blend normalized candidate rank displacement and fold Spearman correlation
            if v_rank is not None:
                max_rank_delta = max(1, len(candidates) - 1)
                cand_displacement_stab = max(0.0, 1.0 - (rank_delta / max_rank_delta)) if rank_delta is not None else 1.0
                norm_spearman = max(0.0, min(1.0, (spearman_corr + 1.0) / 2.0))
                rank_stability = 0.60 * cand_displacement_stab + 0.40 * norm_spearman
            else:
                rank_stability = 1.0

            # Composite aggregate robustness score
            # Preference: broad plateau + low sensitivity + neighbor min + fold rank stability + raw train score
            agg_score = (
                self.policy.raw_score_weight * max(-2.0, min(5.0, train_score))
                + self.policy.plateau_weight * (plateau_fraction * max(0.0, train_score))
                - self.policy.sensitivity_weight * sensitivity
                + self.policy.stability_weight * rank_stability
                + 0.10 * max(-2.0, min(5.0, n_min))
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
                    neighbor_min=n_min,
                    plateau_neighbor_count=plateau_neighbors,
                    neighbor_count=n_count,
                    plateau_fraction=plateau_fraction,
                    plateau_width=plateau_width,
                    plateau_score=plateau_fraction,
                    sensitivity_score=sensitivity,
                    train_rank=t_rank,
                    val_rank=v_rank,
                    rank_delta=rank_delta,
                    rank_stability=rank_stability,
                    aggregate_robustness_score=float(agg_score),
                    selected=False,
                )
            )

        # Sort deterministically by aggregate robustness score, then train score, then parameter hash
        evaluated.sort(key=lambda c: (c.aggregate_robustness_score, c.train_score, c.parameter_hash), reverse=True)
        evaluated[0].selected = True
        evaluated[0].selection_reason = (
            f"Selected by RobustnessPolicy v{self.policy.policy_version}: "
            f"aggregate_score={evaluated[0].aggregate_robustness_score:.4f}, "
            f"train_score={evaluated[0].train_score:.4f}, "
            f"plateau_fraction={evaluated[0].plateau_fraction:.2f}, "
            f"sensitivity={evaluated[0].sensitivity_score:.4f}, "
            f"rank_stability={evaluated[0].rank_stability:.4f}"
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
        """Recompute net performance across cost multipliers on actual fill evidence."""
        results: list[CostStressResult] = []
        fills = getattr(strategy_run, "fills", pd.DataFrame())
        raw_curve = getattr(strategy_run, "equity_curve", pd.DataFrame())
        if raw_curve.empty:
            return results

        base_ret = raw_curve["net_return"].fillna(0.0)
        base_metrics_obj = _compute_metrics(
            equity_curve=raw_curve,
            net_returns=base_ret,
            fills=fills,
            execution_model=ExecutionModel(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        base_metrics_dict = {
            "sharpe": float(base_metrics_obj.sharpe) if base_metrics_obj.sharpe is not None else 0.0,
            "cagr": float(base_metrics_obj.cagr) if base_metrics_obj.cagr is not None else 0.0,
            "max_drawdown": float(base_metrics_obj.max_drawdown) if base_metrics_obj.max_drawdown is not None else 0.0,
            "total_return": float(base_metrics_obj.total_return) if base_metrics_obj.total_return is not None else 0.0,
            "profit_factor": float(base_metrics_obj.profit_factor) if base_metrics_obj.profit_factor is not None else 0.0,
            "win_rate": float(base_metrics_obj.win_rate) if base_metrics_obj.win_rate is not None else 0.0,
        }

        for mult in self.policy.cost_multipliers:
            if math.isclose(mult, 1.0, rel_tol=1e-6):
                results.append(
                    CostStressResult(
                        multiplier=1.0,
                        slippage_bps_override=None,
                        liquidity_stress_factor=None,
                        metrics=base_metrics_dict,
                        cost_schedule_summary={"multiplier": 1.0, "base_keys": list(base_cost_model.keys())},
                        status=EvidenceStatus.VALID,
                    )
                )
                continue

            if fills.empty:
                results.append(
                    CostStressResult(
                        multiplier=mult,
                        slippage_bps_override=self.policy.slippage_stress_bps,
                        liquidity_stress_factor=self.policy.liquidity_stress_factor,
                        metrics=base_metrics_dict,
                        cost_schedule_summary={"multiplier": mult},
                        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                        reason="NO_FILL_RECORDS_FOR_COST_STRESS",
                    )
                )
                continue

            if "timestamp" not in fills.columns or "timestamp" not in raw_curve.columns:
                results.append(
                    CostStressResult(
                        multiplier=mult,
                        slippage_bps_override=self.policy.slippage_stress_bps,
                        liquidity_stress_factor=self.policy.liquidity_stress_factor,
                        metrics={},
                        cost_schedule_summary={"multiplier": mult},
                        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                        reason="MISSING_FILL_TIMESTAMP_EVIDENCE",
                    )
                )
                continue

            stressed_curve = raw_curve.copy()
            stressed_net_ret = stressed_curve["net_return"].fillna(0.0).copy()
            curve_ts = pd.to_datetime(stressed_curve["timestamp"], utc=True)

            base_fees = fills["fees"] if "fees" in fills.columns else (fills["cost"] if "cost" in fills.columns else pd.Series(0.0, index=fills.index))
            extra_fees = base_fees * (mult - 1.0)
            fill_notional = (fills["quantity"] * fills["price"]).abs() if {"quantity", "price"}.issubset(fills.columns) else pd.Series(0.0, index=fills.index)
            extra_slippage = fill_notional * (self.policy.slippage_stress_bps / 10000.0)
            total_fill_drag = extra_fees + extra_slippage

            fill_ts = pd.to_datetime(fills["timestamp"], utc=True)
            bar_drags = np.zeros(len(stressed_curve))
            for f_t, d in zip(fill_ts, total_fill_drag):
                matching_indices = np.where(curve_ts == f_t)[0]
                if len(matching_indices) > 0:
                    bar_drags[matching_indices[0]] += d
                else:
                    prior_indices = np.where(curve_ts <= f_t)[0]
                    if len(prior_indices) > 0:
                        bar_drags[prior_indices[-1]] += d
                    else:
                        bar_drags[0] += d
            equity_vals = starting_capital * (1.0 + stressed_net_ret).cumprod()
            ret_drags = bar_drags / np.maximum(equity_vals.values, starting_capital * 0.1)
            stressed_net_ret = stressed_net_ret - ret_drags

            stressed_curve["net_return"] = stressed_net_ret
            stressed_curve["equity"] = starting_capital * (1.0 + stressed_net_ret).cumprod()
            stressed_curve["drawdown"] = stressed_curve["equity"] / stressed_curve["equity"].cummax() - 1.0

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
                    slippage_bps_override=self.policy.slippage_stress_bps,
                    metrics=metrics_dict,
                    cost_schedule_summary={
                        "multiplier": mult,
                        "slippage_bps": self.policy.slippage_stress_bps,
                        "base_keys": list(base_cost_model.keys()),
                    },
                    status=EvidenceStatus.VALID,
                )
            )

        return results

    def evaluate_execution_stress(
        self,
        strategy_run: Any,
        timeframe: str,
        starting_capital: float,
    ) -> list[ExecutionStressResult]:
        """Evaluate overnight gap, stop slippage, delay, missed fills, and reduced liquidity on actual evidence."""
        results: list[ExecutionStressResult] = []
        raw_curve = getattr(strategy_run, "equity_curve", pd.DataFrame())
        fills = getattr(strategy_run, "fills", pd.DataFrame())

        if raw_curve.empty:
            return results

        # 1. Overnight Gap Stress
        if "timestamp" in raw_curve.columns and "position" in raw_curve.columns:
            ts_series = pd.to_datetime(raw_curve["timestamp"], utc=True)
            dates = ts_series.dt.date
            date_diff = dates.ne(dates.shift())
            overnight_mask = date_diff & (raw_curve["position"].shift(1).fillna(0.0).abs() > 1e-6)
            overnight_count = int(overnight_mask.sum())

            gap_curve = raw_curve.copy()
            gap_net_ret = gap_curve["net_return"].fillna(0.0).copy()

            if overnight_count > 0:
                gap_loss_fraction = (self.policy.overnight_gap_bps / 10000.0)
                held_positions = gap_curve["position"].shift(1).fillna(0.0).abs()
                gap_drag = overnight_mask.astype(float) * held_positions * gap_loss_fraction
                gap_net_ret = gap_net_ret - gap_drag

            gap_curve["net_return"] = gap_net_ret
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
                    perturbation_params={"gap_bps": self.policy.overnight_gap_bps, "overnight_exposure_bars": overnight_count},
                    metrics={
                        "sharpe": float(gap_mets.sharpe) if gap_mets.sharpe is not None else 0.0,
                        "cagr": float(gap_mets.cagr) if gap_mets.cagr is not None else 0.0,
                        "max_drawdown": float(gap_mets.max_drawdown) if gap_mets.max_drawdown is not None else 0.0,
                        "total_return": float(gap_mets.total_return) if gap_mets.total_return is not None else 0.0,
                    },
                    seed=None,
                    status=EvidenceStatus.VALID,
                )
            )
        else:
            results.append(
                ExecutionStressResult(
                    scenario_name="overnight_gap_stress",
                    perturbation_params={"gap_bps": self.policy.overnight_gap_bps},
                    metrics={},
                    seed=None,
                    status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    reason="MISSING_TIMESTAMP_OR_POSITION_EVIDENCE",
                )
            )

        # 2. Stop Slippage Stress on identifiable stop orders
        if fills.empty or not {"quantity", "price"}.issubset(fills.columns):
            results.append(
                ExecutionStressResult(
                    scenario_name="stop_slippage_stress",
                    perturbation_params={"stop_slippage_bps": self.policy.stop_slippage_bps},
                    metrics={},
                    seed=None,
                    status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    reason="NO_FILL_RECORDS_FOR_STOP_SLIPPAGE",
                )
            )
        else:
            is_stop_mask = pd.Series(False, index=fills.index)
            if "order_type" in fills.columns:
                is_stop_mask |= fills["order_type"].astype(str).str.upper().isin(["STOP", "STOP_LOSS", "TRAILING_STOP", "SL"])
            if "order_tag" in fills.columns:
                is_stop_mask |= fills["order_tag"].astype(str).str.upper().str.contains("STOP|SL")
            if "reason" in fills.columns:
                is_stop_mask |= fills["reason"].astype(str).str.upper().str.contains("STOP|SL")
            if "is_stop" in fills.columns:
                is_stop_mask |= fills["is_stop"].astype(bool)

            if not is_stop_mask.any():
                results.append(
                    ExecutionStressResult(
                        scenario_name="stop_slippage_stress",
                        perturbation_params={"stop_slippage_bps": self.policy.stop_slippage_bps},
                        metrics={},
                        seed=None,
                        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                        reason="NO_STOP_ORDER_EVIDENCE",
                    )
                )
            elif "timestamp" not in fills.columns or "timestamp" not in raw_curve.columns:
                results.append(
                    ExecutionStressResult(
                        scenario_name="stop_slippage_stress",
                        perturbation_params={"stop_slippage_bps": self.policy.stop_slippage_bps},
                        metrics={},
                        seed=None,
                        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                        reason="MISSING_FILL_TIMESTAMP_EVIDENCE",
                    )
                )
            else:
                stop_fills = fills[is_stop_mask].copy()
                slip_notional = (stop_fills["quantity"] * stop_fills["price"]).abs()
                stop_slip_loss = slip_notional * (self.policy.stop_slippage_bps / 10000.0)

                slip_curve = raw_curve.copy()
                slip_net_ret = slip_curve["net_return"].fillna(0.0).copy()
                curve_ts = pd.to_datetime(slip_curve["timestamp"], utc=True)
                fill_ts = pd.to_datetime(stop_fills["timestamp"], utc=True)

                bar_drags = np.zeros(len(slip_curve))
                for f_t, d in zip(fill_ts, stop_slip_loss):
                    matching_indices = np.where(curve_ts == f_t)[0]
                    if len(matching_indices) > 0:
                        bar_drags[matching_indices[0]] += d
                    else:
                        prior_indices = np.where(curve_ts <= f_t)[0]
                        if len(prior_indices) > 0:
                            bar_drags[prior_indices[-1]] += d
                        else:
                            bar_drags[0] += d

                equity_vals = starting_capital * (1.0 + slip_net_ret).cumprod()
                ret_drags = bar_drags / np.maximum(equity_vals.values, starting_capital * 0.1)
                slip_net_ret = slip_net_ret - ret_drags

                slip_curve["net_return"] = slip_net_ret
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
                        perturbation_params={"stop_slippage_bps": self.policy.stop_slippage_bps, "exit_fills_count": len(stop_fills)},
                        metrics={
                            "sharpe": float(slip_mets.sharpe) if slip_mets.sharpe is not None else 0.0,
                            "cagr": float(slip_mets.cagr) if slip_mets.cagr is not None else 0.0,
                            "max_drawdown": float(slip_mets.max_drawdown) if slip_mets.max_drawdown is not None else 0.0,
                            "total_return": float(slip_mets.total_return) if slip_mets.total_return is not None else 0.0,
                        },
                        seed=None,
                        status=EvidenceStatus.VALID,
                    )
                )

        # 3. Execution Delay Stress
        delayed_run = getattr(strategy_run, "delayed_run", None)
        if delayed_run is not None and hasattr(delayed_run, "equity_curve") and not delayed_run.equity_curve.empty:
            del_curve = delayed_run.equity_curve
            del_ret = del_curve["net_return"].fillna(0.0)
            del_fills = getattr(delayed_run, "fills", fills)
            delay_mets = _compute_metrics(
                equity_curve=del_curve,
                net_returns=del_ret,
                fills=del_fills,
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
                    status=EvidenceStatus.VALID,
                )
            )
        else:
            results.append(
                ExecutionStressResult(
                    scenario_name="execution_delay",
                    perturbation_params={"delay_bars": self.policy.execution_delay_bars},
                    metrics={},
                    seed=None,
                    status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    reason="NO_DELAYED_FILL_REPLAY_EVIDENCE",
                )
            )

        # 4. Missed Fills Stress
        if fills.empty:
            results.append(
                ExecutionStressResult(
                    scenario_name="missed_fills",
                    perturbation_params={"missed_fill_rate": self.policy.missed_fill_rate},
                    metrics={},
                    seed=self.policy.monte_carlo_seed,
                    status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    reason="NO_FILL_RECORDS_FOR_MISSED_FILLS",
                )
            )
        elif "timestamp" not in fills.columns or "timestamp" not in raw_curve.columns:
            results.append(
                ExecutionStressResult(
                    scenario_name="missed_fills",
                    perturbation_params={"missed_fill_rate": self.policy.missed_fill_rate},
                    metrics={},
                    seed=self.policy.monte_carlo_seed,
                    status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    reason="MISSING_TIMESTAMP_EVIDENCE_FOR_MISSED_FILLS",
                )
            )
        else:
            rng = np.random.default_rng(self.policy.monte_carlo_seed)
            n_fills = len(fills)
            omission_mask = rng.random(n_fills) < self.policy.missed_fill_rate
            surviving_fills = fills[~omission_mask].copy()

            missed_curve = raw_curve.copy()
            missed_ret = missed_curve["net_return"].fillna(0.0).copy()
            omitted_ts = set(pd.to_datetime(fills.loc[omission_mask, "timestamp"], utc=True))
            curve_ts = pd.to_datetime(missed_curve["timestamp"], utc=True)
            bar_mask = curve_ts.isin(omitted_ts)
            missed_ret.loc[bar_mask] = 0.0

            missed_curve["net_return"] = missed_ret
            missed_curve["equity"] = starting_capital * (1.0 + missed_ret).cumprod()
            missed_curve["drawdown"] = missed_curve["equity"] / missed_curve["equity"].cummax() - 1.0
            missed_mets = _compute_metrics(
                equity_curve=missed_curve,
                net_returns=missed_ret,
                fills=surviving_fills,
                execution_model=ExecutionModel(),
                timeframe=timeframe,
                starting_capital=starting_capital,
            )
            results.append(
                ExecutionStressResult(
                    scenario_name="missed_fills",
                    perturbation_params={"missed_fill_rate": self.policy.missed_fill_rate, "omitted_fills_count": int(omission_mask.sum())},
                    metrics={
                        "sharpe": float(missed_mets.sharpe) if missed_mets.sharpe is not None else 0.0,
                        "cagr": float(missed_mets.cagr) if missed_mets.cagr is not None else 0.0,
                        "max_drawdown": float(missed_mets.max_drawdown) if missed_mets.max_drawdown is not None else 0.0,
                        "total_return": float(missed_mets.total_return) if missed_mets.total_return is not None else 0.0,
                    },
                    seed=self.policy.monte_carlo_seed,
                    status=EvidenceStatus.VALID,
                )
            )

        # 5. Reduced Liquidity Stress
        has_volume_evidence = (
            not fills.empty
            and ("market_volume" in fills.columns or "bar_volume" in fills.columns or "adv" in fills.columns or "participation_rate" in fills.columns)
            and {"quantity", "price"}.issubset(fills.columns)
            and "timestamp" in fills.columns
            and "timestamp" in raw_curve.columns
        )
        if not has_volume_evidence:
            results.append(
                ExecutionStressResult(
                    scenario_name="reduced_liquidity",
                    perturbation_params={"liquidity_factor": self.policy.liquidity_stress_factor},
                    metrics={},
                    seed=None,
                    status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    reason="NO_MARKET_VOLUME_EVIDENCE",
                )
            )
        elif "participation_rate" in fills.columns:
            p_rate = pd.to_numeric(fills["participation_rate"], errors="coerce")
            qty = pd.to_numeric(fills["quantity"], errors="coerce").abs()
            px = pd.to_numeric(fills["price"], errors="coerce").abs()
            if p_rate.isna().any() or (p_rate < 0.0).any() or qty.isna().any() or px.isna().any():
                results.append(
                    ExecutionStressResult(
                        scenario_name="reduced_liquidity",
                        perturbation_params={"liquidity_factor": self.policy.liquidity_stress_factor},
                        metrics={},
                        seed=None,
                        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                        reason="INVALID_MARKET_VOLUME_EVIDENCE",
                    )
                )
            else:
                participation_rate = p_rate.clip(upper=1.0)
                fill_notional = qty * px
                impact_bps = participation_rate * (self.policy.liquidity_stress_factor - 1.0) * 100.0
                liq_impact_cost = fill_notional * (impact_bps / 10000.0)

                liq_curve = raw_curve.copy()
                liq_net_ret = liq_curve["net_return"].fillna(0.0).copy()
                curve_ts = pd.to_datetime(liq_curve["timestamp"], utc=True)
                fill_ts = pd.to_datetime(fills["timestamp"], utc=True)

                bar_drags = np.zeros(len(liq_curve))
                for f_t, d in zip(fill_ts, liq_impact_cost):
                    matching_indices = np.where(curve_ts == f_t)[0]
                    if len(matching_indices) > 0:
                        bar_drags[matching_indices[0]] += d
                    else:
                        prior_indices = np.where(curve_ts <= f_t)[0]
                        if len(prior_indices) > 0:
                            bar_drags[prior_indices[-1]] += d
                        else:
                            bar_drags[0] += d

                equity_vals = starting_capital * (1.0 + liq_net_ret).cumprod()
                ret_drags = bar_drags / np.maximum(equity_vals.values, starting_capital * 0.1)
                liq_net_ret = liq_net_ret - ret_drags

                liq_curve["net_return"] = liq_net_ret
                liq_curve["equity"] = starting_capital * (1.0 + liq_net_ret).cumprod()
                liq_curve["drawdown"] = liq_curve["equity"] / liq_curve["equity"].cummax() - 1.0
                liq_mets = _compute_metrics(
                    equity_curve=liq_curve,
                    net_returns=liq_net_ret,
                    fills=fills,
                    execution_model=ExecutionModel(),
                    timeframe=timeframe,
                    starting_capital=starting_capital,
                )
                results.append(
                    ExecutionStressResult(
                        scenario_name="reduced_liquidity",
                        perturbation_params={"liquidity_factor": self.policy.liquidity_stress_factor, "participation_source": "participation_rate", "traded_notional": float(fill_notional.sum())},
                        metrics={
                            "sharpe": float(liq_mets.sharpe) if liq_mets.sharpe is not None else 0.0,
                            "cagr": float(liq_mets.cagr) if liq_mets.cagr is not None else 0.0,
                            "max_drawdown": float(liq_mets.max_drawdown) if liq_mets.max_drawdown is not None else 0.0,
                            "total_return": float(liq_mets.total_return) if liq_mets.total_return is not None else 0.0,
                        },
                        seed=None,
                        status=EvidenceStatus.VALID,
                    )
                )
        else:
            vol_col = "market_volume" if "market_volume" in fills.columns else ("bar_volume" if "bar_volume" in fills.columns else "adv")
            volumes = pd.to_numeric(fills[vol_col], errors="coerce")
            qty = pd.to_numeric(fills["quantity"], errors="coerce").abs()
            px = pd.to_numeric(fills["price"], errors="coerce").abs()
            if volumes.isna().any() or (volumes <= 0.0).any() or qty.isna().any() or px.isna().any():
                results.append(
                    ExecutionStressResult(
                        scenario_name="reduced_liquidity",
                        perturbation_params={"liquidity_factor": self.policy.liquidity_stress_factor},
                        metrics={},
                        seed=None,
                        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                        reason="INVALID_MARKET_VOLUME_EVIDENCE",
                    )
                )
            else:
                participation_rate = (qty / volumes).clip(upper=1.0)
                fill_notional = qty * px
                impact_bps = participation_rate * (self.policy.liquidity_stress_factor - 1.0) * 100.0
                liq_impact_cost = fill_notional * (impact_bps / 10000.0)

                liq_curve = raw_curve.copy()
                liq_net_ret = liq_curve["net_return"].fillna(0.0).copy()
                curve_ts = pd.to_datetime(liq_curve["timestamp"], utc=True)
                fill_ts = pd.to_datetime(fills["timestamp"], utc=True)

                bar_drags = np.zeros(len(liq_curve))
                for f_t, d in zip(fill_ts, liq_impact_cost):
                    matching_indices = np.where(curve_ts == f_t)[0]
                    if len(matching_indices) > 0:
                        bar_drags[matching_indices[0]] += d
                    else:
                        prior_indices = np.where(curve_ts <= f_t)[0]
                        if len(prior_indices) > 0:
                            bar_drags[prior_indices[-1]] += d
                        else:
                            bar_drags[0] += d

                equity_vals = starting_capital * (1.0 + liq_net_ret).cumprod()
                ret_drags = bar_drags / np.maximum(equity_vals.values, starting_capital * 0.1)
                liq_net_ret = liq_net_ret - ret_drags

                liq_curve["net_return"] = liq_net_ret
                liq_curve["equity"] = starting_capital * (1.0 + liq_net_ret).cumprod()
                liq_curve["drawdown"] = liq_curve["equity"] / liq_curve["equity"].cummax() - 1.0
                liq_mets = _compute_metrics(
                    equity_curve=liq_curve,
                    net_returns=liq_net_ret,
                    fills=fills,
                    execution_model=ExecutionModel(),
                    timeframe=timeframe,
                    starting_capital=starting_capital,
                )
                results.append(
                    ExecutionStressResult(
                        scenario_name="reduced_liquidity",
                        perturbation_params={"liquidity_factor": self.policy.liquidity_stress_factor, "traded_notional": float(fill_notional.sum())},
                        metrics={
                            "sharpe": float(liq_mets.sharpe) if liq_mets.sharpe is not None else 0.0,
                            "cagr": float(liq_mets.cagr) if liq_mets.cagr is not None else 0.0,
                            "max_drawdown": float(liq_mets.max_drawdown) if liq_mets.max_drawdown is not None else 0.0,
                            "total_return": float(liq_mets.total_return) if liq_mets.total_return is not None else 0.0,
                        },
                        seed=None,
                        status=EvidenceStatus.VALID,
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
        self.splitter = NestedWalkForwardSplitter()
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

        # Authoritative split plans from NestedWalkForwardSplitter
        plans = self.splitter.split_plans(
            len(dates),
            train_size=train_size,
            val_size=val_size,
            test_size=test_size,
            purge_window=purge_w,
            embargo_window=embargo_w,
        )

        if not plans:
            raise ValueError(
                f"Dataset length ({len(dates)}) insufficient for nested walk-forward "
                f"with train_size={train_size}, val_size={val_size}, test_size={test_size}."
            )

        nested_folds: list[NestedFoldEvidence] = []
        all_evaluated_candidates: list[ParameterRobustnessCandidate] = []
        final_test_returns_list: list[pd.Series] = []
        final_test_curves_list: list[pd.DataFrame] = []
        final_test_fills_list: list[pd.DataFrame] = []

        for plan in plans:
            fold_id = plan.fold_id

            train_dates = dates[plan.train_indices]
            val_dates = dates[plan.val_indices]
            test_dates = dates[plan.test_indices]

            purged_train_dates = dates[plan.purged_train_indices]
            purged_val_dates = dates[plan.purged_val_indices]
            embargoed_dates = dates[plan.embargoed_indices]

            train_source = self._slice(source, train_dates[0], train_dates[-1])
            val_source = self._slice(source, val_dates[0], val_dates[-1])
            test_source = self._slice(source, test_dates[0], test_dates[-1])

            # Selection on TRAIN + VALIDATION only
            selected, winning_trial_id, train_mets, val_mets, fold_candidates = self._select_nested(
                spec,
                metadata.scope,
                train_source,
                val_source,
                candidates,
                metadata.parameter_grid,
                starting_capital,
                fold_id=fold_id,
            )
            all_evaluated_candidates.extend(fold_candidates)

            # FINAL OOS TEST is evaluated ONLY ONCE after candidate selection is frozen!
            final_replay = self._run(spec, metadata.scope, test_source, selected, starting_capital)
            final_run = getattr(final_replay, "run", final_replay)
            final_curve = getattr(final_run, "equity_curve", pd.DataFrame())
            final_ret = final_curve["net_return"].fillna(0.0) if not final_curve.empty else pd.Series()
            final_fills = getattr(final_run, "fills", pd.DataFrame())

            final_test_returns_list.append(final_ret)
            if not final_curve.empty:
                final_test_curves_list.append(final_curve)
            if not final_fills.empty:
                final_test_fills_list.append(final_fills)

            final_metrics_obj = _compute_metrics(
                equity_curve=final_curve,
                net_returns=final_ret,
                fills=final_fills,
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
                "purged_train_range": [purged_train_dates[0].isoformat(), purged_train_dates[-1].isoformat()] if len(purged_train_dates) else [],
                "purged_val_range": [purged_val_dates[0].isoformat(), purged_val_dates[-1].isoformat()] if len(purged_val_dates) else [],
                "embargoed_ranges": [embargoed_dates[0].isoformat(), embargoed_dates[-1].isoformat()] if len(embargoed_dates) else [],
                "dataset_snapshot_ids": dict(source.dataset_snapshot_ids),
                "contributing_dataset_ids": sorted(list(source.contributing_dataset_ids)),
                "dataset_content_hashes": dict(source.dataset_content_hashes),
                "frame_certification_id": source.frame_certification_id,
                "train_hash": train_source.data_hash,
                "val_hash": val_source.data_hash,
                "test_hash": test_source.data_hash,
                "selected_parameters": selected,
                "selected_trial_id": winning_trial_id,
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
                    purged_train_range=[purged_train_dates[0].isoformat(), purged_train_dates[-1].isoformat()] if len(purged_train_dates) else [],
                    purged_val_range=[purged_val_dates[0].isoformat(), purged_val_dates[-1].isoformat()] if len(purged_val_dates) else [],
                    embargoed_ranges=[embargoed_dates[0].isoformat(), embargoed_dates[-1].isoformat()] if len(embargoed_dates) else [],
                    dataset_snapshot_ids=dict(source.dataset_snapshot_ids),
                    contributing_dataset_ids=sorted(list(source.contributing_dataset_ids)),
                    dataset_content_hashes=dict(source.dataset_content_hashes),
                    train_data_hash=train_source.data_hash,
                    val_data_hash=val_source.data_hash,
                    test_data_hash=test_source.data_hash,
                    frame_certification_id=source.frame_certification_id,
                    selected_parameters=selected,
                    selected_parameter_hash=canonical_hash(selected),
                    selected_trial_id=winning_trial_id,
                    train_metrics=train_mets,
                    val_metrics=val_mets,
                    final_oos_metrics=final_mets,
                    evidence_hash=canonical_hash(fold_evidence_payload),
                )
            )

        # Concatenate out-of-sample returns across all folds
        combined_final_returns = pd.concat(final_test_returns_list, ignore_index=True) if final_test_returns_list else pd.Series(dtype=float)
        combined_final_curve = pd.concat(final_test_curves_list, ignore_index=True) if final_test_curves_list else pd.DataFrame()
        combined_final_fills = pd.concat(final_test_fills_list, ignore_index=True) if final_test_fills_list else pd.DataFrame()

        # Build synthetic OOS strategy run for OOS stress evaluation
        class _OOSStrategyRun:
            def __init__(self, curve: pd.DataFrame, fills: pd.DataFrame) -> None:
                self.equity_curve = curve
                self.fills = fills

        oos_run = _OOSStrategyRun(combined_final_curve, combined_final_fills)

        # 1. Probabilistic Sharpe Ratio (PSR)
        psr_result = compute_psr(
            combined_final_returns,
            benchmark_sharpe=self.policy.psr_benchmark_sharpe,
            annualization_factor=self.policy.annualization_factor,
            minimum_observations=self.policy.minimum_observations,
        )

        # 2. Deflated Sharpe Ratio (DSR) via Authoritative Storage Resolver
        if spec.experiment_family_id and self.db is not None:
            dsr_result = resolve_authoritative_dsr(
                db=self.db,
                returns=combined_final_returns,
                experiment_family_id=spec.experiment_family_id,
                annualization_factor=self.policy.annualization_factor,
                minimum_observations=self.policy.minimum_observations,
                trial_policy_version=self.policy.policy_version,
                trial_policy_hash=self.policy.policy_hash,
            )
        elif spec.experiment_family_id and self.db is None:
            dsr_result = DSRResult(
                effective_trials=0,
                sharpe_count=0,
                trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
                experiment_family_id=spec.experiment_family_id,
                trial_ids=[],
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason="UNVERIFIED_DATABASE_PROVENANCE",
            )
        else:
            dsr_result = DSRResult(
                effective_trials=0,
                sharpe_count=0,
                trial_count_source=TrialCountSource.MANUAL_STATISTICAL_INPUT,
                experiment_family_id=None,
                trial_ids=[],
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason="MISSING_AUTHORITATIVE_TRIAL_FAMILY",
            )

        # 3. Deterministic Seeded Bootstrap
        bootstrap_cis = compute_bootstrap_confidence_intervals(
            combined_final_returns,
            fills=combined_final_fills,
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
            fills=combined_final_fills,
            n_simulations=self.policy.monte_carlo_simulations,
            drawdown_threshold=self.policy.monte_carlo_drawdown_threshold,
            ruin_threshold=self.policy.monte_carlo_ruin_threshold,
            seed=self.policy.monte_carlo_seed,
            minimum_observations=self.policy.minimum_observations,
            annualization_factor=self.policy.annualization_factor,
            starting_capital=starting_capital,
        )

        # 5. Cost Stress Testing evaluated on OOS evidence
        cost_stress_res = self.stress_engine.evaluate_cost_stress(
            strategy_run=oos_run,
            base_cost_model=spec.cost_model,
            timeframe=spec.timeframe,
            starting_capital=starting_capital,
        )

        # 6. Swing Execution Stress Testing evaluated on OOS evidence
        exec_stress_res = self.stress_engine.evaluate_execution_stress(
            strategy_run=oos_run,
            timeframe=spec.timeframe,
            starting_capital=starting_capital,
        )

        # Overall evidence status fails closed if any critical component is non-valid
        boot_valid = all(b.status == EvidenceStatus.VALID for b in bootstrap_cis.values())
        cost_valid = len(cost_stress_res) > 0 and all(c.status == EvidenceStatus.VALID for c in cost_stress_res)
        exec_executed = len(exec_stress_res) > 0 and all(e.status != EvidenceStatus.INVALID_INPUT for e in exec_stress_res)
        overall_status = EvidenceStatus.VALID
        if (
            psr_result.status != EvidenceStatus.VALID
            or dsr_result.status != EvidenceStatus.VALID
            or not boot_valid
            or monte_carlo_res.status != EvidenceStatus.VALID
            or not cost_valid
            or not exec_executed
            or not nested_folds
        ):
            overall_status = EvidenceStatus.INSUFFICIENT_EVIDENCE

        selected_winner = nested_folds[-1].selected_parameters
        winner_trial_id = nested_folds[-1].selected_trial_id

        # Compute deterministic evidence bundle identity (excluding timestamps)
        bundle_identity_payload = {
            "run_id": parent_run_id,
            "strategy_name": spec.strategy_name,
            "strategy_version": metadata.version,
            "data_hash": source.data_hash,
            "policy_hash": self.policy.policy_hash,
            "folds_count": len(nested_folds),
            "selected_parameters": selected_winner,
            "selected_trial_id": winner_trial_id,
            "experiment_family_id": spec.experiment_family_id,
        }
        robustness_id = canonical_hash(bundle_identity_payload)

        evidence_hash_payload = {
            "robustness_id": robustness_id,
            "folds": [f.evidence_hash for f in nested_folds],
            "fold_dataset_lineage": [
                {
                    "fold_id": f.fold_id,
                    "dataset_snapshot_ids": f.dataset_snapshot_ids,
                    "contributing_dataset_ids": f.contributing_dataset_ids,
                    "dataset_content_hashes": f.dataset_content_hashes,
                    "frame_certification_id": f.frame_certification_id,
                }
                for f in nested_folds
            ],
            "parameter_robustness": [c.model_dump(mode="json") for c in all_evaluated_candidates],
            "psr": psr_result.model_dump(mode="json"),
            "dsr": dsr_result.model_dump(mode="json"),
            "bootstrap": {k: v.model_dump(mode="json") for k, v in bootstrap_cis.items()},
            "monte_carlo": monte_carlo_res.model_dump(mode="json"),
            "cost_stress": [c.model_dump(mode="json") for c in cost_stress_res],
            "exec_stress": [e.model_dump(mode="json") for e in exec_stress_res],
            "policy_hash": self.policy.policy_hash,
            "data_hash": source.data_hash,
            "frame_certification_id": source.frame_certification_id,
        }
        evidence_hash = canonical_hash(evidence_hash_payload)

        bundle = RobustnessBundle(
            robustness_id=robustness_id,
            run_id=parent_run_id,
            experiment_family_id=spec.experiment_family_id,
            strategy_name=spec.strategy_name,
            strategy_version=metadata.version,
            selected_trial_id=winner_trial_id,
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
    ) -> tuple[dict[str, Any], str | None, dict[str, float], dict[str, float], list[ParameterRobustnessCandidate]]:
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
        winning_trial_id = candidate_trial_ids.get(win_key)
        if spec.experiment_family_id and winning_trial_id:
            self.db.mark_trial_selected(winning_trial_id, True)

        return (
            dict(winning_cand.parameters),
            winning_trial_id,
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
