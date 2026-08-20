"""Angel One SmartAPI WebSocket 2.0 (SmartStream) client for real-time tick streaming."""

from __future__ import annotations

import json
import queue
import random
import ssl
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

import websocket
from loguru import logger

from data_platform.contracts import (
    LiveTickerMode,
    MarketDataEvent,
)
from data_platform.live_admission import LiveMarketDataAdmissionValidator, TickAdmissionAction
from smartapi.auth import SmartAPIAuth
from smartapi.instrument import InstrumentMaster
from smartapi.stream_decoder import SmartStreamDecoder
from smartapi.stream_metrics import StreamMetrics
from smartapi.subscription_registry import SubscriptionKey, SubscriptionRegistry


class ConnectionState(str, Enum):
    """WebSocket connection lifecycle state."""

    STOPPED = "STOPPED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    STOPPING = "STOPPING"


class SmartAPIWebSocketClient:
    """Production-grade WebSocket 2.0 streaming client with state machine, generation ID, and bounded queue isolation."""

    WS_URL = "wss://smartapisocket.angelone.in/smart-stream"

    def __init__(
        self,
        auth: SmartAPIAuth,
        instrument_master: InstrumentMaster | None = None,
        admission_validator: LiveMarketDataAdmissionValidator | None = None,
        max_dispatch_queue_size: int = 50_000,
        watchdog_timeout_seconds: float = 30.0,
        ping_interval_seconds: int = 10,
        allow_insecure_tls: bool = False,
        clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        backoff_rng: Callable[[float, float], float] = random.uniform,
        websocket_factory: Any = websocket.WebSocketApp,
        quarantine_conn: Any = None,
        quarantine_db_path: str | None = None,
        raw_packet_sink: Any | None = None,
    ) -> None:
        """Initialize the WebSocket client."""
        self.auth = auth
        self.instrument_master = instrument_master
        self.admission_validator = admission_validator or LiveMarketDataAdmissionValidator()
        self.watchdog_timeout = watchdog_timeout_seconds
        self.ping_interval = ping_interval_seconds
        self.allow_insecure_tls = allow_insecure_tls
        self.raw_packet_sink = raw_packet_sink
        self._quarantine_conn = quarantine_conn
        self._quarantine_db_path = quarantine_db_path

        self._clock = clock
        self._monotonic = monotonic_clock
        self._rng = backoff_rng
        self._ws_factory = websocket_factory

        self.registry = SubscriptionRegistry()
        self.metrics = StreamMetrics()

        self._state = ConnectionState.STOPPED
        self._state_lock = threading.Lock()
        self._generation_id = 0

        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._quarantine_thread: threading.Thread | None = None

        self._dispatch_queue: queue.Queue[MarketDataEvent] = queue.Queue(maxsize=max_dispatch_queue_size)
        self._quarantine_queue: queue.Queue[tuple[Any, Any]] = queue.Queue(maxsize=10_000)
        self._callbacks: list[Callable[[MarketDataEvent], None]] = []
        self._callback_lock = threading.Lock()

        self._last_rx_monotonic = 0.0
        self._connected_monotonic = 0.0
        self._reconnect_attempts = 0
        self._auth_refresh_lock = threading.Lock()

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        with self._state_lock:
            return self._state

    @property
    def generation_id(self) -> int:
        """Current connection generation identifier."""
        with self._state_lock:
            return self._generation_id

    def subscribe_tick(self, callback: Callable[[MarketDataEvent], None]) -> None:
        """Register a subscriber callback for decoded market data events."""
        with self._callback_lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def unsubscribe_tick(self, callback: Callable[[MarketDataEvent], None]) -> None:
        """Remove a subscriber callback."""
        with self._callback_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def configure_quarantine_store(self, db_path: str) -> None:
        """Configure path for quarantine worker's dedicated DuckDB connection."""
        self._quarantine_db_path = db_path

    def start(self) -> None:
        """Start the streaming client, dispatch worker, and connection loop."""
        with self._state_lock:
            if self._state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
                return
            self._state = ConnectionState.CONNECTING
            self._generation_id += 1
            gen = self._generation_id

        # Start background dispatch thread
        if self._dispatch_thread is None or not self._dispatch_thread.is_alive():
            self._dispatch_thread = threading.Thread(target=self._dispatch_worker, name="TickDispatcher", daemon=True)
            self._dispatch_thread.start()

        # Start quarantine drain thread
        if self._quarantine_thread is None or not self._quarantine_thread.is_alive():
            self._quarantine_thread = threading.Thread(target=self._quarantine_worker, name="QuarantineDrainer", daemon=True)
            self._quarantine_thread.start()

        # Start watchdog thread
        if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name="StreamWatchdog", daemon=True)
            self._watchdog_thread.start()

        self._connect_socket(gen)

    def set_quarantine_connection(self, conn: Any) -> None:
        """Set or update DuckDB connection for asynchronous quarantine writes."""
        self._quarantine_conn = conn


    def stop(self) -> None:
        """Gracefully and idempotently shut down the streaming client."""
        with self._state_lock:
            if self._state == ConnectionState.STOPPED:
                return
            self._state = ConnectionState.STOPPING

        logger.info("🛑 Stopping SmartAPI WebSocket client...")


        # Close WebSocket connection
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception as exc:
                logger.debug("Error closing socket: {}", exc)

        # Wait for socket thread
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2.0)

        # Lossless shutdown: drain dispatch and quarantine queues before closing
        start_drain = time.monotonic()
        while not self._dispatch_queue.empty() and (time.monotonic() - start_drain) < 3.0:
            time.sleep(0.05)
        while not self._quarantine_queue.empty() and (time.monotonic() - start_drain) < 3.0:
            time.sleep(0.05)

        with self._state_lock:
            self._state = ConnectionState.STOPPED
            self._ws = None

        if self._dispatch_thread and self._dispatch_thread.is_alive():
            self._dispatch_thread.join(timeout=1.0)
        if self._quarantine_thread and self._quarantine_thread.is_alive():
            self._quarantine_thread.join(timeout=1.0)

        logger.info("🛑 SmartAPI WebSocket client stopped.")

    def subscribe(self, keys: list[SubscriptionKey]) -> None:
        """Add subscriptions to desired state and send subscription payloads if connected."""
        new_keys = self.registry.validate_and_add(keys)
        if not new_keys:
            return

        if self.state == ConnectionState.CONNECTED and self._ws is not None:
            payloads = self.registry.build_action_payloads(new_keys, action=1)
            for p in payloads:
                self._send_json(p)
                self.metrics.subscription_replay_total += 1

    def unsubscribe(self, keys: list[SubscriptionKey]) -> None:
        """Remove subscriptions from desired state and send unsubscribe payloads if connected."""
        removed_keys = self.registry.remove(keys)
        if not removed_keys:
            return

        if self.state == ConnectionState.CONNECTED and self._ws is not None:
            payloads = self.registry.build_action_payloads(removed_keys, action=0)
            for p in payloads:
                self._send_json(p)

    def subscribe_symbols(
        self,
        symbols: list[str],
        mode: LiveTickerMode = LiveTickerMode.QUOTE,
        exchange_type: int = 1,
    ) -> list[SubscriptionKey]:
        """Convenience method to subscribe by trading symbol names."""
        keys: list[SubscriptionKey] = []
        for sym in symbols:
            token = sym
            if self.instrument_master is not None:
                resolved = self.instrument_master.resolve_token(sym, "NSE" if exchange_type == 1 else "BSE")
                if resolved:
                    token = resolved
            keys.append(SubscriptionKey(mode=mode, exchange_type=exchange_type, token=token))
        self.subscribe(keys)
        return keys

    # -------------------------------------------------------------------------
    # Internal Socket Lifecycle & Callbacks
    # -------------------------------------------------------------------------

    def _connect_socket(self, generation: int) -> None:
        """Initialize headers and connect the WebSocketApp in a worker thread."""
        headers = self._build_auth_headers()
        sslopt = self._build_ssl_options()

        self._ws = self._ws_factory(
            url=self.WS_URL,
            header=headers,
            on_open=lambda ws: self._on_open(ws, generation),
            on_data=lambda ws, data, opcode, fin: self._on_data(ws, data, opcode, fin, generation),
            on_error=lambda ws, error: self._on_error(ws, error, generation),
            on_close=lambda ws, close_status, close_msg: self._on_close(ws, close_status, close_msg, generation),
            on_ping=lambda ws, msg: self._on_ping(ws, msg, generation),
            on_pong=lambda ws, msg: self._on_pong(ws, msg, generation),
        )

        def run_socket() -> None:
            try:
                self._ws.run_forever(
                    sslopt=sslopt,
                    ping_interval=self.ping_interval,
                    ping_timeout=5,
                )
            except Exception as exc:
                logger.error("WebSocket run_forever error: {}", exc)

        self._ws_thread = threading.Thread(target=run_socket, name=f"SmartStream-Gen{generation}", daemon=True)
        self._ws_thread.start()

    def _build_auth_headers(self) -> dict[str, str]:
        """Build normalized headers with single-Bearer token."""
        auth_header = self.auth.websocket_authorization
        return {
            "Authorization": auth_header,
            "x-api-key": self.auth.api_key,
            "x-client-code": self.auth.client_code,
            "x-feed-token": self.auth.feed_token or "",
        }

    def _build_ssl_options(self) -> dict[str, Any]:
        """Build secure SSL options with certificate verification."""
        if self.allow_insecure_tls:
            logger.warning("⚠️ Insecure TLS certificate verification explicitly enabled.")
            return {"cert_reqs": ssl.CERT_NONE}
        return {"cert_reqs": ssl.CERT_REQUIRED}

    def _on_open(self, ws: websocket.WebSocketApp, generation: int) -> None:
        """Handle socket connection open."""
        with self._state_lock:
            if generation != self._generation_id or self._state == ConnectionState.STOPPING:
                return
            self._state = ConnectionState.CONNECTED
            self._last_rx_monotonic = self._monotonic()
            self._connected_monotonic = self._monotonic()
            self._reconnect_attempts = 0

        logger.info("🟢 SmartStream WebSocket connected (gen={}).", generation)

        # Replay all desired subscriptions
        desired = self.registry.get_desired_state()
        if desired:
            payloads = self.registry.build_action_payloads(desired, action=1)
            for p in payloads:
                self._send_json(p)
                self.metrics.subscription_replay_total += len(desired)
            logger.info("📡 Replayed {} subscriptions across {} batches.", len(desired), len(payloads))

    def _on_data(
        self,
        ws: websocket.WebSocketApp,
        data: bytes | str,
        opcode: int,
        fin: int,
        generation: int,
    ) -> None:
        """Handle incoming binary market data packet."""
        recv_ns = time.monotonic_ns()
        recv_utc = datetime.now(timezone.utc)
        self._last_rx_monotonic = self._monotonic()

        with self._state_lock:
            if generation != self._generation_id or self._state not in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
                return

        self.metrics.packets_received_total += 1

        if not isinstance(data, (bytes, bytearray)):
            return

        raw_bytes = bytes(data)

        if self.raw_packet_sink is not None:
            try:
                self.raw_packet_sink.enqueue_raw_packet(raw_bytes, received_at=recv_utc)
            except Exception as exc:
                logger.debug("Error forwarding raw packet to sink: {}", exc)

        # Resolve symbol helper
        def symbol_lookup(ex: str, tok: str) -> str | None:
            if self.instrument_master is not None:
                return self.instrument_master.resolve_symbol(tok, ex)
            return None

        try:
            event = SmartStreamDecoder.decode(
                data=raw_bytes,
                received_at_utc=recv_utc,
                received_monotonic_ns=recv_ns,
                symbol_resolver=symbol_lookup,
            )
            self.metrics.packets_decoded_total += 1

            # Sequence tracking
            seq_num = getattr(event, "sequence_number", 0)
            if seq_num > 0:
                is_gap, is_dup, gap_size = self.metrics.sequence_tracker.inspect_sequence(event.exchange, event.token, seq_num)
                if is_gap:
                    self.metrics.sequence_gaps_total += gap_size
                    with self._state_lock:
                        if self._state == ConnectionState.CONNECTED:
                            self._state = ConnectionState.DEGRADED
                    logger.warning(
                        "Stream sequence gap detected: exchange={} token={} gap_size={}; transitioning connection to DEGRADED state.",
                        event.exchange, event.token, gap_size,
                    )
                if is_dup:
                    self.metrics.duplicate_packets_total += 1

            # Admission validation gate (mandatory fail-closed)
            admission = self.admission_validator.validate(event, received_at_utc=recv_utc)
            if not admission.is_accepted:
                logger.debug(
                    "Admission filtered live tick: token={} action={} reasons={}",
                    getattr(event, "token", ""),
                    admission.action.value,
                    [r.value for r in admission.reasons],
                )
                if admission.action in (TickAdmissionAction.QUARANTINE, TickAdmissionAction.REJECT_MALFORMED):
                    try:
                        self._quarantine_queue.put_nowait((admission, {"raw_length": len(raw_bytes), "token": getattr(event, "token", "")}))
                    except queue.Full:
                        pass
                return

            # Enqueue to bounded dispatch queue
            try:
                self._dispatch_queue.put_nowait(event)
                self.metrics.dispatch_queue_depth = self._dispatch_queue.qsize()
            except queue.Full:
                self.metrics.dispatch_queue_drops += 1

        except Exception as exc:
            self.metrics.invalid_packets_total += 1
            logger.debug("Failed to decode binary packet ({} bytes): {}", len(raw_bytes), exc)

    def _quarantine_worker(self) -> None:
        """Asynchronously drain quarantine queue and persist records to DuckDB."""
        import duckdb
        worker_conn = None
        if self._quarantine_db_path:
            try:
                worker_conn = duckdb.connect(self._quarantine_db_path)
            except Exception as exc:
                logger.error("Failed to connect quarantine worker to DuckDB at {}: {}", self._quarantine_db_path, exc)
        elif self._quarantine_conn is not None:
            worker_conn = self._quarantine_conn

        try:
            while True:
                with self._state_lock:
                    if self._state == ConnectionState.STOPPED and self._quarantine_queue.empty():
                        break
                try:
                    item = self._quarantine_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                admission, payload = item
                if worker_conn is not None:
                    try:
                        self.admission_validator.persist_quarantine(worker_conn, admission, payload)
                    except Exception as exc:
                        logger.debug("Asynchronous quarantine persistence warning: {}", exc)
                self._quarantine_queue.task_done()
        finally:
            if worker_conn is not None and worker_conn is not self._quarantine_conn:
                try:
                    worker_conn.close()
                except Exception:
                    pass


    def _on_ping(self, ws: websocket.WebSocketApp, msg: bytes | str, generation: int) -> None:
        """Handle transport ping frame."""
        self._last_rx_monotonic = self._monotonic()

    def _on_pong(self, ws: websocket.WebSocketApp, msg: bytes | str, generation: int) -> None:
        """Handle transport pong frame."""
        self._last_rx_monotonic = self._monotonic()

    def _on_error(self, ws: websocket.WebSocketApp, error: Any, generation: int) -> None:
        """Handle WebSocket error."""
        with self._state_lock:
            if generation != self._generation_id:
                return
        logger.warning("SmartStream WebSocket error (gen={}): {}", generation, error)

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        close_status: int | None,
        close_msg: str | None,
        generation: int,
    ) -> None:
        """Handle WebSocket close and schedule reconnect if applicable."""
        with self._state_lock:
            if generation != self._generation_id or self._state in (ConnectionState.STOPPED, ConnectionState.STOPPING):
                return
            self._state = ConnectionState.RECONNECTING

        logger.info("🟡 SmartStream WebSocket closed (gen={}, status={}, msg={}).", generation, close_status, close_msg)
        self._schedule_reconnect(is_auth_error=(close_status in (401, 403, 4001)))

    def _schedule_reconnect(self, is_auth_error: bool = False) -> None:
        """Perform jittered backoff reconnect with selective auth refresh."""
        self.metrics.reconnect_total += 1
        self._reconnect_attempts += 1

        # Exponential backoff with full jitter
        base_delay = min(30.0, 1.0 * (2 ** min(self._reconnect_attempts, 5)))
        delay = self._rng(0.0, base_delay)

        logger.info("🔄 Reconnecting in {:.2f}s (attempt {})...", delay, self._reconnect_attempts)

        def reconnect_task() -> None:
            time.sleep(delay)
            with self._state_lock:
                if self._state in (ConnectionState.STOPPED, ConnectionState.STOPPING):
                    return
                self._generation_id += 1
                gen = self._generation_id

            # If disconnect was caused by auth rejection, refresh token once
            if is_auth_error:
                with self._auth_refresh_lock:
                    try:
                        self.auth.refresh_token()
                        self.metrics.auth_refresh_total += 1
                        logger.info("🔑 SmartAPI token refreshed successfully for reconnect.")
                    except Exception as exc:
                        logger.error("Token refresh failed during reconnect: {}", exc)

            self._connect_socket(gen)

        threading.Thread(target=reconnect_task, name="ReconnectThread", daemon=True).start()

    def _watchdog_loop(self) -> None:
        """Monitor connection health and trigger reconnect on prolonged inactivity."""
        while self.state != ConnectionState.STOPPED:
            time.sleep(5.0)
            if self.state == ConnectionState.CONNECTED:
                elapsed = self._monotonic() - self._last_rx_monotonic
                if elapsed > self.watchdog_timeout:
                    logger.warning("⚠️ Watchdog timeout: no traffic for {:.1f}s. Triggering reconnect.", elapsed)
                    ws = self._ws
                    if ws is not None:
                        try:
                            ws.close()
                        except Exception:
                            pass

    def _dispatch_worker(self) -> None:
        """Asynchronously dispatch decoded ticks to all subscribers with exception isolation."""
        while self.state != ConnectionState.STOPPED:
            try:
                event = self._dispatch_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            dispatch_start_ns = time.monotonic_ns()
            # Feed latency is already on event; calculate internal dispatch latency
            if event.received_monotonic_ns > 0:
                dispatch_latency_ms = (dispatch_start_ns - event.received_monotonic_ns) / 1_000_000.0
                self.metrics.dispatch_latency.record(dispatch_latency_ms)
            if event.feed_latency_ms is not None:
                self.metrics.feed_latency.record(event.feed_latency_ms)


            with self._callback_lock:
                subscribers_snapshot = list(self._callbacks)

            for cb in subscribers_snapshot:
                try:
                    cb(event)
                except Exception as exc:
                    logger.exception("Error in tick subscriber callback: {}", exc)

            self.metrics.ticks_dispatched_total += 1
            self._dispatch_queue.task_done()

    def _send_json(self, payload: dict[str, Any]) -> None:
        """Send JSON string across active WebSocket."""
        ws = self._ws
        if ws is not None and self.state == ConnectionState.CONNECTED:
            try:
                ws.send(json.dumps(payload))
            except Exception as exc:
                logger.error("Failed to send WebSocket payload: {}", exc)
