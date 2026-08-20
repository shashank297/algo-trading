"""Unit, property, and adversarial test suite for Point-in-Time Universe Manager."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import duckdb
import pandas as pd

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from trading_stack.domain import StrategyMetadata, StrategyScope
from trading_stack.strategy_library.cross_sectional import CrossSectionalRankingStrategy


class DummyMomentumStrategy(CrossSectionalRankingStrategy):
    @property
    def strategy_metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            name="TEST_MOMENTUM",
            version="1.0.0",
            family="MOMENTUM",
            scope=StrategyScope.CROSS_SECTIONAL,
            required_lookback=1,

        )


    def score_panel(self, panel: pd.DataFrame) -> pd.Series:
        return panel["close"]



class TestPointInTimeUniverse(unittest.TestCase):
    def setUp(self) -> None:
        self.con = duckdb.connect(":memory:")
        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        self.con.execute(schema_sql)

    def tearDown(self) -> None:
        self.con.close()

    def test_insert_and_query_exact_pit_constituents(self) -> None:
        """Constituents are retrieved strictly point-in-time without future lookahead or survivorship bias."""
        c1 = PointInTimeConstituent(
            universe_name="NIFTY50",
            symbol="STOCK_A",
            token="1001",
            instrument_id="NSE:STOCK_A:EQ",
            exchange="NSE",
            effective_from=date(2020, 1, 1),
            effective_until=date(2022, 3, 31),
            inclusion_reason="INITIAL",
            exclusion_reason="REBALANCED_OUT",
        )
        c2 = PointInTimeConstituent(
            universe_name="NIFTY50",
            symbol="STOCK_B",
            token="1002",
            instrument_id="NSE:STOCK_B:EQ",
            exchange="NSE",
            effective_from=date(2022, 3, 31),
            effective_until=None,
            inclusion_reason="REBALANCED_IN",
        )

        PointInTimeUniverseManager.insert_constituent(self.con, c1)
        PointInTimeUniverseManager.insert_constituent(self.con, c2)

        # 1. Query as of 2021-06-15 -> Only STOCK_A should be active
        syms_2021 = PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTY50", "2021-06-15")
        self.assertEqual(syms_2021, ["STOCK_A"])

        # 2. Query as of 2022-04-01 -> Only STOCK_B should be active
        syms_2022 = PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTY50", "2022-04-01")
        self.assertEqual(syms_2022, ["STOCK_B"])

    def test_overlapping_pit_membership_rejected(self) -> None:
        """Inserting overlapping intervals for the same constituent raises ValueError fail-closed."""
        c1 = PointInTimeConstituent(
            universe_name="NIFTY50",
            symbol="RELIANCE",
            token="2885",
            effective_from=date(2020, 1, 1),
            effective_until=date(2023, 1, 1),
        )
        PointInTimeUniverseManager.insert_constituent(self.con, c1)

        # Overlapping interval 2022-01-01 to 2024-01-01
        c_overlap = PointInTimeConstituent(
            universe_name="NIFTY50",
            symbol="RELIANCE",
            token="2885",
            effective_from=date(2022, 1, 1),
            effective_until=date(2024, 1, 1),
        )
        with self.assertRaises(ValueError) as ctx:
            PointInTimeUniverseManager.insert_constituent(self.con, c_overlap)
        self.assertIn("Overlapping PIT membership interval", str(ctx.exception))

    def test_effective_until_before_start_rejected(self) -> None:
        """Constructing constituent with effective_until <= effective_from raises ValueError immediately."""
        with self.assertRaises(ValueError):
            PointInTimeConstituent(
                universe_name="NIFTY50",
                symbol="BADCO",
                token="999",
                effective_from=date(2023, 1, 1),
                effective_until=date(2022, 1, 1),  # Inverted!
            )

    def test_membership_not_visible_before_known_from(self) -> None:
        """Constituent with future known_from (announcement date) is hidden when queried point-in-time as_of_knowledge."""
        # Member effective from 2023-01-01, but announced / known only on 2022-12-15
        c = PointInTimeConstituent(
            universe_name="NIFTY50",
            symbol="NEWCO",
            token="888",
            effective_from=date(2023, 1, 1),
            effective_until=None,
            known_from=date(2022, 12, 15),
        )
        PointInTimeUniverseManager.insert_constituent(self.con, c)

        # As of 2022-12-01 knowledge time, NEWCO should NOT be visible
        syms_before = PointInTimeUniverseManager.get_constituent_symbols(
            self.con, "NIFTY50", as_of="2023-01-02", as_of_knowledge="2022-12-01"
        )
        self.assertEqual(syms_before, [])

        # As of 2022-12-20 knowledge time, NEWCO is visible
        syms_after = PointInTimeUniverseManager.get_constituent_symbols(
            self.con, "NIFTY50", as_of="2023-01-02", as_of_knowledge="2022-12-20"
        )
        self.assertEqual(syms_after, ["NEWCO"])

    def test_cross_sectional_strategy_enforces_pit_universe_at_rebalance(self) -> None:
        """Cross-sectional strategy ranks only active PIT constituents on each rebalance date."""
        # Insert INFY (always active) and OLDCO (active only until 2021-06-30)
        c_infy = PointInTimeConstituent(universe_name="NIFTY200", symbol="INFY", token="1", effective_from=date(2020, 1, 1))
        c_oldco = PointInTimeConstituent(universe_name="NIFTY200", symbol="OLDCO", token="2", effective_from=date(2020, 1, 1), effective_until=date(2021, 6, 30))
        PointInTimeUniverseManager.insert_constituent(self.con, c_infy)
        PointInTimeUniverseManager.insert_constituent(self.con, c_oldco)

        panel = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2021-01-31", tz="UTC"), pd.Timestamp("2021-01-31", tz="UTC"),
                    pd.Timestamp("2021-07-31", tz="UTC"), pd.Timestamp("2021-07-31", tz="UTC"),
                ],
                "symbol": ["INFY", "OLDCO", "INFY", "OLDCO"],
                "close": [100.0, 100.0, 110.0, 120.0],
            }
        )

        strat = DummyMomentumStrategy(
            name="TEST_MOMENTUM",
            top_fraction=1.0,
            universe_name="NIFTY200",
            pit_db_conn=self.con,
        )

        signals = strat.generate_signals(panel)
        # On 2021-01-31: both INFY and OLDCO are active -> both selected
        sig_jan = signals[signals["timestamp"] == pd.Timestamp("2021-01-31", tz="UTC")]
        self.assertEqual(sorted(sig_jan["symbol"].tolist()), ["INFY", "OLDCO"])

        # On 2021-07-31: OLDCO was excluded on 2021-06-30 -> only INFY selected (OLDCO dropped via PIT filter)
        sig_jul = signals[signals["timestamp"] == pd.Timestamp("2021-07-31", tz="UTC")]
        self.assertEqual(sig_jul["symbol"].tolist(), ["INFY"])


if __name__ == "__main__":
    unittest.main()
