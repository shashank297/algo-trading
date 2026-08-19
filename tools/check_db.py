from pathlib import Path
import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "market_data.duckdb"
conn = duckdb.connect(str(DB_PATH), read_only=True)
try:
    for row in conn.execute("SELECT token, symbol, exch_seg, name FROM instrument_master WHERE name LIKE '%NIFTY%' OR symbol LIKE '%NIFTY%'").fetchall():
        if row[3] == 'NIFTY 50' or row[1] == 'NIFTY' or row[1] == 'NIFTY 50':
            print(row)
finally:
    conn.close()

