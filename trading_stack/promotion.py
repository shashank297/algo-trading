"""Deterministic research-to-paper promotion gates."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

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

    def assert_paper_authorized(
        self,
        run_id: str,
        strategy_name: str,
        approval_evidence: Any = None,
        *,
        expected_stage: str | None = None,
        expected_foundation_cert_id: str | None = None,
        expected_risk_policy_id: str | None = None,
        expected_risk_policy_hash: str | None = None,
        expected_code_sha: str | None = None,
        expected_evidence_hash: str | None = None,
        expected_scope: str | None = None,
        expected_subject_type: str | None = None,
        expected_promotion_review_id: str | None = None,
        trusted_issuers: Mapping[str, Any] | None = None,
        as_of_time: datetime | None = None,
    ) -> None:
        """Fail closed unless a human-approved promotion permits paper execution and valid external approval evidence is verified."""

        review = self.db.conn.execute(
            """SELECT review_id, stage, decision, human_approved FROM promotion_reviews
               WHERE run_id = ? AND strategy_name = ?
               ORDER BY reviewed_at DESC LIMIT 1""",
            [run_id, strategy_name],
        ).fetchone()
        if review is None:
            raise PermissionError(f"No promotion review authorizes paper trading for run {run_id}.")
        review_id, stage, decision, human_approved = str(review[0]), str(review[1]), str(review[2]), bool(review[3])
        if stage not in {PromotionStage.PAPER_CANDIDATE.value, PromotionStage.PAPER_ACTIVE.value}:
            raise PermissionError(f"Run {run_id} is at stage {stage}, not a paper-authorized stage.")
        if decision != "PASS" or not human_approved:
            raise PermissionError(f"Run {run_id} does not have a passing human approval.")

        if expected_stage is not None and stage.upper() != expected_stage.upper():
            raise PermissionError(f"Review stage '{stage}' does not match expected stage '{expected_stage}'")

        from trading_stack.approval import ExternalApprovalVerifier
        if approval_evidence is None:
            approval_evidence = ExternalApprovalVerifier.load_active_approval(self.db.conn, run_id, strategy_name)

        if approval_evidence is None:
            raise PermissionError(
                f"Run {run_id} lacks authoritative external human/board approval evidence in database."
            )

        if expected_promotion_review_id is not None and review_id != expected_promotion_review_id:
            raise PermissionError(
                f"Review '{review_id}' does not match expected promotion review '{expected_promotion_review_id}'"
            )

        # Resolve authoritative context. A run's frame certification is not a
        # foundation certification and must never be used as a substitute.
        resolved_subject_type = expected_subject_type or "STRATEGY_RUN"
        resolved_scope = expected_scope or "PAPER_TRADING"

        # Resolve run details from database if not supplied
        run_row = None
        try:
            run_row = self.db.conn.execute(
                "SELECT data_hash, frame_certification_id FROM strategy_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
        except Exception:
            pass

        resolved_evidence_hash = expected_evidence_hash
        if resolved_evidence_hash is None and run_row is not None and run_row[0]:
            resolved_evidence_hash = str(run_row[0])

        active_cert_row = self.db.conn.execute(
            """SELECT foundation_certification_id, code_sha, risk_policy_id, risk_policy_hash, status
               FROM foundation_certifications
               WHERE is_active = TRUE AND status = 'PASS'
               ORDER BY recorded_at DESC LIMIT 1"""
        ).fetchone()
        if active_cert_row is None:
            raise PermissionError("Paper authorization requires an active PASS foundation certification.")
        resolved_foundation_cert_id = expected_foundation_cert_id
        resolved_code_sha = expected_code_sha
        active_cert_id, active_code_sha = str(active_cert_row[0]), str(active_cert_row[1] or "")
        if resolved_foundation_cert_id is None:
            resolved_foundation_cert_id = active_cert_id
        elif resolved_foundation_cert_id != active_cert_id:
            raise PermissionError(
                f"Requested foundation certification '{resolved_foundation_cert_id}' is not the active certification '{active_cert_id}'"
            )
        if not active_code_sha:
            raise PermissionError("Active foundation certification has no authoritative code identity.")
        runtime_code_sha = os.environ.get("CODE_SHA", "").strip()
        if not runtime_code_sha:
            raise PermissionError("Paper authorization requires an explicit runtime CODE_SHA identity.")
        if active_code_sha != runtime_code_sha:
            raise PermissionError(
                "Active foundation certification code identity does not match the runtime CODE_SHA."
            )
        if resolved_code_sha is None:
            resolved_code_sha = runtime_code_sha
        elif resolved_code_sha != runtime_code_sha:
            raise PermissionError(
                f"Approval code_sha '{resolved_code_sha}' is not the runtime code identity '{runtime_code_sha}'"
            )
        from risk.factory import load_canonical_risk_policy
        active_risk_policy = load_canonical_risk_policy()
        resolved_risk_policy_id = expected_risk_policy_id or active_risk_policy.policy_id
        resolved_risk_policy_hash = expected_risk_policy_hash or active_risk_policy.policy_hash
        if resolved_risk_policy_id != active_risk_policy.policy_id:
            raise PermissionError(
                f"Requested risk policy id '{resolved_risk_policy_id}' is not the canonical active policy '{active_risk_policy.policy_id}'"
            )
        if resolved_risk_policy_hash != active_risk_policy.policy_hash:
            raise PermissionError(
                f"Requested risk policy hash '{resolved_risk_policy_hash}' is not the canonical active policy hash"
            )

        # Fail closed if any required context field cannot be resolved
        missing_context: list[str] = []
        if not run_id:
            missing_context.append("run_id")
        if not strategy_name:
            missing_context.append("strategy_name")
        if not stage:
            missing_context.append("stage")
        if not resolved_foundation_cert_id:
            missing_context.append("foundation_certification_id")
        if not resolved_risk_policy_id:
            missing_context.append("risk_policy_id")
        if not resolved_risk_policy_hash:
            missing_context.append("risk_policy_hash")
        if not resolved_code_sha:
            missing_context.append("code_sha")
        if not resolved_evidence_hash:
            missing_context.append("evidence_hash")
        if not resolved_scope:
            missing_context.append("scope")
        if not resolved_subject_type:
            missing_context.append("subject_type")

        if missing_context:
            raise PermissionError(
                f"Paper authorization failed closed: unresolvable authoritative context {sorted(missing_context)} for run {run_id}"
            )

        ExternalApprovalVerifier.verify_approval(
            approval_evidence,
            expected_run_id=run_id,
            expected_strategy_name=strategy_name,
            expected_stage=stage,
            expected_foundation_cert_id=resolved_foundation_cert_id,
            expected_risk_policy_id=resolved_risk_policy_id,
            expected_risk_policy_hash=resolved_risk_policy_hash,
            expected_code_sha=resolved_code_sha,
            expected_evidence_hash=resolved_evidence_hash,
            expected_scope=resolved_scope,
            expected_subject_type=resolved_subject_type,
            expected_promotion_review_id=review_id,
            trusted_issuers=trusted_issuers,
            as_of_time=as_of_time,
        )

    def review(
        self,
        run_id: str,
        *,
        human_approved: bool = False,
        paper_activation: bool = False,
        certification_bundle_id: str | None = None,
    ) -> dict[str, object]:
        run = self.db.conn.execute(
            "SELECT strategy_name, mode, data_hash, frame_certification_id FROM strategy_runs WHERE run_id = ?", [run_id]
        ).fetchone()
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")
        strategy_name = str(run[0])
        run_mode = str(run[1])
        if "DIAGNOSTIC" in run_mode.upper() or "OVERRIDE" in run_mode.upper():
            return {
                "run_id": run_id,
                "strategy_name": strategy_name,
                "stage": "NOT_PROMOTABLE",
                "decision": "REJECT",
                "score": 0.0,
                "reasons": ["RUN_USES_RISK_OVERRIDE_OR_DIAGNOSTIC_MODE_NOT_PROMOTABLE"],
                "human_approved": False,
                "reviewed_at": datetime.now(timezone.utc),
            }
        run_data_hash = str(run[2])
        run_frame_certification_id = str(run[3]) if run[3] else None
        has_authoritative_frame = run_frame_certification_id is not None

        # Resolve or certify immutable run certification bundle
        from trading_stack.certification import RunCertificationService
        if not certification_bundle_id:
            bundle_row = self.db.conn.execute(
                "SELECT bundle_id FROM run_certification_bundles WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
                [run_id],
            ).fetchone()
            if bundle_row:
                certification_bundle_id = str(bundle_row[0])
            else:
                certification_bundle_id = RunCertificationService(self.db).certify(run_id)

        bundle = self.db.conn.execute(
            "SELECT run_id, run_data_hash, frame_certification_id FROM run_certification_bundles WHERE bundle_id = ?",
            [certification_bundle_id],
        ).fetchone()
        if not bundle or str(bundle[0]) != run_id or str(bundle[1]) != run_data_hash or bundle[2] != run_frame_certification_id:
            raise RuntimeError("Certification bundle is not bound to this run's immutable data and frame evidence.")

        cert_rows = self.db.conn.execute(
            "SELECT category, status FROM run_certifications WHERE bundle_id = ? AND run_id = ?",
            [certification_bundle_id, run_id],
        ).fetchall()
        required_categories = {
            "DATA_LINEAGE", "DATA_QUALITY", "CAUSALITY", "PIT_SURVIVORSHIP", "OOS_WALK_FORWARD",
        }
        if len(cert_rows) != len(required_categories) or {str(row[0]) for row in cert_rows} != required_categories:
            raise RuntimeError(f"Certification bundle {certification_bundle_id} is incomplete for run {run_id}.")
        cert_map = {str(row[0]): str(row[1]) for row in cert_rows}

        lineage_certified = has_authoritative_frame and cert_map.get("DATA_LINEAGE") == "PASS"
        dq_certified = (cert_map.get("DATA_QUALITY") == "PASS")
        causality_certified = (cert_map.get("CAUSALITY") == "PASS")
        pit_certified = (cert_map.get("PIT_SURVIVORSHIP") == "PASS")
        oos_certified = (cert_map.get("OOS_WALK_FORWARD") == "PASS")

        metrics = dict(self.db.conn.execute("SELECT metric_name, AVG(metric_value) FROM walk_forward_metrics WHERE run_id = ? GROUP BY metric_name", [run_id]).fetchall())
        evidence_row = self.db.conn.execute("SELECT COUNT(*) FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE'", [run_id]).fetchone()
        if evidence_row is None:
            raise RuntimeError(f"DuckDB returned no evidence count for {run_id}.")
        evidence = int(evidence_row[0])

        # Compute primary performance metrics from stitched out-of-sample equity returns
        import numpy as np
        equity_df = self.db.conn.execute(
            "SELECT timestamp, equity FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE' ORDER BY timestamp",
            [run_id],
        ).df()

        oos_sharpe: float | None = None
        oos_sortino: float | None = None
        oos_drawdown: float | None = None
        oos_profit_factor: float | None = None

        if not equity_df.empty and len(equity_df) > 1:
            rets = equity_df["equity"].pct_change().dropna()
            if len(rets) > 0:
                ret_std = float(rets.std())
                ret_mean = float(rets.mean())
                if ret_std > 1e-9:
                    oos_sharpe = float(ret_mean / ret_std * np.sqrt(252))
                elif ret_mean > 0:
                    oos_sharpe = float(ret_mean / 1e-6 * np.sqrt(252))
                else:
                    oos_sharpe = 0.0

                downside = rets[rets < 0]
                if len(downside) > 0 and float(downside.std()) > 1e-9:
                    oos_sortino = float(ret_mean / downside.std() * np.sqrt(252))
                else:
                    oos_sortino = oos_sharpe

            cum_peak = equity_df["equity"].cummax()
            dd = (cum_peak - equity_df["equity"]) / cum_peak
            oos_drawdown = float(dd.max()) if not dd.empty else 0.0
            pos_rets = float(rets[rets > 0].sum()) if len(rets[rets > 0]) > 0 else 0.0
            neg_rets = abs(float(rets[rets < 0].sum())) if len(rets[rets < 0]) > 0 else 0.0
            oos_profit_factor = (pos_rets / neg_rets) if neg_rets > 1e-9 else (2.0 if pos_rets > 0 else 1.0)

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

        checks = {
            "authoritative_execution": run_mode != "vectorized",
            "sharpe": oos_sharpe is not None and oos_sharpe >= self.policy.minimum_sharpe,
            "sortino": oos_sortino is not None and oos_sortino >= self.policy.minimum_sortino,
            "profit_factor": oos_profit_factor is not None and oos_profit_factor >= self.policy.minimum_profit_factor,
            "drawdown": oos_drawdown is not None and oos_drawdown <= self.policy.maximum_drawdown,
            "trades": metrics.get("trades", 0.0) >= self.policy.minimum_trades,
            "out_of_sample": evidence > 0 and oos_certified and oos_sharpe is not None and oos_drawdown is not None,
            "walk_forward_metrics": bool(metrics) or not equity_df.empty,
            "minimum_folds": len(fold_rows) >= self.policy.minimum_walk_forward_folds,
            "fold_consistency": positive_fold_fraction >= self.policy.minimum_positive_fold_fraction,
            "cost_stress": cost_stress_passes,
            "parameter_stability": parameter_stability >= self.policy.minimum_parameter_stability,
            "profit_breadth": breadth_passes,
            "zero_survivorship_bias": pit_certified,
            "data_quality_verified": dq_certified,
            "causality_certified": causality_certified,
            "data_lineage_verified": lineage_certified,
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
            "certification_bundle_id": certification_bundle_id,
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
