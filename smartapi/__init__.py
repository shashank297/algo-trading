"""SmartAPI integration package for authentication, historical data, and live streaming."""

from data_platform.contracts import (
    BaseMarketEvent,
    Depth20Snapshot,
    DepthLevel,
    LiveTickerMode,
    LtpTick,
    MarketDataEvent,
    QuoteTick,
    SnapQuoteTick,
)
from smartapi.auth import SmartAPIAuth
from smartapi.historical import HistoricalDataClient, RateLimiter
from smartapi.instrument import InstrumentMaster
from smartapi.stream_decoder import PriceScaler, SmartStreamDecoder
from smartapi.stream_metrics import StreamMetrics
from smartapi.subscription_registry import SubscriptionKey, SubscriptionRegistry
from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient

__all__ = [
    "BaseMarketEvent",
    "ConnectionState",
    "Depth20Snapshot",
    "DepthLevel",
    "HistoricalDataClient",
    "InstrumentMaster",
    "LiveTickerMode",
    "LtpTick",
    "MarketDataEvent",
    "PriceScaler",
    "QuoteTick",
    "RateLimiter",
    "SmartAPIAuth",
    "SmartAPIWebSocketClient",
    "SmartStreamDecoder",
    "SnapQuoteTick",
    "StreamMetrics",
    "SubscriptionKey",
    "SubscriptionRegistry",
]
