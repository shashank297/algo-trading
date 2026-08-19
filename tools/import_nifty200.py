"""Import an immutable official NIFTY 200 universe snapshot into DuckDB."""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage import DuckDBManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "universes" / "nifty_200.yaml"))
    parser.add_argument("--database", default=str(PROJECT_ROOT / "market_data.duckdb"))
    parser.add_argument("--effective-date", default=date.today().isoformat())
    parser.add_argument("--snapshot-id", default=None, help="Defaults to NIFTY200_YYYY_MM_DD.")
    parser.add_argument("--csv", default=None, help="Optional previously downloaded official CSV path.")
    return parser


def import_snapshot(db: DuckDBManager, config: dict[str, object], effective_date: date, snapshot_id: str, csv_content: bytes | None = None) -> int:
    if csv_content is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
            "Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.8",
            "Referer": "https://www.nseindia.com/static/products-services/indices-nifty200-index",
        })
        response = session.get(str(config["source_url"]), timeout=(10, 90))
        response.raise_for_status()
        csv_content = response.content
    content_hash = hashlib.sha256(csv_content).hexdigest()
    constituents = pd.read_csv(io.BytesIO(csv_content))
    required = {"Company Name", "Industry", "Symbol"}
    missing = required.difference(constituents.columns)
    if missing:
        raise ValueError(f"Official constituent file is missing columns: {sorted(missing)}")
    if len(constituents) != 200 or constituents["Symbol"].nunique() != 200:
        raise ValueError("The official NIFTY 200 snapshot must contain exactly 200 unique symbols.")
    db._replace_rows("universe_snapshots", [{
        "snapshot_id": snapshot_id, "name": str(config["name"]), "source_url": str(config["source_url"]),
        "effective_date": effective_date, "content_hash": content_hash,
        "survivorship_bias": bool(config.get("survivorship_bias", True)),
    }])
    token_rows = db.conn.execute("SELECT symbol, token FROM instrument_master WHERE exch_seg = 'NSE'").fetchall()
    tokens = {str(symbol): str(token) for symbol, token in token_rows}
    members = []
    for row in constituents.to_dict(orient="records"):
        symbol = str(row["Symbol"]).strip().upper()
        provider_symbol = symbol if symbol in tokens else f"{symbol}-EQ"
        members.append({
            "snapshot_id": snapshot_id, "symbol": symbol, "provider_symbol": provider_symbol,
            "provider_token": tokens.get(provider_symbol) or tokens.get(symbol),
            "company_name": str(row["Company Name"]), "sector": str(row["Industry"]),
            "exchange": "NSE", "active_from": effective_date, "active_to": None,
            "liquidity_eligible": True, "data_eligible": True,
            "paper_eligible": bool(tokens.get(provider_symbol) or tokens.get(symbol)),
        })
    db._replace_rows("universe_snapshot_members", members)
    return len(members)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with open(args.config, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    effective_date = date.fromisoformat(args.effective_date)
    snapshot_id = args.snapshot_id or f"NIFTY200_{effective_date.isoformat().replace('-', '_')}"
    db = DuckDBManager(args.database)
    try:
        csv_content = Path(args.csv).read_bytes() if args.csv else None
        count = import_snapshot(db, config, effective_date, snapshot_id, csv_content)
        print(f"Imported {count} NIFTY 200 members into snapshot {snapshot_id}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
