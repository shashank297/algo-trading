"""DuckDB storage manager for historical market data."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import date, datetime, timezone


from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import threading
from contextlib import contextmanager
from loguru import logger

from utils.timezone import to_ist


def _scalar(row: tuple[Any, ...] | None, description: str) -> Any:
    if row is None:
        raise RuntimeError(f"DuckDB returned no row for {description}.")
    return row[0]


class DuckDBManager:
    """Manage DuckDB schema creation, upserts, and audit logging."""

    def __init__(self, db_path: str) -> None:
        """Connect to DuckDB and initialize the schema.

        Args:
            db_path: Filesystem path to the DuckDB database file.
        """

        self.db_path = db_path
        self._write_lock = threading.RLock()
        
        for attempt in range(10):
            try:
                self.conn = duckdb.connect(database=db_path)
                break
            except duckdb.IOException as e:
                if attempt == 9:
                    logger.error("Failed to acquire DuckDB lock after 10 attempts.")
                    raise e
                logger.debug(f"DuckDB locked, retrying in 1s (attempt {attempt+1}/10)...")
                time.sleep(1)
                
        self.initialize_schema()
        logger.info("🗄️ Database connected: {}", db_path)

    def initialize_schema(self) -> None:
        """Create all required DuckDB tables if they do not exist."""

        schema_path = Path(__file__).resolve().parent.parent / "database_schema.sql"
        try:
            with self._write_lock:
                self.conn.execute(schema_path.read_text(encoding="utf-8"))
                self._migrate_equity_curve_primary_key()
                self._migrate_corporate_actions_schema()
                try:
                    self.conn.execute("FORCE CHECKPOINT;")
                except Exception as e:
                    logger.debug("Skipped checkpoint during initialization: {}", e)
        except Exception as exc:
            logger.exception("Failed to initialize DuckDB schema: {}", exc)

            raise

    def upsert_candles(
        self,
        df: pd.DataFrame,
        symbol: str,
        token: str,
        exchange: str,
        timeframe: str,
        adjustment: str = "UNADJUSTED",
        provider_name: str | None = None,
        dataset_id: str | None = None,
    ) -> int:
        """Batch insert candles, ignoring duplicates by primary key.

        Args:
            df: Candle DataFrame.
            symbol: Trading symbol.
            token: Instrument token.
            exchange: Exchange segment.
            timeframe: Local timeframe label.

        Returns:
            int: Number of newly inserted candles.
        """

        if df.empty:
            return 0

        required_columns = {"timestamp", "open", "high", "low", "close", "volume"}
        missing_columns = required_columns.difference(df.columns)
        if missing_columns:
            raise ValueError(f"Candle data is missing columns: {sorted(missing_columns)}")

        insert_df = df.copy()
        insert_df["timestamp"] = pd.to_datetime(insert_df["timestamp"], utc=True, errors="coerce")
        numeric_columns = ["open", "high", "low", "close", "volume"]
        for column in numeric_columns:
            insert_df[column] = pd.to_numeric(insert_df[column], errors="coerce")
        insert_df = insert_df.dropna(subset=["timestamp", *numeric_columns])
        if insert_df.empty:
            raise ValueError("Candle data contains no valid rows.")
        bad_volume = insert_df["volume"] < 0
        bad_open = insert_df["open"] <= 0
        if bad_volume.any() or bad_open.any():
            bad_count = (bad_volume | bad_open).sum()
            logger.warning(
                "⚠️ {} {}: dropping {} rows with negative volume or zero/negative open price",
                symbol, timeframe, bad_count
            )
            insert_df = insert_df.loc[~(bad_volume | bad_open)].copy()
        if insert_df.empty:
            logger.warning("⚠️ {} {}: all rows were invalid, nothing to insert.", symbol, timeframe)
            return 0
        bad_ohlc = (
            (insert_df["high"] < insert_df[["open", "close"]].max(axis=1))
            | (insert_df["low"] > insert_df[["open", "close"]].min(axis=1))
            | (insert_df["high"] < insert_df["low"])
        )
        if bad_ohlc.any():
            logger.warning(
                "⚠️ {} {}: dropping {} rows with invalid OHLC relationships",
                symbol, timeframe, bad_ohlc.sum()
            )
            insert_df = insert_df.loc[~bad_ohlc].copy()
        if insert_df.empty:
            logger.warning("⚠️ {} {}: all rows failed OHLC validation, nothing to insert.", symbol, timeframe)
            return 0
        insert_df["volume"] = insert_df["volume"].astype("int64")
        insert_df = insert_df.drop_duplicates(subset=["timestamp"])

        insert_df["symbol"] = symbol
        insert_df["token"] = token
        insert_df["exchange"] = exchange
        insert_df["timeframe"] = timeframe
        insert_df["adjustment"] = str(adjustment).upper()
        insert_df["provider_name"] = provider_name
        insert_df["dataset_id"] = dataset_id
        insert_df = insert_df[
            ["symbol", "token", "exchange", "timeframe", "timestamp", "open", "high", "low", "close", "volume", "adjustment", "provider_name", "dataset_id"]
        ]

        table_name = f"temp_historical_candles_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                existing_adjustments = {
                    str(row[0]).upper()
                    for row in self.conn.execute(
                        "SELECT DISTINCT adjustment FROM historical_candles WHERE symbol = ? AND timeframe = ?",
                        [symbol, timeframe],
                    ).fetchall()
                    if row[0] is not None
                }
                if existing_adjustments and existing_adjustments != {str(adjustment).upper()}:
                    raise ValueError(
                        f"Cannot mix adjustment states for {symbol} {timeframe}: "
                        f"stored={sorted(existing_adjustments)}, incoming={str(adjustment).upper()}"
                    )
                self.conn.register(table_name, insert_df)
                conflicting_rows = int(
                    _scalar(self.conn.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM historical_candles AS dst
                        JOIN {table_name} AS src
                          ON dst.symbol = src.symbol
                         AND dst.timeframe = src.timeframe
                         AND dst.timestamp = src.timestamp
                        WHERE dst.open IS DISTINCT FROM src.open
                           OR dst.high IS DISTINCT FROM src.high
                           OR dst.low IS DISTINCT FROM src.low
                           OR dst.close IS DISTINCT FROM src.close
                           OR dst.volume IS DISTINCT FROM src.volume
                        """
                    ).fetchone(), "conflicting candle count")
                )
                if conflicting_rows:
                    logger.warning(
                        f"Canonical candle conflict for {symbol} {timeframe}: "
                        f"{conflicting_rows} existing timestamps have different OHLCV values. Keeping existing data."
                    )
                inserted_count = int(
                    _scalar(self.conn.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {table_name} AS src
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM historical_candles AS dst
                            WHERE dst.symbol = src.symbol
                              AND dst.timeframe = src.timeframe
                              AND dst.timestamp = src.timestamp
                        )
                        """
                    ).fetchone(), "new candle count")
                )
                self.conn.execute(
                    f"""
                    INSERT OR IGNORE INTO historical_candles (
                        symbol,
                        token,
                        exchange,
                        timeframe,
                        timestamp,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        adjustment,
                        provider_name,
                        dataset_id
                    )
                    SELECT
                        symbol,
                        token,
                        exchange,
                        timeframe,
                        timestamp,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        adjustment,
                        provider_name,
                        dataset_id
                    FROM {table_name}
                    """
                )

                provenance_updates = 0
                if provider_name is not None or dataset_id is not None:
                    provenance_updates = int(
                        _scalar(self.conn.execute(
                            f"""
                            SELECT COUNT(*)
                            FROM historical_candles AS dst
                            JOIN {table_name} AS src
                              ON dst.symbol = src.symbol
                             AND dst.timeframe = src.timeframe
                             AND dst.timestamp = src.timestamp
                            WHERE (dst.provider_name IS NULL AND src.provider_name IS NOT NULL)
                               OR (dst.dataset_id IS NULL AND src.dataset_id IS NOT NULL)
                            """
                        ).fetchone(), "provenance update count")
                    )
                    self.conn.execute(
                        f"""
                        UPDATE historical_candles AS dst
                        SET provider_name = COALESCE(dst.provider_name, src.provider_name),
                            dataset_id = COALESCE(dst.dataset_id, src.dataset_id)
                        FROM {table_name} AS src
                        WHERE dst.symbol = src.symbol
                          AND dst.timeframe = src.timeframe
                          AND dst.timestamp = src.timestamp
                          AND dst.open IS NOT DISTINCT FROM src.open
                          AND dst.high IS NOT DISTINCT FROM src.high
                          AND dst.low IS NOT DISTINCT FROM src.low
                          AND dst.close IS NOT DISTINCT FROM src.close
                          AND dst.volume IS NOT DISTINCT FROM src.volume
                        """
                    )

                if inserted_count > 0 or provenance_updates > 0:
                    self.conn.execute(
                        """UPDATE market_data_state
                           SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                           WHERE state_id = 1"""
                    )

                # Post-insert verification (holiness check)
                if inserted_count > 0:
                    min_ts = insert_df["timestamp"].min()
                    max_ts = insert_df["timestamp"].max()
                    actual_count = _scalar(self.conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM historical_candles
                        WHERE symbol = ? AND timeframe = ? AND timestamp BETWEEN ? AND ?
                        """,
                        [symbol, timeframe, min_ts, max_ts]
                    ).fetchone(), "persisted candle count")
                    if actual_count < inserted_count:
                        logger.error(
                            "Post-insert holiness check FAILED for {} {}: expected >= {}, found {}",
                            symbol, timeframe, inserted_count, actual_count
                        )
                        raise RuntimeError(
                            f"Data holiness failure: {inserted_count} rows reported inserted "
                            f"but only {actual_count} found in range."
                        )
                self.conn.unregister(table_name)

            return inserted_count
        except Exception as exc:
            logger.exception("Failed to upsert candles for {} {}: {}", symbol, timeframe, exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def market_data_revision(self) -> int:
        """Return the monotonic canonical-data revision used to invalidate research caches."""

        row = self.conn.execute(
            "SELECT revision FROM market_data_state WHERE state_id = 1"
        ).fetchone()
        return int(row[0]) if row else 0

    @contextmanager
    def transaction(self):
        """Serialize a group of storage calls in one DuckDB transaction."""

        with self._write_lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                yield
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def upsert_instrument_master(self, df: pd.DataFrame) -> int:
        """Upsert the instrument master into DuckDB.

        Args:
            df: Instrument master DataFrame.

        Returns:
            int: Number of processed instrument rows.
        """

        if df.empty:
            return 0

        table_name = f"temp_instrument_master_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, df)
                self.conn.execute(
                f"""
                INSERT OR REPLACE INTO instrument_master (
                    token,
                    symbol,
                    name,
                    expiry,
                    strike,
                    lotsize,
                    instrumenttype,
                    exch_seg,
                    tick_size
                )
                SELECT
                    token,
                    symbol,
                    name,
                    expiry,
                    strike,
                    lotsize,
                    instrumenttype,
                    exch_seg,
                    tick_size
                FROM {table_name}
                """
            )
            return len(df)
        except Exception as exc:
            logger.exception("Failed to upsert instrument master: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def get_latest_timestamp(self, symbol: str, timeframe: str) -> datetime | None:
        """Return the latest stored candle timestamp for a symbol and timeframe."""

        try:
            with self._write_lock:
                result = self.conn.execute(
                    """
                    SELECT timestamp
                    FROM historical_candles
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    [symbol, timeframe],
                ).fetchone()
            if result is None or result[0] is None:
                return None
            return to_ist(pd.Timestamp(result[0]).to_pydatetime())
        except Exception as exc:
            logger.exception("Failed to get latest timestamp for {} {}: {}", symbol, timeframe, exc)
            raise

    def get_candle_count(self, symbol: str, timeframe: str) -> int:
        """Return the stored candle count for a symbol and timeframe."""

        try:
            with self._write_lock:
                return int(
                    _scalar(self.conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM historical_candles
                        WHERE symbol = ? AND timeframe = ?
                        """,
                        [symbol, timeframe],
                    ).fetchone(), "candle count"),
                )
        except Exception as exc:
            logger.exception("Failed to get candle count for {} {}: {}", symbol, timeframe, exc)
            raise


    def log_download(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
        candles_fetched: int,
        candles_inserted: int,
        status: str,
        error_message: str | None,
        duration_sec: float,
    ) -> None:
        """Insert one download audit row into DuckDB."""

        audit_df = pd.DataFrame(
            [
                {
                    "id": None,
                    "symbol": symbol,
                    "exchange": exchange,
                    "timeframe": timeframe,
                    "from_date": from_date,
                    "to_date": to_date,
                    "candles_fetched": candles_fetched,
                    "candles_inserted": candles_inserted,
                    "status": status,
                    "error_message": error_message,
                    "duration_sec": duration_sec,
                },
            ],
        )
        table_name = f"temp_download_log_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, audit_df)
                self.conn.execute(
                f"""
                INSERT INTO download_log (
                    id,
                    symbol,
                    exchange,
                    timeframe,
                    from_date,
                    to_date,
                    candles_fetched,
                    candles_inserted,
                    status,
                    error_message,
                    duration_sec
                )
                SELECT
                    id,
                    symbol,
                    exchange,
                    timeframe,
                    from_date,
                    to_date,
                    candles_fetched,
                    candles_inserted,
                    status,
                    error_message,
                    duration_sec
                FROM {table_name}
                """
            )
        except Exception as exc:
            logger.exception("Failed to log download for {} {}: {}", symbol, timeframe, exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def log_quality_report(self, reports: list[dict[str, Any]]) -> None:
        """Flatten and bulk insert data-quality reports."""

        rows: list[dict[str, Any]] = []
        for report in reports:
            for check_type, details in report["checks"].items():
                rows.append(
                    {
                        "id": None,
                        "symbol": report["symbol"],
                        "timeframe": report["timeframe"],
                        "check_type": check_type,
                        "issue_count": int(details["count"]),
                        "details": json.dumps(details, default=str),
                        "checked_at": report["checked_at"],
                    },
                )

        if not rows:
            return

        report_df = pd.DataFrame(rows)
        table_name = f"temp_quality_report_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, report_df)
                self.conn.execute(
                f"""
                INSERT INTO quality_report (
                    id,
                    symbol,
                    timeframe,
                    check_type,
                    issue_count,
                    details,
                    checked_at
                )
                SELECT
                    id,
                    symbol,
                    timeframe,
                    check_type,
                    issue_count,
                    details,
                    checked_at
                FROM {table_name}
                """
            )
        except Exception as exc:
            logger.exception("Failed to log quality reports: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def get_all_symbols(self) -> list[str]:
        """Return all distinct symbols stored in historical data."""

        try:
            with self._write_lock:
                rows = self.conn.execute(
                    """
                    SELECT DISTINCT symbol
                    FROM historical_candles
                    ORDER BY symbol
                    """,
                ).fetchall()
            return [str(row[0]) for row in rows]
        except Exception as exc:
            logger.exception("Failed to fetch all symbols: {}", exc)
            raise

    def get_candles(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Return stored candles for a symbol/timeframe pair."""

        try:
            with self._write_lock:
                return self.conn.execute(
                    """
                    SELECT symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume
                    FROM historical_candles
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY timestamp
                    """,
                    [symbol, timeframe],
                ).df()
        except Exception as exc:
            logger.exception("Failed to load candles for {} {}: {}", symbol, timeframe, exc)
            raise

    def upsert_market_universe(self, rows: list[dict[str, Any]]) -> int:
        """Upsert canonical market metadata rows."""

        if not rows:
            return 0

        frame = pd.DataFrame(rows)
        required = {
            "symbol",
            "exchange",
            "asset_class",
            "currency",
            "timezone",
            "session_open",
            "session_close",
            "tradable",
            "lot_size",
            "tick_size",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Market universe rows are missing columns: {sorted(missing)}")

        table_name = f"temp_market_universe_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, frame)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO market_universe (
                        symbol,
                        exchange,
                        asset_class,
                        currency,
                        timezone,
                        session_open,
                        session_close,
                        tradable,
                        lot_size,
                        tick_size
                    )
                    SELECT
                        symbol,
                        exchange,
                        asset_class,
                        currency,
                        timezone,
                        session_open,
                        session_close,
                        tradable,
                        lot_size,
                        tick_size
                    FROM {table_name}
                    """
                )
            return len(frame)
        except Exception as exc:
            logger.exception("Failed to upsert market universe: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def upsert_feature_frame(self, df: pd.DataFrame, symbol: str, timeframe: str, feature_group: str = "default") -> int:
        """Flatten a feature frame into the feature store."""

        if df.empty:
            return 0
        if "timestamp" not in df.columns:
            raise ValueError("Feature frame must contain a timestamp column.")

        working = df.copy()
        working["timestamp"] = pd.to_datetime(working["timestamp"], utc=True, errors="coerce")
        feature_columns = [
            column
            for column in working.columns
            if column != "timestamp" and pd.api.types.is_numeric_dtype(working[column])
        ]
        if not feature_columns:
            return 0

        rows = working.melt(
            id_vars=["timestamp"],
            value_vars=feature_columns,
            var_name="feature_name",
            value_name="feature_value",
        )
        rows["symbol"] = symbol
        rows["timeframe"] = timeframe
        rows["feature_group"] = feature_group
        rows = rows.dropna(subset=["feature_value"])
        rows = rows[[
            "symbol",
            "timeframe",
            "timestamp",
            "feature_group",
            "feature_name",
            "feature_value",
        ]]

        table_name = f"temp_feature_store_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, rows)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO feature_store (
                        symbol,
                        timeframe,
                        timestamp,
                        feature_group,
                        feature_name,
                        feature_value
                    )
                    SELECT
                        symbol,
                        timeframe,
                        timestamp,
                        feature_group,
                        feature_name,
                        feature_value
                    FROM {table_name}
                    """
                )
            return len(rows)
        except Exception as exc:
            logger.exception("Failed to upsert feature frame for {} {}: {}", symbol, timeframe, exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def log_strategy_run(self, run_payload: dict[str, Any], metrics: Any) -> None:
        """Persist a completed strategy run and its summary metrics."""

        run_df = pd.DataFrame([run_payload])
        metrics_dict = metrics.__dict__ if hasattr(metrics, "__dict__") else dict(metrics)
        metric_rows = [
            {
                "run_id": run_payload["run_id"],
                "metric_name": metric_name,
                "metric_value": float(metric_value),
            }
            for metric_name, metric_value in metrics_dict.items()
        ]
        metric_df = pd.DataFrame(metric_rows)
        run_table = f"temp_strategy_run_{uuid.uuid4().hex}"
        metric_table = f"temp_strategy_metrics_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(run_table, run_df)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO strategy_runs (
                        run_id,
                        strategy_name,
                        asset_class,
                        symbol,
                        timeframe,
                        mode,
                        parameters_json,
                        data_hash,
                        status,
                        started_at,
                        finished_at,
                        notes
                    )
                    SELECT
                        run_id,
                        strategy_name,
                        asset_class,
                        symbol,
                        timeframe,
                        mode,
                        parameters_json,
                        data_hash,
                        status,
                        started_at,
                        finished_at,
                        notes
                    FROM {run_table}
                    """
                )
                self.conn.register(metric_table, metric_df)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO strategy_metrics (
                        run_id,
                        metric_name,
                        metric_value
                    )
                    SELECT
                        run_id,
                        metric_name,
                        metric_value
                    FROM {metric_table}
                    """
                )
        except Exception as exc:
            logger.exception("Failed to log strategy run {}: {}", run_payload.get("run_id"), exc)
            raise
        finally:
            self._safe_unregister(run_table)
            self._safe_unregister(metric_table)

    def log_strategy_orders(self, orders: list[dict[str, Any]]) -> None:
        """Persist order lifecycle rows."""

        if not orders:
            return
        order_df = pd.DataFrame(orders)
        table_name = f"temp_strategy_orders_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, order_df)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO strategy_orders (
                        order_id,
                        run_id,
                        symbol,
                        side,
                        quantity,
                        order_type,
                        time_in_force,
                        status,
                        requested_at,
                        filled_at,
                        limit_price,
                        stop_price,
                        average_fill_price,
                        slippage_bps,
                        fees,
                        metadata_json
                    )
                    SELECT
                        order_id,
                        run_id,
                        symbol,
                        side,
                        quantity,
                        order_type,
                        time_in_force,
                        status,
                        requested_at,
                        filled_at,
                        limit_price,
                        stop_price,
                        average_fill_price,
                        slippage_bps,
                        fees,
                        metadata_json
                    FROM {table_name}
                    """
                )
        except Exception as exc:
            logger.exception("Failed to log strategy orders: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def log_strategy_fills(self, fills: list[dict[str, Any]]) -> None:
        """Persist fill rows for backtest or paper sessions."""

        if not fills:
            return
        fill_df = pd.DataFrame(fills)
        table_name = f"temp_strategy_fills_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, fill_df)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO strategy_fills (
                        fill_id,
                        order_id,
                        run_id,
                        symbol,
                        timestamp,
                        quantity,
                        price,
                        side,
                        fill_type,
                        fees,
                        slippage_bps,
                        metadata_json
                    )
                    SELECT
                        fill_id,
                        order_id,
                        run_id,
                        symbol,
                        timestamp,
                        quantity,
                        price,
                        side,
                        fill_type,
                        fees,
                        slippage_bps,
                        metadata_json
                    FROM {table_name}
                    """
                )
        except Exception as exc:
            logger.exception("Failed to log strategy fills: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def log_paper_reconciliation(self, rows: list[dict[str, Any]]) -> None:
        """Persist paper-trading reconciliation rows."""

        if not rows:
            return
        frame = pd.DataFrame(rows)
        table_name = f"temp_paper_reconciliation_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                self.conn.register(table_name, frame)
                self.conn.execute(
                    f"""
                    INSERT OR REPLACE INTO paper_reconciliation (
                        run_id,
                        trade_date,
                        expected_orders,
                        submitted_orders,
                        filled_orders,
                        rejected_orders,
                        pnl,
                        drift,
                        notes
                    )
                    SELECT
                        run_id,
                        trade_date,
                        expected_orders,
                        submitted_orders,
                        filled_orders,
                        rejected_orders,
                        pnl,
                        drift,
                        notes
                    FROM {table_name}
                    """
                )
        except Exception as exc:
            logger.exception("Failed to log paper reconciliation rows: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def record_dataset(self, metadata: dict[str, Any], bars: pd.DataFrame) -> None:
        """Persist an immutable normalized dataset and its raw observations."""

        required = {
            "dataset_id", "provider_name", "provider_symbol", "canonical_symbol", "exchange",
            "timeframe", "adjustment", "timezone", "retrieved_at", "raw_hash",
            "transformation_hash", "status", "metadata_json",
        }
        missing = required.difference(metadata)
        if missing:
            raise ValueError(f"Dataset metadata is missing columns: {sorted(missing)}")
        if bars.empty:
            raise ValueError("A dataset snapshot must contain at least one bar.")

        observations = bars.copy()
        required_bar_columns = {"timestamp", "open", "high", "low", "close", "volume"}
        missing_bar_columns = required_bar_columns.difference(observations.columns)
        if missing_bar_columns:
            raise ValueError(f"Dataset bars are missing columns: {sorted(missing_bar_columns)}")
        observations["timestamp"] = pd.to_datetime(observations["timestamp"], utc=True, errors="coerce")
        observations = observations.dropna(subset=["timestamp", *required_bar_columns.difference({"timestamp"})])
        observations["dataset_id"] = metadata["dataset_id"]
        observations["symbol"] = metadata["canonical_symbol"]
        observations["exchange"] = metadata["exchange"]
        observations["timeframe"] = metadata["timeframe"]
        observations = observations[
            ["dataset_id", "symbol", "exchange", "timeframe", "timestamp", "open", "high", "low", "close", "volume"]
        ]
        self._replace_rows("market_datasets", [metadata])
        self._replace_frame("raw_bar_observations", observations)

    def record_provider_attempt(self, payload: dict[str, Any]) -> None:
        """Store every provider fetch attempt for fallback and audit visibility."""

        required = {"attempt_id", "provider_name", "request_json", "status", "started_at"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Provider attempt is missing fields: {sorted(missing)}")
        row = {
            "dataset_id": None,
            "error_message": None,
            "finished_at": None,
            **payload,
        }
        self._replace_rows("provider_attempts", [row])

    def upsert_instrument_alias(self, payload: dict[str, Any]) -> None:
        """Map one provider-specific symbol to a canonical instrument symbol."""

        required = {"canonical_symbol", "exchange", "provider_name", "provider_symbol"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Instrument alias is missing fields: {sorted(missing)}")
        self._replace_rows("instrument_aliases", [payload])

    def log_experiment(self, payload: dict[str, Any]) -> None:
        """Persist an experiment definition and reproducibility inputs."""

        required = {
            "experiment_id", "strategy_name", "strategy_version", "universe_json", "timeframe",
            "mode", "parameters_json", "feature_version", "cost_model_json", "source_revision",
            "llm_config_json", "status", "started_at",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Experiment is missing fields: {sorted(missing)}")
        row = {"benchmark_symbol": None, "data_hash": None, "finished_at": None, "notes": None, **payload}
        self._replace_rows("experiments", [row])

    def link_experiment_run(self, experiment_id: str, run_id: str, dataset_id: str | None, role: str = "primary") -> None:
        """Link a persisted deterministic strategy run to an experiment."""

        self._replace_rows(
            "experiment_runs",
            [{"experiment_id": experiment_id, "run_id": run_id, "dataset_id": dataset_id, "role": role}],
        )

    def create_research_task(self, payload: dict[str, Any]) -> None:
        """Create an auditable local orchestration task."""

        required = {"task_id", "goal_id", "task_name", "state", "input_json", "created_at"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Research task is missing fields: {sorted(missing)}")
        row = {
            "parent_task_id": None,
            "assigned_agent": None,
            "retry_count": 0,
            "max_retries": 0,
            "timeout_seconds": None,
            "output_json": None,
            "error_message": None,
            "token_usage": 0,
            "cost_usd": 0.0,
            "started_at": None,
            "finished_at": None,
            **payload,
        }
        self._replace_rows("research_tasks", [row])

    def update_research_task(self, task_id: str, **changes: Any) -> None:
        """Update a task state without exposing arbitrary SQL to agents."""

        allowed = {
            "state", "retry_count", "output_json", "error_message", "token_usage", "cost_usd",
            "started_at", "finished_at",
        }
        invalid = set(changes).difference(allowed)
        if invalid:
            raise ValueError(f"Unsupported task updates: {sorted(invalid)}")
        if not changes:
            return
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with self._write_lock:
            self.conn.execute(
                f"UPDATE research_tasks SET {assignments} WHERE task_id = ?",
                [*changes.values(), task_id],
            )

    def log_agent_run(self, payload: dict[str, Any]) -> None:
        """Persist model, cost, timing, and prompt provenance for an agent call."""

        required = {"agent_run_id", "task_id", "agent_name", "status", "prompt_hash", "started_at"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Agent run is missing fields: {sorted(missing)}")
        row = {"model_name": None, "token_usage": 0, "cost_usd": 0.0, "finished_at": None, **payload}
        self._replace_rows("agent_runs", [row])

    def log_agent_output(self, agent_run_id: str, output_json: str, evidence_json: str) -> None:
        """Persist validated structured output separately from model telemetry."""

        self._replace_rows(
            "agent_outputs",
            [{"agent_run_id": agent_run_id, "output_json": output_json, "evidence_json": evidence_json}],
        )

    def log_risk_decision(self, payload: dict[str, Any]) -> None:
        """Persist an independent risk approval, modification, or rejection."""

        required = {
            "decision_id", "symbol", "decision", "requested_notional", "approved_notional",
            "reasons_json", "policy_json", "decided_at",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Risk decision is missing fields: {sorted(missing)}")
        row = {"run_id": None, "experiment_id": None, **payload}
        self._replace_rows("risk_decisions", [row])

    def log_experiment_job(self, payload: dict[str, Any]) -> None:
        """Persist or update one deterministic resumable research job."""

        row = {
            "symbol": None, "universe_snapshot_id": None, "fold_id": None,
            "retry_count": 0, "max_retries": 2, "run_id": None,
            "error_message": None, "started_at": None, "finished_at": None,
            "data_revision": 0,
            "source_revision": None,
            "data_from": None,
            "data_to": None,
            "bar_count": None,
            **payload,
        }
        self._replace_rows("experiment_jobs", [row])

    def get_experiment_job(self, job_key: str) -> dict[str, Any] | None:
        """Return a job as a dictionary for resumability decisions."""

        result = self.conn.execute("SELECT * FROM experiment_jobs WHERE job_key = ?", [job_key])
        row = result.fetchone()
        if row is None:
            return None
        return dict(zip([description[0] for description in result.description], row))

    def recover_stale_research_work(self, stale_before: datetime) -> dict[str, int]:
        """Move abandoned RUNNING records to explicit retry or failed states."""

        with self.transaction():
            jobs = int(_scalar(self.conn.execute(
                """SELECT COUNT(*) FROM experiment_jobs
                   WHERE state = 'RUNNING' AND started_at < ?""",
                [stale_before],
            ).fetchone(), "stale experiment job count"))
            self.conn.execute(
                """UPDATE experiment_jobs
                   SET state = CASE WHEN retry_count < max_retries THEN 'RETRYING' ELSE 'FAILED' END,
                       error_message = 'Worker stopped before recording a terminal state',
                       finished_at = CASE WHEN retry_count < max_retries THEN NULL ELSE CURRENT_TIMESTAMP END
                   WHERE state = 'RUNNING' AND started_at < ?""",
                [stale_before],
            )
            experiments = int(_scalar(self.conn.execute(
                """SELECT COUNT(*) FROM experiments
                   WHERE status = 'RUNNING' AND started_at < ?""",
                [stale_before],
            ).fetchone(), "stale experiment count"))
            self.conn.execute(
                """UPDATE experiments
                   SET status = 'FAILED', finished_at = CURRENT_TIMESTAMP,
                       notes = 'Worker stopped before recording a terminal state'
                   WHERE status = 'RUNNING' AND started_at < ?""",
                [stale_before],
            )
        return {"jobs": jobs, "experiments": experiments}

    def cancel_superseded_experiment_jobs(self, source_revision: str, data_revision: int) -> int:
        """Cancel queued jobs whose code or canonical market-data revision changed."""

        with self._write_lock:
            count = int(_scalar(self.conn.execute(
                """SELECT COUNT(*) FROM experiment_jobs
                   WHERE state IN ('PENDING', 'RETRYING')
                     AND (COALESCE(source_revision, '') <> ? OR data_revision <> ?)""",
                [source_revision, data_revision],
            ).fetchone(), "superseded experiment job count"))
            self.conn.execute(
                """UPDATE experiment_jobs
                   SET state = 'CANCELLED',
                       error_message = 'Superseded by a newer source or market-data revision',
                       finished_at = CURRENT_TIMESTAMP
                   WHERE state IN ('PENDING', 'RETRYING')
                     AND (COALESCE(source_revision, '') <> ? OR data_revision <> ?)""",
                [source_revision, data_revision],
            )
        return count

    def log_portfolio_result(self, result: Any) -> None:
        """Persist authoritative portfolio replay artifacts and cost attribution."""

        with self.transaction():
            self.clear_backtest_artifacts(result.run.run_id)
            self.log_strategy_run(
                {
                    "run_id": result.run.run_id, "strategy_name": result.run.strategy_name,
                    "asset_class": result.run.asset_class.value, "symbol": result.run.symbol,
                    "timeframe": result.run.timeframe, "mode": result.run.mode,
                    "parameters_json": json.dumps(result.run.parameters, sort_keys=True, default=str),
                    "data_hash": result.run.data_hash, "status": "COMPLETED",
                    "started_at": datetime.now(timezone.utc), "finished_at": datetime.now(timezone.utc),
                    "notes": result.run.notes,
                },
                result.run.metrics,
            )
            self.log_strategy_orders(result.run.orders.to_dict(orient="records"))
            self.log_strategy_fills(result.run.fills.to_dict(orient="records"))
            self._replace_frame("portfolio_positions", result.positions)
            self._replace_frame("portfolio_rebalances", result.rebalances)
            self._replace_frame("trade_attribution", result.attribution)
            self._replace_frame("trade_round_trips", result.round_trips)
            self._replace_frame("fill_cost_components", result.cost_components)
            self.log_equity_curve(result.run.run_id, result.run.equity_curve)

    def clear_backtest_artifacts(self, run_id: str) -> None:
        """Remove regenerated base-run children while preserving walk-forward evidence."""

        for table in (
            "strategy_metrics", "strategy_orders", "strategy_fills", "portfolio_positions",
            "portfolio_rebalances", "trade_attribution", "trade_round_trips",
            "fill_cost_components",
        ):
            self.conn.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
        self.conn.execute(
            "DELETE FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'IN_SAMPLE'",
            [run_id],
        )

    def log_strategy_correlations(self, rows: list[dict[str, Any]]) -> None:
        self._replace_rows("strategy_correlations", rows)

    def log_promotion_review(self, payload: dict[str, Any]) -> None:
        self._replace_rows("promotion_reviews", [payload])

    def log_equity_curve(self, run_id: str, curve: pd.DataFrame, *, evidence_level: str = "IN_SAMPLE", fold_id: str | None = None) -> None:
        """Persist normalized return evidence used by RCA and promotion."""

        if curve.empty:
            return
        frame = curve.copy()
        frame["run_id"] = run_id
        exposure = frame["gross_exposure"] if "gross_exposure" in frame else frame.get("position", 0.0)
        frame["gross_exposure"] = pd.Series(exposure, index=frame.index).abs()
        frame["evidence_level"] = evidence_level
        frame["fold_id"] = fold_id or ""
        required = ["run_id", "timestamp", "equity", "gross_return", "net_return", "drawdown", "gross_exposure", "evidence_level", "fold_id"]
        self._replace_frame("strategy_equity_curve", frame[required])

    def _migrate_equity_curve_primary_key(self) -> None:
        """Retain in-sample and fold evidence independently on upgraded databases."""

        info = self.conn.execute("PRAGMA table_info('strategy_equity_curve')").fetchall()
        primary_columns = [row[1] for row in sorted((row for row in info if row[5]), key=lambda row: row[5])]
        if primary_columns != ["run_id", "timestamp"]:
            return
        self.conn.execute("DROP TABLE IF EXISTS strategy_equity_curve_v2")
        self.conn.execute("""
            CREATE TABLE strategy_equity_curve_v2 (
                run_id VARCHAR NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                equity DOUBLE NOT NULL,
                gross_return DOUBLE NOT NULL,
                net_return DOUBLE NOT NULL,
                drawdown DOUBLE NOT NULL,
                gross_exposure DOUBLE NOT NULL,
                evidence_level VARCHAR NOT NULL DEFAULT 'IN_SAMPLE',
                fold_id VARCHAR NOT NULL DEFAULT '',
                PRIMARY KEY (run_id, timestamp, evidence_level, fold_id)
            )
        """)
        self.conn.execute("""
            INSERT INTO strategy_equity_curve_v2
            SELECT run_id, timestamp, equity, gross_return, net_return, drawdown,
                   gross_exposure, evidence_level, COALESCE(fold_id, '')
            FROM strategy_equity_curve
        """)
        self.conn.execute("DROP TABLE strategy_equity_curve")
        self.conn.execute("ALTER TABLE strategy_equity_curve_v2 RENAME TO strategy_equity_curve")

    def _migrate_corporate_actions_schema(self) -> None:
        """Ensure corporate_actions table uses action_id VARCHAR PRIMARY KEY."""

        info = self.conn.execute("PRAGMA table_info('corporate_actions')").fetchall()
        if not info:
            return
        primary_columns = [row[1] for row in sorted((row for row in info if row[5]), key=lambda row: row[5])]
        if primary_columns == ["action_id"]:
            return
        logger.info("Migrating corporate_actions to action_id PRIMARY KEY schema...")
        self.conn.execute("DROP TABLE IF EXISTS corporate_actions_v2")
        self.conn.execute("""
            CREATE TABLE corporate_actions_v2 (
                action_id VARCHAR NOT NULL PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL DEFAULT 'NSE',
                action_type VARCHAR NOT NULL,
                ex_date DATE NOT NULL,
                record_date DATE,
                announcement_date DATE,
                payment_date DATE,
                share_multiplier DOUBLE NOT NULL DEFAULT 1.0,
                bonus_new_shares DOUBLE,
                bonus_existing_shares DOUBLE,
                old_face_value DOUBLE,
                new_face_value DOUBLE,
                dividend_amount DOUBLE DEFAULT 0.0,
                currency VARCHAR DEFAULT 'INR',
                purpose VARCHAR,
                source VARCHAR NOT NULL,
                source_event_id VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'ACTIVE',
                recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing_cols = {row[1] for row in info}
        action_id_expr = "COALESCE(action_id, symbol || '_' || CAST(ex_date AS VARCHAR) || '_' || action_type || '_' || SUBSTRING(MD5(RANDOM()::VARCHAR), 1, 8))" if "action_id" in existing_cols else "symbol || '_' || CAST(ex_date AS VARCHAR) || '_' || action_type || '_' || SUBSTRING(MD5(RANDOM()::VARCHAR), 1, 8)"
        exchange_expr = "COALESCE(exchange, 'NSE')" if "exchange" in existing_cols else "'NSE'"
        record_date_expr = "record_date" if "record_date" in existing_cols else "NULL"
        announcement_date_expr = "announcement_date" if "announcement_date" in existing_cols else "NULL"
        payment_date_expr = "payment_date" if "payment_date" in existing_cols else "NULL"
        share_multiplier_expr = "COALESCE(share_multiplier, 1.0)" if "share_multiplier" in existing_cols else "1.0"
        bonus_new_shares_expr = "bonus_new_shares" if "bonus_new_shares" in existing_cols else "NULL"
        bonus_existing_shares_expr = "bonus_existing_shares" if "bonus_existing_shares" in existing_cols else "NULL"
        old_face_value_expr = "old_face_value" if "old_face_value" in existing_cols else "NULL"
        new_face_value_expr = "new_face_value" if "new_face_value" in existing_cols else "NULL"
        dividend_amount_expr = "COALESCE(dividend_amount, 0.0)" if "dividend_amount" in existing_cols else "0.0"
        currency_expr = "COALESCE(currency, 'INR')" if "currency" in existing_cols else "'INR'"
        purpose_expr = "purpose" if "purpose" in existing_cols else "NULL"
        source_expr = "COALESCE(source, 'NSE')" if "source" in existing_cols else "'NSE'"
        source_event_id_expr = "source_event_id" if "source_event_id" in existing_cols else "NULL"
        status_expr = "COALESCE(status, 'ACTIVE')" if "status" in existing_cols else "'ACTIVE'"
        recorded_at_expr = "COALESCE(recorded_at, CURRENT_TIMESTAMP)" if "recorded_at" in existing_cols else "CURRENT_TIMESTAMP"

        self.conn.execute(f"""
            INSERT INTO corporate_actions_v2
            SELECT
                {action_id_expr} AS action_id,
                symbol,
                {exchange_expr} AS exchange,
                action_type,
                ex_date,
                {record_date_expr} AS record_date,
                {announcement_date_expr} AS announcement_date,
                {payment_date_expr} AS payment_date,
                {share_multiplier_expr} AS share_multiplier,
                {bonus_new_shares_expr} AS bonus_new_shares,
                {bonus_existing_shares_expr} AS bonus_existing_shares,
                {old_face_value_expr} AS old_face_value,
                {new_face_value_expr} AS new_face_value,
                {dividend_amount_expr} AS dividend_amount,
                {currency_expr} AS currency,
                {purpose_expr} AS purpose,
                {source_expr} AS source,
                {source_event_id_expr} AS source_event_id,
                {status_expr} AS status,
                {recorded_at_expr} AS recorded_at
            FROM corporate_actions
        """)
        self.conn.execute("DROP TABLE corporate_actions")
        self.conn.execute("ALTER TABLE corporate_actions_v2 RENAME TO corporate_actions")
        logger.info("✅ corporate_actions table schema migrated successfully.")



    def _replace_rows(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        """Insert-or-replace trusted internal payloads using a temporary relation."""

        if not rows:
            return
        self._replace_frame(table_name, pd.DataFrame(rows))

    def _replace_frame(self, table_name: str, frame: pd.DataFrame) -> None:
        """Insert a dataframe into a known schema table by matching column names."""

        if frame.empty:
            return
        temporary_name = f"temp_{table_name}_{uuid.uuid4().hex}"
        columns = list(frame.columns)
        column_sql = ", ".join(columns)
        try:
            with self._write_lock:
                self.conn.register(temporary_name, frame)
                self.conn.execute(
                    f"INSERT OR REPLACE INTO {table_name} ({column_sql}) SELECT {column_sql} FROM {temporary_name}",
                )
        finally:
            self._safe_unregister(temporary_name)

    def upsert_corporate_actions(self, rows: list[dict[str, Any]]) -> int:
        """Upsert corporate action events (splits, bonuses, dividends, consolidations)."""

        if not rows:
            return 0
        frame = pd.DataFrame(rows)
        if "action_id" not in frame.columns or frame["action_id"].isna().any():

            def _build_action_id(r: dict[str, Any]) -> str:
                existing = r.get("action_id")
                if existing and not pd.isna(existing):
                    return str(existing)
                source = str(r.get("source", "MANUAL")).strip().upper()
                src_id = str(r.get("source_event_id") or "").strip()
                sym = str(r.get("symbol", "UNKNOWN")).strip().upper()
                ex_d = str(r.get("ex_date", "NODATE")).strip()
                act_type = str(r.get("action_type", "ACTION")).strip().upper()
                mult = str(r.get("share_multiplier", 1.0))
                div = str(r.get("dividend_amount", 0.0))
                if src_id:
                    raw_seed = f"{source}:{src_id}:{sym}:{ex_d}"
                else:
                    raw_seed = f"{source}:{sym}:{ex_d}:{act_type}:{mult}:{div}"
                return f"act_{hashlib.sha256(raw_seed.encode()).hexdigest()[:16]}"

            frame["action_id"] = [_build_action_id(r) for r in frame.to_dict(orient="records")]
        if "share_multiplier" not in frame.columns:
            frame["share_multiplier"] = 1.0
        if "exchange" not in frame.columns:
            frame["exchange"] = "NSE"

        if "status" not in frame.columns:
            frame["status"] = "ACTIVE"
        if "recorded_at" not in frame.columns:
            frame["recorded_at"] = datetime.now(timezone.utc)
        self._replace_rows("corporate_actions", frame.to_dict(orient="records"))
        return len(frame)

    def get_corporate_actions(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Return sorted corporate action records for a symbol with optional date filters."""

        with self._write_lock:
            query = """
                SELECT action_id, symbol, exchange, action_type, ex_date, record_date, announcement_date,
                       payment_date, share_multiplier, bonus_new_shares, bonus_existing_shares,
                       old_face_value, new_face_value, dividend_amount, currency, purpose, source,
                       source_event_id, status
                FROM corporate_actions
                WHERE symbol = ?
            """
            params: list[Any] = [symbol]
            if start_date is not None:
                query += " AND ex_date >= ?"
                params.append(start_date)
            if end_date is not None:
                query += " AND ex_date <= ?"
                params.append(end_date)
            query += " ORDER BY ex_date ASC, recorded_at ASC"
            return self.conn.execute(query, params).df()

    def get_all_corporate_actions(self) -> pd.DataFrame:
        """Return all recorded corporate actions across all symbols."""

        with self._write_lock:
            return self.conn.execute(
                """
                SELECT action_id, symbol, exchange, action_type, ex_date, record_date, announcement_date,
                       payment_date, share_multiplier, bonus_new_shares, bonus_existing_shares,
                       old_face_value, new_face_value, dividend_amount, currency, purpose, source,
                       source_event_id, status
                FROM corporate_actions
                ORDER BY symbol ASC, ex_date ASC
                """
            ).df()

    def persist_source_semantics(
        self,
        dataset_id: str,
        semantics: Any,
        symbol: str | None = None,
        instrument_id: str | None = None,
    ) -> None:
        """Persist forensic source semantics admission and action-level detections.

        Args:
            dataset_id: Canonical dataset identifier.
            semantics: SourceBarSemantics instance.
            symbol: Optional trading symbol.
            instrument_id: Optional instrument identifier.
        """
        from data_platform.source_semantics import SourceSemanticsAdapter

        with self._write_lock:
            SourceSemanticsAdapter.persist_detections(
                conn=self.conn,
                dataset_id=dataset_id,
                semantics=semantics,
                symbol=symbol,
                instrument_id=instrument_id,
            )

    def close(self) -> None:
        """Close the DuckDB connection."""

        try:
            self.conn.close()
        except Exception as exc:
            logger.exception("Failed to close DuckDB connection: {}", exc)
            raise

    def _safe_unregister(self, table_name: str) -> None:
        """Unregister a temporary DuckDB relation and log cleanup issues.

        Args:
            table_name: Registered relation name.
        """

        try:
            with self._write_lock:
                self.conn.unregister(table_name)
        except Exception as exc:
            logger.debug("Skipping unregister for {}: {}", table_name, exc)

