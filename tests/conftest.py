"""Suite-wide test isolation for external transports."""

from __future__ import annotations

from typing import Any

import pytest


class _NoNetworkWebSocketApp:
    """In-process WebSocket double that makes accidental network use impossible."""

    def __init__(self, url: str, **callbacks: Any) -> None:
        self.url = url
        self.callbacks = callbacks

    def close(self) -> None:
        return None

    def run_forever(self, **_: Any) -> bool:
        return False

    def send(self, _: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _block_real_websocket_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must use injected doubles rather than creating broker transports."""
    monkeypatch.setattr(
        "smartapi.websocket_client.websocket.WebSocketApp",
        _NoNetworkWebSocketApp,
    )
