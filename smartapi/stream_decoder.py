"""Zero-I/O binary frame parser and price scaler for Angel One SmartStream WebSocket."""

from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from typing import Callable

from data_platform.contracts import (
    Depth20Snapshot,
    DepthLevel,
    LiveTickerMode,
    LtpTick,
    MarketDataEvent,
    QuoteTick,
    SnapQuoteTick,
)


class PriceScaler:
    """Centralized price scaling according to exchange segment rules."""

    @staticmethod
    def scale(raw_price: int, exchange_type: int) -> float:
        """Convert raw integer price from SmartAPI wire packet to float currency price.

        Currency derivatives (CDE_FO / exchange_type=13) use 10^7 divisor (10,000,000.0).
        All other supported segments (NSE_CM, NSE_FO, BSE_CM, BSE_FO, MCX_FO, NCX_FO) use 100.0.

        Args:
            raw_price: Unscaled integer price from wire packet.
            exchange_type: Angel One exchange segment identifier.

        Returns:
            float: Scaled floating-point price.
        """
        if exchange_type == 13:  # CDE_FO (Currency Derivatives)
            return raw_price / 10_000_000.0
        return raw_price / 100.0


class SmartStreamDecoder:
    """Pure zero-I/O binary parser for SmartStream packets."""

    EXPECTED_PACKET_SIZES: dict[int, int] = {
        1: 51,   # LTP
        2: 123,  # QUOTE
        3: 379,  # SNAP_QUOTE
        4: 443,  # DEPTH20
    }

    EXCHANGE_TYPE_NAMES: dict[int, str] = {
        1: "NSE_CM",
        2: "NSE_FO",
        3: "BSE_CM",
        4: "BSE_FO",
        5: "MCX_FO",
        7: "NCX_FO",
        13: "CDE_FO",
    }

    @classmethod
    def decode(
        cls,
        data: bytes,
        received_at_utc: datetime | None = None,
        received_monotonic_ns: int | None = None,
        symbol_resolver: Callable[[str, str], str | None] | None = None,
    ) -> MarketDataEvent:
        """Parse raw binary WebSocket frame into a strongly typed MarketDataEvent.

        Args:
            data: Raw binary packet from WebSocketApp.
            received_at_utc: UTC arrival timestamp.
            received_monotonic_ns: Monotonic arrival timestamp in nanoseconds.
            symbol_resolver: Optional callable (exchange, token) -> tradingsymbol.

        Returns:
            MarketDataEvent: Decoded typed event.

        Raises:
            ValueError: If packet length or mode is invalid or malformed.
        """
        if len(data) < 2:
            raise ValueError(f"Packet too short to determine mode: {len(data)} bytes")

        mode_int = data[0]
        expected_size = cls.EXPECTED_PACKET_SIZES.get(mode_int)
        if expected_size is None:
            raise ValueError(f"Unknown subscription mode: {mode_int}")

        if len(data) != expected_size:
            raise ValueError(
                f"Invalid packet size for mode {mode_int}: expected {expected_size} bytes, got {len(data)} bytes"
            )

        recv_utc = received_at_utc or datetime.now(timezone.utc)
        recv_ns = received_monotonic_ns or 0

        if mode_int == 1:
            return cls._parse_ltp(data, recv_utc, recv_ns, symbol_resolver)
        elif mode_int == 2:
            return cls._parse_quote(data, recv_utc, recv_ns, symbol_resolver)
        elif mode_int == 3:
            return cls._parse_snap_quote(data, recv_utc, recv_ns, symbol_resolver)
        elif mode_int == 4:
            return cls._parse_depth20(data, recv_utc, recv_ns, symbol_resolver)
        else:
            raise ValueError(f"Unsupported mode: {mode_int}")

    @staticmethod
    def _parse_token(raw_token_bytes: bytes) -> str:
        """Decode and sanitize null-padded 25-byte token string."""
        return raw_token_bytes.split(b"\x00")[0].decode("ascii", errors="ignore").strip()


    @classmethod
    def _parse_ltp(
        cls,
        data: bytes,
        recv_utc: datetime,
        recv_ns: int,
        symbol_resolver: Callable[[str, str], str | None] | None,
    ) -> LtpTick:
        """Parse 51-byte Mode 1 LTP packet."""
        exchange_type = data[1]
        token = cls._parse_token(data[2:27])
        exchange_name = cls.EXCHANGE_TYPE_NAMES.get(exchange_type, f"EX_{exchange_type}")
        symbol = symbol_resolver(exchange_name, token) if symbol_resolver else None

        seq_num, ex_ts_raw, ltp_raw = struct.unpack_from("<qqq", data, 27)

        # Exchange timestamp is epoch ms
        ex_ts = datetime.fromtimestamp(ex_ts_raw / 1000.0, tz=timezone.utc) if ex_ts_raw > 0 else None
        feed_latency = (recv_utc.timestamp() * 1000.0 - ex_ts_raw) if ex_ts_raw > 0 else None
        ltp = PriceScaler.scale(ltp_raw, exchange_type)

        return LtpTick(
            exchange=exchange_name,
            token=token,
            symbol=symbol,
            mode=LiveTickerMode.LTP,
            exchange_timestamp=ex_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=recv_ns,
            raw_packet_size=len(data),
            feed_latency_ms=feed_latency,
            sequence_number=seq_num,
            ltp=ltp,
        )

    @classmethod
    def _parse_quote(
        cls,
        data: bytes,
        recv_utc: datetime,
        recv_ns: int,
        symbol_resolver: Callable[[str, str], str | None] | None,
    ) -> QuoteTick:
        """Parse 123-byte Mode 2 Quote packet."""
        exchange_type = data[1]
        token = cls._parse_token(data[2:27])
        exchange_name = cls.EXCHANGE_TYPE_NAMES.get(exchange_type, f"EX_{exchange_type}")
        symbol = symbol_resolver(exchange_name, token) if symbol_resolver else None

        seq_num, ex_ts_raw, ltp_raw = struct.unpack_from("<qqq", data, 27)
        ltq, avg_price_raw, cum_vol, total_buy, total_sell = struct.unpack_from("<qqqdd", data, 51)
        open_raw, high_raw, low_raw, close_raw = struct.unpack_from("<qqqq", data, 91)

        ex_ts = datetime.fromtimestamp(ex_ts_raw / 1000.0, tz=timezone.utc) if ex_ts_raw > 0 else None
        feed_latency = (recv_utc.timestamp() * 1000.0 - ex_ts_raw) if ex_ts_raw > 0 else None

        ltp = PriceScaler.scale(ltp_raw, exchange_type)
        avg_price = PriceScaler.scale(avg_price_raw, exchange_type)
        day_open = PriceScaler.scale(open_raw, exchange_type)
        day_high = PriceScaler.scale(high_raw, exchange_type)
        day_low = PriceScaler.scale(low_raw, exchange_type)
        day_close = PriceScaler.scale(close_raw, exchange_type)

        return QuoteTick(
            exchange=exchange_name,
            token=token,
            symbol=symbol,
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=ex_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=recv_ns,
            raw_packet_size=len(data),
            feed_latency_ms=feed_latency,
            sequence_number=seq_num,
            ltp=ltp,
            last_traded_qty=ltq,
            average_traded_price=avg_price,
            cumulative_volume=cum_vol,
            total_buy_qty=total_buy,
            total_sell_qty=total_sell,
            day_open=day_open,
            day_high=day_high,
            day_low=day_low,
            day_close=day_close,
        )

    @classmethod
    def _parse_snap_quote(
        cls,
        data: bytes,
        recv_utc: datetime,
        recv_ns: int,
        symbol_resolver: Callable[[str, str], str | None] | None,
    ) -> SnapQuoteTick:
        """Parse 379-byte Mode 3 Snap Quote packet."""
        exchange_type = data[1]
        token = cls._parse_token(data[2:27])
        exchange_name = cls.EXCHANGE_TYPE_NAMES.get(exchange_type, f"EX_{exchange_type}")
        symbol = symbol_resolver(exchange_name, token) if symbol_resolver else None

        seq_num, ex_ts_raw, ltp_raw = struct.unpack_from("<qqq", data, 27)
        ltq, avg_price_raw, cum_vol, total_buy, total_sell = struct.unpack_from("<qqqdd", data, 51)
        open_raw, high_raw, low_raw, close_raw = struct.unpack_from("<qqqq", data, 91)

        lt_ts_raw, oi = struct.unpack_from("<qq", data, 123)
        # Parse OI change percentage as 64-bit IEEE double (<d) at offset 139
        oi_change_raw = struct.unpack_from("<d", data, 139)[0]
        oi_change_pct = oi_change_raw if math.isfinite(oi_change_raw) and abs(oi_change_raw) <= 10_000.0 else None

        # Parse Best-5 Depth (10 records * 20 bytes = 200 bytes at offset 147..347)
        best_5_buy: list[DepthLevel] = []
        best_5_sell: list[DepthLevel] = []

        depth_offset = 147
        for _ in range(10):
            flag, qty, price_raw, num_orders = struct.unpack_from("<hqqh", data, depth_offset)
            depth_offset += 20
            level_price = PriceScaler.scale(price_raw, exchange_type)
            level = DepthLevel(price=level_price, quantity=qty, orders=num_orders, flag=flag)

            # Invariant: flag 1 = BUY (Bid), flag 0 = SELL (Ask)
            if flag == 1:
                best_5_buy.append(level)
            elif flag == 0:
                best_5_sell.append(level)

        # Parse Circuit limits and 52-week statistics at offset 347..379
        upper_c_raw, lower_c_raw, h52_raw, l52_raw = struct.unpack_from("<qqqq", data, 347)


        ex_ts = datetime.fromtimestamp(ex_ts_raw / 1000.0, tz=timezone.utc) if ex_ts_raw > 0 else None
        last_trade_ts = (
            datetime.fromtimestamp(lt_ts_raw / 1000.0 if lt_ts_raw > 1e11 else lt_ts_raw, tz=timezone.utc)
            if lt_ts_raw > 0
            else None
        )
        feed_latency = (recv_utc.timestamp() * 1000.0 - ex_ts_raw) if ex_ts_raw > 0 else None

        return SnapQuoteTick(
            exchange=exchange_name,
            token=token,
            symbol=symbol,
            mode=LiveTickerMode.SNAP_QUOTE,
            exchange_timestamp=ex_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=recv_ns,
            raw_packet_size=len(data),
            feed_latency_ms=feed_latency,
            sequence_number=seq_num,
            ltp=PriceScaler.scale(ltp_raw, exchange_type),
            last_traded_qty=ltq,
            average_traded_price=PriceScaler.scale(avg_price_raw, exchange_type),
            cumulative_volume=cum_vol,
            total_buy_qty=total_buy,
            total_sell_qty=total_sell,
            day_open=PriceScaler.scale(open_raw, exchange_type),
            day_high=PriceScaler.scale(high_raw, exchange_type),
            day_low=PriceScaler.scale(low_raw, exchange_type),
            day_close=PriceScaler.scale(close_raw, exchange_type),
            last_traded_timestamp=last_trade_ts,
            open_interest=oi,
            oi_change_pct=oi_change_pct,
            upper_circuit=PriceScaler.scale(upper_c_raw, exchange_type),
            lower_circuit=PriceScaler.scale(lower_c_raw, exchange_type),
            high_52w=PriceScaler.scale(h52_raw, exchange_type),
            low_52w=PriceScaler.scale(l52_raw, exchange_type),
            best_5_buy=tuple(best_5_buy),
            best_5_sell=tuple(best_5_sell),
        )

    @classmethod
    def _parse_depth20(
        cls,
        data: bytes,
        recv_utc: datetime,
        recv_ns: int,
        symbol_resolver: Callable[[str, str], str | None] | None,
    ) -> Depth20Snapshot:
        """Parse dedicated 443-byte Mode 4 Depth20 packet.

        Layout:
        0       : mode (1B)
        1       : exchange_type (1B)
        2:27    : token (25B)
        27:35   : exchange_timestamp (8B <q)
        35:43   : packet_received_time (8B <q)
        43:243  : 20 Buy depth records (20 * 10B = 200B)
        243:443 : 20 Sell depth records (20 * 10B = 200B)
        Each 10B record: quantity (4B <i), price (4B <i), num_orders (2B <h)
        """
        exchange_type = data[1]
        token = cls._parse_token(data[2:27])
        exchange_name = cls.EXCHANGE_TYPE_NAMES.get(exchange_type, f"EX_{exchange_type}")
        symbol = symbol_resolver(exchange_name, token) if symbol_resolver else None

        ex_ts_raw, packet_recv_time = struct.unpack_from("<qq", data, 27)

        bids: list[DepthLevel] = []
        asks: list[DepthLevel] = []

        # 20 Buy records (43 to 243)
        offset = 43
        for _ in range(20):
            qty, price_raw, num_orders = struct.unpack_from("<iih", data, offset)
            offset += 10
            scaled_price = PriceScaler.scale(price_raw, exchange_type)
            bids.append(DepthLevel(price=scaled_price, quantity=qty, orders=num_orders, flag=1))

        # 20 Sell records (243 to 443)
        offset = 243
        for _ in range(20):
            qty, price_raw, num_orders = struct.unpack_from("<iih", data, offset)
            offset += 10
            scaled_price = PriceScaler.scale(price_raw, exchange_type)
            asks.append(DepthLevel(price=scaled_price, quantity=qty, orders=num_orders, flag=0))

        ex_ts = datetime.fromtimestamp(ex_ts_raw / 1000.0, tz=timezone.utc) if ex_ts_raw > 0 else None
        feed_latency = (recv_utc.timestamp() * 1000.0 - ex_ts_raw) if ex_ts_raw > 0 else None

        return Depth20Snapshot(
            exchange=exchange_name,
            token=token,
            symbol=symbol,
            mode=LiveTickerMode.DEPTH,
            exchange_timestamp=ex_ts,
            received_at_utc=recv_utc,
            received_monotonic_ns=recv_ns,
            raw_packet_size=len(data),
            feed_latency_ms=feed_latency,
            packet_received_time=packet_recv_time,
            bids=tuple(bids),
            asks=tuple(asks),
        )
