"""Asynchronous single-writer DuckDB stream persistence for live ticks and aggregated bars."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

import duckdb
import pandas as pd
from loguru import logger

from data_platform.contracts import (
    MarketDataEvent,
)
from trading_stack.domain import Bar


class DuckDBStreamWriter:
    """Dedicated single-writer background thread for market tick and bar persistence."""

    def __init__(
        self,
        db_path: str,
        batch_size: int = 500,
        flush_interval_seconds: float = 1.0,
        queue_maxsize: int = 100_000,
        capture_raw_packets: bool = False,
    ) -> None:
        """Initialize the single-writer DuckDB stream writer.

        Args:
            db_path: Path to the DuckDB database file.
            batch_size: Maximum records to accumulate before flushing.
            flush_interval_seconds: Maximum interval between flushes.
            queue_maxsize: Maximum bounded queue size.
            capture_raw_packets: Whether to capture raw binary packets.
        """
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self.capture_raw_packets = capture_raw_packets

        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=queue_maxsize)
        self._running = False
        self._thread: threading.Thread | None = None
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._dropped_records = 0

    def start(self) -> None:
        """Initialize schema and start the background persistence worker thread."""
        if self._running:
            return
        self._conn = duckdb.connect(database=self.db_path)
        self._init_tables()
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, name="DuckDBStreamWriter", daemon=True)
        self._thread.start()
        logger.info("💾 DuckDBStreamWriter started (batch={}, flush={}s).", self.batch_size, self.flush_interval)

    def _init_tables(self) -> None:
        """Create stream tables if they do not exist."""
        if self._conn is None:
            return
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS market_ticks (
                exchange VARCHAR NOT NULL,
                token VARCHAR NOT NULL,
                symbol VARCHAR,
                mode VARCHAR NOT NULL,
                exchange_timestamp TIMESTAMPTZ,
                received_at TIMESTAMPTZ NOT NULL,
                sequence_number BIGINT,
                ltp DOUBLE NOT NULL,
                volume BIGINT,
                open_interest BIGINT,
                feed_latency_ms DOUBLE,
                PRIMARY KEY (exchange, token, received_at, sequence_number)
            );
            CREATE TABLE IF NOT EXISTS market_bars (
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume DOUBLE NOT NULL,
                turnover DOUBLE NOT NULL,
                is_final BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, exchange, timeframe, timestamp)
            );
        """)

    def enqueue_tick(self, event: MarketDataEvent) -> bool:
        """Enqueue a market tick for asynchronous persistence.

        Returns:
            bool: True if queued, False if dropped due to queue saturation.
        """
        try:
            self._queue.put_nowait(("tick", event))
            return True
        except queue.Full:
            self._dropped_records += 1
            logger.warning("Persistence queue full! Dropped live tick. Total drops: {}", self._dropped_records)
            return False

    def enqueue_bar(self, bar: Bar, timeframe: str = "1m") -> bool:
        """Enqueue an aggregated bar for asynchronous persistence.

        Returns:
            bool: True if queued, False if dropped.
        """
        try:
            self._queue.put_nowait(("bar", (bar, timeframe)))
            return True
        except queue.Full:
            self._dropped_records += 1
            logger.warning("Persistence queue full! Dropped bar. Total drops: {}", self._dropped_records)
            return False

    def _worker_loop(self) -> None:
        """Accumulate records and flush on batch size or timer interval."""
        tick_batch: list[dict[str, Any]] = []
        bar_batch: list[dict[str, Any]] = []
        last_flush_time = time.monotonic()

        while self._running or not self._queue.empty():
            try:
                record_type, payload = self._queue.get(timeout=0.2)
                if record_type == "tick":
                    event = payload
                    tick_batch.append(
                        {
                            "exchange": event.exchange,
                            "token": event.token,
                            "symbol": event.symbol,
                            "mode": event.mode.value,
                            "exchange_timestamp": event.exchange_timestamp,
                            "received_at": event.received_at_utc,
                            "sequence_number": getattr(event, "sequence_number", 0),
                            "ltp": getattr(event, "ltp", 0.0),
                            "volume": getattr(event, "cumulative_volume", None),
                            "open_interest": getattr(event, "open_interest", None),
                            "feed_latency_ms": getattr(event, "feed_latency_ms", None),
                        }
                    )
                elif record_type == "bar":
                    bar, tf = payload
                    bar_batch.append(
                        {
                            "symbol": bar.symbol,
                            "exchange": getattr(bar, "exchange", "NSE_CM"),
                            "timeframe": tf,
                            "timestamp": bar.timestamp,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                            "turnover": getattr(bar, "turnover", bar.close * bar.volume),
                            "is_final": getattr(bar, "is_final", True),
                        }
                    )
                self._queue.task_done()

            except queue.Empty:
                pass

            now = time.monotonic()
            should_flush = (
                len(tick_batch) >= self.batch_size
                or len(bar_batch) >= self.batch_size
                or (now - last_flush_time >= self.flush_interval and (tick_batch or bar_batch))
            )

            if should_flush:
                self._flush_batches(tick_batch, bar_batch)
                tick_batch.clear()
                bar_batch.clear()
                last_flush_time = now

        # Final drain
        if tick_batch or bar_batch:
            self._flush_batches(tick_batch, bar_batch)

    def _flush_batches(self, tick_batch: list[dict[str, Any]], bar_batch: list[dict[str, Any]]) -> None:
        """Batch insert ticks and bars into DuckDB."""
        if self._conn is None:
            return

        if tick_batch:
            try:
                df_ticks = pd.DataFrame(tick_batch)
                temp_name = f"temp_ticks_{time.time_ns()}"
                self._conn.register(temp_name, df_ticks)
                cols = ", ".join(df_ticks.columns)
                self._conn.execute(f"INSERT OR REPLACE INTO market_ticks ({cols}) SELECT {cols} FROM {temp_name}")
                self._conn.unregister(temp_name)
            except Exception as exc:
                logger.error("Failed to batch insert market ticks: {}", exc)

        if bar_batch:
            try:
                df_bars = pd.DataFrame(bar_batch)
                temp_name = f"temp_bars_{time.time_ns()}"
                self._conn.register(temp_name, df_bars)
                cols = ", ".join(df_bars.columns)
                self._conn.execute(f"INSERT OR REPLACE INTO market_bars ({cols}) SELECT {cols} FROM {temp_name}")
                self._conn.unregister(temp_name)
            except Exception as exc:
                logger.error("Failed to batch insert market bars: {}", exc)

    def stop(self) -> None:
        """Gracefully drain the persistence queue, flush to DuckDB, and close connection."""
        if not self._running:
            return
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as exc:
                logger.debug("Error closing DuckDB stream connection: {}", exc)
            self._conn = None
        logger.info("💾 DuckDBStreamWriter stopped gracefully.")
