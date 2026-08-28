"""Resumably backfill NIFTY 200 daily and minute history from Angel One."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (
    apply_env_overrides,
    load_index_benchmark_symbol,
    load_universe_snapshot_symbols,
    load_yaml,
    validate_config,
)
from data_platform.contracts import PriceAdjustment
from data_platform.service import ingest_raw_provider_dataset
from smartapi import HistoricalDataClient, InstrumentMaster, RateLimiter, SmartAPIAuth
from storage import DuckDBManager
from trading_stack.bar_availability import bar_available_at
from trading_stack.calendars import MarketCalendar
from trading_stack.domain import infer_market_spec
from utils import LoggerSetup, get_ist_now


INTERVALS = {"1m": "ONE_MINUTE", "1d": "ONE_DAY"}
SOURCE_BOUNDARY_EMPTY_WINDOWS = 3
PERSISTENCE_BATCH_WINDOWS = 12


def _source_availability_for_backfill(frame: pd.DataFrame, symbol: str, exchange: str, timeframe: str) -> datetime:
    """Use the provider's completed-bar publication contract, never retrieval time."""
    calendar = MarketCalendar(infer_market_spec(symbol, exchange, "EQUITY"))
    return max(
        bar_available_at(pd.Timestamp(timestamp).to_pydatetime(), timeframe, calendar)
        for timestamp in frame["timestamp"]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-snapshot", required=True)
    parser.add_argument("--start-date", default="2012-01-01")
    parser.add_argument("--timeframes", default="1m,1d")
    parser.add_argument("--benchmark", default="NIFTY200")
    parser.add_argument("--symbols", default="", help="Optional comma-separated provider symbols.")
    parser.add_argument("--full-backward", action="store_true", help="Attempt to download backwards to start-date even if data exists (useful for filling historical gaps).")
    parser.add_argument("--max-workers", type=int, default=3, choices=range(1, 4))
    parser.add_argument(
        "--max-windows",
        type=int,
        default=None,
        help="Bound API windows per symbol/timeframe for smoke tests; omit for complete backfill.",
    )
    return parser


def _stored_bounds(db: DuckDBManager, symbol: str, timeframe: str) -> tuple[datetime | None, datetime | None]:
    with db._write_lock:
        row = db.conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM historical_candles WHERE symbol = ? AND timeframe = ?",
            [symbol, timeframe],
        ).fetchone()
    if row is None:
        raise RuntimeError(f"DuckDB returned no bounds row for {symbol} {timeframe}.")
    return row[0], row[1]


def _backward_windows(end_date: date, start_date: date, window_days: int):
    cursor = end_date
    while cursor >= start_date:
        window_start = max(start_date, cursor - timedelta(days=window_days - 1))
        yield window_start, cursor
        cursor = window_start - timedelta(days=1)


def _forward_windows(start_date: date, end_date: date, window_days: int):
    cursor = start_date
    while cursor <= end_date:
        window_end = min(end_date, cursor + timedelta(days=window_days - 1))
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _backfill_timeframe(
    db: DuckDBManager,
    historical: HistoricalDataClient,
    symbol_config: dict[str, Any],
    timeframe: str,
    requested_start: date,
    requested_end: date,
    max_windows: int | None,
    full_backward: bool = False,
) -> dict[str, Any]:
    symbol = str(symbol_config["symbol"])
    token = str(symbol_config["token"])
    exchange = str(symbol_config["exchange"])
    interval = INTERVALS[timeframe]
    window_days = int(historical.config["rate_limits"][f"chunk_days_{'1min' if timeframe == '1m' else '1day'}"])
    earliest, latest = _stored_bounds(db, symbol, timeframe)
    backward_end = earliest.date() if earliest is not None else requested_end
    forward_start = latest.date() if latest is not None else requested_end
    windows_used = 0
    inserted_total = 0
    stopped_at_source_boundary = False
    failed = False
    quarantined = False
    consecutive_empty_windows = 0
    pending_frames: list[tuple[Any, date, date]] = []

    def flush_pending() -> None:
        nonlocal inserted_total, quarantined
        if not pending_frames:
            return
        res = _persist_backfill_batch(
            db, pending_frames, symbol, token, exchange, timeframe,
        )
        if isinstance(res, tuple):
            count, batch_status = res
        else:
            count, batch_status = int(res), "SUCCESS"
        inserted_total += count
        if batch_status == "QUARANTINED":
            quarantined = True
        pending_frames.clear()

    if earliest is None or full_backward:
        for window_start, window_end in _backward_windows(backward_end, requested_start, window_days):
            if max_windows is not None and windows_used >= max_windows:
                break
            frame = historical.fetch_candles(symbol, token, exchange, interval, window_start, window_end)
            windows_used += 1
            failed_chunks = frame.attrs.get("failed_chunks", [])
            if failed_chunks:
                flush_pending()
                _record_backfill_attempt(db, symbol, timeframe, window_start, window_end, "FAILED", "; ".join(failed_chunks))
                failed = True
                break
            if frame.empty:
                _record_backfill_attempt(db, symbol, timeframe, window_start, window_end, "EMPTY", None)
                consecutive_empty_windows += 1
                if consecutive_empty_windows >= SOURCE_BOUNDARY_EMPTY_WINDOWS:
                    flush_pending()
                    stopped_at_source_boundary = True
                    break
                continue
            consecutive_empty_windows = 0
            pending_frames.append((frame, window_start, window_end))
            if len(pending_frames) >= PERSISTENCE_BATCH_WINDOWS:
                flush_pending()

    flush_pending()

    if earliest is not None and not failed:
        for window_start, window_end in _forward_windows(forward_start, requested_end, window_days):
            if max_windows is not None and windows_used >= max_windows:
                break
            frame = historical.fetch_candles(symbol, token, exchange, interval, window_start, window_end)
            windows_used += 1
            failed_chunks = frame.attrs.get("failed_chunks", [])
            if failed_chunks:
                flush_pending()
                _record_backfill_attempt(db, symbol, timeframe, window_start, window_end, "FAILED", "; ".join(failed_chunks))
                failed = True
                break
            if frame.empty:
                _record_backfill_attempt(db, symbol, timeframe, window_start, window_end, "EMPTY", None)
                continue
            pending_frames.append((frame, window_start, window_end))
            if len(pending_frames) >= PERSISTENCE_BATCH_WINDOWS:
                flush_pending()

    flush_pending()

    final_earliest, final_latest = _stored_bounds(db, symbol, timeframe)
    status_label = "QUARANTINED" if quarantined else "FAILED" if failed else "SUCCESS"
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "windows": windows_used,
        "inserted": inserted_total,
        "earliest": final_earliest,
        "latest": final_latest,
        "source_boundary": stopped_at_source_boundary,
        "status": status_label,
    }


def _persist_backfill_batch(
    db: DuckDBManager,
    windows: list[tuple[pd.DataFrame, date, date]],
    symbol: str,
    token: str,
    exchange: str,
    timeframe: str,
) -> tuple[int, str]:
    if not windows:
        return 0, "SUCCESS"
    frame = pd.concat([item[0] for item in windows], ignore_index=True)
    available_at = _source_availability_for_backfill(frame, symbol, exchange, timeframe)

    result = ingest_raw_provider_dataset(
        bars=frame,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        provider_name="angel_one",
        provider_symbol=symbol,
        provider_token=token,
        declared_adjustment=PriceAdjustment.UNADJUSTED,
        timezone_name="Asia/Kolkata",
        available_at=available_at,
        db=db,
        target_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
    )

    with db.transaction():
        attempt_status = "SUCCEEDED" if result.raw_status == "STRUCTURALLY_VALID" and result.canonical_status == "VERIFIED" else "QUARANTINED"
        for _, requested_start, requested_end in windows:
            _record_backfill_attempt(
                db,
                symbol,
                timeframe,
                requested_start,
                requested_end,
                attempt_status,
                "; ".join(result.quarantine_reasons) if result.quarantine_reasons else None,
                result.canonical_dataset_id or result.raw_dataset_id,
            )

    if result.raw_status == "QUARANTINED":
        logger.warning(
            "Backfill dataset for {} {} quarantined: {}",
            symbol,
            timeframe,
            result.quarantine_reasons,
        )
        return 0, "QUARANTINED"
    elif result.canonical_status != "VERIFIED" and (result.bars is None or result.bars.empty):
        logger.warning(
            "Backfill dataset for {} {} unadmitted: {}",
            symbol,
            timeframe,
            result.canonical_status,
        )
        return 0, "UNADMITTED"

    return (len(result.bars) if result.bars is not None else 0), "SUCCESS"


def _persist_backfill_frame(
    db: DuckDBManager,
    frame: Any,
    symbol: str,
    token: str,
    exchange: str,
    timeframe: str,
    window_start: date,
    window_end: date,
) -> int:
    count, _ = _persist_backfill_batch(
        db, [(frame, window_start, window_end)], symbol, token, exchange, timeframe,
    )
    return count



def _record_backfill_attempt(
    db: DuckDBManager,
    symbol: str,
    timeframe: str,
    window_start: date,
    window_end: date,
    status: str,
    error_message: str | None,
    dataset_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    db.record_provider_attempt({
        "attempt_id": str(uuid.uuid4()),
        "provider_name": "angel_one",
        "request_json": json.dumps({
            "symbol": symbol, "timeframe": timeframe,
            "start": window_start.isoformat(), "end": window_end.isoformat(),
        }, sort_keys=True),
        "status": status,
        "dataset_id": dataset_id,
        "error_message": error_message,
        "started_at": now,
        "finished_at": now,
    })


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requested_start = date.fromisoformat(args.start_date)
    requested_end = get_ist_now().date()
    if requested_start >= requested_end:
        raise ValueError("--start-date must be before today.")
    timeframes = tuple(value.strip() for value in args.timeframes.split(",") if value.strip())
    if not timeframes or set(timeframes).difference(INTERVALS):
        raise ValueError("--timeframes must contain only 1m and/or 1d.")
    requested_symbols = {value.strip().upper() for value in args.symbols.split(",") if value.strip()}

    config = apply_env_overrides(load_yaml(str(PROJECT_ROOT / "config" / "config.yaml")))
    validate_config(config)
    config["database"]["path"] = str((PROJECT_ROOT / config["database"]["path"]).resolve())
    config["logging"]["path"] = str((PROJECT_ROOT / config["logging"]["path"]).resolve())
    logger = LoggerSetup.setup(config, component="ingestion", command="historical-backfill")
    started = time.perf_counter()
    db = DuckDBManager(config["database"]["path"])
    try:
        auth = SmartAPIAuth(config)
        if not auth.login():
            raise RuntimeError("Angel One authentication failed.")
        instrument = InstrumentMaster(config)
        instrument.download_instrument_master()
        db.upsert_instrument_master(instrument._df)
        symbols = load_universe_snapshot_symbols(db, args.universe_snapshot)
        symbols.append(load_index_benchmark_symbol(db, args.benchmark))
        if requested_symbols:
            symbols = [item for item in symbols if str(item["symbol"]).upper() in requested_symbols]
            missing = requested_symbols.difference(str(item["symbol"]).upper() for item in symbols)
            if missing:
                raise ValueError(f"Requested symbols are not in the snapshot/benchmark: {sorted(missing)}")
        shared_limiter = RateLimiter(
            rps=int(config["rate_limits"]["requests_per_second"]),
            rpm=int(config["rate_limits"]["requests_per_minute"]),
        )
        historical = HistoricalDataClient(auth, config, rate_limiter=shared_limiter)

        jobs = [(symbol, timeframe) for timeframe in timeframes for symbol in symbols]
        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [
                executor.submit(
                    _backfill_timeframe,
                    db,
                    historical,
                    symbol,
                    timeframe=timeframe,
                    requested_start=requested_start,
                    requested_end=requested_end,
                    max_windows=args.max_windows,
                    full_backward=args.full_backward,
                )
                for symbol, timeframe in jobs
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                logger.info(
                    "backfill_progress symbol={} timeframe={} windows={} inserted={} earliest={} latest={} boundary={} status={}",
                    result["symbol"], result["timeframe"], result["windows"], result["inserted"],
                    result["earliest"], result["latest"], result["source_boundary"], result["status"],
                )

        failures = [
            result for result in results if result["status"] in ("FAILED", "QUARANTINED", "PARTIAL")
        ]
        logger.info(
            "backfill_finished jobs={} failures={} duration_seconds={:.1f}",
            len(results), len(failures), time.perf_counter() - started,
        )
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
