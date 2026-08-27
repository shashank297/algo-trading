"""Market Context and Deterministic Raw Market Regime Engine.

Phase 2.3 implementation satisfying causal point-in-time constraints (known_at <= decision_time),
versioned deterministic component scoring, exact evidence hashing, and raw regime classification.
"""

from __future__ import annotations

import datetime
from enum import Enum
import hashlib
import json
from typing import Any
import uuid
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_stack.calendars import MarketCalendar, build_nse_calendar

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


class MarketContextType(str, Enum):
    """Context evaluation horizon."""

    EOD = "EOD"
    INTRADAY = "INTRADAY"


class RawMarketRegime(str, Enum):
    """Raw market regime classification taxonomy."""

    BULL_LOW_VOL = "BULL_LOW_VOL"
    BULL_HIGH_VOL = "BULL_HIGH_VOL"
    SIDEWAYS_LOW_VOL = "SIDEWAYS_LOW_VOL"
    SIDEWAYS_HIGH_VOL = "SIDEWAYS_HIGH_VOL"
    BEAR_HIGH_VOL = "BEAR_HIGH_VOL"
    RECOVERY = "RECOVERY"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class MarketRegimePolicy:
    """Deterministic configuration and threshold policy for market regime classification."""

    def __init__(
        self,
        policy_version: str = "1.0.0",
        min_benchmark_history: int = 120,
        trend_20_target: float = 0.05,
        trend_60_target: float = 0.10,
        trend_dma50_target: float = 0.03,
        trend_dma200_target: float = 0.06,
        bull_trend_threshold: float = 0.25,
        bear_trend_threshold: float = -0.20,
        bull_breadth_threshold: float = 0.15,
        bear_breadth_threshold: float = -0.10,
        high_vol_threshold: float = 0.15,
        low_vol_threshold: float = 0.15,
        stress_threshold: float = 0.40,
        recovery_drawdown_threshold: float = -0.10,
        missing_vix_confidence_penalty: float = 0.15,
        missing_breadth_confidence_penalty: float = 0.25,
    ) -> None:
        self.policy_version = policy_version
        self.min_benchmark_history = min_benchmark_history
        self.trend_20_target = trend_20_target
        self.trend_60_target = trend_60_target
        self.trend_dma50_target = trend_dma50_target
        self.trend_dma200_target = trend_dma200_target
        self.bull_trend_threshold = bull_trend_threshold
        self.bear_trend_threshold = bear_trend_threshold
        self.bull_breadth_threshold = bull_breadth_threshold
        self.bear_breadth_threshold = bear_breadth_threshold
        self.high_vol_threshold = high_vol_threshold
        self.low_vol_threshold = low_vol_threshold
        self.stress_threshold = stress_threshold
        self.recovery_drawdown_threshold = recovery_drawdown_threshold
        self.missing_vix_confidence_penalty = missing_vix_confidence_penalty
        self.missing_breadth_confidence_penalty = missing_breadth_confidence_penalty

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "min_benchmark_history": self.min_benchmark_history,
            "trend_20_target": self.trend_20_target,
            "trend_60_target": self.trend_60_target,
            "trend_dma50_target": self.trend_dma50_target,
            "trend_dma200_target": self.trend_dma200_target,
            "bull_trend_threshold": self.bull_trend_threshold,
            "bear_trend_threshold": self.bear_trend_threshold,
            "bull_breadth_threshold": self.bull_breadth_threshold,
            "bear_breadth_threshold": self.bear_breadth_threshold,
            "high_vol_threshold": self.high_vol_threshold,
            "low_vol_threshold": self.low_vol_threshold,
            "stress_threshold": self.stress_threshold,
            "recovery_drawdown_threshold": self.recovery_drawdown_threshold,
            "missing_vix_confidence_penalty": self.missing_vix_confidence_penalty,
            "missing_breadth_confidence_penalty": self.missing_breadth_confidence_penalty,
        }

    def compute_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MarketRegimeFeatures:
    """Calculated point-in-time market context features."""

    def __init__(
        self,
        # Trend
        benchmark_ret_20: float | None = None,
        benchmark_ret_60: float | None = None,
        benchmark_ret_120: float | None = None,
        close_vs_50dma: float | None = None,
        close_vs_200dma: float | None = None,
        dma50_slope: float | None = None,
        dma200_slope: float | None = None,
        # Volatility
        realized_vol_20: float | None = None,
        realized_vol_60: float | None = None,
        normalized_atr_14: float | None = None,
        vol_percentile_252: float | None = None,
        india_vix: float | None = None,
        # Breadth
        pct_above_20dma: float | None = None,
        pct_above_50dma: float | None = None,
        pct_above_200dma: float | None = None,
        advance_decline_ratio: float | None = None,
        net_new_highs_lows: float | None = None,
        # Dispersion
        return_dispersion_20: float | None = None,
        vol_dispersion: float | None = None,
        # Liquidity
        median_adv_20: float | None = None,
        market_turnover_ratio: float | None = None,
        liquidity_percentile: float | None = None,
        # Stress
        current_drawdown_252: float | None = None,
        extreme_downside_day_freq: float | None = None,
        gap_frequency: float | None = None,
        volatility_shock_ratio: float | None = None,
        liquidity_deterioration: float | None = None,
    ) -> None:
        self.benchmark_ret_20 = benchmark_ret_20
        self.benchmark_ret_60 = benchmark_ret_60
        self.benchmark_ret_120 = benchmark_ret_120
        self.close_vs_50dma = close_vs_50dma
        self.close_vs_200dma = close_vs_200dma
        self.dma50_slope = dma50_slope
        self.dma200_slope = dma200_slope
        self.realized_vol_20 = realized_vol_20
        self.realized_vol_60 = realized_vol_60
        self.normalized_atr_14 = normalized_atr_14
        self.vol_percentile_252 = vol_percentile_252
        self.india_vix = india_vix
        self.pct_above_20dma = pct_above_20dma
        self.pct_above_50dma = pct_above_50dma
        self.pct_above_200dma = pct_above_200dma
        self.advance_decline_ratio = advance_decline_ratio
        self.net_new_highs_lows = net_new_highs_lows
        self.return_dispersion_20 = return_dispersion_20
        self.vol_dispersion = vol_dispersion
        self.median_adv_20 = median_adv_20
        self.market_turnover_ratio = market_turnover_ratio
        self.liquidity_percentile = liquidity_percentile
        self.current_drawdown_252 = current_drawdown_252
        self.extreme_downside_day_freq = extreme_downside_day_freq
        self.gap_frequency = gap_frequency
        self.volatility_shock_ratio = volatility_shock_ratio
        self.liquidity_deterioration = liquidity_deterioration

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 6) if isinstance(v, float) else v for k, v in self.__dict__.items()}


class MarketRegimeComponentScores:
    """Continuous normalized component scores."""

    def __init__(
        self,
        trend_score: float = 0.0,
        volatility_score: float = 0.0,
        breadth_score: float = 0.0,
        dispersion_score: float = 0.0,
        liquidity_score: float = 0.0,
        stress_score: float = 0.0,
    ) -> None:
        self.trend_score = float(np.clip(trend_score, -1.0, 1.0))
        self.volatility_score = float(np.clip(volatility_score, -1.0, 1.0))
        self.breadth_score = float(np.clip(breadth_score, -1.0, 1.0))
        self.dispersion_score = float(np.clip(dispersion_score, -1.0, 1.0))
        self.liquidity_score = float(np.clip(liquidity_score, -1.0, 1.0))
        self.stress_score = float(np.clip(stress_score, 0.0, 1.0))

    def to_dict(self) -> dict[str, float]:
        return {
            "trend_score": round(self.trend_score, 6),
            "volatility_score": round(self.volatility_score, 6),
            "breadth_score": round(self.breadth_score, 6),
            "dispersion_score": round(self.dispersion_score, 6),
            "liquidity_score": round(self.liquidity_score, 6),
            "stress_score": round(self.stress_score, 6),
        }


class MarketRegimeEvidence:
    """Cryptographic audit evidence binding for a market regime decision."""

    def __init__(
        self,
        benchmark_dataset_id: str | None = None,
        benchmark_content_hash: str | None = None,
        benchmark_bars_count: int = 0,
        universe_snapshot_id: str | None = None,
        universe_member_count: int = 0,
        universe_content_hash: str | None = None,
        vix_dataset_id: str | None = None,
        vix_content_hash: str | None = None,
        as_of: str = "",
        decision_time: str = "",
        cutoff_timestamp: str = "",
    ) -> None:
        self.benchmark_dataset_id = benchmark_dataset_id
        self.benchmark_content_hash = benchmark_content_hash
        self.benchmark_bars_count = benchmark_bars_count
        self.universe_snapshot_id = universe_snapshot_id
        self.universe_member_count = universe_member_count
        self.universe_content_hash = universe_content_hash
        self.vix_dataset_id = vix_dataset_id
        self.vix_content_hash = vix_content_hash
        self.as_of = as_of
        self.decision_time = decision_time
        self.cutoff_timestamp = cutoff_timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_dataset_id": self.benchmark_dataset_id,
            "benchmark_content_hash": self.benchmark_content_hash,
            "benchmark_bars_count": self.benchmark_bars_count,
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_member_count": self.universe_member_count,
            "universe_content_hash": self.universe_content_hash,
            "vix_dataset_id": self.vix_dataset_id,
            "vix_content_hash": self.vix_content_hash,
            "as_of": self.as_of,
            "decision_time": self.decision_time,
            "cutoff_timestamp": self.cutoff_timestamp,
        }

    def compute_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MarketRegimeSnapshot:
    """Immutable, auditable market regime snapshot."""

    def __init__(
        self,
        regime_id: str,
        market: str,
        benchmark: str,
        context_type: MarketContextType,
        as_of: str,
        decision_time: str,
        raw_regime: RawMarketRegime,
        confidence: float,
        component_scores: MarketRegimeComponentScores,
        features: MarketRegimeFeatures,
        input_evidence: MarketRegimeEvidence,
        input_evidence_hash: str,
        model_version: str,
        policy_version: str,
        policy_hash: str,
        calendar_version: str,
        missing_evidence: list[str],
        created_at: str | None = None,
    ) -> None:
        self.regime_id = regime_id
        self.market = market
        self.benchmark = benchmark
        self.context_type = context_type
        self.as_of = as_of
        self.decision_time = decision_time
        self.raw_regime = raw_regime
        self.confidence = float(np.clip(confidence, 0.0, 1.0))
        self.component_scores = component_scores
        self.features = features
        self.input_evidence = input_evidence
        self.input_evidence_hash = input_evidence_hash
        self.model_version = model_version
        self.policy_version = policy_version
        self.policy_hash = policy_hash
        self.calendar_version = calendar_version
        self.missing_evidence = missing_evidence
        self.created_at = created_at or datetime.datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime_id": self.regime_id,
            "market": self.market,
            "benchmark": self.benchmark,
            "context_type": self.context_type.value,
            "as_of": self.as_of,
            "decision_time": self.decision_time,
            "raw_regime": self.raw_regime.value,
            "confidence": round(self.confidence, 4),
            "trend_score": round(self.component_scores.trend_score, 6),
            "volatility_score": round(self.component_scores.volatility_score, 6),
            "breadth_score": round(self.component_scores.breadth_score, 6),
            "dispersion_score": round(self.component_scores.dispersion_score, 6),
            "liquidity_score": round(self.component_scores.liquidity_score, 6),
            "stress_score": round(self.component_scores.stress_score, 6),
            "input_evidence_json": json.dumps(self.input_evidence.to_dict(), sort_keys=True),
            "input_evidence_hash": self.input_evidence_hash,
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "calendar_version": self.calendar_version,
            "missing_evidence_json": json.dumps(self.missing_evidence),
            "created_at": self.created_at,
        }


class MarketRegimeEngine:
    """Causal, deterministic point-in-time market regime engine."""

    MODEL_VERSION = "1.0.0"
    NAMESPACE_REGIME = uuid.UUID("3c4d5e6f-7a8b-9c0d-1e2f-3a4b5c6d7e8f")

    def __init__(
        self,
        policy: MarketRegimePolicy | None = None,
        market_calendar: MarketCalendar | None = None,
    ) -> None:
        self.policy = policy or MarketRegimePolicy()
        self.calendar = market_calendar or build_nse_calendar()

    def evaluate_market_regime(
        self,
        market: str,
        benchmark: str,
        context_type: MarketContextType,
        as_of: datetime.date | str,
        decision_time: datetime.datetime | str,
        benchmark_daily_bars: pd.DataFrame,
        benchmark_intraday_bars: pd.DataFrame | None = None,
        universe_daily_bars: dict[str, pd.DataFrame] | None = None,
        pit_universe_members: list[str] | None = None,
        vix_bars: pd.DataFrame | None = None,
        evidence_metadata: dict[str, Any] | None = None,
    ) -> MarketRegimeSnapshot:
        """Evaluate market regime under strict point-in-time causality."""
        as_of_date = datetime.date.fromisoformat(str(as_of)) if isinstance(as_of, str) else as_of
        as_of_str = as_of_date.isoformat()

        if isinstance(decision_time, str):
            # Normalize ISO timestamp
            dt_clean = decision_time.replace("Z", "+00:00")
            decision_dt = datetime.datetime.fromisoformat(dt_clean)
        else:
            decision_dt = decision_time

        if decision_dt.tzinfo is None:
            decision_dt = decision_dt.replace(tzinfo=IST)
        decision_time_str = decision_dt.isoformat()

        missing_evidence: list[str] = []
        metadata = evidence_metadata or {}

        # 1. Point-in-time filtering of benchmark evidence
        filtered_daily_bench = pd.DataFrame()
        if benchmark_daily_bars is not None and not benchmark_daily_bars.empty:
            df = benchmark_daily_bars.copy()
            if "date" not in df.columns and "timestamp" in df.columns:
                df["date"] = pd.to_datetime(df["timestamp"]).dt.date
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            if context_type == MarketContextType.INTRADAY:
                # Intraday context cannot see today's daily close
                filtered_daily_bench = df[df["date"] < as_of_date].sort_values("date").copy()
            else:
                # EOD context sees completed session D
                filtered_daily_bench = df[df["date"] <= as_of_date].sort_values("date").copy()

        # Build combined benchmark price series
        bench_prices = pd.Series(dtype=float)
        bench_volumes = pd.Series(dtype=float)

        if not filtered_daily_bench.empty:
            bench_prices = filtered_daily_bench["close"].astype(float).reset_index(drop=True)
            if "volume" in filtered_daily_bench.columns:
                bench_volumes = filtered_daily_bench["volume"].astype(float).reset_index(drop=True)

        # In INTRADAY context, append intraday bar known at or before decision_time
        if context_type == MarketContextType.INTRADAY and benchmark_intraday_bars is not None and not benchmark_intraday_bars.empty:
            idf = benchmark_intraday_bars.copy()
            if "timestamp" in idf.columns:
                idf["dt"] = pd.to_datetime(idf["timestamp"])
                if idf["dt"].dt.tz is None:
                    idf["dt"] = idf["dt"].dt.tz_localize(IST)
                # Keep only bars completed at or before decision_dt
                valid_intraday = idf[idf["dt"] <= decision_dt].sort_values("dt")
                if not valid_intraday.empty:
                    latest_bar = valid_intraday.iloc[-1]
                    bench_prices = pd.concat([bench_prices, pd.Series([float(latest_bar["close"])])], ignore_index=True)
                    if "volume" in valid_intraday.columns:
                        bench_volumes = pd.concat([bench_volumes, pd.Series([float(valid_intraday["volume"].sum())])], ignore_index=True)

        # 2. Check critical benchmark sufficiency
        if len(bench_prices) < self.policy.min_benchmark_history:
            missing_evidence.append(
                f"Insufficient benchmark history: {len(bench_prices)} bars available, {self.policy.min_benchmark_history} required"
            )
            return self._build_insufficient_snapshot(
                market=market,
                benchmark=benchmark,
                context_type=context_type,
                as_of=as_of_str,
                decision_time=decision_time_str,
                missing_evidence=missing_evidence,
                metadata=metadata,
                bench_count=len(bench_prices),
            )

        # 3. Calculate Trend Features
        p_now = float(bench_prices.iloc[-1])
        p_20 = float(bench_prices.iloc[-21]) if len(bench_prices) >= 21 else p_now
        p_60 = float(bench_prices.iloc[-61]) if len(bench_prices) >= 61 else p_now
        p_120 = float(bench_prices.iloc[-121]) if len(bench_prices) >= 121 else p_now

        ret_20 = (p_now - p_20) / p_20 if p_20 > 0 else 0.0
        ret_60 = (p_now - p_60) / p_60 if p_60 > 0 else 0.0
        ret_120 = (p_now - p_120) / p_120 if p_120 > 0 else 0.0

        sma_50_series = bench_prices.rolling(window=50).mean()
        sma_200_series = bench_prices.rolling(window=200).mean()

        sma_50_now = float(sma_50_series.iloc[-1]) if len(bench_prices) >= 50 else p_now
        sma_200_now = float(sma_200_series.iloc[-1]) if len(bench_prices) >= 200 else p_now

        close_vs_50 = (p_now / sma_50_now - 1.0) if sma_50_now > 0 else 0.0
        close_vs_200 = (p_now / sma_200_now - 1.0) if sma_200_now > 0 else 0.0

        # Slopes
        slope_50 = 0.0
        if len(sma_50_series) >= 60 and not np.isnan(sma_50_series.iloc[-11]):
            s_base = float(sma_50_series.iloc[-11])
            if s_base > 0:
                slope_50 = (sma_50_now - s_base) / (10.0 * s_base)

        slope_200 = 0.0
        if len(sma_200_series) >= 220 and not np.isnan(sma_200_series.iloc[-21]):
            s_base200 = float(sma_200_series.iloc[-21])
            if s_base200 > 0:
                slope_200 = (sma_200_now - s_base200) / (20.0 * s_base200)

        # 4. Calculate Volatility Features
        returns = bench_prices.pct_change().dropna()
        realized_vol_20 = float(returns.iloc[-20:].std() * np.sqrt(252)) if len(returns) >= 20 else 0.15
        realized_vol_60 = float(returns.iloc[-60:].std() * np.sqrt(252)) if len(returns) >= 60 else realized_vol_20

        # ATR14 normalized
        norm_atr_14 = 0.015
        if not filtered_daily_bench.empty and len(filtered_daily_bench) >= 15:
            highs = filtered_daily_bench["high"].astype(float)
            lows = filtered_daily_bench["low"].astype(float)
            closes = filtered_daily_bench["close"].astype(float)
            tr = np.maximum(highs - lows, np.maximum(np.abs(highs - closes.shift(1)), np.abs(lows - closes.shift(1))))
            atr14 = float(tr.rolling(14).mean().iloc[-1])
            norm_atr_14 = atr14 / p_now if p_now > 0 else 0.015

        # Realized Vol Percentile over 252 days
        vol_p252 = 0.5
        if len(returns) >= 70:
            rolling_vols = returns.rolling(20).std() * np.sqrt(252)
            valid_vols = rolling_vols.dropna().iloc[-252:]
            if len(valid_vols) >= 20:
                vol_p252 = float((valid_vols < realized_vol_20).mean())

        # VIX observation
        vix_val = None
        if vix_bars is not None and not vix_bars.empty:
            vdf = vix_bars.copy()
            if "timestamp" in vdf.columns:
                vdf["dt"] = pd.to_datetime(vdf["timestamp"])
                if vdf["dt"].dt.tz is None:
                    vdf["dt"] = vdf["dt"].dt.tz_localize(IST)
                valid_vix = vdf[vdf["dt"] <= decision_dt].sort_values("dt")
                if not valid_vix.empty:
                    vix_val = float(valid_vix.iloc[-1]["close"])
            elif "date" in vdf.columns:
                vdf["date_col"] = pd.to_datetime(vdf["date"]).dt.date
                valid_vix = vdf[vdf["date_col"] <= as_of_date].sort_values("date_col")
                if not valid_vix.empty:
                    vix_val = float(valid_vix.iloc[-1]["close"])

        if vix_val is None:
            missing_evidence.append("Optional India VIX not available at decision_time")

        # 5. Calculate Breadth Features (over PIT universe)
        pct_above_20dma = 0.5
        pct_above_50dma = 0.5
        pct_above_200dma = 0.5
        ad_ratio = 0.0
        net_high_low = 0.0
        ret_dispersion_20 = 0.05
        vol_dispersion = 0.05

        has_universe = False
        if pit_universe_members and universe_daily_bars:
            member_above_20 = []
            member_above_50 = []
            member_above_200 = []
            member_ret_1d = []
            member_ret_20d = []
            member_vols = []
            member_high_52w = []
            member_low_52w = []

            for sym in pit_universe_members:
                if sym in universe_daily_bars:
                    udf = universe_daily_bars[sym]
                    if udf is not None and not udf.empty:
                        udf_clean = udf.copy()
                        if "date" not in udf_clean.columns and "timestamp" in udf_clean.columns:
                            udf_clean["date"] = pd.to_datetime(udf_clean["timestamp"]).dt.date
                        elif "date" in udf_clean.columns:
                            udf_clean["date"] = pd.to_datetime(udf_clean["date"]).dt.date

                        if context_type == MarketContextType.INTRADAY:
                            udf_valid = udf_clean[udf_clean["date"] < as_of_date].sort_values("date")
                        else:
                            udf_valid = udf_clean[udf_clean["date"] <= as_of_date].sort_values("date")

                        if len(udf_valid) >= 20:
                            c_series = udf_valid["close"].astype(float).reset_index(drop=True)
                            c_now = float(c_series.iloc[-1])
                            c_prev = float(c_series.iloc[-2]) if len(c_series) >= 2 else c_now
                            ret_1d = (c_now - c_prev) / c_prev if c_prev > 0 else 0.0
                            member_ret_1d.append(ret_1d)

                            sma20 = float(c_series.rolling(20).mean().iloc[-1])
                            member_above_20.append(1.0 if c_now >= sma20 else 0.0)

                            if len(c_series) >= 20:
                                c20 = float(c_series.iloc[-20])
                                member_ret_20d.append((c_now - c20) / c20 if c20 > 0 else 0.0)
                                member_vols.append(float(c_series.pct_change().dropna().iloc[-20:].std() * np.sqrt(252)))

                            if len(c_series) >= 50:
                                sma50 = float(c_series.rolling(50).mean().iloc[-1])
                                member_above_50.append(1.0 if c_now >= sma50 else 0.0)

                            if len(c_series) >= 200:
                                sma200 = float(c_series.rolling(200).mean().iloc[-1])
                                member_above_200.append(1.0 if c_now >= sma200 else 0.0)

                            if len(c_series) >= 252:
                                h252 = float(c_series.iloc[-252:].max())
                                l252 = float(c_series.iloc[-252:].min())
                                member_high_52w.append(1.0 if c_now >= 0.98 * h252 else 0.0)
                                member_low_52w.append(1.0 if c_now <= 1.02 * l252 else 0.0)

            if member_above_20:
                has_universe = True
                pct_above_20dma = float(np.mean(member_above_20))
                pct_above_50dma = float(np.mean(member_above_50)) if member_above_50 else pct_above_20dma
                pct_above_200dma = float(np.mean(member_above_200)) if member_above_200 else pct_above_50dma

                advances = sum(1 for r in member_ret_1d if r > 0.001)
                declines = sum(1 for r in member_ret_1d if r < -0.001)
                total_c = len(member_ret_1d)
                ad_ratio = float((advances - declines) / total_c) if total_c > 0 else 0.0

                if member_high_52w and member_low_52w:
                    net_high_low = float(np.mean(member_high_52w) - np.mean(member_low_52w))

                if len(member_ret_20d) >= 5:
                    ret_dispersion_20 = float(np.std(member_ret_20d))
                if len(member_vols) >= 5:
                    vol_dispersion = float(np.std(member_vols))
        else:
            missing_evidence.append("PIT universe breadth data not provided or empty")

        # 6. Calculate Liquidity & Stress Features
        # Turnover ratio
        turnover_ratio = 1.0
        adv_20 = 1_000_000.0
        if len(bench_volumes) >= 60:
            vol_5 = float(bench_volumes.iloc[-5:].mean())
            vol_60 = float(bench_volumes.iloc[-60:].mean())
            adv_20 = float(bench_volumes.iloc[-20:].mean())
            turnover_ratio = vol_5 / vol_60 if vol_60 > 0 else 1.0

        # Drawdown from 252d peak
        peak_252 = float(bench_prices.iloc[-252:].max()) if len(bench_prices) >= 252 else float(bench_prices.max())
        drawdown_252 = (p_now - peak_252) / peak_252 if peak_252 > 0 else 0.0

        # Downside frequency
        downside_freq = 0.0
        if len(returns) >= 20:
            downside_freq = float((returns.iloc[-20:] <= -0.02).mean())

        # Gap frequency
        gap_freq = 0.0
        if not filtered_daily_bench.empty and len(filtered_daily_bench) >= 21:
            opens = filtered_daily_bench["open"].astype(float).iloc[-20:]
            prev_closes = filtered_daily_bench["close"].astype(float).shift(1).iloc[-20:]
            gaps = np.abs((opens - prev_closes) / prev_closes)
            gap_freq = float((gaps >= 0.01).mean())

        # Vol shock
        vol_shock = max(0.0, (realized_vol_20 / realized_vol_60) - 1.0) if realized_vol_60 > 0 else 0.0
        liq_deterioration = max(0.0, 1.0 - turnover_ratio)

        features = MarketRegimeFeatures(
            benchmark_ret_20=ret_20,
            benchmark_ret_60=ret_60,
            benchmark_ret_120=ret_120,
            close_vs_50dma=close_vs_50,
            close_vs_200dma=close_vs_200,
            dma50_slope=slope_50,
            dma200_slope=slope_200,
            realized_vol_20=realized_vol_20,
            realized_vol_60=realized_vol_60,
            normalized_atr_14=norm_atr_14,
            vol_percentile_252=vol_p252,
            india_vix=vix_val,
            pct_above_20dma=pct_above_20dma,
            pct_above_50dma=pct_above_50dma,
            pct_above_200dma=pct_above_200dma,
            advance_decline_ratio=ad_ratio,
            net_new_highs_lows=net_high_low,
            return_dispersion_20=ret_dispersion_20,
            vol_dispersion=vol_dispersion,
            median_adv_20=adv_20,
            market_turnover_ratio=turnover_ratio,
            liquidity_percentile=0.5,
            current_drawdown_252=drawdown_252,
            extreme_downside_day_freq=downside_freq,
            gap_frequency=gap_freq,
            volatility_shock_ratio=vol_shock,
            liquidity_deterioration=liq_deterioration,
        )

        # 7. Component Scoring
        trend_score = (
            0.25 * (ret_20 / self.policy.trend_20_target)
            + 0.25 * (ret_60 / self.policy.trend_60_target)
            + 0.25 * (close_vs_50 / self.policy.trend_dma50_target)
            + 0.25 * (close_vs_200 / self.policy.trend_dma200_target)
        )

        # Volatility scoring
        vol_abs_norm = float(np.clip((realized_vol_20 - 0.16) / 0.08, -1.0, 1.0))
        vol_pct_norm = 2.0 * (vol_p252 - 0.5)
        vol_score = 0.5 * vol_abs_norm + 0.5 * vol_pct_norm
        if vix_val is not None:
            # Anchor VIX around 15.0 level: 12.0 = -0.3, 20.0 = +0.5
            vix_norm = float(np.clip((vix_val - 15.0) / 10.0, -1.0, 1.0))
            vol_score = 0.6 * vol_score + 0.4 * vix_norm

        # Breadth scoring
        b_50 = 2.0 * pct_above_50dma - 1.0
        b_200 = 2.0 * pct_above_200dma - 1.0
        breadth_score = 0.4 * b_50 + 0.3 * b_200 + 0.3 * ad_ratio

        # Dispersion scoring
        dispersion_score = float(np.clip((ret_dispersion_20 - 0.04) / 0.04, -1.0, 1.0))

        # Liquidity scoring
        liquidity_score = float(np.clip((turnover_ratio - 1.0) / 0.4, -1.0, 1.0))

        # Stress scoring [0.0, 1.0]
        dd_stress = min(1.0, abs(min(0.0, drawdown_252)) / 0.15)
        down_stress = min(1.0, downside_freq / 0.15)
        shock_stress = min(1.0, vol_shock)
        stress_score = 0.4 * dd_stress + 0.3 * down_stress + 0.3 * shock_stress
        if vix_val is not None and vix_val > 24.0:
            stress_score = min(1.0, stress_score + 0.20)

        scores = MarketRegimeComponentScores(
            trend_score=trend_score,
            volatility_score=vol_score,
            breadth_score=breadth_score,
            dispersion_score=dispersion_score,
            liquidity_score=liquidity_score,
            stress_score=stress_score,
        )

        # 8. Deterministic Classification Tree
        raw_regime = RawMarketRegime.SIDEWAYS_LOW_VOL

        if (
            drawdown_252 <= self.policy.recovery_drawdown_threshold
            and (scores.trend_score > 0.0 or slope_50 > 0.0)
            and scores.breadth_score >= 0.0
            and downside_freq <= 0.10
            and vol_shock <= 0.25
        ):
            raw_regime = RawMarketRegime.RECOVERY
        elif scores.trend_score <= self.policy.bear_trend_threshold and (
            scores.breadth_score <= self.policy.bear_breadth_threshold or scores.stress_score >= 0.45
        ):
            raw_regime = RawMarketRegime.BEAR_HIGH_VOL
        elif (
            scores.trend_score >= self.policy.bull_trend_threshold
            and scores.breadth_score >= self.policy.bull_breadth_threshold
            and scores.volatility_score <= self.policy.high_vol_threshold
            and scores.stress_score <= self.policy.stress_threshold
        ):
            raw_regime = RawMarketRegime.BULL_LOW_VOL
        elif (
            scores.trend_score >= self.policy.bull_trend_threshold
            and scores.breadth_score >= 0.05
            and scores.volatility_score > self.policy.high_vol_threshold
        ):
            raw_regime = RawMarketRegime.BULL_HIGH_VOL
        elif scores.volatility_score > self.policy.high_vol_threshold or scores.stress_score >= 0.45:
            raw_regime = RawMarketRegime.SIDEWAYS_HIGH_VOL
        else:
            raw_regime = RawMarketRegime.SIDEWAYS_LOW_VOL

        # 9. Deterministic Confidence Calculation
        confidence = 1.0
        if not has_universe:
            confidence -= self.policy.missing_breadth_confidence_penalty
        if vix_val is None:
            confidence -= self.policy.missing_vix_confidence_penalty
        if len(bench_prices) < 200:
            confidence -= 0.15

        # Ambiguity reduction if right on the boundary
        if abs(scores.trend_score - self.policy.bull_trend_threshold) < 0.05:
            confidence -= 0.05
        if abs(scores.volatility_score - self.policy.high_vol_threshold) < 0.05:
            confidence -= 0.05

        confidence = float(np.clip(confidence, 0.20, 1.0))

        # 10. Audit Evidence & Snapshot
        evidence = MarketRegimeEvidence(
            benchmark_dataset_id=metadata.get("benchmark_dataset_id"),
            benchmark_content_hash=metadata.get("benchmark_content_hash"),
            benchmark_bars_count=len(bench_prices),
            universe_snapshot_id=metadata.get("universe_snapshot_id"),
            universe_member_count=len(pit_universe_members) if pit_universe_members else 0,
            universe_content_hash=metadata.get("universe_content_hash"),
            vix_dataset_id=metadata.get("vix_dataset_id"),
            vix_content_hash=metadata.get("vix_content_hash"),
            as_of=as_of_str,
            decision_time=decision_time_str,
            cutoff_timestamp=decision_time_str,
        )
        evidence_hash = evidence.compute_hash()

        regime_id_str = f"{market}:{benchmark}:{context_type.value}:{as_of_str}:{decision_time_str}:{evidence_hash}:{self.MODEL_VERSION}"
        regime_id = str(uuid.uuid5(self.NAMESPACE_REGIME, regime_id_str))

        return MarketRegimeSnapshot(
            regime_id=regime_id,
            market=market,
            benchmark=benchmark,
            context_type=context_type,
            as_of=as_of_str,
            decision_time=decision_time_str,
            raw_regime=raw_regime,
            confidence=confidence,
            component_scores=scores,
            features=features,
            input_evidence=evidence,
            input_evidence_hash=evidence_hash,
            model_version=self.MODEL_VERSION,
            policy_version=self.policy.policy_version,
            policy_hash=self.policy.compute_hash(),
            calendar_version=getattr(self.calendar, "version", "1.0.0"),
            missing_evidence=missing_evidence,
        )

    def _build_insufficient_snapshot(
        self,
        market: str,
        benchmark: str,
        context_type: MarketContextType,
        as_of: str,
        decision_time: str,
        missing_evidence: list[str],
        metadata: dict[str, Any],
        bench_count: int,
    ) -> MarketRegimeSnapshot:
        evidence = MarketRegimeEvidence(
            benchmark_dataset_id=metadata.get("benchmark_dataset_id"),
            benchmark_content_hash=metadata.get("benchmark_content_hash"),
            benchmark_bars_count=bench_count,
            universe_snapshot_id=metadata.get("universe_snapshot_id"),
            universe_member_count=0,
            universe_content_hash=metadata.get("universe_content_hash"),
            vix_dataset_id=metadata.get("vix_dataset_id"),
            vix_content_hash=metadata.get("vix_content_hash"),
            as_of=as_of,
            decision_time=decision_time,
            cutoff_timestamp=decision_time,
        )
        evidence_hash = evidence.compute_hash()
        regime_id_str = f"{market}:{benchmark}:{context_type.value}:{as_of}:{decision_time}:{evidence_hash}:{self.MODEL_VERSION}"
        regime_id = str(uuid.uuid5(self.NAMESPACE_REGIME, regime_id_str))

        return MarketRegimeSnapshot(
            regime_id=regime_id,
            market=market,
            benchmark=benchmark,
            context_type=context_type,
            as_of=as_of,
            decision_time=decision_time,
            raw_regime=RawMarketRegime.INSUFFICIENT_CONTEXT,
            confidence=0.0,
            component_scores=MarketRegimeComponentScores(),
            features=MarketRegimeFeatures(),
            input_evidence=evidence,
            input_evidence_hash=evidence_hash,
            model_version=self.MODEL_VERSION,
            policy_version=self.policy.policy_version,
            policy_hash=self.policy.compute_hash(),
            calendar_version=getattr(self.calendar, "version", "1.0.0"),
            missing_evidence=missing_evidence,
        )
