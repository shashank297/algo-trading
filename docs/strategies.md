# Strategies

The registry auto-discovers 20 long-only delivery-research strategies plus inactive compatibility strategy `opening_range_breakout`.

Single-asset: `trend_following`, `time_series_momentum`, `donchian_trend`, `mean_reversion`, `rsi_pullback`, `bollinger_pullback`, `donchian_breakout`, `volume_confirmed_breakout`, and `volatility_contraction_breakout`.

Cross-sectional: `cross_sectional_momentum`, `fifty_two_week_high`, `consistent_momentum`, `residual_momentum`, `sector_relative_momentum`, `cross_sectional_short_term_reversal`, `low_volatility`, `low_beta`, `momentum_reversal_volatility`, `ohlcv_multi_factor`, and `walk_forward_logistic`.

Every class declares version, family, scope, features/lookback, rebalance frequency, paper eligibility, source, and bounded parameters. Cross-sectional strategies rank only symbols with sufficient causal history.

The logistic strategy trains only on labels known before each prediction date. `opening_range_breakout` has `paper_eligible=False`. `legacy_seven_condition_buy` remains absent until its exact original rules are supplied.
