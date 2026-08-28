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
from trading_stack.bar_availability import is_bar_available

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
        policy_version: str = "2.3.1",
        min_benchmark_history: int = 220,
        min_component_coverage: float = 0.75,
        min_breadth_coverage: float = 0.80,
        min_liquidity_history: int = 60,
        liquidity_percentile_history: int = 252,
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
        self.min_component_coverage = min_component_coverage
        self.min_breadth_coverage = min_breadth_coverage
        self.min_liquidity_history = min_liquidity_history
        self.liquidity_percentile_history = liquidity_percentile_history
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
        self.trend_weights = {
            "ret20": 0.20, "ret60": 0.20, "ret120": 0.10,
            "close_vs_50": 0.15, "close_vs_200": 0.20,
            "dma50_slope": 0.075, "dma200_slope": 0.075,
        }
        self.trend_hard_required = {"ret20", "ret60", "close_vs_50", "close_vs_200"}
        self.volatility_weights = {
            "realized_vol_20": 0.30, "realized_vol_60": 0.25,
            "normalized_atr_14": 0.25, "vol_percentile_252": 0.10, "india_vix": 0.10,
        }
        self.volatility_hard_required = {
            "realized_vol_20", "realized_vol_60", "normalized_atr_14",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "min_benchmark_history": self.min_benchmark_history,
            "min_component_coverage": self.min_component_coverage,
            "min_breadth_coverage": self.min_breadth_coverage,
            "min_liquidity_history": self.min_liquidity_history,
            "liquidity_percentile_history": self.liquidity_percentile_history,
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
            "trend_weights": self.trend_weights,
            "trend_hard_required": sorted(self.trend_hard_required),
            "volatility_weights": self.volatility_weights,
            "volatility_hard_required": sorted(self.volatility_hard_required),
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
        dispersion_score: float | None = None,
        liquidity_score: float | None = None,
        stress_score: float = 0.0,
    ) -> None:
        self.trend_score = float(np.clip(trend_score, -1.0, 1.0))
        self.volatility_score = float(np.clip(volatility_score, -1.0, 1.0))
        self.breadth_score = float(np.clip(breadth_score, -1.0, 1.0))
        self.dispersion_score = float(np.clip(dispersion_score, -1.0, 1.0)) if dispersion_score is not None else None
        self.liquidity_score = float(np.clip(liquidity_score, -1.0, 1.0)) if liquidity_score is not None else None
        self.stress_score = float(np.clip(stress_score, 0.0, 1.0))

    def to_dict(self) -> dict[str, float | None]:
        return {
            "trend_score": round(self.trend_score, 6),
            "volatility_score": round(self.volatility_score, 6),
            "breadth_score": round(self.breadth_score, 6),
            "dispersion_score": round(self.dispersion_score, 6) if self.dispersion_score is not None else None,
            "liquidity_score": round(self.liquidity_score, 6) if self.liquidity_score is not None else None,
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
        evidence_manifest: dict[str, Any] | None = None,
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
        self.evidence_manifest = evidence_manifest or {}

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
            "evidence_manifest": self.evidence_manifest,
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
        component_evidence: dict[str, Any] | None = None,
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
        self.component_evidence = component_evidence or {}
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
            **self.component_scores.to_dict(),
            "input_evidence_json": json.dumps(self.input_evidence.to_dict(), sort_keys=True),
            "input_evidence_hash": self.input_evidence_hash,
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "calendar_version": self.calendar_version,
            "missing_evidence_json": json.dumps(self.missing_evidence),
            "input_evidence_manifest_json": json.dumps(self.input_evidence.evidence_manifest, sort_keys=True),
            "component_evidence_json": json.dumps(self.component_evidence, sort_keys=True),
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

            timestamp_col = pd.to_datetime(df.get("timestamp", df["date"]), errors="coerce")
            filtered_daily_bench = df[
                timestamp_col.map(lambda value: not pd.isna(value) and is_bar_available(
                    pd.Timestamp(value).to_pydatetime(), "1d", decision_dt, self.calendar
                ))
            ].sort_values("date").copy()
            if context_type == MarketContextType.INTRADAY:
                filtered_daily_bench = filtered_daily_bench[
                    filtered_daily_bench["date"] < as_of_date
                ].copy()

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
                valid_intraday = idf[idf["dt"].map(
                    lambda value: is_bar_available(value.to_pydatetime(), str(idf["timeframe"].iloc[0]) if "timeframe" in idf else "1m", decision_dt, self.calendar)
                )].sort_values("dt")
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
        p_20 = float(bench_prices.iloc[-21]) if len(bench_prices) >= 21 else None
        p_60 = float(bench_prices.iloc[-61]) if len(bench_prices) >= 61 else None
        p_120 = float(bench_prices.iloc[-121]) if len(bench_prices) >= 121 else None

        ret_20 = (p_now - p_20) / p_20 if p_20 is not None and p_20 > 0 else None
        ret_60 = (p_now - p_60) / p_60 if p_60 is not None and p_60 > 0 else None
        ret_120 = (p_now - p_120) / p_120 if p_120 is not None and p_120 > 0 else None

        sma_50_series = bench_prices.rolling(window=50).mean()
        sma_200_series = bench_prices.rolling(window=200).mean()

        sma_50_now = float(sma_50_series.iloc[-1]) if len(bench_prices) >= 50 else None
        sma_200_now = float(sma_200_series.iloc[-1]) if len(bench_prices) >= 200 else None

        close_vs_50 = (p_now / sma_50_now - 1.0) if sma_50_now is not None and sma_50_now > 0 else None
        close_vs_200 = (p_now / sma_200_now - 1.0) if sma_200_now is not None and sma_200_now > 0 else None

        # Slopes
        slope_50: float | None = None
        if len(sma_50_series) >= 60 and not np.isnan(sma_50_series.iloc[-11]):
            s_base = float(sma_50_series.iloc[-11])
            if s_base > 0:
                slope_50 = (sma_50_now - s_base) / (10.0 * s_base) if sma_50_now is not None else None

        slope_200: float | None = None
        if len(sma_200_series) >= 220 and not np.isnan(sma_200_series.iloc[-21]):
            s_base200 = float(sma_200_series.iloc[-21])
            if s_base200 > 0:
                slope_200 = (sma_200_now - s_base200) / (20.0 * s_base200) if sma_200_now is not None else None

        # 4. Calculate Volatility Features
        returns = bench_prices.pct_change().dropna()
        realized_vol_20 = float(returns.iloc[-20:].std() * np.sqrt(252)) if len(returns) >= 20 else None
        realized_vol_60 = float(returns.iloc[-60:].std() * np.sqrt(252)) if len(returns) >= 60 else None

        # ATR14 normalized
        norm_atr_14 = None
        if not filtered_daily_bench.empty and len(filtered_daily_bench) >= 15:
            highs = filtered_daily_bench["high"].astype(float)
            lows = filtered_daily_bench["low"].astype(float)
            closes = filtered_daily_bench["close"].astype(float)
            tr = np.maximum(highs - lows, np.maximum(np.abs(highs - closes.shift(1)), np.abs(lows - closes.shift(1))))
            atr14 = float(tr.rolling(14).mean().iloc[-1])
            norm_atr_14 = atr14 / p_now if p_now > 0 else None

        # Realized Vol Percentile over 252 days
        vol_p252 = None
        if realized_vol_20 is not None and len(returns) >= 252:
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
        pct_above_20dma = None
        pct_above_50dma = None
        pct_above_200dma = None
        ad_ratio = None
        net_high_low = None
        ret_dispersion_20 = None
        vol_dispersion = None

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
            member_traded_values_20 = []
            member_turnover_ratios = []
            market_traded_values_by_date: dict[datetime.date, list[float]] = {}

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
                                if "volume" in udf_valid.columns:
                                    traded_values = c_series * udf_valid["volume"].astype(float).reset_index(drop=True)
                                    for session_date, traded_value in zip(udf_valid["date"], traded_values):
                                        market_traded_values_by_date.setdefault(session_date, []).append(float(traded_value))
                                    member_traded_values_20.append(float(traded_values.iloc[-20:].median()))
                                    if len(traded_values) >= 60:
                                        base = float(traded_values.iloc[-60:].mean())
                                        if base > 0:
                                            member_turnover_ratios.append(float(traded_values.iloc[-5:].mean()) / base)

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
                total_members = len(pit_universe_members)
                coverage = min(
                    len(member_above_20), len(member_above_50), len(member_above_200), len(member_ret_1d)
                ) / total_members
                if coverage < self.policy.min_breadth_coverage:
                    missing_evidence.append(
                        f"Insufficient critical breadth coverage: {coverage:.1%} available, {self.policy.min_breadth_coverage:.0%} required"
                    )
                    return self._build_insufficient_snapshot(
                        market=market, benchmark=benchmark, context_type=context_type, as_of=as_of_str,
                        decision_time=decision_time_str, missing_evidence=missing_evidence, metadata=metadata,
                        bench_count=len(bench_prices),
                    )
                has_universe = True
                pct_above_20dma = float(np.mean(member_above_20))
                pct_above_50dma = float(np.mean(member_above_50))
                pct_above_200dma = float(np.mean(member_above_200))

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
            return self._build_insufficient_snapshot(
                market=market, benchmark=benchmark, context_type=context_type, as_of=as_of_str,
                decision_time=decision_time_str, missing_evidence=missing_evidence, metadata=metadata,
                bench_count=len(bench_prices),
            )

        if not has_universe:
            missing_evidence.append("No members have complete critical breadth history")
            return self._build_insufficient_snapshot(
                market=market, benchmark=benchmark, context_type=context_type, as_of=as_of_str,
                decision_time=decision_time_str, missing_evidence=missing_evidence, metadata=metadata,
                bench_count=len(bench_prices),
            )

        if any(value is None for value in (close_vs_50, close_vs_200, pct_above_50dma, pct_above_200dma, ad_ratio)):
            missing_evidence.append("Critical trend or breadth feature unavailable")
            return self._build_insufficient_snapshot(
                market=market, benchmark=benchmark, context_type=context_type, as_of=as_of_str,
                decision_time=decision_time_str, missing_evidence=missing_evidence, metadata=metadata,
                bench_count=len(bench_prices),
            )

        assert close_vs_50 is not None and close_vs_200 is not None
        assert pct_above_50dma is not None and pct_above_200dma is not None and ad_ratio is not None

        # 6. Calculate Liquidity & Stress Features
        # Turnover ratio
        market_liquidity_series = [sum(values) for _, values in sorted(market_traded_values_by_date.items())]
        turnover_ratio = None
        if len(market_liquidity_series) >= self.policy.min_liquidity_history:
            baseline_turnover = float(np.mean(market_liquidity_series[-self.policy.min_liquidity_history:]))
            if baseline_turnover > 0:
                turnover_ratio = float(np.mean(market_liquidity_series[-5:]) / baseline_turnover)
        adv_20 = float(np.median(member_traded_values_20)) if member_traded_values_20 else None
        liquidity_percentile = None
        if len(market_liquidity_series) >= self.policy.liquidity_percentile_history:
            trailing_liquidity = market_liquidity_series[-self.policy.liquidity_percentile_history:]
            liquidity_percentile = float(
                np.mean(np.asarray(trailing_liquidity) <= trailing_liquidity[-1])
            )

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
        vol_shock = (
            max(0.0, (realized_vol_20 / realized_vol_60) - 1.0)
            if realized_vol_20 is not None and realized_vol_60 is not None and realized_vol_60 > 0 else None
        )
        liq_deterioration = max(0.0, 1.0 - turnover_ratio) if turnover_ratio is not None else None

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
            liquidity_percentile=liquidity_percentile,
            current_drawdown_252=drawdown_252,
            extreme_downside_day_freq=downside_freq,
            gap_frequency=gap_freq,
            volatility_shock_ratio=vol_shock,
            liquidity_deterioration=liq_deterioration,
        )

        # 7. Component scoring. Missing evidence is never neutralized: hard
        # requirements fail closed and optional values renormalize their weights.
        trend_values = {
            "ret20": None if ret_20 is None else ret_20 / self.policy.trend_20_target,
            "ret60": None if ret_60 is None else ret_60 / self.policy.trend_60_target,
            "ret120": None if ret_120 is None else ret_120 / self.policy.trend_60_target,
            "close_vs_50": None if close_vs_50 is None else close_vs_50 / self.policy.trend_dma50_target,
            "close_vs_200": None if close_vs_200 is None else close_vs_200 / self.policy.trend_dma200_target,
            "dma50_slope": slope_50,
            "dma200_slope": slope_200,
        }
        volatility_values = {
            "realized_vol_20": None if realized_vol_20 is None else float(np.clip((realized_vol_20 - 0.16) / 0.08, -1.0, 1.0)),
            "realized_vol_60": None if realized_vol_60 is None else float(np.clip((realized_vol_60 - 0.16) / 0.08, -1.0, 1.0)),
            "normalized_atr_14": None if norm_atr_14 is None else float(np.clip((norm_atr_14 - 0.015) / 0.015, -1.0, 1.0)),
            "vol_percentile_252": None if vol_p252 is None else 2.0 * (vol_p252 - 0.5),
            "india_vix": None if vix_val is None else float(np.clip((vix_val - 15.0) / 10.0, -1.0, 1.0)),
        }

        def weighted_component(
            values: dict[str, float | None], weights: dict[str, float], hard_required: set[str], name: str,
        ) -> tuple[float, float]:
            missing_hard = sorted(feature for feature in hard_required if values[feature] is None)
            coverage = sum(weights[feature] for feature, value in values.items() if value is not None)
            if missing_hard or coverage < self.policy.min_component_coverage:
                missing_evidence.append(
                    f"{name} evidence insufficient: coverage={coverage:.1%}; missing={','.join(missing_hard)}"
                )
                raise ValueError("insufficient_component_evidence")
            return (
                sum(weights[feature] * value for feature, value in values.items() if value is not None) / coverage,
                coverage,
            )

        try:
            trend_score, trend_coverage = weighted_component(
                trend_values, self.policy.trend_weights, self.policy.trend_hard_required, "Trend",
            )
            vol_score, volatility_coverage = weighted_component(
                volatility_values, self.policy.volatility_weights, self.policy.volatility_hard_required, "Volatility",
            )
        except ValueError:
            return self._build_insufficient_snapshot(
                market=market, benchmark=benchmark, context_type=context_type, as_of=as_of_str,
                decision_time=decision_time_str, missing_evidence=missing_evidence, metadata=metadata,
                bench_count=len(bench_prices),
            )

        # Breadth scoring
        b_50 = 2.0 * pct_above_50dma - 1.0
        b_200 = 2.0 * pct_above_200dma - 1.0
        breadth_score = 0.4 * b_50 + 0.3 * b_200 + 0.3 * ad_ratio

        # Dispersion scoring
        dispersion_score = (
            float(np.clip((ret_dispersion_20 - 0.04) / 0.04, -1.0, 1.0))
            if ret_dispersion_20 is not None else None
        )

        # Liquidity scoring
        liquidity_score = float(np.clip((turnover_ratio - 1.0) / 0.4, -1.0, 1.0)) if turnover_ratio is not None else None

        # Stress scoring [0.0, 1.0]
        dd_stress = min(1.0, abs(min(0.0, drawdown_252)) / 0.15)
        down_stress = min(1.0, downside_freq / 0.15)
        shock_stress = min(1.0, vol_shock) if vol_shock is not None else 0.0
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
            and (scores.trend_score > 0.0 or (slope_50 is not None and slope_50 > 0.0))
            and scores.breadth_score >= 0.0
            and downside_freq <= 0.10
            and (vol_shock is None or vol_shock <= 0.25)
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
        # Use caller-supplied cutoff_timestamp (from load_regime_bars) when available;
        # it records the exact data-layer PIT cutoff that was applied.
        cutoff_ts = metadata.get("cutoff_timestamp") or decision_time_str
        policy_hash = self.policy.compute_hash()
        calendar_version = getattr(self.calendar, "version", "1.0.0")
        manifest = {
            "market": market, "benchmark": benchmark, "context_type": context_type.value,
            "as_of": as_of_str, "decision_time": decision_time_str,
            "benchmark_daily": metadata.get("benchmark_daily_evidence", {
                "available": False, "reason": "NO_CAUSAL_CERTIFIED_BENCHMARK",
            }),
            "benchmark_intraday": metadata.get("benchmark_intraday_evidence", {"available": False}),
            "vix": metadata.get("vix_evidence", {"available": vix_val is not None, "dataset_id": metadata.get("vix_dataset_id"), "content_hash": metadata.get("vix_content_hash")}),
            "universe": metadata.get("universe_manifest", {}),
            "component_coverage": {
                "trend": trend_coverage, "volatility": volatility_coverage,
                "breadth": coverage, "liquidity": len(member_traded_values_20) / len(pit_universe_members),
            },
            "model_version": self.MODEL_VERSION, "policy_version": self.policy.policy_version,
            "policy_hash": policy_hash, "calendar_version": calendar_version,
        }
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
            cutoff_timestamp=cutoff_ts,
            evidence_manifest=manifest,
        )
        evidence_hash = evidence.compute_hash()

        regime_id_str = f"{market}:{benchmark}:{context_type.value}:{as_of_str}:{decision_time_str}:{evidence_hash}:{self.MODEL_VERSION}:{policy_hash}:{calendar_version}"
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
            policy_hash=policy_hash,
            calendar_version=calendar_version,
            missing_evidence=missing_evidence,
            component_evidence=manifest["component_coverage"],
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
        cutoff_ts = metadata.get("cutoff_timestamp") or decision_time
        policy_hash = self.policy.compute_hash()
        calendar_version = getattr(self.calendar, "version", "1.0.0")
        manifest = {
            "market": market,
            "benchmark": benchmark,
            "context_type": context_type.value,
            "as_of": as_of,
            "decision_time": decision_time,
            "benchmark_daily": metadata.get("benchmark_daily_evidence", {
                "available": False, "reason": "NO_CAUSAL_CERTIFIED_BENCHMARK",
            }),
            "benchmark_intraday": metadata.get("benchmark_intraday_evidence", {"available": False}),
            "vix": metadata.get(
                "vix_evidence",
                {
                    "available": False,
                    "dataset_id": metadata.get("vix_dataset_id"),
                    "content_hash": metadata.get("vix_content_hash"),
                },
            ),
            "universe": metadata.get("universe_manifest", {}),
            "component_coverage": metadata.get(
                "component_coverage",
                {"trend": 0.0, "volatility": 0.0, "breadth": 0.0, "liquidity": 0.0},
            ),
            "missing_evidence": missing_evidence,
            "model_version": self.MODEL_VERSION,
            "policy_version": self.policy.policy_version,
            "policy_hash": policy_hash,
            "calendar_version": calendar_version,
        }
        evidence = MarketRegimeEvidence(
            benchmark_dataset_id=metadata.get("benchmark_dataset_id"),
            benchmark_content_hash=metadata.get("benchmark_content_hash"),
            benchmark_bars_count=bench_count,
            universe_snapshot_id=metadata.get("universe_snapshot_id"),
            universe_member_count=metadata.get("universe_manifest", {}).get("total_member_count", 0),
            universe_content_hash=metadata.get("universe_content_hash"),
            vix_dataset_id=metadata.get("vix_dataset_id"),
            vix_content_hash=metadata.get("vix_content_hash"),
            as_of=as_of,
            decision_time=decision_time,
            cutoff_timestamp=cutoff_ts,
            evidence_manifest=manifest,
        )
        evidence_hash = evidence.compute_hash()
        regime_id_str = f"{market}:{benchmark}:{context_type.value}:{as_of}:{decision_time}:{evidence_hash}:{self.MODEL_VERSION}:{policy_hash}:{calendar_version}"
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
            policy_hash=policy_hash,
            calendar_version=calendar_version,
            missing_evidence=missing_evidence,
            component_evidence=manifest["component_coverage"],
        )
