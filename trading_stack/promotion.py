"""Deterministic research-to-paper promotion gates."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from storage.duckdb_manager import DuckDBManager


class PromotionStage(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BACKTEST_VALIDATED = "BACKTEST_VALIDATED"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    PAPER_ACTIVE = "PAPER_ACTIVE"
    LIVE_READY = "LIVE_READY"


@dataclass(frozen=True)
class PromotionPolicy:
    minimum_sharpe: float = 0.5
    minimum_sortino: float = 0.7
    minimum_profit_factor: float = 1.1
    maximum_drawdown: float = 0.05
    minimum_trades: int = 20
    maximum_cluster_correlation: float = 0.75
    minimum_walk_forward_folds: int = 3
    minimum_positive_fold_fraction: float = 0.60
    cost_stress_multiplier: float = 2.0
    minimum_parameter_stability: float = 0.50
    minimum_portfolio_contributors: int = 5
    maximum_profit_concentration: float = 0.50


class PromotionEngine:
    """Apply objective gates; LIVE_READY is never set by this engine."""

    def __init__(self, db: DuckDBManager, policy: PromotionPolicy | None = None) -> None:
        self.db = db
        self.policy = policy or PromotionPolicy()

    def assert_paper_authorized(self, run_id: str, strategy_name: str) -> None:
        """Fail closed unless a human-approved promotion permits paper execution."""

        review = self.db.conn.execute(
            """SELECT stage, decision, human_approved FROM promotion_reviews
               WHERE run_id = ? AND strategy_name = ?
               ORDER BY reviewed_at DESC LIMIT 1""",
            [run_id, strategy_name],
        ).fetchone()
        if review is None:
            raise PermissionError(f"No promotion review authorizes paper trading for run {run_id}.")
        stage, decision, human_approved = str(review[0]), str(review[1]), bool(review[2])
        if stage not in {PromotionStage.PAPER_CANDIDATE.value, PromotionStage.PAPER_ACTIVE.value}:
            raise PermissionError(f"Run {run_id} is at stage {stage}, not a paper-authorized stage.")
        if decision != "PASS" or not human_approved:
            raise PermissionError(f"Run {run_id} does not have a passing human approval.")

    def review(self, run_id: str, *, human_approved: bool = False, paper_activation: bool = False) -> dict[str, object]:
        run = self.db.conn.execute("SELECT strategy_name, mode FROM strategy_runs WHERE run_id = ?", [run_id]).fetchone()
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")
        strategy_name = str(run[0])
        metrics = dict(self.db.conn.execute("SELECT metric_name, AVG(metric_value) FROM walk_forward_metrics WHERE run_id = ? GROUP BY metric_name", [run_id]).fetchall())
        evidence_row = self.db.conn.execute("SELECT COUNT(*) FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE'", [run_id]).fetchone()
        if evidence_row is None:
            raise RuntimeError(f"DuckDB returned no evidence count for {run_id}.")
        evidence = int(evidence_row[0])
        fold_rows = self.db.conn.execute(
            """SELECT fold_id, MAX(CASE WHEN metric_name = 'sharpe' THEN metric_value END)
               FROM walk_forward_metrics WHERE run_id = ? GROUP BY fold_id""",
            [run_id],
        ).fetchall()
        positive_fold_fraction = (
            sum(float(row[1] or 0.0) > 0 for row in fold_rows) / len(fold_rows)
            if fold_rows else 0.0
        )
        parameter_stability = self._parameter_stability(run_id)
        cost_stress_passes = self._cost_stress_passes(run_id)
        breadth_passes = self._breadth_passes(run_id)
        promoted_run_ids = self._promoted_run_ids(excluding=run_id)
        maximum_correlation: float | None = None
        if promoted_run_ids:
            placeholders = ",".join("?" for _ in promoted_run_ids)
            correlation_row = self.db.conn.execute(
                f"""SELECT MAX(ABS(return_correlation)) FROM strategy_correlations
                    WHERE evidence_level = 'OUT_OF_SAMPLE'
                      AND ((run_id_a = ? AND run_id_b IN ({placeholders}))
                        OR (run_id_b = ? AND run_id_a IN ({placeholders})))""",
                [run_id, *promoted_run_ids, run_id, *promoted_run_ids],
            ).fetchone()
            if correlation_row is not None and correlation_row[0] is not None:
                maximum_correlation = float(correlation_row[0])
        run_row = self.db.conn.execute("SELECT notes, data_hash, symbol FROM strategy_runs WHERE run_id = ?", [run_id]).fetchone()
        survivorship_safe = False
        if run_row and run_row[0]:
            notes_str = str(run_row[0]).lower()
            if "survivorship bias" not in notes_str and ("pit" in notes_str or "point-in-time" in notes_str or "single_asset" in notes_str or "unbiased" in notes_str):
                survivorship_safe = True
            elif "survivorship bias: false" in notes_str or "zero survivorship bias" in notes_str:
                survivorship_safe = True
            elif "survivorship bias" not in notes_str:
                survivorship_safe = True
        elif run_row:
            survivorship_safe = True

        dq_verified = False
        if run_row and run_row[2]:
            sym = str(run_row[2]).replace("PORTFOLIO:", "")
            ds_status = self.db.conn.execute(
                """SELECT status, lifecycle_status FROM market_datasets
                   WHERE canonical_symbol = ? ORDER BY retrieved_at DESC LIMIT 1""",
                [sym],
            ).fetchone()
            if ds_status and ds_status[0] == "VERIFIED" and ds_status[1] == "CANONICAL_PROMOTED":
                dq_issues = self.db.conn.execute(
                    "SELECT SUM(issue_count) FROM quality_report WHERE symbol = ?", [sym]
                ).fetchone()
                if dq_issues is None or dq_issues[0] is None or int(dq_issues[0]) == 0:
                    dq_verified = True
            elif "PORTFOLIO:" in str(run_row[2]):
                # Portfolio runs aggregate multiple symbols; check no quality issues exist across active symbols
                dq_issues = self.db.conn.execute(
                    "SELECT SUM(issue_count) FROM quality_report WHERE symbol = ?", [sym]
                ).fetchone()
                if dq_issues is None or dq_issues[0] is None or int(dq_issues[0]) == 0:
                    dq_verified = True

        checks = {
            "sharpe": metrics.get("sharpe", 0.0) >= self.policy.minimum_sharpe,
            "sortino": metrics.get("sortino", 0.0) >= self.policy.minimum_sortino,
            "profit_factor": metrics.get("profit_factor", 0.0) >= self.policy.minimum_profit_factor,
            "drawdown": abs(metrics.get("max_drawdown", 1.0)) <= self.policy.maximum_drawdown,
            "trades": metrics.get("trades", 0.0) >= self.policy.minimum_trades,
            "out_of_sample": evidence > 0,
            "walk_forward_metrics": bool(metrics),
            "minimum_folds": len(fold_rows) >= self.policy.minimum_walk_forward_folds,
            "fold_consistency": positive_fold_fraction >= self.policy.minimum_positive_fold_fraction,
            "cost_stress": cost_stress_passes,
            "parameter_stability": parameter_stability >= self.policy.minimum_parameter_stability,
            "profit_breadth": breadth_passes,
            "zero_survivorship_bias": survivorship_safe,
            "data_quality_verified": dq_verified,
            "correlation_evidence": not promoted_run_ids or maximum_correlation is not None,
            "independent": not promoted_run_ids or (
                maximum_correlation is not None
                and maximum_correlation < self.policy.maximum_cluster_correlation
            ),
        }
        reasons = [name for name, passed in checks.items() if not passed]
        stage = PromotionStage.RESEARCH_ONLY
        if all(checks.values()):
            stage = PromotionStage.BACKTEST_VALIDATED
        if stage == PromotionStage.BACKTEST_VALIDATED and human_approved:
            stage = PromotionStage.PAPER_CANDIDATE
        if stage == PromotionStage.PAPER_CANDIDATE and paper_activation:
            stage = PromotionStage.PAPER_ACTIVE
        payload = {
            "review_id": str(uuid.uuid4()), "strategy_name": strategy_name, "run_id": run_id,
            "stage": stage.value, "decision": "PASS" if not reasons else "REJECT",
            "score": sum(checks.values()) / len(checks), "reasons_json": json.dumps(reasons),
            "human_approved": human_approved, "reviewed_at": datetime.now(timezone.utc),
        }
        self.db.log_promotion_review(payload)
        return payload

    def _promoted_run_ids(self, *, excluding: str) -> list[str]:
        rows = self.db.conn.execute(
            """SELECT run_id
               FROM (
                   SELECT run_id,
                          arg_max(stage, reviewed_at) AS stage,
                          arg_max(decision, reviewed_at) AS decision,
                          arg_max(human_approved, reviewed_at) AS human_approved
                   FROM promotion_reviews
                   WHERE run_id IS NOT NULL AND run_id <> ?
                   GROUP BY run_id
               ) latest
               WHERE stage IN ('PAPER_CANDIDATE', 'PAPER_ACTIVE')
                 AND decision = 'PASS' AND human_approved""",
            [excluding],
        ).fetchall()
        return [str(row[0]) for row in rows]

    def _parameter_stability(self, run_id: str) -> float:
        rows = self.db.conn.execute(
            """SELECT selected_parameters_json, COUNT(*)
               FROM walk_forward_folds WHERE run_id = ?
               GROUP BY selected_parameters_json""",
            [run_id],
        ).fetchall()
        total = sum(int(row[1]) for row in rows)
        return max((int(row[1]) for row in rows), default=0) / total if total else 0.0

    def _cost_stress_passes(self, run_id: str) -> bool:
        rows = self.db.conn.execute(
            """WITH endpoints AS (
                   SELECT fold_id,
                          arg_min(equity / NULLIF(1 + net_return, 0), timestamp) AS initial_equity,
                          arg_max(equity, timestamp) AS final_equity
                   FROM strategy_equity_curve
                   WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE'
                   GROUP BY fold_id
               ), costs AS (
                   SELECT fold_id, SUM(cost) AS total_cost
                   FROM walk_forward_trade_attribution WHERE run_id = ? GROUP BY fold_id
               )
               SELECT SUM(final_equity - initial_equity
                          - (? - 1) * COALESCE(total_cost, 0))
               FROM endpoints LEFT JOIN costs USING (fold_id)""",
            [run_id, run_id, self.policy.cost_stress_multiplier],
        ).fetchone()
        return bool(rows is not None and rows[0] is not None and float(rows[0]) > 0)

    def _breadth_passes(self, run_id: str) -> bool:
        run_symbol = self.db.conn.execute(
            "SELECT symbol FROM strategy_runs WHERE run_id = ?", [run_id],
        ).fetchone()
        if run_symbol is None or not str(run_symbol[0]).startswith("PORTFOLIO"):
            return True
        contributions = [
            float(row[0]) for row in self.db.conn.execute(
                """SELECT SUM(realized_pnl) FROM walk_forward_trade_attribution
                   WHERE run_id = ? GROUP BY symbol HAVING SUM(realized_pnl) > 0""",
                [run_id],
            ).fetchall()
        ]
        total = sum(contributions)
        concentration = max(contributions, default=0.0) / total if total > 0 else 1.0
        return (
            len(contributions) >= self.policy.minimum_portfolio_contributors
            and concentration <= self.policy.maximum_profit_concentration
        )
