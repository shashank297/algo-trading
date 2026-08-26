"""Certify existing historical candles in DuckDB that have NULL dataset_id."""

import sys
from pathlib import Path
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage import DuckDBManager
from data_platform.contracts import PriceAdjustment
from data_platform.service import ingest_raw_provider_dataset

def main():
    db = DuckDBManager("market_data.duckdb")
    try:
        # Check symbols in historical_candles for 1d that have null dataset_id
        symbols = [
            row[0] for row in db.conn.execute(
                """
                SELECT DISTINCT symbol
                FROM historical_candles
                WHERE timeframe = '1d' AND (dataset_id IS NULL OR dataset_id = '')
                ORDER BY symbol
                """
            ).fetchall()
        ]
        logger.info(f"Found {len(symbols)} symbols with uncertified 1d candles")
        
        for idx, symbol in enumerate(symbols, 1):
            bars = db.conn.execute(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM historical_candles
                WHERE symbol = ? AND timeframe = '1d'
                ORDER BY timestamp
                """,
                [symbol]
            ).df()
            if bars.empty:
                continue
            
            token_row = db.conn.execute(
                "SELECT token FROM instrument_master WHERE symbol = ? AND exch_seg = 'NSE' LIMIT 1",
                [symbol]
            ).fetchone()
            token = token_row[0] if token_row else None
            
            res = ingest_raw_provider_dataset(
                bars=bars,
                symbol=symbol,
                exchange="NSE",
                timeframe="1d",
                provider_name="angel_one",
                provider_symbol=symbol,
                provider_token=token,
                declared_adjustment=PriceAdjustment.UNADJUSTED,
                timezone_name="Asia/Kolkata",
                db=db,
                target_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            )
            logger.info(f"[{idx}/{len(symbols)}] Certified {symbol} 1d ({len(bars)} bars): raw_status={res.raw_status}, canonical_status={res.canonical_status}")
            
    finally:
        db.close()

if __name__ == "__main__":
    main()
