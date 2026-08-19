# Quickstart & Verification: Corporate Actions & Total Return Engine

## 1. Seed Ingestion
```powershell
.\venv\Scripts\python.exe tools/import_corporate_actions.py --seed-file data/corporate_actions_nifty200.json
```

## 2. Test Execution
Run the dedicated test suite:
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_adjustments.py -v
```

## 3. Real-Market Verification: TATASTEEL Split
Verify the 2022-07-28 10:1 split behavior:
```powershell
.\venv\Scripts\python.exe -c "from storage import DuckDBManager; from trading_stack.pipeline import StrategyPipeline; db = DuckDBManager('market_data.duckdb'); p = StrategyPipeline(db); raw = p.load_candles('TATASTEEL-EQ', '1d', adjustment='UNADJUSTED'); adj = p.load_candles('TATASTEEL-EQ', '1d', adjustment='SPLIT_ADJUSTED'); print('Raw:', raw[raw['timestamp'].str.startswith('2022-07-27')]['close'].values[0]); print('Adj:', adj[adj['timestamp'].str.startswith('2022-07-27')]['close'].values[0])"
```
Expected output:
* Raw 2022-07-27 close: ~₹960+
* Split-Adjusted 2022-07-27 close: ~₹96+ (divided by 10)
* Post-split (2022-07-28 onwards) close: identical between raw and adjusted.
