"""Main orchestration entrypoint for Phase 1 historical data ingestion."""

from __future__ import annotations

import time
import os
import sys
import concurrent.futures
import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time as time_value, timedelta
from pathlib import Path
from typing import Any

import threading
import yaml
from loguru import logger
from tqdm import tqdm

from smartapi import (
    ConnectionState,
    HistoricalDataClient,
    InstrumentMaster,
    LiveTickerMode,
    SmartAPIAuth,
    SmartAPIWebSocketClient,
)
from storage import DuckDBManager
from utils import LoggerSetup, ReportGenerator, get_ist_now
from data_platform.contracts import PriceAdjustment
from data_platform.live_admission import LiveAdmissionPolicy, LiveMarketDataAdmissionValidator
from data_platform.service import ingest_raw_provider_dataset
from trading_stack.calendars import MarketCalendar, SessionOverride, build_nse_calendar
from trading_stack.domain import Bar, infer_market_spec
from trading_stack.live_aggregator import RealtimeBarAggregator
from trading_stack.stream_persistence import DuckDBStreamWriter
from validators.duckdb_quality import DuckDBValidator

PROJECT_ROOT = Path(__file__).resolve().parent


SMARTAPI_ENV_VARS = {
    "api_key": "SMARTAPI_API_KEY",
    "client_code": "SMARTAPI_CLIENT_CODE",
    "pin": "SMARTAPI_PIN",
    "totp_secret": "SMARTAPI_TOTP_SECRET",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the ingestion CLI without changing its no-argument behavior."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe-snapshot",
        default=None,
        help="Use paper-eligible members from an immutable universe snapshot instead of symbols.yaml.",
    )
    parser.add_argument(
        "--benchmark",
        default="NIFTY200",
        help="Canonical benchmark to ingest with a universe snapshot (default: NIFTY200).",
    )
    parser.add_argument(
        "--without-benchmark",
        action="store_true",
        help="Do not ingest a benchmark with the universe snapshot.",
    )
    parser.add_argument(
        "--live-ticker",
        action="store_true",
        help="Stream live market data via SmartAPI WebSocket 2.0.",
    )
    parser.add_argument(
        "--stream-mode",
        choices=["LTP", "QUOTE", "SNAP_QUOTE"],
        default="SNAP_QUOTE",
        help="WebSocket streaming mode (default: SNAP_QUOTE).",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated list of symbols to stream (e.g. RELIANCE,INFY).",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=None,
        help="Optional duration in seconds to run the live stream before stopping.",
    )
    return parser


def load_yaml(path: str) -> dict[str, Any]:
    """Load and parse a YAML configuration file with environment variable expansion."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Configuration file missing: {file_path}")

    try:
        raw_content = file_path.read_text(encoding="utf-8")
        expanded_content = os.path.expandvars(raw_content)
        payload = yaml.safe_load(expanded_content)
    except Exception as exc:
        logger.exception("Failed to read YAML file {}: {}", path, exc)
        raise RuntimeError(f"Unable to load YAML file: {path}") from exc

    if not isinstance(payload, dict):
        logger.error("YAML file {} did not contain a top-level mapping.", path)
        raise RuntimeError(f"Invalid YAML structure in {path}")

    return payload


def apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Overlay SmartAPI settings from environment variables.

    Environment values win over file-based values so secrets can stay out of
    config/config.yaml while the rest of the app still uses YAML for defaults.
    """

    merged_config = dict(config)
    smartapi_config = dict(merged_config.get("smartapi", {}))

    for config_key, env_name in SMARTAPI_ENV_VARS.items():
        env_value = os.getenv(env_name)
        if env_value:
            smartapi_config[config_key] = env_value

    merged_config["smartapi"] = smartapi_config
    return merged_config


def validate_config(config: dict[str, Any]) -> None:
    """Validate that the main config contains all required keys.

    Args:
        config: Parsed config dictionary.

    Raises:
        RuntimeError: If required keys are missing.
    """

    required_sections = {
        "smartapi": ["api_key", "client_code", "pin", "totp_secret", "base_url", "instrument_master_url"],
        "database": ["path"],
        "logging": ["path", "level", "rotation", "retention"],
        "rate_limits": [
            "requests_per_second",
            "requests_per_minute",
            "chunk_days_1min",
            "chunk_days_1day",
            "retry_max_attempts",
            "retry_wait_seconds",
            "retry_max_wait_seconds",
        ],
        "data": ["start_date", "timeframes", "instrument_master_refresh_hours"],
        "timezone": ["market_tz", "market_open", "market_close"],
    }

    missing_keys: list[str] = []
    for section, keys in required_sections.items():
        if section not in config or not isinstance(config[section], dict):
            missing_keys.append(section)
            continue
        for key in keys:
            if key not in config[section]:
                missing_keys.append(f"{section}.{key}")

    timeframes = config.get("data", {}).get("timeframes", [])
    if not isinstance(timeframes, list) or not timeframes:
        missing_keys.append("data.timeframes")
    else:
        for index, timeframe in enumerate(timeframes):
            if not isinstance(timeframe, dict):
                missing_keys.append(f"data.timeframes[{index}]")
                continue
            if "interval" not in timeframe:
                missing_keys.append(f"data.timeframes[{index}].interval")
            if "label" not in timeframe:
                missing_keys.append(f"data.timeframes[{index}].label")

    if missing_keys:
        logger.error("Configuration validation failed. Missing keys: {}", ", ".join(missing_keys))
        raise RuntimeError("Configuration validation failed.")

    smartapi_config = config["smartapi"]
    for key in ("api_key", "client_code", "pin", "totp_secret", "base_url", "instrument_master_url"):
        if not isinstance(smartapi_config[key], str) or not smartapi_config[key].strip():
            raise RuntimeError(f"Configuration value smartapi.{key} must be a non-empty string.")
        if smartapi_config[key].strip().startswith(("${", "%")):
            raise RuntimeError(f"Configuration value smartapi.{key} contains an unresolved environment placeholder.")
    for key in ("base_url", "instrument_master_url"):
        if not smartapi_config[key].startswith(("http://", "https://")):
            raise RuntimeError(f"Configuration value smartapi.{key} must be an HTTP(S) URL.")

    database_path = config["database"]["path"]
    if not isinstance(database_path, str) or not database_path.strip():
        raise RuntimeError("Configuration value database.path must be a non-empty string.")

    rate_limits = config["rate_limits"]
    positive_integer_keys = (
        "requests_per_second",
        "requests_per_minute",
        "chunk_days_1min",
        "chunk_days_1day",
        "retry_max_attempts",
    )
    for key in positive_integer_keys:
        value = rate_limits[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RuntimeError(f"Configuration value rate_limits.{key} must be a positive integer.")
    if rate_limits["requests_per_second"] > rate_limits["requests_per_minute"]:
        raise RuntimeError("rate_limits.requests_per_second cannot exceed requests_per_minute.")
    for key in ("retry_wait_seconds", "retry_max_wait_seconds"):
        value = rate_limits[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise RuntimeError(f"Configuration value rate_limits.{key} must be positive.")
    if rate_limits["retry_wait_seconds"] > rate_limits["retry_max_wait_seconds"]:
        raise RuntimeError("retry_wait_seconds cannot exceed retry_max_wait_seconds.")

    data_config = config["data"]
    try:
        date.fromisoformat(str(data_config["start_date"]))
    except ValueError as exc:
        raise RuntimeError("Configuration value data.start_date must be YYYY-MM-DD.") from exc
    refresh_hours = data_config["instrument_master_refresh_hours"]
    if isinstance(refresh_hours, bool) or not isinstance(refresh_hours, (int, float)) or refresh_hours <= 0:
        raise RuntimeError("instrument_master_refresh_hours must be positive.")
    holidays = data_config.get("market_holidays", [])
    if not isinstance(holidays, list):
        raise RuntimeError("data.market_holidays must be a list of YYYY-MM-DD dates.")
    for holiday in holidays:
        try:
            date.fromisoformat(str(holiday))
        except ValueError as exc:
            raise RuntimeError("data.market_holidays must contain YYYY-MM-DD dates.") from exc

    labels: set[str] = set()
    supported_intervals = {"ONE_MINUTE": "1m", "ONE_DAY": "1d"}
    for index, timeframe in enumerate(data_config["timeframes"]):
        if not isinstance(timeframe, dict):
            raise RuntimeError(f"data.timeframes[{index}] must be a mapping.")
        interval = str(timeframe["interval"])
        label = str(timeframe["label"])
        if interval not in supported_intervals or supported_intervals[interval] != label:
            raise RuntimeError(f"Unsupported timeframe at data.timeframes[{index}].")
        if label in labels:
            raise RuntimeError(f"Duplicate timeframe label: {label}.")
        labels.add(label)

    try:
        market_open = datetime.strptime(str(config["timezone"]["market_open"]), "%H:%M").time()
        market_close = datetime.strptime(str(config["timezone"]["market_close"]), "%H:%M").time()
    except ValueError as exc:
        raise RuntimeError("Market hours must use HH:MM format.") from exc
    if market_open >= market_close:
        raise RuntimeError("timezone.market_open must be earlier than market_close.")
    if config["timezone"]["market_tz"] != "Asia/Kolkata":
        raise RuntimeError("This project currently supports only Asia/Kolkata market timezone.")

    if config.get("research", {}).get("live_trading") is not False:
        raise RuntimeError("research.live_trading must remain false; live order routing is unavailable.")


def validate_symbols(symbols_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the symbols config and return the symbol list.

    Args:
        symbols_config: Parsed symbols YAML dictionary.

    Returns:
        list[dict[str, Any]]: Validated symbol records.

    Raises:
        RuntimeError: If the symbols config is invalid.
    """

    symbols = symbols_config.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        logger.error("symbols.yaml must define a non-empty 'symbols' list.")
        raise RuntimeError("Invalid symbols configuration.")

    required_keys = {"symbol", "token", "exchange", "instrument_type"}
    for index, symbol_config in enumerate(symbols):
        if not isinstance(symbol_config, dict):
            logger.error("Symbol entry at index {} is not a mapping.", index)
            raise RuntimeError("Invalid symbols configuration.")
        missing = required_keys.difference(symbol_config.keys())
        if missing:
            logger.error("Symbol entry {} is missing keys: {}", index, ", ".join(sorted(missing)))
            raise RuntimeError("Invalid symbols configuration.")
        for key in required_keys:
            if not isinstance(symbol_config[key], (str, int)) or not str(symbol_config[key]).strip():
                raise RuntimeError(f"Symbol entry {index} has an invalid {key}.")
        symbol_timeframes = symbol_config.get("timeframes")
        if symbol_timeframes is not None:
            if not isinstance(symbol_timeframes, list) or not symbol_timeframes:
                raise RuntimeError(f"Symbol entry {index} timeframes must be a non-empty list.")
            unsupported = {str(value) for value in symbol_timeframes}.difference({"1m", "1d"})
            if unsupported:
                raise RuntimeError(f"Symbol entry {index} has unsupported timeframes: {sorted(unsupported)}")
        if "data_enabled" in symbol_config and not isinstance(symbol_config["data_enabled"], bool):
            raise RuntimeError(f"Symbol entry {index} data_enabled must be a boolean.")

    identities = [(str(item["symbol"]), str(item["exchange"])) for item in symbols]
    if len(identities) != len(set(identities)):
        raise RuntimeError("symbols.yaml contains duplicate symbol/exchange entries.")

    return symbols


def configured_timeframes_for_symbol(
    symbol_config: dict[str, Any],
    configured_timeframes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply an optional per-symbol timeframe allowlist."""

    allowed = symbol_config.get("timeframes")
    if allowed is None:
        return configured_timeframes
    allowed_labels = {str(value) for value in allowed}
    return [item for item in configured_timeframes if str(item["label"]) in allowed_labels]


def load_universe_snapshot_symbols(db: DuckDBManager, snapshot_id: str) -> list[dict[str, Any]]:
    """Return ingestible Angel One symbols from an immutable universe snapshot."""

    snapshot_exists = db.conn.execute(
        "SELECT 1 FROM universe_snapshots WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchone()
    if snapshot_exists is None:
        raise RuntimeError(f"Universe snapshot not found: {snapshot_id}")

    rows = db.conn.execute(
        """
        SELECT provider_symbol, provider_token, exchange
        FROM universe_snapshot_members
        WHERE snapshot_id = ?
          AND active_to IS NULL
          AND liquidity_eligible
          AND data_eligible
          AND paper_eligible
          AND provider_symbol IS NOT NULL
          AND provider_token IS NOT NULL
        ORDER BY symbol
        """,
        [snapshot_id],
    ).fetchall()
    symbols = [
        {
            "symbol": str(provider_symbol),
            "token": str(provider_token),
            "exchange": str(exchange),
            "instrument_type": "EQUITY",
            "timeframes": ["1d"],
        }
        for provider_symbol, provider_token, exchange in rows
    ]
    if not symbols:
        raise RuntimeError(f"Universe snapshot has no ingestible paper-eligible members: {snapshot_id}")
    return validate_symbols({"symbols": symbols})


def load_index_benchmark_symbol(db: DuckDBManager, canonical_symbol: str) -> dict[str, Any]:
    """Resolve an exact NSE index token from the downloaded instrument master."""

    normalized = "".join(character for character in canonical_symbol.upper() if character.isalnum())
    row = db.conn.execute(
        """
        SELECT symbol, token, exch_seg
        FROM instrument_master
        WHERE exch_seg = 'NSE'
          AND instrumenttype = 'AMXIDX'
          AND regexp_replace(upper(name), '[^A-Z0-9]', '', 'g') = ?
        ORDER BY symbol
        LIMIT 1
        """,
        [normalized],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Exact NSE index benchmark is absent from instrument master: {canonical_symbol}")
    return {
        "symbol": canonical_symbol.upper(),
        "token": str(row[1]),
        "exchange": str(row[2]),
        "instrument_type": "INDEX",
        "timeframes": ["1d"],
    }


def latest_completed_daily_session(
    calendar: MarketCalendar,
    now: datetime,
    market_close: time_value,
) -> date:
    """Return the latest exchange session whose normal close has passed."""

    candidate = now.date()
    if not calendar.is_trading_day(candidate) or now.timetz().replace(tzinfo=None) < market_close:
        candidate -= timedelta(days=1)
    while not calendar.is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def configured_nse_calendar(config: dict[str, Any]) -> MarketCalendar:
    """Build the versioned NSE calendar declared by operator configuration."""

    calendar_config = config.get("market_calendar", {})
    overrides = tuple(
        SessionOverride(
            session_date=date.fromisoformat(str(item["date"])),
            override_type=str(item["type"]).upper(),
            reason=str(item["reason"]),
            start_time=datetime.strptime(str(item["start"]), "%H:%M").time() if item.get("start") else None,
            end_time=datetime.strptime(str(item["end"]), "%H:%M").time() if item.get("end") else None,
        )
        for item in calendar_config.get("overrides", [])
    )
    return build_nse_calendar(
        overrides=overrides,
        version=str(calendar_config.get("version", "config-v1")),
        verified_through=(
            date.fromisoformat(str(calendar_config["verified_through"]))
            if calendar_config.get("verified_through") else None
        ),
    )


def update_result_quality(
    results: list[dict[str, Any]],
    symbol: str,
    timeframe: str,
    quality_summary: str,
) -> None:
    """Attach a quality summary line to a matching result record."""

    for result in results:
        if result["symbol"] == symbol and result["timeframe"] == timeframe:
            result["quality_summary"] = quality_summary
            return


def build_market_universe_rows(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize symbol configuration into market-universe rows."""

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        market_spec = infer_market_spec(
            str(symbol["symbol"]),
            str(symbol["exchange"]),
            str(symbol["instrument_type"]),
            tradable=True,
            lot_size=int(symbol.get("lot_size", 1)),
            tick_size=float(symbol.get("tick_size", 0.01)),
        )
        rows.append(
            {
                "symbol": market_spec.symbol,
                "exchange": market_spec.exchange,
                "asset_class": market_spec.asset_class.value,
                "currency": market_spec.currency,
                "timezone": market_spec.timezone,
                "session_open": market_spec.session_open,
                "session_close": market_spec.session_close,
                "tradable": market_spec.tradable,
                "lot_size": market_spec.lot_size,
                "tick_size": market_spec.tick_size,
            },
        )
    return rows


def run_live_ticker(bootstrap_config: dict[str, Any], args: argparse.Namespace) -> int:
    """Stream real-time ticks via SmartAPI WebSocket 2.0 with decoupled snapshot rendering."""
    logger.info("🚀 Starting SmartAPI WebSocket Live Ticker...")
    auth = SmartAPIAuth(bootstrap_config)
    auth.login()

    instrument_master = InstrumentMaster(bootstrap_config)
    instrument_master.download_instrument_master()

    stream_mode = LiveTickerMode(args.stream_mode)
    calendar = configured_nse_calendar(bootstrap_config)
    admission_policy = LiveAdmissionPolicy(
        max_future_skew_seconds=1.0,
        max_stale_latency_seconds=2.0,
        max_price_velocity_pct=0.10,
        enforce_monotonic_cumulative_volume=True,
        check_session_hours=True,
        fail_closed=True,
    )
    admission_validator = LiveMarketDataAdmissionValidator(
        policy=admission_policy,
        market_calendar=calendar,
    )

    db_path = str(PROJECT_ROOT / bootstrap_config["database"]["path"])
    client = SmartAPIWebSocketClient(
        auth=auth,
        instrument_master=instrument_master,
        admission_validator=admission_validator,
    )
    client.configure_quarantine_store(db_path)

    db_writer = DuckDBStreamWriter(db_path=db_path, batch_size=200, flush_interval_seconds=1.0)
    db_writer.start()

    aggregator = RealtimeBarAggregator(timeframe="1m", market_calendar=calendar)

    latest_ticks: dict[str, Any] = {}
    ticks_lock = threading.Lock()

    def on_tick(event: Any) -> None:
        aggregator.process_tick(event)
        db_writer.enqueue_tick(event)
        sym = event.symbol or event.token
        with ticks_lock:
            latest_ticks[sym] = event

    def on_bar(bar: Bar) -> None:
        db_writer.enqueue_bar(bar, timeframe="1m")
        logger.info(
            "🕯️ [1m BAR CLOSED] {} | O: {:.2f} H: {:.2f} L: {:.2f} C: {:.2f} | Vol: {:,.0f} @ {}",
            bar.symbol,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.timestamp.strftime("%H:%M:%S"),
        )

    client.subscribe_tick(on_tick)
    aggregator.subscribe_bar(on_bar)

    # Determine symbols to stream (fail closed on missing snapshot)
    symbols_to_stream: list[str] = []
    if args.symbols:
        symbols_to_stream = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.universe_snapshot:
        db = DuckDBManager(db_path)
        symbols_to_stream = load_universe_snapshot_symbols(db, args.universe_snapshot)
        if not symbols_to_stream:
            raise ValueError(f"Universe snapshot '{args.universe_snapshot}' could not be resolved from database.")
    if not symbols_to_stream:
        symbols_config = load_yaml(str(PROJECT_ROOT / "config" / "symbols.yaml"))
        symbols_to_stream = [str(s["symbol"]) for s in symbols_config.get("symbols", [])]

    logger.info("Subscribing to {} symbols in {} mode: {}", len(symbols_to_stream), stream_mode.value, symbols_to_stream[:10])
    client.subscribe_symbols(symbols_to_stream, mode=stream_mode, exchange_type=1)

    client.start()

    try:
        start_time = time.time()
        last_render_time = time.time()
        while client.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING, ConnectionState.RECONNECTING):
            if args.duration_seconds and (time.time() - start_time) >= args.duration_seconds:
                logger.info("Duration reached ({}s). Stopping stream.", args.duration_seconds)
                break

            # Periodically close elapsed windows on illiquid streams
            aggregator.close_elapsed_windows()

            # Decoupled dashboard render at ~2 Hz
            now = time.time()
            if now - last_render_time >= 0.5:
                with ticks_lock:
                    snapshot_copy = dict(latest_ticks)
                if snapshot_copy:
                    metrics_snap = client.metrics.snapshot()
                    summary_parts = [
                        f"{sym}: ₹{getattr(ev, 'ltp', 0.0):.2f}"
                        for sym, ev in list(snapshot_copy.items())[:5]
                    ]
                    logger.debug(
                        "⚡ Live [{}] Dispatched: {} | Drops: {} | Feed Latency p50: {:.1f}ms",
                        " | ".join(summary_parts),
                        metrics_snap["ticks_dispatched_total"],
                        metrics_snap["dispatch_queue_drops"],
                        metrics_snap["feed_latency_ms"].get("p50", 0.0),
                    )
                last_render_time = now

            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Stream interrupted by user.")
    finally:
        client.stop()
        aggregator.close_elapsed_windows()
        db_writer.stop()

    return 0



def main(argv: list[str] | None = None) -> int:
    """Run historical ingestion for configured symbols or a universe snapshot."""

    db: DuckDBManager | None = None

    try:
        args = build_parser().parse_args(argv)
        bootstrap_config = load_yaml(str(PROJECT_ROOT / "config" / "config.yaml"))
        bootstrap_config = apply_env_overrides(bootstrap_config)
        validate_config(bootstrap_config)
        bootstrap_config["database"]["path"] = str(
            (PROJECT_ROOT / bootstrap_config["database"]["path"]).resolve()
            if not Path(bootstrap_config["database"]["path"]).is_absolute()
            else Path(bootstrap_config["database"]["path"]),
        )
        bootstrap_config["logging"]["path"] = str(
            (PROJECT_ROOT / bootstrap_config["logging"]["path"]).resolve()
            if not Path(bootstrap_config["logging"]["path"]).is_absolute()
            else Path(bootstrap_config["logging"]["path"]),
        )
        project_logger = LoggerSetup.setup(bootstrap_config, component="ingestion", command="historical-ingestion")

        if args.live_ticker:
            return run_live_ticker(bootstrap_config, args)

        project_logger.info("🚀 AlgoTrading Phase 1 starting...")
        run_started_at = get_ist_now()
        run_started_perf = time.perf_counter()

        db = DuckDBManager(bootstrap_config["database"]["path"])
        project_logger.info("✅ Database ready at {}", bootstrap_config["database"]["path"])
        calendar_config = bootstrap_config.get("market_calendar", {})
        calendar_overrides = tuple(
            SessionOverride(
                session_date=date.fromisoformat(str(item["date"])),
                override_type=str(item["type"]).upper(),
                reason=str(item["reason"]),
                start_time=datetime.strptime(str(item["start"]), "%H:%M").time() if item.get("start") else None,
                end_time=datetime.strptime(str(item["end"]), "%H:%M").time() if item.get("end") else None,
            )
            for item in calendar_config.get("overrides", [])
        )
        nse_calendar = build_nse_calendar(
            overrides=calendar_overrides,
            verified_through=(
                date.fromisoformat(str(calendar_config["verified_through"]))
                if calendar_config.get("verified_through") else None
            ),
        )
        if calendar_config:
            calendar_payload = json.dumps(calendar_config, sort_keys=True, default=str)
            db._replace_rows("market_calendar_versions", [{
                "calendar_id": str(calendar_config.get("calendar_id", "NSE_CASH")),
                "market": "NSE", "timezone": bootstrap_config["timezone"]["market_tz"],
                "session_open": bootstrap_config["timezone"]["market_open"],
                "session_close": bootstrap_config["timezone"]["market_close"],
                "source": str(calendar_config.get("source", "operator-configured")),
                "version": str(calendar_config.get("version", "config-v1")),
                "verified_through": date.fromisoformat(str(calendar_config["verified_through"])),
                "content_hash": hashlib.sha256(calendar_payload.encode()).hexdigest(),
                "created_at": get_ist_now(),
            }])
        if args.universe_snapshot:
            symbols = load_universe_snapshot_symbols(db, args.universe_snapshot)
            project_logger.info(
                "✅ Loaded {} ingestible symbols from universe snapshot {}.",
                len(symbols),
                args.universe_snapshot,
            )
        else:
            symbols = validate_symbols(load_yaml(str(PROJECT_ROOT / "config" / "symbols.yaml")))
            project_logger.info("✅ Config loaded. {} symbols found.", len(symbols))

        auth = SmartAPIAuth(bootstrap_config)
        login_success = auth.login()
        if not login_success:
            project_logger.critical("❌ Login failed. Exiting.")
            return 1
        project_logger.info("✅ Authentication successful.")

        instrument = InstrumentMaster(bootstrap_config)
        instrument.download_instrument_master()
        instrument_rows = db.upsert_instrument_master(instrument._df)
        project_logger.info("✅ Instrument master updated. {} rows processed.", instrument_rows)

        if args.universe_snapshot and not args.without_benchmark:
            benchmark = load_index_benchmark_symbol(db, args.benchmark)
            symbols.append(benchmark)
            db._replace_rows("benchmark_aliases", [{
                "canonical_symbol": args.benchmark.upper(),
                "provider_symbol": benchmark["symbol"],
                "relationship": "EXACT",
                "source": "Angel One instrument master AMXIDX",
                "approved_for_research": True,
                "notes": f"Automatically registered with universe snapshot {args.universe_snapshot}.",
            }])
            project_logger.info("✅ Exact benchmark {} included in daily ingestion.", args.benchmark.upper())

        db.upsert_market_universe(build_market_universe_rows(symbols))
        project_logger.info("✅ Market universe updated. {} symbols normalized.", len(symbols))
        ingestion_symbols = [item for item in symbols if bool(item.get("data_enabled", True))]
        project_logger.info("✅ Historical ingestion enabled for {} symbols.", len(ingestion_symbols))

        historical = HistoricalDataClient(auth, bootstrap_config)
        results: list[dict[str, Any]] = []

        def process_symbol(sym_config: dict[str, Any]) -> list[dict[str, Any]]:
            symbol_results = []
            try:
                symbol = str(sym_config["symbol"])
                token = str(sym_config["token"])
                exchange = str(sym_config["exchange"])
            except KeyError as exc:
                project_logger.exception("❌ Missing required key in symbol config: {}", exc)
                return [{"symbol": "UNKNOWN", "timeframe": "UNKNOWN", "status": "FAILED", "quality_summary": None}]

            for timeframe_config in configured_timeframes_for_symbol(
                sym_config,
                bootstrap_config["data"]["timeframes"],
            ):
                interval = str(timeframe_config["interval"])
                label = str(timeframe_config["label"])
                now_ist = get_ist_now()
                configured_market_close = datetime.strptime(
                    bootstrap_config["timezone"]["market_close"], "%H:%M",
                ).time()
                to_date = (
                    latest_completed_daily_session(nse_calendar, now_ist, configured_market_close)
                    if label == "1d" else now_ist.date()
                )
                from_date = to_date

                try:
                    latest_ts = db.get_latest_timestamp(symbol, label)
                    if latest_ts is None:
                        from_date = date.fromisoformat(str(bootstrap_config["data"]["start_date"]))
                    else:
                        if label == "1d" and latest_ts.date() >= to_date:
                            project_logger.info("⏭️ {} {}: already up to date.", symbol, label)
                            symbol_results.append(
                                {
                                    "symbol": symbol,
                                    "timeframe": label,
                                    "candles_fetched": 0,
                                    "candles_inserted": 0,
                                    "status": "UP_TO_DATE",
                                    "quality_summary": None,
                                },
                            )
                            continue
                        from_date = latest_ts.date()

                    if from_date > to_date:
                        project_logger.info("⏭️ {} {}: already up to date.", symbol, label)
                        symbol_results.append(
                            {
                                "symbol": symbol,
                                "timeframe": label,
                                "candles_fetched": 0,
                                "candles_inserted": 0,
                                "status": "UP_TO_DATE",
                                "quality_summary": None,
                            },
                        )
                        continue

                    from_datetime = datetime.combine(
                        from_date,
                        datetime.strptime(bootstrap_config["timezone"]["market_open"], "%H:%M").time(),
                    )
                    to_datetime = datetime.combine(
                        to_date,
                        datetime.strptime(bootstrap_config["timezone"]["market_close"], "%H:%M").time(),
                    )

                    task_started = time.perf_counter()
                    candle_df = historical.fetch_candles(symbol, token, exchange, interval, from_date, to_date)

                    fetch_failed_chunks = candle_df.attrs.get("failed_chunks", [])
                    fetch_status = "PARTIAL" if fetch_failed_chunks else "SUCCESS"
                    if candle_df.empty:
                        duration = time.perf_counter() - task_started
                        project_logger.warning("⚠️ {} {}: no data returned.", symbol, label)
                        db.log_download(
                            symbol=symbol,
                            exchange=exchange,
                            timeframe=label,
                            from_date=from_datetime,
                            to_date=to_datetime,
                            candles_fetched=0,
                            candles_inserted=0,
                            status="FAILED" if fetch_failed_chunks else "PARTIAL",
                            error_message="; ".join(fetch_failed_chunks) if fetch_failed_chunks else "Empty response",
                            duration_sec=duration,
                        )
                        symbol_results.append(
                            {
                                "symbol": symbol,
                                "timeframe": label,
                                "candles_fetched": 0,
                                "candles_inserted": 0,
                                "status": "FAILED" if fetch_failed_chunks else "PARTIAL",
                                "quality_summary": None,
                            },
                        )
                        continue

                    res = ingest_raw_provider_dataset(
                        bars=candle_df,
                        symbol=symbol,
                        exchange=exchange,
                        timeframe=label,
                        provider_name="angel_one",
                        provider_symbol=symbol,
                        provider_token=token,
                        declared_adjustment=PriceAdjustment.UNADJUSTED,
                        timezone_name="Asia/Kolkata",
                        db=db,
                        target_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
                    )
                    inserted = len(res.bars) if res.bars is not None else 0
                    duration = time.perf_counter() - task_started
                    db.log_download(
                        symbol=symbol,
                        exchange=exchange,
                        timeframe=label,
                        from_date=from_datetime,
                        to_date=to_datetime,
                        candles_fetched=len(candle_df),
                        candles_inserted=inserted,
                        status=fetch_status,
                        error_message="; ".join(fetch_failed_chunks) if fetch_failed_chunks else None,
                        duration_sec=duration,
                    )

                    project_logger.info(
                        "✅ {} {}: {:,} fetched | {:,} inserted | {:.1f}s",
                        symbol,
                        label,
                        len(candle_df),
                        inserted,
                        duration,
                    )
                    symbol_results.append(
                        {
                            "symbol": symbol,
                            "timeframe": label,
                            "candles_fetched": len(candle_df),
                            "candles_inserted": inserted,
                            "status": fetch_status,
                            "quality_summary": None,
                        },
                    )
                except Exception as exc:
                    project_logger.exception("❌ {} {} failed: {}", symbol, label, exc)
                    failure_from_datetime = datetime.combine(
                        from_date,
                        datetime.strptime(bootstrap_config["timezone"]["market_open"], "%H:%M").time(),
                    )
                    failure_to_datetime = datetime.combine(
                        to_date,
                        datetime.strptime(bootstrap_config["timezone"]["market_close"], "%H:%M").time(),
                    )
                    db.log_download(
                        symbol=symbol,
                        exchange=exchange,
                        timeframe=label,
                        from_date=failure_from_datetime,
                        to_date=failure_to_datetime,
                        candles_fetched=0,
                        candles_inserted=0,
                        status="FAILED",
                        error_message=str(exc),
                        duration_sec=0.0,
                    )
                    symbol_results.append(
                        {
                            "symbol": symbol,
                            "timeframe": label,
                            "candles_fetched": 0,
                            "candles_inserted": 0,
                            "status": "FAILED",
                            "quality_summary": None,
                        },
                    )
            return symbol_results

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(process_symbol, sym_config) for sym_config in ingestion_symbols]
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(ingestion_symbols), desc="Downloading", disable=not sys.stdout.isatty()):
                results.extend(future.result())

        daily_symbols = {
            str(item["symbol"])
            for item in ingestion_symbols
            if any(
                str(timeframe["label"]) == "1d"
                for timeframe in configured_timeframes_for_symbol(item, bootstrap_config["data"]["timeframes"])
            )
        }
        previous_missing_rows = db.conn.execute(
            """
            SELECT symbol, details
            FROM quality_report
            WHERE timeframe = '1d' AND check_type = 'missing_candles'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY symbol, timeframe, check_type ORDER BY checked_at DESC
            ) = 1
            """,
        ).fetchall()
        missing_frequency: Counter[str] = Counter()
        for previous_symbol, details in previous_missing_rows:
            if str(previous_symbol) not in daily_symbols:
                continue
            missing_frequency.update(json.loads(str(details)).get("gaps", []))
        systemic_threshold = max(2, (len(daily_symbols) * 4 + 4) // 5)
        repairable_daily_gaps = {
            date.fromisoformat(value)
            for value, count in missing_frequency.items()
            if count >= systemic_threshold
        }
        if repairable_daily_gaps:
            project_logger.info(
                "Daily gap repair selected {} systemic dates (threshold {}/{} symbols).",
                len(repairable_daily_gaps), systemic_threshold, len(daily_symbols),
            )

        quality_reports: list[dict[str, Any]] = []
        for sym_config in ingestion_symbols:
            symbol = str(sym_config["symbol"])
            for timeframe_config in configured_timeframes_for_symbol(
                sym_config,
                bootstrap_config["data"]["timeframes"],
            ):
                label = str(timeframe_config["label"])
                candle_count = db.get_candle_count(symbol, label)
                if candle_count == 0:
                    continue

                validator = DuckDBValidator(
                    label,
                    market_open=datetime.strptime(bootstrap_config["timezone"]["market_open"], "%H:%M").time(),
                    market_close=datetime.strptime(bootstrap_config["timezone"]["market_close"], "%H:%M").time(),
                    market_holidays={
                        date.fromisoformat(str(holiday))
                        for holiday in bootstrap_config["data"].get("market_holidays", [])
                    },
                    session_overrides=calendar_overrides,
                    calendar_version=str(calendar_config.get("version", "config-v1")),
                    calendar_verified_through=(
                        date.fromisoformat(str(calendar_config["verified_through"]))
                        if calendar_config.get("verified_through") else None
                    ),
                )
                report = validator.run_all_checks(db, symbol)
                if label == "1d":
                    missing_dates = [
                        date.fromisoformat(value)
                        for value in report["checks"]["missing_candles"].get("gaps", [])
                        if date.fromisoformat(value) in repairable_daily_gaps
                    ]
                    repaired = 0
                    for missing_date in missing_dates[:20]:
                        repair_frame = historical.fetch_candles(
                            symbol,
                            str(sym_config["token"]),
                            str(sym_config["exchange"]),
                            "ONE_DAY",
                            missing_date - timedelta(days=1),
                            missing_date + timedelta(days=1),
                        )
                        if repair_frame.empty:
                            continue
                        repair_res = ingest_raw_provider_dataset(
                            bars=repair_frame,
                            symbol=symbol,
                            exchange=str(sym_config["exchange"]),
                            timeframe=label,
                            provider_name="angel_one",
                            provider_symbol=symbol,
                            provider_token=str(sym_config["token"]),
                            declared_adjustment=PriceAdjustment.UNADJUSTED,
                            timezone_name="Asia/Kolkata",
                            db=db,
                            target_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
                        )
                        if repair_res.bars is not None:
                            repaired += len(repair_res.bars)
                    if repaired:
                        project_logger.info("✅ {} {}: repaired {} missing daily bars.", symbol, label, repaired)
                        report = validator.run_all_checks(db, symbol)
                quality_reports.append(report)
                total_issues = sum(int(check_result["count"]) for check_result in report["checks"].values())
                quality_summary = f"{symbol} {label}: {total_issues} issues"
                update_result_quality(results, symbol, label, quality_summary)
                if not report["passed"]:
                    project_logger.warning("⚠️ Quality issues in {} {}: {} total", symbol, label, total_issues)

        db.log_quality_report(quality_reports)

        reporter = ReportGenerator(log_path=bootstrap_config["logging"]["path"])
        reporter.generate_summary(
            results=results,
            start_time=run_started_at,
            duration_seconds=time.perf_counter() - run_started_perf,
        )
        project_logger.info("🏁 Phase 1 complete.")
        unsuccessful_results = sum(result["status"] in {"FAILED", "PARTIAL"} for result in results)
        if unsuccessful_results:
            project_logger.error("Phase 1 completed with {} failed or partial downloads.", unsuccessful_results)
            return 1
        return 0
    except Exception as exc:
        logger.exception("Fatal error in Phase 1 execution: {}", exc)
        raise
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
