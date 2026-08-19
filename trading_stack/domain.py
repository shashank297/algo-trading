"""Core domain objects for the research, backtest, and paper-trading stack."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd

from data_platform.contracts import OrderSide


class AssetClass(str, Enum):
    """Supported market families."""

    INDIA_EQUITY = "INDIA_EQUITY"
    INDIA_INDEX = "INDIA_INDEX"
    US_EQUITY = "US_EQUITY"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"


class StrategyScope(str, Enum):
    """Whether a strategy evaluates one instrument or ranks a synchronized universe."""

    SINGLE_ASSET = "SINGLE_ASSET"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"


@dataclass(frozen=True)
class StrategyMetadata:
    """Validated strategy research and promotion metadata."""

    name: str
    version: str
    family: str
    scope: StrategyScope
    required_features: tuple[str, ...] = ()
    required_lookback: int = 1
    rebalance_frequency: str = "DAILY"
    paper_eligible: bool = True
    source: str = ""
    parameter_grid: dict[str, tuple[Any, ...]] = field(default_factory=dict)

class OrderType(str, Enum):


    """Supported order types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    BRACKET = "BRACKET"


class TimeInForce(str, Enum):
    """Supported order durations."""

    DAY = "DAY"
    IOC = "IOC"
    GTC = "GTC"


class OrderStatus(str, Enum):
    """Order lifecycle states."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class MarketSpec:
    """Canonical market metadata for a tradable instrument or venue."""

    symbol: str
    exchange: str
    asset_class: AssetClass
    currency: str
    timezone: str
    session_open: str
    session_close: str
    tradable: bool = True
    lot_size: int = 1
    tick_size: float = 0.01
    holidays: frozenset[date] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Bar:
    """Normalized OHLCV candle."""

    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    timeframe: str
    exchange: str
    asset_class: AssetClass


@dataclass(frozen=True)
class Order:
    """Broker-neutral order request."""

    order_id: str
    run_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    requested_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    limit_price: float | None = None
    stop_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Fill:
    """Broker-neutral fill event."""

    fill_id: str
    order_id: str
    run_id: str
    symbol: str
    timestamp: datetime
    quantity: float
    price: float
    side: OrderSide
    fill_type: str
    fees: float = 0.0
    slippage_bps: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestMetrics:
    """Canonical performance metrics for a strategy run."""

    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    max_drawdown_duration: int
    var_95: float
    cvar_95: float  # Expected shortfall: mean loss in worst 5% of periods
    monte_carlo_sharpe_prob: float  # Probability Sharpe > 0 via bootstrap
    win_rate: float
    profit_factor: float
    turnover: float
    exposure: float
    average_trade: float
    trades: int
    fees: float
    slippage: float
    beta: float = 0.0          # Sensitivity to benchmark (NIFTY200)
    alpha: float = 0.0         # CAPM alpha annualized
    information_ratio: float = 0.0  # Active return / tracking error


@dataclass
class StrategyRun:
    """Full result bundle returned by backtests and paper runs."""

    run_id: str
    strategy_name: str
    asset_class: AssetClass
    symbol: str
    timeframe: str
    mode: str
    parameters: dict[str, Any]
    data_hash: str
    metrics: BacktestMetrics
    signals: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    equity_curve: pd.DataFrame
    notes: str | None = None


def infer_asset_class(exchange: str, instrument_type: str) -> AssetClass:
    """Infer the market family from exchange and instrument type."""

    exchange_upper = str(exchange).upper()
    instrument_upper = str(instrument_type).upper()
    if exchange_upper in {"NSE", "BSE"}:
        return AssetClass.INDIA_INDEX if instrument_upper == "INDEX" else AssetClass.INDIA_EQUITY
    if exchange_upper in {"NASDAQ", "NYSE", "ARCA", "AMEX"}:
        return AssetClass.US_EQUITY
    if exchange_upper in {"FOREX", "FX"}:
        return AssetClass.FOREX
    if exchange_upper in {"CRYPTO", "BINANCE", "COINBASE", "KRAKEN"}:
        return AssetClass.CRYPTO
    if "/" in exchange_upper:
        return AssetClass.FOREX
    return AssetClass.INDIA_EQUITY


def infer_market_spec(
    symbol: str,
    exchange: str,
    instrument_type: str,
    *,
    tradable: bool = True,
    lot_size: int = 1,
    tick_size: float = 0.01,
    holidays: set[date] | None = None,
) -> MarketSpec:
    """Build a market specification with sensible defaults for the asset class."""

    asset_class = infer_asset_class(exchange, instrument_type)
    defaults = {
        AssetClass.INDIA_EQUITY: ("INR", "Asia/Kolkata", "09:15", "15:30"),
        AssetClass.INDIA_INDEX: ("INR", "Asia/Kolkata", "09:15", "15:30"),
        AssetClass.US_EQUITY: ("USD", "America/New_York", "09:30", "16:00"),
        AssetClass.FOREX: ("USD", "UTC", "00:00", "23:59"),
        AssetClass.CRYPTO: ("USD", "UTC", "00:00", "23:59"),
    }
    currency, timezone_name, session_open, session_close = defaults[asset_class]
    return MarketSpec(
        symbol=symbol,
        exchange=exchange,
        asset_class=asset_class,
        currency=currency,
        timezone=timezone_name,
        session_open=session_open,
        session_close=session_close,
        tradable=tradable,
        lot_size=lot_size,
        tick_size=tick_size,
        holidays=frozenset(holidays or set()),
    )
