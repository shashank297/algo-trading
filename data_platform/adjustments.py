"""Mathematical adjustment engine for stock splits, bonuses, consolidations, and total return series."""

from __future__ import annotations


import numpy as np
import pandas as pd
from loguru import logger

from data_platform.contracts import PriceAdjustment
from data_platform.source_semantics import (
    SourceBarSemantics,
    SourceSemanticsAdapter,
    UnsupportedAdjustmentConversion,
    VolumeAdjustment,
)


def _to_ist_dates(timestamps: pd.Series) -> np.ndarray:

    """Convert any timestamp series (UTC, tz-naive, or IST) into Asia/Kolkata calendar dates."""
    ts = pd.to_datetime(timestamps)
    if ts.dt.tz is None:
        # Treat tz-naive as UTC first, then convert to IST
        ts = ts.dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata")
    else:
        ts = ts.dt.tz_convert("Asia/Kolkata")
    return np.asarray(ts.dt.date)


class PriceAdjustmentEngine:
    """Apply backward price and volume adjustments to OHLCV historical bars."""

    @classmethod
    def calculate_split_factors(
        cls,
        bar_timestamps: pd.Series,
        corporate_actions: pd.DataFrame,
    ) -> pd.Series:
        """Calculate cumulative backward share multiplier for each bar date.

        For bars strictly before an ex-date (session_date < ex_date), the cumulative multiplier
        is the product of all share_multipliers with ex_date > session_date.
        For bars on or after the ex-date, the multiplier is 1.0.

        Args:
            bar_timestamps: Series of bar timestamps.
            corporate_actions: DataFrame containing 'ex_date', 'action_type', and 'share_multiplier'.

        Returns:
            pd.Series: Multiplier for each bar in bar_timestamps.
        """
        if corporate_actions.empty or bar_timestamps.empty:
            return pd.Series(1.0, index=bar_timestamps.index, dtype="float64")

        multiplier_col = "share_multiplier" if "share_multiplier" in corporate_actions.columns else "split_factor"

        splits = corporate_actions[
            corporate_actions["action_type"].isin(["SPLIT", "BONUS", "CONSOLIDATION"])
            & (corporate_actions[multiplier_col] > 0)
        ].copy()

        if splits.empty:
            return pd.Series(1.0, index=bar_timestamps.index, dtype="float64")

        splits["ex_date"] = pd.to_datetime(splits["ex_date"]).dt.date
        bar_dates = _to_ist_dates(bar_timestamps)

        # Sort ex-dates descending
        splits_sorted = splits.sort_values("ex_date", ascending=False)

        multipliers = np.ones(len(bar_dates), dtype="float64")

        for _, row in splits_sorted.iterrows():
            ex_d = row["ex_date"]
            factor = float(row[multiplier_col])
            if factor != 1.0 and factor > 0:
                mask = np.array([d < ex_d for d in bar_dates], dtype=bool)
                multipliers[mask] *= factor

        return pd.Series(multipliers, index=bar_timestamps.index, dtype="float64")

    @classmethod
    def calculate_dividend_factors(
        cls,
        bars: pd.DataFrame,
        corporate_actions: pd.DataFrame,
        is_split_adjusted: bool = False,
    ) -> pd.Series:
        """Calculate cumulative continuity discount factors for cash dividends.

        F_k = 1.0 - (D_k / P_prev_k) where P_prev_k is the official close of the active
        trading session immediately prior to ex_date_k.

        Args:
            bars: OHLCV DataFrame sorted by timestamp ascending.
            corporate_actions: DataFrame containing 'ex_date', 'action_type', and 'dividend_amount'.
            is_split_adjusted: Whether prices in `bars` have already been split-adjusted.

        Returns:
            pd.Series: Multiplier for each bar in bars.
        """
        if corporate_actions.empty or bars.empty:
            return pd.Series(1.0, index=bars.index, dtype="float64")

        divs = corporate_actions[
            (corporate_actions["action_type"] == "DIVIDEND") & (corporate_actions["dividend_amount"] > 0)
        ].copy()

        if divs.empty:
            return pd.Series(1.0, index=bars.index, dtype="float64")

        multiplier_col = "share_multiplier" if "share_multiplier" in corporate_actions.columns else "split_factor"
        splits = (
            corporate_actions[
                corporate_actions["action_type"].isin(["SPLIT", "BONUS", "CONSOLIDATION"])
                & (corporate_actions[multiplier_col] > 0)
            ].copy()
            if is_split_adjusted
            else pd.DataFrame()
        )

        divs["ex_date"] = pd.to_datetime(divs["ex_date"]).dt.date
        if not splits.empty:
            splits["ex_date"] = pd.to_datetime(splits["ex_date"]).dt.date

        # Aggregate multiple distributions on the same ex-date (e.g. Regular ₹2 + Special ₹3 = ₹5)
        div_agg = divs.groupby("ex_date", as_index=False).agg({"dividend_amount": "sum"})
        div_grouped = pd.DataFrame(div_agg).sort_values("ex_date", ascending=False)
        bar_dates = _to_ist_dates(bars["timestamp"])
        bar_closes = bars["close"].values

        multipliers = np.ones(len(bars), dtype="float64")

        for _, row in div_grouped.iterrows():
            ex_d = row["ex_date"]
            div_amt = float(row["dividend_amount"])

            # If input bars are already split-adjusted, normalize nominal dividend by subsequent splits
            if is_split_adjusted and not splits.empty:
                subsequent_splits = splits[splits["ex_date"] > ex_d]
                forward_split_factor = 1.0
                for _, s_row in subsequent_splits.iterrows():
                    forward_split_factor *= float(s_row[multiplier_col])
                if forward_split_factor > 0:
                    div_amt = div_amt / forward_split_factor

            # Find the closing price of the trading session immediately prior to ex_date
            mask = np.array([d < ex_d for d in bar_dates], dtype=bool)
            pre_ex_indices = np.flatnonzero(mask)
            if len(pre_ex_indices) == 0:
                continue

            last_pre_ex_idx = pre_ex_indices[-1]
            pre_ex_close = float(bar_closes[last_pre_ex_idx])

            if pre_ex_close > div_amt:
                factor = 1.0 - (div_amt / pre_ex_close)
                multipliers[pre_ex_indices] *= factor
            else:
                logger.warning(
                    "Dividend amount {} >= pre-ex close {} on ex-date {}. Skipping dividend factor.",
                    div_amt,
                    pre_ex_close,
                    ex_d,
                )

        return pd.Series(multipliers, index=bars.index, dtype="float64")

    @classmethod
    def adjust_ohlcv(
        cls,
        bars: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
        adjustment: PriceAdjustment | str = PriceAdjustment.UNADJUSTED,
        source_semantics: SourceBarSemantics | None = None,
    ) -> pd.DataFrame:
        """Apply backward price and volume adjustments to an OHLCV DataFrame with source-semantics awareness.

        Args:
            bars: Input OHLCV DataFrame.
            corporate_actions: Optional corporate actions DataFrame.
            adjustment: Target requested adjustment mode.
            source_semantics: Optional explicit source bar semantics (price & volume basis).

        Returns:
            pd.DataFrame: Adjusted copy of the OHLCV bars.

        Raises:
            UnsupportedAdjustmentConversion: If requested conversion is impossible (e.g. SPLIT_ADJUSTED -> UNADJUSTED).
        """
        if bars.empty:
            return bars.copy()

        # Parse target adjustment
        if isinstance(adjustment, PriceAdjustment):
            target_adj = adjustment
        else:
            raw_val = str(getattr(adjustment, "value", adjustment)).upper()
            if raw_val.startswith("PRICEADJUSTMENT."):
                raw_val = raw_val.split(".", 1)[1]
            target_adj = PriceAdjustment(raw_val)

        # Determine source semantics
        if source_semantics is None:
            source_semantics = SourceSemanticsAdapter.infer_semantics(
                bars=bars,
                corporate_actions=corporate_actions,
            )

        # Ground-truth admission gateway invariant check
        source_semantics.require_admitted()

        source_adj = source_semantics.price_adjustment
        volume_basis = source_semantics.volume_adjustment



        # Illegal reverse-adjustments
        if source_adj in (PriceAdjustment.SPLIT_ADJUSTED, PriceAdjustment.BACK_ADJUSTED) and target_adj == PriceAdjustment.UNADJUSTED:
            raise UnsupportedAdjustmentConversion(
                f"Cannot reverse-adjust {source_adj.value} provider data back to {target_adj.value} "
                f"without original raw trade-basis records."
            )

        if source_adj == PriceAdjustment.BACK_ADJUSTED and target_adj != PriceAdjustment.BACK_ADJUSTED:
            raise UnsupportedAdjustmentConversion(
                f"Cannot deconstruct {source_adj.value} series into {target_adj.value}."
            )

        if corporate_actions is None or corporate_actions.empty:
            result = bars.copy()
            result["adjustment"] = target_adj.value
            return result

        result = bars.copy()
        split_multipliers = cls.calculate_split_factors(result["timestamp"], corporate_actions)

        # 1. Independent Price Conversion
        if source_adj == target_adj:
            # Price is already in target representation (no-op)
            pass
        elif source_adj == PriceAdjustment.UNADJUSTED and target_adj == PriceAdjustment.SPLIT_ADJUSTED:
            for col in ["open", "high", "low", "close"]:
                if col in result.columns:
                    result[col] = result[col] / split_multipliers
        elif source_adj == PriceAdjustment.UNADJUSTED and target_adj == PriceAdjustment.BACK_ADJUSTED:
            div_multipliers = cls.calculate_dividend_factors(result, corporate_actions, is_split_adjusted=False)
            total_price_factors = split_multipliers / div_multipliers
            for col in ["open", "high", "low", "close"]:
                if col in result.columns:
                    result[col] = result[col] / total_price_factors
        elif source_adj == PriceAdjustment.SPLIT_ADJUSTED and target_adj == PriceAdjustment.BACK_ADJUSTED:
            div_multipliers = cls.calculate_dividend_factors(result, corporate_actions, is_split_adjusted=True)
            for col in ["open", "high", "low", "close"]:
                if col in result.columns:
                    result[col] = result[col] * div_multipliers

        # 2. Independent Volume Conversion
        # If target adjustment is SPLIT_ADJUSTED or BACK_ADJUSTED, volume should be split-adjusted
        # If volume_basis is UNADJUSTED, scale volume by split multipliers
        target_volume_adj = (
            VolumeAdjustment.SPLIT_ADJUSTED
            if target_adj in (PriceAdjustment.SPLIT_ADJUSTED, PriceAdjustment.BACK_ADJUSTED)
            else VolumeAdjustment.UNADJUSTED
        )

        if "volume" in result.columns:
            if volume_basis == VolumeAdjustment.UNADJUSTED and target_volume_adj == VolumeAdjustment.SPLIT_ADJUSTED:
                result["volume"] = (result["volume"] * split_multipliers).round().astype("int64")

        result["adjustment"] = target_adj.value
        return result




class TotalReturnEngine:
    """Exact dividend-reinvested total return calculation and Total Return Index (TRI)."""

    @classmethod
    def calculate_total_return_series(
        cls,
        bars: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
        source_semantics: SourceBarSemantics | None = None,
    ) -> pd.Series:
        """Compute discrete shareholder total return for each session.

        r_t^TR = (P_t^split + D_t^split) / P_{t-1}^split - 1.0

        Historical cash dividends occurring before subsequent stock splits/bonuses are scaled
        to the matching split-adjusted share basis: D_k^split = D_k / S_forward.

        Args:
            bars: Input OHLCV bars (UNADJUSTED or SPLIT_ADJUSTED).
            corporate_actions: Corporate actions table.
            source_semantics: Optional source bar semantics.

        Returns:
            pd.Series: Daily fractional total return series.
        """
        if bars.empty:
            return pd.Series(dtype="float64")

        # First ensure we have split-adjusted prices
        if corporate_actions is not None and not corporate_actions.empty:
            split_bars = PriceAdjustmentEngine.adjust_ohlcv(
                bars,
                corporate_actions,
                adjustment=PriceAdjustment.SPLIT_ADJUSTED,
                source_semantics=source_semantics,
            )
        else:
            split_bars = bars.copy()

        closes = split_bars["close"].values
        bar_dates = _to_ist_dates(split_bars["timestamp"])

        # Map cash dividends to each session, normalized by subsequent splits
        div_payouts = np.zeros(len(split_bars), dtype="float64")
        if corporate_actions is not None and not corporate_actions.empty:
            divs = corporate_actions[
                (corporate_actions["action_type"] == "DIVIDEND") & (corporate_actions["dividend_amount"] > 0)
            ].copy()

            splits = corporate_actions[
                corporate_actions["action_type"].isin(["SPLIT", "BONUS", "CONSOLIDATION"])
                & (corporate_actions["share_multiplier"] > 0)
            ].copy()

            if not divs.empty:
                divs["ex_date"] = pd.to_datetime(divs["ex_date"]).dt.date
                if not splits.empty:
                    splits["ex_date"] = pd.to_datetime(splits["ex_date"]).dt.date

                for _, row in divs.iterrows():
                    ex_d = row["ex_date"]
                    div_amt = float(row["dividend_amount"])

                    # Calculate subsequent forward split multiplier (splits occurring strictly AFTER this dividend)
                    forward_split_factor = 1.0
                    if not splits.empty:
                        subsequent_splits = splits[splits["ex_date"] > ex_d]
                        for _, s_row in subsequent_splits.iterrows():
                            forward_split_factor *= float(s_row["share_multiplier"])

                    # Normalize dividend amount to post-split share basis
                    normalized_div = div_amt / forward_split_factor if forward_split_factor > 0 else div_amt

                    # Find bars on ex-date
                    mask = np.array([d == ex_d for d in bar_dates], dtype=bool)
                    ex_indices = np.flatnonzero(mask)
                    if len(ex_indices) > 0:
                        div_payouts[ex_indices[0]] += normalized_div


        # Compute total return
        returns = np.zeros(len(split_bars), dtype="float64")
        for i in range(1, len(split_bars)):
            prev_close = closes[i - 1]
            if prev_close > 0:
                returns[i] = (closes[i] + div_payouts[i] - prev_close) / prev_close

        return pd.Series(returns, index=bars.index, name="total_return", dtype="float64")


    @classmethod
    def build_total_return_index(
        cls,
        bars: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
        base_value: float = 100.0,
        source_semantics: SourceBarSemantics | None = None,
    ) -> pd.DataFrame:
        """Construct a Total Return Index (TRI) series starting at base_value.

        Args:
            bars: Input OHLCV bars.
            corporate_actions: Corporate actions table.
            base_value: Initial index value (default 100.0).
            source_semantics: Optional source bar semantics.

        Returns:
            pd.DataFrame: DataFrame with ['timestamp', 'close', 'total_return', 'total_return_index'].
        """
        if bars.empty:
            return pd.DataFrame(columns=["timestamp", "close", "total_return", "total_return_index"])

        tr_series = cls.calculate_total_return_series(bars, corporate_actions, source_semantics=source_semantics)
        tri_values = np.zeros(len(bars), dtype="float64")
        tri_values[0] = base_value

        for i in range(1, len(bars)):
            tri_values[i] = tri_values[i - 1] * (1.0 + tr_series.iloc[i])

        result = pd.DataFrame(
            {
                "timestamp": bars["timestamp"].values,
                "close": bars["close"].values,
                "total_return": tr_series.values,
                "total_return_index": tri_values,
            },
            index=bars.index,
        )
        return result

