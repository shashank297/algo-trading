from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import duckdb
import pandas as pd
from pathlib import Path
import time
from functools import wraps

def ttl_cache(ttl_seconds: int = 30):
    cache = {}
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)
            now = time.time()
            if key in cache:
                val, timestamp = cache[key]
                if now - timestamp < ttl_seconds:
                    return val
            val = func(*args, **kwargs)
            cache[key] = (val, now)
            return val
        return wrapper
    return decorator

app = FastAPI(title="Trading Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def _resolve_db_path() -> Path:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if cfg and "database" in cfg and "path" in cfg["database"]:
                    p = Path(cfg["database"]["path"])
                    return p if p.is_absolute() else PROJECT_ROOT / p
        except Exception:
            pass
    return PROJECT_ROOT / "market_data.duckdb"


DB_PATH = _resolve_db_path()


def get_db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Database file not found at {DB_PATH}")
    try:
        return duckdb.connect(str(DB_PATH), read_only=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database read-only connection error: {str(e)}")



# ── Pydantic models ─────────────────────────────────────────────────────────

class StrategyRunSummary(BaseModel):
    run_id: str
    strategy_name: str
    mode: str
    started_at: str
    status: str
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float


class EquityCurvePoint(BaseModel):
    timestamp: str
    equity: float
    drawdown: float


class StockPerformance(BaseModel):
    symbol: str
    pnl: float
    trade_count: int
    win_rate: float


class PaperReconciliation(BaseModel):
    trade_date: str
    expected_orders: int
    submitted_orders: int
    filled_orders: int
    rejected_orders: int
    pnl: float
    drift: float


class TradeStats(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    base_investment_profit: float
    avg_profit_per_win: float
    avg_loss_per_loss: float
    profit_factor: float
    max_drawdown: float


class MonthlyReturn(BaseModel):
    year: int
    month: int
    return_pct: float


class TradeLedgerEntry(BaseModel):
    trade_id: str
    symbol: str
    entry_timestamp: str
    exit_timestamp: str
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    holding_period_days: float
    entry_reason: str
    exit_reason: str


# ── Helper ───────────────────────────────────────────────────────────────────

def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        if v != v or abs(v) == float("inf"):  # NaN or Inf
            return default
        return v
    except Exception:
        return default


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/runs", response_model=List[StrategyRunSummary])
@ttl_cache(30)
def get_runs():
    conn = get_db()
    try:
        query = """
            SELECT
                r.run_id,
                r.strategy_name,
                r.mode,
                r.started_at,
                r.status,
                MAX(CASE WHEN m.metric_name = 'total_return'  THEN m.metric_value ELSE NULL END) as total_return,
                MAX(CASE WHEN m.metric_name = 'max_drawdown'  THEN m.metric_value ELSE NULL END) as max_drawdown,
                MAX(CASE WHEN m.metric_name = 'sharpe_ratio'  THEN m.metric_value ELSE NULL END) as sharpe_ratio,
                MAX(CASE WHEN m.metric_name = 'win_rate'      THEN m.metric_value ELSE NULL END) as win_rate
            FROM strategy_runs r
            LEFT JOIN strategy_metrics m ON r.run_id = m.run_id
            GROUP BY r.run_id, r.strategy_name, r.mode, r.started_at, r.status
            ORDER BY r.started_at DESC
        """
        df = conn.execute(query).df().fillna(0)
        return [
            StrategyRunSummary(
                run_id=str(row["run_id"]),
                strategy_name=str(row["strategy_name"]),
                mode=str(row["mode"]),
                started_at=str(row["started_at"]),
                status=str(row["status"]),
                total_return=_safe_float(row["total_return"]),
                max_drawdown=_safe_float(row["max_drawdown"]),
                sharpe_ratio=_safe_float(row["sharpe_ratio"]),
                win_rate=_safe_float(row["win_rate"]),
            )
            for _, row in df.iterrows()
        ]
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/equity-curve", response_model=List[EquityCurvePoint])
@ttl_cache(30)
def get_equity_curve(run_id: str):
    conn = get_db()
    try:
        df = conn.execute(
            "SELECT timestamp, equity, drawdown FROM strategy_equity_curve WHERE run_id = ? ORDER BY timestamp ASC",
            [run_id],
        ).df()
        return [
            EquityCurvePoint(
                timestamp=str(row["timestamp"]),
                equity=_safe_float(row["equity"]),
                drawdown=_safe_float(row["drawdown"]),
            )
            for _, row in df.iterrows()
        ]
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/stock-performance", response_model=List[StockPerformance])
@ttl_cache(30)
def get_stock_performance(run_id: str):
    conn = get_db()
    try:
        query = """
            SELECT
                symbol,
                SUM(net_pnl) as pnl,
                COUNT(*) as trade_count,
                SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0) as win_rate
            FROM trade_round_trips
            WHERE run_id = ?
            GROUP BY symbol
            ORDER BY pnl DESC
        """
        try:
            df = conn.execute(query, [run_id]).df().fillna(0)
        except duckdb.CatalogException:
            return []
        return [
            StockPerformance(
                symbol=str(row["symbol"]),
                pnl=_safe_float(row["pnl"]),
                trade_count=int(row["trade_count"]),
                win_rate=_safe_float(row["win_rate"]),
            )
            for _, row in df.iterrows()
        ]
    finally:
        conn.close()


@app.get("/api/paper/reconciliations", response_model=List[PaperReconciliation])
@ttl_cache(30)
def get_paper_reconciliations():
    conn = get_db()
    try:
        try:
            df = conn.execute(
                """SELECT trade_date, expected_orders, submitted_orders, filled_orders,
                          rejected_orders, pnl, drift
                   FROM paper_reconciliation ORDER BY trade_date DESC"""
            ).df().fillna(0)
        except duckdb.CatalogException:
            return []
        return [
            PaperReconciliation(
                trade_date=str(row["trade_date"]),
                expected_orders=int(row["expected_orders"]),
                submitted_orders=int(row["submitted_orders"]),
                filled_orders=int(row["filled_orders"]),
                rejected_orders=int(row["rejected_orders"]),
                pnl=_safe_float(row["pnl"]),
                drift=_safe_float(row["drift"]),
            )
            for _, row in df.iterrows()
        ]
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/analytics/stats", response_model=TradeStats)
@ttl_cache(30)
def get_analytics_stats(
    run_id: str,
    symbol: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
):
    conn = get_db()
    try:
        # Build WHERE clause
        conditions = ["run_id = ?"]
        params: list = [run_id]
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if year:
            conditions.append("EXTRACT(YEAR FROM exit_timestamp) = ?")
            params.append(year)
        where = " AND ".join(conditions)

        query_trades = f"""
            SELECT
                COUNT(*)                                                        as total_trades,
                SUM(CASE WHEN net_pnl > 0  THEN 1 ELSE 0 END)                  as winning_trades,
                SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END)                  as losing_trades,
                AVG(CASE WHEN net_pnl > 0  THEN net_pnl END)                   as avg_profit_per_win,
                AVG(CASE WHEN net_pnl <= 0 THEN net_pnl END)                   as avg_loss_per_loss,
                SUM(CASE WHEN net_pnl > 0  THEN net_pnl ELSE 0 END)            as total_win_pnl,
                ABS(SUM(CASE WHEN net_pnl < 0  THEN net_pnl ELSE 0 END))       as total_loss_pnl,
                SUM(net_pnl)                                                    as total_pnl
            FROM trade_round_trips
            WHERE {where}
        """
        try:
            row = conn.execute(query_trades, params).df().fillna(0).iloc[0]
        except (duckdb.CatalogException, IndexError):
            row = pd.Series({"total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                             "avg_profit_per_win": 0, "avg_loss_per_loss": 0,
                             "total_win_pnl": 0, "total_loss_pnl": 0, "total_pnl": 0})

        total        = int(row["total_trades"])
        winning      = int(row["winning_trades"])
        losing       = int(row["losing_trades"])
        win_rate     = winning / total if total > 0 else 0.0
        avg_win      = _safe_float(row["avg_profit_per_win"])
        avg_loss     = _safe_float(row["avg_loss_per_loss"])
        total_wins   = _safe_float(row["total_win_pnl"])
        total_losses = _safe_float(row["total_loss_pnl"])
        profit_factor = total_wins / total_losses if total_losses > 0 else 0.0

        # Base investment profit
        if symbol or year:
            # Scope: absolute ₹ profit from matching trades
            base_investment_profit = _safe_float(row["total_pnl"])
        else:
            # Full-run: resolve starting_capital from strategy_runs or default to 100k
            df_cap = conn.execute(
                "SELECT starting_capital FROM strategy_runs WHERE run_id = ?",
                [run_id],
            ).df()
            start_cap = (
                _safe_float(df_cap["starting_capital"].iloc[0])
                if not df_cap.empty and "starting_capital" in df_cap.columns and pd.notna(df_cap["starting_capital"].iloc[0])
                else 100_000.0
            )

            df_ret = conn.execute(
                "SELECT metric_value FROM strategy_metrics WHERE run_id = ? AND metric_name = 'total_return'",
                [run_id],
            ).df()
            net_return = _safe_float(df_ret["metric_value"].iloc[0]) if not df_ret.empty else 0.0
            base_investment_profit = net_return * start_cap

        # Max drawdown from stored metrics
        df_dd = conn.execute(
            "SELECT metric_value FROM strategy_metrics WHERE run_id = ? AND metric_name = 'max_drawdown'",
            [run_id],
        ).df()
        max_drawdown = _safe_float(df_dd["metric_value"].iloc[0]) if not df_dd.empty else 0.0

        return TradeStats(
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            base_investment_profit=base_investment_profit,
            avg_profit_per_win=avg_win,
            avg_loss_per_loss=avg_loss,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
        )
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/analytics/monthly", response_model=List[MonthlyReturn])
@ttl_cache(30)
def get_analytics_monthly(run_id: str, symbol: Optional[str] = Query(None)):
    conn = get_db()
    try:
        if symbol:
            # Stock-level: monthly net PnL contribution relative to run starting_capital
            run_cap_row = conn.execute(
                "SELECT starting_capital FROM strategy_runs WHERE run_id = ?", [run_id]
            ).fetchone()
            starting_cap = float(run_cap_row[0]) if (run_cap_row and run_cap_row[0] and float(run_cap_row[0]) > 0) else 100_000.0

            query = """
                SELECT
                    EXTRACT(YEAR  FROM exit_timestamp)::INTEGER as year,
                    EXTRACT(MONTH FROM exit_timestamp)::INTEGER as month,
                    SUM(net_pnl) as month_pnl
                FROM trade_round_trips
                WHERE run_id = ? AND symbol = ?
                GROUP BY year, month
                ORDER BY year ASC, month ASC
            """
            df = conn.execute(query, [run_id, symbol]).df()
            if df.empty:
                return []
            return [
                MonthlyReturn(
                    year=int(row["year"]),
                    month=int(row["month"]),
                    return_pct=_safe_float(row["month_pnl"]) / starting_cap,
                )
                for _, row in df.iterrows()
            ]
        else:
            # Portfolio-level: equity-curve based monthly returns (clean, no fractional bugs)
            query = """
                SELECT timestamp, equity
                FROM strategy_equity_curve
                WHERE run_id = ?
                ORDER BY timestamp ASC
            """
            df = conn.execute(query, [run_id]).df()
            if df.empty:
                return []

            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["year"]  = df["timestamp"].dt.year
            df["month"] = df["timestamp"].dt.month

            monthly_returns = []
            for (year, month), group in df.groupby(["year", "month"]):
                first_equity = _safe_float(group.iloc[0]["equity"], default=1.0)
                last_equity  = _safe_float(group.iloc[-1]["equity"], default=first_equity)
                ret = (last_equity / first_equity - 1.0) if first_equity > 0 else 0.0
                monthly_returns.append(MonthlyReturn(
                    year=int(year), month=int(month), return_pct=_safe_float(ret)
                ))
            return monthly_returns
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/analytics/ledger", response_model=List[TradeLedgerEntry])
@ttl_cache(30)
def get_analytics_ledger(
    run_id: str,
    symbol: Optional[str] = Query(None),
):
    conn = get_db()
    try:
        conditions = ["run_id = ?"]
        params: list = [run_id]
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        where = " AND ".join(conditions)

        query = f"""
            SELECT
                trade_id, symbol,
                entry_timestamp, exit_timestamp,
                quantity, entry_price, exit_price,
                COALESCE(gross_pnl, net_pnl)        as gross_pnl,
                COALESCE(entry_cost + exit_cost, 0)  as fees,
                net_pnl,
                COALESCE(holding_period_days, 0)     as holding_period_days,
                COALESCE(entry_reason, '')           as entry_reason,
                COALESCE(exit_reason, '')            as exit_reason
            FROM trade_round_trips
            WHERE {where}
            ORDER BY exit_timestamp DESC
        """
        try:
            df = conn.execute(query, params).df().fillna(0)
        except duckdb.CatalogException:
            return []

        return [
            TradeLedgerEntry(
                trade_id=str(row["trade_id"]),
                symbol=str(row["symbol"]),
                entry_timestamp=str(row["entry_timestamp"]),
                exit_timestamp=str(row["exit_timestamp"]),
                quantity=_safe_float(row["quantity"]),
                entry_price=_safe_float(row["entry_price"]),
                exit_price=_safe_float(row["exit_price"]),
                gross_pnl=_safe_float(row["gross_pnl"]),
                fees=_safe_float(row["fees"]),
                net_pnl=_safe_float(row["net_pnl"]),
                holding_period_days=_safe_float(row["holding_period_days"]),
                entry_reason=str(row["entry_reason"]),
                exit_reason=str(row["exit_reason"]),
            )
            for _, row in df.iterrows()
        ]
    finally:
        conn.close()


# ── Strategy-level aggregate endpoints ───────────────────────────────────────

class StrategyAggregate(BaseModel):
    strategy_name: str
    total_runs: int
    total_stocks: int
    avg_return: float
    avg_win_rate: float
    avg_sharpe: float
    avg_max_drawdown: float
    avg_profit_factor: float


class StrategyStockSummary(BaseModel):
    symbol: str
    run_id: str
    mode: str
    total_return: float
    win_rate: float
    max_drawdown: float
    sharpe: float
    total_trades: int
    net_pnl: float
    has_trades: bool


@app.get("/api/strategies", response_model=List[StrategyAggregate])
@ttl_cache(30)
def get_strategies():
    """Aggregated list of all unique strategies with cross-run metrics."""
    conn = get_db()
    try:
        query = """
            SELECT
                sr.strategy_name,
                COUNT(DISTINCT sr.run_id)                                                                     AS total_runs,
                COUNT(DISTINCT COALESCE(NULLIF(split_part(sr.run_id, ':', 2), ''), sr.symbol, 'PORTFOLIO')) AS total_stocks,
                AVG(CASE WHEN m.metric_name = 'total_return'   THEN m.metric_value END)                      AS avg_return,
                AVG(CASE WHEN m.metric_name = 'win_rate'       THEN m.metric_value END)                      AS avg_win_rate,
                AVG(CASE WHEN m.metric_name = 'sharpe'         THEN m.metric_value END)                      AS avg_sharpe,
                AVG(CASE WHEN m.metric_name = 'max_drawdown'   THEN m.metric_value END)                      AS avg_max_drawdown,
                AVG(CASE WHEN m.metric_name = 'profit_factor'  THEN m.metric_value END)                      AS avg_profit_factor
            FROM strategy_runs sr
            LEFT JOIN strategy_metrics m ON sr.run_id = m.run_id
            GROUP BY sr.strategy_name
            ORDER BY total_runs DESC, avg_return DESC
        """
        df = conn.execute(query).df().fillna(0)
        return [
            StrategyAggregate(
                strategy_name=str(row["strategy_name"]),
                total_runs=int(row["total_runs"]),
                total_stocks=int(row["total_stocks"]),
                avg_return=_safe_float(row["avg_return"]),
                avg_win_rate=_safe_float(row["avg_win_rate"]),
                avg_sharpe=_safe_float(row["avg_sharpe"]),
                avg_max_drawdown=_safe_float(row["avg_max_drawdown"]),
                avg_profit_factor=_safe_float(row["avg_profit_factor"]),
            )
            for _, row in df.iterrows()
        ]
    finally:
        conn.close()


@app.get("/api/strategies/{strategy_name}/stocks", response_model=List[StrategyStockSummary])
@ttl_cache(30)
def get_strategy_stocks(strategy_name: str):
    """All stocks tested under a given strategy, with per-run metrics and trade data."""
    conn = get_db()
    try:
        # Get all runs for the strategy (use best/latest run per symbol)
        query = """
            WITH ranked AS (
                SELECT
                    sr.run_id,
                    sr.mode,
                    COALESCE(NULLIF(split_part(sr.run_id, ':', 2), ''), sr.symbol, 'PORTFOLIO') AS symbol,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(NULLIF(split_part(sr.run_id, ':', 2), ''), sr.symbol, 'PORTFOLIO')
                        ORDER BY 
                            (SELECT COUNT(*) FROM trade_round_trips t WHERE t.run_id = sr.run_id) > 0 DESC,
                            sr.started_at DESC
                    )                                                                           AS rn,
                    MAX(CASE WHEN m.metric_name = 'total_return'  THEN m.metric_value END)     AS total_return,
                    MAX(CASE WHEN m.metric_name = 'win_rate'      THEN m.metric_value END)     AS win_rate,
                    MAX(CASE WHEN m.metric_name = 'max_drawdown'  THEN m.metric_value END)     AS max_drawdown,
                    MAX(CASE WHEN m.metric_name = 'sharpe'        THEN m.metric_value END)     AS sharpe,
                    MAX(CASE WHEN m.metric_name = 'trades'        THEN m.metric_value END)     AS total_trades
                FROM strategy_runs sr
                LEFT JOIN strategy_metrics m ON sr.run_id = m.run_id
                WHERE sr.strategy_name = ?
                GROUP BY sr.run_id, sr.mode, sr.symbol, sr.started_at
            )
            SELECT run_id, mode, symbol, total_return, win_rate, max_drawdown, sharpe, total_trades
            FROM ranked WHERE rn = 1
            ORDER BY COALESCE(total_return, 0) DESC
        """
        df = conn.execute(query, [strategy_name]).df().fillna(0)

        # For each run, check if there are actual trade round trips
        results = []
        for _, row in df.iterrows():
            rid = str(row["run_id"])
            try:
                ct = conn.execute(
                    "SELECT COUNT(*) FROM trade_round_trips WHERE run_id = ?", [rid]
                ).fetchone()[0]
                has_trades = ct > 0
                net_pnl = _safe_float(
                    conn.execute(
                        "SELECT SUM(net_pnl) FROM trade_round_trips WHERE run_id = ?", [rid]
                    ).fetchone()[0]
                )
            except duckdb.CatalogException:
                has_trades = False
                net_pnl = 0.0

            results.append(StrategyStockSummary(
                symbol=str(row["symbol"]),
                run_id=rid,
                mode=str(row["mode"]),
                total_return=_safe_float(row["total_return"]),
                win_rate=_safe_float(row["win_rate"]),
                max_drawdown=_safe_float(row["max_drawdown"]),
                sharpe=_safe_float(row["sharpe"]),
                total_trades=int(row["total_trades"]),
                net_pnl=net_pnl,
                has_trades=has_trades,
            ))
        return results
    finally:
        conn.close()


@app.get("/api/strategies/{strategy_name}/run-for-stock")
@ttl_cache(30)
def get_run_for_stock(strategy_name: str, symbol: str = Query(...)):
    """Find the best run_id for a given strategy + symbol combination."""
    conn = get_db()
    try:
        df = conn.execute(
            """
            SELECT run_id FROM strategy_runs
            WHERE strategy_name = ?
              AND split_part(run_id, ':', 2) = ?
            ORDER BY started_at DESC LIMIT 1
            """,
            [strategy_name, symbol],
        ).df()
        if df.empty:
            raise HTTPException(status_code=404, detail="No run found for this strategy + symbol")
        return {"run_id": str(df["run_id"].iloc[0])}
    finally:
        conn.close()
