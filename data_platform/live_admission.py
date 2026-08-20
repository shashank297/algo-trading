"""Live Market Data Admission Gateway.

Validates streaming live ticks, quotes, and market depth snapshots before
dispatching to realtime candle aggregators, portfolio risk systems, or order routers.
Enforces physical, mathematical, temporal, calendar, and depth sanity fail-closed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import json
from typing import Any
import uuid

import numpy as np
import pandas as pd

from data_platform.contracts import (
    Depth20Snapshot,
    MarketDataEvent,
    SnapQuoteTick,
)
from trading_stack.calendars import MarketCalendar, build_nse_calendar

from trading_stack.trading_calendar import IST, TradingCalendar


class TickAdmissionAction(str, Enum):
    """Structured disposition for incoming live market data events."""

    ACCEPT = "ACCEPT"
    DROP_DUPLICATE = "DROP_DUPLICATE"
    DROP_STALE = "DROP_STALE"
    DROP_OUT_OF_SESSION = "DROP_OUT_OF_SESSION"
    QUARANTINE = "QUARANTINE"
    REJECT_MALFORMED = "REJECT_MALFORMED"


class AdmissionReasonCode(str, Enum):
    """Exhaustive reason codes explaining admission decisions."""

    VALID_TICK = "VALID_TICK"
    TOKEN_NOT_IN_UNIVERSE = "TOKEN_NOT_IN_UNIVERSE"
    INVALID_EXCHANGE = "INVALID_EXCHANGE"
    MISSING_EXCHANGE = "MISSING_EXCHANGE"
    MISSING_TOKEN = "MISSING_TOKEN"
    MISSING_EXCHANGE_TIMESTAMP = "MISSING_EXCHANGE_TIMESTAMP"
    PRICE_NON_POSITIVE = "PRICE_NON_POSITIVE"
    PRICE_NON_FINITE = "PRICE_NON_FINITE"
    VOLUME_NEGATIVE = "VOLUME_NEGATIVE"
    CUMULATIVE_VOLUME_DECREASE = "CUMULATIVE_VOLUME_DECREASE"
    FUTURE_TIMESTAMP_EXCEEDED = "FUTURE_TIMESTAMP_EXCEEDED"
    STALE_TICK_LATENCY = "STALE_TICK_LATENCY"
    CLOCK_SKEW_EXCEEDED = "CLOCK_SKEW_EXCEEDED"
    DUPLICATE_TICK_FINGERPRINT = "DUPLICATE_TICK_FINGERPRINT"
    DUPLICATE_SEQUENCE_NUMBER = "DUPLICATE_SEQUENCE_NUMBER"
    OUT_OF_ORDER_TIMESTAMP = "OUT_OF_ORDER_TIMESTAMP"
    SEQUENCE_GAP_DETECTED = "SEQUENCE_GAP_DETECTED"
    CROSSED_BOOK_BID_GE_ASK = "CROSSED_BOOK_BID_GE_ASK"
    INVALID_DEPTH_PRICE = "INVALID_DEPTH_PRICE"
    INVALID_DEPTH_QUANTITY = "INVALID_DEPTH_QUANTITY"
    INVALID_DEPTH_ORDERING = "INVALID_DEPTH_ORDERING"
    EXTREME_PRICE_VELOCITY = "EXTREME_PRICE_VELOCITY"
    OUT_OF_SESSION_HOURS = "OUT_OF_SESSION_HOURS"
    WEEKEND_SESSION_REJECTED = "WEEKEND_SESSION_REJECTED"
    HOLIDAY_SESSION_REJECTED = "HOLIDAY_SESSION_REJECTED"


@dataclass(frozen=True, slots=True)
class LiveAdmissionPolicy:
    """Configurable boundaries and thresholds for live tick admission."""

    max_future_skew_seconds: float = 1.0
    max_stale_latency_seconds: float = 5.0
    max_price_velocity_pct: float = 0.10  # 10% instant single-tick jump threshold
    enforce_monotonic_cumulative_volume: bool = True
    allow_out_of_order_within_ms: float = 500.0
    dedup_cache_size: int = 10_000
    check_session_hours: bool = True
    fail_closed: bool = True
    allowed_exchanges: tuple[str, ...] = (
        "NSE", "BSE", "NFO", "BFO", "MCX",
        "NSE_CM", "NSE_FO", "BSE_CM", "BSE_FO",
        "MCX_FO", "NCX_FO", "CDE_FO", "CDS", "NCDEX"
    )
    allowed_tokens: tuple[str, ...] = ()  # Empty tuple allows all tokens


@dataclass(slots=True)
class TokenStreamState:
    """Internal state tracking for a specific instrument stream."""

    last_sequence_number: int | None = None
    highest_sequence_seen: int | None = None
    last_exchange_timestamp: datetime | None = None
    last_ltp: float | None = None
    last_cumulative_volume: int = 0
    session_date: date | None = None
    processed_count: int = 0


@dataclass(frozen=True, slots=True)
class TickAdmissionResult:
    """Immutable, fully structured evaluation result for an ingested event."""

    token: str
    symbol: str | None
    exchange: str
    action: TickAdmissionAction
    reasons: tuple[AdmissionReasonCode, ...]
    tick_timestamp: datetime | None
    received_timestamp: datetime
    price: float
    volume: float
    sequence_number: int | None = None
    latency_ms: float = 0.0
    price_velocity_pct: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_accepted(self) -> bool:
        return self.action == TickAdmissionAction.ACCEPT


class LiveMarketDataAdmissionValidator:
    """Institutional-grade gatekeeper for streaming real-time market data."""

    def __init__(
        self,
        policy: LiveAdmissionPolicy | None = None,
        calendar: TradingCalendar | None = None,
        market_calendar: MarketCalendar | None = None,
    ) -> None:
        self.policy = policy or LiveAdmissionPolicy()
        self.calendar = calendar or TradingCalendar()
        self.market_calendar = market_calendar or build_nse_calendar()

        self._token_states: dict[str, TokenStreamState] = {}
        self._dedup_cache: deque[str] = deque(maxlen=self.policy.dedup_cache_size)
        self._dedup_set: set[str] = set()

        # Telemetry counters
        self._stats: dict[str, int] = {
            "total_evaluated": 0,
            "accepted": 0,
            "dropped_duplicate": 0,
            "dropped_stale": 0,
            "dropped_out_of_session": 0,
            "quarantined": 0,
            "rejected_malformed": 0,
        }

    def reset(self) -> None:
        """Clear all stream state, deduplication cache, and metrics."""
        self._token_states.clear()
        self._dedup_cache.clear()
        self._dedup_set.clear()
        for k in self._stats:
            self._stats[k] = 0

    def validate(
        self,
        event: MarketDataEvent | dict[str, Any],
        received_at_utc: datetime | None = None,
    ) -> TickAdmissionResult:
        """Evaluate a raw or normalized market data event against admission invariants."""
        self._stats["total_evaluated"] += 1
        now_utc = received_at_utc or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        # 1. Extract unified properties
        raw_token = getattr(event, "token", None) if not isinstance(event, dict) else event.get("token")
        raw_exchange = getattr(event, "exchange", None) if not isinstance(event, dict) else event.get("exchange")
        symbol = getattr(event, "symbol", None) if not isinstance(event, dict) else event.get("symbol")
        seq_no = getattr(event, "sequence_number", None) if not isinstance(event, dict) else event.get("sequence_number")

        reasons: list[AdmissionReasonCode] = []

        # Fail-closed token and exchange validation
        if not raw_token:
            reasons.append(AdmissionReasonCode.MISSING_TOKEN)
            self._stats["rejected_malformed"] += 1
            return self._build_result("", symbol, "", TickAdmissionAction.REJECT_MALFORMED, reasons, None, now_utc, 0.0, 0.0, seq_no, 0.0)

        token = str(raw_token).strip()

        if not raw_exchange:
            reasons.append(AdmissionReasonCode.MISSING_EXCHANGE)
            self._stats["rejected_malformed"] += 1
            return self._build_result(token, symbol, "", TickAdmissionAction.REJECT_MALFORMED, reasons, None, now_utc, 0.0, 0.0, seq_no, 0.0)

        exchange = str(raw_exchange).strip().upper()

        # 2. Timestamp extraction (Fail-closed on missing exchange timestamp)
        ts_val = getattr(event, "exchange_timestamp", None) if not isinstance(event, dict) else (event.get("exchange_timestamp") or event.get("timestamp"))

        if ts_val is None:
            reasons.append(AdmissionReasonCode.MISSING_EXCHANGE_TIMESTAMP)
            self._stats["rejected_malformed"] += 1
            return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, None, now_utc, 0.0, 0.0, seq_no, 0.0)

        if isinstance(ts_val, (int, float)):
            if ts_val <= 0:
                reasons.append(AdmissionReasonCode.MISSING_EXCHANGE_TIMESTAMP)
                self._stats["rejected_malformed"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, None, now_utc, 0.0, 0.0, seq_no, 0.0)
            tick_timestamp = datetime.fromtimestamp(ts_val / 1000.0 if ts_val > 1e11 else ts_val, tz=timezone.utc)
        elif isinstance(ts_val, str):
            tick_timestamp = pd.Timestamp(ts_val).to_pydatetime()
            if tick_timestamp.tzinfo is None:
                tick_timestamp = tick_timestamp.replace(tzinfo=timezone.utc)
        else:
            tick_timestamp = ts_val
            if tick_timestamp.tzinfo is None:
                tick_timestamp = tick_timestamp.replace(tzinfo=timezone.utc)

        latency_ms = (now_utc - tick_timestamp).total_seconds() * 1000.0

        # 3. Check allowed tokens and exchanges
        if self.policy.allowed_tokens and token not in self.policy.allowed_tokens:
            reasons.append(AdmissionReasonCode.TOKEN_NOT_IN_UNIVERSE)
            self._stats["rejected_malformed"] += 1
            return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

        if self.policy.allowed_exchanges and exchange not in self.policy.allowed_exchanges:
            reasons.append(AdmissionReasonCode.INVALID_EXCHANGE)
            self._stats["rejected_malformed"] += 1
            return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

        # 4. Check temporal validity: future timestamp vs stale latency
        future_skew = (tick_timestamp - now_utc).total_seconds()
        if future_skew > self.policy.max_future_skew_seconds:
            reasons.append(AdmissionReasonCode.FUTURE_TIMESTAMP_EXCEEDED)
            self._stats["rejected_malformed"] += 1
            return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

        stale_lag = (now_utc - tick_timestamp).total_seconds()
        if stale_lag > self.policy.max_stale_latency_seconds:
            reasons.append(AdmissionReasonCode.STALE_TICK_LATENCY)
            self._stats["dropped_stale"] += 1
            return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_STALE, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

        # 5. Check exchange calendar (Weekend and Holiday gating)
        if self.policy.check_session_hours:
            ist_ts = pd.Timestamp(tick_timestamp).tz_convert(IST)
            ist_date = ist_ts.date()
            if ist_date.weekday() >= 5:
                reasons.append(AdmissionReasonCode.WEEKEND_SESSION_REJECTED)
                self._stats["dropped_out_of_session"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_OUT_OF_SESSION, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

            if not self.market_calendar.is_trading_day(ist_date):
                reasons.append(AdmissionReasonCode.HOLIDAY_SESSION_REJECTED)
                self._stats["dropped_out_of_session"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_OUT_OF_SESSION, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

            if not self.calendar.is_market_open(exchange, tick_timestamp):
                reasons.append(AdmissionReasonCode.OUT_OF_SESSION_HOURS)
                self._stats["dropped_out_of_session"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_OUT_OF_SESSION, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)

        # 6. Event-Specific Processing & Validation
        is_depth20 = isinstance(event, Depth20Snapshot) or (isinstance(event, dict) and "bids" in event and "asks" in event and "ltp" not in event)
        price = 0.0
        cumulative_volume = 0

        if is_depth20:
            # Depth 20 Snapshot validation
            bids = getattr(event, "bids", None) if not isinstance(event, dict) else event.get("bids", [])
            asks = getattr(event, "asks", None) if not isinstance(event, dict) else event.get("asks", [])
            depth_res = self._validate_depth_book(bids, asks)
            if depth_res is not None:
                reasons.append(depth_res[1])
                action = depth_res[0]
                if action == TickAdmissionAction.QUARANTINE:
                    self._stats["quarantined"] += 1
                else:
                    self._stats["rejected_malformed"] += 1
                return self._build_result(token, symbol, exchange, action, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)
        else:
            # Price extraction & validation
            price_val = getattr(event, "ltp", None) if not isinstance(event, dict) else (event.get("ltp") or event.get("price") or event.get("close"))
            if price_val is None:
                reasons.append(AdmissionReasonCode.PRICE_NON_FINITE)
                self._stats["rejected_malformed"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, 0.0, 0.0, seq_no, latency_ms)
            
            price = float(price_val)
            if not np.isfinite(price):
                reasons.append(AdmissionReasonCode.PRICE_NON_FINITE)
                self._stats["rejected_malformed"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, price, 0.0, seq_no, latency_ms)

            if price <= 0.0:
                reasons.append(AdmissionReasonCode.PRICE_NON_POSITIVE)
                self._stats["rejected_malformed"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, price, 0.0, seq_no, latency_ms)

            # Volume extraction & validation
            vol_val = getattr(event, "cumulative_volume", None) if not isinstance(event, dict) else (event.get("cumulative_volume") or event.get("volume"))
            cumulative_volume = int(vol_val or 0) if vol_val is not None else 0
            if cumulative_volume < 0:
                reasons.append(AdmissionReasonCode.VOLUME_NEGATIVE)
                self._stats["rejected_malformed"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.REJECT_MALFORMED, reasons, tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms)

            # Snap Quote depth validation
            if isinstance(event, SnapQuoteTick) or (isinstance(event, dict) and ("best_5_buy" in event or "best_5_sell" in event)):
                best_buy = getattr(event, "best_5_buy", ()) if not isinstance(event, dict) else event.get("best_5_buy", ())
                best_sell = getattr(event, "best_5_sell", ()) if not isinstance(event, dict) else event.get("best_5_sell", ())
                depth_res = self._validate_depth_book(best_buy, best_sell)
                if depth_res is not None:
                    reasons.append(depth_res[1])
                    action = depth_res[0]
                    if action == TickAdmissionAction.QUARANTINE:
                        self._stats["quarantined"] += 1
                    else:
                        self._stats["rejected_malformed"] += 1
                    return self._build_result(token, symbol, exchange, action, reasons, tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms)

        # 7. Deduplication check via sequence number or tick fingerprint
        fingerprint = f"{token}:{seq_no}:{tick_timestamp.isoformat()}:{price:.4f}:{cumulative_volume}"
        if fingerprint in self._dedup_set:
            reasons.append(AdmissionReasonCode.DUPLICATE_TICK_FINGERPRINT)
            self._stats["dropped_duplicate"] += 1
            return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_DUPLICATE, reasons, tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms)

        # 8. Stateful Stream State Tracking & Verification
        state = self._token_states.setdefault(token, TokenStreamState())
        current_session_date = pd.Timestamp(tick_timestamp).tz_convert(IST).date()
        velocity_pct = 0.0

        # A. Sequence number monotonicity without regression (within same session)
        if seq_no is not None and seq_no > 0:
            if state.session_date == current_session_date and state.last_sequence_number is not None and state.last_sequence_number > 0:
                if seq_no == state.last_sequence_number:
                    reasons.append(AdmissionReasonCode.DUPLICATE_SEQUENCE_NUMBER)
                    self._stats["dropped_duplicate"] += 1
                    return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_DUPLICATE, reasons, tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms)
                elif seq_no < state.last_sequence_number:
                    reasons.append(AdmissionReasonCode.SEQUENCE_GAP_DETECTED)
                elif seq_no > state.last_sequence_number + 1:
                    reasons.append(AdmissionReasonCode.SEQUENCE_GAP_DETECTED)

        # B. Out-of-order timestamp check (within same session)
        if state.session_date == current_session_date and state.last_exchange_timestamp is not None and tick_timestamp < state.last_exchange_timestamp:
            time_delta_ms = (state.last_exchange_timestamp - tick_timestamp).total_seconds() * 1000.0
            if time_delta_ms > self.policy.allow_out_of_order_within_ms:
                reasons.append(AdmissionReasonCode.OUT_OF_ORDER_TIMESTAMP)
                self._stats["dropped_stale"] += 1
                return self._build_result(token, symbol, exchange, TickAdmissionAction.DROP_STALE, reasons, tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms)


        # C. Cumulative volume monotonicity across SAME session
        if self.policy.enforce_monotonic_cumulative_volume and not is_depth20:
            if state.session_date == current_session_date and state.last_cumulative_volume > 0:
                if cumulative_volume > 0 and cumulative_volume < state.last_cumulative_volume:
                    reasons.append(AdmissionReasonCode.CUMULATIVE_VOLUME_DECREASE)
                    self._stats["quarantined"] += 1
                    return self._build_result(token, symbol, exchange, TickAdmissionAction.QUARANTINE, reasons, tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms)

        # D. Extreme single-tick price velocity across SAME session (Overnight gap safe)
        if not is_depth20 and state.session_date == current_session_date and state.last_ltp is not None and state.last_ltp > 0:
            velocity_pct = abs(price - state.last_ltp) / state.last_ltp
            if velocity_pct > self.policy.max_price_velocity_pct:
                reasons.append(AdmissionReasonCode.EXTREME_PRICE_VELOCITY)
                self._stats["quarantined"] += 1
                return self._build_result(
                    token, symbol, exchange, TickAdmissionAction.QUARANTINE, reasons,
                    tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms,
                    price_velocity_pct=velocity_pct,
                )

        # 9. Update state & commit deduplication record
        if seq_no is not None:
            state.highest_sequence_seen = max(state.highest_sequence_seen or 0, seq_no)
        state.last_sequence_number = seq_no
        state.last_exchange_timestamp = tick_timestamp
        if not is_depth20:
            state.last_ltp = price
            state.last_cumulative_volume = cumulative_volume
        state.session_date = current_session_date
        state.processed_count += 1

        if len(self._dedup_cache) == self.policy.dedup_cache_size:
            oldest = self._dedup_cache.popleft()
            self._dedup_set.discard(oldest)
        self._dedup_cache.append(fingerprint)
        self._dedup_set.add(fingerprint)

        reasons.append(AdmissionReasonCode.VALID_TICK)
        self._stats["accepted"] += 1
        return self._build_result(
            token, symbol, exchange, TickAdmissionAction.ACCEPT, reasons,
            tick_timestamp, now_utc, price, cumulative_volume, seq_no, latency_ms,
            price_velocity_pct=velocity_pct,
        )

    def _validate_depth_book(
        self,
        bids: Any,
        asks: Any,
    ) -> tuple[TickAdmissionAction, AdmissionReasonCode] | None:
        """Validate book monotonicity, positive prices/quantities, and crossed book sanity."""
        if not bids or not asks:
            return None

        bid_levels = list(bids)
        ask_levels = list(asks)
        if not bid_levels or not ask_levels:
            return None

        # 1. Validate Bid levels (monotonic non-increasing prices: Bid[i] >= Bid[i+1] > 0)
        prev_bid_price = float("inf")
        for lvl in bid_levels:
            p = float(getattr(lvl, "price", None) or (lvl.get("price") if isinstance(lvl, dict) else 0.0) or 0.0)
            q = int(getattr(lvl, "quantity", None) or (lvl.get("quantity") if isinstance(lvl, dict) else 0) or 0)
            if p <= 0.0:
                return (TickAdmissionAction.REJECT_MALFORMED, AdmissionReasonCode.INVALID_DEPTH_PRICE)
            if q < 0:
                return (TickAdmissionAction.REJECT_MALFORMED, AdmissionReasonCode.INVALID_DEPTH_QUANTITY)
            if p > prev_bid_price:
                return (TickAdmissionAction.QUARANTINE, AdmissionReasonCode.INVALID_DEPTH_ORDERING)
            prev_bid_price = p

        # 2. Validate Ask levels (monotonic non-decreasing prices: Ask[i] <= Ask[i+1] > 0)
        prev_ask_price = 0.0
        for lvl in ask_levels:
            p = float(getattr(lvl, "price", None) or (lvl.get("price") if isinstance(lvl, dict) else 0.0) or 0.0)
            q = int(getattr(lvl, "quantity", None) or (lvl.get("quantity") if isinstance(lvl, dict) else 0) or 0)
            if p <= 0.0:
                return (TickAdmissionAction.REJECT_MALFORMED, AdmissionReasonCode.INVALID_DEPTH_PRICE)
            if q < 0:
                return (TickAdmissionAction.REJECT_MALFORMED, AdmissionReasonCode.INVALID_DEPTH_QUANTITY)
            if p < prev_ask_price:
                return (TickAdmissionAction.QUARANTINE, AdmissionReasonCode.INVALID_DEPTH_ORDERING)
            prev_ask_price = p

        # 3. Top of book spread sanity (Best Bid < Best Ask)
        best_bid = float(getattr(bid_levels[0], "price", None) or (bid_levels[0].get("price") if isinstance(bid_levels[0], dict) else 0.0) or 0.0)
        best_ask = float(getattr(ask_levels[0], "price", None) or (ask_levels[0].get("price") if isinstance(ask_levels[0], dict) else 0.0) or 0.0)
        if best_bid >= best_ask:
            return (TickAdmissionAction.QUARANTINE, AdmissionReasonCode.CROSSED_BOOK_BID_GE_ASK)

        return None

    def persist_quarantine(
        self,
        conn: Any,
        result: TickAdmissionResult,
        raw_payload: Any = None,
    ) -> None:
        """Persist a quarantined or rejected tick to DuckDB."""
        if conn is None:
            raise ValueError("DuckDB connection must not be None")
        raw_conn = getattr(conn, "conn", conn)
        if raw_conn is None or not hasattr(raw_conn, "execute"):
            raise ValueError("Resolved connection must support .execute()")

        quarantine_id = f"quar_{uuid.uuid4().hex[:12]}"
        reasons_str = "; ".join(r.value for r in result.reasons)
        payload_str = json.dumps(raw_payload, default=str) if raw_payload is not None else None
        tick_ts_str = result.tick_timestamp.isoformat() if result.tick_timestamp else datetime.now(timezone.utc).isoformat()

        raw_conn.execute(
            """
            INSERT OR REPLACE INTO live_market_data_quarantine (
                quarantine_id, token, symbol, exchange, tick_timestamp,
                received_timestamp, action, reasons, last_price, volume,
                raw_payload_json, quarantined_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                quarantine_id,
                result.token,
                result.symbol,
                result.exchange,
                tick_ts_str,
                result.received_timestamp.isoformat(),
                result.action.value,
                reasons_str,
                result.price,
                result.volume,
                payload_str,
                datetime.now(timezone.utc).isoformat(),
            ],
        )

    def get_stats(self) -> dict[str, Any]:
        """Return real-time admission telemetry counters."""
        total = max(self._stats["total_evaluated"], 1)
        return {
            **self._stats,
            "acceptance_rate_pct": (self._stats["accepted"] / total) * 100.0,
            "quarantine_rate_pct": (self._stats["quarantined"] / total) * 100.0,
            "active_token_count": len(self._token_states),
        }

    def _build_result(
        self,
        token: str,
        symbol: str | None,
        exchange: str,
        action: TickAdmissionAction,
        reasons: list[AdmissionReasonCode],
        tick_ts: datetime | None,
        recv_ts: datetime,
        price: float,
        volume: float,
        seq_no: int | None,
        latency_ms: float,
        price_velocity_pct: float = 0.0,
    ) -> TickAdmissionResult:
        return TickAdmissionResult(
            token=token,
            symbol=symbol,
            exchange=exchange,
            action=action,
            reasons=tuple(reasons),
            tick_timestamp=tick_ts,
            received_timestamp=recv_ts,
            price=price,
            volume=volume,
            sequence_number=seq_no,
            latency_ms=latency_ms,
            price_velocity_pct=price_velocity_pct,
            metrics={"acceptance": action == TickAdmissionAction.ACCEPT},
        )
