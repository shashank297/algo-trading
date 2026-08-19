"""Unit and integration tests for corporate action and price adjustment engine."""

from __future__ import annotations

import tempfile
import unittest
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data_platform.adjustments import PriceAdjustmentEngine, TotalReturnEngine
from data_platform.contracts import PriceAdjustment
from data_platform.source_semantics import (
    CorporateActionBasisWarning,
    SourceBarSemantics,
    SourceBasisDetection,
    SourceSemanticsAdapter,
    UnsupportedAdjustmentConversion,
    VolumeAdjustment,
)
from storage.duckdb_manager import DuckDBManager



class TestPriceAdjustmentEngine(unittest.TestCase):
    def setUp(self) -> None:
        # Create a sample 5-day daily DataFrame with genuine raw unadjusted prices
        self.raw_bars = pd.DataFrame(
            {
                "timestamp": pd.date_range("2022-07-25", periods=5, freq="D", tz="UTC"),
                "open": [1000.0, 1020.0, 1010.0, 105.0, 108.0],
                "high": [1030.0, 1040.0, 1020.0, 110.0, 112.0],
                "low": [990.0, 1000.0, 995.0, 102.0, 105.0],
                "close": [1010.0, 1015.0, 1000.0, 106.0, 110.0],
                "volume": [10_000, 12_000, 15_000, 140_000, 160_000],
            }
        )

        # 10-for-1 split on 2022-07-28 (Tata Steel boundary: 1 old Rs 10 share -> 10 new Rs 1 shares)
        self.split_actions = pd.DataFrame(
            [
                {
                    "action_id": "TATASTEEL_20220728_SPLIT",
                    "symbol": "TATASTEEL-EQ",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "SPLIT",
                    "share_multiplier": 10.0,
                    "old_face_value": 10.0,
                    "new_face_value": 1.0,
                    "dividend_amount": 0.0,
                }
            ]
        )

    def test_split_factor_calculation(self) -> None:
        factors = PriceAdjustmentEngine.calculate_split_factors(self.raw_bars["timestamp"], self.split_actions)
        self.assertEqual(len(factors), 5)
        # First 3 days (before 2022-07-28) should have share_multiplier = 10.0
        self.assertEqual(factors.iloc[0], 10.0)
        self.assertEqual(factors.iloc[1], 10.0)
        self.assertEqual(factors.iloc[2], 10.0)
        # Last 2 days (on and after 2022-07-28) should have share_multiplier = 1.0
        self.assertEqual(factors.iloc[3], 1.0)
        self.assertEqual(factors.iloc[4], 1.0)

    # -------------------------------------------------------------------------
    # 3-Stage Tata Steel Integration & Source-Semantics Verification
    # -------------------------------------------------------------------------

    def test_tatasteel_stage_a_identify_provider_basis(self) -> None:
        """Stage A: Provider data (27-Jul close = 95.94, 28-Jul close = 100.35) is detected as SPLIT_ADJUSTED."""
        provider_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [96.00, 97.50],
                "high": [98.20, 101.50],
                "low": [94.50, 97.00],
                "close": [95.94, 100.35],
                "volume": [5_254_698, 48_500_000],
            }
        )

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            semantics = SourceSemanticsAdapter.infer_semantics(
                bars=provider_bars,
                corporate_actions=self.split_actions,
                provider_name="angel_one",
            )
            # Inferred basis should be SPLIT_ADJUSTED because observed ratio 95.94 / 97.50 ≈ 0.98 (near 1.0)
            self.assertEqual(semantics.price_adjustment, PriceAdjustment.SPLIT_ADJUSTED)
            self.assertTrue(any(issubclass(w.category, CorporateActionBasisWarning) for w in recorded_warnings))

    def test_tatasteel_stage_b_requesting_split_adjusted_on_provider_data(self) -> None:
        """Stage B: Requesting SPLIT_ADJUSTED on already-adjusted provider data preserves continuous prices (no double division to 9.59!)."""
        provider_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [96.00, 97.50],
                "high": [98.20, 101.50],
                "low": [94.50, 97.00],
                "close": [95.94, 100.35],
                "volume": [5_254_698, 48_500_000],
            }
        )

        provider_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            volume_adjustment=VolumeAdjustment.SPLIT_ADJUSTED,
            provider_name="angel_one",
        )

        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            provider_bars,
            self.split_actions,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            source_semantics=provider_semantics,
        )

        pre_close = float(adjusted.loc[adjusted["timestamp"] == pd.Timestamp("2022-07-27", tz="UTC"), "close"].iloc[0])
        post_close = float(adjusted.loc[adjusted["timestamp"] == pd.Timestamp("2022-07-28", tz="UTC"), "close"].iloc[0])

        # Exact price bounds
        self.assertTrue(90 < pre_close < 110, f"Expected 90 < pre_close < 110, got {pre_close}")
        self.assertTrue(90 < post_close < 110, f"Expected 90 < post_close < 110, got {post_close}")
        self.assertAlmostEqual(pre_close, 95.94, places=2)
        self.assertAlmostEqual(post_close, 100.35, places=2)

        # Overnight return continuity assertion: must NOT be 900%+
        overnight_return = (post_close / pre_close) - 1.0
        self.assertLess(abs(overnight_return), 0.25, f"Overnight return {overnight_return:.2%} violates continuity threshold.")

    def test_tatasteel_stage_c_genuine_raw_source_adjustment(self) -> None:
        """Stage C: Genuine raw pre-split bars (27-Jul close = 959.40, 28-Jul close = 100.35) are divided by 10 to yield ~95.94."""
        genuine_raw_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [960.00, 97.50],
                "high": [982.00, 101.50],
                "low": [945.00, 97.00],
                "close": [959.40, 100.35],
                "volume": [525_469, 48_500_000],
            }
        )

        raw_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.UNADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
            provider_name="raw_exchange",
        )

        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            genuine_raw_bars,
            self.split_actions,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            source_semantics=raw_semantics,
        )

        pre_close = float(adjusted.loc[adjusted["timestamp"] == pd.Timestamp("2022-07-27", tz="UTC"), "close"].iloc[0])
        post_close = float(adjusted.loc[adjusted["timestamp"] == pd.Timestamp("2022-07-28", tz="UTC"), "close"].iloc[0])

        self.assertAlmostEqual(pre_close, 95.94, places=2)
        self.assertAlmostEqual(post_close, 100.35, places=2)
        self.assertEqual(adjusted["volume"].iloc[0], 5_254_690)  # volume scaled by 10

        overnight_return = (post_close / pre_close) - 1.0
        self.assertLess(abs(overnight_return), 0.25)

    def test_turnover_invariance_on_genuine_raw_data(self) -> None:
        """Traded turnover (Close * Volume) must remain mathematically identical on genuine raw data."""
        raw_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.UNADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
        )
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            self.raw_bars,
            self.split_actions,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            source_semantics=raw_semantics,
        )
        raw_turnover = self.raw_bars["close"] * self.raw_bars["volume"]
        adj_turnover = adjusted["close"] * adjusted["volume"]
        np.testing.assert_allclose(raw_turnover.values, adj_turnover.values, rtol=1e-5)

    def test_bonus_issue_1_to_3_ratio(self) -> None:
        """1-for-3 bonus (1 new share for 3 existing held) => share_multiplier = (3+1)/3 = 4/3."""
        bonus_actions = pd.DataFrame(
            [
                {
                    "action_id": "POWERGRID_BONUS_1_3",
                    "symbol": "POWERGRID-EQ",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "BONUS",
                    "share_multiplier": 4.0 / 3.0,
                    "bonus_new_shares": 1.0,
                    "bonus_existing_shares": 3.0,
                    "dividend_amount": 0.0,
                }
            ]
        )
        raw_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.UNADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
        )
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            self.raw_bars,
            bonus_actions,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            source_semantics=raw_semantics,
        )
        # Pre-bonus open (1000.0) / (4/3) = 750.0
        self.assertAlmostEqual(adjusted["open"].iloc[0], 750.0)
        # Pre-bonus volume (10000) * (4/3) = 13333
        self.assertEqual(adjusted["volume"].iloc[0], 13333)

    def test_consolidation_reverse_split(self) -> None:
        """1-for-5 consolidation (5 old shares -> 1 new share) => share_multiplier = 0.2."""
        cons_actions = pd.DataFrame(
            [
                {
                    "action_id": "TEST_CONS",
                    "symbol": "TEST-EQ",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "CONSOLIDATION",
                    "share_multiplier": 0.2,
                    "dividend_amount": 0.0,
                }
            ]
        )
        raw_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.UNADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
        )
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            self.raw_bars,
            cons_actions,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            source_semantics=raw_semantics,
        )
        # Pre-consolidation price 1000.0 / 0.2 = 5000.0
        self.assertAlmostEqual(adjusted["open"].iloc[0], 5000.0)
        # Pre-consolidation volume 10000 * 0.2 = 2000
        self.assertEqual(adjusted["volume"].iloc[0], 2000)

    def test_back_adjusted_cash_dividend_does_not_scale_volume(self) -> None:
        """BACK_ADJUSTED must scale pre-ex prices by dividend continuity factor without scaling volume."""
        div_actions = pd.DataFrame(
            [
                {
                    "action_id": "TEST_DIV",
                    "symbol": "TEST-EQ",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "DIVIDEND",
                    "share_multiplier": 1.0,
                    "dividend_amount": 10.0,
                }
            ]
        )
        raw_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.UNADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
        )
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            self.raw_bars,
            div_actions,
            adjustment=PriceAdjustment.BACK_ADJUSTED,
            source_semantics=raw_semantics,
        )
        self.assertEqual(adjusted["adjustment"].iloc[0], "BACK_ADJUSTED")
        # Factor is 1 - (10 / 1000) = 0.99
        expected_close_0 = 1010.0 * 0.99
        self.assertAlmostEqual(adjusted["close"].iloc[0], expected_close_0, places=4)
        # Volume must NOT be scaled for cash dividends
        self.assertEqual(adjusted["volume"].iloc[0], 10_000)

    def test_split_adjusted_to_back_adjusted_transition(self) -> None:
        """Applying BACK_ADJUSTED to an already SPLIT_ADJUSTED series applies ONLY dividend factor."""
        split_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [100.0, 98.0],
                "high": [102.0, 100.0],
                "low": [99.0, 97.0],
                "close": [100.0, 99.0],
                "volume": [100_000, 120_000],
            }
        )
        div_actions = pd.DataFrame(
            [
                {
                    "action_id": "TEST_DIV",
                    "symbol": "TEST-EQ",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "DIVIDEND",
                    "share_multiplier": 1.0,
                    "dividend_amount": 2.0,  # 2% dividend on Rs 100 pre-close
                }
            ]
        )
        semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            volume_adjustment=VolumeAdjustment.SPLIT_ADJUSTED,
        )
        back_adj = PriceAdjustmentEngine.adjust_ohlcv(
            split_bars,
            div_actions,
            adjustment=PriceAdjustment.BACK_ADJUSTED,
            source_semantics=semantics,
        )
        self.assertEqual(back_adj["adjustment"].iloc[0], "BACK_ADJUSTED")
        # Factor: 1 - 2/100 = 0.98. Pre-close: 100 * 0.98 = 98.0
        self.assertAlmostEqual(back_adj["close"].iloc[0], 98.0)
        # Volume must remain 100,000
        self.assertEqual(back_adj["volume"].iloc[0], 100_000)

    def test_split_adjusted_to_back_adjusted_with_subsequent_split(self) -> None:
        """Applying BACK_ADJUSTED to a SPLIT_ADJUSTED series with subsequent splits normalizes nominal dividends by forward splits."""
        actions = pd.DataFrame(
            [
                {
                    "action_id": "DIV_2021",
                    "symbol": "SPLITDIVCO",
                    "ex_date": date(2021, 6, 1),
                    "action_type": "DIVIDEND",
                    "dividend_amount": 50.0,
                    "share_multiplier": 1.0,
                },
                {
                    "action_id": "SPLIT_2022",
                    "symbol": "SPLITDIVCO",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "SPLIT",
                    "share_multiplier": 10.0,
                },
            ]
        )
        # Split-adjusted prices: 2021 pre-split price is 100.0 (raw was 1000.0)
        split_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2021-05-31", tz="UTC"),
                    pd.Timestamp("2021-06-01", tz="UTC"),
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [100.0, 95.0, 96.0, 100.0],
                "high": [102.0, 96.0, 98.0, 102.0],
                "low": [98.0, 94.0, 95.0, 99.0],
                "close": [100.0, 95.0, 96.0, 100.0],
                "volume": [100_000, 120_000, 110_000, 130_000],
            }
        )
        semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            volume_adjustment=VolumeAdjustment.SPLIT_ADJUSTED,
        )
        back_adj = PriceAdjustmentEngine.adjust_ohlcv(
            split_bars,
            actions,
            adjustment=PriceAdjustment.BACK_ADJUSTED,
            source_semantics=semantics,
        )
        # Dividend Rs 50 normalized by 10x forward split -> Rs 5.0
        # Factor: 1.0 - (5.0 / 100.0) = 0.95
        # Adjusted close for 2021-05-31: 100.0 * 0.95 = 95.0
        self.assertAlmostEqual(back_adj["close"].iloc[0], 95.0)

    def test_unsupported_adjustment_conversions(self) -> None:

        """Attempting to reverse-adjust SPLIT_ADJUSTED back to UNADJUSTED raises UnsupportedAdjustmentConversion."""
        split_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            volume_adjustment=VolumeAdjustment.SPLIT_ADJUSTED,
        )
        with self.assertRaises(UnsupportedAdjustmentConversion):
            PriceAdjustmentEngine.adjust_ohlcv(
                self.raw_bars,
                self.split_actions,
                adjustment=PriceAdjustment.UNADJUSTED,
                source_semantics=split_semantics,
            )


class TestTotalReturnEngine(unittest.TestCase):
    def test_total_return_series_and_index(self) -> None:
        # 3-day series: Day 0: Close 100, Day 1: Close 96 with Rs 5 Div, Day 2: Close 98
        bars = pd.DataFrame(
            {
                "timestamp": pd.date_range("2023-01-02", periods=3, freq="D", tz="UTC"),
                "open": [100.0, 95.0, 96.0],
                "high": [102.0, 97.0, 99.0],
                "low": [98.0, 94.0, 95.0],
                "close": [100.0, 96.0, 98.0],
                "volume": [1000, 1200, 1100],
            }
        )
        div_actions = pd.DataFrame(
            [
                {
                    "action_id": "DIV_01",
                    "symbol": "TEST-EQ",
                    "ex_date": date(2023, 1, 3),
                    "action_type": "DIVIDEND",
                    "share_multiplier": 1.0,
                    "dividend_amount": 5.0,
                }
            ]
        )

        tr_series = TotalReturnEngine.calculate_total_return_series(bars, div_actions)
        # Day 1 return: (96 + 5 - 100) / 100 = 1.0% (0.01)
        self.assertAlmostEqual(tr_series.iloc[1], 0.01, places=5)
        # Day 2 return: (98 - 96) / 96 = 2.0833%
        self.assertAlmostEqual(tr_series.iloc[2], 2.0 / 96.0, places=5)

        tri_df = TotalReturnEngine.build_total_return_index(bars, div_actions, base_value=100.0)
        self.assertAlmostEqual(tri_df["total_return_index"].iloc[0], 100.0)
        self.assertAlmostEqual(tri_df["total_return_index"].iloc[1], 101.0)
        expected_tri_2 = 101.0 * (1.0 + 2.0 / 96.0)
        self.assertAlmostEqual(tri_df["total_return_index"].iloc[2], expected_tri_2, places=4)

    def test_dividend_followed_by_subsequent_split_share_basis(self) -> None:
        """A historical Rs 50 dividend occurring before a 10-for-1 split is scaled to Rs 5.0 on split-adjusted basis."""
        # 3-day series across split:
        # Day 0 (2022-07-20): Raw close = 1000, Div = 50
        # Day 1 (2022-07-27): Raw close = 1000
        # Day 2 (2022-07-28): 10-for-1 Split! Raw close = 105
        bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-20", tz="UTC"),
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [1000.0, 1000.0, 105.0],
                "high": [1010.0, 1010.0, 108.0],
                "low": [990.0, 990.0, 102.0],
                "close": [1000.0, 1000.0, 105.0],
                "volume": [10_000, 10_000, 100_000],
            }
        )

        actions = pd.DataFrame(
            [
                {
                    "action_id": "DIV_20220720",
                    "symbol": "TEST-EQ",
                    "ex_date": date(2022, 7, 20),
                    "action_type": "DIVIDEND",
                    "share_multiplier": 1.0,
                    "dividend_amount": 50.0,
                },
                {
                    "action_id": "SPLIT_20220728",
                    "symbol": "TEST-EQ",
                    "ex_date": date(2022, 7, 28),
                    "action_type": "SPLIT",
                    "share_multiplier": 10.0,
                    "dividend_amount": 0.0,
                },
            ]
        )

        # On split-adjusted basis:
        # Day 0 close = 100.0, Div = 50/10 = 5.0
        # Day 1 close = 100.0 (Return = (100 - 100)/100 = 0%)
        # Day 2 close = 105.0 (Return = (105 - 100)/100 = +5%)
        raw_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.UNADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
        )
        tr_series = TotalReturnEngine.calculate_total_return_series(
            bars,
            actions,
            source_semantics=raw_semantics,
        )
        self.assertAlmostEqual(tr_series.iloc[1], 0.0, places=4)
        self.assertAlmostEqual(tr_series.iloc[2], 0.05, places=4)


class TestDuckDBCorporateActionsPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.duckdb")
        self.db = DuckDBManager(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_upsert_and_retrieve_corporate_actions_with_action_id(self) -> None:
        records = [
            {
                "action_id": "TATASTEEL_20220728_SPLIT",
                "symbol": "TATASTEEL-EQ",
                "exchange": "NSE",
                "action_type": "SPLIT",
                "ex_date": date(2022, 7, 28),
                "share_multiplier": 10.0,
                "old_face_value": 10.0,
                "new_face_value": 1.0,
                "dividend_amount": 0.0,
                "purpose": "10-for-1 Stock Split",
                "source": "NSE",
            },
            {
                "action_id": "RELIANCE_20170907_BONUS",
                "symbol": "RELIANCE-EQ",
                "exchange": "NSE",
                "action_type": "BONUS",
                "ex_date": date(2017, 9, 7),
                "share_multiplier": 2.0,
                "bonus_new_shares": 1.0,
                "bonus_existing_shares": 1.0,
                "dividend_amount": 0.0,
                "purpose": "1-for-1 Bonus",
                "source": "NSE",
            },
        ]
        inserted = self.db.upsert_corporate_actions(records)
        self.assertEqual(inserted, 2)

        # Retrieve for TATASTEEL
        df = self.db.get_corporate_actions("TATASTEEL-EQ")
        self.assertEqual(len(df), 1)
        self.assertEqual(df["action_id"].iloc[0], "TATASTEEL_20220728_SPLIT")
        self.assertEqual(df["share_multiplier"].iloc[0], 10.0)

        # Retrieve all
        all_df = self.db.get_all_corporate_actions()
        self.assertEqual(len(all_df), 2)

    def test_repeated_import_idempotency(self) -> None:
        """Importing the exact same source event twice without explicit action_id produces deterministic identical ID and keeps count = 1."""
        record = {
            "symbol": "INFY-EQ",
            "exchange": "NSE",
            "action_type": "DIVIDEND",
            "ex_date": date(2023, 10, 26),
            "dividend_amount": 18.0,
            "share_multiplier": 1.0,
            "source": "NSE",
            "source_event_id": "NSE_DIV_INFY_20231026",
        }
        self.db.upsert_corporate_actions([record])
        df1 = self.db.get_corporate_actions("INFY-EQ")
        self.assertEqual(len(df1), 1)
        action_id_1 = df1["action_id"].iloc[0]

        self.db.upsert_corporate_actions([record])
        df2 = self.db.get_corporate_actions("INFY-EQ")
        self.assertEqual(len(df2), 1)
        action_id_2 = df2["action_id"].iloc[0]

        self.assertEqual(action_id_1, action_id_2)

    def test_migrate_legacy_corporate_actions_schema(self) -> None:
        """Migration from legacy natural PK table populates action_id, preserves rows, and allows same-day distributions."""
        legacy_temp = tempfile.TemporaryDirectory()
        db_path = Path(legacy_temp.name) / "legacy.duckdb"
        import duckdb
        conn = duckdb.connect(str(db_path))
        conn.execute("""
            CREATE TABLE corporate_actions (
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL DEFAULT 'NSE',
                action_type VARCHAR NOT NULL,
                ex_date DATE NOT NULL,
                share_multiplier DOUBLE NOT NULL DEFAULT 1.0,
                dividend_amount DOUBLE DEFAULT 0.0,
                source VARCHAR NOT NULL,
                recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, ex_date, action_type)
            );
            INSERT INTO corporate_actions (symbol, exchange, action_type, ex_date, share_multiplier, dividend_amount, source)
            VALUES ('TATASTEEL', 'NSE', 'SPLIT', '2022-07-28', 10.0, 0.0, 'NSE');
        """)
        conn.close()

        migrated_db = DuckDBManager(str(db_path))
        try:
            df = migrated_db.get_all_corporate_actions()
            self.assertEqual(len(df), 1)
            self.assertIsNotNone(df["action_id"].iloc[0])
            self.assertEqual(df["symbol"].iloc[0], "TATASTEEL")

            same_day_records = [
                {"symbol": "TATASTEEL", "action_type": "DIVIDEND", "ex_date": date(2023, 6, 15), "dividend_amount": 2.0, "source": "NSE", "source_event_id": "E1"},
                {"symbol": "TATASTEEL", "action_type": "DIVIDEND", "ex_date": date(2023, 6, 15), "dividend_amount": 3.0, "source": "NSE", "source_event_id": "E2"},
            ]
            migrated_db.upsert_corporate_actions(same_day_records)
            tata_df = migrated_db.get_corporate_actions("TATASTEEL")
            self.assertEqual(len(tata_df), 3)
        finally:
            migrated_db.close()
            legacy_temp.cleanup()


class TestHardeningAndEdgeCases(unittest.TestCase):
    def test_mixed_price_and_volume_source_basis(self) -> None:
        """Provider returns price=SPLIT_ADJUSTED, volume=UNADJUSTED; requesting SPLIT_ADJUSTED must no-op price and scale volume."""
        split_actions = pd.DataFrame(
            [{"action_id": "S1", "symbol": "TATASTEEL", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}]
        )
        provider_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                ],
                "open": [96.00, 97.50],
                "high": [98.20, 101.50],
                "low": [94.50, 97.00],
                "close": [95.94, 100.35],
                "volume": [5_000_000, 48_500_000],
            }
        )
        mixed_semantics = SourceBarSemantics(
            price_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            volume_adjustment=VolumeAdjustment.UNADJUSTED,
            provider_name="vendor_with_raw_volume",
        )
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(
            provider_bars,
            split_actions,
            adjustment=PriceAdjustment.SPLIT_ADJUSTED,
            source_semantics=mixed_semantics,
        )
        # Price is NO-OP
        self.assertAlmostEqual(adjusted["close"].iloc[0], 95.94, places=2)
        # Volume scaled: 5,000,000 * 10 = 50,000,000
        self.assertEqual(adjusted["volume"].iloc[0], 50_000_000)
        self.assertEqual(adjusted["volume"].iloc[1], 48_500_000)

    def test_ambiguous_detector_state_for_small_corporate_action(self) -> None:
        """For small corporate actions (1:3 bonus with R=1.333), overlapping tolerance regions classify as AMBIGUOUS."""
        small_bonus = pd.DataFrame(
            [{"action_id": "BONUS_1_3", "symbol": "BONUSCO", "ex_date": date(2023, 5, 10), "action_type": "BONUS", "share_multiplier": 1.333333}]
        )
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2023-05-09", tz="UTC"), pd.Timestamp("2023-05-10", tz="UTC")],
                "open": [100.0, 86.60],
                "high": [102.0, 87.00],
                "low": [98.0, 84.00],
                "close": [100.0, 86.60],
                "volume": [1000, 1500],
                "symbol": ["BONUSCO", "BONUSCO"],
            }
        )

        reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(bars, small_bonus)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["detection"], SourceBasisDetection.AMBIGUOUS)

        semantics = SourceSemanticsAdapter.infer_semantics(bars, small_bonus, declared_adjustment=PriceAdjustment.UNADJUSTED)
        self.assertEqual(semantics.price_adjustment, PriceAdjustment.UNADJUSTED)

    def test_same_day_multiple_dividend_aggregation(self) -> None:
        """Multiple dividends on same ex-date (regular Rs 2 + special Rs 3) aggregate into single factor 1 - (5/100) = 0.95."""
        multi_div_actions = pd.DataFrame(
            [
                {"action_id": "REG_DIV", "symbol": "DIVCO", "ex_date": date(2023, 8, 15), "action_type": "DIVIDEND", "dividend_amount": 2.0, "share_multiplier": 1.0},
                {"action_id": "SPEC_DIV", "symbol": "DIVCO", "ex_date": date(2023, 8, 15), "action_type": "DIVIDEND", "dividend_amount": 3.0, "share_multiplier": 1.0},
            ]
        )
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2023-08-14", tz="UTC"), pd.Timestamp("2023-08-15", tz="UTC")],
                "open": [100.0, 95.0],
                "high": [102.0, 96.0],
                "low": [98.0, 94.0],
                "close": [100.0, 95.0],
                "volume": [1000, 1200],
            }
        )
        factors = PriceAdjustmentEngine.calculate_dividend_factors(bars, multi_div_actions)
        self.assertAlmostEqual(factors.iloc[0], 0.95, places=5)
        self.assertAlmostEqual(factors.iloc[1], 1.00, places=5)

    def test_sequential_multi_action_properties(self) -> None:
        """Sequential splits/bonuses (2020: 2x, 2022: 2x, 2024: 10x) compound backwards and preserve P*V invariant."""
        seq_actions = pd.DataFrame(
            [
                {"action_id": "A1", "symbol": "SEQCO", "ex_date": date(2020, 6, 1), "action_type": "SPLIT", "share_multiplier": 2.0},
                {"action_id": "A2", "symbol": "SEQCO", "ex_date": date(2022, 6, 1), "action_type": "BONUS", "share_multiplier": 2.0},
                {"action_id": "A3", "symbol": "SEQCO", "ex_date": date(2024, 6, 1), "action_type": "SPLIT", "share_multiplier": 10.0},
            ]
        )
        bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2019-01-01", tz="UTC"),
                    pd.Timestamp("2021-01-01", tz="UTC"),
                    pd.Timestamp("2023-01-01", tz="UTC"),
                    pd.Timestamp("2025-01-01", tz="UTC"),
                ],
                "open": [4000.0, 2000.0, 1000.0, 100.0],
                "high": [4100.0, 2050.0, 1020.0, 105.0],
                "low": [3900.0, 1950.0, 980.0, 95.0],
                "close": [4000.0, 2000.0, 1000.0, 100.0],
                "volume": [1_000, 2_000, 4_000, 40_000],
            }
        )
        multipliers = PriceAdjustmentEngine.calculate_split_factors(bars["timestamp"], seq_actions)
        self.assertEqual(multipliers.iloc[0], 40.0)
        self.assertEqual(multipliers.iloc[1], 20.0)
        self.assertEqual(multipliers.iloc[2], 10.0)
        raw_semantics = SourceBarSemantics(price_adjustment=PriceAdjustment.UNADJUSTED, volume_adjustment=VolumeAdjustment.UNADJUSTED)
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(bars, seq_actions, adjustment=PriceAdjustment.SPLIT_ADJUSTED, source_semantics=raw_semantics)
        raw_turnover = bars["close"] * bars["volume"]
        adj_turnover = adjusted["close"] * adjusted["volume"]
        np.testing.assert_allclose(raw_turnover.values, adj_turnover.values, rtol=1e-5)


    def test_intraday_and_session_boundaries(self) -> None:
        """Friday 15:29 bar before Monday ex-date is adjusted; Monday 09:15 bar is unchanged."""
        intraday_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-22 09:15:00", tz="Asia/Kolkata"),
                    pd.Timestamp("2022-07-22 15:29:00", tz="Asia/Kolkata"),
                    pd.Timestamp("2022-07-25 09:15:00", tz="Asia/Kolkata"),
                ],
                "open": [1000.0, 1010.0, 100.0],
                "high": [1020.0, 1015.0, 105.0],
                "low": [990.0, 1005.0, 98.0],
                "close": [1010.0, 1012.0, 102.0],
                "volume": [1000, 2000, 20000],
            }
        )
        mon_split = pd.DataFrame(
            [{"action_id": "MON_SPLIT", "symbol": "MONCO", "ex_date": date(2022, 7, 25), "action_type": "SPLIT", "share_multiplier": 10.0}]
        )
        adjusted = PriceAdjustmentEngine.adjust_ohlcv(intraday_bars, mon_split, adjustment=PriceAdjustment.SPLIT_ADJUSTED)
        self.assertAlmostEqual(adjusted["close"].iloc[0], 101.0, places=2)
        self.assertAlmostEqual(adjusted["close"].iloc[1], 101.2, places=2)
        self.assertAlmostEqual(adjusted["close"].iloc[2], 102.0, places=2)


if __name__ == "__main__":
    unittest.main()

