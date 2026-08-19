"""Deterministic binary packet test fixtures for SmartStream WebSocket decoder."""

from __future__ import annotations

import struct


def build_ltp_packet(
    mode: int = 1,
    exchange_type: int = 1,
    token: str = "2885",
    seq_num: int = 1001,
    ex_ts_ms: int = 1690000000000,
    ltp_raw: int = 250050,  # Rs 2500.50 (for equity) or currency
) -> bytes:
    """Build a 51-byte LTP packet."""
    token_bytes = token.encode("ascii")[:25].ljust(25, b"\x00")
    header = struct.pack("<BB25s", mode, exchange_type, token_bytes)
    body = struct.pack("<qqq", seq_num, ex_ts_ms, ltp_raw)
    packet = header + body
    assert len(packet) == 51, f"Expected 51 bytes, got {len(packet)}"
    return packet


def build_quote_packet(
    mode: int = 2,
    exchange_type: int = 1,
    token: str = "2885",
    seq_num: int = 1002,
    ex_ts_ms: int = 1690000000000,
    ltp_raw: int = 250050,
    ltq: int = 50,
    avg_price_raw: int = 249500,
    cum_vol: int = 1_000_000,
    total_buy: float = 50_000.0,
    total_sell: float = 45_000.0,
    day_open_raw: int = 248000,
    day_high_raw: int = 251000,
    day_low_raw: int = 247500,
    day_close_raw: int = 249000,
) -> bytes:
    """Build a 123-byte Quote packet."""
    token_bytes = token.encode("ascii")[:25].ljust(25, b"\x00")
    header = struct.pack("<BB25s", mode, exchange_type, token_bytes)
    data = struct.pack(
        "<qqqqqqddqqqq",
        seq_num,
        ex_ts_ms,
        ltp_raw,
        ltq,
        avg_price_raw,
        cum_vol,
        total_buy,
        total_sell,
        day_open_raw,
        day_high_raw,
        day_low_raw,
        day_close_raw,
    )
    packet = header + data
    assert len(packet) == 123, f"Expected 123 bytes, got {len(packet)}"
    return packet


def build_snap_quote_packet(
    mode: int = 3,
    exchange_type: int = 1,
    token: str = "2885",
    seq_num: int = 1003,
    ex_ts_ms: int = 1690000000000,
    ltp_raw: int = 250050,
    ltq: int = 50,
    avg_price_raw: int = 249500,
    cum_vol: int = 1_000_000,
    total_buy: float = 50_000.0,
    total_sell: float = 45_000.0,
    day_open_raw: int = 248000,
    day_high_raw: int = 251000,
    day_low_raw: int = 247500,
    day_close_raw: int = 249000,
    last_trade_ts_ms: int = 1690000000000,
    open_interest: int = 500_000,
    oi_change_pct: float = 5.25,  # 5.25% IEEE-754 double
    upper_circuit_raw: int = 275000,
    lower_circuit_raw: int = 225000,
    high_52w_raw: int = 280000,
    low_52w_raw: int = 210000,
) -> bytes:
    """Build a 379-byte Snap Quote packet."""
    token_bytes = token.encode("ascii")[:25].ljust(25, b"\x00")
    header = struct.pack("<BB25s", mode, exchange_type, token_bytes)
    quote_part = struct.pack(
        "<qqqqqqddqqqq",
        seq_num,
        ex_ts_ms,
        ltp_raw,
        ltq,
        avg_price_raw,
        cum_vol,
        total_buy,
        total_sell,
        day_open_raw,
        day_high_raw,
        day_low_raw,
        day_close_raw,
    )
    snap_part = struct.pack(
        "<qqdqqqq",
        last_trade_ts_ms,
        open_interest,
        oi_change_pct,  # <d 8-byte double at offset 139
        upper_circuit_raw,
        lower_circuit_raw,
        high_52w_raw,
        low_52w_raw,
    )

    # 10 Best-5 records (5 buy flag=1, 5 sell flag=0)
    best_5_records = bytearray()
    for i in range(5):
        # Buy: flag=1, qty=100*(i+1), price=250000 - i*10, orders=i+1
        rec = struct.pack("<hqqh", 1, 100 * (i + 1), 250000 - (i * 10), i + 1)
        best_5_records.extend(rec)
    for i in range(5):
        # Sell: flag=0, qty=150*(i+1), price=250100 + i*10, orders=i+1
        rec = struct.pack("<hqqh", 0, 150 * (i + 1), 250100 + (i * 10), i + 1)
        best_5_records.extend(rec)

    packet = header + quote_part + snap_part + bytes(best_5_records)
    assert len(packet) == 379, f"Expected 379 bytes, got {len(packet)}"
    return packet


def build_depth20_packet(
    mode: int = 4,
    exchange_type: int = 1,
    token: str = "2885",
    ex_ts_ms: int = 1690000000000,
    packet_recv_time: int = 1690000000010,
) -> bytes:
    """Build a 443-byte Depth20 packet."""
    token_bytes = token.encode("ascii")[:25].ljust(25, b"\x00")
    header = struct.pack("<BB25s", mode, exchange_type, token_bytes)
    ts_part = struct.pack("<qq", ex_ts_ms, packet_recv_time)

    # 20 Buy records (43:243, 10B each: <iih)
    buy_records = bytearray()
    for i in range(20):
        rec = struct.pack("<iih", 100 * (i + 1), 250000 - (i * 5), i + 1)
        buy_records.extend(rec)

    # 20 Sell records (243:443, 10B each: <iih)
    sell_records = bytearray()
    for i in range(20):
        rec = struct.pack("<iih", 120 * (i + 1), 250100 + (i * 5), i + 1)
        sell_records.extend(rec)

    packet = header + ts_part + bytes(buy_records) + bytes(sell_records)
    assert len(packet) == 443, f"Expected 443 bytes, got {len(packet)}"
    return packet
