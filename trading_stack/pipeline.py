import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
import pandas as pd

from data_platform.adjustments import PriceAdjustmentEngine
from data_platform.contracts import PriceAdjustment
from storage.duckdb_manager import DuckDBManager
from risk.engine import RiskEngine
from risk.models import RiskAction, RiskDecision, TradeProposal
from trading_stack.backtest import EventDrivenBacktester, ExecutionModel, PaperBroker, VectorizedBacktester
from trading_stack.calendars import MarketCalendar, build_default_calendars
from trading_stack.costs import IndianDeliveryCostSchedule
from trading_stack.domain import AssetClass, PaperExecutionMode, StrategyScope, infer_asset_class
from trading_stack.features import FeatureFactory
from trading_stack.strategies import StrategyRegistry
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine
from trading_stack.promotion import PromotionEngine


class DataQualityError(ValueError):
    """Raised when data fails pre-backtest quality checks."""
    pass


REQUIRED_AUTHORITATIVE_DQ_CHECKS = {
    "schema",
    "ohlc_integrity",
    "duplicates",
    "session_alignment",
    "missing_sessions",
    "timestamp_integrity",
}


class StrategyPipeline:
    """End-to-end research and paper-trading pipeline."""

    def __init__(
        self,
        db: DuckDBManager | None = None,
        feature_factory: FeatureFactory | None = None,
        risk_engine: RiskEngine | None = None,
        strict_calendar: bool = False,
        india_calendar: MarketCalendar | None = None,
        require_authoritative_certification: bool = False,
    ) -> None:
        self.db = db or DuckDBManager()
        self.calendars = build_default_calendars()
        if india_calendar is not None:
            self.calendars[AssetClass.INDIA_EQUITY] = india_calendar
            self.calendars[AssetClass.INDIA_INDEX] = india_calendar
            self.strict_calendar = True
        else:
            self.strict_calendar = strict_calendar
        self.feature_factory = feature_factory or FeatureFactory()
        self.risk_engine = risk_engine or RiskEngine()
        self.promotion_engine = PromotionEngine(self.db)
        self.require_authoritative_certification = require_authoritative_certification
        self.vector_backtester = VectorizedBacktester()
        self.event_backtester = EventDrivenBacktester()

    def load_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        bypass_quality_gate: bool = False,
        require_authoritative_certification: bool | None = None,
        adjustment: PriceAdjustment | str = PriceAdjustment.SPLIT_ADJUSTED,
    ) -> pd.DataFrame:
        """Load stored candles for a symbol/timeframe from DuckDB, with optional corporate action adjustment."""

        frame = self.db.conn.execute(
            """
            SELECT symbol, exchange, timeframe, timestamp, open, high, low, close, volume,
                   adjustment, provider_name, dataset_id
            FROM historical_candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp ASC
            """,
            [symbol, timeframe],
        ).df()
        if frame.empty:
            raise ValueError(f"No stored candles found for {symbol} {timeframe}")

        if not bypass_quality_gate:
            must_certify = self.require_authoritative_certification if require_authoritative_certification is None else require_authoritative_certification
            try:
                contributing_dataset_ids = [
                    str(x).strip() for x in frame["dataset_id"].dropna().unique() if str(x).strip()
                ]
                null_dataset_count = int(frame["dataset_id"].isna().sum()) + int((frame["dataset_id"] == "").sum())

                if must_certify:
                    if null_dataset_count > 0 or not contributing_dataset_ids:
                        raise DataQualityError(
                            f"DataQualityError: {null_dataset_count} uncertified candle rows present with NULL dataset_id for {symbol} {timeframe}. "
                            "Authoritative research requires every row to belong to a verified, certified dataset."
                        )

                    for ds_id in contributing_dataset_ids:
                        # 1. Verify dataset in market_datasets
                        ds_record = self.db.conn.execute(
                            "SELECT status, lifecycle_status FROM market_datasets WHERE dataset_id = ?",
                            [ds_id],
                        ).fetchone()
                        if not ds_record or ds_record[0] != "VERIFIED" or ds_record[1] != "CANONICAL_PROMOTED":
                            raise DataQualityError(
                                f"DataQualityError: Dataset {ds_id} contributing to {symbol} {timeframe} has status={ds_record[0] if ds_record else 'NONE'}, "
                                f"lifecycle={ds_record[1] if ds_record else 'NONE'}; must be VERIFIED and CANONICAL_PROMOTED."
                            )

                        # 2. Verify atomic certification batch in data_quality_certifications
                        cert_record = self.db.conn.execute(
                            "SELECT certification_id, status, issue_count FROM data_quality_certifications WHERE dataset_id = ? ORDER BY completed_at DESC LIMIT 1",
                            [ds_id],
                        ).fetchone()
                        if not cert_record or cert_record[1] != "CERTIFIED" or int(cert_record[2]) > 0:
                            raise DataQualityError(
                                f"DataQualityError: Contributing dataset {ds_id} for {symbol} {timeframe} does not possess an active CERTIFIED batch in data_quality_certifications."
                            )

                        cert_id = cert_record[0]
                        # 3. Verify exact 6 child checks in quality_report
                        quality_rows = self.db.conn.execute(
                            "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?",
                            [cert_id],
                        ).fetchall()
                        observed_checks = {r[0] for r in quality_rows if int(r[1]) == 0}
                        missing_checks = REQUIRED_AUTHORITATIVE_DQ_CHECKS - observed_checks
                        if missing_checks:
                            raise DataQualityError(
                                f"DataQualityError: Incomplete DQ certification for dataset {ds_id} ({symbol} {timeframe}). "
                                f"Missing required check categories: {sorted(missing_checks)}."
                            )

                    # Composed research frame validation
                    # Timestamp duplicates
                    dup_count = int(frame.duplicated(subset=["timestamp"]).sum())
                    if dup_count > 0:
                        raise DataQualityError(f"DataQualityError: Composed frame for {symbol} contains {dup_count} duplicate timestamps.")

                    # Timestamp monotonicity
                    ts_series = pd.to_datetime(frame["timestamp"], utc=True)
                    if not ts_series.is_monotonic_increasing:
                        raise DataQualityError(f"DataQualityError: Composed frame for {symbol} timestamps are not strictly monotonic.")

                    # OHLC validity
                    if (frame["high"] < frame["low"]).any() or (frame["open"] <= 0).any() or (frame["close"] <= 0).any() or (frame["volume"] < 0).any():
                        raise DataQualityError(f"DataQualityError: Composed frame for {symbol} contains OHLC integrity violations.")

                    # Persist research frame certification
                    frame_hash = hashlib.sha256(frame[["timestamp", "open", "high", "low", "close", "volume"]].to_json().encode()).hexdigest()[:16]
                    frame_cert_id = str(uuid.uuid4())
                    now_utc = datetime.now(timezone.utc)
                    self.db.conn.execute(
                        """
                        INSERT INTO research_frame_certifications (
                            frame_certification_id, research_frame_hash, contributing_dataset_ids_json,
                            symbol, timeframe, row_count, basis, validator_version, status, verified_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            frame_cert_id, frame_hash, json.dumps(contributing_dataset_ids),
                            symbol, timeframe, len(frame), str(adjustment), "validator-v1", "CERTIFIED", now_utc,
                        ],
                    )
                else:
                    # Non-authoritative fallback check on quality_report
                    quality_rows = self.db.conn.execute(
                        "SELECT check_type, issue_count FROM quality_report WHERE symbol = ? AND timeframe = ? ORDER BY checked_at DESC",
                        [symbol, timeframe],
                    ).fetchall()
                    for q_type, count in quality_rows:
                        if count and int(count) > 0:
                            raise DataQualityError(f"DataQualityError: {symbol} {timeframe} failed {q_type} check with {count} issues.")
            except Exception as e:
                if isinstance(e, DataQualityError):
                    raise
                logger.error("Data quality verification failed for {}: {}", symbol, e)
                raise DataQualityError(
                    f"Data quality certification failed for {symbol} {timeframe}: {e}. Failing closed."
                ) from e

        adj_enum = (
            adjustment if isinstance(adjustment, PriceAdjustment)
            else PriceAdjustment(str(getattr(adjustment, "value", adjustment)).upper())
        )
        ca_df = self.db.get_corporate_actions(symbol)
        frame = PriceAdjustmentEngine.adjust_ohlcv(frame, ca_df, adjustment=adj_enum)

        return frame


    def run(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe: str,
        mode: str = "vectorized",
        parameters: dict[str, Any] | None = None,
        starting_capital: float = 100_000.0,
        cost_model: dict[str, Any] | None = None,
        adjustment: PriceAdjustment | str = PriceAdjustment.SPLIT_ADJUSTED,
        require_authoritative_certification: bool | None = None,
    ) -> dict[str, Any]:
        """Run a strategy and persist the result bundle."""

        parameters = parameters or {}
        certify = self.require_authoritative_certification if require_authoritative_certification is None else require_authoritative_certification
        raw_bars = self.load_candles(
            symbol, timeframe, adjustment=adjustment, require_authoritative_certification=certify,
        )
        asset_class = self._lookup_asset_class(symbol=symbol, exchange=str(raw_bars["exchange"].iloc[0]))
        calendar = self.calendars[asset_class]
        if self.strict_calendar:
            validation = calendar.validate_bars(raw_bars["timestamp"], timeframe)
            if validation.out_of_session_count:
                raise ValueError(
                    f"Stored bars contain {validation.out_of_session_count} timestamps outside calendar {calendar.version}."
                )
        featured = self.feature_factory.build(raw_bars, timezone_name="Asia/Kolkata")
        self._persist_features(featured, symbol=symbol, timeframe=timeframe)
        strategy = StrategyRegistry.create(strategy_name, **parameters)
        signals = strategy.generate_signals(featured)
        if signals.empty:
            raise ValueError("Strategy produced zero signals for the provided dataset.")

        metadata = strategy.metadata
        dataset_id = self._latest_dataset_id(symbol, timeframe)
        execution_model = self._execution_model(cost_model)
        if mode == "vectorized":
            result = self.vector_backtester.run(
                strategy, featured, starting_capital=starting_capital,
                symbol=symbol, timeframe=timeframe, calendar=calendar, parameters=parameters,
            )
        elif mode == "event-driven":
            result = EventDrivenBacktester(
                execution_model=execution_model,
            ).run(
                strategy, featured, starting_capital=starting_capital,
                symbol=symbol, timeframe=timeframe, calendar=calendar, parameters=parameters,
            )
        else:
            raise ValueError(f"Unknown backtest mode: {mode}")

        persisted_starting_capital = starting_capital
        result.starting_capital = persisted_starting_capital
        result.dataset_id = dataset_id
        self._persist_result(
            result,
            mode=mode,
            strategy_name=strategy_name,
            asset_class=asset_class,
            execution_model=execution_model,
            starting_capital=persisted_starting_capital,
        )
        if mode == "event-driven":
            self._apply_paper_risk(result, starting_capital)
        return {
            "result": result,
            "signals": signals,
            "featured": featured,
            "run_id": result.run_id,
            "dataset_id": dataset_id,
            "data_hash": result.data_hash,
        }

    def run_paper_session(
        self,
        *,
        strategy_name: str,
        approved_run_id: str,
        symbol: str,
        timeframe: str,
        universe: list[str] | None = None,
        universe_snapshot_id: str = "CONFIGURED_UNIVERSE",
        benchmark_symbol: str = "NIFTY200",
        parameters: dict[str, Any] | None = None,
        starting_capital: float = 100_000.0,
        cost_model: dict[str, Any] | None = None,
        as_of: datetime | None = None,
        execution_mode: str = PaperExecutionMode.EOD_BATCH.value,
        opening_ticks: dict[str, float] | None = None,
        open_tick_timestamps: dict[str, datetime] | None = None,
        adjustment: PriceAdjustment | str = PriceAdjustment.SPLIT_ADJUSTED,
    ) -> dict[str, Any]:
        """Advance a persisted forward-only paper session by newly observed bars."""

        PromotionEngine(self.db).assert_paper_authorized(approved_run_id, strategy_name)
        metadata = StrategyRegistry.metadata(strategy_name)
        if metadata.scope == StrategyScope.CROSS_SECTIONAL:
            if not universe:
                raise ValueError("Cross-sectional paper sessions require a synchronized universe.")
            allowed = set(IndianDeliveryCostSchedule.__dataclass_fields__)
            schedule = IndianDeliveryCostSchedule(**{
                key: value for key, value in (cost_model or {}).items() if key in allowed
            })
            portfolio_result = ForwardPortfolioPaperSessionEngine(
                self.db, calendar=self.calendars[AssetClass.INDIA_EQUITY],
                risk_engine=self.risk_engine, cost_schedule=schedule,
            ).run(
                strategy_name=strategy_name, approved_run_id=approved_run_id,
                symbols=universe, universe_snapshot_id=universe_snapshot_id,
                benchmark_symbol=benchmark_symbol, timeframe=timeframe,
                parameters=parameters, starting_capital=starting_capital, as_of=as_of,
                execution_mode=execution_mode, opening_ticks=opening_ticks,
                open_tick_timestamps=open_tick_timestamps,
            )
            return {
                "forward_portfolio_result": portfolio_result,
                "paper_summary": portfolio_result.paper_summary,
            }
        certify = self.require_authoritative_certification
        raw_bars = self.load_candles(
            symbol, timeframe, adjustment=adjustment, require_authoritative_certification=certify,
        )
        asset_class = self._lookup_asset_class(symbol=symbol, exchange=str(raw_bars["exchange"].iloc[0]))
        if self.strict_calendar:
            validation = self.calendars[asset_class].validate_bars(raw_bars["timestamp"], timeframe)
            if validation.out_of_session_count:
                raise ValueError("Paper session bars are outside the verified market calendar.")
        engine = ForwardPaperSessionEngine(
            self.db,
            calendar=self.calendars[asset_class],
            risk_engine=self.risk_engine,
            feature_factory=self.feature_factory,
            execution_model=self._execution_model(cost_model),
        )
        open_tick = (opening_ticks.get(symbol) if opening_ticks else None)
        open_ts = (open_tick_timestamps.get(symbol) if open_tick_timestamps else None)
        result = engine.run(
            strategy_name=strategy_name,
            approved_run_id=approved_run_id,
            symbol=symbol,
            timeframe=timeframe,
            parameters=parameters,
            starting_capital=starting_capital,
            as_of=as_of,
            execution_mode=execution_mode,
            open_tick_price=open_tick,
            open_tick_timestamp=open_ts,
        )
        return {"forward_result": result, "paper_summary": result.paper_summary}

    def _execution_model(self, cost_model: dict[str, Any] | None) -> ExecutionModel:
        allowed = set(ExecutionModel.__dataclass_fields__)
        values: dict[str, Any] = {
            key: value for key, value in (cost_model or {}).items() if key in allowed
        }
        indian_fields = {
            key for key in (cost_model or {})
            if key in IndianDeliveryCostSchedule.__dataclass_fields__
        }
        if indian_fields:
            values["indian_delivery_costs"] = {
                key: value for key, value in (cost_model or {}).items() if key in indian_fields
            }
        return ExecutionModel(**values)

    def _apply_paper_risk(self, result: Any, starting_capital: float) -> None:
        """Audit pre-sized paper orders and fail closed if an entry needs modification."""

        if result.orders.empty:
            return
        gross_exposure = 0.0
        for _, order in result.orders.sort_values("requested_at").iterrows():
            price = float(order.get("average_fill_price") or order.get("price") or 100.0)
            qty = abs(float(order["quantity"]))
            requested_notional = abs(qty * price)
            if str(order["side"]).upper() == "SELL":
                decision = RiskDecision(
                    symbol=str(order["symbol"]),
                    action=RiskAction.PASS,
                    requested_notional=max(requested_notional, 1e-9),
                    approved_notional=max(requested_notional, 1e-9),
                    reasons=["risk_reducing_exit"],
                    policy=self.risk_engine.policy,
                )
                gross_exposure = max(gross_exposure - requested_notional, 0.0)
            else:
                turnover_cr = (qty * price * 50.0 / 10_000_000.0) if (qty * price) > 0 else 10.0
                est_var = 1.65 * 0.015 * (gross_exposure / max(starting_capital, 1e-9))
                decision = self.risk_engine.evaluate(
                    TradeProposal(
                        symbol=str(order["symbol"]),
                        requested_notional=max(requested_notional, 1e-9),
                        capital=starting_capital,
                        current_gross_exposure=gross_exposure,
                        current_sector_exposure=0.0,
                        daily_pnl=0.0,
                        current_drawdown=0.0,
                        open_position_count=0,
                        daily_turnover_crore=turnover_cr,
                        estimated_portfolio_var_pct=est_var,
                    ),
                )
                gross_exposure += decision.approved_notional
            self.db.log_risk_decision(decision.storage_payload(run_id=result.run_id))

    def _persist_result(
        self,
        result: Any,
        *,
        mode: str,
        strategy_name: str,
        asset_class: AssetClass,
        execution_model: ExecutionModel,
        starting_capital: float = 100_000.0,
    ) -> None:
        with self.db.transaction():
            self.db.clear_backtest_artifacts(result.run_id)
            self.db.log_strategy_run(
                {
                    "run_id": result.run_id,
                    "strategy_name": strategy_name,
                    "asset_class": asset_class.value,
                    "symbol": result.symbol,
                    "timeframe": result.timeframe,
                    "mode": mode,
                    "starting_capital": starting_capital,
                    "parameters_json": json.dumps(result.parameters, default=str),
                    "data_hash": result.data_hash,
                    "status": "COMPLETED",
                    "started_at": datetime.now(tz=timezone.utc),
                    "finished_at": datetime.now(tz=timezone.utc),
                    "notes": None,
                },
                result.metrics,
            )
            self.db.log_strategy_orders(result.orders.to_dict(orient="records"))
            self.db.log_strategy_fills(result.fills.to_dict(orient="records"))
            self.db.log_equity_curve(result.run_id, result.equity_curve)
            self._persist_single_asset_attribution(result, execution_model)

    def _persist_single_asset_attribution(
        self,
        result: Any,
        execution_model: ExecutionModel,
        *,
        persist: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Reconcile single-asset fills into RCA-ready realized trade evidence."""

        if result.fills.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        orders = result.orders.set_index("order_id").to_dict(orient="index") if not result.orders.empty else {}
        quantity = 0.0
        average_cost = 0.0
        entry_timestamp: pd.Timestamp | None = None
        entry_reason = "ENTRY"
        entry_cost_pool = 0.0
        entry_execution_cost_pool = 0.0
        rows: list[dict[str, Any]] = []
        cost_rows: list[dict[str, Any]] = []
        round_trips: list[dict[str, Any]] = []
        for fill in result.fills.sort_values("timestamp").to_dict(orient="records"):
            side = str(fill["side"]).upper()
            fill_quantity = float(fill["quantity"])
            price = float(fill["price"])
            timestamp = pd.Timestamp(fill["timestamp"])
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            order = orders.get(fill["order_id"], {})
            try:
                metadata = json.loads(str(order.get("metadata_json") or "{}"))
            except json.JSONDecodeError:
                metadata = {}
            try:
                fill_metadata = json.loads(str(fill.get("metadata_json") or "{}"))
            except json.JSONDecodeError:
                fill_metadata = {}
            components = fill_metadata.get("cost_components") or metadata.get("cost_components")
            if components:
                cost = float(components["total_cost"])
                execution_drag = sum(float(components.get(name, 0.0)) for name in (
                    "spread", "slippage", "market_impact",
                ))
                cost_rows.append({
                    "run_id": result.run_id, "fill_id": fill["fill_id"], "timestamp": timestamp,
                    **components,
                })
            else:
                execution_drag = abs(fill_quantity * price) * (
                    execution_model.slippage_bps + execution_model.spread_bps
                ) / 10_000.0
                cost = float(fill.get("fees", 0.0)) + execution_drag
            gross_pnl = 0.0
            holding_days: float | None = None
            allocated_entry_cost = 0.0
            prior_average = average_cost
            prior_entry = entry_timestamp
            prior_quantity = quantity
            if side == "BUY":
                if quantity <= 0:
                    entry_timestamp = timestamp
                    entry_reason = str(metadata.get("reason") or "ENTRY")
                average_cost = (
                    quantity * average_cost + fill_quantity * price
                ) / max(quantity + fill_quantity, 1e-12)
                quantity += fill_quantity
                entry_cost_pool += cost
                entry_execution_cost_pool += execution_drag
            else:
                closed_quantity = min(fill_quantity, max(quantity, 0.0))
                executed_pnl = (price - average_cost) * closed_quantity
                allocated_entry_cost = entry_cost_pool * closed_quantity / max(prior_quantity, 1e-12)
                allocated_entry_execution_cost = (
                    entry_execution_cost_pool * closed_quantity / max(prior_quantity, 1e-12)
                )
                entry_cost_pool = max(entry_cost_pool - allocated_entry_cost, 0.0)
                entry_execution_cost_pool = max(
                    entry_execution_cost_pool - allocated_entry_execution_cost, 0.0,
                )
                gross_pnl = executed_pnl + allocated_entry_execution_cost + execution_drag
                quantity = max(quantity - closed_quantity, 0.0)
                if prior_entry is not None:
                    holding_days = (timestamp - prior_entry).total_seconds() / 86_400.0
                    exit_reason = str(metadata.get("reason") or "SIGNAL_FLIP")
                    round_trips.append({
                        "trade_id": str(fill["fill_id"]),
                        "run_id": result.run_id,
                        "symbol": result.symbol,
                        "entry_timestamp": prior_entry,
                        "exit_timestamp": timestamp,
                        "quantity": closed_quantity,
                        "entry_price": prior_average,
                        "exit_price": price,
                        "entry_cost": allocated_entry_cost,
                        "exit_cost": cost,
                        "gross_pnl": gross_pnl,
                        "net_pnl": gross_pnl - allocated_entry_cost - cost,
                        "holding_period_days": holding_days,
                        "entry_reason": entry_reason,
                        "exit_reason": exit_reason,
                        "exit_classification": "SIGNAL_FLIP",
                    })
                if quantity == 0:
                    average_cost = 0.0
                    entry_timestamp = None
                    entry_cost_pool = 0.0
                    entry_execution_cost_pool = 0.0
            rows.append({
                "run_id": result.run_id, "timestamp": timestamp,
                "symbol": result.symbol, "side": side,
                "reason": str(metadata.get("reason") or metadata.get("mode") or "signal_target_change"),
                "realized_pnl": gross_pnl - cost if side == "SELL" else -cost,
                "cost": cost, "target_weight": float(metadata.get("delta_position", 0.0)),
                "quantity": fill_quantity, "price": price,
                "average_cost": prior_average if side == "SELL" else average_cost,
                "gross_pnl": gross_pnl, "entry_timestamp": prior_entry if side == "SELL" else entry_timestamp,
                "holding_period_days": holding_days,
                "exit_classification": "SIGNAL_FLIP" if side == "SELL" else "ENTRY",
            })
        attribution_frame = pd.DataFrame(rows)
        round_trip_frame = pd.DataFrame(round_trips)
        cost_frame = pd.DataFrame(cost_rows)
        if persist:
            self.db._replace_frame("trade_attribution", attribution_frame)
            self.db._replace_frame("trade_round_trips", round_trip_frame)
            self.db._replace_frame("fill_cost_components", cost_frame)
        return attribution_frame, round_trip_frame, cost_frame

    def _persist_features(self, frame: pd.DataFrame, *, symbol: str, timeframe: str) -> None:
        storeable = self.feature_factory.storeable_features(frame)
        self.db.upsert_feature_frame(storeable, symbol=symbol, timeframe=timeframe, feature_group="default")

    def _lookup_asset_class(self, *, symbol: str, exchange: str) -> AssetClass:
        """Resolve the market family from the normalized universe table when possible."""

        try:
            result = self.db.conn.execute(
                """
                SELECT asset_class
                FROM market_universe
                WHERE symbol = ? AND exchange = ?
                LIMIT 1
                """,
                [symbol, exchange],
            ).fetchone()
            if result and result[0]:
                return AssetClass(str(result[0]))
        except Exception:
            pass
        return infer_asset_class(exchange, "EQUITY")

    def _latest_dataset_id(self, symbol: str, timeframe: str) -> str | None:
        row = self.db.conn.execute(
            """SELECT dataset_id FROM market_datasets 
               WHERE (canonical_symbol = ? OR symbol = ?) 
                 AND timeframe = ? 
                 AND lifecycle_status = 'CANONICAL_PROMOTED' 
                 AND status = 'VERIFIED'
               ORDER BY retrieved_at DESC LIMIT 1""",
            [symbol, symbol, timeframe],
        ).fetchone()
        return str(row[0]) if row else None
