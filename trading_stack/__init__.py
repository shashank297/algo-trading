"""Multi-market research, backtest, and paper-trading framework."""

from trading_stack.backtest import BacktestResult, EventDrivenBacktester, VectorizedBacktester
from trading_stack.broker import PaperBroker
from trading_stack.calendars import MarketCalendar, build_default_calendars
from trading_stack.domain import (
    AssetClass,
    BacktestMetrics,
    Bar,
    Fill,
    MarketSpec,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    StrategyRun,
    StrategyMetadata,
    StrategyScope,
    TimeInForce,
    infer_market_spec,
)
from trading_stack.features import FeatureFactory
from trading_stack.costs import IndianDeliveryCostSchedule
from trading_stack.datasets import ResearchDataset, SynchronizedPanelBuilder
from trading_stack.portfolio import PortfolioEventBacktester, equal_weight_targets, volatility_targeted_targets
from trading_stack.promotion import PromotionEngine, PromotionStage
from trading_stack.rca import RCAEngine
from trading_stack.strategies import (
    BaseStrategy,
    MeanReversionStrategy,
    OpeningRangeBreakoutStrategy,
    StrategyRegistry,
    TrendFollowingStrategy,
)

from trading_stack.market_regime import (
    MarketContextType,
    MarketRegimeComponentScores,
    MarketRegimeEngine,
    MarketRegimeEvidence,
    MarketRegimeFeatures,
    MarketRegimePolicy,
    MarketRegimeSnapshot,
    RawMarketRegime,
)
from trading_stack.regime_transition import (
    OperationalMarketRegime,
    OperationalRiskState,
    RegimeTransitionEngine,
    RegimeTransitionPolicy,
    StressEvidence,
    StressThresholds,
)

__all__ = [
    "AssetClass",
    "BacktestMetrics",
    "BacktestResult",
    "Bar",
    "BaseStrategy",
    "EventDrivenBacktester",
    "FeatureFactory",
    "Fill",
    "MarketCalendar",
    "MarketContextType",
    "MarketRegimeComponentScores",
    "MarketRegimeEngine",
    "MarketRegimeEvidence",
    "MarketRegimeFeatures",
    "MarketRegimePolicy",
    "MarketRegimeSnapshot",
    "MarketSpec",
    "MeanReversionStrategy",
    "OpeningRangeBreakoutStrategy",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "OperationalMarketRegime",
    "OperationalRiskState",
    "PaperBroker",
    "RawMarketRegime",
    "RegimeTransitionEngine",
    "RegimeTransitionPolicy",
    "StrategyRegistry",
    "StrategyMetadata",
    "StrategyScope",
    "StrategyRun",
    "StressEvidence",
    "StressThresholds",
    "TimeInForce",
    "TrendFollowingStrategy",
    "VectorizedBacktester",
    "build_default_calendars",
    "equal_weight_targets",
    "infer_market_spec",
    "volatility_targeted_targets",
    "IndianDeliveryCostSchedule",
    "PortfolioEventBacktester",
    "PromotionEngine",
    "PromotionStage",
    "RCAEngine",
    "ResearchDataset",
    "SynchronizedPanelBuilder",
]
