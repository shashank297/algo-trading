"""Long-only single-asset strategies using causal OHLCV features."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from trading_stack.domain import StrategyMetadata, StrategyScope
from trading_stack.strategies import BaseStrategy


def _stateful(
    frame: pd.DataFrame,
    entry: pd.Series,
    exit_: pd.Series,
    entry_reason: str,
    exit_reason: str,
    *,
    atr: pd.Series | None = None,
    stop_atr_mult: float = 3.0,
    risk_pct: float = 0.02,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Stateful position tracker with ATR-based trailing stop and fractional sizing.

    Args:
        frame: OHLCV feature frame sorted ascending by timestamp.
        entry: Boolean series — True on bars where entry condition fires.
        exit_: Boolean series — True on bars where exit condition fires.
        entry_reason: Label written on entry bars.
        exit_reason: Label written on signal-driven exit bars.
        atr: Average True Range series for stop calculation. If None, stop is disabled.
        stop_atr_mult: Stop fires if price drops more than this × ATR below entry price.
        risk_pct: Fraction of capital risked per trade (used for position sizing).

    Returns:
        (targets, reasons, sizes) — target_position (0/1), reason string, size fraction.
    """
    position = 0.0
    entry_price = 0.0
    highest_price = 0.0
    trailing_stop = 0.0
    targets: list[float] = []
    reasons: list[str] = []
    sizes: list[float] = []
    closes = frame["close"].values
    atrs = atr.values if atr is not None else None
    for i, (should_enter, should_exit) in enumerate(zip(entry.fillna(False), exit_.fillna(False))):
        reason = ""
        current_close = float(closes[i])
        current_atr = float(atrs[i]) if atrs is not None and i < len(atrs) and not pd.isna(atrs[i]) else None
        # --- ATR trailing stop-loss (monotonic ratcheting) ---
        if position > 0.0 and current_atr is not None and current_atr > 0 and entry_price > 0:
            highest_price = max(highest_price, current_close)
            candidate_stop = highest_price - stop_atr_mult * current_atr
            trailing_stop = max(trailing_stop, candidate_stop)
            if current_close <= trailing_stop:
                position = 0.0
                entry_price = 0.0
                highest_price = 0.0
                trailing_stop = 0.0
                reason = "atr_stop_loss"
                targets.append(position)
                reasons.append(reason)
                sizes.append(0.0)
                continue
        # --- Signal-driven transitions ---
        if position == 0.0 and should_enter:
            position = 1.0
            entry_price = current_close
            highest_price = current_close
            trailing_stop = current_close - (stop_atr_mult * current_atr if current_atr and current_atr > 0 else 0.0)
            reason = entry_reason
        elif position > 0.0 and should_exit:
            position = 0.0
            entry_price = 0.0
            highest_price = 0.0
            trailing_stop = 0.0
            reason = exit_reason
        # --- ATR-based fractional sizing ---
        size = 0.0
        if position > 0.0 and current_atr is not None and current_atr > 0 and current_close > 0:
            # Size so that stop_atr_mult * ATR loss = risk_pct of capital
            size = min(1.0, (risk_pct * current_close) / (stop_atr_mult * current_atr))
        elif position > 0.0:
            size = 1.0  # Fallback: full position when ATR unavailable
        targets.append(position)
        reasons.append(reason)
        sizes.append(size)
    return pd.Series(targets, index=frame.index), pd.Series(reasons, index=frame.index), pd.Series(sizes, index=frame.index)


class _SingleAssetStrategy(BaseStrategy):
    # Configurable stop and sizing defaults; subclasses may override.
    _stop_atr_mult: float = 3.0
    _risk_pct: float = 0.02

    def __init__(self, name: str, **parameters: Any) -> None:
        metadata = self.strategy_metadata
        if metadata is None:
            raise ValueError(f"Strategy metadata is required for {name}.")
        super().__init__(name=name, parameters=parameters, version=metadata.version)

    def _finish(
        self,
        frame: pd.DataFrame,
        entry: pd.Series,
        exit_: pd.Series,
        enter: str,
        exit_reason: str,
    ) -> pd.DataFrame:
        atr = frame.get("atr")
        target, reasons, sizes = _stateful(
            frame, entry, exit_, enter, exit_reason,
            atr=atr,
            stop_atr_mult=self._stop_atr_mult,
            risk_pct=self._risk_pct,
        )
        result = self._signal_frame(frame, target, reasons)
        # Override target_position with ATR-sized fraction
        result["target_position"] = sizes
        result["target_weight"] = sizes
        return result


class TimeSeriesMomentumStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "time_series_momentum", "1.0.0", "TREND", StrategyScope.SINGLE_ASSET,
        ("close",), 253, "MONTHLY", True, "Time Series Momentum Effect; Robert Carver",
        {"long_lookback": (126, 252), "short_lookback": (63, 126)},
    )

    def __init__(self, long_lookback: int = 252, short_lookback: int = 63) -> None:
        super().__init__(self.strategy_metadata.name, long_lookback=long_lookback, short_lookback=short_lookback)
        self.long_lookback, self.short_lookback = long_lookback, short_lookback

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        long_return = frame["close"] / frame["close"].shift(self.long_lookback) - 1
        short_return = frame["close"] / frame["close"].shift(self.short_lookback) - 1
        return self._finish(frame, (long_return > 0) & (short_return > 0), long_return <= 0, "positive_time_series_momentum", "momentum_reversal")


class DonchianTrendStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "donchian_trend", "1.0.0", "TREND", StrategyScope.SINGLE_ASSET,
        ("high", "low"), 56, "DAILY", True, "Canonical Donchian trend system",
        {"entry_window": (40, 55, 80), "exit_window": (10, 20, 40)},
    )

    def __init__(self, entry_window: int = 55, exit_window: int = 20) -> None:
        super().__init__(self.strategy_metadata.name, entry_window=entry_window, exit_window=exit_window)
        self.entry_window, self.exit_window = entry_window, exit_window

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        upper = frame["high"].rolling(self.entry_window).max().shift(1)
        lower = frame["low"].rolling(self.exit_window).min().shift(1)
        return self._finish(frame, frame["close"] > upper, frame["close"] < lower, "donchian_trend_entry", "donchian_trend_exit")


class RSIPullbackStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "rsi_pullback", "1.0.0", "MEAN_REVERSION", StrategyScope.SINGLE_ASSET,
        ("close",), 200, "DAILY", True, "Canonical RSI(2) equity pullback",
        {"entry_rsi": (5.0, 10.0, 15.0), "exit_rsi": (60.0, 70.0, 80.0)},
    )

    def __init__(self, period: int = 2, entry_rsi: float = 10.0, exit_rsi: float = 70.0) -> None:
        super().__init__(self.strategy_metadata.name, period=period, entry_rsi=entry_rsi, exit_rsi=exit_rsi)
        self.period, self.entry_rsi, self.exit_rsi = period, entry_rsi, exit_rsi

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        delta = frame["close"].diff()
        gain = delta.clip(lower=0).rolling(self.period).mean()
        loss = -delta.clip(upper=0).rolling(self.period).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        trend = frame["close"] > frame["close"].rolling(200).mean()
        return self._finish(frame, (rsi < self.entry_rsi) & trend, rsi > self.exit_rsi, "rsi_oversold_in_uptrend", "rsi_recovered")


class BollingerPullbackStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "bollinger_pullback", "1.0.0", "MEAN_REVERSION", StrategyScope.SINGLE_ASSET,
        ("close",), 200, "DAILY", True, "Canonical Bollinger pullback; Ernest Chan",
        {"window": (15, 20, 30), "standard_deviations": (1.5, 2.0, 2.5)},
    )

    def __init__(self, window: int = 20, standard_deviations: float = 2.0) -> None:
        super().__init__(self.strategy_metadata.name, window=window, standard_deviations=standard_deviations)
        self.window, self.standard_deviations = window, standard_deviations

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        mean = frame["close"].rolling(self.window).mean()
        lower = mean - self.standard_deviations * frame["close"].rolling(self.window).std(ddof=0)
        trend = frame["close"] > frame["close"].rolling(200).mean()
        return self._finish(frame, (frame["close"] < lower) & trend, frame["close"] >= mean, "bollinger_pullback", "bollinger_mean_exit")


class DonchianBreakoutStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "donchian_breakout", "1.0.0", "BREAKOUT", StrategyScope.SINGLE_ASSET,
        ("high", "low", "atr"), 21, "DAILY", True, "Canonical price-channel breakout",
        {"entry_window": (20, 40, 55), "atr_buffer": (0.0, 0.25, 0.5)},
    )

    def __init__(self, entry_window: int = 20, exit_window: int = 10, atr_buffer: float = 0.25) -> None:
        super().__init__(self.strategy_metadata.name, entry_window=entry_window, exit_window=exit_window, atr_buffer=atr_buffer)
        self.entry_window, self.exit_window, self.atr_buffer = entry_window, exit_window, atr_buffer

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        atr = frame.get("atr", (frame["high"] - frame["low"]).rolling(20).mean())
        upper = frame["high"].rolling(self.entry_window).max().shift(1) + self.atr_buffer * atr.shift(1)
        lower = frame["low"].rolling(self.exit_window).min().shift(1)
        return self._finish(frame, frame["close"] > upper, frame["close"] < lower, "donchian_breakout", "channel_failure")


class VolumeConfirmedBreakoutStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "volume_confirmed_breakout", "1.0.0", "BREAKOUT", StrategyScope.SINGLE_ASSET,
        ("high", "volume"), 21, "DAILY", True, "Volume-confirmed price breakout",
        {"window": (20, 40, 55), "volume_multiplier": (1.25, 1.5, 2.0)},
    )

    def __init__(self, window: int = 20, volume_multiplier: float = 1.5) -> None:
        super().__init__(self.strategy_metadata.name, window=window, volume_multiplier=volume_multiplier)
        self.window, self.volume_multiplier = window, volume_multiplier

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        upper = frame["high"].rolling(self.window).max().shift(1)
        average_volume = frame["volume"].rolling(self.window).mean().shift(1)
        middle = frame["close"].rolling(self.window).mean().shift(1)
        entry = (frame["close"] > upper) & (frame["volume"] > average_volume * self.volume_multiplier)
        return self._finish(frame, entry, frame["close"] < middle, "volume_confirmed_breakout", "breakout_failure")


class VolatilityContractionBreakoutStrategy(_SingleAssetStrategy):
    strategy_metadata = StrategyMetadata(
        "volatility_contraction_breakout", "1.0.0", "VOLATILITY", StrategyScope.SINGLE_ASSET,
        ("close", "high", "volume"), 101, "DAILY", True, "Volatility contraction and expansion breakout",
        {"window": (15, 20, 30), "contraction_quantile": (0.15, 0.25, 0.35)},
    )

    def __init__(self, window: int = 20, contraction_quantile: float = 0.25, volume_multiplier: float = 1.25) -> None:
        super().__init__(self.strategy_metadata.name, window=window, contraction_quantile=contraction_quantile, volume_multiplier=volume_multiplier)
        self.window, self.contraction_quantile, self.volume_multiplier = window, contraction_quantile, volume_multiplier

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        mean = frame["close"].rolling(self.window).mean()
        width = 4 * frame["close"].rolling(self.window).std(ddof=0) / mean.replace(0, np.nan)
        threshold = width.rolling(100).quantile(self.contraction_quantile).shift(1)
        recently_contracted = (width.shift(1) <= threshold).rolling(5).max().fillna(0).astype(bool)
        upper = frame["high"].rolling(self.window).max().shift(1)
        volume_ok = frame["volume"] > frame["volume"].rolling(self.window).mean().shift(1) * self.volume_multiplier
        return self._finish(frame, recently_contracted & (frame["close"] > upper) & volume_ok, frame["close"] < mean, "volatility_expansion_breakout", "volatility_breakout_failure")
