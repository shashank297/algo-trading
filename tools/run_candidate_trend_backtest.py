"""Deterministic, read-only candidate backtest for the research evidence package.

This intentionally runs on the NIFTY200 index series, not on a reconstructed
historical constituent universe. It is a diagnostic proof-of-concept only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_platform.contracts import OrderSide
from trading_stack.costs import TransactionCostCalculator, TransactionCostConfig, get_cost_schedule


def _metrics(frame: pd.DataFrame) -> dict[str, float | int | str | None]:
    frame = frame.copy()
    frame["equity"] = (1.0 + frame["net_return"]).cumprod()
    total_days = max((frame["date"].iloc[-1] - frame["date"].iloc[0]).days, 1)
    years = total_days / 365.25
    total_return = float(frame["equity"].iloc[-1] - 1.0)
    annualized_return = float(frame["equity"].iloc[-1] ** (1.0 / years) - 1.0)
    daily_vol = float(frame["net_return"].std(ddof=1))
    sharpe = float(np.sqrt(252.0) * frame["net_return"].mean() / daily_vol) if daily_vol else None
    drawdown = frame["equity"] / frame["equity"].cummax() - 1.0
    return {
        "start_date": str(frame["date"].iloc[0]),
        "end_date": str(frame["date"].iloc[-1]),
        "observations": int(len(frame)),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": float(daily_vol * np.sqrt(252.0)),
        "sharpe_no_risk_rate": sharpe,
        "max_drawdown": float(drawdown.min()),
        "trade_events": int(frame["trade"].sum()),
        "exposure": float(frame["position"].mean()),
        "gross_return": float((1.0 + frame["gross_return"]).prod() - 1.0),
        "cost_drag": float(frame["gross_return"].sum() - frame["net_return"].sum()),
    }


def _calculator(as_of: pd.Timestamp, multiplier: float = 1.0) -> TransactionCostCalculator:
    schedule = get_cost_schedule(as_of.date())
    config = TransactionCostConfig(
        version=schedule.version,
        brokerage_bps=schedule.brokerage_rate_bps,
        brokerage_min=schedule.brokerage_min,
        brokerage_max=schedule.brokerage_max,
        buy_tax_bps=schedule.stt_buy_bps,
        sell_tax_bps=schedule.stt_sell_bps,
        exchange_bps=schedule.exchange_transaction_bps,
        regulatory_bps=schedule.sebi_bps,
        other_bps=schedule.ipft_bps,
        sell_fixed=schedule.dp_charge_sell,
        gst_rate=schedule.gst_rate,
        buy_stamp_bps=schedule.stamp_duty_buy_bps,
        spread_bps=schedule.spread_bps,
        slippage_bps=schedule.slippage_bps,
        impact_bps_at_full_participation=schedule.impact_bps_at_full_participation,
        max_participation=schedule.max_volume_participation,
    )
    return TransactionCostCalculator(config.with_multiplier(multiplier, version=f"{schedule.version}-{multiplier:g}x"))


def _apply_costs(frame: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    frame = frame.copy()
    costs = []
    for row in frame.itertuples():
        position_change = float(row.position - row.previous_position)
        if position_change == 0:
            costs.append(0.0)
            continue
        side = OrderSide.BUY if position_change > 0 else OrderSide.SELL
        calculator = _calculator(pd.Timestamp(row.date), multiplier)
        notional = abs(position_change) * float(row.open)
        result = calculator.calculate(notional, side, participation=0.0)
        # The diagnostic holds one unit when invested; convert rupee cost to
        # the corresponding portfolio return drag at the execution price.
        costs.append(result.total / float(row.open))
    frame["cost"] = costs
    frame["net_return"] = frame["gross_return"] - frame["cost"]
    return frame


def run(db_path: Path, symbol: str, window: int, output: Path) -> None:
    con = duckdb.connect(str(db_path), read_only=True)
    query = """
        select cast(timestamp as date) as date, open, high, low, close, volume,
               adjustment, provider_name, dataset_id
        from historical_candles
        where symbol = ? and timeframe = '1d'
        order by timestamp
    """
    raw = con.execute(query, [symbol]).fetchdf()
    con.close()
    if raw.empty:
        raise SystemExit(f"No daily data found for {symbol!r}")
    raw = raw.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if len(raw) <= window + 2:
        raise SystemExit(f"Need more than {window + 2} observations; got {len(raw)}")

    # The signal uses close[t] and its rolling history only. Execution is at
    # t+1 open, so no same-bar close execution or future field is used.
    raw["sma"] = raw["close"].rolling(window, min_periods=window).mean()
    raw["signal"] = (raw["close"] > raw["sma"]).astype(float)
    raw["position"] = raw["signal"].shift(1).fillna(0.0)
    raw["previous_position"] = raw["position"].shift(1).fillna(0.0)
    raw["trade"] = (raw["position"] != raw["previous_position"]).astype(int)
    # Prior position owns the overnight gap; the newly targeted position owns
    # the current session open-to-close move. This models next-open execution
    # without using the current close to determine the current position.
    raw["gross_return"] = raw["previous_position"] * (raw["open"] / raw["close"].shift(1) - 1.0) + raw["position"] * (raw["close"] / raw["open"] - 1.0)

    evaluated = raw[raw["sma"].notna()].copy()
    evaluated = _apply_costs(evaluated, 1.0)

    csv_bytes = evaluated[["date", "open", "close", "sma", "signal", "position", "trade", "gross_return", "cost", "net_return"]].to_csv(index=False).encode()
    result = {
        "status": "DIAGNOSTIC_ONLY",
        "candidate": "long-only 200-session close>SMA trend filter",
        "symbol": symbol,
        "timeframe": "1d",
        "execution": "signal at t close; target applied at t+1 open; mark to t+1 close",
        "data_adjustment": sorted(set(raw["adjustment"].dropna().astype(str))),
        "provider_names": sorted(set(raw["provider_name"].dropna().astype(str))),
        "dataset_ids": sorted(set(raw["dataset_id"].dropna().astype(str))),
        "data_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "cost_model": {
            "calculator": "trading_stack.costs.TransactionCostCalculator",
            "base_schedule": "date-effective Indian delivery schedule",
            "components": ["brokerage", "tax", "exchange", "regulatory", "other", "fixed_charge", "gst", "stamp_duty", "spread", "slippage", "market_impact"],
            "fixed_charges": "included; sell-side DP charge is side-aware",
        },
        "cost_sensitivity": {
            f"{multiplier:g}x": _metrics(_apply_costs(raw[raw["sma"].notna()].copy(), multiplier))
            for multiplier in (1.0, 1.5, 2.0, 3.0)
        },
        "metrics": _metrics(evaluated),
        "pit_status": "FAIL: index series is not historical constituent membership evidence; index_constituents_pit is empty in the source database",
        "leakage_controls": [
            "rolling SMA is unshifted for the signal but position is shifted one session",
            "execution uses next row open, never same-row close",
            "rows are sorted by date and duplicate dates are removed deterministically",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("recovery/campaign1-20260902/base-only/market_data.duckdb"))
    parser.add_argument("--symbol", default="NIFTY200")
    parser.add_argument("--window", type=int, default=200)
    parser.add_argument("--output", type=Path, default=Path("reports/candidate_trend_backtest_20260906.json"))
    args = parser.parse_args()
    run(args.db, args.symbol, args.window, args.output)
