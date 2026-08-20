"""Long-only cross-sectional strategies for synchronized equity panels."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from trading_stack.domain import StrategyMetadata, StrategyScope
from trading_stack.strategies import BaseStrategy


class CrossSectionalRankingStrategy(BaseStrategy):
    """Base class that converts causal scores into capped long-only weights."""

    def __init__(self, name: str, top_fraction: float = 0.20, max_gross_exposure: float = 0.20, max_holdings: int = 40, **parameters: Any) -> None:
        metadata = self.strategy_metadata
        if metadata is None:
            raise ValueError(f"Strategy metadata is required for {name}.")
        super().__init__(
            name=name,
            parameters={"top_fraction": top_fraction, "max_gross_exposure": max_gross_exposure, "max_holdings": max_holdings, **parameters},
            version=metadata.version,
        )
        self.top_fraction = top_fraction
        self.max_gross_exposure = max_gross_exposure
        self.max_holdings = max_holdings

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = {"timestamp", "symbol", "close"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Cross-sectional panel is missing columns: {sorted(missing)}")
        panel = frame.copy().sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        panel["timestamp"] = pd.to_datetime(panel["timestamp"], utc=True)
        panel["score"] = self.score_panel(panel).replace([np.inf, -np.inf], np.nan)
        panel["observation_count"] = panel.groupby("symbol").cumcount() + 1
        panel = panel[panel["observation_count"] >= self.metadata.required_lookback]
        rebalance_dates = panel.groupby(panel["timestamp"].dt.strftime("%Y-%m"))["timestamp"].max()
        ranked = panel[panel["timestamp"].isin(rebalance_dates)].dropna(subset=["score"]).copy()
        if ranked.empty:
            return pd.DataFrame(columns=["timestamp", "symbol", "target_weight", "target_position", "signal", "reason", "score", "rank", "feature_snapshot"])

        # Point-in-Time Universe filtering via dataset eligible column
        if "eligible" in panel.columns:
            panel = panel[panel["eligible"]].copy()

        # Legacy fallback if pit_db_conn is explicitly provided in strategy parameters
        universe_name = self.parameters.get("universe_name") or self.parameters.get("pit_universe_name")
        pit_conn = self.parameters.get("pit_db_conn") or self.parameters.get("db_conn")
        if universe_name and pit_conn is not None:
            from data_platform.universe import PointInTimeUniverseManager

            valid_mask = pd.Series(False, index=ranked.index)
            for rebal_ts in rebalance_dates:
                ts_mask = ranked["timestamp"] == rebal_ts
                active_symbols = set(PointInTimeUniverseManager.get_constituent_symbols(pit_conn, str(universe_name), rebal_ts))
                if active_symbols:
                    valid_mask |= (ts_mask & ranked["symbol"].isin(active_symbols))

            ranked = ranked[valid_mask].copy()

            if ranked.empty:
                return pd.DataFrame(columns=["timestamp", "symbol", "target_weight", "target_position", "signal", "reason", "score", "rank", "feature_snapshot"])

        ranked["rank"] = ranked.groupby("timestamp")["score"].rank(method="first", ascending=False)

        ranked["eligible_count"] = ranked.groupby("timestamp")["symbol"].transform("count")
        ranked["selection_count"] = np.maximum(1, np.ceil(ranked["eligible_count"] * self.top_fraction)).astype(int).clip(upper=self.max_holdings)
        selected = ranked["rank"] <= ranked["selection_count"]
        ranked["target_weight"] = np.where(selected, self.max_gross_exposure / ranked["selection_count"], 0.0)
        ranked["target_position"] = ranked["target_weight"]
        ranked["signal"] = np.where(selected, "LONG", "FLAT")
        ranked["reason"] = np.where(selected, self.metadata.name + "_selected", self.metadata.name + "_not_selected")
        ranked["feature_snapshot"] = ranked.apply(lambda row: f'{{"score":{float(row["score"]):.10g},"rank":{int(row["rank"])}}}', axis=1)
        return ranked[["timestamp", "symbol", "target_weight", "target_position", "signal", "reason", "score", "rank", "feature_snapshot"]].reset_index(drop=True)

    @staticmethod
    def _group_return(panel: pd.DataFrame, periods: int) -> pd.Series:
        return panel.groupby("symbol", group_keys=False)["close"].pct_change(periods)


class CrossSectionalMomentumStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "cross_sectional_momentum", "1.0.0", "MOMENTUM", StrategyScope.CROSS_SECTIONAL,
        ("close",), 253, "MONTHLY", True, "Momentum Factor Effect in Stocks; Gray and Vogel",
        {"long_lookback": (126, 252), "skip_recent": (10, 21)},
    )

    def __init__(self, long_lookback: int = 252, skip_recent: int = 21, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, long_lookback=long_lookback, skip_recent=skip_recent, **kwargs)
        self.long_lookback, self.skip_recent = long_lookback, skip_recent

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        grouped = panel.groupby("symbol")["close"]
        return grouped.shift(self.skip_recent) / grouped.shift(self.long_lookback) - 1


class FiftyTwoWeekHighMomentumStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "fifty_two_week_high", "1.0.0", "MOMENTUM", StrategyScope.CROSS_SECTIONAL,
        ("close", "high"), 252, "MONTHLY", True, "52-Weeks High Effect in Stocks",
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, **kwargs)

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        prior_high = panel.groupby("symbol")["high"].transform(lambda value: value.rolling(252).max().shift(1))
        trend = panel["close"] > panel.groupby("symbol")["close"].transform(lambda value: value.rolling(200).mean())
        return (panel["close"] / prior_high).where(trend)


class ConsistentMomentumStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "consistent_momentum", "1.0.0", "MOMENTUM", StrategyScope.CROSS_SECTIONAL,
        ("close",), 253, "MONTHLY", True, "Consistent Momentum Strategy",
    )

    def __init__(self, minimum_positive_months: int = 8, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, minimum_positive_months=minimum_positive_months, **kwargs)
        self.minimum_positive_months = minimum_positive_months

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        output = pd.Series(np.nan, index=panel.index)
        for _, indexes in panel.groupby("symbol").groups.items():
            group = panel.loc[indexes]
            month_end = group.groupby(group["timestamp"].dt.strftime("%Y-%m")).tail(1)
            monthly_return = month_end["close"].pct_change()
            positive_months = monthly_return.gt(0).rolling(12, min_periods=12).sum()
            momentum = month_end["close"].pct_change(12)
            output.loc[month_end.index] = momentum.where(positive_months >= self.minimum_positive_months).values
        return output


class ResidualMomentumStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "residual_momentum", "1.0.0", "MOMENTUM", StrategyScope.CROSS_SECTIONAL,
        ("close", "benchmark_close"), 253, "MONTHLY", True, "Residual Momentum Factor",
    )

    def __init__(self, lookback: int = 252, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, lookback=lookback, **kwargs)
        self.lookback = lookback

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        stock_return = self._group_return(panel, self.lookback)
        if "benchmark_close" not in panel:
            return stock_return
        benchmark_return = panel.groupby("symbol")["benchmark_close"].pct_change(self.lookback)
        beta = pd.Series(np.nan, index=panel.index)
        for _, indexes in panel.groupby("symbol").groups.items():
            stock_daily = panel.loc[indexes, "close"].pct_change()
            benchmark_daily = panel.loc[indexes, "benchmark_close"].pct_change()
            values = stock_daily.rolling(126).cov(benchmark_daily) / benchmark_daily.rolling(126).var().replace(0, np.nan)
            beta.loc[indexes] = values.values
        return stock_return - beta * benchmark_return


class SectorRelativeMomentumStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "sector_relative_momentum", "1.0.0", "MOMENTUM", StrategyScope.CROSS_SECTIONAL,
        ("close", "sector"), 126, "MONTHLY", True, "Sector Momentum Rotational System",
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, **kwargs)

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        stock_momentum = self._group_return(panel, 126)
        if "sector" not in panel:
            return stock_momentum
        temporary = pd.DataFrame({"timestamp": panel["timestamp"], "sector": panel["sector"], "momentum": stock_momentum})
        sector_score = temporary.groupby(["timestamp", "sector"])["momentum"].transform("mean")
        return 0.5 * stock_momentum + 0.5 * sector_score


class CrossSectionalShortTermReversalStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "cross_sectional_short_term_reversal", "1.0.0", "MEAN_REVERSION", StrategyScope.CROSS_SECTIONAL,
        ("close",), 200, "MONTHLY", True, "Short Term Reversal Effect in Stocks",
    )

    def __init__(self, reversal_window: int = 5, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, reversal_window=reversal_window, **kwargs)
        self.reversal_window = reversal_window

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        reversal = -self._group_return(panel, self.reversal_window)
        trend = panel["close"] > panel.groupby("symbol")["close"].transform(lambda value: value.rolling(200).mean())
        return reversal.where(trend)


class LowVolatilityStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "low_volatility", "1.0.0", "FACTOR", StrategyScope.CROSS_SECTIONAL,
        ("close",), 200, "MONTHLY", True, "Low Volatility Factor Effect in Stocks",
    )

    def __init__(self, window: int = 60, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, window=window, **kwargs)
        self.window = window

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        returns = panel.groupby("symbol")["close"].pct_change()
        volatility = returns.groupby(panel["symbol"]).transform(lambda value: value.rolling(self.window).std(ddof=0))
        trend = panel["close"] > panel.groupby("symbol")["close"].transform(lambda value: value.rolling(200).mean())
        return (-volatility).where(trend)


class LowBetaStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "low_beta", "1.0.0", "FACTOR", StrategyScope.CROSS_SECTIONAL,
        ("close", "benchmark_close"), 252, "MONTHLY", True, "Betting Against Beta adapted to a long-only low-beta leg",
    )

    def __init__(self, window: int = 252, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, window=window, **kwargs)
        self.window = window

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        if "benchmark_close" not in panel:
            raise ValueError("low_beta requires benchmark_close")
        output = pd.Series(np.nan, index=panel.index)
        for _, index in panel.groupby("symbol").groups.items():
            stock = panel.loc[index, "close"].pct_change()
            benchmark = panel.loc[index, "benchmark_close"].pct_change()
            beta = stock.rolling(self.window).cov(benchmark) / benchmark.rolling(self.window).var().replace(0, np.nan)
            output.loc[index] = -beta.values
        return output


class MomentumReversalVolatilityStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "momentum_reversal_volatility", "1.0.0", "COMPOSITE", StrategyScope.CROSS_SECTIONAL,
        ("close",), 253, "MONTHLY", True, "Momentum and Reversal Combined with Volatility Effect in Stocks",
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, **kwargs)

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        momentum = self._group_return(panel, 252) - self._group_return(panel, 21)
        reversal = -self._group_return(panel, 5)
        daily = panel.groupby("symbol")["close"].pct_change()
        volatility = daily.groupby(panel["symbol"]).transform(lambda value: value.rolling(60).std(ddof=0))
        return _date_zscore(momentum, panel["timestamp"]) + _date_zscore(reversal, panel["timestamp"]) - _date_zscore(volatility, panel["timestamp"])


class OHLCVMultiFactorStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "ohlcv_multi_factor", "1.0.0", "COMPOSITE", StrategyScope.CROSS_SECTIONAL,
        ("close", "volume"), 253, "MONTHLY", True, "Smart-factor and quantitative equity literature",
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, **kwargs)

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        momentum = self._group_return(panel, 252) - self._group_return(panel, 21)
        trend = panel["close"] / panel.groupby("symbol")["close"].transform(lambda value: value.rolling(200).mean()) - 1
        daily = panel.groupby("symbol")["close"].pct_change()
        volatility = daily.groupby(panel["symbol"]).transform(lambda value: value.rolling(60).std(ddof=0))
        liquidity = (panel["close"] * panel["volume"]).groupby(panel["symbol"]).transform(lambda value: value.rolling(20).mean())
        return sum((_date_zscore(momentum, panel["timestamp"]), _date_zscore(trend, panel["timestamp"]), -_date_zscore(volatility, panel["timestamp"]), _date_zscore(liquidity, panel["timestamp"]))) / 4


class WalkForwardLogisticStrategy(CrossSectionalRankingStrategy):
    strategy_metadata = StrategyMetadata(
        "walk_forward_logistic", "1.0.0", "MACHINE_LEARNING", StrategyScope.CROSS_SECTIONAL,
        ("close", "volume"), 253, "MONTHLY", True, "Walk-forward logistic classifier; Stefan Jansen and Lopez de Prado",
    )

    def __init__(self, horizon: int = 20, minimum_training_rows: int = 500, **kwargs: Any) -> None:
        super().__init__(self.strategy_metadata.name, horizon=horizon, minimum_training_rows=minimum_training_rows, **kwargs)
        self.horizon, self.minimum_training_rows = horizon, minimum_training_rows

    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:
            raise RuntimeError("walk_forward_logistic requires scikit-learn") from exc
        working = panel.copy()
        working["momentum_21"] = self._group_return(working, 21)
        working["momentum_126"] = self._group_return(working, 126)
        daily = working.groupby("symbol")["close"].pct_change()
        working["volatility_20"] = daily.groupby(working["symbol"]).transform(lambda value: value.rolling(20).std(ddof=0))
        working["volume_change"] = working.groupby("symbol")["volume"].pct_change(20)
        future = working.groupby("symbol")["close"].shift(-self.horizon) / working["close"] - 1
        working["label"] = (future > 0).astype(float).where(future.notna())
        working["label_available_at"] = working.groupby("symbol")["timestamp"].shift(-self.horizon)
        scores = pd.Series(np.nan, index=working.index)
        features = ["momentum_21", "momentum_126", "volatility_20", "volume_change"]
        dates = working.groupby(working["timestamp"].dt.strftime("%Y-%m"))["timestamp"].max()
        for date in dates:
            training = working[(working["label_available_at"] <= date) & working[features + ["label"]].notna().all(axis=1)]
            current = working[(working["timestamp"] == date) & working[features].notna().all(axis=1)]
            if len(training) < self.minimum_training_rows or current.empty or training["label"].nunique() < 2:
                continue
            model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=0))
            model.fit(training[features], training["label"].astype(int))
            scores.loc[current.index] = model.predict_proba(current[features])[:, 1]
        return scores


def _date_zscore(values: pd.Series, dates: pd.Series) -> pd.Series:
    mean = values.groupby(dates).transform("mean")
    std = values.groupby(dates).transform("std").replace(0, np.nan)
    return (values - mean) / std
