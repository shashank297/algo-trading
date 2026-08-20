"""Backtesting engines for vectorized and event-driven research."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_stack.domain import AssetClass, BacktestMetrics, OrderSide, OrderStatus, OrderType, StrategyRun, TimeInForce
from trading_stack.calendars import MarketCalendar
from trading_stack.costs import (
    IndianDeliveryCostSchedule,
    UnexecutableOrderError,
)



BacktestResult = StrategyRun


@dataclass(slots=True)
class ExecutionModel:
    """Fill and cost assumptions for a backtest run."""

    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    spread_bps: float = 0.0
    tax_bps: float = 0.0
    financing_bps: float = 0.0
    fill_timing: str = "next_open"
    exit_on_session_close: bool = True
    allow_partial_fills: bool = False
    max_fill_fraction: float = 1.0
    indian_delivery_costs: dict[str, Any] | None = None


class VectorizedBacktester:
    """Fast research engine using vectorized calculations."""

    def __init__(self, execution_model: ExecutionModel | None = None) -> None:
        self.execution_model = execution_model or ExecutionModel(fill_timing="close")

    def run(
        self,
        strategy: Any,
        bars: pd.DataFrame,
        *,
        starting_capital: float = 100_000.0,
        market_asset_class: AssetClass = AssetClass.INDIA_EQUITY,
        symbol: str | None = None,
        timeframe: str = "1d",
        parameters: dict[str, Any] | None = None,
    ) -> BacktestResult:
        return _run_backtest(
            strategy=strategy,
            bars=bars,
            execution_model=self.execution_model,
            starting_capital=starting_capital,
            market_asset_class=market_asset_class,
            symbol=symbol or _default_symbol(bars),
            timeframe=timeframe,
            mode="vectorized",
            parameters=parameters or {},
        )


class EventDrivenBacktester:
    """Replay engine that models order creation and fills bar-by-bar."""

    def __init__(self, execution_model: ExecutionModel | None = None) -> None:
        self.execution_model = execution_model or ExecutionModel()

    def run(
        self,
        strategy: Any,
        bars: pd.DataFrame,
        *,
        starting_capital: float = 100_000.0,
        market_asset_class: AssetClass = AssetClass.INDIA_EQUITY,
        symbol: str | None = None,
        timeframe: str = "1d",
        parameters: dict[str, Any] | None = None,
        result_mode: str = "event-driven",
        max_abs_position: float | None = None,
    ) -> BacktestResult:
        return _run_backtest(
            strategy=strategy,
            bars=bars,
            execution_model=self.execution_model,
            starting_capital=starting_capital,
            market_asset_class=market_asset_class,
            symbol=symbol or _default_symbol(bars),
            timeframe=timeframe,
            mode=result_mode,
            parameters=parameters or {},
            max_abs_position=max_abs_position,
        )


class PaperBroker:
    """Lightweight paper broker that mirrors the execution model."""

    def __init__(self, execution_model: ExecutionModel | None = None) -> None:
        self.execution_model = execution_model or ExecutionModel()
        self.orders: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []

    def execute_order(
        self,
        *,
        run_id: str,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        timestamp: datetime,
        order_type: OrderType = OrderType.MARKET,
        time_in_force: TimeInForce = TimeInForce.DAY,
        metadata: dict[str, Any] | None = None,
        risk_decision: Any | None = None,
        volume: float | None = None,
        close_price: float | None = None,
    ) -> dict[str, Any]:
        """Simulate a paper fill and store the lifecycle."""

        metadata = metadata or {}
        order_id = str(uuid.uuid4())
        if risk_decision is not None and getattr(risk_decision, "action", None) is not None:
            if str(getattr(risk_decision.action, "value", risk_decision.action)) == "REJECT":
                order_row = {
                    "order_id": order_id, "run_id": run_id, "symbol": symbol, "side": side.value,
                    "quantity": float(quantity), "order_type": order_type.value, "time_in_force": time_in_force.value,
                    "status": OrderStatus.REJECTED.value, "requested_at": timestamp, "filled_at": None,
                    "limit_price": None, "stop_price": None, "average_fill_price": None,
                    "slippage_bps": self.execution_model.slippage_bps, "fees": 0.0,
                    "metadata_json": json.dumps({**metadata, "risk": "REJECT"}),
                }
                self.orders.append(order_row)
                return {"order": order_row, "fill": None, "cost_components": None}
            approved_notional = getattr(risk_decision, "approved_notional", None)
            if approved_notional is not None:
                quantity = min(float(quantity), float(approved_notional) / max(price, 1e-9))
        schedule = _indian_schedule(self.execution_model)
        requested_quantity = float(quantity)
        if schedule is not None and volume is not None:
            traded_value = float(volume) * float(close_price or price)
            if traded_value < schedule.minimum_daily_traded_value:
                order_row = {
                    "order_id": order_id, "run_id": run_id, "symbol": symbol, "side": side.value,
                    "quantity": requested_quantity, "order_type": order_type.value, "time_in_force": time_in_force.value,
                    "status": OrderStatus.REJECTED.value, "requested_at": timestamp, "filled_at": None,
                    "limit_price": None, "stop_price": None, "average_fill_price": None,
                    "slippage_bps": schedule.slippage_bps, "fees": 0.0,
                    "metadata_json": json.dumps({**metadata, "rejection_reason": "LIQUIDITY_REJECTION"}),
                }
                self.orders.append(order_row)
                return {"order": order_row, "fill": None, "cost_components": None}
            quantity = min(requested_quantity, float(np.floor(float(volume) * schedule.max_volume_participation)))
        order_row = {
            "order_id": order_id,
            "run_id": run_id,
            "symbol": symbol,
            "side": side.value,
            "quantity": requested_quantity,
            "order_type": order_type.value,
            "time_in_force": time_in_force.value,
            "status": OrderStatus.FILLED.value,
            "requested_at": timestamp,
            "filled_at": timestamp,
            "limit_price": None,
            "stop_price": None,
            "average_fill_price": None,
            "slippage_bps": schedule.slippage_bps if schedule is not None else self.execution_model.slippage_bps,
            "fees": 0.0,
            "metadata_json": json.dumps(metadata),
        }
        participation = float(quantity) / max(float(volume or 0.0), 1.0)
        if schedule is not None:
            try:
                fill_price = schedule.execution_price(price, side, participation)
            except UnexecutableOrderError as err:
                order_row["status"] = OrderStatus.REJECTED.value
                order_row["filled_at"] = None
                order_row["metadata_json"] = json.dumps({**metadata, "rejection_reason": err.reason_code, "estimated_drag_bps": err.estimated_drag_bps})
                self.orders.append(order_row)
                return {"order": order_row, "fill": None, "cost_components": None}
            breakdown = schedule.calculate(abs(quantity * fill_price), side, participation)
            fee = breakdown.statutory_and_broker_fees
            components = {**asdict(breakdown), "total_cost": breakdown.total}
        else:
            fill_price = _apply_slippage(price, side, self.execution_model.slippage_bps + self.execution_model.spread_bps)
            fee = abs(quantity * fill_price) * (self.execution_model.fee_bps + self.execution_model.tax_bps) / 10_000.0
            components = None

        if quantity <= 0:
            order_row["status"] = OrderStatus.REJECTED.value
            order_row["filled_at"] = None
            order_row["metadata_json"] = json.dumps({**metadata, "rejection_reason": "VOLUME_CAP_REJECTION"})
            self.orders.append(order_row)
            return {"order": order_row, "fill": None, "cost_components": None}
        if quantity < requested_quantity:
            order_row["status"] = OrderStatus.PARTIALLY_FILLED.value
        order_row["average_fill_price"] = fill_price
        order_row["fees"] = fee
        fill_row = {
            "fill_id": str(uuid.uuid4()),
            "order_id": order_id,
            "run_id": run_id,
            "symbol": symbol,
            "timestamp": timestamp,
            "quantity": float(quantity),
            "price": float(fill_price),
            "side": side.value,
            "fill_type": "PAPER",
            "fees": float(fee),
            "slippage_bps": self.execution_model.slippage_bps,
            "metadata_json": json.dumps({**metadata, "cost_components": components}),
        }
        self.orders.append(order_row)
        self.fills.append(fill_row)
        return {"order": order_row, "fill": fill_row, "cost_components": components}

    def reconcile(self, *, run_id: str, trade_date: datetime, expected_pnl: float = 0.0) -> dict[str, Any]:
        """Summarize the day's order flow and PnL drift."""

        submitted_orders = len(self.orders)
        filled_orders = len(self.fills)
        rejected_orders = sum(str(order.get("status", "")) == OrderStatus.REJECTED.value for order in self.orders)
        return {
            "run_id": run_id,
            "trade_date": trade_date.date(),
            "expected_orders": submitted_orders,
            "submitted_orders": submitted_orders,
            "filled_orders": filled_orders,
            "rejected_orders": rejected_orders,
            "pnl": expected_pnl,
            "drift": 0.0,
            "notes": "paper broker reconciliation",
        }


def _run_backtest(
    *,
    strategy: Any,
    bars: pd.DataFrame,
    execution_model: ExecutionModel,
    starting_capital: float,
    market_asset_class: AssetClass,
    symbol: str,
    timeframe: str,
    mode: str,
    parameters: dict[str, Any],
    max_abs_position: float | None = None,
) -> BacktestResult:
    if bars.empty:
        raise ValueError("Cannot backtest an empty bar frame.")

    frame = bars.copy().sort_values("timestamp").reset_index(drop=True)
    if "adjustment" in frame.columns and frame["adjustment"].dropna().nunique() > 1:
        raise ValueError("Backtests cannot mix adjusted and unadjusted price series.")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    if frame.empty:
        raise ValueError("No valid rows remain after cleaning the input frame.")

    strategy.validate()
    signals = strategy.generate_signals(frame).sort_values("timestamp").reset_index(drop=True)
    if "target_position" not in signals:
        raise ValueError("Strategy signals must contain target_position.")
    signals["target_position"] = strategy.position_sizing(signals, portfolio={})
    constraints = strategy.risk_constraints(portfolio={})
    max_position = float(constraints.get("max_abs_target_position", 1.0))
    if max_abs_position is not None:
        if max_abs_position <= 0:
            raise ValueError("max_abs_position must be positive.")
        max_position = min(max_position, float(max_abs_position))
    signals["target_position"] = signals["target_position"].clip(-max_position, max_position)
    merged = frame.merge(signals[["timestamp", "target_position", "signal", "reason"]], on="timestamp", how="left")
    merged["target_position"] = merged["target_position"].fillna(0.0).ffill().fillna(0.0)
    merged["signal"] = merged["signal"].fillna("FLAT")
    merged["reason"] = merged["reason"].fillna("")

    data_hash = _hash_frame(frame)
    effective_parameters = {**dict(getattr(strategy, "parameters", {})), **parameters}
    run_id = _build_run_id(
        strategy.name, symbol, timeframe, mode, data_hash,
        effective_parameters, execution_model,
    )
    positions = merged["target_position"].astype("float64")
    if mode != "vectorized":
        orders, fills, equity_curve = _run_event_replay(
            merged,
            positions=positions,
            execution_model=execution_model,
            run_id=run_id,
            mode=mode,
            starting_capital=starting_capital,
            timeframe=timeframe,
            market_asset_class=market_asset_class,
        )
        metrics = _compute_metrics(
            equity_curve=equity_curve,
            net_returns=equity_curve["net_return"],
            fills=fills,
            execution_model=execution_model,
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        return BacktestResult(
            run_id=run_id,
            strategy_name=strategy.name,
            asset_class=market_asset_class,
            symbol=symbol,
            timeframe=timeframe,
            mode=mode,
            parameters=effective_parameters,
            data_hash=data_hash,
            metrics=metrics,
            signals=signals,
            orders=orders,
            fills=fills,
            equity_curve=equity_curve,
        )

    close_returns = merged["close"].pct_change().fillna(0.0)
    gross_returns = positions.shift(1).fillna(0.0) * close_returns
    turnover = positions.diff().abs().fillna(positions.abs())
    cost_bps = (
        execution_model.fee_bps + execution_model.slippage_bps + execution_model.spread_bps
        + execution_model.tax_bps + execution_model.financing_bps
    )
    net_returns = gross_returns - turnover * cost_bps / 10_000.0
    equity_curve = merged[["timestamp", "close"]].copy()
    equity_curve["position"] = positions
    equity_curve["bar_return"] = close_returns
    equity_curve["gross_return"] = gross_returns
    equity_curve["net_return"] = net_returns
    equity_curve["equity"] = starting_capital * (1 + net_returns).cumprod()
    equity_curve["drawdown"] = equity_curve["equity"] / equity_curve["equity"].cummax() - 1.0

    orders, fills = _build_lifecycle(
        merged,
        positions=positions,
        execution_model=execution_model,
        run_id=run_id,
        mode=mode,
        starting_capital=starting_capital,
    )
    metrics = _compute_metrics(
        equity_curve=equity_curve,
        net_returns=net_returns,
        fills=fills,
        execution_model=execution_model,
        timeframe=timeframe,
        starting_capital=starting_capital,
    )
    return BacktestResult(
        run_id=run_id,
        strategy_name=strategy.name,
        asset_class=market_asset_class,
        symbol=symbol,
        timeframe=timeframe,
        mode=mode,
        parameters=effective_parameters,
        data_hash=data_hash,
        metrics=metrics,
        signals=signals,
        orders=orders,
        fills=fills,
        equity_curve=equity_curve,
    )


def _run_event_replay(
    frame: pd.DataFrame,
    *,
    positions: pd.Series,
    execution_model: ExecutionModel,
    run_id: str,
    mode: str,
    starting_capital: float,
    timeframe: str,
    market_asset_class: AssetClass,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Replay target changes into actual fills, cash, holdings, and equity."""

    orders: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    cash = float(starting_capital)
    quantity = 0.0
    cumulative_cost = 0.0
    previous_equity = float(starting_capital)
    previous_gross_equity = float(starting_capital)
    pending_target: float | None = None
    pending_time: datetime | None = None
    intraday = str(timeframe).lower().endswith(("m", "h"))
    zone = ZoneInfo("Asia/Kolkata" if market_asset_class in {AssetClass.INDIA_EQUITY, AssetClass.INDIA_INDEX} else "UTC")
    indian_schedule = _indian_schedule(execution_model)

    def execute(target: float, source_price: float, source_close: float, source_volume: float, fill_time: datetime, requested_at: datetime) -> None:
        nonlocal cash, quantity, cumulative_cost
        fill_price_hint = max(float(source_price), 1e-9)
        desired_quantity = target * starting_capital / fill_price_hint
        requested_quantity = desired_quantity - quantity
        if abs(requested_quantity) <= 1e-12:
            return
        side = OrderSide.BUY if requested_quantity > 0 else OrderSide.SELL
        requested_abs = abs(requested_quantity)
        initial_participation = requested_abs / max(source_volume, 1.0)
        order_id = str(uuid.uuid4())
        try:
            if indian_schedule is not None:
                fill_price = indian_schedule.execution_price(fill_price_hint, side, initial_participation)
            else:
                fill_price = _fill_price(fill_price_hint, side, execution_model.slippage_bps + execution_model.spread_bps)
        except UnexecutableOrderError as exc:
            orders.append({
                "order_id": order_id, "run_id": run_id, "symbol": frame.iloc[0].get("symbol", ""),
                "side": side.value, "quantity": float(requested_abs), "order_type": OrderType.MARKET.value,
                "time_in_force": TimeInForce.DAY.value, "status": OrderStatus.REJECTED.value,
                "requested_at": requested_at, "filled_at": None, "limit_price": None, "stop_price": None,
                "average_fill_price": None, "slippage_bps": indian_schedule.slippage_bps if indian_schedule else 0.0, "fees": 0.0,
                "metadata_json": json.dumps({"mode": mode, "rejection_reason": exc.reason_code, "estimated_drag_bps": exc.estimated_drag_bps}),
            })
            return

        desired_quantity = target * starting_capital / max(fill_price, 1e-9)
        requested_quantity = desired_quantity - quantity
        requested_abs = abs(requested_quantity)
        filled_quantity = requested_abs
        if indian_schedule is not None:
            if source_close * source_volume < indian_schedule.minimum_daily_traded_value:
                orders.append({
                    "order_id": order_id, "run_id": run_id, "symbol": frame.iloc[0].get("symbol", ""),
                    "side": side.value, "quantity": float(requested_abs), "order_type": OrderType.MARKET.value,
                    "time_in_force": TimeInForce.DAY.value, "status": OrderStatus.REJECTED.value,
                    "requested_at": requested_at, "filled_at": None, "limit_price": None, "stop_price": None,
                    "average_fill_price": None, "slippage_bps": indian_schedule.slippage_bps, "fees": 0.0,
                    "metadata_json": json.dumps({"mode": mode, "rejection_reason": "LIQUIDITY_REJECTION"}),
                })
                return
            filled_quantity = min(
                filled_quantity,
                float(np.floor(source_volume * indian_schedule.max_volume_participation)),
            )
            if market_asset_class == AssetClass.INDIA_EQUITY:
                filled_quantity = float(np.floor(filled_quantity))
        if execution_model.allow_partial_fills:
            filled_quantity *= min(max(execution_model.max_fill_fraction, 0.0), 1.0)
            if market_asset_class == AssetClass.INDIA_EQUITY:
                filled_quantity = float(np.floor(filled_quantity))
        participation = filled_quantity / max(source_volume, 1.0)
        if indian_schedule is not None:
            try:
                fill_price = indian_schedule.execution_price(fill_price_hint, side, participation)
            except UnexecutableOrderError as exc:
                orders.append({
                    "order_id": order_id, "run_id": run_id, "symbol": frame.iloc[0].get("symbol", ""),
                    "side": side.value, "quantity": float(requested_abs), "order_type": OrderType.MARKET.value,
                    "time_in_force": TimeInForce.DAY.value, "status": OrderStatus.REJECTED.value,
                    "requested_at": requested_at, "filled_at": None, "limit_price": None, "stop_price": None,
                    "average_fill_price": None, "slippage_bps": indian_schedule.slippage_bps, "fees": 0.0,
                    "metadata_json": json.dumps({"mode": mode, "rejection_reason": exc.reason_code, "estimated_drag_bps": exc.estimated_drag_bps}),
                })
                return
            breakdown = indian_schedule.calculate(filled_quantity * fill_price, side, participation)
            fee = breakdown.statutory_and_broker_fees
            cost_components = {**asdict(breakdown), "total_cost": breakdown.total}
        else:
            fee_rate = (execution_model.fee_bps + execution_model.tax_bps) / 10_000.0
            fee = filled_quantity * fill_price * fee_rate
            cost_components = None
        if side == OrderSide.BUY and quantity >= 0:
            affordable = max(cash - fee, 0.0) / max(fill_price, 1e-9)
            if market_asset_class == AssetClass.INDIA_EQUITY:
                affordable = float(np.floor(affordable))
            filled_quantity = min(filled_quantity, affordable)
        if filled_quantity <= 0:
            if indian_schedule is not None:
                orders.append({
                    "order_id": order_id, "run_id": run_id, "symbol": frame.iloc[0].get("symbol", ""),
                    "side": side.value, "quantity": float(requested_abs), "order_type": OrderType.MARKET.value,
                    "time_in_force": TimeInForce.DAY.value, "status": OrderStatus.REJECTED.value,
                    "requested_at": requested_at, "filled_at": None, "limit_price": None, "stop_price": None,
                    "average_fill_price": None, "slippage_bps": indian_schedule.slippage_bps, "fees": 0.0,
                    "metadata_json": json.dumps({"mode": mode, "rejection_reason": "VOLUME_OR_CASH_REJECTION"}),
                })
            return
        if indian_schedule is not None:
            participation = filled_quantity / max(source_volume, 1.0)
            fill_price = indian_schedule.execution_price(fill_price_hint, side, participation)
            breakdown = indian_schedule.calculate(filled_quantity * fill_price, side, participation)
            fee = breakdown.statutory_and_broker_fees
            cost_components = {**asdict(breakdown), "total_cost": breakdown.total}
        else:
            fee = filled_quantity * fill_price * fee_rate
        order_id = str(uuid.uuid4())

        status = OrderStatus.PARTIALLY_FILLED if filled_quantity + 1e-12 < requested_abs else OrderStatus.FILLED
        orders.append({
            "order_id": order_id, "run_id": run_id, "symbol": frame.iloc[0].get("symbol", ""),
            "side": side.value, "quantity": float(requested_abs), "order_type": OrderType.MARKET.value,
            "time_in_force": TimeInForce.DAY.value, "status": status.value,
            "requested_at": requested_at, "filled_at": fill_time, "limit_price": None,
            "stop_price": None, "average_fill_price": fill_price,
            "slippage_bps": indian_schedule.slippage_bps if indian_schedule is not None else execution_model.slippage_bps, "fees": fee,
            "metadata_json": json.dumps({"mode": mode, "target_position": target, "cost_components": cost_components}),
        })
        fills.append({
            "fill_id": str(uuid.uuid4()), "order_id": order_id, "run_id": run_id,
            "symbol": frame.iloc[0].get("symbol", ""), "timestamp": fill_time,
            "quantity": float(filled_quantity), "price": float(fill_price), "side": side.value,
            "fill_type": "PAPER" if mode == "paper" else "BACKTEST", "fees": float(fee),
            "slippage_bps": indian_schedule.slippage_bps if indian_schedule is not None else execution_model.slippage_bps,
            "metadata_json": json.dumps({"mode": mode, "cost_components": cost_components}),
        })
        signed_fill = filled_quantity if side == OrderSide.BUY else -filled_quantity
        cash -= signed_fill * fill_price + fee
        quantity += signed_fill
        execution_drag = filled_quantity * abs(fill_price - fill_price_hint)
        cumulative_cost += float(cost_components["total_cost"]) if cost_components else fee + execution_drag

    last_known_close = float(frame.iloc[0].get("close", 1.0))
    last_known_volume = float(frame.iloc[0].get("volume", 1.0))

    for index, row in frame.iterrows():
        timestamp = pd.Timestamp(row["timestamp"])
        fill_time = timestamp.to_pydatetime()
        if pending_target is not None and pending_time is not None:
            # Capacity and liquidity use close and volume known at bar t (signal bar), NOT bar t+1's future volume
            execute(pending_target, float(row["open"]), last_known_close, last_known_volume, fill_time, pending_time)

        is_last = index == len(frame) - 1
        next_session = False
        if intraday and not is_last:
            next_timestamp = pd.Timestamp(frame.iloc[index + 1]["timestamp"])
            next_session = timestamp.tz_convert(zone).date() != next_timestamp.tz_convert(zone).date()
        if execution_model.exit_on_session_close and quantity != 0 and (is_last or next_session):
            execute(0.0, float(row["close"]), float(row["close"]), float(row["volume"]), fill_time, fill_time)

        equity = cash + quantity * float(row["close"])
        gross_equity = equity + cumulative_cost
        curve.append({
            "timestamp": timestamp,
            "close": float(row["close"]),
            "position": quantity * float(row["close"]) / max(equity, 1e-12),
            "gross_return": gross_equity / max(previous_gross_equity, 1e-12) - 1.0,
            "net_return": equity / max(previous_equity, 1e-12) - 1.0,
            "equity": equity,
        })
        previous_equity = equity
        previous_gross_equity = gross_equity
        pending_target = 0.0 if next_session else float(positions.iloc[index])
        pending_time = fill_time
        last_known_close = float(row["close"])
        last_known_volume = float(row["volume"])


    equity_curve = pd.DataFrame(curve)
    equity_curve["drawdown"] = equity_curve["equity"] / equity_curve["equity"].cummax() - 1.0
    return pd.DataFrame(orders), pd.DataFrame(fills), equity_curve


def _build_lifecycle(
    frame: pd.DataFrame,
    *,
    positions: pd.Series,
    execution_model: ExecutionModel,
    run_id: str,
    mode: str,
    starting_capital: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    orders: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    previous_position = 0.0

    for index, row in frame.iterrows():
        desired_position = float(positions.iloc[index])
        if index == len(frame) - 1 and execution_model.exit_on_session_close and desired_position != 0.0:
            desired_position = 0.0

        if desired_position == previous_position:
            continue

        delta = desired_position - previous_position
        order_id = str(uuid.uuid4())
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        order_time = pd.Timestamp(row["timestamp"]).to_pydatetime()
        if execution_model.fill_timing == "next_open" and index + 1 < len(frame):
            fill_row = frame.iloc[index + 1]
            fill_time = pd.Timestamp(fill_row["timestamp"]).to_pydatetime()
            fill_source_price = float(fill_row["open"])
        else:
            fill_time = order_time
            fill_source_price = float(row["close"])
        fill_price = _fill_price(fill_source_price, side, execution_model.slippage_bps + execution_model.spread_bps)
        quantity = abs(delta) * starting_capital / max(fill_price, 1e-9)
        requested_quantity = quantity
        if execution_model.allow_partial_fills:
            quantity = quantity * min(max(execution_model.max_fill_fraction, 0.0), 1.0)
        if quantity <= 0:
            continue
        fee = abs(quantity * fill_price) * (execution_model.fee_bps + execution_model.tax_bps) / 10_000.0
        order_status = OrderStatus.PARTIALLY_FILLED.value if quantity < requested_quantity else OrderStatus.FILLED.value

        orders.append(
            {
                "order_id": order_id,
                "run_id": run_id,
                "symbol": row.get("symbol", ""),
                "side": side.value,
                "quantity": float(quantity),
                "order_type": OrderType.MARKET.value,
                "time_in_force": TimeInForce.DAY.value,
                "status": order_status,
                "requested_at": order_time,
                "filled_at": fill_time,
                "limit_price": None,
                "stop_price": None,
                "average_fill_price": fill_price,
                "slippage_bps": execution_model.slippage_bps,
                "fees": fee,
                "metadata_json": json.dumps({"mode": mode, "delta_position": delta}),
            }
        )
        fills.append(
            {
                "fill_id": str(uuid.uuid4()),
                "order_id": order_id,
                "run_id": run_id,
                "symbol": row.get("symbol", ""),
                "timestamp": fill_time,
                "quantity": float(quantity),
                "price": float(fill_price),
                "side": side.value,
                "fill_type": "PAPER" if mode == "paper" else "BACKTEST",
                "fees": float(fee),
                "slippage_bps": execution_model.slippage_bps,
                "metadata_json": json.dumps({"mode": mode}),
            }
        )
        previous_position = desired_position

    return pd.DataFrame(orders), pd.DataFrame(fills)


def _compute_metrics(
    *,
    equity_curve: pd.DataFrame,
    net_returns: pd.Series,
    fills: pd.DataFrame,
    execution_model: ExecutionModel,
    timeframe: str,
    starting_capital: float,
) -> BacktestMetrics:
    total_return = float(equity_curve["equity"].iloc[-1] / starting_capital - 1.0)
    cagr = _annualized_return(equity_curve["equity"], timeframe, starting_capital)
    sharpe = _sharpe_ratio(net_returns, timeframe)
    max_drawdown = float(equity_curve["drawdown"].min())
    trade_pnls = _completed_trade_pnls(fills)
    trade_count = len(trade_pnls)
    win_rate = float(sum(value > 0 for value in trade_pnls) / trade_count) if trade_count else 0.0
    fees = float(fills["fees"].sum()) if not fills.empty else 0.0
    slippage = float(fills["slippage_bps"].sum()) if not fills.empty else 0.0
    var_95 = float(net_returns.quantile(0.05)) if not net_returns.empty else 0.0
    # CVaR (Expected Shortfall): mean of returns below VaR threshold
    tail = net_returns[net_returns <= var_95] if not net_returns.empty else pd.Series(dtype=float)
    cvar_95 = float(tail.mean()) if not tail.empty else var_95
    
    # Monte Carlo Sharpe Confidence (Bootstrap P(Sharpe > 0))
    mc_sharpe_prob = 0.0
    if len(net_returns) > 30 and net_returns.std(ddof=0) > 0:
        rng = np.random.default_rng(42)
        samples = rng.choice(net_returns.values, size=(1000, len(net_returns)), replace=True)
        means = np.mean(samples, axis=1)
        stds = np.std(samples, axis=1, ddof=0)
        valid = stds > 0
        sharpes = means[valid] / stds[valid]
        if len(sharpes) > 0:
            mc_sharpe_prob = float(np.mean(sharpes > 0))


    return BacktestMetrics(
        total_return=total_return,
        cagr=cagr,
        volatility=float(net_returns.std(ddof=0) * np.sqrt(_annualization_factor(timeframe))),
        sharpe=sharpe,
        sortino=_sortino_ratio(net_returns, timeframe),
        calmar=float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0,
        max_drawdown=max_drawdown,
        max_drawdown_duration=_max_drawdown_duration(equity_curve["drawdown"]),
        var_95=var_95,
        cvar_95=cvar_95,
        monte_carlo_sharpe_prob=mc_sharpe_prob,
        win_rate=win_rate,
        profit_factor=_trade_profit_factor(trade_pnls) if trade_pnls else _profit_factor(net_returns),
        turnover=float(equity_curve["position"].diff().abs().fillna(equity_curve["position"].abs()).sum()),
        exposure=float(equity_curve["position"].abs().mean()),
        average_trade=float(np.mean(trade_pnls)) if trade_pnls else 0.0,
        trades=trade_count,
        fees=fees,
        slippage=slippage,
        # beta/alpha/information_ratio require benchmark returns; set by caller when available.
        beta=0.0,
        alpha=0.0,
        information_ratio=0.0,
    )


def _annualized_return(equity: pd.Series, timeframe: str, starting_capital: float) -> float:
    periods = len(equity)
    if periods <= 1:
        return 0.0
    factor = _annualization_factor(timeframe)
    years = periods / factor if factor > 0 else 0.0
    if years <= 0:
        return 0.0
    ending_value = float(equity.iloc[-1])
    if starting_capital <= 0 or ending_value <= 0:
        return 0.0
    return float((ending_value / starting_capital) ** (1 / years) - 1.0)


def _sharpe_ratio(returns: pd.Series, timeframe: str) -> float:
    if returns.std(ddof=0) == 0:
        return 0.0
    factor = _annualization_factor(timeframe)
    return float((returns.mean() / returns.std(ddof=0)) * np.sqrt(factor))


def _sortino_ratio(returns: pd.Series, timeframe: str) -> float:
    downside = returns[returns < 0]
    if downside.empty or downside.std(ddof=0) == 0:
        return 0.0
    return float((returns.mean() / downside.std(ddof=0)) * np.sqrt(_annualization_factor(timeframe)))


def _profit_factor(returns: pd.Series) -> float:
    gains = float(returns[returns > 0].sum())
    losses = float(abs(returns[returns < 0].sum()))
    if losses == 0:
        return gains if gains > 0 else 0.0
    return gains / losses


def _completed_trade_pnls(fills: pd.DataFrame) -> list[float]:
    """Match long-only buys and sells into completed trade PnL observations."""

    if fills.empty or not {"symbol", "side", "quantity", "price"}.issubset(fills.columns):
        return []
    positions: dict[str, tuple[float, float]] = {}
    pnls: list[float] = []
    ordered = fills.sort_values("timestamp") if "timestamp" in fills else fills
    for _, fill in ordered.iterrows():
        symbol = str(fill["symbol"])
        quantity = float(fill["quantity"])
        price = float(fill["price"])
        fees = float(fill.get("fees", 0.0) or 0.0)
        held, average = positions.get(symbol, (0.0, 0.0))
        if str(fill["side"]).upper() == "BUY":
            new_quantity = held + quantity
            new_average = (held * average + quantity * price + fees) / max(new_quantity, 1e-12)
            positions[symbol] = (new_quantity, new_average)
            continue
        closed = min(quantity, held)
        if closed > 0:
            pnls.append((price - average) * closed - fees)
            remaining = held - closed
            if remaining > 0:
                positions[symbol] = (remaining, average)
            else:
                positions.pop(symbol, None)
    return pnls


def _trade_profit_factor(trade_pnls: list[float]) -> float:
    gains = sum(value for value in trade_pnls if value > 0)
    losses = abs(sum(value for value in trade_pnls if value < 0))
    if losses == 0:
        return gains if gains > 0 else 0.0
    return gains / losses


def _max_drawdown_duration(drawdown: pd.Series) -> int:
    current = 0
    longest = 0
    for value in drawdown:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _annualization_factor(timeframe: str, calendar: MarketCalendar | None = None) -> float:
    if calendar is not None:
        return calendar.annualization_factor(timeframe)
    label = str(timeframe).lower()
    if label.endswith("m"):
        minutes = int(label[:-1] or 1)
        bars_per_day = max(int(round(375 / minutes)), 1)
        return 252.0 * bars_per_day
    if label.endswith("h"):
        hours = int(label[:-1] or 1)
        bars_per_day = max(int(round(6.25 / hours)), 1)
        return 252.0 * bars_per_day
    return 252.0


def _build_run_id(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    mode: str,
    data_hash: str,
    parameters: dict[str, Any],
    execution_model: ExecutionModel,
) -> str:
    configuration_hash = hashlib.sha256(json.dumps({
        "parameters": parameters,
        "execution_model": asdict(execution_model),
    }, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"{strategy_name}:{symbol}:{timeframe}:{mode}:{data_hash[:12]}:{configuration_hash}"


def _hash_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    columns = [column for column in ["timestamp", "open", "high", "low", "close", "volume", "adjustment", "provider_name", "dataset_id"] if column in frame.columns]
    payload = pd.util.hash_pandas_object(frame[columns], index=True).values.tobytes()
    digest.update(payload)
    return digest.hexdigest()


def _default_symbol(bars: pd.DataFrame) -> str:
    if "symbol" in bars.columns and not bars["symbol"].empty:
        return str(bars["symbol"].iloc[0])
    return "UNKNOWN"


def _apply_slippage(price: float, side: OrderSide, slippage_bps: float) -> float:
    if side == OrderSide.BUY:
        return float(price * (1.0 + slippage_bps / 10_000.0))
    return float(price * (1.0 - slippage_bps / 10_000.0))


def _indian_schedule(execution_model: ExecutionModel) -> IndianDeliveryCostSchedule | None:
    values = execution_model.indian_delivery_costs
    if values is None:
        return None
    allowed = set(IndianDeliveryCostSchedule.__dataclass_fields__)
    return IndianDeliveryCostSchedule(**{key: value for key, value in values.items() if key in allowed})



def _fill_price(price: float, side: OrderSide, slippage_bps: float) -> float:
    return _apply_slippage(price, side, slippage_bps)
