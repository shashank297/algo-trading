import pandas as pd
import numpy as np
from pathlib import Path

from trading_stack.strategy_library.single_asset import BollingerPullbackStrategy

def test_bollinger_pullback_golden_file():
    """M3: Golden-file regression test for bollinger_pullback"""
    # Load the golden file data
    golden_path = Path(__file__).parent / 'golden_bollinger_pullback.csv'
    golden_df = pd.read_csv(golden_path, parse_dates=['timestamp'])
    
    # Extract the original input columns
    input_df = golden_df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
    
    # Re-run the strategy
    strat = BollingerPullbackStrategy()
    signals = strat.generate_signals(input_df)
    
    # Assert that the output matches the golden file
    # We compare the target_position, reason, size columns
    pd.testing.assert_series_equal(signals['target_position'], golden_df['target_position'], check_names=False)
    # the reason column might have NaN parsed as float in csv if empty
    golden_reason = golden_df['reason'].fillna('').astype(str)
    signals_reason = signals['reason'].fillna('').astype(str)
    pd.testing.assert_series_equal(signals_reason, golden_reason, check_names=False)
    pd.testing.assert_series_equal(signals['target_weight'], golden_df['target_weight'], check_names=False)

def test_single_asset_signals_format():
    """M2: Add per-strategy signal unit tests (basic sanity check)"""
    dates = pd.date_range('2023-01-01', periods=50, freq='D')
    closes = np.cumprod(1 + np.random.normal(0, 0.02, size=50)) * 100
    df = pd.DataFrame({
        'timestamp': dates,
        'open': closes,
        'high': closes * 1.01,
        'low': closes * 0.99,
        'close': closes,
        'volume': np.random.randint(1000, 10000, size=50)
    })
    
    strat = BollingerPullbackStrategy()
    signals = strat.generate_signals(df)
    
    assert 'target_position' in signals.columns
    assert 'reason' in signals.columns
    assert 'target_weight' in signals.columns
    assert len(signals) == len(df)
    assert set(signals['target_position'].unique()).issubset({0.0, 1.0})
