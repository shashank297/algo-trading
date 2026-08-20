"""Forward-only paper sessions for approved cross-sectional portfolios."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from risk.engine import RiskEngine
from risk.models import RiskAction, RiskDecision, TradeProposal
from storage import DuckDBManager
from trading_stack.calendars import MarketCalendar
from trading_stack.costs import IndianDeliveryCostSchedule
from trading_stack.datasets import SynchronizedPanelBuilder
from trading_stack.domain import PaperExecutionMode
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.strategies import StrategyRegistry


@dataclass(frozen=True)
class ForwardPortfolioPaperResult:
    session_id: str
    status: str
    strategy_name: str
    universe_snapshot_id: str
    timeframe: str
    processed_sessions: int
    orders: tuple[dict[str, Any], ...]
    fills: tuple[dict[str, Any], ...]
    cash: float
    holdings: dict[str, float]
    equity: float
    pending_signal_timestamp: datetime | None
    paper_summary: dict[str, Any]


class ForwardPortfolioPaperSessionEngine:
    """Advance a synchronized portfolio only when a newer completed session exists."""

    def __init__(
        self,
        db: DuckDBManager,
        *,
        calendar: MarketCalendar,
        risk_engine: RiskEngine,
        cost_schedule: IndianDeliveryCostSchedule | None = None,
    ) -> None:
        self.db = db
        self.calendar = calendar
        self.risk_engine = risk_engine
        self.cost_schedule = cost_schedule or IndianDeliveryCostSchedule()
        self.backtester = PortfolioEventBacktester(
            self.cost_schedule,
            max_position_weight=risk_engine.policy.max_position_pct,
            max_gross_exposure=risk_engine.policy.max_gross_exposure_pct,
        )

    def run(
        self,
        *,
        strategy_name: str,
        approved_run_id: str,
        symbols: list[str],
        universe_snapshot_id: str,
        benchmark_symbol: str,
        timeframe: str,
        parameters: dict[str, Any] | None = None,
        starting_capital: float = 100_000.0,
        as_of: datetime | None = None,
        execution_mode: str = PaperExecutionMode.EOD_BATCH.value,
    ) -> ForwardPortfolioPaperResult:
        if timeframe != "1d":
            raise ValueError("Cross-sectional forward paper sessions currently require daily bars.")
        parameters = parameters or {}
        as_of = as_of or datetime.now(timezone.utc)
        strategy = StrategyRegistry.create(strategy_name, **parameters)
        dataset = SynchronizedPanelBuilder(
            self.db, calendar=self.calendar, strict_calendar=True,
        ).build(
            symbols, timeframe, universe_snapshot_id=universe_snapshot_id,
            benchmark_symbol=benchmark_symbol, minimum_lookback=strategy.metadata.required_lookback,
        )
        panel = self._completed_panel(dataset.panel, as_of)
        if panel.empty:
            raise ValueError("No completed synchronized sessions are available for portfolio paper trading.")
        panel = panel.copy().sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        panel["lagged_adv20"] = (
            panel.groupby("symbol", group_keys=False)["volume"]
            .apply(lambda s: s.shift(1).rolling(20, min_periods=1).mean())
        )
        panel["lagged_close"] = (
            panel.groupby("symbol", group_keys=False)["close"]
            .shift(1)
        )
        panel["lagged_traded_value"] = panel["lagged_close"] * panel["lagged_adv20"]
        signals = strategy.generate_signals(panel).copy()
        signals["timestamp"] = pd.to_datetime(signals["timestamp"], utc=True)
        session_id = self._session_id(
            strategy_name, strategy.metadata.version, approved_run_id, universe_snapshot_id,
            benchmark_symbol, timeframe, parameters, starting_capital,
        )
        latest_timestamp = pd.Timestamp(panel["timestamp"].max()).tz_convert("UTC")
        state = self._load_state(session_id)
        now = pd.Timestamp(as_of).tz_convert("UTC").to_pydatetime()
        if state is None:
            pending = self._targets_at_or_before(signals, latest_timestamp)
            with self.db.transaction():
                self.db._replace_rows("paper_portfolio_sessions", [{
                    "session_id": session_id, "approved_run_id": approved_run_id,
                    "strategy_name": strategy_name, "strategy_version": strategy.metadata.version,
                    "universe_snapshot_id": universe_snapshot_id, "benchmark_symbol": benchmark_symbol,
                    "timeframe": timeframe, "parameters_json": json.dumps(parameters, sort_keys=True),
                    "starting_capital": starting_capital, "cash": starting_capital,
                    "peak_equity": starting_capital,
                    "daily_start_date": latest_timestamp.tz_convert(self.calendar.zone).date(),
                    "daily_start_equity": starting_capital,
                    "last_processed_timestamp": latest_timestamp, "status": "ACTIVE",
                    "created_at": now, "updated_at": now,
                }])
                self._save_pending(session_id, pending, now)
                self._persist_run_state(
                    session_id, strategy_name, universe_snapshot_id, timeframe, parameters,
                    latest_timestamp, starting_capital, 0, starting_capital=starting_capital,
                )
                summary = self._reconcile(
                    session_id, as_of, [], [], 0.0,
                    "portfolio session bootstrapped; no historical orders replayed",
                )
            return ForwardPortfolioPaperResult(
                session_id, "BOOTSTRAPPED", strategy_name, universe_snapshot_id, timeframe,
                0, (), (), starting_capital, {}, starting_capital,
                self._pending_timestamp(pending), summary,
            )

        watermark = pd.Timestamp(state["last_processed_timestamp"])
        watermark = watermark.tz_localize("UTC") if watermark.tzinfo is None else watermark.tz_convert("UTC")
        dates = sorted(pd.Timestamp(value) for value in panel.loc[panel["timestamp"] > watermark, "timestamp"].unique())
        holdings = self._load_holdings(session_id)
        quantities = {symbol: float(row["quantity"]) for symbol, row in holdings.items()}
        average_cost = {symbol: float(row["average_cost"]) for symbol, row in holdings.items()}
        entry_timestamps = {
            symbol: pd.Timestamp(row["entry_timestamp"])
            for symbol, row in holdings.items() if pd.notna(row.get("entry_timestamp"))
        }
        entry_reasons = {
            symbol: str(row["entry_reason"])
            for symbol, row in holdings.items() if row.get("entry_reason") is not None
        }
        entry_cost_pools = {symbol: float(row["entry_cost_pool"]) for symbol, row in holdings.items()}
        entry_execution_cost_pools = {
            symbol: float(row.get("entry_execution_cost_pool") or 0.0)
            for symbol, row in holdings.items()
        }
        cash = float(state["cash"])
        pending = self._load_pending(session_id)
        latest_prices = self._latest_prices(panel, watermark)
        opening_equity = cash + sum(quantity * latest_prices.get(symbol, 0.0) for symbol, quantity in quantities.items())
        peak_equity = max(float(state["peak_equity"]), opening_equity)
        daily_start_equity = float(state.get("daily_start_equity") or opening_equity)
        daily_start_date = pd.Timestamp(state["daily_start_date"]).date()
        all_orders: list[dict[str, Any]] = []
        all_fills: list[dict[str, Any]] = []
        all_attribution: list[dict[str, Any]] = []
        all_round_trips: list[dict[str, Any]] = []
        all_costs: list[dict[str, Any]] = []
        all_rebalances: list[dict[str, Any]] = []
        all_risk: list[RiskDecision] = []
        position_rows: list[dict[str, Any]] = []

        for session_timestamp in dates:
            day = panel[panel["timestamp"] == session_timestamp].set_index("symbol", drop=False)
            session_date = session_timestamp.tz_convert(self.calendar.zone).date()
            if session_date != daily_start_date:
                daily_start_equity = cash + sum(
                    quantity * (
                        float(day.loc[symbol, "open"])
                        if symbol in day.index else latest_prices.get(symbol, 0.0)
                    )
                    for symbol, quantity in quantities.items()
                )
                daily_start_date = session_date
            if not pending.empty and pd.Timestamp(pending["timestamp"].max()) < session_timestamp:
                adjusted, decisions = self._risk_adjust_targets(
                    pending, day, quantities, cash, latest_prices, starting_capital,
                    daily_start_equity, peak_equity,
                )
                all_risk.extend(decisions)
                cash, generated = self.backtester._rebalance(
                    run_id=session_id, date=session_timestamp, day=day, targets=adjusted,
                    cash=cash, quantities=quantities, average_cost=average_cost,
                    entry_timestamps=entry_timestamps, entry_reasons=entry_reasons,
                    entry_cost_pools=entry_cost_pools,
                    entry_execution_cost_pools=entry_execution_cost_pools,
                    last_prices=latest_prices, mode="paper",
                    execution_mode=execution_mode,
                )
                all_orders.extend(generated["orders"])
                all_fills.extend(generated["fills"])
                all_attribution.extend(generated["attribution"])
                all_round_trips.extend(generated["round_trips"])
                all_costs.extend(generated["costs"])
                all_rebalances.append(generated["rebalance"])

            # A temporary missing bar freezes that holding at its last observed close.
            # Update latest_prices with completed session's close after rebalance execution
            latest_prices.update({str(symbol): float(row["close"]) for symbol, row in day.iterrows()})
            pending = self._targets_at_or_before(signals, session_timestamp)
            equity = cash + sum(quantity * latest_prices[symbol] for symbol, quantity in quantities.items())
            peak_equity = max(peak_equity, equity)
            gross = sum(abs(quantity * latest_prices[symbol]) for symbol, quantity in quantities.items())
            position_rows.append({
                "run_id": session_id, "timestamp": session_timestamp, "symbol": "__PORTFOLIO__",
                "quantity": 0.0, "market_value": equity - cash, "cash": cash, "equity": equity,
                "gross_exposure": gross / max(equity, 1e-12), "daily_pnl": equity - daily_start_equity,
            })
            position_rows.extend({
                "run_id": session_id, "timestamp": session_timestamp, "symbol": symbol,
                "quantity": quantity, "market_value": quantity * latest_prices[symbol],
                "cash": None, "equity": None,
                "gross_exposure": abs(quantity * latest_prices[symbol]) / max(equity, 1e-12),
                "daily_pnl": None,
            } for symbol, quantity in quantities.items())

        if not dates:
            equity = opening_equity
            with self.db.transaction():
                self._persist_run_state(
                    session_id, strategy_name, universe_snapshot_id, timeframe, parameters,
                    watermark, equity, len(quantities), starting_capital=starting_capital,
                )
                summary = self._reconcile(session_id, as_of, [], [], equity - starting_capital, "no new eligible session")
            return ForwardPortfolioPaperResult(
                session_id, "NO_NEW_SESSION", strategy_name, universe_snapshot_id, timeframe,
                0, (), (), cash, quantities, equity, self._pending_timestamp(pending), summary,
            )

        final_timestamp = dates[-1]
        equity = cash + sum(quantity * latest_prices[symbol] for symbol, quantity in quantities.items())
        with self.db.transaction():
            self.db._replace_rows("paper_portfolio_sessions", [{
                **state, "cash": cash, "peak_equity": peak_equity,
                "daily_start_date": daily_start_date, "daily_start_equity": daily_start_equity,
                "last_processed_timestamp": final_timestamp, "status": "ACTIVE", "updated_at": now,
            }])
            self._replace_holdings(
                session_id, quantities, average_cost, entry_timestamps, entry_reasons,
                entry_cost_pools, entry_execution_cost_pools, now,
            )
            self._save_pending(session_id, pending, now)
            self.db.log_strategy_orders(all_orders)
            self.db.log_strategy_fills(all_fills)
            self.db._replace_rows("trade_attribution", all_attribution)
            self.db._replace_rows("trade_round_trips", all_round_trips)
            self.db._replace_rows("fill_cost_components", all_costs)
            self.db._replace_rows("portfolio_rebalances", all_rebalances)
            self.db._replace_rows("portfolio_positions", position_rows)
            for decision in all_risk:
                self.db.log_risk_decision(decision.storage_payload(run_id=session_id))
            self._persist_run_state(
                session_id, strategy_name, universe_snapshot_id, timeframe, parameters,
                final_timestamp, equity, len(quantities), starting_capital=starting_capital,
            )
            summary = self._reconcile(
                session_id, as_of, all_orders, all_fills, equity - starting_capital,
                "forward-only synchronized portfolio paper reconciliation",
            )
        return ForwardPortfolioPaperResult(
            session_id, "PROCESSED", strategy_name, universe_snapshot_id, timeframe,
            len(dates), tuple(all_orders), tuple(all_fills), cash, quantities, equity,
            self._pending_timestamp(pending), summary,
        )

    def _completed_panel(self, panel: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
        frame = panel.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        local = frame["timestamp"].dt.tz_convert(self.calendar.zone)
        completed = local.map(
            lambda value: self.calendar.is_trading_day(value.date())
            and self.calendar.session_bounds(value.date()).end <= as_of.astimezone(self.calendar.zone)
        )
        return frame.loc[completed.to_numpy()].reset_index(drop=True)

    def _risk_adjust_targets(
        self,
        targets: pd.DataFrame,
        day: pd.DataFrame,
        quantities: dict[str, float],
        cash: float,
        prices: dict[str, float],
        capital: float,
        daily_start_equity: float,
        peak_equity: float,
    ) -> tuple[pd.DataFrame, list[RiskDecision]]:
        adjusted = targets.copy()
        equity = cash + sum(quantity * prices.get(symbol, 0.0) for symbol, quantity in quantities.items())
        target_weights = dict(zip(adjusted["symbol"].astype(str), adjusted["target_weight"].astype(float)))
        current_gross = sum(
            min(abs(quantity * prices.get(symbol, 0.0)), target_weights.get(symbol, 0.0) * equity)
            for symbol, quantity in quantities.items()
        )
        decisions: list[RiskDecision] = []
        for symbol, quantity in quantities.items():
            current_notional = abs(quantity * prices.get(symbol, 0.0))
            target_notional = target_weights.get(symbol, 0.0) * equity
            reduction = max(current_notional - target_notional, 0.0)
            if reduction > 0:
                decisions.append(RiskDecision(
                    symbol=symbol, action=RiskAction.PASS,
                    requested_notional=reduction, approved_notional=reduction,
                    reasons=["risk_reducing_exit"], policy=self.risk_engine.policy,
                ))
        for index, row in adjusted.sort_values("rank", na_position="last").iterrows():
            symbol = str(row["symbol"])
            if symbol not in day.index:
                adjusted.loc[index, "target_weight"] = 0.0
                continue
            price = float(day.loc[symbol, "open"])
            current_notional = quantities.get(symbol, 0.0) * price
            requested_delta = max(float(row["target_weight"]) * equity - current_notional, 0.0)
            if requested_delta <= 0:
                continue
            decision = self.risk_engine.evaluate(TradeProposal(
                symbol=symbol,
                requested_notional=requested_delta,
                capital=capital,
                current_position_notional=current_notional,
                current_gross_exposure=current_gross,
                daily_pnl=equity - daily_start_equity,
                daily_turnover_crore=max(float(day.loc[symbol, "volume"] if (symbol in day.index and "volume" in day.columns) else 0.0) * price / 10_000_000, 15.0),
                estimated_portfolio_var_pct=0.01,
                current_sector_exposure=sum(
                    abs(quantities.get(s, 0.0) * prices.get(s, 0.0))
                    for s in quantities
                    if (s in day.index and symbol in day.index and "sector" in day.columns and day.loc[s, "sector"] == day.loc[symbol, "sector"])
                ) if ("sector" in day.columns and symbol in day.index) else 0.0,
            ))
            decisions.append(decision)
            if decision.action == RiskAction.REJECT:
                adjusted.loc[index, "target_weight"] = current_notional / max(equity, 1e-12)
            else:
                adjusted.loc[index, "target_weight"] = (
                    current_notional + decision.approved_notional
                ) / max(equity, 1e-12)
                current_gross += decision.approved_notional
        return adjusted, decisions

    def _load_state(self, session_id: str) -> dict[str, Any] | None:
        frame = self.db.conn.execute(
            "SELECT * FROM paper_portfolio_sessions WHERE session_id = ?", [session_id],
        ).df()
        return frame.iloc[0].to_dict() if not frame.empty else None

    def _load_holdings(self, session_id: str) -> dict[str, dict[str, Any]]:
        frame = self.db.conn.execute(
            "SELECT * FROM paper_portfolio_holdings WHERE session_id = ?", [session_id],
        ).df()
        return {str(row["symbol"]): row.to_dict() for _, row in frame.iterrows()}

    def _load_pending(self, session_id: str) -> pd.DataFrame:
        frame = self.db.conn.execute(
            "SELECT * FROM paper_portfolio_pending_targets WHERE session_id = ?", [session_id],
        ).df()
        if frame.empty:
            return frame
        return frame.rename(columns={"signal_timestamp": "timestamp"})

    def _save_pending(self, session_id: str, targets: pd.DataFrame, now: datetime) -> None:
        self.db.conn.execute("DELETE FROM paper_portfolio_pending_targets WHERE session_id = ?", [session_id])
        if targets.empty:
            return
        rows = []
        for row in targets.to_dict(orient="records"):
            rows.append({
                "session_id": session_id, "symbol": str(row["symbol"]),
                "signal_timestamp": row["timestamp"], "target_weight": float(row["target_weight"]),
                "signal": str(row.get("signal", "FLAT")), "reason": str(row.get("reason", "")),
                "score": row.get("score"), "rank": row.get("rank"),
                "feature_snapshot": row.get("feature_snapshot"), "created_at": now,
            })
        self.db._replace_rows("paper_portfolio_pending_targets", rows)

    def _replace_holdings(
        self,
        session_id: str,
        quantities: dict[str, float],
        average_cost: dict[str, float],
        entry_timestamps: dict[str, pd.Timestamp],
        entry_reasons: dict[str, str],
        entry_cost_pools: dict[str, float],
        entry_execution_cost_pools: dict[str, float],
        now: datetime,
    ) -> None:
        self.db.conn.execute("DELETE FROM paper_portfolio_holdings WHERE session_id = ?", [session_id])
        self.db._replace_rows("paper_portfolio_holdings", [{
            "session_id": session_id, "symbol": symbol, "quantity": quantity,
            "average_cost": average_cost[symbol], "entry_timestamp": entry_timestamps.get(symbol),
            "entry_reason": entry_reasons.get(symbol), "entry_cost_pool": entry_cost_pools.get(symbol, 0.0),
            "entry_execution_cost_pool": entry_execution_cost_pools.get(symbol, 0.0),
            "updated_at": now,
        } for symbol, quantity in quantities.items()])

    @staticmethod
    def _targets_at_or_before(signals: pd.DataFrame, timestamp: pd.Timestamp) -> pd.DataFrame:
        eligible = signals[signals["timestamp"] <= timestamp]
        if eligible.empty:
            return eligible
        latest = eligible["timestamp"].max()
        return eligible[eligible["timestamp"] == latest].copy()

    @staticmethod
    def _pending_timestamp(targets: pd.DataFrame) -> datetime | None:
        if targets.empty:
            return None
        return pd.Timestamp(targets["timestamp"].max()).to_pydatetime()

    @staticmethod
    def _latest_prices(panel: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, float]:
        prior = panel[panel["timestamp"] <= timestamp].sort_values("timestamp").groupby("symbol").tail(1)
        return dict(zip(prior["symbol"].astype(str), prior["close"].astype(float)))

    def _persist_run_state(
        self,
        session_id: str,
        strategy_name: str,
        universe_snapshot_id: str,
        timeframe: str,
        parameters: dict[str, Any],
        timestamp: pd.Timestamp,
        equity: float,
        holdings_count: int,
        starting_capital: float = 100_000.0,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.db._replace_rows("strategy_runs", [{
            "run_id": session_id, "strategy_name": strategy_name, "asset_class": "INDIA_EQUITY",
            "symbol": f"PORTFOLIO:{universe_snapshot_id}", "timeframe": timeframe,
            "mode": "paper-forward", "parameters_json": json.dumps(parameters, sort_keys=True),
            "data_hash": hashlib.sha256(str(timestamp).encode()).hexdigest(), "status": "ACTIVE",
            "started_at": now, "finished_at": None,
            "notes": "Forward-only synchronized paper portfolio; historical orders were not replayed.",
            "starting_capital": starting_capital,
        }])
        self.db._replace_rows("strategy_metrics", [
            {"run_id": session_id, "metric_name": "current_equity", "metric_value": equity},
            {"run_id": session_id, "metric_name": "current_holdings", "metric_value": holdings_count},
        ])

    def _reconcile(
        self,
        session_id: str,
        as_of: datetime,
        orders: list[dict[str, Any]],
        fills: list[dict[str, Any]],
        pnl: float,
        notes: str,
    ) -> dict[str, Any]:
        summary = {
            "run_id": session_id, "trade_date": as_of.date(), "expected_orders": len(orders),
            "submitted_orders": len(orders), "filled_orders": len(fills),
            "rejected_orders": sum(order["status"] == "REJECTED" for order in orders),
            "pnl": pnl, "drift": 0.0, "notes": notes,
        }
        self.db.log_paper_reconciliation([summary])
        return summary

    def _session_id(
        self,
        strategy: str,
        version: str,
        approved_run_id: str,
        snapshot: str,
        benchmark: str,
        timeframe: str,
        parameters: dict[str, Any],
        capital: float,
    ) -> str:
        payload = json.dumps({
            "strategy": strategy, "version": version, "approved_run_id": approved_run_id,
            "snapshot": snapshot, "benchmark": benchmark, "timeframe": timeframe,
            "parameters": parameters, "capital": capital,
            "cost_schedule": self.cost_schedule.__dict__,
            "risk_policy": self.risk_engine.policy.model_dump(),
        }, sort_keys=True, default=str)
        return f"paper-forward:{strategy}:PORTFOLIO:{hashlib.sha256(payload.encode()).hexdigest()[:12]}"
