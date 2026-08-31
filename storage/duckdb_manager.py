"""DuckDB storage manager for historical market data."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict
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

    _path_locks: dict[str, threading.RLock] = {}
    _path_locks_lock = threading.Lock()

    @classmethod
    def _get_path_lock(cls, db_path: str) -> threading.RLock:
        import os
        norm = os.path.abspath(db_path) if db_path != ":memory:" else f":memory:{uuid.uuid4()}"
        with cls._path_locks_lock:
            if norm not in cls._path_locks:
                cls._path_locks[norm] = threading.RLock()
            return cls._path_locks[norm]

    def __init__(self, db_path: str) -> None:
        """Connect to DuckDB and initialize the schema.

        Args:
            db_path: Filesystem path to the DuckDB database file.
        """

        self.db_path = db_path
        self._write_lock = self._get_path_lock(db_path)
        
        with self._write_lock:
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

    @staticmethod
    def _availability_timestamp(value: datetime | str) -> datetime:
        """Normalize an explicit, timezone-aware information-availability time."""
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return timestamp.to_pydatetime()

    def record_market_dataset_availability(
        self, dataset_id: str, available_at: datetime | str,
    ) -> None:
        """Persist immutable source-publication availability for a dataset."""
        timestamp = self._availability_timestamp(available_at)
        existing = self.conn.execute(
            "SELECT available_at FROM market_dataset_availability WHERE dataset_id = ?", [dataset_id]
        ).fetchone()
        if existing is not None:
            if pd.Timestamp(existing[0]) != pd.Timestamp(timestamp):
                raise ValueError(f"Conflicting immutable dataset availability for {dataset_id}")
            return
        self.conn.execute(
            "INSERT INTO market_dataset_availability (dataset_id, available_at) VALUES (?, ?)",
            [dataset_id, timestamp],
        )

    def get_market_dataset_availability(self, dataset_id: str) -> datetime | None:
        """Return immutable dataset availability, if recorded."""
        row = self.conn.execute(
            "SELECT available_at FROM market_dataset_availability WHERE dataset_id = ?", [dataset_id]
        ).fetchone()
        return pd.Timestamp(row[0]).to_pydatetime() if row else None

    def record_historical_candle_availability(
        self, dataset_id: str, symbol: str, exchange: str, timeframe: str,
        timestamp: datetime | str, available_at: datetime | str,
    ) -> None:
        """Persist immutable source-publication availability for one candle."""
        bar_timestamp = self._availability_timestamp(timestamp)
        evidence_timestamp = self._availability_timestamp(available_at)
        key = [dataset_id, symbol, exchange, timeframe, bar_timestamp]
        existing = self.conn.execute(
            """SELECT available_at FROM historical_candle_availability
               WHERE dataset_id = ? AND symbol = ? AND exchange = ? AND timeframe = ? AND timestamp = ?""",
            key,
        ).fetchone()
        if existing is not None:
            if pd.Timestamp(existing[0]) != pd.Timestamp(evidence_timestamp):
                raise ValueError(f"Conflicting immutable candle availability for {dataset_id}/{symbol}/{timeframe}")
            return
        self.conn.execute(
            """INSERT INTO historical_candle_availability
               (dataset_id, symbol, exchange, timeframe, timestamp, available_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [*key, evidence_timestamp],
        )

    def record_historical_candle_availability_batch(
        self, dataset_id: str, symbol: str, exchange: str, timeframe: str,
        records: list[tuple[datetime | str, datetime | str]],
    ) -> None:
        """Persist a deterministic batch of immutable candle availability evidence."""
        for timestamp, available_at in records:
            self.record_historical_candle_availability(
                dataset_id, symbol, exchange, timeframe, timestamp, available_at,
            )

    def get_historical_candle_availability(
        self, dataset_id: str, symbol: str, exchange: str, timeframe: str, timestamp: datetime | str,
    ) -> datetime | None:
        """Return immutable candle availability, if recorded."""
        bar_timestamp = self._availability_timestamp(timestamp)
        row = self.conn.execute(
            """SELECT available_at FROM historical_candle_availability
               WHERE dataset_id = ? AND symbol = ? AND exchange = ? AND timeframe = ? AND timestamp = ?""",
            [dataset_id, symbol, exchange, timeframe, bar_timestamp],
        ).fetchone()
        return pd.Timestamp(row[0]).to_pydatetime() if row else None

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
        available_at: datetime | str | None = None,
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

                if dataset_id is not None and available_at is not None:
                    evidence_time = self._availability_timestamp(available_at)
                    self.record_historical_candle_availability_batch(
                        dataset_id, symbol, exchange, timeframe,
                        [(timestamp, evidence_time) for timestamp in insert_df["timestamp"]],
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
        row = self.conn.execute(
            "SELECT status, trial_json FROM research_trials_log WHERE trial_id = ?",
            [trial_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown research trial {trial_id}.")
        current_status = str(row[0])
        if status == "SUCCEEDED" and not self._has_authoritative_trial_lineage(str(row[1])):
            raise ValueError(
                "Governed research trials require a resolved data hash and frame certification before SUCCEEDED."
            )
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
        if selected:
            row = self.conn.execute(
                "SELECT status, trial_json FROM research_trials_log WHERE trial_id = ?",
                [trial_id],
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown research trial {trial_id}.")
            if str(row[0]) != "SUCCEEDED" or not self._has_authoritative_trial_lineage(str(row[1])):
                raise ValueError(
                    "Only SUCCEEDED trials with resolved data and frame lineage may be selected."
                )
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

    @staticmethod
    def _has_authoritative_trial_lineage(trial_json: str) -> bool:
        """Validate immutable governed lineage before terminal success or selection."""

        try:
            trial = json.loads(trial_json)
        except json.JSONDecodeError:
            return False
        data_hash = str(trial.get("data_hash") or "").strip()
        frame_certification_id = str(trial.get("frame_certification_id") or "").strip()
        return bool(data_hash and not data_hash.startswith("unresolved:") and frame_certification_id)


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

    # ------------------------------------------------------------------
    # Phase 2.2 — Derived dataset lineage and cross-provider verification
    # ------------------------------------------------------------------

    def load_certified_1m_source(
        self, *, source_dataset_id: str, symbol: str, exchange: str,
        start_ts: datetime | None = None, end_ts: datetime | None = None,
    ) -> dict[str, Any]:
        """Load one exact canonical 1m dataset only after authoritative admission checks."""
        row = self.conn.execute(
            """SELECT symbol, canonical_symbol, exchange, timeframe, provider_token,
                      adjustment, transformation_hash, raw_hash, status, lifecycle_status
               FROM market_datasets WHERE dataset_id = ?""",
            [source_dataset_id],
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown source dataset {source_dataset_id}.")
        ds_symbol, canonical_symbol, ds_exchange, timeframe, token, adjustment, transformed, raw, status, lifecycle = row
        if str(timeframe) != "1m" or str(status) != "VERIFIED" or str(lifecycle) != "CANONICAL_PROMOTED":
            raise ValueError("Source dataset must be exactly 1m, VERIFIED, and CANONICAL_PROMOTED.")
        if str(ds_symbol or canonical_symbol or "") != symbol or str(ds_exchange) != exchange:
            raise ValueError("Source dataset symbol/exchange does not match the requested derivation.")
        content_hash = str(transformed or raw or "").strip()
        if not content_hash:
            raise ValueError("Source dataset has no immutable content hash.")
        certs = self.conn.execute(
            """SELECT certification_id, checks_json FROM data_quality_certifications
               WHERE dataset_id = ? AND status = 'CERTIFIED' AND issue_count = 0
               ORDER BY completed_at DESC""", [source_dataset_id]
        ).fetchall()
        required = {"schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"}
        valid_cert = False
        for cert_id, checks_json in certs:
            try:
                bound_hash = json.loads(str(checks_json or "{}")).get("dataset_content_hash")
            except json.JSONDecodeError:
                continue
            checks = self.conn.execute(
                "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?", [cert_id]
            ).fetchall()
            if bound_hash == content_hash and len(checks) == 6 and {str(c[0]) for c in checks if int(c[1]) == 0} == required:
                valid_cert = True
                break
        if not valid_cert:
            raise ValueError("Source dataset lacks DQ certification bound to its immutable hash.")
        conditions = ["dataset_id = ?", "symbol = ?", "exchange = ?", "timeframe = '1m'"]
        params: list[Any] = [source_dataset_id, symbol, exchange]
        if start_ts is not None:
            conditions.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("timestamp < ?")
            params.append(end_ts)
        dataset_available_at = self.get_market_dataset_availability(source_dataset_id)
        if dataset_available_at is None:
            raise ValueError("Source dataset lacks immutable availability evidence.")
        bars = self.conn.execute(
            """SELECT candles.symbol, candles.exchange, candles.timeframe, candles.timestamp,
                      candles.open, candles.high, candles.low, candles.close, candles.volume,
                      candles.adjustment, candles.dataset_id, availability.available_at
               FROM historical_candles candles
               INNER JOIN historical_candle_availability availability
                 ON availability.dataset_id = candles.dataset_id
                AND availability.symbol = candles.symbol
                AND availability.exchange = candles.exchange
                AND availability.timeframe = candles.timeframe
                AND availability.timestamp = candles.timestamp
               WHERE """ + " AND ".join(conditions).replace("dataset_id", "candles.dataset_id").replace("symbol", "candles.symbol").replace("exchange", "candles.exchange").replace("timeframe", "candles.timeframe").replace("timestamp", "candles.timestamp") + " ORDER BY candles.timestamp", params
        ).df()
        if bars.empty:
            raise ValueError("No authoritative 1m source bars exist for the requested range.")
        return {"bars": bars, "adjustment": str(adjustment), "content_hash": content_hash,
                "provider_token": str(token or "DERIVED"), "dataset_available_at": dataset_available_at}

    def _has_authoritative_dq_certification(
        self,
        dataset_id: str,
        content_hash: str,
        decision_time: str,
    ) -> tuple[bool, str | None]:
        """Return whether a dataset has Phase 2.2 hash-bound DQ evidence."""
        certs = self.conn.execute(
            """SELECT certification_id, checks_json FROM data_quality_certifications
               WHERE dataset_id = ? AND status = 'CERTIFIED' AND issue_count = 0
                 AND completed_at <= ?
               ORDER BY completed_at DESC""",
            [dataset_id, decision_time],
        ).fetchall()
        required = {"schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"}
        for cert_id, checks_json in certs:
            try:
                bound_hash = json.loads(str(checks_json or "{}")).get("dataset_content_hash")
            except json.JSONDecodeError:
                continue
            checks = self.conn.execute(
                "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?", [cert_id]
            ).fetchall()
            if bound_hash == content_hash and {str(row[0]) for row in checks if int(row[1]) == 0} == required:
                return True, str(cert_id)
        return False, None

    def _has_completed_dq_integrity_failure(self, dataset_id: str, decision_time: str) -> bool:
        """Return whether an explicit causal DQ failure rejected this exact dataset."""
        row = self.conn.execute(
            """SELECT 1 FROM data_quality_certifications
               WHERE dataset_id = ? AND completed_at <= ?
                 AND (status <> 'CERTIFIED' OR issue_count > 0)
               LIMIT 1""",
            [dataset_id, decision_time],
        ).fetchone()
        return row is not None

    def is_certification_valid(
        self,
        certification_id: str,
        *,
        content_hash: str | None = None,
        decision_time: str | datetime | None = None,
    ) -> bool:
        """Return whether a certification exists, is CERTIFIED with zero issues, and completed by decision_time."""
        if not certification_id:
            return False
        try:
            query = "SELECT checks_json, status, issue_count FROM data_quality_certifications WHERE certification_id = ?"
            params: list[Any] = [certification_id]
            if decision_time is not None:
                decision_str = decision_time.isoformat() if isinstance(decision_time, datetime) else str(decision_time)
                query += " AND completed_at <= ?"
                params.append(decision_str)
            row = self.conn.execute(query, params).fetchone()
            if row is None:
                return False
            checks_json, status, issue_count = row
            if status != "CERTIFIED" or int(issue_count) != 0:
                return False
            if content_hash is not None and content_hash != "":
                try:
                    bound_hash = json.loads(str(checks_json or "{}")).get("dataset_content_hash")
                    if not bound_hash or bound_hash != content_hash:
                        return False
                except json.JSONDecodeError:
                    return False
            return True
        except Exception as exc:
            logger.warning("is_certification_valid failed: {}", exc)
            return False

    def persist_failed_derived_dataset(self, certification: "Any") -> None:
        """Retain failed derived DQ evidence without admitting bars to research."""
        if certification.dq_status != "DQ_FAILED":
            raise ValueError("Only DQ_FAILED derivation attempts may use the forensic failure ledger.")
        self.persist_derived_dataset(certification)

    def persist_certified_derived_dataset(
        self, *, certification: "Any", derived_bars: pd.DataFrame, source_provider_token: str,
    ) -> None:
        """Atomically admit a certified derived dataset with its bars and DQ evidence."""
        if certification.dq_status != "CERTIFIED":
            raise ValueError("Only CERTIFIED derived datasets may be admitted.")
        if derived_bars.empty:
            raise ValueError("Certified derived dataset cannot contain zero bars.")
        row = certification.to_storage_row()
        cert_id = f"derived-dq-{certification.derived_dataset_id}"
        required = ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]
        frame = derived_bars.copy()
        frame["symbol"] = certification.symbol
        frame["token"] = source_provider_token
        frame["exchange"] = certification.exchange
        frame["timeframe"] = certification.timeframe
        frame["adjustment"] = certification.adjustment_basis
        frame["provider_name"] = "derived"
        frame["dataset_id"] = certification.derived_dataset_id
        if "available_at" not in frame.columns:
            raise ValueError("Derived admission requires per-bar causal availability evidence.")
        availability_values = [self._availability_timestamp(value) for value in frame["available_at"]]
        dataset_available_at = max(availability_values)
        table_name = f"temp_derived_{uuid.uuid4().hex}"
        try:
            with self.transaction():
                self.conn.register(table_name, frame)
                self.conn.execute(
                    f"""INSERT INTO historical_candles
                       (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id)
                       SELECT symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id
                       FROM {table_name}"""
                )
                self.conn.execute(
                    """INSERT INTO market_datasets
                       (dataset_id, parent_dataset_id, dataset_stage, symbol, canonical_symbol, exchange, timeframe,
                        provider_name, provider_token, declared_adjustment, adjustment, lifecycle_status, status,
                        raw_hash, transformation_hash, hash_algorithm, hash_version, row_count, metadata_json)
                       VALUES (?, ?, 'DERIVED', ?, ?, ?, ?, 'derived', ?, ?, ?, 'CANONICAL_PROMOTED', 'VERIFIED',
                               ?, ?, 'SHA256', 'derived-session-v1', ?, ?)""",
                    [certification.derived_dataset_id, certification.source_dataset_ids[0], certification.symbol,
                     certification.symbol, certification.exchange, certification.timeframe, source_provider_token,
                     certification.adjustment_basis, certification.adjustment_basis, certification.content_hash,
                     certification.content_hash, certification.row_count, row["dq_report_json"]],
                )
                self.conn.execute(
                    """INSERT INTO derived_datasets
                       (derived_dataset_id, source_dataset_ids, source_content_hashes, symbol, exchange, timeframe,
                        adjustment_basis, resampler_version, calendar_version, start_ts, end_ts, row_count,
                        content_hash, dq_status, dq_report_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [row[key] for key in ("derived_dataset_id", "source_dataset_ids", "source_content_hashes", "symbol", "exchange", "timeframe", "adjustment_basis", "resampler_version", "calendar_version", "start_ts", "end_ts", "row_count", "content_hash", "dq_status", "dq_report_json", "created_at")],
                )
                self.record_market_dataset_availability(certification.derived_dataset_id, dataset_available_at)
                self.record_historical_candle_availability_batch(
                    certification.derived_dataset_id, certification.symbol, certification.exchange,
                    certification.timeframe,
                    list(zip(frame["timestamp"].tolist(), availability_values)),
                )
                checks_json = json.dumps({"dataset_content_hash": certification.content_hash, "derived_report": certification.dq_report}, sort_keys=True, default=str)
                now = datetime.now(timezone.utc)
                self.conn.execute(
                    """INSERT INTO data_quality_certifications
                       (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
                       VALUES (?, ?, ?, 6, 0, ?, 'CERTIFIED', ?, ?)""",
                    [cert_id, certification.derived_dataset_id, certification.resampler_version, checks_json, now, now],
                )
                for check_type in required:
                    self.conn.execute(
                        """INSERT INTO quality_report
                           (symbol, timeframe, dataset_id, certification_id, check_type, issue_count, details, checked_at)
                           VALUES (?, ?, ?, ?, ?, 0, '{}', ?)""",
                        [certification.symbol, certification.timeframe, certification.derived_dataset_id, cert_id, check_type, now],
                    )
        finally:
            self._safe_unregister(table_name)

    def persist_derived_dataset(self, certification: "Any") -> None:
        """Persist a :class:`~data_platform.resampling.DerivedDatasetCertification` to ``derived_datasets``.

        Args:
            certification: A ``DerivedDatasetCertification`` instance with ``.to_storage_row()``.
        """
        row = certification.to_storage_row()
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO derived_datasets (
                    derived_dataset_id, source_dataset_ids, source_content_hashes,
                    symbol, exchange, timeframe, adjustment_basis,
                    resampler_version, calendar_version,
                    start_ts, end_ts, row_count, content_hash,
                    dq_status, dq_report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["derived_dataset_id"],
                    row["source_dataset_ids"],
                    row["source_content_hashes"],
                    row["symbol"],
                    row["exchange"],
                    row["timeframe"],
                    row["adjustment_basis"],
                    row["resampler_version"],
                    row["calendar_version"],
                    row["start_ts"],
                    row["end_ts"],
                    row["row_count"],
                    row["content_hash"],
                    row["dq_status"],
                    row["dq_report_json"],
                    row["created_at"],
                ],
            )
        logger.debug(
            "Persisted derived_dataset: id={} symbol={} tf={} status={}",
            row["derived_dataset_id"][:8],
            row["symbol"],
            row["timeframe"],
            row["dq_status"],
        )

    def get_derived_datasets(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        source_dataset_id: str | None = None,
    ) -> list[dict]:
        """Query the ``derived_datasets`` registry.

        Args:
            symbol: Filter by symbol (optional).
            timeframe: Filter by timeframe (optional).
            source_dataset_id: Filter by source dataset_id substring match (optional).

        Returns:
            List of row dicts from ``derived_datasets``.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        if timeframe is not None:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        if source_dataset_id is not None:
            conditions.append("source_dataset_ids LIKE ?")
            params.append(f"%{source_dataset_id}%")

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM derived_datasets {where_clause} ORDER BY created_at DESC"
        try:
            result = self.conn.execute(sql, params).fetchdf()
            return result.to_dict(orient="records")
        except Exception as exc:
            logger.warning("get_derived_datasets failed: {}", exc)
            return []

    def get_canonical_1m_bars(
        self,
        *,
        source_dataset_id: str,
        symbol: str | None = None,
        exchange: str | None = None,
    ) -> "Any":
        """Load 1m bars from ``historical_candles`` for the given dataset_id.

        Args:
            source_dataset_id: The ``dataset_id`` of the CANONICAL_PROMOTED 1m source.
            symbol: Symbol filter (optional, used for logging).
            exchange: Exchange filter (optional).

        Returns:
            pandas DataFrame with OHLCV columns (UTC timestamps).
        """
        conditions = ["dataset_id = ?", "timeframe = '1m'"]
        params: list[Any] = [source_dataset_id]

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if exchange:
            conditions.append("exchange = ?")
            params.append(exchange)

        sql = (
            "SELECT symbol, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, dataset_id "
            f"FROM historical_candles WHERE {' AND '.join(conditions)} ORDER BY timestamp"
        )
        try:
            return self.conn.execute(sql, params).df()
        except Exception as exc:
            logger.error("get_canonical_1m_bars failed for dataset_id={}: {}", source_dataset_id, exc)
            raise

    def load_provider_verification_dataset(
        self, *, dataset_id: str, symbol: str, exchange: str, timeframe: str,
        provider_name: str, require_canonical: bool, start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> pd.DataFrame:
        """Load one identity-bound provider dataset for observational comparison."""
        record = self.conn.execute(
            """SELECT symbol, canonical_symbol, exchange, timeframe, provider_name, status, lifecycle_status
               FROM market_datasets WHERE dataset_id = ?""", [dataset_id]
        ).fetchone()
        if not record:
            raise ValueError(f"Unknown provider dataset {dataset_id}.")
        ds_symbol, canonical_symbol, ds_exchange, ds_timeframe, ds_provider, status, lifecycle = record
        if str(ds_symbol or canonical_symbol or "") != symbol or str(ds_exchange) != exchange or str(ds_timeframe) != timeframe:
            raise ValueError("Provider dataset identity does not match requested symbol/exchange/timeframe.")
        if str(ds_provider) != provider_name:
            raise ValueError("Provider dataset does not belong to the requested provider.")
        if require_canonical and (str(status) != "VERIFIED" or str(lifecycle) != "CANONICAL_PROMOTED"):
            raise ValueError("Primary provider dataset must be VERIFIED and CANONICAL_PROMOTED.")
        conditions = ["dataset_id = ?", "symbol = ?", "exchange = ?", "timeframe = ?"]
        params: list[Any] = [dataset_id, symbol, exchange, timeframe]
        if start_ts is not None:
            conditions.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("timestamp < ?")
            params.append(end_ts)
        return self.conn.execute(
            "SELECT * FROM historical_candles WHERE " + " AND ".join(conditions) + " ORDER BY timestamp", params
        ).df()

    def persist_reconciliation(
        self,
        report: "Any",
        *,
        comparison_date: "Any | None" = None,
    ) -> None:
        """Persist a :class:`~data_platform.provider_verification.ProviderVerificationReport` to ``cross_provider_reconciliations``.

        Args:
            report: A ``ProviderVerificationReport`` instance.
            comparison_date: Optional datetime for the comparison_date column.
        """
        row = report.to_storage_row(comparison_date=comparison_date)
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO cross_provider_reconciliations (
                    reconciliation_id, symbol, exchange, timeframe,
                    primary_provider, secondary_provider, comparison_version, comparison_date,
                    primary_dataset_id, secondary_dataset_id,
                    total_bars_primary, total_bars_secondary,
                    bars_match, bars_tolerance_match, bars_disagreement, bars_unavailable,
                    tolerance_config_json, bar_outcomes_json, overall_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["reconciliation_id"],
                    row["symbol"],
                    row["exchange"],
                    row["timeframe"],
                    row["primary_provider"],
                    row["secondary_provider"],
                    row["comparison_version"],
                    row["comparison_date"],
                    row["primary_dataset_id"],
                    row["secondary_dataset_id"],
                    row["total_bars_primary"],
                    row["total_bars_secondary"],
                    row["bars_match"],
                    row["bars_tolerance_match"],
                    row["bars_disagreement"],
                    row["bars_unavailable"],
                    row["tolerance_config_json"],
                    row["bar_outcomes_json"],
                    row["overall_status"],
                    row["created_at"],
                ],
            )
        logger.debug(
            "Persisted reconciliation: id={} {} {} {} → {}",
            row["reconciliation_id"][:8],
            row["symbol"],
            row["timeframe"],
            row["primary_provider"],
            row["overall_status"],
        )

    def get_reconciliations(
        self,
        *,
        symbol: str | None = None,
        exchange: str | None = None,
        timeframe: str | None = None,
        primary_provider: str | None = None,
        secondary_provider: str | None = None,
    ) -> list[dict]:
        """Query the ``cross_provider_reconciliations`` table.

        Args:
            symbol: Filter by symbol (optional).
            exchange: Filter by exchange (optional).
            timeframe: Filter by timeframe (optional).
            primary_provider: Filter by primary provider name (optional).
            secondary_provider: Filter by secondary provider name (optional).

        Returns:
            List of row dicts.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        if exchange is not None:
            conditions.append("exchange = ?")
            params.append(exchange)
        if timeframe is not None:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        if primary_provider is not None:
            conditions.append("primary_provider = ?")
            params.append(primary_provider)
        if secondary_provider is not None:
            conditions.append("secondary_provider = ?")
            params.append(secondary_provider)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM cross_provider_reconciliations {where_clause} ORDER BY created_at DESC"
        try:
            return self.conn.execute(sql, params).fetchdf().to_dict(orient="records")
        except Exception as exc:
            logger.warning("get_reconciliations failed: {}", exc)
            return []

    def load_regime_bars(
        self,
        symbol: str,
        timeframe: str,
        decision_time: str,
        *,
        exchange: str = "NSE",
        intraday: bool = False,
        context_type: str = "EOD",
    ) -> dict[str, Any]:
        """Load bars for market-regime evaluation from certified (VERIFIED + CANONICAL_PROMOTED) datasets only.

        Enforces Phase 2.3 PIT-certified data requirement: only bars whose dataset is
        both ``status='VERIFIED'`` and ``lifecycle_status='CANONICAL_PROMOTED'`` are
        returned.  When no certified dataset exists, returns an empty DataFrame with
        ``dataset_id=None`` so the caller can record ``missing_evidence`` rather than
        crash.

        For intraday=True the method prefers the finest available certified timeframe
        (1m → 5m → 15m) for the symbol/exchange pair.

        Args:
            symbol: Market symbol (e.g. ``'NIFTY200'``).
            timeframe: Requested timeframe (e.g. ``'1d'``, ``'1m'``).
            decision_time: ISO-8601 decision timestamp used as a label for ``cutoff_applied``.
                           The date component is extracted and used as the date-based cutoff.
            exchange: Exchange code (default ``'NSE'``).
            intraday: If True, search for finest certified intraday timeframe.

        Returns:
            Dict with keys:
              - ``bars``: :class:`pd.DataFrame` with OHLCV columns (may be empty).
              - ``dataset_id``: The certified dataset_id used (or ``None``).
              - ``content_hash``: The certified dataset content hash (or ``None``).
              - ``cutoff_applied``: The cutoff timestamp string applied to filter bars.
        """
        cutoff_applied = str(decision_time)
        normalized_context = str(context_type).upper()
        if normalized_context not in {"EOD", "INTRADAY"}:
            raise ValueError(f"Unsupported market-regime context: {context_type!r}")
        # Delayed imports avoid the storage/provider package cycle during bootstrap.
        from trading_stack.bar_availability import is_bar_available
        from trading_stack.calendars import build_nse_calendar

        # Determine which timeframes to attempt
        timeframes_to_try: list[str]
        if intraday:
            timeframes_to_try = ["1m", "5m", "15m", "30m", "60m"]
        else:
            timeframes_to_try = [timeframe]

        dq_integrity_failure = False

        for tf in timeframes_to_try:
            try:
                # Find certified candidate datasets for this symbol/timeframe/exchange ordered by availability
                ds_rows = self.conn.execute(
                    """
                    SELECT md.dataset_id,
                           COALESCE(md.transformation_hash, md.raw_hash) AS content_hash,
                           mda.available_at AS dataset_available_at
                    FROM market_datasets md
                    INNER JOIN market_dataset_availability mda ON mda.dataset_id = md.dataset_id
                    WHERE (md.symbol = ? OR md.canonical_symbol = ?)
                      AND md.exchange = ?
                      AND md.timeframe = ?
                      AND md.status = 'VERIFIED'
                      AND md.lifecycle_status = 'CANONICAL_PROMOTED'
                      AND mda.available_at <= ?
                    ORDER BY mda.available_at DESC
                    """,
                    [symbol, symbol, exchange, tf, cutoff_applied],
                ).fetchall()

                if not ds_rows:
                    continue  # try next timeframe

                for row_id, row_hash, row_avail in ds_rows:
                    valid_dq, cert_id = self._has_authoritative_dq_certification(
                        str(row_id), str(row_hash or ""), cutoff_applied
                    )
                    if not valid_dq:
                        dq_integrity_failure = (
                            dq_integrity_failure
                            or self._has_completed_dq_integrity_failure(str(row_id), cutoff_applied)
                        )
                        continue
                    bars = self.conn.execute(
                        """
                        SELECT hc.symbol, hc.exchange, hc.timeframe, hc.timestamp,
                               hc.open, hc.high, hc.low, hc.close, hc.volume, hc.adjustment,
                               hca.available_at AS candle_available_at
                        FROM historical_candles hc
                        INNER JOIN historical_candle_availability hca
                          ON hca.dataset_id = hc.dataset_id
                         AND hca.symbol = hc.symbol
                         AND hca.exchange = hc.exchange
                         AND hca.timeframe = hc.timeframe
                         AND hca.timestamp = hc.timestamp
                        WHERE hc.dataset_id = ?
                          AND hc.symbol = ?
                          AND hc.exchange = ?
                          AND hc.timeframe = ?
                          AND hca.available_at <= ?
                        ORDER BY hc.timestamp
                        """,
                        [str(row_id), symbol, exchange, tf, cutoff_applied],
                    ).df()

                    decision_dt = pd.Timestamp(cutoff_applied).to_pydatetime()
                    calendar = build_nse_calendar()
                    if normalized_context == "INTRADAY" and tf == "1d":
                        decision_session = pd.Timestamp(decision_dt).date()
                        bars = bars[pd.to_datetime(bars["timestamp"]).dt.date < decision_session].copy()
                    bars = bars[bars["timestamp"].map(
                        lambda timestamp: is_bar_available(pd.Timestamp(timestamp).to_pydatetime(), tf, decision_dt, calendar)
                    )].copy()
                    if bars.empty:
                        continue

                    last_bar = bars.iloc[-1]
                    return {
                        "bars": bars,
                        "dataset_id": str(row_id),
                        "content_hash": str(row_hash or ""),
                        "certification_id": cert_id,
                        "cutoff_applied": cutoff_applied,
                        "timeframe": tf,
                        "dataset_available_at": pd.Timestamp(row_avail).isoformat(),
                        "last_bar_timestamp": pd.Timestamp(last_bar["timestamp"]).isoformat(),
                        "last_bar_available_at": pd.Timestamp(last_bar["candle_available_at"]).isoformat(),
                        "integrity_failure": False,
                        "integrity_failure_reason": None,
                    }

            except Exception as exc:
                logger.warning(
                    "load_regime_bars failed for {}/{}/{}: {}", symbol, exchange, tf, exc
                )
                continue

        # No certified dataset found for any attempted timeframe
        return {
            "bars": pd.DataFrame(),
            "dataset_id": None,
            "content_hash": None,
            "certification_id": None,
            "cutoff_applied": cutoff_applied,
            "timeframe": None,
            "dataset_available_at": None,
            "last_bar_timestamp": None,
            "last_bar_available_at": None,
            "integrity_failure": dq_integrity_failure,
            "integrity_failure_reason": "EXPLICIT_DQ_FAILURE" if dq_integrity_failure else None,
        }

    def persist_market_regime_snapshot(self, snapshot: Any) -> None:
        """Persist an immutable MarketRegimeSnapshot.

        Identical replays are idempotent.  A conflicting payload for an existing
        ``regime_id`` raises rather than rewriting historical raw output.
        """
        with self._write_lock:
            data = self._market_regime_snapshot_data(snapshot)
            self._persist_market_regime_snapshot_locked(data)
        logger.debug(
            "Persisted market regime snapshot: id={} market={} as_of={} regime={} conf={}",
            data["regime_id"][:8],
            data["market"],
            data["as_of"],
            data["raw_regime"],
            data["confidence"],
        )

    @staticmethod
    def _market_regime_snapshot_data(snapshot: Any) -> dict[str, Any]:
        if hasattr(snapshot, "to_dict"):
            return snapshot.to_dict()
        if isinstance(snapshot, dict):
            return dict(snapshot)
        raise TypeError(f"Unsupported snapshot type: {type(snapshot)}")

    @staticmethod
    def _canonical_json(value: Any) -> str:
        if value is None:
            return "null"
        parsed = json.loads(value) if isinstance(value, str) else value
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)

    def _market_regime_semantic_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        json_fields = {
            "input_evidence_json", "missing_evidence_json",
            "input_evidence_manifest_json", "component_evidence_json",
        }
        fields = (
            "regime_id", "market", "benchmark", "context_type", "as_of", "decision_time",
            "raw_regime", "confidence", "trend_score", "volatility_score", "breadth_score",
            "dispersion_score", "liquidity_score", "stress_score", "input_evidence_json",
            "input_evidence_hash", "model_version", "policy_version", "policy_hash",
            "calendar_version", "missing_evidence_json", "input_evidence_manifest_json",
            "component_evidence_json",
        )
        payload: dict[str, Any] = {}
        for field in fields:
            value = data.get(field)
            if field in json_fields:
                value = self._canonical_json(value)
            elif field == "as_of":
                value = pd.Timestamp(value).date().isoformat()
            elif field == "decision_time":
                timestamp = pd.Timestamp(value)
                value = timestamp.tz_convert("UTC").isoformat() if timestamp.tzinfo else timestamp.isoformat()
            elif isinstance(value, float) and pd.isna(value):
                value = None
            payload[field] = value
        return payload

    def _persist_market_regime_snapshot_locked(self, data: dict[str, Any]) -> None:
        columns = (
            "regime_id", "market", "benchmark", "context_type", "as_of", "decision_time",
            "raw_regime", "confidence", "trend_score", "volatility_score", "breadth_score",
            "dispersion_score", "liquidity_score", "stress_score", "input_evidence_json",
            "input_evidence_hash", "model_version", "policy_version", "policy_hash",
            "calendar_version", "missing_evidence_json", "input_evidence_manifest_json",
            "component_evidence_json", "created_at",
        )
        existing = self.conn.execute(
            f"SELECT {', '.join(columns)} FROM market_regime_snapshots WHERE regime_id = ?",
            [data["regime_id"]],
        ).fetchone()
        if existing is not None:
            existing_data = dict(zip(columns, existing))
            if self._market_regime_semantic_payload(existing_data) != self._market_regime_semantic_payload(data):
                raise ValueError(f"Conflicting immutable raw regime snapshot: {data['regime_id']}")
            return
        placeholders = ", ".join("?" for _ in columns)
        self.conn.execute(
            f"INSERT INTO market_regime_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
            [data.get(column) for column in columns],
        )

    def get_regime_transition_state(
        self, market: str, benchmark: str, context_type: Any,
    ) -> Any | None:
        """Load restart-safe operational state for one context."""
        from trading_stack.market_regime import MarketContextType
        from trading_stack.regime_transition import OperationalMarketRegime, RegimeTransitionState

        context = context_type.value if hasattr(context_type, "value") else str(context_type)
        row = self.conn.execute(
            """SELECT operational_regime, pending_candidate_regime, candidate_started_at,
                      candidate_observations, candidate_confidence, last_raw_regime_id,
                      last_decision_time, policy_version, policy_hash, revision
               FROM operational_regime_states
               WHERE market = ? AND benchmark = ? AND context_type = ?""",
            [market, benchmark, context],
        ).fetchone()
        if row is None:
            return None
        return RegimeTransitionState(
            market=market, benchmark=benchmark, context_type=MarketContextType(context),
            operational_regime=OperationalMarketRegime(row[0]) if row[0] else None,
            pending_candidate_regime=OperationalMarketRegime(row[1]) if row[1] else None,
            candidate_started_at=row[2], candidate_observations=int(row[3]),
            candidate_confidence=row[4], last_raw_regime_id=row[5], last_decision_time=row[6],
            policy_version=row[7], policy_hash=row[8], revision=int(row[9]),
        )

    def get_operational_risk_state(
        self, market: str, benchmark: str, context_type: Any,
    ) -> Any | None:
        """Load restart-safe operational risk state for one context."""
        from trading_stack.market_regime import MarketContextType
        from trading_stack.regime_transition import OperationalRiskState, RiskTransitionState

        context = context_type.value if hasattr(context_type, "value") else str(context_type)
        row = self.conn.execute(
            """SELECT risk_state, release_candidate_state, release_started_at,
                      release_observations, last_stress_evidence_hash, last_decision_time,
                      policy_version, policy_hash, revision
               FROM operational_risk_states
               WHERE market = ? AND benchmark = ? AND context_type = ?""",
            [market, benchmark, context],
        ).fetchone()
        if row is None:
            return None
        return RiskTransitionState(
            market=market, benchmark=benchmark, context_type=MarketContextType(context),
            risk_state=OperationalRiskState(row[0]),
            release_candidate_state=OperationalRiskState(row[1]) if row[1] else None,
            release_started_at=row[2], release_observations=int(row[3]),
            last_stress_evidence_hash=row[4], last_decision_time=row[5],
            policy_version=row[6], policy_hash=row[7], revision=int(row[8]),
        )

    def persist_regime_transition(self, snapshot: Any, result: Any) -> None:
        """Atomically persist raw evidence, transition events, and both current states."""
        data = self._market_regime_snapshot_data(snapshot)
        with self._write_lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                self._persist_market_regime_snapshot_locked(data)
                if result.replayed:
                    self.conn.execute("COMMIT")
                    return
                state = result.state
                risk_state = result.risk_state
                context = state.context_type.value
                current_state = self.conn.execute(
                    "SELECT revision FROM operational_regime_states WHERE market=? AND benchmark=? AND context_type=?",
                    [state.market, state.benchmark, context],
                ).fetchone()
                current_risk = self.conn.execute(
                    "SELECT revision FROM operational_risk_states WHERE market=? AND benchmark=? AND context_type=?",
                    [state.market, state.benchmark, context],
                ).fetchone()
                expected_state_revision = state.revision - 1
                expected_risk_revision = risk_state.revision - 1
                if (int(current_state[0]) if current_state else 0) != expected_state_revision:
                    raise ValueError("Operational regime state revision conflict")
                if (int(current_risk[0]) if current_risk else 0) != expected_risk_revision:
                    raise ValueError("Operational risk state revision conflict")

                event = result.transition_event
                self.conn.execute(
                    """INSERT INTO regime_transition_events VALUES
                       (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    [
                        event.transition_id, state.market, state.benchmark, context, data["decision_time"],
                        data["regime_id"],
                        event.previous_operational_regime.value if event.previous_operational_regime else None,
                        event.raw_candidate_regime.value,
                        event.candidate_started_at, event.candidate_observations,
                        event.candidate_confidence, event.decision.value, event.reason,
                        event.operational_regime_after.value if event.operational_regime_after else None,
                        result.policy.policy_version, result.policy.compute_hash(),
                    ],
                )
                stress = result.risk_event.stress_evidence
                self.conn.execute(
                    """INSERT INTO risk_state_transition_events VALUES
                       (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    [
                        result.risk_event.risk_transition_id, state.market, state.benchmark, context,
                        data["decision_time"], data["regime_id"], result.risk_event.previous_risk_state.value,
                        json.dumps(stress.to_dict(), sort_keys=True) if stress else None,
                        stress.compute_hash() if stress else None, result.risk_event.decision.value,
                        result.risk_event.reason,
                        result.risk_event.release_candidate_state.value if result.risk_event.release_candidate_state else None,
                        result.risk_event.release_observations, result.risk_event.risk_state_after.value,
                        result.policy.policy_version, result.policy.compute_hash(),
                    ],
                )
                self._write_regime_state(state)
                self._write_risk_state(risk_state)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def _write_regime_state(self, state: Any) -> None:
        context = state.context_type.value
        self.conn.execute(
            "DELETE FROM operational_regime_states WHERE market=? AND benchmark=? AND context_type=?",
            [state.market, state.benchmark, context],
        )
        self.conn.execute(
            """INSERT INTO operational_regime_states VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                state.market, state.benchmark, context,
                state.operational_regime.value if state.operational_regime else None,
                state.pending_candidate_regime.value if state.pending_candidate_regime else None,
                state.candidate_started_at, state.candidate_observations, state.candidate_confidence,
                state.last_raw_regime_id, state.last_decision_time, state.policy_version,
                state.policy_hash, state.revision,
            ],
        )

    def _write_risk_state(self, state: Any) -> None:
        context = state.context_type.value
        self.conn.execute(
            "DELETE FROM operational_risk_states WHERE market=? AND benchmark=? AND context_type=?",
            [state.market, state.benchmark, context],
        )
        self.conn.execute(
            """INSERT INTO operational_risk_states VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                state.market, state.benchmark, context, state.risk_state.value,
                state.release_candidate_state.value if state.release_candidate_state else None,
                state.release_started_at, state.release_observations, state.last_stress_evidence_hash,
                state.last_decision_time, state.policy_version, state.policy_hash, state.revision,
            ],
        )

    def list_regime_transition_events(
        self, *, market: str | None = None, context_type: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable operational-regime decisions in causal order."""
        clauses: list[str] = []
        params: list[Any] = []
        if market:
            clauses.append("market = ?")
            params.append(market)
        if context_type:
            clauses.append("context_type = ?")
            params.append(context_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.conn.execute(
            f"SELECT * FROM regime_transition_events {where} ORDER BY decision_time, transition_id LIMIT ?",
            [*params, limit],
        ).fetchdf()
        return frame.to_dict("records")

    def list_risk_state_transition_events(
        self, *, market: str | None = None, context_type: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable operational risk decisions in causal order."""
        clauses: list[str] = []
        params: list[Any] = []
        if market:
            clauses.append("market = ?")
            params.append(market)
        if context_type:
            clauses.append("context_type = ?")
            params.append(context_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.conn.execute(
            f"SELECT * FROM risk_state_transition_events {where} ORDER BY decision_time, risk_transition_id LIMIT ?",
            [*params, limit],
        ).fetchdf()
        return frame.to_dict("records")

    def get_market_regime_snapshot(self, regime_id: str) -> dict[str, Any] | None:
        """Fetch a single MarketRegimeSnapshot by its unique regime_id."""
        records = self.conn.execute(
            "SELECT * FROM market_regime_snapshots WHERE regime_id = ?",
            [regime_id],
        ).fetchdf()
        if records.empty:
            return None
        return records.iloc[0].to_dict()

    def list_market_regime_snapshots(
        self,
        *,
        market: str | None = None,
        context_type: str | None = None,
        as_of: Any | None = None,
        raw_regime: str | None = None,
        model_version: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List market regime snapshots matching filters.

        Args:
            market: Optional market filter (e.g. 'NSE').
            context_type: Optional context filter ('EOD' or 'INTRADAY').
            as_of: Optional as_of date filter.
            raw_regime: Optional raw_regime filter.
            model_version: Optional model_version filter.
            limit: Maximum rows to return.

        Returns:
            List of snapshot row dicts.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if market is not None:
            conditions.append("market = ?")
            params.append(market)
        if context_type is not None:
            conditions.append("context_type = ?")
            params.append(str(context_type))
        if as_of is not None:
            conditions.append("as_of = ?")
            params.append(str(as_of))
        if raw_regime is not None:
            conditions.append("raw_regime = ?")
            params.append(str(raw_regime))
        if model_version is not None:
            conditions.append("model_version = ?")
            params.append(str(model_version))

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM market_regime_snapshots {where_clause} ORDER BY decision_time DESC, created_at DESC LIMIT ?"
        params.append(limit)

        try:
            return self.conn.execute(sql, params).fetchdf().to_dict(orient="records")
        except Exception as exc:
            logger.warning("list_market_regime_snapshots failed: {}", exc)
            return []

    def persist_asset_state_snapshot(self, snapshot: Any) -> None:
        """Persist an immutable asset-state snapshot with idempotent replay."""
        data = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
        columns = (
            "asset_state_id", "symbol", "exchange", "context_type", "as_of",
            "decision_time", "trend_score", "momentum_score", "volatility_score",
            "liquidity_score", "gap_risk_score", "mean_reversion_score",
            "relative_strength_score", "beta", "atr", "normalized_atr", "sector",
            "market_cap_bucket", "earnings_proximity", "behavior_cluster",
            "cluster_confidence", "eligibility", "eligibility_reasons_json",
            "features_json", "input_evidence_manifest_json", "input_evidence_hash",
            "input_hashes_json", "model_version", "policy_version", "policy_hash",
            "created_at",
        )
        with self._write_lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                existing = self.conn.execute(
                    f"SELECT {', '.join(columns)} FROM asset_state_snapshots WHERE asset_state_id = ?",
                    [data["asset_state_id"]],
                ).fetchone()
                if existing is not None:
                    existing_data = dict(zip(columns, existing))
                    if self._asset_state_semantic_payload(existing_data) != self._asset_state_semantic_payload(data):
                        raise ValueError(
                            f"Conflicting immutable asset state snapshot: {data['asset_state_id']}"
                        )
                    self.conn.execute("COMMIT")
                    return
                placeholders = ", ".join("?" for _ in columns)
                self.conn.execute(
                    f"INSERT INTO asset_state_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
                    [data.get(column) for column in columns],
                )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def _asset_state_semantic_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        json_fields = {
            "eligibility_reasons_json", "features_json",
            "input_evidence_manifest_json", "input_hashes_json",
        }
        payload: dict[str, Any] = {}
        for field, value in data.items():
            if field == "created_at":
                continue
            if field in json_fields:
                value = self._canonical_json(value)
            elif field == "as_of":
                value = pd.Timestamp(value).date().isoformat()
            elif field == "decision_time":
                timestamp = pd.Timestamp(value)
                value = timestamp.tz_convert("UTC").isoformat() if timestamp.tzinfo else timestamp.isoformat()
            elif isinstance(value, float) and pd.isna(value):
                value = None
            payload[field] = value
        return payload

    def get_asset_state_snapshot(self, asset_state_id: str) -> dict[str, Any] | None:
        """Fetch one immutable asset-state snapshot by deterministic identity."""
        frame = self.conn.execute(
            "SELECT * FROM asset_state_snapshots WHERE asset_state_id = ?",
            [asset_state_id],
        ).fetchdf()
        return None if frame.empty else frame.iloc[0].to_dict()

    def list_asset_state_snapshots(
        self,
        *,
        symbol: str | None = None,
        exchange: str | None = None,
        context_type: str | None = None,
        as_of: Any | None = None,
        behavior_cluster: str | None = None,
        eligibility: str | None = None,
        model_version: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List asset-state snapshots using deterministic indexed filters."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        filters = {
            "symbol": symbol,
            "exchange": exchange,
            "context_type": context_type,
            "as_of": str(as_of) if as_of is not None else None,
            "behavior_cluster": behavior_cluster,
            "eligibility": eligibility,
            "model_version": model_version,
        }
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return self.conn.execute(
            f"SELECT * FROM asset_state_snapshots {where} "
            "ORDER BY decision_time DESC, asset_state_id LIMIT ?",
            params,
        ).fetchdf().to_dict(orient="records")

    def save_robustness_evaluation(self, bundle: Any) -> str:
        """Persist an immutable strategy robustness evaluation bundle with idempotent replay and conflict check."""
        if hasattr(bundle, "model_dump"):
            data = bundle.model_dump(mode="json")
        elif hasattr(bundle, "to_dict"):
            data = bundle.to_dict()
        else:
            data = dict(bundle)

        columns = (
            "robustness_id", "run_id", "experiment_family_id", "strategy_name",
            "strategy_version", "selected_trial_id", "evidence_status",
            "psr_json", "dsr_json", "bootstrap_json", "monte_carlo_json",
            "cost_stress_json", "execution_stress_json", "parameter_robustness_json",
            "nested_folds_json", "policy_version", "policy_hash", "data_hash",
            "evidence_hash", "created_at",
        )

        row_payload = {
            "robustness_id": data["robustness_id"],
            "run_id": data["run_id"],
            "experiment_family_id": data.get("experiment_family_id"),
            "strategy_name": data["strategy_name"],
            "strategy_version": data["strategy_version"],
            "selected_trial_id": data.get("selected_trial_id"),
            "evidence_status": str(data["evidence_status"]),
            "psr_json": self._canonical_json(data["psr"]),
            "dsr_json": self._canonical_json(data["dsr"]),
            "bootstrap_json": self._canonical_json(data["bootstrap_intervals"]),
            "monte_carlo_json": self._canonical_json(data["monte_carlo"]),
            "cost_stress_json": self._canonical_json(data["cost_stress"]),
            "execution_stress_json": self._canonical_json(data["execution_stress"]),
            "parameter_robustness_json": self._canonical_json(data["parameter_robustness"]),
            "nested_folds_json": self._canonical_json(data["nested_folds"]),
            "policy_version": data["policy_version"],
            "policy_hash": data["policy_hash"],
            "data_hash": data["data_hash"],
            "evidence_hash": data["evidence_hash"],
            "created_at": data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }

        with self._write_lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                existing = self.conn.execute(
                    f"SELECT {', '.join(columns)} FROM strategy_robustness_evaluations WHERE robustness_id = ?",
                    [row_payload["robustness_id"]],
                ).fetchone()
                if existing is not None:
                    existing_data = dict(zip(columns, existing))
                    if self._robustness_semantic_payload(existing_data) != self._robustness_semantic_payload(row_payload):
                        raise ValueError(
                            f"Conflicting immutable robustness evaluation payload: {row_payload['robustness_id']}"
                        )
                    self.conn.execute("COMMIT")
                    return str(row_payload["robustness_id"])

                placeholders = ", ".join("?" for _ in columns)
                self.conn.execute(
                    f"INSERT INTO strategy_robustness_evaluations ({', '.join(columns)}) VALUES ({placeholders})",
                    [row_payload.get(column) for column in columns],
                )
                self.conn.execute("COMMIT")
                return str(row_payload["robustness_id"])
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def _robustness_semantic_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        json_fields = {
            "psr_json", "dsr_json", "bootstrap_json", "monte_carlo_json",
            "cost_stress_json", "execution_stress_json",
            "parameter_robustness_json", "nested_folds_json",
        }
        payload: dict[str, Any] = {}
        for field, value in data.items():
            if field == "created_at":
                continue
            if field in json_fields:
                value = self._canonical_json(value)
            payload[field] = value
        return payload

    def get_robustness_evaluation(self, robustness_id: str) -> dict[str, Any] | None:
        """Fetch one immutable robustness evaluation by ID."""
        frame = self.conn.execute(
            "SELECT * FROM strategy_robustness_evaluations WHERE robustness_id = ?",
            [robustness_id],
        ).fetchdf()
        return None if frame.empty else frame.iloc[0].to_dict()

    def list_robustness_evaluations(
        self,
        *,
        strategy_name: str | None = None,
        strategy_version: str | None = None,
        experiment_family_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List persisted robustness evaluations using indexed filters."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        filters = {
            "strategy_name": strategy_name,
            "strategy_version": strategy_version,
            "experiment_family_id": experiment_family_id,
            "run_id": run_id,
        }
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return self.conn.execute(
            f"SELECT * FROM strategy_robustness_evaluations {where} "
            "ORDER BY created_at DESC, robustness_id LIMIT ?",
            params,
        ).fetchdf().to_dict(orient="records")


    def list_phase2_7_conditional_evidence_at(
        self, decision_time: datetime, *, strategy_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Return only Phase 2.7 evidence available at an explicit historical cutoff."""
        if pd.Timestamp(decision_time).tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        query = "SELECT * FROM strategy_conditional_evidence WHERE available_at <= ?"
        params: list[Any] = [decision_time]
        if strategy_name is not None:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        return self.conn.execute(query + " ORDER BY available_at, evidence_id", params).fetchdf().to_dict("records")

    def persist_scorecard(self, scorecard: Any) -> str:
        data = dict(scorecard.__dict__)
        columns = (
            "scorecard_id", "strategy_name", "strategy_version", "horizon", "timeframe",
            "global_evidence_id", "conditional_evidence_id", "eligibility_status",
            "rejection_reasons_json", "performance_score", "downside_score",
            "fold_consistency_score", "parameter_robustness_score", "cost_robustness_score",
            "breadth_score", "paper_score", "regime_compatibility_score", "asset_compatibility_score",
            "drawdown_penalty", "turnover_penalty", "correlation_penalty", "capacity_penalty",
            "uncertainty_penalty", "overall_score", "available_at", "scorecard_version",
            "scorecard_policy_version", "scorecard_policy_hash", "evidence_hash",
            "evidence_ids_json", "explanation_json",
        )
        data.update(
            {
                "rejection_reasons_json": json.dumps(data.pop("rejection_reasons"), sort_keys=True),
                "evidence_ids_json": json.dumps(data.pop("evidence_ids"), sort_keys=True),
                "explanation_json": json.dumps(data.pop("explanation"), sort_keys=True, default=str),
            }
        )
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT evidence_hash FROM strategy_scorecards WHERE scorecard_id=?", [data["scorecard_id"]]
            ).fetchone()
            if existing and existing[0] != data["evidence_hash"]:
                raise ValueError("Conflicting immutable scorecard")
            if not existing:
                self.conn.execute(
                    f"INSERT INTO strategy_scorecards ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [data.get(column) for column in columns],
                )
        return str(data["scorecard_id"])

    def list_scorecards_at(
        self, decision_time: datetime, *, horizon: str | None = None, strategy_name: str | None = None
    ) -> list[dict[str, Any]]:
        if pd.Timestamp(decision_time).tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        query = "SELECT * FROM strategy_scorecards WHERE available_at <= ?"
        params: list[Any] = [decision_time]
        if horizon:
            query += " AND horizon = ?"
            params.append(horizon)
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        return self.conn.execute(query + " ORDER BY available_at, scorecard_id", params).fetchdf().to_dict("records")

    def persist_selector_decision(self, decision: Any) -> str:
        data = dict(decision.__dict__)
        json_fields = (
            "selected_strategies", "weights", "candidate_scorecards", "decision_reasons", "rejection_reasons",
        )
        for field in json_fields:
            data[field + "_json"] = json.dumps(data.pop(field), sort_keys=True)
        data["evidence_ids_json"] = json.dumps(data.pop("evidence_ids"), sort_keys=True, default=str)
        columns = (
            "selector_decision_id", "decision_time", "symbol", "horizon", "market_regime",
            "regime_confidence", "asset_cluster", "decision", "selected_strategies_json",
            "weights_json", "candidate_scorecards_json", "current_incumbent_strategy",
            "expected_benefit_estimate", "uncertainty", "switch_required", "estimated_switch_cost",
            "switch_buffer", "decision_reasons_json", "rejection_reasons_json",
            "selector_policy_version", "selector_policy_hash", "evidence_hash", "available_at",
            "evidence_ids_json",
        )
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT evidence_hash FROM selector_decisions WHERE selector_decision_id=?",
                [data["selector_decision_id"]],
            ).fetchone()
            if existing and existing[0] != data["evidence_hash"]:
                raise ValueError("Conflicting immutable selector decision")
            if not existing:
                self.conn.execute(
                    f"INSERT INTO selector_decisions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [data.get(column) for column in columns],
                )
        return str(data["selector_decision_id"])

    def get_selector_incumbent(self, symbol: str, horizon: str, at: datetime) -> str | None:
        row = self.conn.execute(
            """SELECT selected_strategies_json FROM selector_decisions
               WHERE symbol=? AND horizon=? AND decision_time <= ? AND decision <> 'ABSTAIN'
               ORDER BY decision_time DESC LIMIT 1""",
            [symbol, horizon, at],
        ).fetchone()
        return json.loads(row[0])[0] if row and json.loads(row[0]) else None

    def persist_meta_selector_result(
        self,
        result: Any,
        *,
        policy_version: str,
        selector_policy_version: str,
        selector_policy_hash: str,
        scorecard_policy_version: str | None = None,
        meta_split: str = "FINAL_OOS",
        purge_periods: int = 0,
        embargo_periods: int = 0,
        available_at: datetime | None = None,
    ) -> str:
        timestamp = available_at or datetime.now(timezone.utc)
        if pd.Timestamp(timestamp).tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        run_columns = (
            "meta_run_id", "policy_version", "selector_policy_version", "selector_policy_hash",
            "scorecard_policy_version", "meta_split", "purge_periods", "embargo_periods",
            "status", "verdict", "metrics_json", "baselines_json", "stress_results_json",
            "attribution_json", "checkpoint_json", "checkpoint_hash", "orders_json", "fills_json",
            "risk_decisions_json", "evidence_hash", "available_at",
            "final_oos_execution_hash",
        )
        run_data = {
            "meta_run_id": result.meta_run_id,
            "policy_version": policy_version,
            "selector_policy_version": selector_policy_version,
            "selector_policy_hash": selector_policy_hash,
            "scorecard_policy_version": scorecard_policy_version,
            "meta_split": meta_split,
            "purge_periods": purge_periods,
            "embargo_periods": embargo_periods,
            "status": "SUCCEEDED",
            "verdict": result.verdict,
            "metrics_json": json.dumps(result.metrics, sort_keys=True),
            "baselines_json": json.dumps(result.baselines, sort_keys=True),
            "stress_results_json": json.dumps(result.stress_results, sort_keys=True, default=str),
            "attribution_json": json.dumps(result.attribution, sort_keys=True),
            "checkpoint_json": json.dumps(asdict(result.checkpoint), sort_keys=True, default=str),
            "checkpoint_hash": result.checkpoint.checkpoint_hash,
            "orders_json": json.dumps(result.orders, sort_keys=True, default=str),
            "fills_json": json.dumps(result.fills, sort_keys=True, default=str),
            "risk_decisions_json": json.dumps(result.risk_decisions, sort_keys=True, default=str),
            "evidence_hash": result.evidence_hash,
            "available_at": timestamp,
            "final_oos_execution_hash": getattr(result, "final_oos_execution_hash", result.evidence_hash),
        }
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT evidence_hash FROM meta_selector_runs WHERE meta_run_id=?", [result.meta_run_id]
            ).fetchone()
            if existing and existing[0] != result.evidence_hash:
                raise ValueError("Conflicting immutable meta selector run")
            if not existing:
                self.conn.execute(
                    f"INSERT INTO meta_selector_runs ({', '.join(run_columns)}) VALUES ({', '.join('?' for _ in run_columns)})",
                    [run_data[column] for column in run_columns],
                )
                for row in result.equity_curve:
                    self.conn.execute(
                        """INSERT INTO meta_selector_equity_curve
                           (meta_run_id, timestamp, equity, net_return, drawdown, position, decision)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [
                            result.meta_run_id, row["timestamp"], row["equity"], row["net_return"],
                            row["drawdown"], row["position"], row["decision"],
                        ],
                    )
                for decision in result.decisions:
                    self.conn.execute(
                        """INSERT INTO meta_selector_decisions
                           (meta_run_id, selector_decision_id, decision_time, evidence_hash)
                           VALUES (?, ?, ?, ?)""",
                        [result.meta_run_id, decision.selector_decision_id, decision.decision_time, decision.evidence_hash],
                    )
                for switch in result.switches:
                    self.conn.execute(
                        """INSERT INTO meta_selector_switches
                           (meta_run_id, decision_time, old_strategy, new_strategy, switching_cost,
                            sells_first_json, buys_after_sells_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [
                            result.meta_run_id, switch["decision_time"], switch["old_strategy"],
                            switch["new_strategy"], switch["switching_cost"],
                            json.dumps(switch["sells_first"], sort_keys=True),
                            json.dumps(switch["buys_after_sells"], sort_keys=True),
                        ],
                    )
                for attribution_type, value in result.attribution.items():
                    self.conn.execute(
                        "INSERT INTO meta_selector_attribution (meta_run_id, attribution_type, value) VALUES (?, ?, ?)",
                        [result.meta_run_id, attribution_type, value],
                    )
        return str(result.meta_run_id)

    def load_meta_selector_checkpoint(self, meta_run_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT checkpoint_json, checkpoint_hash FROM meta_selector_runs WHERE meta_run_id=?",
            [meta_run_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown meta selector run {meta_run_id}")
        checkpoint = json.loads(str(row[0] or "{}"))
        if not checkpoint:
            raise ValueError(f"Meta selector run {meta_run_id} has no checkpoint")
        return checkpoint

    def persist_frozen_meta_policy(self, artifact: Any) -> str:
        values = asdict(artifact)
        columns = (
            "frozen_policy_id", "selector_policy_version", "selector_policy_hash",
            "scorecard_policy_hash", "meta_policy_version", "meta_policy_hash",
            "candidate_trial_ids", "selected_trial_id", "data_hash", "universe_lineage",
            "b2_strategy",
            "selection_rule", "selection_result",
            "selector_policy_payload", "meta_policy_payload", "scorecard_policy_payload",
            "cost_model_version", "cost_model_hash", "purge_periods", "embargo_periods",
            "frozen_at", "artifact_hash",
        )
        data = {
            **values,
            "candidate_trial_ids": json.dumps(values["candidate_trial_ids"], sort_keys=True),
            "universe_lineage": json.dumps(values["universe_lineage"], sort_keys=True),
            "selector_policy_payload": json.dumps(values["selector_policy_payload"], sort_keys=True),
            "meta_policy_payload": json.dumps(values["meta_policy_payload"], sort_keys=True),
            "scorecard_policy_payload": json.dumps(values["scorecard_policy_payload"], sort_keys=True),
        }
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT artifact_hash FROM frozen_meta_policies WHERE frozen_policy_id=?",
                [values["frozen_policy_id"]],
            ).fetchone()
            if existing and existing[0] != values["artifact_hash"]:
                raise ValueError("Conflicting immutable frozen meta policy")
            if not existing:
                self.conn.execute(
                    f"INSERT INTO frozen_meta_policies ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [data[column] for column in columns],
                )
        return str(values["frozen_policy_id"])

    def load_frozen_meta_policy(self, frozen_policy_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM frozen_meta_policies WHERE frozen_policy_id=?",
            [frozen_policy_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown frozen meta policy {frozen_policy_id}")
        columns = [item[0] for item in self.conn.description]
        result = dict(zip(columns, row))
        result["candidate_trial_ids"] = json.loads(str(result["candidate_trial_ids"]))
        result["universe_lineage"] = json.loads(str(result["universe_lineage"]))
        for field in ("selector_policy_payload", "meta_policy_payload", "scorecard_policy_payload"):
            result[field] = json.loads(str(result[field] or "{}"))
        return result

    def persist_final_oos_provenance_certificate(self, certificate: Any) -> str:
        values = asdict(certificate)
        json_fields = ("dataset_ids", "dataset_content_hashes", "evidence_hashes")
        for field in json_fields:
            values[field] = json.dumps(values[field], sort_keys=True)
        columns = tuple(values)
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT certificate_hash FROM final_oos_provenance_certificates WHERE certificate_id=?",
                [certificate.certificate_id],
            ).fetchone()
            if existing is not None and existing[0] != certificate.certificate_hash:
                raise ValueError("Conflicting immutable FINAL_OOS provenance certificate")
            if existing is None:
                self.conn.execute(
                    f"INSERT INTO final_oos_provenance_certificates ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [values[column] for column in columns],
                )
        return str(certificate.certificate_id)

    def load_final_oos_provenance_certificate(self, certificate_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM final_oos_provenance_certificates WHERE certificate_id=?", [certificate_id]
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown FINAL_OOS provenance certificate {certificate_id}")
        columns = [item[0] for item in self.conn.description]
        result = dict(zip(columns, row))
        for field in ("dataset_ids", "dataset_content_hashes", "evidence_hashes"):
            result[field] = json.loads(str(result[field]))
        return result

    def validate_final_oos_provenance_certificate(self, certificate_id: str) -> dict[str, Any]:
        certificate = self.load_final_oos_provenance_certificate(certificate_id)
        payload = {
            key: certificate[key]
            for key in (
                "frozen_policy_id", "frozen_policy_hash", "selected_trial_id",
                "selector_policy_hash", "meta_policy_hash", "scorecard_policy_hash",
                "dataset_ids", "dataset_content_hashes", "evidence_hashes", "resolver_hash",
                "execution_hash", "final_oos_start", "final_oos_end", "materialized_at",
                "cost_model_version", "cost_model_hash", "purge_periods", "embargo_periods",
            )
        }
        expected_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        if expected_hash != certificate["certificate_hash"]:
            raise ValueError("FINAL_OOS provenance certificate hash mismatch")
        result = self.conn.execute(
            "SELECT final_oos_execution_hash FROM meta_selector_runs WHERE meta_run_id IN (SELECT meta_run_id FROM meta_selector_runs WHERE final_oos_execution_hash = ?)",
            [certificate["execution_hash"]],
        ).fetchone()
        if result is None:
            raise ValueError("FINAL_OOS provenance certificate has no persisted execution result")
        if certificate["materialized_at"] <= certificate["final_oos_end"]:
            raise ValueError("FINAL_OOS provenance certificate materialized before completion")
        return certificate

    def persist_phase2_10_causal_risk_snapshot(self, snapshot: Any) -> str:
        values = asdict(snapshot)
        for field in ("sector_exposure", "var_inputs", "open_positions", "instrument_liquidity", "rolling_returns"):
            values[field] = json.dumps(values[field], sort_keys=True, default=str)
        columns = tuple(values)
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT snapshot_hash FROM phase2_10_causal_risk_snapshots WHERE snapshot_id=?",
                [values["snapshot_id"]],
            ).fetchone()
            if existing is not None and existing[0] != values["snapshot_hash"]:
                raise ValueError("Conflicting immutable causal risk snapshot")
            if existing is None:
                self.conn.execute(
                    f"INSERT INTO phase2_10_causal_risk_snapshots ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [values[column] for column in columns],
                )
        return str(values["snapshot_id"])

    def load_phase2_10_causal_risk_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM phase2_10_causal_risk_snapshots WHERE snapshot_id=?", [snapshot_id]
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown causal risk snapshot {snapshot_id}")
        columns = [item[0] for item in self.conn.description]
        result = dict(zip(columns, row))
        for field in ("sector_exposure", "var_inputs", "open_positions", "instrument_liquidity", "rolling_returns"):
            result[field] = json.loads(str(result[field]))
        return result

    def persist_phase2_10_empirical_acceptance(self, *, acceptance_id: str, meta_run_id: str,
                                                certificate_id: str, certificate_hash: str,
                                                execution_hash: str, verdict: str,
                                                accepted_at: datetime, acceptance_hash: str) -> str:
        values = (acceptance_id, meta_run_id, certificate_id, certificate_hash, execution_hash, verdict, accepted_at, acceptance_hash)
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT acceptance_hash FROM phase2_10_empirical_acceptance WHERE acceptance_id=?", [acceptance_id]
            ).fetchone()
            if existing is not None and existing[0] != acceptance_hash:
                raise ValueError("Conflicting immutable empirical acceptance")
            if existing is None:
                self.conn.execute(
                    "INSERT INTO phase2_10_empirical_acceptance VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values
                )
        return acceptance_id

    def list_research_trials_at(self, cutoff: datetime, *, family_id: str | None = None) -> list[dict[str, Any]]:
        if pd.Timestamp(cutoff).tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        trials = self.list_research_trials(family_id=family_id)
        return [
            trial for trial in trials
            if pd.Timestamp(trial["created_at"]).to_pydatetime() < cutoff
            and trial.get("status") == "SUCCEEDED"
        ]
