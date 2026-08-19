"""Performance telemetry, sequence-gap monitoring, and latency metrics for SmartStream."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


class RollingLatencyTracker:
    """Track rolling percentiles (p50, p95, p99, max) for latency measurements."""

    def __init__(self, max_samples: int = 10_000) -> None:
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def record(self, latency_ms: float) -> None:
        """Record a latency observation in milliseconds."""
        if latency_ms >= 0:
            with self._lock:
                self._samples.append(latency_ms)

    def stats(self) -> dict[str, float]:
        """Compute latency distribution percentiles."""
        with self._lock:
            if not self._samples:
                return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "count": 0}
            sorted_vals = sorted(self._samples)
            n = len(sorted_vals)
            return {
                "p50": sorted_vals[int(n * 0.50)],
                "p95": sorted_vals[min(int(n * 0.95), n - 1)],
                "p99": sorted_vals[min(int(n * 0.99), n - 1)],
                "max": sorted_vals[-1],
                "count": n,
            }


class StreamSequenceTracker:
    """Detect packet sequence gaps, duplicates, and out-of-order deliveries per stream."""

    def __init__(self) -> None:
        self._last_sequences: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def inspect_sequence(self, exchange: str, token: str, sequence_number: int) -> tuple[bool, bool, int]:
        """Inspect incoming sequence number.

        Args:
            exchange: Exchange segment name.
            token: Instrument token.
            sequence_number: Sequence number from wire header.

        Returns:
            tuple[bool, bool, int]: (is_gap, is_duplicate, gap_size)
        """
        if sequence_number <= 0:
            return False, False, 0

        stream_key = (exchange, token)
        with self._lock:
            last_seq = self._last_sequences.get(stream_key)
            if last_seq is None:
                self._last_sequences[stream_key] = sequence_number
                return False, False, 0

            if sequence_number <= last_seq:
                return False, True, 0

            gap_size = sequence_number - last_seq - 1
            is_gap = gap_size > 0
            self._last_sequences[stream_key] = sequence_number
            return is_gap, False, gap_size


@dataclass
class StreamMetrics:
    """Global counters and latency distribution metrics for live streaming operations."""

    packets_received_total: int = 0
    packets_decoded_total: int = 0
    invalid_packets_total: int = 0
    invalid_packet_size: int = 0
    invalid_oi_change: int = 0
    ticks_dispatched_total: int = 0
    sequence_gaps_total: int = 0
    duplicate_packets_total: int = 0
    dispatch_queue_drops: int = 0
    persistence_drops_total: int = 0
    reconnect_total: int = 0
    auth_refresh_total: int = 0
    subscription_replay_total: int = 0
    bars_emitted_total: int = 0
    late_ticks_total: int = 0
    bar_corrections_total: int = 0

    dispatch_queue_depth: int = 0
    persistence_queue_depth: int = 0

    feed_latency: RollingLatencyTracker = field(default_factory=RollingLatencyTracker)
    dispatch_latency: RollingLatencyTracker = field(default_factory=RollingLatencyTracker)
    sequence_tracker: StreamSequenceTracker = field(default_factory=StreamSequenceTracker)

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable dictionary snapshot of telemetry."""
        return {
            "packets_received_total": self.packets_received_total,
            "packets_decoded_total": self.packets_decoded_total,
            "invalid_packets_total": self.invalid_packets_total,
            "invalid_packet_size": self.invalid_packet_size,
            "invalid_oi_change": self.invalid_oi_change,
            "ticks_dispatched_total": self.ticks_dispatched_total,
            "sequence_gaps_total": self.sequence_gaps_total,
            "duplicate_packets_total": self.duplicate_packets_total,
            "dispatch_queue_drops": self.dispatch_queue_drops,
            "persistence_drops_total": self.persistence_drops_total,
            "reconnect_total": self.reconnect_total,
            "auth_refresh_total": self.auth_refresh_total,
            "subscription_replay_total": self.subscription_replay_total,
            "bars_emitted_total": self.bars_emitted_total,
            "late_ticks_total": self.late_ticks_total,
            "bar_corrections_total": self.bar_corrections_total,
            "dispatch_queue_depth": self.dispatch_queue_depth,
            "persistence_queue_depth": self.persistence_queue_depth,
            "feed_latency_ms": self.feed_latency.stats(),
            "dispatch_latency_ms": self.dispatch_latency.stats(),
        }
