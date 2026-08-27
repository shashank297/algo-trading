"""DuckDB storage manager for historical market data."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import date, datetime, timezone


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
        """Create all required DuckDB tables and run schema migrations."""

        try:
            with self._write_lock:
                from storage.migrations.runner import MigrationRunner
                MigrationRunner(self.conn).run_migrations()
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

    def record_stream_gap(
        self,
        *,
        gap_id: str,
        exchange: str,
        token: str,
        symbol: str,
        expected_sequence: int,
        received_sequence: int,
        gap_size: int,
        stream_epoch: int,
        detected_at: datetime,
    ) -> str:
        """Persist one unrepaired stream discontinuity in the canonical gap ledger."""
        if min(expected_sequence, received_sequence, gap_size, stream_epoch) < 0 or gap_size <= 0:
            raise ValueError("Stream gap evidence requires non-negative bounds and positive gap_size.")
        with self.transaction():
            self.conn.execute(
                """INSERT INTO stream_gaps (
                       gap_id, token, symbol, exchange, expected_sequence, received_sequence,
                       gap_size, stream_epoch, detected_at, gap_status, gap_start
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNREPAIRED', ?)""",
                [gap_id, token, symbol, exchange, expected_sequence, received_sequence,
                 gap_size, stream_epoch, detected_at, detected_at],
            )
        return gap_id

    def reanchor_stream_gap(
        self, *, exchange: str, token: str, stream_epoch: int, reanchored_at: datetime, evidence: dict[str, Any],
    ) -> list[tuple[str, str, datetime, datetime | None]]:
        """Durably close matching unrepaired ranges before trusted dispatch resumes."""
        with self.transaction():
            rows = self.conn.execute(
                """SELECT gap_id, symbol, gap_start, gap_end FROM stream_gaps
                   WHERE exchange = ? AND token = ? AND stream_epoch <= ? AND gap_status = 'UNREPAIRED'""",
                [exchange, token, stream_epoch],
            ).fetchall()
            self.conn.execute(
                """UPDATE stream_gaps SET gap_end = COALESCE(gap_end, ?), reanchored_at = ?,
                       reanchor_evidence_json = ?
                   WHERE exchange = ? AND token = ? AND stream_epoch <= ? AND gap_status = 'UNREPAIRED'""",
                [reanchored_at, reanchored_at, json.dumps(evidence, sort_keys=True, default=str),
                 exchange, token, stream_epoch],
            )
        return [(str(row[0]), str(row[1] or token), row[2], row[3]) for row in rows]

    def repair_stream_gap(self, *, gap_id: str, evidence: dict[str, Any], repaired_at: datetime) -> tuple[str, str, datetime, datetime | None]:
        """Mark a specific historical range repaired and return its interval for memory projection."""
        with self.transaction():
            row = self.conn.execute(
                "SELECT symbol, gap_start, gap_end FROM stream_gaps WHERE gap_id = ? AND gap_status = 'UNREPAIRED'",
                [gap_id],
            ).fetchone()
            if row is None:
                raise ValueError(f"No unrepaired canonical stream gap exists for {gap_id}.")
            self.conn.execute(
                """UPDATE stream_gaps SET gap_status = 'REPAIRED', repaired_at = ?, repair_evidence_json = ?
                   WHERE gap_id = ?""",
                [repaired_at, json.dumps(evidence, sort_keys=True, default=str), gap_id],
            )
        return gap_id, str(row[0]), row[1], row[2]

    def load_unrepaired_stream_gaps(self) -> list[tuple[str, str, datetime, datetime | None]]:
        """Load canonical unresolved intervals; database failure is intentionally propagated."""
        rows = self.conn.execute(
            "SELECT gap_id, symbol, gap_start, gap_end FROM stream_gaps WHERE gap_status = 'UNREPAIRED'"
        ).fetchall()
        if any(not row[0] or not row[1] or row[2] is None for row in rows):
            raise RuntimeError("Canonical stream gap ledger contains an invalid unresolved interval.")
        return [(str(row[0]), str(row[1]), row[2], row[3]) for row in rows]

    def load_unrepaired_stream_gap_state(self) -> list[tuple[str, str, str, str, datetime, datetime | None, int]]:
        """Load full canonical gap state for websocket restart recovery."""
        rows = self.conn.execute(
            """SELECT gap_id, exchange, token, symbol, gap_start, gap_end, stream_epoch
               FROM stream_gaps WHERE gap_status = 'UNREPAIRED'"""
        ).fetchall()
        if any(not row[0] or not row[1] or not row[2] or not row[3] or row[4] is None for row in rows):
            raise RuntimeError("Canonical stream gap ledger contains an invalid unresolved recovery record.")
        return [
            (str(row[0]), str(row[1]), str(row[2]), str(row[3]), row[4], row[5], int(row[6]))
            for row in rows
        ]

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
            dataset_id = report.get("dataset_id")
            certification_id = report.get("certification_id")
            for check_type, details in report["checks"].items():
                rows.append(
                    {
                        "id": None,
                        "symbol": report["symbol"],
                        "timeframe": report["timeframe"],
                        "dataset_id": dataset_id,
                        "certification_id": certification_id,
                        "check_type": check_type,
                        "issue_count": int(details.get("count", 0)),
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
                    dataset_id,
                    certification_id,
                    check_type,
                    issue_count,
                    details,
                    checked_at
                )
                SELECT
                    id,
                    symbol,
                    timeframe,
                    dataset_id,
                    certification_id,
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

    def log_atomic_quality_certification(
        self,
        *,
        certification_id: str,
        dataset_id: str,
        validator_version: str,
        check_count: int,
        issue_count: int,
        checks_json: str,
        status: str,
        started_at: datetime,
        completed_at: datetime,
        check_rows: list[dict[str, Any]],
    ) -> None:
        """Atomically persist a DQ certification batch and all child check rows in one transaction."""
        try:
            checks_payload = json.loads(checks_json)
        except (TypeError, json.JSONDecodeError):
            checks_payload = {}
        dataset_row = self.conn.execute(
            "SELECT transformation_hash FROM market_datasets WHERE dataset_id = ?",
            [dataset_id],
        ).fetchone()
        if dataset_row and dataset_row[0]:
            checks_payload["dataset_content_hash"] = str(dataset_row[0])
            checks_json = json.dumps(checks_payload, sort_keys=True)
        with self.transaction():
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO data_quality_certifications (
                        certification_id, dataset_id, validator_version,
                        check_count, issue_count, checks_json, status,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        certification_id, dataset_id, validator_version,
                        check_count, issue_count, checks_json, status,
                        started_at, completed_at,
                    ],
                )
                for r in check_rows:
                    cur.execute(
                        """
                        INSERT INTO quality_report (
                            symbol, timeframe, dataset_id, certification_id,
                            check_type, issue_count, details, checked_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            r["symbol"], r["timeframe"], dataset_id, certification_id,
                            r["check_type"], int(r["issue_count"]), r["details"], r["checked_at"],
                        ],
                    )

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
        if "starting_capital" not in run_df.columns:
            run_df["starting_capital"] = 100_000.0
        if "frame_certification_id" not in run_df.columns:
            run_df["frame_certification_id"] = None
        if "notes" not in run_df.columns:
            run_df["notes"] = None
        if "finished_at" not in run_df.columns:
            run_df["finished_at"] = None
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
                        notes,
                        starting_capital,
                        frame_certification_id
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
                        notes,
                        starting_capital,
                        frame_certification_id
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
        """Persist immutable fill rows; conflicting replay evidence is rejected."""

        if not fills:
            return
        fill_df = pd.DataFrame(fills)
        table_name = f"temp_strategy_fills_{uuid.uuid4().hex}"
        try:
            with self._write_lock:
                existing = self.conn.execute(
                    "SELECT fill_id, order_id, run_id, symbol, timestamp, quantity, price, side, fill_type "
                    "FROM strategy_fills WHERE fill_id IN (SELECT UNNEST(?))",
                    [fill_df["fill_id"].astype(str).tolist()],
                ).fetchall()
                proposed = {
                    str(row.fill_id): (
                        str(row.order_id), str(row.run_id), str(row.symbol), row.timestamp,
                        float(row.quantity), float(row.price), str(row.side), str(row.fill_type),
                    )
                    for row in fill_df.itertuples(index=False)
                }
                for row in existing:
                    persisted = (str(row[1]), str(row[2]), str(row[3]), row[4], float(row[5]), float(row[6]), str(row[7]), str(row[8]))
                    if proposed[str(row[0])] != persisted:
                        raise ValueError(f"Conflicting immutable fill evidence for fill_id={row[0]}.")
                self.conn.register(table_name, fill_df)
                self.conn.execute(
                    f"""
                    INSERT INTO strategy_fills (
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
                    ON CONFLICT (fill_id) DO NOTHING
                    """
                )
        except Exception as exc:
            logger.exception("Failed to log strategy fills: {}", exc)
            raise
        finally:
            self._safe_unregister(table_name)

    def record_paper_position_intents(self, rows: list[dict[str, Any]]) -> None:
        """Append desired-position evidence, rejecting a changed replay at the same instant."""
        for row in rows:
            existing = self.conn.execute(
                "SELECT desired_quantity FROM paper_position_intents WHERE session_id = ? AND symbol = ? AND as_of = ?",
                [row["session_id"], row["symbol"], row["as_of"]],
            ).fetchone()
            if existing is not None:
                if float(existing[0]) != float(row["desired_quantity"]):
                    raise ValueError("Conflicting desired-position evidence for an existing paper execution instant.")
                continue
            self.conn.execute(
                """INSERT INTO paper_position_intents
                   (intent_id, session_id, symbol, as_of, desired_quantity, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [row["intent_id"], row["session_id"], row["symbol"], row["as_of"], row["desired_quantity"], row["created_at"]],
            )

    def fill_derived_positions(self, session_id: str) -> dict[str, float]:
        """Rebuild observed position quantities from immutable fills only."""
        rows = self.conn.execute(
            """SELECT symbol, SUM(CASE WHEN side = 'BUY' THEN quantity ELSE -quantity END)
               FROM strategy_fills WHERE run_id = ? GROUP BY symbol""",
            [session_id],
        ).fetchall()
        return {str(symbol): float(quantity or 0.0) for symbol, quantity in rows}

    def latest_paper_position_intents(self, session_id: str) -> dict[str, float]:
        """Return the latest independently persisted desired quantity for each symbol."""
        rows = self.conn.execute(
            """SELECT symbol, desired_quantity FROM paper_position_intents
               WHERE session_id = ?
               QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY as_of DESC, created_at DESC) = 1""",
            [session_id],
        ).fetchall()
        return {str(symbol): float(quantity) for symbol, quantity in rows}

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
        observations["dataset_id"] = metadata["dataset_id"]
        observations["raw_dataset_id"] = metadata["dataset_id"]
        observations["symbol"] = metadata["canonical_symbol"]
        observations["exchange"] = metadata["exchange"]
        observations["timeframe"] = metadata["timeframe"]
        observations["provider_name"] = metadata.get("provider_name", "unknown")
        observations["source_row_number"] = list(range(len(observations)))
        observations["timestamp_raw"] = observations["timestamp"].astype(str)
        observations["open_raw"] = observations["open"].astype(str)
        observations["high_raw"] = observations["high"].astype(str)
        observations["low_raw"] = observations["low"].astype(str)
        observations["close_raw"] = observations["close"].astype(str)
        observations["volume_raw"] = observations["volume"].astype(str)
        observations["raw_row_json"] = "{}"
        observations["retrieved_at"] = metadata.get("retrieved_at", datetime.now(timezone.utc))
        self._replace_rows("market_datasets", [metadata])
        raw_cols = [
            "raw_dataset_id", "source_row_number", "symbol", "exchange", "timeframe",
            "provider_name", "timestamp_raw", "open_raw", "high_raw", "low_raw",
            "close_raw", "volume_raw", "raw_row_json", "retrieved_at",
        ]
        self._replace_frame("raw_bar_observations", observations[raw_cols])

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

    def register_experiment_family(self, family: Any) -> None:
        """Persist an immutable pre-registered research family."""
        payload = family.model_dump(mode="json")
        existing = self.conn.execute(
            "SELECT definition_hash FROM experiment_families WHERE experiment_family_id = ?",
            [family.experiment_family_id],
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != family.definition_hash:
                raise ValueError("Experiment family material definition is immutable.")
            return
        self.conn.execute(
            "INSERT INTO experiment_families VALUES (?, ?, ?, ?, ?, NULL)",
            [family.experiment_family_id, family.definition_hash, json.dumps(payload, sort_keys=True), family.maximum_trials, family.created_at],
        )

    def get_experiment_family(self, family_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT f.definition_json, f.maximum_trials, f.created_at,
                   COALESCE(f.started_at, (SELECT MIN(t.created_at) FROM research_trials_log t WHERE t.experiment_family_id = f.experiment_family_id))
            FROM experiment_families f
            WHERE f.experiment_family_id = ?
            """,
            [family_id],
        ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row[0]))
        value.update({"maximum_trials": int(row[1]), "created_at": row[2], "started_at": row[3]})
        return value

    def list_experiment_families(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT f.experiment_family_id, f.definition_json, f.maximum_trials, f.created_at,
                   COALESCE(f.started_at, (SELECT MIN(t.created_at) FROM research_trials_log t WHERE t.experiment_family_id = f.experiment_family_id))
            FROM experiment_families f
            ORDER BY f.created_at
            """
        ).fetchall()
        result = []
        for r in rows:
            val = json.loads(str(r[1]))
            val.update({"experiment_family_id": r[0], "maximum_trials": int(r[2]), "created_at": r[3], "started_at": r[4]})
            result.append(val)
        return result

    def create_research_trial(self, trial: Any) -> str:
        """Atomically reserve an immutable trial slot before execution."""
        max_retries = 10
        for attempt in range(max_retries):
            try:
                with self.transaction():
                    family = self.conn.execute(
                        "SELECT maximum_trials FROM experiment_families WHERE experiment_family_id = ?",
                        [trial.experiment_family_id],
                    ).fetchone()
                    if family is None:
                        raise ValueError("Research trial requires a pre-registered experiment family.")
                    
                    # Check if this exact trial or any successor attempt already SUCCEEDED
                    succeeded_attempt = self.conn.execute(
                        "SELECT trial_id FROM research_trials_log WHERE (trial_id = ? OR parent_trial_id = ?) AND status = 'SUCCEEDED'",
                        [trial.trial_id, trial.trial_id],
                    ).fetchone()
                    if succeeded_attempt is not None:
                        return str(succeeded_attempt[0])

                    # Check if an in-flight RUNNING attempt exists
                    running_attempt = self.conn.execute(
                        "SELECT trial_id FROM research_trials_log WHERE (trial_id = ? OR parent_trial_id = ?) AND status = 'RUNNING'",
                        [trial.trial_id, trial.trial_id],
                    ).fetchone()
                    if running_attempt is not None:
                        return str(running_attempt[0])

                    target_trial_id = trial.trial_id
                    parent_trial_id = getattr(trial, "parent_trial_id", None)

                    # Check if any prior attempts exist (for retry creation)
                    attempts_row = self.conn.execute(
                        "SELECT COUNT(*) FROM research_trials_log WHERE trial_id = ? OR parent_trial_id = ?",
                        [trial.trial_id, trial.trial_id],
                    ).fetchone()
                    attempt_count = int(attempts_row[0]) if attempts_row else 0
                    if attempt_count > 0:
                        target_trial_id = f"{trial.trial_id}#attempt={attempt_count + 1}"
                        parent_trial_id = trial.trial_id

                    consumed_row = self.conn.execute(
                        "SELECT COUNT(*) FROM research_trials_log WHERE experiment_family_id = ?",
                        [trial.experiment_family_id],
                    ).fetchone()
                    consumed = int(_scalar(consumed_row, "research trial count"))
                    if int(consumed) >= int(family[0]):
                        raise RuntimeError("Experiment family trial budget exhausted.")

                    # Serialize concurrent reservations for the same family via write lock on family row
                    self.conn.execute(
                        "UPDATE experiment_families SET started_at = ? WHERE experiment_family_id = ?",
                        [trial.created_at, trial.experiment_family_id],
                    )

                    trial_payload = trial.model_dump(mode="json")
                    trial_payload["trial_id"] = target_trial_id
                    trial_payload["parent_trial_id"] = parent_trial_id

                    self.conn.execute(
                        "INSERT INTO research_trials_log (trial_id, experiment_family_id, status, trial_json, parent_trial_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        [
                            target_trial_id,
                            trial.experiment_family_id,
                            trial.status.value if hasattr(trial.status, "value") else str(trial.status),
                            json.dumps(trial_payload, sort_keys=True, default=str),
                            parent_trial_id,
                            trial.created_at,
                        ],
                    )
                return target_trial_id
            except (RuntimeError, ValueError):
                raise
            except Exception as exc:
                if ("Conflict on update" in str(exc) or "TransactionContext Error" in str(exc)) and attempt < max_retries - 1:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("Failed to reserve research trial slot due to concurrent transaction contention.")

    def reserve_research_trial(self, trial: Any) -> str:
        """Alias for create_research_trial."""
        return self.create_research_trial(trial)

    def get_research_trial(self, trial_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT trial_id, status, trial_json, metrics_json, error_message, invalidation_reason, selected, created_at, started_at, finished_at, invalidated_at, parent_trial_id FROM research_trials_log WHERE trial_id = ?",
            [trial_id],
        ).fetchone()
        if row is None:
            return None
        trial_data = json.loads(str(row[2]))
        trial_data.update({
            "trial_id": row[0],
            "status": row[1],
            "metrics": json.loads(str(row[3])) if row[3] else None,
            "error_message": row[4],
            "invalidation_reason": row[5],
            "selected": bool(row[6]),
            "created_at": row[7],
            "started_at": row[8],
            "finished_at": row[9],
            "invalidated_at": row[10],
            "parent_trial_id": row[11],
        })
        return trial_data

    def find_exact_reusable_trial(self, trial_id: str) -> dict[str, Any] | None:
        """Find an exact SUCCEEDED trial that can be reused deterministically without consuming budget."""
        trial = self.get_research_trial(trial_id)
        if trial is not None and trial.get("status") == "SUCCEEDED" and not trial.get("invalidated"):
            return trial
        return None

    def transition_research_trial(
        self,
        trial_id: str,
        status: str,
        *,
        metrics: dict[str, Any] | None = None,
        error_message: str | None = None,
        invalidation_reason: str | None = None,
    ) -> None:
        """Append lifecycle evidence without deleting or replacing the trial."""
        row = self.conn.execute("SELECT status FROM research_trials_log WHERE trial_id = ?", [trial_id]).fetchone()
        if row is None:
            raise ValueError(f"Unknown research trial {trial_id}.")
        current_status = str(row[0])
        # If already in terminal state and transitioning to the same terminal state, allow idempotency
        if current_status in {"SUCCEEDED", "FAILED", "INVALIDATED", "CANCELLED"} and status == current_status:
            return
        if current_status in {"SUCCEEDED", "FAILED", "INVALIDATED", "CANCELLED"} and status != "INVALIDATED":
            raise ValueError(f"Invalid immutable research-trial transition from {current_status} to {status}.")
        now = datetime.now(timezone.utc)
        self.conn.execute(
            """
            UPDATE research_trials_log
            SET status=?,
                started_at=CASE WHEN ?='RUNNING' THEN COALESCE(started_at, ?) ELSE started_at END,
                finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED','CANCELLED','INVALIDATED') THEN COALESCE(finished_at, ?) ELSE finished_at END,
                metrics_json=COALESCE(?, metrics_json),
                metrics_hash=COALESCE(?, metrics_hash),
                error_message=COALESCE(?, error_message),
                invalidation_reason=COALESCE(?, invalidation_reason),
                invalidated_at=CASE WHEN ?='INVALIDATED' THEN COALESCE(invalidated_at, ?) ELSE invalidated_at END
            WHERE trial_id=?
            """,
            [
                status,
                status,
                now,
                status,
                now,
                json.dumps(metrics, sort_keys=True, default=str) if metrics is not None else None,
                hashlib.sha256(json.dumps(metrics, sort_keys=True, default=str).encode()).hexdigest() if metrics is not None else None,
                error_message,
                invalidation_reason,
                status,
                now,
                trial_id,
            ],
        )

    def mark_trial_selected(self, trial_id: str, selected: bool = True) -> None:
        """Mark whether this trial's candidate was selected as winning/optimal."""
        self.conn.execute(
            "UPDATE research_trials_log SET selected = ? WHERE trial_id = ?",
            [selected, trial_id],
        )

    def invalidate_trial(self, trial_id: str, reason: str) -> None:
        """Forensically invalidate a research trial while preserving its full history."""
        self.transition_research_trial(trial_id, "INVALIDATED", invalidation_reason=reason)

    def remaining_trial_budget(self, family_id: str) -> int:
        family = self.get_experiment_family(family_id)
        if family is None:
            raise ValueError(f"Unknown experiment family {family_id}.")
        consumed_row = self.conn.execute(
            "SELECT COUNT(*) FROM research_trials_log WHERE experiment_family_id = ?",
            [family_id],
        ).fetchone()
        consumed = int(_scalar(consumed_row, "research trial count"))
        return max(int(family["maximum_trials"]) - consumed, 0)

    def list_research_trials(
        self,
        family_id: str | None = None,
        strategy: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT trial_id, status, trial_json, metrics_json, error_message, invalidation_reason,
                   selected, created_at, started_at, finished_at, invalidated_at, parent_trial_id
            FROM research_trials_log
            WHERE (? IS NULL OR experiment_family_id=?)
              AND (? IS NULL OR trial_json LIKE ?)
              AND (? IS NULL OR status=?)
            ORDER BY created_at
            """,
            [family_id, family_id, strategy, f'%"strategy_name": "{strategy}"%' if strategy else None, status, status],
        ).fetchall()
        return [
            {
                **json.loads(str(row[2])),
                "trial_id": row[0],
                "status": row[1],
                "metrics": json.loads(str(row[3])) if row[3] else None,
                "error_message": row[4],
                "invalidation_reason": row[5],
                "selected": bool(row[6]),
                "created_at": row[7],
                "started_at": row[8],
                "finished_at": row[9],
                "invalidated_at": row[10],
                "parent_trial_id": row[11],
            }
            for row in rows
        ]

    def research_trial_summary(self, family_id: str) -> dict[str, Any]:
        family = self.get_experiment_family(family_id)
        if family is None:
            raise ValueError(f"Unknown experiment family {family_id}.")
        rows = self.conn.execute(
            "SELECT status, COUNT(*) FROM research_trials_log WHERE experiment_family_id=? GROUP BY status",
            [family_id],
        ).fetchall()
        counts = {str(status): int(count) for status, count in rows}
        consumed = sum(counts.values())
        selected_count_row = self.conn.execute(
            "SELECT COUNT(*) FROM research_trials_log WHERE experiment_family_id=? AND selected=TRUE",
            [family_id],
        ).fetchone()
        selected_count = int(_scalar(selected_count_row, "selected trial count"))
        return {
            "family": family,
            "counts": counts,
            "consumed": consumed,
            "remaining": max(int(family["maximum_trials"]) - consumed, 0),
            "selected_count": selected_count,
        }

    def recover_interrupted_research_trials(self) -> int:
        now = datetime.now(timezone.utc)
        count_row = self.conn.execute("SELECT COUNT(*) FROM research_trials_log WHERE status='RUNNING'").fetchone()
        count = int(_scalar(count_row, "running trials count"))
        if count > 0:
            self.conn.execute(
                "UPDATE research_trials_log SET status='FAILED', finished_at=?, error_message=COALESCE(error_message, 'INTERRUPTED_PROCESS') WHERE status='RUNNING'",
                [now],
            )
        return count


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
        table_cols_rows = self.conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        valid_cols = {r[1] for r in table_cols_rows}
        matched_cols = [col for col in frame.columns if col in valid_cols]
        if not matched_cols:
            return
        column_sql = ", ".join(matched_cols)
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

    def persist_raw_dataset(self, raw: Any) -> None:
        """Durably persist verbatim raw provider dataset before domain validation."""
        with self._write_lock:
            self.conn.execute("BEGIN TRANSACTION;")
            try:
                # 1. Insert into market_datasets with RAW_RECORDED
                declared_adj = raw.declared_adjustment.value if raw.declared_adjustment else "UNADJUSTED"
                timezone_val = raw.timezone_name or "Asia/Kolkata"
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO market_datasets (
                        dataset_id, parent_dataset_id, dataset_stage, symbol, canonical_symbol, exchange, timeframe,
                        provider_name, provider_symbol, provider_token, declared_adjustment, adjustment, timezone,
                        retrieved_at, lifecycle_status, status, raw_hash, transformation_hash, hash_algorithm, hash_version, row_count,
                        metadata_json, created_at, updated_at
                    ) VALUES (
                        ?, NULL, 'RAW', ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, 'RAW_RECORDED', 'VALID', ?, ?, ?, ?, ?,
                        '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    [
                        raw.raw_dataset_id,
                        raw.symbol,
                        raw.symbol,
                        raw.exchange,
                        raw.timeframe,
                        raw.provider_name,
                        raw.provider_symbol,
                        raw.provider_token,
                        declared_adj,
                        declared_adj,
                        timezone_val,
                        raw.retrieved_at,
                        raw.raw_hash,
                        raw.raw_hash,
                        raw.hash_algorithm,
                        raw.hash_version,
                        len(raw.parsed_rows),
                    ],
                )
                # 2. Insert into raw_bar_observations
                for row in raw.parsed_rows:
                    row_num = int(row.get("source_row_number", 0))
                    ts_raw = str(row.get("timestamp_raw", row.get("timestamp", "")))
                    o_raw = str(row.get("open_raw", row.get("open", "")))
                    h_raw = str(row.get("high_raw", row.get("high", "")))
                    l_raw = str(row.get("low_raw", row.get("low", "")))
                    c_raw = str(row.get("close_raw", row.get("close", "")))
                    v_raw = str(row.get("volume_raw", row.get("volume", "")))
                    row_json = json.dumps(row, default=str)
                    self.conn.execute(
                        """
                        INSERT OR REPLACE INTO raw_bar_observations (
                            raw_dataset_id, dataset_id, source_row_number, symbol, exchange, timeframe,
                            provider_name, timestamp_raw, open_raw, high_raw, low_raw, close_raw, volume_raw,
                            raw_row_json, retrieved_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?,
                            ?, ?
                        )
                        """,
                        [
                            raw.raw_dataset_id,
                            raw.raw_dataset_id,
                            row_num,
                            raw.symbol,
                            raw.exchange,
                            raw.timeframe,
                            raw.provider_name,
                            ts_raw,
                            o_raw,
                            h_raw,
                            l_raw,
                            c_raw,
                            v_raw,
                            row_json,
                            raw.retrieved_at,
                        ],
                    )
                self.conn.execute("COMMIT;")
            except Exception as exc:
                self.conn.execute("ROLLBACK;")
                logger.exception("Failed to persist raw dataset {}: {}", raw.raw_dataset_id, exc)
                raise

    def record_historical_quarantine(
        self,
        *,
        quarantine_id: str,
        raw_dataset_id: str,
        symbol: str,
        exchange: str,
        timeframe: str,
        provider_name: str,
        raw_hash: str,
        malformed_row_count: int,
        issues: list[Any] | tuple[Any, ...],
    ) -> None:
        """Atomically persist historical quarantine, row-level issues, and update lifecycle status."""
        with self._write_lock:
            self.conn.execute("BEGIN TRANSACTION;")
            try:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO historical_market_data_quarantine (
                        quarantine_id, raw_dataset_id, symbol, exchange, timeframe,
                        provider_name, raw_hash, malformed_row_count, quarantined_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    [
                        quarantine_id,
                        raw_dataset_id,
                        symbol,
                        exchange,
                        timeframe,
                        provider_name,
                        raw_hash,
                        malformed_row_count,
                    ],
                )
                for issue in issues:
                    ts_val = issue.event_timestamp
                    self.conn.execute(
                        """
                        INSERT OR REPLACE INTO historical_market_data_quarantine_issues (
                            quarantine_id, source_row_number, event_timestamp, reason_code, detected_at
                        ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        [
                            quarantine_id,
                            issue.source_row_number,
                            ts_val,
                            issue.reason_code,
                        ],
                    )
                self.conn.execute(
                    "UPDATE market_datasets SET lifecycle_status = 'QUARANTINED', updated_at = CURRENT_TIMESTAMP WHERE dataset_id = ?",
                    [raw_dataset_id],
                )
                self.conn.execute("COMMIT;")
            except Exception as exc:
                self.conn.execute("ROLLBACK;")
                logger.exception("Failed to record historical quarantine for {}: {}", raw_dataset_id, exc)
                raise

    def update_dataset_lifecycle_status(
        self,
        dataset_id: str,
        status: str,
        parent_dataset_id: str | None = None,
    ) -> None:
        """Update dataset lifecycle status in market_datasets."""
        with self._write_lock:
            if parent_dataset_id:
                self.conn.execute(
                    """
                    UPDATE market_datasets 
                    SET lifecycle_status = ?, parent_dataset_id = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE dataset_id = ?
                    """,
                    [status, parent_dataset_id, dataset_id],
                )
            else:
                self.conn.execute(
                    "UPDATE market_datasets SET lifecycle_status = ?, updated_at = CURRENT_TIMESTAMP WHERE dataset_id = ?",
                    [status, dataset_id],
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
