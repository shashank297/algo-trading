"""Desired-state subscription manager and quota enforcement for SmartAPI WebSocket."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from data_platform.contracts import LiveTickerMode
from smartapi.stream_decoder import UnsupportedFeedModeError


@dataclass(frozen=True, slots=True)
class SubscriptionKey:
    """Unique subscription identity across feed mode, exchange, and token."""

    mode: LiveTickerMode
    exchange_type: int
    token: str


class SubscriptionRegistry:
    """Manages active and desired subscriptions with strict quota enforcement."""

    MAX_SUBSCRIPTIONS_PER_SESSION = 1000
    MAX_DEPTH_SUBSCRIPTIONS = 50
    SUBSCRIPTION_BATCH_SIZE = 500

    MODE_TO_INT: dict[LiveTickerMode, int] = {
        LiveTickerMode.LTP: 1,
        LiveTickerMode.QUOTE: 2,
        LiveTickerMode.SNAP_QUOTE: 3,
        LiveTickerMode.DEPTH: 4,
    }

    INT_TO_MODE: dict[int, LiveTickerMode] = {
        1: LiveTickerMode.LTP,
        2: LiveTickerMode.QUOTE,
        3: LiveTickerMode.SNAP_QUOTE,
        4: LiveTickerMode.DEPTH,
    }

    def __init__(self) -> None:
        self._desired: set[SubscriptionKey] = set()

    @property
    def total_count(self) -> int:
        """Current count of desired logical subscriptions."""
        return len(self._desired)

    @property
    def depth_count(self) -> int:
        """Current count of DEPTH mode subscriptions."""
        return sum(1 for k in self._desired if k.mode == LiveTickerMode.DEPTH)

    @property
    def desired_subscriptions(self) -> set[SubscriptionKey]:
        """Return a copy of the desired subscription set."""
        return self.get_desired_state()

    def get_desired_state(self) -> set[SubscriptionKey]:
        """Return a copy of the desired subscription set."""
        return set(self._desired)

    def validate_and_add(self, keys: list[SubscriptionKey]) -> list[SubscriptionKey]:
        """Validate quota constraints and add keys to desired state.

        Args:
            keys: List of SubscriptionKey instances to add.

        Returns:
            list[SubscriptionKey]: Newly added keys that were not already in desired state.

        Raises:
            ValueError: If adding keys would violate server quotas or exchange restrictions.
        """
        new_keys: list[SubscriptionKey] = []
        projected = set(self._desired)

        for key in keys:
            if key.mode == LiveTickerMode.DEPTH:
                raise UnsupportedFeedModeError(
                    "SmartAPI WebSocket 20-depth (Mode 4) was deprecated April 25, 2025. Use SNAP_QUOTE for Best-5 depth."
                )

            if key not in projected:
                projected.add(key)
                new_keys.append(key)

        # Check total quota
        if len(projected) > self.MAX_SUBSCRIPTIONS_PER_SESSION:
            raise ValueError(
                f"Subscription limit exceeded: requested total {len(projected)} exceeds maximum quota {self.MAX_SUBSCRIPTIONS_PER_SESSION}."
            )

        # Check depth quota
        depth_total = sum(1 for k in projected if k.mode == LiveTickerMode.DEPTH)
        if depth_total > self.MAX_DEPTH_SUBSCRIPTIONS:
            raise ValueError(
                f"DEPTH subscription limit exceeded: requested {depth_total} exceeds maximum quota {self.MAX_DEPTH_SUBSCRIPTIONS}."
            )

        self._desired.update(new_keys)
        return new_keys

    def remove(self, keys: list[SubscriptionKey]) -> list[SubscriptionKey]:
        """Remove keys from desired state.

        Args:
            keys: List of SubscriptionKey instances to remove.

        Returns:
            list[SubscriptionKey]: Keys that were actually present and removed.
        """
        removed: list[SubscriptionKey] = []
        for key in keys:
            if key in self._desired:
                self._desired.remove(key)
                removed.append(key)
        return removed

    def clear(self) -> None:
        """Clear all desired subscriptions."""
        self._desired.clear()

    @classmethod
    def build_action_payloads(
        cls,
        keys: list[SubscriptionKey] | set[SubscriptionKey],
        action: int = 1,
    ) -> list[dict[str, Any]]:
        """Build SmartAPI WebSocket action JSON payloads batched by 500 tokens.

        Args:
            keys: Subscriptions to format.
            action: 1 for SUBSCRIBE, 0 for UNSUBSCRIBE.

        Returns:
            list[dict[str, Any]]: List of JSON-serializable payloads.
        """
        if not keys:
            return []

        # Group by mode and exchange_type
        grouped: dict[tuple[int, int], list[str]] = {}
        for k in keys:
            mode_int = cls.MODE_TO_INT.get(k.mode, 1)
            group_key = (mode_int, k.exchange_type)
            if group_key not in grouped:
                grouped[group_key] = []
            if k.token not in grouped[group_key]:
                grouped[group_key].append(k.token)

        payloads: list[dict[str, Any]] = []

        for (mode_int, ex_type), token_list in grouped.items():
            # Batch tokens by SUBSCRIPTION_BATCH_SIZE (500)
            for i in range(0, len(token_list), cls.SUBSCRIPTION_BATCH_SIZE):
                chunk = token_list[i : i + cls.SUBSCRIPTION_BATCH_SIZE]
                payload = {
                    "correlationID": str(uuid.uuid4()),
                    "action": action,
                    "params": {
                        "mode": mode_int,
                        "tokenList": [
                            {
                                "exchangeType": ex_type,
                                "tokens": chunk,
                            }
                        ],
                    },
                }
                payloads.append(payload)

        return payloads
