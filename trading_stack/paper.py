"""Stateful forward-only paper sessions."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from risk.engine import RiskEngine
from risk.models import RiskAction, RiskDecision, TradeProposal
from storage import DuckDBManager
from trading_stack.backtest import ExecutionModel, PaperBroker
from trading_stack.calendars import MarketCalendar
from trading_stack.domain import (
    OpeningTickObservation,
    OrderSide,
    PaperExecutionMode,
)
from trading_stack.features import FeatureFactory
from trading_stack.strategies import StrategyRegistry


@dataclass(frozen=True)
class ForwardPaperResult:
    session_id: str
    status: str
    strategy_name: str
    symbol: str
    timeframe: str
    processed_bars: int
    orders: tuple[dict[str, Any], ...]
    fills: tuple[dict[str, Any], ...]
    cash: float
    quantity: float
    equity: float
    pending_signal_timestamp: datetime | None
    paper_summary: dict[str, Any]


class ForwardPaperSessionEngine:
    """Execute only targets created before a newly observed eligible bar."""

    def __init__(
        self,
        db: DuckDBManager,
        *,
        calendar: MarketCalendar,
        risk_engine: RiskEngine,
        feature_factory: FeatureFactory | None = None,
        execution_model: ExecutionModel | None = None,
    ) -> None:
        self.db = db
        self.calendar = calendar
        self.risk_engine = risk_engine
        self.feature_factory = feature_factory or FeatureFactory()
        self.execution_model = execution_model or ExecutionModel()

    def run(
        self,
        *,
        strategy_name: str,
        approved_run_id: str,
        symbol: str,
        timeframe: str,
        parameters: dict[str, Any] | None = None,
        starting_capital: float = 100_000.0,
        as_of: datetime | None = None,
        execution_mode: str = "EOD_BATCH",
        open_tick_price: float | None = None,
        open_tick_timestamp: datetime | None = None,
        opening_observation: OpeningTickObservation | None = None,
    ) -> ForwardPaperResult:
        parameters = parameters or {}
        as_of = as_of or datetime.now(timezone.utc)
        bars = self.db.get_candles(symbol, timeframe)
        completed = self._completed_bars(bars, timeframe, as_of)
        if completed.empty:
            raise ValueError(f"No completed eligible bars for {symbol} {timeframe}.")
        features = self.feature_factory.build(completed, timezone_name=self.calendar.spec.timezone)
        strategy = StrategyRegistry.create(strategy_name, **parameters)
        signals = strategy.generate_signals(features).copy()
        signals["timestamp"] = pd.to_datetime(signals["timestamp"], utc=True)
        session_id = self._session_id(
            strategy_name, strategy.metadata.version, approved_run_id, symbol, timeframe, parameters,
            starting_capital, self.execution_model, self.risk_engine.policy,
        )
        state = self._load_state(session_id)
        latest_timestamp = pd.Timestamp(completed["timestamp"].max()).tz_convert("UTC")
        if state is None:
            pending = self._signal_at_or_before(signals, latest_timestamp)
            now = pd.Timestamp(as_of).tz_convert("UTC").to_pydatetime()
            latest_session_date = latest_timestamp.tz_convert(self.calendar.zone).date()
            with self.db.transaction():
                self._save_state({
                    "session_id": session_id, "approved_run_id": approved_run_id,
                    "strategy_name": strategy_name,
                    "strategy_version": strategy.metadata.version, "symbol": symbol,
                    "timeframe": timeframe, "parameters_json": json.dumps(parameters, sort_keys=True),
                    "starting_capital": starting_capital, "cash": starting_capital,
                    "quantity": 0.0, "average_cost": 0.0,
                    "entry_timestamp": None, "entry_reason": None, "entry_cost_pool": 0.0,
                    "entry_execution_cost_pool": 0.0,
                    "peak_equity": starting_capital, "daily_start_date": latest_session_date,
                    "daily_start_equity": starting_capital,
                    "last_processed_timestamp": latest_timestamp, "status": "ACTIVE",
                    "created_at": now, "updated_at": now,
                })
                self._save_pending(session_id, pending, now)
                self._persist_run_state(session_id, strategy_name, symbol, timeframe, parameters, latest_timestamp, starting_capital, 0.0)
                summary = self._reconcile(session_id, as_of, [], [], 0.0, "forward session bootstrapped; no historical orders replayed")
            return ForwardPaperResult(
                session_id, "BOOTSTRAPPED", strategy_name, symbol, timeframe, 0, (), (),
                starting_capital, 0.0, starting_capital,
                pd.Timestamp(pending["timestamp"]).to_pydatetime() if pending else None, summary,
            )

        watermark = pd.Timestamp(state["last_processed_timestamp"])
        if watermark.tzinfo is None:
            watermark = watermark.tz_localize("UTC")
        else:
            watermark = watermark.tz_convert("UTC")
        new_bars = completed[pd.to_datetime(completed["timestamp"], utc=True) > watermark].copy()
        pending = self._load_pending(session_id)
        if new_bars.empty:
            equity = float(state["cash"]) + float(state["quantity"]) * float(completed.iloc[-1]["close"])
            with self.db.transaction():
                self._persist_run_state(session_id, strategy_name, symbol, timeframe, parameters, latest_timestamp, equity, float(state["quantity"]))
                summary = self._reconcile(session_id, as_of, [], [], equity - starting_capital, "no new eligible bar")
            return ForwardPaperResult(
                session_id, "NO_NEW_BAR", strategy_name, symbol, timeframe, 0, (), (),
                float(state["cash"]), float(state["quantity"]), equity,
                pd.Timestamp(pending["signal_timestamp"]).to_pydatetime() if pending else None, summary,
            )

        cash = float(state["cash"])
        quantity = float(state["quantity"])
        average_cost = float(state["average_cost"])
        entry_timestamp = (
            pd.Timestamp(state["entry_timestamp"])
            if pd.notna(state.get("entry_timestamp")) else None
        )
        entry_reason = str(state["entry_reason"]) if state.get("entry_reason") is not None else None
        entry_cost_pool = float(state.get("entry_cost_pool") or 0.0)
        entry_execution_cost_pool = float(state.get("entry_execution_cost_pool") or 0.0)
        opening_equity = cash + quantity * float(new_bars.iloc[0]["open"])
        peak_equity = max(float(state.get("peak_equity") or starting_capital), opening_equity)
        state_day = state.get("daily_start_date")
        daily_start_equity = float(state.get("daily_start_equity") or opening_equity)
        daily_start_date = pd.Timestamp(state_day).date() if state_day is not None else None
        all_orders: list[dict[str, Any]] = []
        all_fills: list[dict[str, Any]] = []
        attribution: list[dict[str, Any]] = []
        round_trips: list[dict[str, Any]] = []
        risk_decisions: list[RiskDecision] = []
        for bar in new_bars.sort_values(by=["timestamp"]).to_dict(orient="records"):
            bar_timestamp = pd.Timestamp(bar["timestamp"]).tz_convert("UTC")
            bar_session_date = bar_timestamp.tz_convert(self.calendar.zone).date()

            if opening_observation is not None:
                obs_ts = pd.Timestamp(opening_observation.timestamp)
                obs_ts = obs_ts.tz_localize("UTC") if obs_ts.tzinfo is None else obs_ts
                if obs_ts.tz_convert(self.calendar.zone).date() == bar_session_date:
                    bar["open_tick_observation"] = opening_observation
            elif open_tick_price is not None:
                if open_tick_timestamp is not None:
                    ts_val = pd.Timestamp(open_tick_timestamp)
                    ts_val = ts_val.tz_localize("UTC") if ts_val.tzinfo is None else ts_val
                    if ts_val.tz_convert(self.calendar.zone).date() == bar_session_date:
                        bar["open_tick_price"] = open_tick_price
                        bar["open_tick_timestamp"] = open_tick_timestamp
                elif len(new_bars) == 1 and bar_timestamp == pd.Timestamp(new_bars.iloc[-1]["timestamp"]).tz_convert("UTC"):
                    bar["open_tick_price"] = open_tick_price

            if daily_start_date != bar_session_date:
                daily_start_equity = cash + quantity * float(bar["open"])
                daily_start_date = bar_session_date
            if pending is not None and pd.Timestamp(pending["signal_timestamp"]) < bar_timestamp:
                (
                    cash, quantity, average_cost, entry_timestamp, entry_reason,
                    entry_cost_pool, entry_execution_cost_pool,
                    order, fill, evidence, round_trip, decision,
                ) = self._execute_pending(
                    session_id, symbol, bar, pending, cash, quantity, average_cost, starting_capital,
                    daily_start_equity, peak_equity, entry_timestamp, entry_reason,
                    entry_cost_pool, entry_execution_cost_pool,
                    execution_mode=execution_mode,
                )
                if order:
                    all_orders.append(order)
                if fill:
                    all_fills.append(fill)
                if evidence:
                    attribution.append(evidence)
                if round_trip:
                    round_trips.append(round_trip)
                if decision:
                    risk_decisions.append(decision)

            pending = self._signal_at_or_before(signals, bar_timestamp)
            peak_equity = max(peak_equity, cash + quantity * float(bar["close"]))

        now = pd.Timestamp(as_of).tz_convert("UTC").to_pydatetime()
        last_price = float(new_bars.iloc[-1]["close"])
        equity = cash + quantity * last_price
        with self.db.transaction():
            self._save_state({
                **state, "cash": cash, "quantity": quantity, "average_cost": average_cost,
                "entry_timestamp": entry_timestamp, "entry_reason": entry_reason,
                "entry_cost_pool": entry_cost_pool,
                "entry_execution_cost_pool": entry_execution_cost_pool,
                "peak_equity": peak_equity, "daily_start_date": daily_start_date,
                "daily_start_equity": daily_start_equity,
                "last_processed_timestamp": pd.Timestamp(new_bars["timestamp"].max()),
                "status": "ACTIVE", "updated_at": now,
            })
            self._save_pending(session_id, pending, now)
            self.db.log_strategy_orders(all_orders)
            self.db.log_strategy_fills(all_fills)
            if attribution:
                self.db._replace_rows("trade_attribution", attribution)
            if round_trips:
                self.db._replace_rows("trade_round_trips", round_trips)
            for decision in risk_decisions:
                self.db.log_risk_decision(decision.storage_payload(run_id=session_id))
            cost_rows = self._paper_cost_rows(session_id, all_fills)
            if cost_rows:
                self.db._replace_rows("fill_cost_components", cost_rows)
            self._persist_run_state(session_id, strategy_name, symbol, timeframe, parameters, pd.Timestamp(new_bars["timestamp"].max()), equity, quantity, starting_capital=starting_capital)
            summary = self._reconcile(
                session_id, as_of, all_orders, all_fills, equity - starting_capital,
                "forward-only paper reconciliation",
            )
        return ForwardPaperResult(
            session_id, "PROCESSED", strategy_name, symbol, timeframe, len(new_bars),
            tuple(all_orders), tuple(all_fills), cash, quantity, equity,
            pd.Timestamp(pending["timestamp"]).to_pydatetime() if pending else None, summary,
        )

    def _execute_pending(
        self,
        session_id: str,
        symbol: str,
        bar: dict[str, Any],
        pending: dict[str, Any],
        cash: float,
        quantity: float,
        average_cost: float,
        starting_capital: float,
        daily_start_equity: float,
        peak_equity: float,
        entry_timestamp: pd.Timestamp | None = None,
        entry_reason: str | None = None,
        entry_cost_pool: float = 0.0,
        entry_execution_cost_pool: float = 0.0,
        execution_mode: str = PaperExecutionMode.EOD_BATCH.value,
    ) -> tuple[
        float, float, float, pd.Timestamp | None, str | None, float, float,
        dict[str, Any] | None, dict[str, Any] | None,
        dict[str, Any] | None, dict[str, Any] | None, RiskDecision | None,
    ]:
        source_seq = None
        execution_source = "COMPLETED_BAR"
        if execution_mode == PaperExecutionMode.EOD_BATCH.value or execution_mode == "EOD_BATCH":
            price = float(bar.get("close") or bar.get("price") or 0.0)
            execution_timestamp = pd.Timestamp(bar["timestamp"]).to_pydatetime()
        elif execution_mode == PaperExecutionMode.TRUE_NEXT_OPEN.value or execution_mode == "TRUE_NEXT_OPEN":
            obs = bar.get("open_tick_observation")
            if obs is not None and hasattr(obs, "price"):
                if getattr(obs, "quality_state", "TRUSTED") == "TRUSTED" and float(obs.price) > 0:
                    price = float(obs.price)
                    execution_timestamp = pd.Timestamp(
                        getattr(obs, "received_at_utc", None) or getattr(obs, "timestamp", None)
                    ).to_pydatetime()
                    source_seq = getattr(obs, "sequence_number", None)
                    execution_source = "OBSERVED_TICK"
                else:
                    rejected_order = {
                        "order_id": str(uuid.uuid4()), "run_id": session_id, "symbol": symbol,
                        "side": (OrderSide.BUY if float(pending.get("target_position", 0.0)) > 0 else OrderSide.SELL).value,
                        "quantity": 0.0, "order_type": "MARKET", "time_in_force": "DAY",
                        "status": "REJECTED", "requested_at": pd.Timestamp(bar["timestamp"]).to_pydatetime(), "filled_at": None,
                        "limit_price": None, "stop_price": None, "average_fill_price": None,
                        "slippage_bps": 0.0, "fees": 0.0,
                        "metadata_json": json.dumps({"reason": pending.get("reason", "signal"), "rejection_reason": "MISSED_LIVE_OPEN_PRICE", "execution_mode": execution_mode, "execution_source": "UNAVAILABLE"}),
                    }
                    return (cash, quantity, average_cost, entry_timestamp, entry_reason, entry_cost_pool, entry_execution_cost_pool, rejected_order, None, None, None, None)
            elif bar.get("open_tick_price") is not None and float(bar["open_tick_price"]) > 0:
                price = float(bar["open_tick_price"])
                execution_timestamp = pd.Timestamp(
                    bar.get("open_tick_timestamp") or bar["timestamp"]
                ).to_pydatetime()
                source_seq = bar.get("source_sequence_number")
                execution_source = "OBSERVED_TICK"
            else:
                rejected_order = {
                    "order_id": str(uuid.uuid4()), "run_id": session_id, "symbol": symbol,
                    "side": (OrderSide.BUY if float(pending.get("target_position", 0.0)) > 0 else OrderSide.SELL).value,
                    "quantity": 0.0, "order_type": "MARKET", "time_in_force": "DAY",
                    "status": "REJECTED", "requested_at": pd.Timestamp(bar["timestamp"]).to_pydatetime(), "filled_at": None,
                    "limit_price": None, "stop_price": None, "average_fill_price": None,
                    "slippage_bps": 0.0, "fees": 0.0,
                    "metadata_json": json.dumps({"reason": pending.get("reason", "signal"), "rejection_reason": "MISSED_LIVE_OPEN_PRICE", "execution_mode": execution_mode, "execution_source": "UNAVAILABLE"}),
                }
                return (cash, quantity, average_cost, entry_timestamp, entry_reason, entry_cost_pool, entry_execution_cost_pool, rejected_order, None, None, None, None)
        else:
            price = float(bar.get("close") or bar.get("price") or 0.0)
            execution_timestamp = pd.Timestamp(bar["timestamp"]).to_pydatetime()
        target = max(0.0, min(float(pending["target_position"]), 1.0))
        current_equity = cash + quantity * price
        position_limit = starting_capital * self.risk_engine.policy.max_position_pct
        target_notional = min(target * starting_capital, position_limit)
        unconstrained_quantity = math.floor(target_notional / max(price, 1e-9))
        requested_delta = unconstrained_quantity - quantity
        if abs(requested_delta) < 1e-9:
            return (
                cash, quantity, average_cost, entry_timestamp, entry_reason, entry_cost_pool,
                entry_execution_cost_pool,
                None, None, None, None, None,
            )

        side = OrderSide.BUY if requested_delta > 0 else OrderSide.SELL
        requested_notional = max(abs(requested_delta) * price, 1e-9)
        current_position_notional = quantity * price

        vol = float(bar.get("volume", 0.0) or 0.0)
        daily_turnover_crore = (vol * price / 10_000_000.0) if (vol > 0 and price > 0) else None
        est_var_pct = 1.65 * 0.02 * (requested_notional / max(starting_capital, 1e-9)) if starting_capital > 0 else None

        proposal = TradeProposal(
            symbol=symbol,
            requested_notional=requested_notional,
            capital=starting_capital,
            current_position_notional=current_position_notional,
            order_side=side,
            current_gross_exposure=abs(current_position_notional),
            daily_pnl=current_equity - daily_start_equity,
            current_drawdown=max((peak_equity - current_equity) / max(peak_equity, 1e-9), 0.0),
            open_position_count=1 if quantity > 0 else 0,
            daily_turnover_crore=daily_turnover_crore,
            estimated_portfolio_var_pct=est_var_pct,
            current_sector_exposure=abs(current_position_notional),
        )
        decision = self.risk_engine.evaluate(proposal)

        if decision.action == RiskAction.REJECT:
            approved_delta_qty = 0.0
            desired_quantity = quantity
        else:
            approved_notional = min(decision.approved_notional, requested_notional)
            approved_shares = float(math.floor(approved_notional / max(price, 1e-9)))
            approved_delta_qty = approved_shares if side == OrderSide.BUY else -approved_shares
            desired_quantity = float(quantity + approved_delta_qty)

        delta = desired_quantity - quantity
        broker = PaperBroker(self.execution_model)
        execution = broker.execute_order(
            run_id=session_id, symbol=symbol, side=side, quantity=abs(delta) if abs(delta) >= 1 else abs(requested_delta),
            price=price, timestamp=execution_timestamp,
            metadata={
                "signal_timestamp": str(pending["signal_timestamp"]),
                "reason": pending.get("reason", "signal"),
                "execution_source": execution_source,
                "source_sequence_number": source_seq,
            },
            risk_decision=decision,
            volume=float(bar.get("lagged_adv20") or bar.get("prior_volume") or bar.get("volume") or 0.0),
            close_price=float(bar.get("prior_close") or bar.get("open") or price),
        ) if (abs(delta) >= 1 or decision.action == RiskAction.REJECT) else None
        if execution is None:
            return (
                cash, quantity, average_cost, entry_timestamp, entry_reason, entry_cost_pool,
                entry_execution_cost_pool,
                None, None, None, None, decision,
            )
        order, fill = execution["order"], execution["fill"]

        if fill is None:
            return (
                cash, quantity, average_cost, entry_timestamp, entry_reason, entry_cost_pool,
                entry_execution_cost_pool,
                order, None, None, None, decision,
            )
        fill_quantity, fill_price, fees = float(fill["quantity"]), float(fill["price"]), float(fill["fees"])
        components = execution.get("cost_components") or {}
        total_cost = float(components.get("total_cost", fees))
        execution_drag = sum(float(components.get(name, 0.0)) for name in (
            "spread", "slippage", "market_impact",
        ))
        gross_pnl = 0.0
        round_trip = None
        prior_quantity = quantity
        prior_average_cost = average_cost
        prior_entry_timestamp = entry_timestamp
        prior_entry_reason = entry_reason
        if side == OrderSide.BUY:
            if quantity <= 0:
                entry_timestamp = pd.Timestamp(fill["timestamp"])
                entry_reason = str(pending.get("reason", "signal"))
            old_cost = quantity * average_cost
            quantity += fill_quantity
            cash -= fill_quantity * fill_price + fees
            average_cost = (old_cost + fill_quantity * fill_price) / max(quantity, 1e-9)
            entry_cost_pool += total_cost
            entry_execution_cost_pool += execution_drag
        else:
            executed_pnl = (fill_price - average_cost) * fill_quantity
            allocated_entry_cost = entry_cost_pool * fill_quantity / max(prior_quantity, 1e-9)
            allocated_entry_execution_cost = (
                entry_execution_cost_pool * fill_quantity / max(prior_quantity, 1e-9)
            )
            entry_cost_pool = max(entry_cost_pool - allocated_entry_cost, 0.0)
            entry_execution_cost_pool = max(
                entry_execution_cost_pool - allocated_entry_execution_cost, 0.0,
            )
            gross_pnl = executed_pnl + allocated_entry_execution_cost + execution_drag
            cash += fill_quantity * fill_price - fees
            quantity = max(quantity - fill_quantity, 0.0)
            if prior_entry_timestamp is not None:
                exit_timestamp = pd.Timestamp(fill["timestamp"])
                holding_days = (exit_timestamp - prior_entry_timestamp).total_seconds() / 86_400.0
                round_trip = {
                    "trade_id": str(fill["fill_id"]), "run_id": session_id, "symbol": symbol,
                    "entry_timestamp": prior_entry_timestamp, "exit_timestamp": exit_timestamp,
                    "quantity": fill_quantity, "entry_price": prior_average_cost,
                    "exit_price": fill_price, "entry_cost": allocated_entry_cost,
                    "exit_cost": total_cost, "gross_pnl": gross_pnl,
                    "net_pnl": gross_pnl - allocated_entry_cost - total_cost,
                    "holding_period_days": holding_days,
                    "entry_reason": prior_entry_reason or "ENTRY",
                    "exit_reason": str(pending.get("reason", "signal")),
                    "exit_classification": "SIGNAL_TARGET_CHANGE",
                }
            if quantity == 0:
                average_cost = 0.0
                entry_timestamp = None
                entry_reason = None
                entry_cost_pool = 0.0
                entry_execution_cost_pool = 0.0
        evidence = {
            "run_id": session_id, "timestamp": fill["timestamp"], "symbol": symbol,
            "side": side.value, "reason": str(pending.get("reason", "signal")),
            "realized_pnl": gross_pnl - total_cost, "cost": total_cost, "target_weight": target,
            "quantity": fill_quantity, "price": fill_price,
            "average_cost": prior_average_cost if side == OrderSide.SELL else average_cost,
            "gross_pnl": gross_pnl,
            "entry_timestamp": prior_entry_timestamp if side == OrderSide.SELL else entry_timestamp,
            "holding_period_days": round_trip["holding_period_days"] if round_trip else None,
            "exit_classification": "SIGNAL_TARGET_CHANGE" if side == OrderSide.SELL else "ENTRY",
        }
        return (
            cash, quantity, average_cost, entry_timestamp, entry_reason, entry_cost_pool,
            entry_execution_cost_pool,
            order, fill, evidence, round_trip, decision,
        )

    def _completed_bars(self, bars: pd.DataFrame, timeframe: str, as_of: datetime) -> pd.DataFrame:
        frame = bars.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        local = frame["timestamp"].dt.tz_convert(self.calendar.zone)
        if timeframe == "1d":
            completed = local.map(
                lambda value: self.calendar.is_trading_day(value.date())
                and self.calendar.session_bounds(value.date()).end <= as_of.astimezone(self.calendar.zone)
            )
        else:
            completed = local.map(
                lambda value: self.calendar.is_session_open(value.to_pydatetime())
                and value.to_pydatetime() < as_of.astimezone(self.calendar.zone)
            )
        return frame.loc[completed.to_numpy()].reset_index(drop=True)

    @staticmethod
    def _signal_at_or_before(signals: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, Any] | None:
        eligible = signals[signals["timestamp"] <= timestamp]
        return eligible.iloc[-1].to_dict() if not eligible.empty else None

    def _load_state(self, session_id: str) -> dict[str, Any] | None:
        frame = self.db.conn.execute("SELECT * FROM paper_sessions WHERE session_id = ?", [session_id]).df()
        return frame.iloc[0].to_dict() if not frame.empty else None

    def _load_pending(self, session_id: str) -> dict[str, Any] | None:
        frame = self.db.conn.execute("SELECT * FROM paper_pending_targets WHERE session_id = ?", [session_id]).df()
        return frame.iloc[0].to_dict() if not frame.empty else None

    def _save_state(self, row: dict[str, Any]) -> None:
        self.db._replace_rows("paper_sessions", [row])

    def _save_pending(self, session_id: str, signal: dict[str, Any] | None, now: datetime) -> None:
        if signal is None:
            self.db.conn.execute("DELETE FROM paper_pending_targets WHERE session_id = ?", [session_id])
            return
        self.db._replace_rows("paper_pending_targets", [{
            "session_id": session_id, "signal_timestamp": signal["timestamp"],
            "target_position": float(signal.get("target_position", signal.get("target_weight", 0.0))),
            "signal": str(signal.get("signal", "FLAT")), "reason": str(signal.get("reason", "")),
            "feature_snapshot": signal.get("feature_snapshot"), "created_at": now,
        }])

    @staticmethod
    def _paper_cost_rows(session_id: str, fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for fill in fills:
            try:
                metadata = json.loads(str(fill.get("metadata_json") or "{}"))
            except json.JSONDecodeError:
                continue
            components = metadata.get("cost_components")
            if not components:
                continue
            rows.append({
                "run_id": session_id, "fill_id": fill["fill_id"], "timestamp": fill["timestamp"],
                **components,
            })
        return rows

    def _persist_run_state(
        self,
        session_id: str,
        strategy_name: str,
        symbol: str,
        timeframe: str,
        parameters: dict[str, Any],
        timestamp: pd.Timestamp,
        equity: float,
        quantity: float,
        starting_capital: float = 100_000.0,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.db._replace_rows("strategy_runs", [{
            "run_id": session_id, "strategy_name": strategy_name,
            "asset_class": "INDIA_EQUITY", "symbol": symbol, "timeframe": timeframe,
            "mode": "paper-forward", "parameters_json": json.dumps(parameters, sort_keys=True),
            "data_hash": hashlib.sha256(str(timestamp).encode()).hexdigest(),
            "status": "ACTIVE", "started_at": now, "finished_at": None,
            "notes": "Forward-only paper session; historical bars were not replayed as orders.",
            "starting_capital": starting_capital,
        }])
        self.db._replace_rows("strategy_metrics", [
            {"run_id": session_id, "metric_name": "current_equity", "metric_value": equity},
            {"run_id": session_id, "metric_name": "current_quantity", "metric_value": quantity},
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

    @staticmethod
    def _session_id(
        strategy: str,
        version: str,
        approved_run_id: str,
        symbol: str,
        timeframe: str,
        parameters: dict[str, Any],
        starting_capital: float,
        execution_model: ExecutionModel,
        risk_policy: Any,
    ) -> str:
        execution = {
            name: getattr(execution_model, name)
            for name in execution_model.__dataclass_fields__
        }
        payload = json.dumps(
            [strategy, version, approved_run_id, symbol, timeframe, parameters, starting_capital, execution, risk_policy.model_dump()],
            sort_keys=True,
        )
        return f"paper-forward:{strategy}:{symbol}:{timeframe}:{hashlib.sha256(payload.encode()).hexdigest()[:12]}"
