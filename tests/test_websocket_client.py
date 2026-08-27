"""Unit tests for SmartAPIWebSocketClient with dependency injection and deterministic state verification."""

from __future__ import annotations

import time
from typing import Any
import unittest
from unittest.mock import MagicMock, patch


from data_platform.live_admission import LiveAdmissionPolicy, LiveMarketDataAdmissionValidator
from smartapi.auth import SmartAPIAuth
from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient
from tests.fixtures.smartstream_packets import build_ltp_packet


class FakeWebSocketApp:
    """Mock WebSocketApp for deterministic testing without network calls."""

    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.kwargs = kwargs
        self.sent_messages: list[str] = []
        self.closed = False

    def run_forever(self, **kwargs: Any) -> None:
        pass

    def send(self, data: str) -> None:
        self.sent_messages.append(data)

    def close(self) -> None:
        self.closed = True


class TestSmartAPIWebSocketClient(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_auth = MagicMock(spec=SmartAPIAuth)
        self.mock_auth.websocket_authorization = "Bearer eyJhbGciOi..."
        self.mock_auth.api_key = "test_key"
        self.mock_auth.client_code = "TEST01"
        self.mock_auth.feed_token = "feed_123"

        self.fake_time = 1000.0
        self.fake_monotonic = 500.0

        test_policy = LiveAdmissionPolicy(
            check_session_hours=False,
            max_stale_latency_seconds=3600.0 * 24 * 365 * 100,
            max_future_skew_seconds=3600.0 * 24 * 365 * 100,
        )
        self.client = SmartAPIWebSocketClient(
            auth=self.mock_auth,
            admission_validator=LiveMarketDataAdmissionValidator(policy=test_policy),
            max_dispatch_queue_size=10,
            watchdog_timeout_seconds=30.0,
            clock=lambda: self.fake_time,
            monotonic_clock=lambda: self.fake_monotonic,
            backoff_rng=lambda a, b: 0.01,  # Fast deterministic delay for tests
            websocket_factory=FakeWebSocketApp,
        )


    def tearDown(self) -> None:
        self.client.stop()

    def test_connection_state_machine_and_generation_id(self) -> None:
        self.assertEqual(self.client.state, ConnectionState.STOPPED)
        self.assertEqual(self.client.generation_id, 0)

        # Start transitions to CONNECTING and increments generation ID
        self.client.start()
        self.assertEqual(self.client.state, ConnectionState.CONNECTING)
        self.assertEqual(self.client.generation_id, 1)

        # Trigger on_open
        self.client._on_open(self.client._ws, generation=1)
        self.assertEqual(self.client.state, ConnectionState.CONNECTED)

        # Trigger on_close
        self.client._on_close(self.client._ws, close_status=1000, close_msg="Normal closure", generation=1)
        self.assertEqual(self.client.state, ConnectionState.RECONNECTING)

        # Stop transitions to STOPPED
        self.client.stop()
        self.assertEqual(self.client.state, ConnectionState.STOPPED)

    def test_stale_generation_callbacks_discarded(self) -> None:
        """Callbacks from old socket generations must not mutate state or enqueue data."""
        self.client.start()
        self.client._on_open(self.client._ws, generation=1)
        self.assertEqual(self.client.generation_id, 1)

        received_events: list[Any] = []
        self.client.subscribe_tick(lambda ev: received_events.append(ev))

        # Stale data from generation 0
        packet = build_ltp_packet(token="2885", seq_num=100)
        self.client._on_data(self.client._ws, packet, opcode=2, fin=1, generation=0)
        time.sleep(0.05)
        self.assertEqual(len(received_events), 0)

        # Valid data from generation 1
        self.client._on_data(self.client._ws, packet, opcode=2, fin=1, generation=1)
        time.sleep(0.05)
        self.assertEqual(len(received_events), 1)

    def test_selective_auth_refresh_on_401_only(self) -> None:
        """Token refresh should only be triggered on authentication failure (e.g. status 401)."""
        self.client.start()
        self.client._on_open(self.client._ws, generation=1)

        # Normal disconnect (status=1006)
        self.client._on_close(self.client._ws, close_status=1006, close_msg="Connection reset", generation=1)
        time.sleep(0.05)
        self.mock_auth.refresh_token.assert_not_called()

        # Re-open and disconnect with 401 Unauthorized
        self.client._on_open(self.client._ws, generation=2)
        self.client._on_close(self.client._ws, close_status=401, close_msg="Token expired", generation=2)
        time.sleep(0.05)
        self.mock_auth.refresh_token.assert_called_once()

    def test_subscriber_callback_exception_isolation(self) -> None:
        """An error in one subscriber callback must not prevent other subscribers from receiving data."""
        self.client.start()
        self.client._on_open(self.client._ws, generation=1)

        healthy_received: list[Any] = []

        def buggy_subscriber(event: Any) -> None:
            raise RuntimeError("Boom! Bug in user callback")

        def healthy_subscriber(event: Any) -> None:
            healthy_received.append(event)

        self.client.subscribe_tick(buggy_subscriber)
        self.client.subscribe_tick(healthy_subscriber)

        packet = build_ltp_packet(token="3045", seq_num=200)
        self.client._on_data(self.client._ws, packet, opcode=2, fin=1, generation=1)

        time.sleep(0.1)
        self.assertEqual(len(healthy_received), 1)
        self.assertEqual(healthy_received[0].token, "3045")

    def test_bounded_dispatch_queue_overflow(self) -> None:
        """Flooding the bounded queue must increment drop metrics without raising exceptions."""
        self.client.start()
        self.client._on_open(self.client._ws, generation=1)

        # Slow subscriber blocks dispatch thread from immediately draining queue
        def slow_cb(ev: Any) -> None:
            time.sleep(0.5)

        self.client.subscribe_tick(slow_cb)

        # Fill internal dispatch queue (capacity 10) and overflow it with unique packets

        for i in range(50):
            pkt = build_ltp_packet(token="2885", seq_num=300 + i, ltp_raw=250050 + i)

            self.client._on_data(self.client._ws, pkt, opcode=2, fin=1, generation=1)

        self.assertGreater(self.client.metrics.dispatch_queue_drops, 0)



    def test_real_instrument_master_token_and_symbol_resolution(self) -> None:
        """Verify real InstrumentMaster correctly resolves tokens and symbols for WebSocket streaming."""
        from smartapi.instrument import InstrumentMaster
        inst_master = InstrumentMaster({"smartapi": {"instrument_master_url": "http://example.com"}, "data": {"instrument_master_refresh_hours": 24}})
        import pandas as pd
        inst_master._df = pd.DataFrame([
            {"token": "2885", "symbol": "RELIANCE-EQ", "exch_seg": "NSE_CM", "name": "RELIANCE", "expiry": "", "strike": 0, "lotsize": 1, "instrumenttype": "", "tick_size": 5},
            {"token": "3045", "symbol": "SBIN-EQ", "exch_seg": "NSE", "name": "SBIN", "expiry": "", "strike": 0, "lotsize": 1, "instrumenttype": "", "tick_size": 5},
        ])

        # Test token resolution
        self.assertEqual(inst_master.resolve_token("RELIANCE-EQ", "NSE"), "2885")
        self.assertEqual(inst_master.resolve_token("SBIN-EQ", "NSE_CM"), "3045")

        # Test symbol resolution
        self.assertEqual(inst_master.resolve_symbol("2885", "NSE"), "RELIANCE-EQ")
        self.assertEqual(inst_master.resolve_symbol("3045", "NSE_CM"), "SBIN-EQ")

        # Wire into client
        self.client.instrument_master = inst_master
        keys = self.client.subscribe_symbols(["RELIANCE-EQ", "SBIN-EQ"], exchange_type=1)
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0].token, "2885")
        self.assertEqual(keys[1].token, "3045")

    def test_quarantine_worker_dedicated_db_path(self) -> None:
        """Quarantine worker accepts a configured dedicated DB path and initializes gracefully."""
        self.client.configure_quarantine_store(":memory:")
        self.assertEqual(self.client._quarantine_db_path, ":memory:")

    def test_default_websocket_factory_is_resolved_at_construction_time(self) -> None:
        """A test-wide transport patch must prevent accidental real sockets."""
        with patch("smartapi.websocket_client.websocket.WebSocketApp", FakeWebSocketApp):
            client = SmartAPIWebSocketClient(auth=self.mock_auth)
        self.assertIs(client._ws_factory, FakeWebSocketApp)


if __name__ == "__main__":
    unittest.main()
