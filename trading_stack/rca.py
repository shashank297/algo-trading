"""Out-of-sample strategy correlation, clustering, and structural-strength RCA."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from storage.duckdb_manager import DuckDBManager


@dataclass(frozen=True)
class RCAReport:
    analysis_id: str
    correlations: pd.DataFrame
    strategy_summary: pd.DataFrame
    effective_independent_bets: float


class RCAEngine:
    """Explain performance breadth and detect redundant strategy evidence."""

    def __init__(self, db: DuckDBManager, cluster_threshold: float = 0.75) -> None:
        self.db = db
        self.cluster_threshold = cluster_threshold

    def analyze(self, run_ids: list[str], *, evidence_level: str = "OUT_OF_SAMPLE") -> RCAReport:
        if not run_ids:
            raise ValueError("RCA requires at least one run.")
        placeholders = ",".join("?" for _ in run_ids)
        curves = self.db.conn.execute(
            f"SELECT run_id, timestamp, net_return, drawdown, evidence_level FROM strategy_equity_curve WHERE run_id IN ({placeholders})",
            run_ids,
        ).df()
        if curves.empty:
            raise ValueError("No persisted equity curves found for the requested runs.")
        requested = curves[curves["evidence_level"] == evidence_level]
        if requested.empty:
            raise ValueError(f"No {evidence_level} equity evidence exists for the requested runs.")
        curves = requested
        metadata_rows = self.db.conn.execute(
            f"SELECT run_id, strategy_name, symbol, mode FROM strategy_runs WHERE run_id IN ({placeholders})", run_ids,
        ).fetchall()
        run_metadata = {
            str(run_id): {"strategy_name": str(name), "symbol": str(symbol), "mode": str(mode)}
            for run_id, name, symbol, mode in metadata_rows
        }
        run_names = {run_id: values["strategy_name"] for run_id, values in run_metadata.items()}
        returns = curves.pivot(index="timestamp", columns="run_id", values="net_return")
        drawdowns = curves.pivot(index="timestamp", columns="run_id", values="drawdown")
        matrix = returns.corr(min_periods=2).fillna(0.0)
        analysis_id = str(uuid.uuid4())
        clusters = self._clusters(matrix)
        rows: list[dict[str, Any]] = []
        for left_index, left in enumerate(matrix.columns):
            for right in matrix.columns[left_index + 1:]:
                trade_overlap = self._trade_overlap(left, right)
                rows.append({
                    "analysis_id": analysis_id,
                    "strategy_a": self._run_label(left, run_metadata),
                    "strategy_b": self._run_label(right, run_metadata),
                    "run_id_a": left, "run_id_b": right,
                    "symbol_a": run_metadata.get(left, {}).get("symbol"),
                    "symbol_b": run_metadata.get(right, {}).get("symbol"),
                    "return_correlation": float(matrix.loc[left, right]),
                    "signal_overlap": trade_overlap, "holdings_overlap": self._holdings_overlap(left, right),
                    "trade_overlap": trade_overlap,
                    "drawdown_overlap": self._drawdown_overlap(drawdowns.get(left), drawdowns.get(right)),
                    "regime_correlation_json": json.dumps(self._regime_correlations(returns[left], returns[right]), sort_keys=True),
                    "cluster_id": clusters.get(left), "evidence_level": evidence_level,
                })
        self.db.log_strategy_correlations(rows)
        return RCAReport(analysis_id, pd.DataFrame(rows), self._summary(run_ids, run_names, clusters), self._effective_bets(matrix))

    def explain_loss(
        self,
        run_id: str,
        symbol: str | None = None,
        *,
        evidence_level: str = "OUT_OF_SAMPLE",
    ) -> dict[str, Any]:
        if evidence_level not in {"OUT_OF_SAMPLE", "IN_SAMPLE"}:
            raise ValueError("evidence_level must be OUT_OF_SAMPLE or IN_SAMPLE.")
        attribution_table = (
            "walk_forward_trade_attribution"
            if evidence_level == "OUT_OF_SAMPLE"
            else "trade_attribution"
        )
        round_trip_table = (
            "walk_forward_round_trips"
            if evidence_level == "OUT_OF_SAMPLE"
            else "trade_round_trips"
        )
        clauses, values = ["run_id = ?"], [run_id]
        if symbol:
            clauses.append("symbol = ?")
            values.append(symbol)
        attribution = self.db.conn.execute(
            f"""SELECT symbol, reason, exit_classification, SUM(realized_pnl) pnl,
                       SUM(gross_pnl) AS gross_pnl, SUM(cost) AS total_cost, SUM(quantity) AS quantity,
                       AVG(holding_period_days) average_holding_days, COUNT(*) events
                FROM {attribution_table} WHERE {' AND '.join(clauses)}
                GROUP BY symbol, reason, exit_classification ORDER BY pnl""",
            values,
        ).df()
        attribution = attribution.rename(columns={"total_cost": "cost"})
        sectors = self.db.conn.execute(
            f"""SELECT COALESCE(u.sector, 'UNKNOWN') sector, SUM(a.realized_pnl) pnl, SUM(a.cost) AS total_cost
               FROM {attribution_table} a LEFT JOIN universe_snapshot_members u ON a.symbol = u.symbol
               WHERE a.run_id = ? GROUP BY sector ORDER BY pnl""", [run_id],
        ).df()
        sectors = sectors.rename(columns={"total_cost": "cost"})
        round_trip_clauses, round_trip_values = ["run_id = ?"], [run_id]
        if symbol:
            round_trip_clauses.append("symbol = ?")
            round_trip_values.append(symbol)
        round_trips = self.db.conn.execute(
            f"""SELECT symbol, entry_timestamp, exit_timestamp, quantity, entry_price, exit_price,
                       entry_cost, exit_cost, gross_pnl, net_pnl, holding_period_days,
                       entry_reason, exit_reason, exit_classification
                FROM {round_trip_table} WHERE {' AND '.join(round_trip_clauses)}
                ORDER BY net_pnl, exit_timestamp""",
            round_trip_values,
        ).df()
        return {
            "run_id": run_id,
            "symbol": symbol,
            "evidence_level": evidence_level,
            "causes": attribution.to_dict(orient="records"),
            "round_trips": round_trips.to_dict(orient="records"),
            "sectors": sectors.to_dict(orient="records"),
        }

    @staticmethod
    def _run_label(run_id: str, metadata: dict[str, dict[str, str]]) -> str:
        values = metadata.get(run_id, {})
        return f"{values.get('strategy_name', run_id)}|{values.get('symbol', 'UNKNOWN')}|{run_id[-12:]}"

    def _summary(self, run_ids: list[str], names: dict[str, str], clusters: dict[str, str]) -> pd.DataFrame:
        rows = []
        for run_id in run_ids:
            metrics = dict(self.db.conn.execute(
                """SELECT metric_name, AVG(metric_value)
                   FROM walk_forward_metrics WHERE run_id = ? GROUP BY metric_name""",
                [run_id],
            ).fetchall())
            breadth = self.db.conn.execute(
                """SELECT COUNT(DISTINCT symbol), SUM(realized_pnl), SUM(cost)
                   FROM walk_forward_trade_attribution WHERE run_id = ?""",
                [run_id],
            ).fetchone()
            if breadth is None:
                raise RuntimeError(f"DuckDB returned no attribution summary for {run_id}.")
            rows.append({
                "run_id": run_id, "strategy_name": names.get(run_id, run_id), "cluster_id": clusters.get(run_id),
                "sharpe": metrics.get("sharpe", 0.0), "sortino": metrics.get("sortino", 0.0),
                "calmar": metrics.get("calmar", 0.0), "max_drawdown": metrics.get("max_drawdown", 0.0),
                "symbols_contributing": int(breadth[0] or 0), "realized_pnl": float(breadth[1] or 0.0),
                "cost": float(breadth[2] or 0.0),
            })
        return pd.DataFrame(rows).sort_values(["sharpe", "symbols_contributing"], ascending=False)

    def _clusters(self, matrix: pd.DataFrame) -> dict[str, str]:
        parent = {name: name for name in matrix.columns}

        def find(value: str) -> str:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        for left in matrix.columns:
            for right in matrix.columns:
                if left != right and abs(float(matrix.loc[left, right])) >= self.cluster_threshold:
                    left_root, right_root = find(left), find(right)
                    if left_root != right_root:
                        parent[right_root] = left_root
        roots = {name: find(name) for name in matrix.columns}
        labels = {root: f"cluster-{index + 1}" for index, root in enumerate(sorted(set(roots.values())))}
        return {name: labels[root] for name, root in roots.items()}

    def _holdings_overlap(self, left: str, right: str) -> float:
        query = "SELECT DISTINCT timestamp, symbol FROM portfolio_positions WHERE run_id = ? AND symbol <> '__PORTFOLIO__' AND quantity > 0"
        left_set, right_set = set(self.db.conn.execute(query, [left]).fetchall()), set(self.db.conn.execute(query, [right]).fetchall())
        return len(left_set & right_set) / len(left_set | right_set) if left_set | right_set else 0.0

    def _trade_overlap(self, left: str, right: str) -> float:
        query = "SELECT DISTINCT requested_at, symbol, side FROM strategy_orders WHERE run_id = ?"
        left_set, right_set = set(self.db.conn.execute(query, [left]).fetchall()), set(self.db.conn.execute(query, [right]).fetchall())
        return len(left_set & right_set) / len(left_set | right_set) if left_set | right_set else 0.0

    @staticmethod
    def _drawdown_overlap(left: pd.Series | None, right: pd.Series | None) -> float:
        if left is None or right is None:
            return 0.0
        union = (left < 0) | (right < 0)
        return float(((left < 0) & (right < 0)).sum() / union.sum()) if union.sum() else 0.0

    @staticmethod
    def _regime_correlations(left: pd.Series, right: pd.Series) -> dict[str, float]:
        market = (left + right) / 2
        masks = {"UP": market > 0, "DOWN": market < 0, "HIGH_VOL": market.abs() >= market.abs().median()}
        return {name: float(left[mask].corr(right[mask])) if mask.sum() >= 2 else 0.0 for name, mask in masks.items()}

    @staticmethod
    def _effective_bets(matrix: pd.DataFrame) -> float:
        if matrix.empty:
            return 0.0
        eigenvalues = np.clip(np.linalg.eigvalsh(matrix.to_numpy(dtype=float)), 0, None)
        denominator = float(np.square(eigenvalues).sum())
        return float(eigenvalues.sum() ** 2 / denominator) if denominator else 0.0
