"""Portfolio allocation helpers and authoritative cross-sectional event replay."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from trading_stack.backtest import _compute_metrics
from trading_stack.costs import IndianDeliveryCostSchedule, get_cost_schedule
from trading_stack.datasets import ResearchDataset
from trading_stack.domain import (
    AssetClass,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperExecutionMode,
    StrategyRun,
    StrategyScope,
    TimeInForce,
)


def equal_weight_targets(signals: pd.DataFrame, max_gross_exposure: float = 0.20) -> pd.Series:
    """Allocate equal gross exposure across non-zero strategy signals."""

    active = signals["target_position"].replace(0, float("nan")).notna()
    count = int(active.sum())
    if count == 0:
        return pd.Series(0.0, index=signals.index)
    return signals["target_position"].clip(-1, 1) * (max_gross_exposure / count)


def volatility_targeted_targets(
    signals: pd.DataFrame,
    volatility: pd.Series,
    target_volatility: float = 0.10,
    max_gross_exposure: float = 0.20,
) -> pd.Series:
    """Scale one strategy's target position by realized volatility and cap exposure."""

    safe_volatility = volatility.replace(0, float("nan")).bfill().fillna(target_volatility)
    targets = signals["target_position"].clip(-1, 1) * (target_volatility / safe_volatility)
    return targets.clip(-max_gross_exposure, max_gross_exposure)


@dataclass
class PortfolioBacktestResult:
    run: StrategyRun
    positions: pd.DataFrame
    rebalances: pd.DataFrame
    attribution: pd.DataFrame
    round_trips: pd.DataFrame
    cost_components: pd.DataFrame
    exclusions: pd.DataFrame


class PortfolioEventBacktester:
    """Replay target portfolio weights as next-session delta orders."""

    def __init__(
        self,
        cost_schedule: IndianDeliveryCostSchedule | None = None,
        *,
        max_position_weight: float = 0.05,
        max_gross_exposure: float = 0.20,
        max_sector_exposure: float = 0.10,
    ) -> None:
        self.cost_schedule = cost_schedule or IndianDeliveryCostSchedule()
        self.max_position_weight = max_position_weight
        self.max_gross_exposure = max_gross_exposure
        self.max_sector_exposure = max_sector_exposure

    def run(
        self,
        strategy: Any,
        dataset: ResearchDataset,
        *,
        starting_capital: float = 100_000.0,
        timeframe: str = "1d",
        parameters: dict[str, Any] | None = None,
        mode: str = "event-driven",
    ) -> PortfolioBacktestResult:
        strategy.validate()
        if strategy.metadata.scope != StrategyScope.CROSS_SECTIONAL:
            raise ValueError("Portfolio event replay requires a CROSS_SECTIONAL strategy.")
        panel = dataset.panel.copy().sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        panel["timestamp"] = pd.to_datetime(panel["timestamp"], utc=True)
        logger.bind(
            event="portfolio_replay_started",
            strategy=strategy.name,
            panel_rows=len(panel),
            symbol_count=int(panel["symbol"].nunique()),
            timeframe=timeframe,
        ).info("portfolio_replay_started")
        signals = strategy.generate_signals(panel)
        signals["timestamp"] = pd.to_datetime(signals["timestamp"], utc=True)
        effective_parameters = {**dict(getattr(strategy, "parameters", {})), **(parameters or {})}
        run_id = self._run_id(strategy.name, dataset.data_hash, effective_parameters, mode)
        panel_causal = panel.copy().sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        panel_causal["lagged_adv20"] = (
            panel_causal.groupby("symbol", group_keys=False)["volume"]
            .apply(lambda s: s.shift(1).rolling(20, min_periods=1).mean())
        )
        panel_causal["lagged_close"] = (
            panel_causal.groupby("symbol", group_keys=False)["close"]
            .shift(1)
        )
        panel_causal["lagged_traded_value"] = panel_causal["lagged_close"] * panel_causal["lagged_adv20"]

        day_groups = {
            pd.Timestamp(timestamp): group.set_index("symbol", drop=False)
            for timestamp, group in panel_causal.groupby("timestamp", sort=True)
        }
        dates = sorted(day_groups)
        next_date = {dates[index]: dates[index + 1] for index in range(len(dates) - 1)}
        executions: dict[pd.Timestamp, list[pd.DataFrame]] = {}
        for signal_date, targets in signals.groupby("timestamp"):
            execution_date = next_date.get(signal_date)
            if execution_date is not None:
                executions.setdefault(execution_date, []).append(targets.copy())

        cash = float(starting_capital)
        quantities: dict[str, float] = {}
        average_cost: dict[str, float] = {}
        entry_timestamps: dict[str, pd.Timestamp] = {}
        entry_reasons: dict[str, str] = {}
        entry_cost_pools: dict[str, float] = {}
        entry_execution_cost_pools: dict[str, float] = {}
        last_prices: dict[str, float] = {}
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        position_rows: list[dict[str, Any]] = []
        rebalance_rows: list[dict[str, Any]] = []
        attribution_rows: list[dict[str, Any]] = []
        round_trip_rows: list[dict[str, Any]] = []
        cost_rows: list[dict[str, Any]] = []
        previous_equity = starting_capital

        for session_index, date in enumerate(dates, start=1):
            day = day_groups[pd.Timestamp(date)]
            # Execute rebalancing orders at Day T+1 open using cash, Day T valuations and lagged ADV
            if date in executions:
                for targets in executions[date]:
                    cash, generated = self._rebalance(
                        run_id=run_id,
                        date=pd.Timestamp(date),
                        day=day,
                        targets=targets,
                        cash=cash,
                        quantities=quantities,
                        average_cost=average_cost,
                        entry_timestamps=entry_timestamps,
                        entry_reasons=entry_reasons,
                        entry_cost_pools=entry_cost_pools,
                        entry_execution_cost_pools=entry_execution_cost_pools,
                        last_prices=last_prices,
                        mode=mode,
                    )
                    orders.extend(generated["orders"])
                    fills.extend(generated["fills"])
                    cost_rows.extend(generated["costs"])
                    attribution_rows.extend(generated["attribution"])
                    round_trip_rows.extend(generated["round_trips"])
                    rebalance_rows.append(generated["rebalance"])

            # After rebalancing at open, update last_prices to Day T+1 CLOSE for EOD mark-to-market
            for symbol, row in day.iterrows():
                last_prices[str(symbol)] = float(row["close"])
            market_value = sum(quantity * last_prices.get(symbol, 0.0) for symbol, quantity in quantities.items())
            equity = cash + market_value
            gross_exposure = market_value / equity if equity > 0 else 0.0
            daily_pnl = equity - previous_equity
            position_rows.append({
                "run_id": run_id, "timestamp": pd.Timestamp(date), "symbol": "__PORTFOLIO__",
                "quantity": 0.0, "market_value": market_value, "cash": cash, "equity": equity,
                "gross_exposure": gross_exposure, "daily_pnl": daily_pnl,
            })
            for symbol, quantity in quantities.items():
                price = last_prices.get(symbol, 0.0)
                position_rows.append({
                    "run_id": run_id, "timestamp": pd.Timestamp(date), "symbol": symbol,
                    "quantity": quantity, "market_value": quantity * price, "cash": np.nan,
                    "equity": np.nan, "gross_exposure": abs(quantity * price) / equity if equity > 0 else 0.0,
                    "daily_pnl": np.nan,
                })
            previous_equity = equity
            if session_index % 500 == 0 or session_index == len(dates):
                logger.bind(
                    event="portfolio_replay_progress",
                    processed_sessions=session_index,
                    total_sessions=len(dates),
                    order_count=len(orders),
                    fill_count=len(fills),
                    equity=equity,
                ).info("portfolio_replay_progress")

        portfolio_positions = pd.DataFrame(position_rows)
        curve = portfolio_positions[portfolio_positions["symbol"] == "__PORTFOLIO__"].copy()
        curve["net_return"] = curve["equity"].pct_change().fillna(0.0)
        if cost_rows:
            cost_by_date = pd.DataFrame(cost_rows).groupby("timestamp")["total_cost"].sum()
            curve["cumulative_cost"] = curve["timestamp"].map(cost_by_date).fillna(0.0).cumsum()
        else:
            curve["cumulative_cost"] = 0.0
        curve["gross_equity"] = curve["equity"] + curve["cumulative_cost"]
        curve["gross_return"] = curve["gross_equity"].pct_change().fillna(0.0)
        curve["position"] = curve["gross_exposure"]
        curve["drawdown"] = curve["equity"] / curve["equity"].cummax() - 1.0
        orders_frame = pd.DataFrame(orders)
        fills_frame = pd.DataFrame(fills)
        metrics = _compute_metrics(
            equity_curve=curve,
            net_returns=curve["net_return"],
            fills=fills_frame,
            execution_model=type("PortfolioExecution", (), {"slippage_bps": self.cost_schedule.slippage_bps})(),
            timeframe=timeframe,
            starting_capital=starting_capital,
        )
        run = StrategyRun(
            run_id=run_id, strategy_name=strategy.name, asset_class=AssetClass.INDIA_EQUITY,
            symbol=f"PORTFOLIO:{dataset.universe_snapshot_id}", timeframe=timeframe, mode=mode,
            parameters=effective_parameters, data_hash=dataset.data_hash, metrics=metrics,
            signals=signals, orders=orders_frame, fills=fills_frame, equity_curve=curve,
            notes=json.dumps({
                "frame_certification_id": dataset.frame_certification_id,
                "survivorship_bias": dataset.survivorship_bias,
            }, sort_keys=True),
        )
        logger.bind(
            event="portfolio_replay_finished",
            run_id=run_id,
            session_count=len(dates),
            order_count=len(orders),
            fill_count=len(fills),
            ending_equity=float(curve["equity"].iloc[-1]),
        ).info("portfolio_replay_finished")
        return PortfolioBacktestResult(
            run=run,
            positions=portfolio_positions,
            rebalances=pd.DataFrame(rebalance_rows),
            attribution=pd.DataFrame(attribution_rows),
            round_trips=pd.DataFrame(round_trip_rows),
            cost_components=pd.DataFrame(cost_rows),
            exclusions=getattr(dataset, "exclusions", pd.DataFrame()),
        )

    def _rebalance(
        self,
        *,
        run_id: str,
        date: pd.Timestamp,
        day: pd.DataFrame,
        targets: pd.DataFrame,
        cash: float,
        quantities: dict[str, float],
        average_cost: dict[str, float],
        entry_timestamps: dict[str, pd.Timestamp],
        entry_reasons: dict[str, str],
        entry_cost_pools: dict[str, float],
        entry_execution_cost_pools: dict[str, float],
        last_prices: dict[str, float],
        mode: str,
        execution_mode: str = "EOD_BATCH",
    ) -> tuple[float, dict[str, Any]]:
        target_frame = targets.copy()
        if "target_weight" in target_frame.columns:
            target_frame["target_weight"] = pd.to_numeric(target_frame["target_weight"], errors="coerce").fillna(0.0).clip(lower=0, upper=self.max_position_weight)
        else:
            target_frame["target_weight"] = 0.0
        target_frame["sector"] = target_frame["symbol"].astype(str).map(
            day["sector"].to_dict() if "sector" in day.columns else {},
        ).fillna("UNKNOWN")
        for sector, indexes in target_frame[target_frame["sector"] != "UNKNOWN"].groupby("sector").groups.items():
            sector_weight = float(target_frame.loc[indexes, "target_weight"].sum())
            if sector_weight > self.max_sector_exposure:
                target_frame.loc[indexes, "target_weight"] *= self.max_sector_exposure / sector_weight
        total_weight = float(target_frame["target_weight"].sum())
        if total_weight > self.max_gross_exposure:
            target_frame["target_weight"] *= self.max_gross_exposure / total_weight
        equity = cash + sum(quantity * last_prices.get(symbol, 0.0) for symbol, quantity in quantities.items())
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        costs: list[dict[str, Any]] = []
        attribution: list[dict[str, Any]] = []
        round_trips: list[dict[str, Any]] = []
        buy_turnover = 0.0
        sell_turnover = 0.0
        target_by_symbol = {
            str(k): (0.0 if pd.isna(v) else float(v))
            for k, v in zip(target_frame["symbol"].astype(str), target_frame["target_weight"])
        }
        all_symbols = sorted(set(quantities) | set(target_by_symbol))
        # Sells free cash before buys consume it.
        all_symbols.sort(key=lambda symbol: target_by_symbol.get(symbol, 0.0) - quantities.get(symbol, 0.0) * last_prices.get(symbol, 0.0) / max(equity, 1e-12))
        for symbol in all_symbols:
            if symbol not in day.index:
                continue
            row = day.loc[symbol]
            open_tick_missing = False
            observation = row.get("open_tick_observation")
            if observation is not None and hasattr(observation, "price"):
                expected_exchange = str(row.get("exchange") or "").upper()
                expected_token = str(row.get("token") or "")
                identity_matches = (
                    str(getattr(observation, "symbol", "")) == symbol
                    and (not expected_exchange or str(getattr(observation, "exchange", "")).upper() == expected_exchange)
                    and (not expected_token or str(getattr(observation, "token", "")) == expected_token)
                )
                if (
                    identity_matches
                    and getattr(observation, "quality_state", "") == "TRUSTED"
                    and getattr(observation, "received_at_utc", None) is not None
                    and float(observation.price) > 0
                ):
                    base_price = float(observation.price)
                    execution_timestamp = pd.Timestamp(observation.received_at_utc)
                    source_seq = getattr(observation, "sequence_number", None)
                    execution_source = "OBSERVED_TICK"
                else:
                    open_tick_missing = True
                    base_price = float(row.get("open") or row.get("close") or 1.0)
                    execution_timestamp = date
                    source_seq = None
                    execution_source = "UNAVAILABLE"
            elif mode == "paper" and (execution_mode == PaperExecutionMode.TRUE_NEXT_OPEN.value or execution_mode == "TRUE_NEXT_OPEN"):
                open_tick_missing = True
                base_price = float(row.get("open") or row.get("close") or 1.0)
                execution_timestamp = date
                source_seq = None
                execution_source = "UNAVAILABLE"
            elif mode == "paper" and (execution_mode == PaperExecutionMode.EOD_BATCH.value or execution_mode == "EOD_BATCH"):
                base_price = float(row.get("close") or row.get("price") or row.get("open") or 0.0)
                execution_timestamp = date
                source_seq = None
                execution_source = "COMPLETED_BAR"
            else:
                base_price = float(row.get("open") or row.get("close") or 0.0)
                execution_timestamp = date
                source_seq = None
                execution_source = "COMPLETED_BAR"

            tw = float(target_by_symbol.get(symbol, 0.0)) if pd.notna(target_by_symbol.get(symbol, 0.0)) else 0.0
            target_quantity = float(np.floor(equity * tw / max(base_price, 1e-12))) if not pd.isna(base_price) and base_price > 0 else 0.0
            current_quantity = float(quantities.get(symbol, 0.0))
            requested_quantity = target_quantity - current_quantity
            if pd.isna(requested_quantity) or abs(requested_quantity) < 1:
                continue
            side = OrderSide.BUY if requested_quantity > 0 else OrderSide.SELL
            requested_abs = float(abs(requested_quantity))
            sched_date = execution_timestamp.tz_convert("Asia/Kolkata").date() if hasattr(execution_timestamp, "tz_convert") and execution_timestamp.tzinfo else (execution_timestamp.date() if hasattr(execution_timestamp, "date") else date)
            effective_schedule = get_cost_schedule(sched_date)
            lagged_adv_raw = row.get("lagged_adv20")
            lagged_adv = float(lagged_adv_raw) if pd.notna(lagged_adv_raw) and float(lagged_adv_raw) > 0 else np.nan
            lagged_val_raw = row.get("lagged_traded_value")
            lagged_traded_value = float(lagged_val_raw) if pd.notna(lagged_val_raw) and float(lagged_val_raw) > 0 else np.nan

            order_id = str(uuid.uuid4())
            reason_row = targets[targets["symbol"].astype(str) == symbol]
            reason = str(reason_row["reason"].iloc[0]) if (not reason_row.empty and "reason" in reason_row.columns) else "rank_removal"
            status = OrderStatus.FILLED
            filled_quantity = float(requested_abs)
            rejection_reason = None

            if open_tick_missing:
                status = OrderStatus.REJECTED
                filled_quantity = 0.0
                rejection_reason = "MISSED_LIVE_OPEN_PRICE"
            elif pd.isna(lagged_adv) or pd.isna(lagged_traded_value):
                status = OrderStatus.REJECTED
                filled_quantity = 0.0
                rejection_reason = "INSUFFICIENT_HISTORY_FOR_CAPACITY"
            elif lagged_traded_value < effective_schedule.minimum_daily_traded_value:
                status = OrderStatus.REJECTED
                filled_quantity = 0.0
                rejection_reason = "LIQUIDITY_REJECTION"
            else:
                volume_cap = np.floor(lagged_adv * effective_schedule.max_volume_participation)
                filled_quantity = float(min(filled_quantity, volume_cap))
                if side == OrderSide.SELL:
                    filled_quantity = float(min(filled_quantity, current_quantity))
                if filled_quantity <= 0:
                    status = OrderStatus.REJECTED
                    rejection_reason = "VOLUME_CAP_REJECTION"
                elif filled_quantity < requested_abs:
                    status = OrderStatus.PARTIALLY_FILLED
            participation = filled_quantity / max(lagged_adv, 1.0) if not pd.isna(lagged_adv) else 0.0
            execution_price = effective_schedule.execution_price(base_price, side, participation) if filled_quantity > 0 else base_price
            notional = filled_quantity * execution_price
            breakdown = effective_schedule.calculate(notional, side, participation) if filled_quantity > 0 else None
            if side == OrderSide.BUY and filled_quantity > 0:
                fee = breakdown.statutory_and_broker_fees if breakdown else 0.0
                affordable = np.floor(max(cash - fee, 0.0) / max(execution_price, 1e-12))
                if affordable < filled_quantity:
                    filled_quantity = affordable
                    participation = filled_quantity / max(lagged_adv, 1.0)
                    execution_price = effective_schedule.execution_price(base_price, side, participation)
                    notional = filled_quantity * execution_price
                    breakdown = effective_schedule.calculate(notional, side, participation)
                    status = OrderStatus.PARTIALLY_FILLED if filled_quantity > 0 else OrderStatus.REJECTED
                    rejection_reason = "INSUFFICIENT_CASH" if filled_quantity <= 0 else None
            orders.append({
                "order_id": order_id, "run_id": run_id, "symbol": symbol, "side": side.value,
                "quantity": float(requested_abs), "order_type": OrderType.MARKET.value,
                "time_in_force": TimeInForce.DAY.value, "status": status.value,
                "requested_at": execution_timestamp, "filled_at": execution_timestamp if filled_quantity > 0 else None,
                "limit_price": None, "stop_price": None,
                "average_fill_price": execution_price if filled_quantity > 0 else None,
                "slippage_bps": self.cost_schedule.slippage_bps,
                "fees": breakdown.statutory_and_broker_fees if breakdown is not None else 0.0,
                "metadata_json": json.dumps({
                    "reason": reason, "requested_quantity": requested_abs, "rejection_reason": rejection_reason,
                    "execution_mode": execution_mode, "execution_source": execution_source,
                    "execution_timestamp": str(execution_timestamp),
                    "source_exchange_timestamp": str(getattr(observation, "exchange_timestamp", "")) if execution_source == "OBSERVED_TICK" else None,
                    "source_received_at_utc": str(getattr(observation, "received_at_utc", "")) if execution_source == "OBSERVED_TICK" else None,
                    "source_sequence_number": source_seq,
                    "source_stream_epoch": getattr(observation, "stream_epoch", None) if execution_source == "OBSERVED_TICK" else None,
                }),
            })
            if filled_quantity <= 0:
                continue
            fill_id = str(uuid.uuid4())
            previous_average = average_cost.get(symbol, execution_price)
            previous_entry = entry_timestamps.get(symbol)
            previous_quantity = current_quantity
            holding_days: float | None = None
            gross_pnl = 0.0
            exit_classification = "ENTRY"
            stat_fees = breakdown.statutory_and_broker_fees if breakdown is not None else 0.0
            total_costs = breakdown.total if breakdown is not None else 0.0
            drag_costs = breakdown.execution_drag if breakdown is not None else 0.0
            if side == OrderSide.BUY:
                if current_quantity <= 0:
                    entry_timestamps[symbol] = execution_timestamp
                    entry_reasons[symbol] = reason
                old_value = current_quantity * previous_average
                new_quantity = current_quantity + filled_quantity
                cash -= notional + stat_fees
                quantities[symbol] = new_quantity
                average_cost[symbol] = (old_value + notional) / max(new_quantity, 1e-12)
                entry_cost_pools[symbol] = entry_cost_pools.get(symbol, 0.0) + total_costs
                entry_execution_cost_pools[symbol] = (
                    entry_execution_cost_pools.get(symbol, 0.0) + drag_costs
                )
                realized_pnl = 0.0
                buy_turnover += notional
            else:
                cash += notional - stat_fees
                quantities[symbol] = max(current_quantity - filled_quantity, 0.0)
                executed_pnl = (execution_price - previous_average) * filled_quantity
                allocated_entry_cost = entry_cost_pools.get(symbol, 0.0) * filled_quantity / max(
                    previous_quantity, 1e-12,
                )
                allocated_entry_execution_cost = (
                    entry_execution_cost_pools.get(symbol, 0.0) * filled_quantity
                    / max(previous_quantity, 1e-12)
                )
                entry_cost_pools[symbol] = max(
                    entry_cost_pools.get(symbol, 0.0) - allocated_entry_cost, 0.0,
                )
                entry_execution_cost_pools[symbol] = max(
                    entry_execution_cost_pools.get(symbol, 0.0) - allocated_entry_execution_cost,
                    0.0,
                )
                gross_pnl = executed_pnl + allocated_entry_execution_cost + drag_costs
                realized_pnl = gross_pnl - allocated_entry_cost - total_costs
                exit_classification = "RANK_REMOVAL" if target_by_symbol.get(symbol, 0.0) <= 0 else "REBALANCE_REDUCTION"
                if previous_entry is not None:
                    holding_days = (execution_timestamp - previous_entry).total_seconds() / 86_400.0
                    round_trips.append({
                        "trade_id": fill_id,
                        "run_id": run_id,
                        "symbol": symbol,
                        "entry_timestamp": previous_entry,
                        "exit_timestamp": execution_timestamp,
                        "quantity": float(filled_quantity),
                        "entry_price": previous_average,
                        "exit_price": execution_price,
                        "entry_cost": allocated_entry_cost,
                        "exit_cost": total_costs,
                        "gross_pnl": gross_pnl,
                        "net_pnl": realized_pnl,
                        "holding_period_days": holding_days,
                        "entry_reason": entry_reasons.get(symbol, "ENTRY"),
                        "exit_reason": reason,
                        "exit_classification": exit_classification,
                    })
                sell_turnover += notional
            if quantities.get(symbol, 0.0) <= 0:
                quantities.pop(symbol, None)
                average_cost.pop(symbol, None)
                entry_timestamps.pop(symbol, None)
                entry_reasons.pop(symbol, None)
                entry_cost_pools.pop(symbol, None)
                entry_execution_cost_pools.pop(symbol, None)
            fills.append({
                "fill_id": fill_id, "order_id": order_id, "run_id": run_id, "symbol": symbol,
                "timestamp": execution_timestamp, "quantity": float(filled_quantity), "price": execution_price,
                "side": side.value, "fill_type": "PAPER" if mode == "paper" else "BACKTEST",
                "fees": stat_fees, "slippage_bps": self.cost_schedule.slippage_bps,
                "metadata_json": json.dumps({
                    "reason": reason, "participation": participation, "execution_mode": execution_mode,
                    "execution_source": execution_source,
                    "source_exchange_timestamp": str(getattr(observation, "exchange_timestamp", "")) if execution_source == "OBSERVED_TICK" else None,
                    "source_received_at_utc": str(getattr(observation, "received_at_utc", "")) if execution_source == "OBSERVED_TICK" else None,
                    "source_sequence_number": source_seq,
                    "source_stream_epoch": getattr(observation, "stream_epoch", None) if execution_source == "OBSERVED_TICK" else None,
                }),
            })
            costs.append({"run_id": run_id, "fill_id": fill_id, "timestamp": execution_timestamp, **(breakdown.__dict__ if breakdown else {}), "total_cost": total_costs})
            attribution.append({
                "run_id": run_id, "timestamp": execution_timestamp, "symbol": symbol, "side": side.value,
                "reason": reason, "realized_pnl": realized_pnl, "cost": total_costs,
                "target_weight": target_by_symbol.get(symbol, 0.0),
                "quantity": float(filled_quantity), "price": execution_price,
                "average_cost": previous_average if side == OrderSide.SELL else average_cost[symbol],
                "gross_pnl": gross_pnl,
                "entry_timestamp": previous_entry if side == OrderSide.SELL else entry_timestamps.get(symbol),
                "holding_period_days": holding_days, "exit_classification": exit_classification,
            })
        return cash, {
            "orders": orders, "fills": fills, "costs": costs, "attribution": attribution,
            "round_trips": round_trips,
            "rebalance": {
                "rebalance_id": str(uuid.uuid4()), "run_id": run_id,
                "signal_timestamp": targets["timestamp"].iloc[0] if (not targets.empty and "timestamp" in targets.columns) else date,
                "execution_timestamp": date, "buy_turnover": buy_turnover, "sell_turnover": sell_turnover,
                "total_turnover": buy_turnover + sell_turnover, "target_count": int((target_frame["target_weight"] > 0).sum()),
                "replacement_pct": (buy_turnover + sell_turnover) / max(equity, 1e-12),
            },
        }

    def _run_id(self, strategy_name: str, data_hash: str, parameters: dict[str, Any], mode: str) -> str:
        configuration_hash = hashlib.sha256(json.dumps({
            "parameters": parameters,
            "cost_schedule": asdict(self.cost_schedule),
            "max_position_weight": self.max_position_weight,
            "max_gross_exposure": self.max_gross_exposure,
            "max_sector_exposure": self.max_sector_exposure,
        }, sort_keys=True, default=str).encode()).hexdigest()[:12]
        return f"{strategy_name}:PORTFOLIO:{mode}:{data_hash[:12]}:{configuration_hash}"
