"""Property-based tests ensuring strictly causal, zero-lookahead feature computation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from trading_stack.features import FeatureFactory


def test_feature_causality_rolling_invariance():
    """Modifying future prices must not alter historical feature values at prior timestamps."""
    dates = pd.date_range("2026-01-01", periods=100, freq="B", tz="UTC")
    np.random.seed(42)
    prices = 100.0 + np.cumsum(np.random.randn(100))

    df_base = pd.DataFrame({
        "timestamp": dates,
        "symbol": "TEST",
        "open": prices,
        "high": prices + 1.0,
        "low": prices - 1.0,
        "close": prices,
        "volume": 10_000.0,
    })

    # Modified dataset where last 20 bars are altered
    df_modified = df_base.copy()
    df_modified.loc[80:, "close"] = df_modified.loc[80:, "close"] * 5.0
    df_modified.loc[80:, "high"] = df_modified.loc[80:, "high"] * 5.0

    factory = FeatureFactory()
    feat_base = factory.build(df_base)
    feat_mod = factory.build(df_modified)

    # First 80 bars of feature values must match identically (0 lookahead)
    cols_to_compare = [c for c in feat_base.columns if c not in ("timestamp", "symbol")]
    for col in cols_to_compare:
        base_slice = feat_base.loc[:79, col].dropna()
        mod_slice = feat_mod.loc[:79, col].dropna()
        pd.testing.assert_series_equal(
            base_slice,
            mod_slice,
            check_names=False,
            obj=f"Feature {col} violated causality!",
        )
