"""Strategy contracts, compatibility strategies, and automatic discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import inspect
import pkgutil
from typing import Any, ClassVar, cast

import numpy as np
import pandas as pd

from trading_stack.domain import StrategyMetadata, StrategyScope


@dataclass(slots=True)
class BaseStrategy:
    """Base class for all strategy templates."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"
    metadata: StrategyMetadata = field(init=False)
    strategy_metadata: ClassVar[StrategyMetadata | None] = None

    def __post_init__(self) -> None:
        declared = self.strategy_metadata
        self.metadata = declared or StrategyMetadata(
            name=self.name,
            version=self.version,
            family="UNCLASSIFIED",
            scope=StrategyScope.SINGLE_ASSET,
        )

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def position_sizing(self, signals: pd.DataFrame, portfolio: dict[str, Any] | None = None) -> pd.Series:
        """Return bounded target exposure; portfolio allocation may scale it later."""

        column = "target_position" if "target_position" in signals else "target_weight"
        return signals[column].clip(-1.0, 1.0)

    def risk_constraints(self, portfolio: dict[str, Any] | None = None) -> dict[str, float]:
        """Expose strategy-local constraints without coupling to the risk engine."""

        return {"max_abs_target_position": 1.0}

    def validate(self) -> None:
        """Reject invalid parameters before a deterministic run starts."""

        if not self.name:
            raise ValueError("A strategy must have a name.")
        if self.metadata.name != self.name:
            raise ValueError("Strategy metadata name must match the registered name.")
        if self.metadata.required_lookback < 1:
            raise ValueError("Strategy required lookback must be positive.")

    def _signal_frame(self, frame: pd.DataFrame, signal_values: pd.Series, reasons: pd.Series | None = None) -> pd.DataFrame:
        result = pd.DataFrame({"timestamp": frame["timestamp"], "target_position": signal_values.fillna(0.0)})
        result["symbol"] = frame["symbol"].astype(str).values if "symbol" in frame else ""
        result["target_weight"] = result["target_position"]
        result["signal"] = np.where(result["target_position"] > 0, "LONG", np.where(result["target_position"] < 0, "SHORT", "FLAT"))
        if reasons is None:
            result["reason"] = ""
        else:
            result["reason"] = reasons.fillna("")
        result["score"] = result["target_position"]
        result["rank"] = np.nan
        result["feature_snapshot"] = "{}"
        return result


class TrendFollowingStrategy(BaseStrategy):
    """Simple trend-following template using moving averages and volatility."""

    fast_threshold: float = 0.0
    min_volatility: float = 0.0
    allow_short: bool = False
    strategy_metadata = StrategyMetadata(
        name="trend_following", version="1.1.0", family="TREND",
        scope=StrategyScope.SINGLE_ASSET, required_features=("ema_fast", "ema_slow", "volatility"),
        required_lookback=40, rebalance_frequency="DAILY", source="Trend-following Effect in Stocks; Robert Carver",
    )

    def __init__(self, fast_threshold: float = 0.0, min_volatility: float = 0.0, allow_short: bool = False) -> None:
        super().__init__(
            name="trend_following",
            parameters={
                "fast_threshold": fast_threshold,
                "min_volatility": min_volatility,
                "allow_short": allow_short,
            },
        )
        self.fast_threshold = fast_threshold
        self.min_volatility = min_volatility
        self.allow_short = allow_short

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        fast = frame["ema_fast"] if "ema_fast" in frame.columns else frame["close"].ewm(span=10, adjust=False).mean()
        slow = frame["ema_slow"] if "ema_slow" in frame.columns else frame["close"].ewm(span=20, adjust=False).mean()
        volatility = frame["volatility"] if "volatility" in frame.columns else frame["close"].pct_change().rolling(20, min_periods=1).std().fillna(0.0)

        long_mask = (fast > slow * (1 + self.fast_threshold)) & (volatility >= self.min_volatility)
        short_mask = (slow > fast * (1 + self.fast_threshold)) & (volatility >= self.min_volatility) & self.allow_short
        signal_values = pd.Series(0.0, index=frame.index)
        signal_values.loc[long_mask] = 1.0
        signal_values.loc[short_mask] = -1.0
        reason = pd.Series("", index=frame.index)
        reason.loc[long_mask] = "trend_up"
        reason.loc[short_mask] = "trend_down"
        return self._signal_frame(frame, signal_values, reason)


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion template driven by z-scores."""

    entry_zscore: float = 1.5
    exit_zscore: float = 0.5
    lookback: int = 20
    allow_short: bool = False
    strategy_metadata = StrategyMetadata(
        name="mean_reversion", version="1.1.0", family="MEAN_REVERSION",
        scope=StrategyScope.SINGLE_ASSET, required_features=("price_zscore",),
        required_lookback=20, rebalance_frequency="DAILY", source="Canonical rolling z-score; Ernest Chan",
    )

    def __init__(
        self,
        entry_zscore: float = 1.5,
        exit_zscore: float = 0.5,
        lookback: int = 20,
        allow_short: bool = False,
    ) -> None:
        super().__init__(
            name="mean_reversion",
            parameters={
                "entry_zscore": entry_zscore,
                "exit_zscore": exit_zscore,
                "lookback": lookback,
                "allow_short": allow_short,
            },
        )
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore
        self.lookback = lookback
        self.allow_short = allow_short

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        zscore = frame["price_zscore"] if "price_zscore" in frame.columns else _rolling_zscore(frame["close"], self.lookback)

        target_position: list[float] = []
        current = 0.0
        reasons: list[str] = []
        for value in zscore.fillna(0.0).tolist():
            if current == 0.0:
                if value <= -self.entry_zscore:
                    current = 1.0
                    reasons.append("oversold")
                elif self.allow_short and value >= self.entry_zscore:
                    current = -1.0
                    reasons.append("overbought")
                else:
                    reasons.append("")
            elif current > 0:
                if value >= -self.exit_zscore:
                    current = 0.0
                    reasons.append("mean_revert_exit")
                else:
                    reasons.append("long_hold")
            else:
                if value <= self.exit_zscore:
                    current = 0.0
                    reasons.append("mean_revert_exit")
                else:
                    reasons.append("short_hold")
            target_position.append(current)

        signal_values = pd.Series(target_position, index=frame.index, dtype="float64")
        return self._signal_frame(frame, signal_values, pd.Series(reasons, index=frame.index))


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Opening-range breakout for intraday markets."""

    opening_range_minutes: int = 15
    breakout_buffer_bps: float = 5.0
    volume_multiplier: float = 1.0
    allow_short: bool = False
    strategy_metadata = StrategyMetadata(
        name="opening_range_breakout", version="1.1.0", family="BREAKOUT",
        scope=StrategyScope.SINGLE_ASSET, required_lookback=15,
        rebalance_frequency="INTRADAY", paper_eligible=False, source="Existing project strategy",
    )

    def __init__(
        self,
        opening_range_minutes: int = 15,
        breakout_buffer_bps: float = 5.0,
        volume_multiplier: float = 1.0,
        allow_short: bool = False,
    ) -> None:
        super().__init__(
            name="opening_range_breakout",
            parameters={
                "opening_range_minutes": opening_range_minutes,
                "breakout_buffer_bps": breakout_buffer_bps,
                "volume_multiplier": volume_multiplier,
                "allow_short": allow_short,
            },
        )
        self.opening_range_minutes = opening_range_minutes
        self.breakout_buffer_bps = breakout_buffer_bps
        self.volume_multiplier = volume_multiplier
        self.allow_short = allow_short

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        target_position = pd.Series(0.0, index=frame.index, dtype="float64")
        reasons = pd.Series("", index=frame.index, dtype="object")
        local_time = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
        session_day = local_time.dt.date

        for day in session_day.unique():
            day_mask = session_day == day
            day_frame = frame.loc[day_mask].copy()
            if day_frame.empty:
                continue
            opening_slice = day_frame.head(max(self.opening_range_minutes, 1))
            opening_high = opening_slice["high"].max()
            opening_low = opening_slice["low"].min()
            volume_reference = opening_slice["volume"].mean() if "volume" in opening_slice else 0.0
            current = 0.0
            day_indexes = list(day_frame.index)
            for position, idx in enumerate(day_indexes):
                row = day_frame.loc[idx]
                bar_number = position
                if bar_number < self.opening_range_minutes:
                    target_position.loc[idx] = current
                    continue
                breakout_up = row["high"] >= opening_high * (1 + self.breakout_buffer_bps / 10000.0)
                breakout_down = row["low"] <= opening_low * (1 - self.breakout_buffer_bps / 10000.0)
                volume_ok = row["volume"] >= volume_reference * self.volume_multiplier if volume_reference > 0 else True
                if breakout_up and volume_ok:
                    current = 1.0
                    reasons.loc[idx] = "breakout_up"
                elif self.allow_short and breakout_down and volume_ok:
                    current = -1.0
                    reasons.loc[idx] = "breakout_down"
                target_position.loc[idx] = current

        return self._signal_frame(frame, target_position, reasons)


class StrategyRegistry:
    """Discover approved strategy subclasses without a manual if/elif chain."""

    _registry: dict[str, type[BaseStrategy]] = {
        "trend_following": TrendFollowingStrategy,
        "mean_reversion": MeanReversionStrategy,
        "opening_range_breakout": OpeningRangeBreakoutStrategy,
    }
    _discovered = False

    @classmethod
    def discover(cls, force: bool = False) -> None:
        if cls._discovered and not force:
            return
        package = importlib.import_module("trading_stack.strategy_library")
        discovered = dict(cls._registry)
        for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
            module = importlib.import_module(module_info.name)
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if candidate is BaseStrategy or not issubclass(candidate, BaseStrategy):
                    continue
                candidate = cast(type[BaseStrategy], candidate)
                metadata = getattr(candidate, "strategy_metadata", None)
                if metadata is None:
                    continue
                existing = discovered.get(metadata.name)
                if existing is not None and existing is not candidate:
                    raise ValueError(f"Duplicate strategy name: {metadata.name}")
                discovered[metadata.name] = candidate
        cls._registry = discovered
        cls._discovered = True

    @classmethod
    def available(cls) -> list[str]:
        cls.discover()
        return sorted(cls._registry)

    @classmethod
    def metadata(cls, strategy_name: str) -> StrategyMetadata:
        cls.discover()
        try:
            metadata = cls._registry[strategy_name].strategy_metadata
        except KeyError as exc:
            raise ValueError(f"Unknown strategy: {strategy_name}") from exc
        if metadata is None:
            raise ValueError(f"Strategy has no metadata: {strategy_name}")
        return metadata

    @classmethod
    def create(cls, strategy_name: str, **parameters: Any) -> BaseStrategy:
        cls.discover()
        try:
            strategy_class = cls._registry[strategy_name]
        except KeyError as exc:
            raise ValueError(f"Unknown strategy: {strategy_name}") from exc
        return strategy_class(**parameters)


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=1).mean()
    std = series.rolling(window, min_periods=1).std(ddof=0).replace(0, np.nan)
    return ((series - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
