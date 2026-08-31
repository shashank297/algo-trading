"""Phase 2.7 OOS-only conditional strategy evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np
import pandas as pd

from trading_stack.backtest import _annualized_return, _profit_factor, _sharpe_ratio, _sortino_ratio

if TYPE_CHECKING:
    from storage.duckdb_manager import DuckDBManager


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ConditionalEvidencePolicy:
    minimum_observations: int = 30
    minimum_trades: int = 10
    minimum_folds: int = 2
    minimum_span_days: int = 30
    prior_observations: float = 60.0


@dataclass(frozen=True)
class StrategyConditionalEvidence:
    evidence_id: str
    strategy_name: str
    strategy_version: str
    run_id: str
    market_regime: str | None
    asset_cluster: str | None
    timeframe: str
    universe: str | None
    observation_count: int
    trade_count: int
    fold_count: int
    first_observation: datetime
    last_observation: datetime
    net_return: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    profit_factor: float
    win_rate: float
    expectancy: float
    turnover: float
    cost_ratio: float
    evidence_status: str
    raw_conditional_metric: float
    global_metric: float
    effective_sample_size: float
    shrinkage_weight: float
    shrunk_metric: float
    available_at: datetime
    evidence_hash: str


class ConditionalEvidenceBuilder:
    """Build deterministic, net-of-cost OOS evidence; no IS fallback exists."""

    def __init__(self, policy: ConditionalEvidencePolicy | None = None) -> None:
        self.policy = policy or ConditionalEvidencePolicy()

    def build(
        self,
        *,
        strategy_name: str,
        strategy_version: str,
        run_id: str,
        observations: Iterable[dict],
        global_metric: float,
        available_at: datetime,
        market_regime: str | None = None,
        asset_cluster: str | None = None,
        timeframe: str = "1d",
        universe: str | None = None,
    ) -> StrategyConditionalEvidence:
        if available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        rows = sorted(
            (dict(x) for x in observations if x.get("evidence_level") == "OUT_OF_SAMPLE"),
            key=lambda x: str(x["timestamp"]),
        )
        if not rows:
            raise ValueError("No OUT_OF_SAMPLE observations; in-sample fallback is prohibited")
        timestamps = [datetime.fromisoformat(str(x["timestamp"]).replace("Z", "+00:00")) for x in rows]
        net_returns = [float(x.get("net_return", 0.0)) for x in rows]
        returns = pd.Series(net_returns, dtype=float)
        equity = (1.0 + returns).cumprod()
        drawdown = equity / equity.cummax() - 1.0
        cost_ratio = sum(
            float(x.get("cost", 0.0)) / abs(float(x.get("equity", 0.0)))
            for x in rows
            if float(x.get("equity", 0.0))
        )
        trades = sum(int(x.get("trade_count", 0)) for x in rows)
        folds = len({str(x.get("fold_id")) for x in rows if x.get("fold_id") is not None})
        span_days = (max(timestamps) - min(timestamps)).days
        raw = sum(net_returns) / len(net_returns)
        weight = len(rows) / (len(rows) + self.policy.prior_observations)
        status = (
            "SUFFICIENT"
            if (
                len(rows) >= self.policy.minimum_observations
                and trades >= self.policy.minimum_trades
                and folds >= self.policy.minimum_folds
                and span_days >= self.policy.minimum_span_days
            )
            else "INSUFFICIENT_CONDITIONAL_EVIDENCE"
        )
        payload = {
            "strategy_name": strategy_name,
            "strategy_version": strategy_version,
            "run_id": run_id,
            "market_regime": market_regime,
            "asset_cluster": asset_cluster,
            "rows": rows,
            "global_metric": global_metric,
            "available_at": available_at.isoformat(),
            "policy": asdict(self.policy),
        }
        digest = _hash(payload)
        return StrategyConditionalEvidence(
            digest[:32],
            strategy_name,
            strategy_version,
            run_id,
            market_regime,
            asset_cluster,
            timeframe,
            universe,
            len(rows),
            trades,
            folds,
            min(timestamps),
            max(timestamps),
            float(equity.iloc[-1] - 1.0) if not equity.empty else 0.0,
            _sharpe_ratio(returns, timeframe),
            _sortino_ratio(returns, timeframe),
            float(_annualized_return(equity, timeframe, 1.0) / abs(float(drawdown.min())))
            if not drawdown.empty and float(drawdown.min()) < 0
            else 0.0,
            float(drawdown.min()) if not drawdown.empty else 0.0,
            _profit_factor(returns),
            float(sum(value > 0 for value in net_returns) / len(net_returns)),
            raw,
            0.0,
            cost_ratio,
            status,
            raw,
            global_metric,
            len(rows),
            weight,
            weight * raw + (1 - weight) * global_metric,
            available_at,
            digest,
        )


class ConditionalEvidenceService:
    """Materialize Phase 2.7 evidence from persisted OOS rows only.

    Context is resolved with an as-of join at each OOS timestamp.  A missing
    context remains unavailable; it is never replaced with a newer snapshot.
    """

    AGGREGATIONS = ("GLOBAL", "REGIME", "ASSET_CLUSTER", "REGIME_ASSET_CLUSTER")

    def __init__(self, db: "DuckDBManager", policy: ConditionalEvidencePolicy | None = None) -> None:
        self.db = db
        self.policy = policy or ConditionalEvidencePolicy()

    def materialize(self, run_id: str, *, market: str = "NSE", context_type: str = "EOD") -> list[str]:
        conn = self.db.conn
        run = conn.execute(
            """SELECT strategy_name, symbol, timeframe, data_hash, finished_at, status
               FROM strategy_runs WHERE run_id = ?""",
            [run_id],
        ).fetchone()
        if run is None or run[4] is None or str(run[5]).upper() not in {"COMPLETED", "SUCCEEDED"}:
            raise ValueError("Conditional evidence requires a completed persisted strategy run")
        rows = conn.execute(
            """SELECT timestamp, fold_id, equity, gross_return, net_return, drawdown, gross_exposure
               FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE'
               ORDER BY timestamp, fold_id""",
            [run_id],
        ).fetchdf()
        if rows.empty:
            raise ValueError("No OUT_OF_SAMPLE observations; in-sample fallback is prohibited")
        trial = self._authoritative_trial(run_id)
        if str(trial["trial_data_hash"]) != str(run[3]):
            raise ValueError("Authoritative trial data hash does not match strategy run data hash")
        evidence_available_at = pd.Timestamp.now(tz="UTC")
        version = str(trial["strategy_version"])
        observations: list[dict] = []
        for record in rows.to_dict("records"):
            point = pd.Timestamp(record["timestamp"])
            regime = conn.execute(
                """SELECT transition_id, operational_regime_after, policy_hash FROM regime_transition_events
                   WHERE market=? AND context_type=? AND decision_time <= ? AND created_at <= ?
                   ORDER BY decision_time DESC, transition_id DESC LIMIT 1""",
                [market, context_type, point, point],
            ).fetchone()
            asset = conn.execute(
                """SELECT asset_state_id, behavior_cluster, policy_hash FROM asset_state_snapshots
                   WHERE symbol=? AND context_type=? AND decision_time <= ? AND created_at <= ?
                   ORDER BY decision_time DESC, asset_state_id DESC LIMIT 1""",
                [run[1], context_type, point, point],
            ).fetchone()
            cost_row = conn.execute(
                """SELECT COALESCE(SUM(cost), 0), COUNT(*) FROM walk_forward_trade_attribution
                   WHERE run_id=? AND fold_id=? AND timestamp=?""",
                [run_id, record["fold_id"], point],
            ).fetchone()
            if cost_row is None:
                raise RuntimeError("DuckDB returned no cost aggregate")
            cost, trade_count = cost_row
            authoritative_net = float(record["net_return"])
            cost_ratio = float(cost) / abs(float(record["equity"])) if float(record["equity"]) else 0.0
            status = "CONTEXT_AVAILABLE" if regime and asset and regime[1] and asset[1] else "CONTEXT_UNAVAILABLE"
            payload = {
                "run_id": run_id,
                "fold_id": record["fold_id"],
                "time": point.isoformat(),
                "regime": regime,
                "asset": asset,
                "net": authoritative_net,
                "gross": float(record["gross_return"]),
                "equity": float(record["equity"]),
                "drawdown": float(record["drawdown"]),
                "gross_exposure": float(record["gross_exposure"]),
                "cost": cost,
                "cost_ratio": cost_ratio,
            }
            observation_id = _hash(payload)[:32]
            observations.append(
                {
                    "observation_id": observation_id,
                    "timestamp": point,
                    "fold_id": str(record["fold_id"]),
                    "net_return": authoritative_net,
                    "gross_return": float(record["gross_return"]),
                    "equity": float(record["equity"]),
                    "drawdown": float(record["drawdown"]),
                    "gross_exposure": float(record["gross_exposure"]),
                    "cost": float(cost),
                    "cost_ratio": cost_ratio,
                    "trade_count": int(trade_count),
                    "regime": regime,
                    "asset": asset,
                    "status": status,
                    "hash": _hash(payload),
                }
            )
        self._persist_observations(run_id, run, version, observations)
        if any(item["status"] != "CONTEXT_AVAILABLE" for item in observations):
            raise ValueError("Every OOS observation requires causal regime and asset-state context")
        return self._aggregate(run_id, run, version, observations, trial, evidence_available_at)

    def _authoritative_trial(self, run_id: str) -> dict[str, Any]:
        """Return the sole immutable successful trial linked to this run."""
        matches = []
        for trial_id, trial_json, metrics_json, finished_at in self.db.conn.execute(
            "SELECT trial_id, trial_json, metrics_json, finished_at FROM research_trials_log WHERE status='SUCCEEDED'"
        ).fetchall():
            trial = json.loads(str(trial_json))
            metrics = json.loads(str(metrics_json)) if metrics_json else {}
            if str(metrics.get("run_id", "")) == run_id:
                required = ("cost_model_version", "cost_model_hash", "strategy_version", "data_hash")
                if finished_at is None or any(not trial.get(field) for field in required):
                    raise ValueError("Authoritative trial cost/data lineage is unavailable")
                matches.append(
                    {
                        "trial_id": str(trial_id),
                        "cost_model_version": str(trial["cost_model_version"]),
                        "cost_model_hash": str(trial["cost_model_hash"]),
                        "strategy_version": str(trial["strategy_version"]),
                        "trial_data_hash": str(trial["data_hash"]),
                        "trial_finished_at": pd.Timestamp(finished_at).isoformat(),
                    }
                )
        if len(matches) != 1:
            raise ValueError("Conditional evidence requires exactly one successful trial linked to the run")
        return matches[0]

    def _persist_observations(self, run_id: str, run: tuple, version: str, rows: list[dict]) -> None:
        for item in rows:
            regime, asset = item["regime"], item["asset"]
            lineage = {
                "run_data_hash": run[3],
                "fold_id": item["fold_id"],
                "regime_transition_id": regime[0] if regime else None,
                "asset_state_id": asset[0] if asset else None,
            }
            values = [
                item["observation_id"],
                run_id,
                item["fold_id"],
                item["timestamp"],
                run[1],
                run[0],
                version,
                regime[1] if regime else None,
                regime[0] if regime else None,
                regime[2] if regime else None,
                asset[1] if asset else None,
                asset[0] if asset else None,
                asset[2] if asset else None,
                item["net_return"],
                item["gross_return"],
                item["cost"],
                item["trade_count"],
                item["status"],
                json.dumps(lineage, sort_keys=True),
                item["hash"],
            ]
            existing = self.db.conn.execute(
                "SELECT evidence_hash FROM strategy_conditional_observations WHERE observation_id=?",
                [item["observation_id"]],
            ).fetchone()
            if existing and existing[0] != item["hash"]:
                raise ValueError("Conflicting immutable conditional observation")
            if not existing:
                self.db.conn.execute(
                    "INSERT INTO strategy_conditional_observations (observation_id,run_id,fold_id,observation_time,symbol,strategy_name,strategy_version,market_regime,regime_transition_id,regime_policy_hash,asset_cluster,asset_state_id,asset_policy_hash,net_return,gross_return,attributable_cost,trade_count,context_status,lineage_json,evidence_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values,
                )

    def _aggregate(
        self,
        run_id: str,
        run: tuple,
        version: str,
        rows: list[dict],
        trial: dict[str, Any],
        evidence_available_at: pd.Timestamp,
    ) -> list[str]:
        valid = [r for r in rows if r["status"] == "CONTEXT_AVAILABLE"]
        if not valid:
            raise ValueError("No causally established historical context")
        global_metric = float(np.mean([r["net_return"] for r in valid]))
        groups: dict[tuple[str, str | None, str | None], list[dict]] = {("GLOBAL", None, None): valid}
        for row in valid:
            regime, asset = row["regime"][1], row["asset"][1]
            groups.setdefault(("REGIME", regime, None), []).append(row)
            groups.setdefault(("ASSET_CLUSTER", None, asset), []).append(row)
            groups.setdefault(("REGIME_ASSET_CLUSTER", regime, asset), []).append(row)
        ids = []
        for (level, regime, asset), group in sorted(groups.items()):
            ids.append(
                self._persist_group(
                    run_id,
                    run,
                    version,
                    level,
                    regime,
                    asset,
                    group,
                    global_metric,
                    trial,
                    evidence_available_at,
                )
            )
        return ids

    def _persist_group(
        self,
        run_id: str,
        run: tuple,
        version: str,
        level: str,
        regime: str | None,
        asset: str | None,
        group: list[dict],
        global_metric: float,
        trial: dict[str, Any],
        evidence_available_at: pd.Timestamp,
    ) -> str:
        ordered = sorted(group, key=lambda row: (row["timestamp"], row["fold_id"]))
        values = np.array([r["net_return"] for r in ordered], dtype=float)
        returns = pd.Series(values, dtype=float)
        equity = (1.0 + returns).cumprod()
        drawdown = equity / equity.cummax() - 1.0
        costs = sum(r["cost"] for r in group)
        gross = sum(r["gross_return"] for r in group)
        cost_ratio = sum(r["cost_ratio"] for r in group)
        n, trades, folds = len(group), sum(r["trade_count"] for r in group), len({r["fold_id"] for r in group})
        first, last = min(r["timestamp"] for r in group), max(r["timestamp"] for r in group)
        span = (last - first).days
        sufficient = (
            n >= self.policy.minimum_observations
            and trades >= self.policy.minimum_trades
            and folds >= self.policy.minimum_folds
            and span >= self.policy.minimum_span_days
        )
        weight = n / (n + self.policy.prior_observations)
        raw = float(values.mean())
        shrunk = weight * raw + (1 - weight) * global_metric
        policy_data = asdict(self.policy)
        policy_hash = _hash(policy_data)
        lineage = {"observation_ids": sorted(r["observation_id"] for r in group), "run_data_hash": run[3], **trial}
        payload = {
            "level": level,
            "run": run_id,
            "version": version,
            "regime": regime,
            "asset": asset,
            "lineage": lineage,
            "policy_hash": policy_hash,
            "global": global_metric,
        }
        digest = _hash(payload)
        evidence_id = digest[:32]
        net_return = float(equity.iloc[-1] - 1.0) if not equity.empty else 0.0
        cagr = _annualized_return(equity, str(run[2]), 1.0)
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
        turnover = float(
            pd.Series([r["gross_exposure"] for r in ordered], dtype=float)
            .diff()
            .abs()
            .fillna(abs(float(ordered[0]["gross_exposure"])) if ordered else 0.0)
            .sum()
        )
        result = [
            evidence_id,
            level,
            run[0],
            version,
            run_id,
            trial["trial_id"],
            regime,
            asset,
            run[2],
            run[1],
            n,
            trades,
            folds,
            first,
            last,
            net_return,
            gross,
            costs,
            _sharpe_ratio(returns, str(run[2])),
            _sortino_ratio(returns, str(run[2])),
            float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0,
            max_drawdown,
            _profit_factor(returns),
            float((values > 0).sum() / n) if n else 0.0,
            raw,
            turnover,
            cost_ratio,
            "SUFFICIENT" if sufficient else "INSUFFICIENT_CONDITIONAL_EVIDENCE",
            raw,
            global_metric,
            float(n),
            weight,
            shrunk,
            "phase2.7-v1",
            policy_hash,
            trial["cost_model_version"],
            json.dumps(lineage, sort_keys=True),
            digest,
            evidence_available_at,
            trial["cost_model_hash"],
        ]
        existing = self.db.conn.execute(
            "SELECT evidence_hash FROM strategy_conditional_evidence WHERE evidence_id=?", [evidence_id]
        ).fetchone()
        if existing and existing[0] != digest:
            raise ValueError("Conflicting immutable conditional evidence")
        if not existing:
            columns = "evidence_id,aggregation_level,strategy_name,strategy_version,run_id,trial_id,market_regime,asset_cluster,timeframe,universe,observation_count,trade_count,fold_count,first_observation,last_observation,net_return,gross_return,total_cost,sharpe,sortino,calmar,max_drawdown,profit_factor,win_rate,expectancy,turnover,cost_ratio,evidence_status,raw_conditional_metric,global_metric,effective_sample_size,shrinkage_weight,shrunk_metric,sample_policy_version,sample_policy_hash,cost_model_version,lineage_json,evidence_hash,available_at,cost_model_hash"
            self.db.conn.execute(
                f"INSERT INTO strategy_conditional_evidence ({columns}) VALUES ({','.join('?' for _ in result)})",
                result,
            )
        return evidence_id
