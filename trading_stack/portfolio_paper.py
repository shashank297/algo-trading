"""Forward-only paper sessions for approved cross-sectional portfolios."""

from __future__ import annotations

import hashlib
import json
import uuid
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
from trading_stack.economic import (
    causal_rolling_volatility,
    calculate_projected_var_pct,
    economic_contract_hash,
)
from trading_stack.domain import (
    OpeningTickObservation,
    PaperExecutionMode,
)
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
        require_authoritative_certification: bool = True,
    ) -> None:
        self.db = db
        self.calendar = calendar
        self.risk_engine = risk_engine
        self.cost_schedule = cost_schedule or IndianDeliveryCostSchedule()
        self.require_authoritative_certification = require_authoritative_certification
        self.backtester = PortfolioEventBacktester(
            self.cost_schedule,
            max_position_weight=risk_engine.policy.max_position_pct,
            max_gross_exposure=risk_engine.policy.max_gross_exposure_pct,
            max_sector_exposure=risk_engine.policy.max_sector_exposure_pct,
            db=self.db,
            risk_engine=risk_engine,
            require_authoritative=True,
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
        opening_ticks: dict[str, float] | None = None,
        open_tick_timestamps: dict[str, datetime] | None = None,
        opening_observations: dict[str, OpeningTickObservation] | None = None,
    ) -> ForwardPortfolioPaperResult:
        if timeframe != "1d":
            raise ValueError("Cross-sectional forward paper sessions currently require daily bars.")
        parameters = parameters or {}
        as_of = as_of or datetime.now(timezone.utc)
        strategy = StrategyRegistry.create(strategy_name, **parameters)
        req_lookback = int(parameters.get("long_lookback", strategy.metadata.required_lookback))
        dataset = SynchronizedPanelBuilder(
            self.db,
            calendar=self.calendar,
            strict_calendar=True,
            require_authoritative_certification=self.require_authoritative_certification,
        ).build(
            symbols, timeframe, universe_snapshot_id=universe_snapshot_id,
            benchmark_symbol=benchmark_symbol, minimum_lookback=req_lookback,
        )
        panel = self._completed_panel(dataset.panel, as_of)
        if panel.empty:
            raise ValueError("No completed synchronized sessions are available for portfolio paper trading.")
        panel = panel.copy().sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        panel["lagged_adv20"] = (
            panel.groupby("symbol")["volume"]
            .transform(lambda s: s.shift(1).rolling(20, min_periods=1).mean())
        )
        panel["lagged_close"] = (
            panel.groupby("symbol")["close"]
            .transform(lambda s: s.shift(1))
        )
        panel["lagged_traded_value"] = panel["lagged_close"] * panel["lagged_adv20"]
        panel["volatility_20"] = panel.groupby("symbol")["close"].transform(
            lambda prices: causal_rolling_volatility(
                prices,
                include_current=execution_mode not in (PaperExecutionMode.TRUE_NEXT_OPEN.value, "TRUE_NEXT_OPEN"),
            )
        )
        signals = strategy.generate_signals(panel).copy()
        signals["timestamp"] = pd.to_datetime(signals["timestamp"], utc=True)
        session_id = self._session_id(
            strategy_name, strategy.metadata.version, approved_run_id, universe_snapshot_id,
            benchmark_symbol, timeframe, parameters, starting_capital,
        )
        economic_hash = self._economic_contract_hash(
            starting_capital=starting_capital,
            execution_mode=execution_mode,
        )
        latest_timestamp = pd.Timestamp(panel["timestamp"].max()).tz_convert("UTC")
        state = self._load_state(session_id)
        if state is not None:
            try:
                persisted_parameters = json.loads(str(state.get("parameters_json") or "{}"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("SESSION ECONOMIC CONTRACT MISMATCH: malformed session parameters") from exc
            persisted_hash = persisted_parameters.get("_economic_contract_hash")
            if persisted_hash != economic_hash:
                raise RuntimeError("SESSION ECONOMIC CONTRACT MISMATCH")
        now = pd.Timestamp(as_of).tz_convert("UTC").to_pydatetime()
        if state is None:
            pending = self._targets_at_or_before(signals, latest_timestamp)
            with self.db.transaction():
                self.db.conn.execute(
                    """
                    INSERT OR REPLACE INTO paper_portfolio_sessions (
                        session_id, approved_run_id, strategy_name, strategy_version,
                        universe_snapshot_id, benchmark_symbol, timeframe, parameters_json,
                        starting_capital, cash, peak_equity, daily_start_date, daily_start_equity,
                        last_processed_timestamp, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        session_id, approved_run_id, strategy_name, strategy.metadata.version,
                        universe_snapshot_id, benchmark_symbol, timeframe,
                        json.dumps({**parameters, "_economic_contract_hash": economic_hash}, sort_keys=True), float(starting_capital),
                        float(starting_capital), float(starting_capital),
                        latest_timestamp.tz_convert(self.calendar.zone).date(),
                        float(starting_capital), latest_timestamp.to_pydatetime(), "ACTIVE", now, now,
                    ],
                )
                self._save_pending(session_id, pending, now)
                self._persist_run_state(
                    session_id, strategy_name, universe_snapshot_id, timeframe, parameters,
                    latest_timestamp, starting_capital, 0, starting_capital=starting_capital,
                )
                self._record_desired_positions(session_id, {}, latest_timestamp.to_pydatetime(), now)
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
            day = panel[panel["timestamp"] == session_timestamp].copy().set_index("symbol", drop=False)
            session_date = session_timestamp.tz_convert(self.calendar.zone).date()

            if opening_observations:
                matching_obs = {}
                for sym, obs in opening_observations.items():
                    ts = getattr(obs, "timestamp", None) or getattr(obs, "exchange_timestamp", None) or getattr(obs, "received_at_utc", None)
                    if ts is not None:
                        ts_val = pd.Timestamp(ts)
                        ts_val = ts_val.tz_localize("UTC") if ts_val.tzinfo is None else ts_val
                        if ts_val.tz_convert(self.calendar.zone).date() == session_date:
                            matching_obs[str(sym)] = obs
                if matching_obs:
                    day["open_tick_observation"] = [matching_obs.get(str(s)) for s in day.index]
            elif execution_mode not in (PaperExecutionMode.TRUE_NEXT_OPEN.value, "TRUE_NEXT_OPEN") and opening_ticks:
                matching_ticks = {}
                matching_ts = {}
                for sym, price in opening_ticks.items():
                    ts = open_tick_timestamps.get(sym) if open_tick_timestamps else None
                    if ts is not None:
                        ts_val = pd.Timestamp(ts)
                        ts_val = ts_val.tz_localize("UTC") if ts_val.tzinfo is None else ts_val
                        if ts_val.tz_convert(self.calendar.zone).date() == session_date:
                            matching_ticks[sym] = price
                            matching_ts[sym] = ts
                    elif len(dates) == 1 and session_timestamp == dates[-1]:
                        matching_ticks[sym] = price
                if matching_ticks:
                    day["open_tick_price"] = day["symbol"].map(matching_ticks)
                if matching_ts:
                    day["open_tick_timestamp"] = day["symbol"].map(matching_ts)

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
                    daily_start_equity, peak_equity, execution_mode,
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
        equity = cash + sum(quantity * latest_prices.get(symbol, 0.0) for symbol, quantity in quantities.items())
        created_at_val = pd.Timestamp(state["created_at"]).tz_convert("UTC").to_pydatetime()
        final_ts_val = pd.Timestamp(final_timestamp).tz_convert("UTC").to_pydatetime()
        with self.db.transaction():
            self.db.conn.execute(
                """
                INSERT OR REPLACE INTO paper_portfolio_sessions (
                    session_id, approved_run_id, strategy_name, strategy_version,
                    universe_snapshot_id, benchmark_symbol, timeframe, parameters_json,
                    starting_capital, cash, peak_equity, daily_start_date, daily_start_equity,
                    last_processed_timestamp, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    session_id, str(state["approved_run_id"]), str(state["strategy_name"]),
                    str(state["strategy_version"]), str(state["universe_snapshot_id"]),
                    str(state.get("benchmark_symbol") or ""), str(state["timeframe"]),
                    str(state.get("parameters_json") or "{}"), float(state["starting_capital"]),
                    float(cash), float(peak_equity), daily_start_date, float(daily_start_equity),
                    final_ts_val, "ACTIVE", created_at_val, now,
                ],
            )
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
            self._record_desired_positions(session_id, quantities, final_timestamp, now)
            summary = self._reconcile(
                session_id, as_of, all_orders, all_fills, equity - starting_capital,
                "forward-only synchronized portfolio paper reconciliation",
            )
            if summary["drift"] > 1e-9:
                self.db.conn.execute(
                    "UPDATE paper_portfolio_sessions SET status = 'RECONCILIATION_FAILED' WHERE session_id = ?",
                    [session_id],
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
        execution_mode: str = PaperExecutionMode.EOD_BATCH.value,
    ) -> tuple[pd.DataFrame, list[RiskDecision]]:
        adjusted = targets.copy()
        del capital  # Risk limits use the current marked-to-market equity below.
        if "target_weight" in adjusted.columns:
            adjusted["target_weight"] = pd.to_numeric(adjusted["target_weight"], errors="coerce").fillna(0.0)
        else:
            adjusted["target_weight"] = 0.0
        is_next_open = execution_mode in (PaperExecutionMode.TRUE_NEXT_OPEN.value, "TRUE_NEXT_OPEN")
        decision_prices = dict(prices)
        for symbol, row in day.iterrows():
            if is_next_open:
                observed_open = row.get("open_tick_price")
                decision_prices[str(symbol)] = float(
                    observed_open if pd.notna(observed_open) and observed_open else row["open"]
                )
            else:
                decision_prices[str(symbol)] = float(row["close"])
        equity = cash + sum(
            quantity * decision_prices.get(symbol, 0.0)
            for symbol, quantity in quantities.items()
        )
        target_weights = {
            str(k): (0.0 if pd.isna(v) else float(v))
            for k, v in zip(adjusted["symbol"].astype(str), adjusted["target_weight"])
        }
        current_gross = sum(
            abs(quantity * decision_prices.get(symbol, 0.0))
            for symbol, quantity in quantities.items()
        )
        sector_exposure: dict[str, float] = {}
        if "sector" in day.columns:
            for held_symbol, held_quantity in quantities.items():
                sector = str(day.loc[held_symbol, "sector"]) if held_symbol in day.index else "UNKNOWN"
                sector_exposure[sector] = sector_exposure.get(sector, 0.0) + abs(
                    held_quantity * decision_prices.get(held_symbol, 0.0)
                )
        decisions: list[RiskDecision] = []
        for symbol, quantity in quantities.items():
            current_notional = abs(quantity * decision_prices.get(symbol, 0.0))
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
            price = decision_prices.get(symbol, 0.0)
            current_notional = quantities.get(symbol, 0.0) * price
            raw_weight = row.get("target_weight", 0.0)
            weight = 0.0 if pd.isna(raw_weight) else float(raw_weight)
            requested_delta = max(weight * equity - current_notional, 0.0)
            if requested_delta <= 0:
                continue
            sym_vol = float(day.loc[symbol, "volume"]) if (symbol in day.index and "volume" in day.columns and pd.notna(day.loc[symbol, "volume"])) else 0.0
            lagged_val = float(day.loc[symbol, "lagged_traded_value"]) if ("lagged_traded_value" in day.columns and symbol in day.index and pd.notna(day.loc[symbol, "lagged_traded_value"])) else sym_vol * price
            turnover_crore = (lagged_val / 10_000_000.0) if lagged_val > 0 else None
            vol_val = float(day.loc[symbol, "volatility_20"]) if (symbol in day.index and "volatility_20" in day.columns and pd.notna(day.loc[symbol, "volatility_20"])) else None
            projected_gross = current_gross + requested_delta
            est_port_var = calculate_projected_var_pct(
                volatility=vol_val,
                projected_gross=projected_gross,
                equity=equity,
            )

            decision = self.risk_engine.evaluate(TradeProposal(
                symbol=symbol,
                requested_notional=requested_delta,
                capital=equity,
                current_position_notional=current_notional,
                current_gross_exposure=current_gross,
                daily_pnl=equity - daily_start_equity,
                current_drawdown=max((peak_equity - equity) / max(peak_equity, 1e-12), 0.0),
                open_position_count=len([q for q in quantities.values() if abs(q) > 0]),
                daily_turnover_crore=turnover_crore,
                estimated_portfolio_var_pct=est_port_var,
                current_sector_exposure=sector_exposure.get(
                    str(row.get("sector", "UNKNOWN")), 0.0
                ),
            ))
            decisions.append(decision)
            if decision.action == RiskAction.REJECT:
                adjusted.loc[index, "target_weight"] = current_notional / max(equity, 1e-12)
            else:
                adjusted.loc[index, "target_weight"] = (
                    current_notional + decision.approved_notional
                ) / max(equity, 1e-12)
                current_gross += decision.approved_notional
                sector = str(row.get("sector", "UNKNOWN"))
                sector_exposure[sector] = sector_exposure.get(sector, 0.0) + decision.approved_notional
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
        valid_holdings = [
            {
                "session_id": session_id, "symbol": symbol, "quantity": float(quantity),
                "average_cost": float(average_cost.get(symbol, 0.0)), "entry_timestamp": entry_timestamps.get(symbol),
                "entry_reason": entry_reasons.get(symbol), "entry_cost_pool": float(entry_cost_pools.get(symbol, 0.0)),
                "entry_execution_cost_pool": float(entry_execution_cost_pools.get(symbol, 0.0)),
                "updated_at": now,
            }
            for symbol, quantity in quantities.items()
            if quantity is not None and not pd.isna(quantity) and float(quantity) > 0
        ]
        if valid_holdings:
            self.db._replace_rows("paper_portfolio_holdings", valid_holdings)

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
        target_quantities = self.db.latest_paper_position_intents(session_id)
        actual_quantities = self.db.fill_derived_positions(session_id)
        all_syms = set(target_quantities) | set(actual_quantities)
        drift = sum(abs(actual_quantities.get(s, 0.0) - target_quantities.get(s, 0.0)) for s in all_syms)
        submitted_count = len(orders)
        filled_count = len(fills)
        rejected_count = sum(order.get("status") == "REJECTED" for order in orders)
        expected_count = submitted_count

        summary = {
            "run_id": session_id,
            "trade_date": as_of.date(),
            "expected_orders": expected_count,
            "submitted_orders": submitted_count,
            "filled_orders": filled_count,
            "rejected_orders": rejected_count,
            "pnl": pnl,
            "drift": drift,
            "notes": notes if drift == 0.0 else f"{notes}; portfolio_drift={drift:.4f}",
        }
        self.db.log_paper_reconciliation([summary])
        return summary

    def _record_desired_positions(
        self, session_id: str, quantities: dict[str, float], as_of: datetime, created_at: datetime,
    ) -> None:
        desired = {symbol: 0.0 for symbol in self.db.latest_paper_position_intents(session_id)}
        desired.update(quantities)
        self.db.record_paper_position_intents([
            {
                "intent_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"portfolio-intent:{session_id}:{symbol}:{as_of.isoformat()}")),
                "session_id": session_id,
                "symbol": symbol,
                "as_of": as_of,
                "desired_quantity": quantity,
                "created_at": created_at,
            }
            for symbol, quantity in desired.items()
        ])

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
        }, sort_keys=True, default=str)
        return f"paper-forward:{strategy}:PORTFOLIO:{hashlib.sha256(payload.encode()).hexdigest()[:12]}"

    def _economic_contract_hash(self, *, starting_capital: float, execution_mode: str) -> str:
        return economic_contract_hash({
            "risk_policy": self.risk_engine.policy.model_dump(),
            "cost_schedule": self.cost_schedule.__dict__,
            "starting_capital": starting_capital,
            "execution_mode": execution_mode,
            "liquidity_policy": {
                "max_volume_participation": self.cost_schedule.max_volume_participation,
                "minimum_daily_traded_value": self.cost_schedule.minimum_daily_traded_value,
            },
            "position_constraints": {
                "max_position": self.risk_engine.policy.max_position_pct,
                "max_gross": self.risk_engine.policy.max_gross_exposure_pct,
                "max_sector": self.risk_engine.policy.max_sector_exposure_pct,
            },
            "sizing_semantics": "current_mark_to_market_equity_v1",
            "rounding_semantics": "floor_whole_share_v1",
        })
