"""Unit tests for pure binary SmartStreamDecoder and PriceScaler."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from data_platform.contracts import (
    Depth20Snapshot,
    LiveTickerMode,
    LtpTick,
    QuoteTick,
    SnapQuoteTick,
)
from smartapi.stream_decoder import PriceScaler, SmartStreamDecoder
from tests.fixtures.smartstream_packets import (
    build_depth20_packet,
    build_ltp_packet,
    build_quote_packet,
    build_snap_quote_packet,
)


class TestPriceScaler(unittest.TestCase):
    def test_equity_segment_price_scaling(self) -> None:
        """Standard equity / derivative segments divide by 100.0."""
        self.assertEqual(PriceScaler.scale(250050, 1), 2500.50)
        self.assertEqual(PriceScaler.scale(100000, 2), 1000.00)
        self.assertEqual(PriceScaler.scale(55025, 3), 550.25)
        self.assertEqual(PriceScaler.scale(6000000, 5), 60000.00)

    def test_currency_cde_fo_segment_price_scaling(self) -> None:
        """Currency derivatives (CDE_FO / exchange_type=13) divide by 10,000,000.0 (1e7)."""
        # USDINR raw 82750000 -> 8.275 (or 82.7500 for 827500000)
        raw_price = 827500000  # 82.7500
        self.assertAlmostEqual(PriceScaler.scale(raw_price, 13), 82.7500, places=4)
        raw_price_2 = 10000000  # 1.0000
        self.assertAlmostEqual(PriceScaler.scale(raw_price_2, 13), 1.0, places=6)


class TestSmartStreamDecoder(unittest.TestCase):
    def setUp(self) -> None:
        self.recv_utc = datetime(2026, 8, 20, 9, 15, 0, tzinfo=timezone.utc)
        self.recv_ns = 1_000_000_000

    def test_decode_ltp_packet(self) -> None:
        packet = build_ltp_packet(mode=1, exchange_type=1, token="2885", seq_num=501, ltp_raw=250050)
        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)

        self.assertIsInstance(event, LtpTick)
        self.assertEqual(event.exchange, "NSE_CM")
        self.assertEqual(event.token, "2885")
        self.assertEqual(event.sequence_number, 501)
        self.assertEqual(event.ltp, 2500.50)
        self.assertEqual(event.mode, LiveTickerMode.LTP)
        self.assertEqual(event.raw_packet_size, 51)

    def test_decode_currency_ltp_packet_with_1e7_scaling(self) -> None:
        """Verify CDE_FO (exchange 13) divides raw price by 1e7."""
        packet = build_ltp_packet(mode=1, exchange_type=13, token="USDINR", seq_num=502, ltp_raw=827500000)
        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)

        self.assertIsInstance(event, LtpTick)
        self.assertEqual(event.exchange, "CDE_FO")
        self.assertEqual(event.token, "USDINR")
        self.assertAlmostEqual(event.ltp, 82.75, places=4)

    def test_decode_quote_packet(self) -> None:
        packet = build_quote_packet(
            mode=2,
            exchange_type=1,
            token="3045",
            seq_num=701,
            ltp_raw=150000,
            ltq=25,
            cum_vol=500_000,
            day_open_raw=148000,
            day_high_raw=151000,
            day_low_raw=147500,
            day_close_raw=149000,
        )
        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)

        self.assertIsInstance(event, QuoteTick)
        self.assertEqual(event.token, "3045")
        self.assertEqual(event.ltp, 1500.00)
        self.assertEqual(event.last_traded_qty, 25)
        self.assertEqual(event.cumulative_volume, 500_000)
        self.assertEqual(event.day_open, 1480.00)
        self.assertEqual(event.day_high, 1510.00)
        self.assertEqual(event.day_low, 1475.00)
        self.assertEqual(event.day_close, 1490.00)
        self.assertEqual(event.raw_packet_size, 123)

    def test_decode_snap_quote_packet_oi_double_and_best5_sides(self) -> None:
        """Verify IEEE-754 double OI change percentage and explicit Best-5 BUY (1) vs SELL (0) sides."""
        packet = build_snap_quote_packet(
            mode=3,
            exchange_type=1,
            token="2885",
            seq_num=801,
            open_interest=750_000,
            oi_change_pct=4.875,  # 4.875% IEEE-754 double
        )
        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)

        self.assertIsInstance(event, SnapQuoteTick)
        self.assertEqual(event.open_interest, 750_000)
        self.assertAlmostEqual(event.oi_change_pct, 4.875, places=4)
        self.assertEqual(event.raw_packet_size, 379)

        # Best-5 depth
        self.assertEqual(len(event.best_5_buy), 5)
        self.assertEqual(len(event.best_5_sell), 5)

        # All buy entries must have flag=1
        for level in event.best_5_buy:
            self.assertEqual(level.flag, 1)
            self.assertGreater(level.price, 0)
            self.assertGreater(level.quantity, 0)

        # All sell entries must have flag=0
        for level in event.best_5_sell:
            self.assertEqual(level.flag, 0)
            self.assertGreater(level.price, 0)
            self.assertGreater(level.quantity, 0)

    def test_snap_quote_golden_byte_offsets(self) -> None:
        """Verify exact byte offsets: Best-5 at bytes 147..347, Circuits at bytes 347..379."""
        packet = build_snap_quote_packet(
            mode=3,
            exchange_type=1,
            token="2885",
            upper_circuit_raw=275000,
            lower_circuit_raw=225000,
            high_52w_raw=280000,
            low_52w_raw=210000,
        )
        # Byte 147: first depth level flag (uint16 = 1)
        import struct
        first_depth_flag = struct.unpack_from("<h", packet, 147)[0]
        self.assertEqual(first_depth_flag, 1)

        # Byte 347: upper circuit (int64 = 275000)
        upper_c = struct.unpack_from("<q", packet, 347)[0]
        self.assertEqual(upper_c, 275000)

        # Byte 371: low 52w (int64 = 210000)
        low_52w = struct.unpack_from("<q", packet, 371)[0]
        self.assertEqual(low_52w, 210000)

        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)
        self.assertEqual(event.upper_circuit, 2750.0)
        self.assertEqual(event.lower_circuit, 2250.0)
        self.assertEqual(event.high_52w, 2800.0)
        self.assertEqual(event.low_52w, 2100.0)


    def test_snap_quote_invalid_oi_change_sanitization(self) -> None:
        """Non-finite or extreme OI change (>10,000%) returns None."""
        packet_nan = build_snap_quote_packet(oi_change_pct=float("nan"))
        event_nan = SmartStreamDecoder.decode(packet_nan, self.recv_utc, self.recv_ns)
        self.assertIsNone(event_nan.oi_change_pct)

        packet_inf = build_snap_quote_packet(oi_change_pct=float("inf"))
        event_inf = SmartStreamDecoder.decode(packet_inf, self.recv_utc, self.recv_ns)
        self.assertIsNone(event_inf.oi_change_pct)

        packet_huge = build_snap_quote_packet(oi_change_pct=15_000_000.0)
        event_huge = SmartStreamDecoder.decode(packet_huge, self.recv_utc, self.recv_ns)
        self.assertIsNone(event_huge.oi_change_pct)

    def test_decode_depth20_packet_structure(self) -> None:
        """Verify dedicated 443-byte Mode 4 Depth20 parsing."""
        packet = build_depth20_packet(mode=4, exchange_type=1, token="2885")
        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)

        self.assertIsInstance(event, Depth20Snapshot)
        self.assertEqual(event.mode, LiveTickerMode.DEPTH)
        self.assertEqual(event.raw_packet_size, 443)
        self.assertEqual(len(event.bids), 20)
        self.assertEqual(len(event.asks), 20)

        # Verify bid prices descending & ask prices ascending
        self.assertGreater(event.bids[0].price, event.bids[1].price)
        self.assertLess(event.asks[0].price, event.asks[1].price)
        for bid in event.bids:
            self.assertEqual(bid.flag, 1)
        for ask in event.asks:
            self.assertEqual(ask.flag, 0)

    def test_malformed_packet_sizes_raise_value_error(self) -> None:
        """Packets with wrong size must raise ValueError without crashing."""
        # 50 bytes instead of 51 bytes for Mode 1
        with self.assertRaises(ValueError):
            SmartStreamDecoder.decode(b"\x01\x01" + b"\x00" * 48)

        # 120 bytes instead of 123 bytes for Mode 2
        with self.assertRaises(ValueError):
            SmartStreamDecoder.decode(b"\x02\x01" + b"\x00" * 118)

        # Unknown mode 99
        with self.assertRaises(ValueError):
            SmartStreamDecoder.decode(b"\x63\x01" + b"\x00" * 49)

    def test_null_padded_token_decoding(self) -> None:
        """Verify tokens with varying null-byte padding decode cleanly."""
        packet = build_ltp_packet(token="INFY-EQ")
        event = SmartStreamDecoder.decode(packet, self.recv_utc, self.recv_ns)
        self.assertEqual(event.token, "INFY-EQ")


if __name__ == "__main__":
    unittest.main()
