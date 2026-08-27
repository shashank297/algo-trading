"""Global test isolation for external transports."""

from __future__ import annotations

from typing import Any

import pytest


class _NoNetworkWebSocketApp:
    """In-process socket stand-in for tests that do not inject a transport."""

    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.kwargs = kwargs

    def run_forever(self, **kwargs: Any) -> None:
        return None

    def send(self, _data: str) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _block_external_smartapi_websockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never open a broker WebSocket connection."""
    monkeypatch.setattr(
        "smartapi.websocket_client.websocket.WebSocketApp",
        _NoNetworkWebSocketApp,
    )
