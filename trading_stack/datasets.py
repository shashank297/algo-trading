"""Synchronized, provenance-aware research panels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from threading import Lock
from typing import ClassVar

import pandas as pd
from loguru import logger

from data_platform.adjustments import PriceAdjustmentEngine
from data_platform.contracts import PriceAdjustment
from storage.duckdb_manager import DuckDBManager
from trading_stack.features import FeatureFactory
from trading_stack.calendars import MarketCalendar
from trading_stack.domain import AssetClass
from trading_stack.calendars import build_default_calendars


@dataclass(frozen=True)
class ResearchDataset:
    universe_snapshot_id: str
    dataset_snapshot_ids: dict[str, str | None]
    panel: pd.DataFrame
    benchmark_symbol: str | None = None
    benchmark_provider_symbol: str | None = None
    benchmark_relationship: str | None = None
    exclusions: pd.DataFrame = field(default_factory=pd.DataFrame)
    survivorship_bias: bool = True

    @property
    def data_hash(self) -> str:
        frame = self.panel.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(frame, index=False, categorize=True).values.tobytes()
        )
        digest.update(json.dumps({
            "universe_snapshot_id": self.universe_snapshot_id,
            "dataset_snapshot_ids": self.dataset_snapshot_ids,
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_provider_symbol": self.benchmark_provider_symbol,
            "benchmark_relationship": self.benchmark_relationship,
        }, sort_keys=True, default=str).encode())
        return digest.hexdigest()


class SynchronizedPanelBuilder:
    """Load each symbol once and build causal per-symbol features."""

    _panel_cache: ClassVar[dict[tuple[object, ...], ResearchDataset]] = {}
    _panel_cache_lock: ClassVar[Lock] = Lock()

    def __init__(
        self,
        db: DuckDBManager,
        feature_factory: FeatureFactory | None = None,
        calendar: MarketCalendar | None = None,
        strict_calendar: bool = False,
    ) -> None:
        self.db = db
        self.feature_factory = feature_factory or FeatureFactory()
        self.calendar = calendar or build_default_calendars()[AssetClass.INDIA_EQUITY]
        self.strict_calendar = strict_calendar

    def build(
        self,
        symbols: list[str],
        timeframe: str,
        *,
        universe_snapshot_id: str = "CONFIGURED_UNIVERSE",
        benchmark_symbol: str | None = "NIFTY",
        minimum_lookback: int = 1,
        adjustment: str = "UNADJUSTED",
    ) -> ResearchDataset:
        """Reuse one immutable featured panel and derive strategy-specific eligibility."""

        feature_config = tuple(
            (item.name, getattr(self.feature_factory, item.name))
            for item in fields(self.feature_factory)
        )
        key = (
            str(self.db.db_path), tuple(symbols), timeframe, universe_snapshot_id,
            benchmark_symbol, feature_config, self.db.market_data_revision(), str(adjustment).upper(),
        )
        with self._panel_cache_lock:
            cached = self._panel_cache.get(key)
            if cached is None:
                cached = self._build_uncached(
                    symbols,
                    timeframe,
                    universe_snapshot_id=universe_snapshot_id,
                    benchmark_symbol=benchmark_symbol,
                    minimum_lookback=1,
                    adjustment=adjustment,
                )
                self._panel_cache[key] = cached
        panel = cached.panel.copy()
        panel["eligible"] = panel.groupby("symbol").cumcount() + 1 >= minimum_lookback
        if "benchmark_close" in panel:
            panel["eligible"] &= panel["benchmark_close"].notna()
        return ResearchDataset(
            universe_snapshot_id=cached.universe_snapshot_id,
            dataset_snapshot_ids=dict(cached.dataset_snapshot_ids),
            panel=panel,
            benchmark_symbol=cached.benchmark_symbol,
            benchmark_provider_symbol=cached.benchmark_provider_symbol,
            benchmark_relationship=cached.benchmark_relationship,
            exclusions=cached.exclusions.copy(),
            survivorship_bias=cached.survivorship_bias,
        )

    def _build_uncached(
        self,
        symbols: list[str],
        timeframe: str,
        *,
        universe_snapshot_id: str = "CONFIGURED_UNIVERSE",
        benchmark_symbol: str | None = "NIFTY",
        minimum_lookback: int = 1,
        adjustment: str = "UNADJUSTED",
    ) -> ResearchDataset:
        if not symbols:
            raise ValueError("A synchronized dataset requires at least one symbol.")
        logger.bind(
            event="panel_build_started",
            symbol_count=len(symbols),
            timeframe=timeframe,
            universe_snapshot_id=universe_snapshot_id,
        ).info("panel_build_started")
        panels: list[pd.DataFrame] = []
        exclusions: list[dict[str, object]] = []
        dataset_ids: dict[str, str | None] = {}
        sectors = self._sector_map(symbols, universe_snapshot_id)
        resolved_benchmark, benchmark_relationship = self._resolve_benchmark(benchmark_symbol, timeframe)
        benchmark = self._load_bars(resolved_benchmark, timeframe, adjustment=adjustment) if resolved_benchmark else pd.DataFrame()
        if benchmark_symbol and benchmark.empty:
            raise ValueError(
                f"Benchmark {benchmark_symbol} {timeframe} has no stored candle data or approved provider mapping."
            )
        benchmark_close = benchmark[["timestamp", "close"]].rename(columns={"close": "benchmark_close"}) if not benchmark.empty else pd.DataFrame()
        adjustment_states: set[str] = set()
        for index, symbol in enumerate(symbols, start=1):
            bars = self._load_bars(symbol, timeframe, adjustment=adjustment)
            if bars.empty:
                exclusions.append({"symbol": symbol, "reason": "MISSING_DATA", "timestamp": pd.NaT})
                dataset_ids[symbol] = None
                continue
            bars = self._valid_sessions(bars, timeframe)
            if bars.empty:
                exclusions.append({"symbol": symbol, "reason": "NO_VALID_SESSIONS", "timestamp": pd.NaT})
                dataset_ids[symbol] = None
                continue
            adjustment_states.update(str(value) for value in bars["adjustment"].dropna().unique())
            featured = self.feature_factory.build(bars, timezone_name="Asia/Kolkata")
            featured["symbol"] = symbol
            featured["sector"] = sectors.get(symbol, "UNKNOWN")
            featured["eligible"] = featured.groupby("symbol").cumcount() + 1 >= minimum_lookback
            if not benchmark_close.empty and symbol != benchmark_symbol:
                featured = featured.merge(benchmark_close, on="timestamp", how="left")
            panels.append(featured)
            dataset_ids[symbol] = self._latest_dataset_id(symbol, timeframe)
            if index % 25 == 0 or index == len(symbols):
                logger.bind(
                    event="panel_build_progress",
                    processed_symbols=index,
                    total_symbols=len(symbols),
                    included_symbols=len(panels),
                    excluded_symbols=len(exclusions),
                    timeframe=timeframe,
                ).info("panel_build_progress")
        if len(adjustment_states) > 1:
            raise ValueError("Synchronized panels cannot mix adjusted and unadjusted series.")
        if not panels:
            raise ValueError("No requested symbols have stored candle data.")
        panel = pd.concat(panels, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        if "benchmark_close" in panel:
            panel["eligible"] &= panel["benchmark_close"].notna()
        reference_timestamps = set(
            pd.to_datetime(benchmark_close["timestamp"], utc=True)
            if not benchmark_close.empty else pd.to_datetime(panel["timestamp"], utc=True)
        )
        for symbol, group in panel.groupby("symbol"):
            observed = set(pd.to_datetime(group["timestamp"], utc=True))
            first, last = min(observed), max(observed)
            for timestamp in sorted(reference_timestamps.difference(observed)):
                if first <= timestamp <= last:
                    exclusions.append({
                        "symbol": symbol, "reason": "MISSING_SESSION", "timestamp": timestamp,
                    })
        latest_timestamp = panel["timestamp"].max()
        for symbol, group in panel.groupby("symbol"):
            if group["timestamp"].max() < latest_timestamp:
                exclusions.append({"symbol": symbol, "reason": "STALE_PRICE", "timestamp": group["timestamp"].max()})
        duplicates = panel.duplicated(["timestamp", "symbol"])
        if duplicates.any():
            raise ValueError("Synchronized panel contains duplicate symbol timestamps.")
        logger.bind(
            event="panel_build_finished",
            panel_rows=len(panel),
            included_symbols=int(panel["symbol"].nunique()),
            exclusion_records=len(exclusions),
            timeframe=timeframe,
        ).info("panel_build_finished")
        return ResearchDataset(
            universe_snapshot_id=universe_snapshot_id,
            dataset_snapshot_ids=dataset_ids,
            panel=panel,
            benchmark_symbol=benchmark_symbol,
            benchmark_provider_symbol=resolved_benchmark,
            benchmark_relationship=benchmark_relationship,
            exclusions=pd.DataFrame(exclusions),
        )

    def _resolve_benchmark(self, symbol: str | None, timeframe: str) -> tuple[str | None, str | None]:
        if not symbol:
            return None, None
        if not self._load_bars(symbol, timeframe).empty:
            return symbol, "EXACT"
        row = self.db.conn.execute(
            """SELECT provider_symbol, relationship FROM benchmark_aliases
               WHERE canonical_symbol = ? AND approved_for_research
               ORDER BY CASE relationship WHEN 'EXACT' THEN 0 ELSE 1 END LIMIT 1""",
            [symbol],
        ).fetchone()
        return (str(row[0]), str(row[1])) if row else (symbol, None)

    def _valid_sessions(self, bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        timestamps = pd.to_datetime(bars["timestamp"], utc=True)
        if self.strict_calendar:
            validation = self.calendar.validate_bars(timestamps, timeframe)
            if validation.out_of_session_count:
                raise ValueError(
                    f"Dataset contains {validation.out_of_session_count} bars outside calendar "
                    f"{self.calendar.version}: {list(validation.out_of_session)}."
                )
        local = timestamps.dt.tz_convert(self.calendar.zone)
        if timeframe == "1d":
            valid = local.map(lambda value: self.calendar.is_trading_day(value.date()))
        else:
            valid = local.map(lambda value: self.calendar.is_session_open(value.to_pydatetime()))
        return bars.loc[valid.to_numpy()].reset_index(drop=True)

    def _load_bars(
        self,
        symbol: str | None,
        timeframe: str,
        adjustment: PriceAdjustment | str = PriceAdjustment.UNADJUSTED,
    ) -> pd.DataFrame:
        if not symbol:
            return pd.DataFrame()
        frame = self.db.conn.execute(
            """SELECT symbol, exchange, timeframe, timestamp, open, high, low, close, volume,
                      adjustment, provider_name, dataset_id
               FROM historical_candles WHERE symbol = ? AND timeframe = ? ORDER BY timestamp""",
            [symbol, timeframe],
        ).df()
        adj_enum = PriceAdjustment(str(getattr(adjustment, "value", adjustment)).upper())
        if not frame.empty:
            ca_df = self.db.get_corporate_actions(symbol)
            frame = PriceAdjustmentEngine.adjust_ohlcv(frame, ca_df, adjustment=adj_enum)
        return frame


    def _latest_dataset_id(self, symbol: str, timeframe: str) -> str | None:
        row = self.db.conn.execute(
            "SELECT dataset_id FROM market_datasets WHERE canonical_symbol = ? AND timeframe = ? ORDER BY retrieved_at DESC LIMIT 1",
            [symbol, timeframe],
        ).fetchone()
        return str(row[0]) if row else None

    def _sector_map(self, symbols: list[str], snapshot_id: str) -> dict[str, str]:
        try:
            rows = self.db.conn.execute(
                "SELECT symbol, provider_symbol, sector FROM universe_snapshot_members WHERE snapshot_id = ?",
                [snapshot_id],
            ).fetchall()
            requested = set(symbols)
            mapping: dict[str, str] = {}
            for symbol, provider_symbol, sector in rows:
                for candidate in (symbol, provider_symbol):
                    if candidate is not None and str(candidate) in requested:
                        mapping[str(candidate)] = str(sector)
            return mapping
        except Exception:
            return {}
