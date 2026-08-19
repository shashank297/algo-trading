"""Unit and property tests for Point-in-Time Universe Manager."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import duckdb
import pandas as pd

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager


class TestPointInTimeUniverse(unittest.TestCase):
    def setUp(self) -> None:
        self.con = duckdb.connect(":memory:")
        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        self.con.execute(schema_sql)

    def tearDown(self) -> None:
        self.con.close()

    def test_insert_and_query_exact_pit_constituents(self) -> None:
        """Constituents are retrieved strictly point-in-time without future lookahead or survivorship bias."""
        # Stock A was in NIFTY50 from 2020-01-01 to 2022-03-31 (excluded on 2022-03-31)
        # Stock B was added to NIFTY50 on 2022-03-31 (active indefinitely)
        c1 = PointInTimeConstituent(
            universe_name="NIFTY50",
            symbol="STOCK_A",
            token="1001",
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

        # 3. Query before 2020 -> None active
        syms_2019 = PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTY50", "2019-12-31")
        self.assertEqual(syms_2019, [])

    def test_bulk_insert_dataframe(self) -> None:
        """Bulk insertion from pandas DataFrame correctly sets all fields and types."""
        df = pd.DataFrame(
            [
                {"universe_name": "NIFTY200", "symbol": "INFY", "token": "1594", "exchange": "NSE", "effective_from": "2015-01-01", "effective_until": None, "weight": 0.08},
                {"universe_name": "NIFTY200", "symbol": "TCS", "token": "11536", "exchange": "NSE", "effective_from": "2015-01-01", "effective_until": None, "weight": 0.06},
                {"universe_name": "NIFTY200", "symbol": "OLDCO", "token": "9999", "exchange": "NSE", "effective_from": "2015-01-01", "effective_until": "2018-06-30", "weight": 0.01},
            ]
        )
        count = PointInTimeUniverseManager.bulk_insert_constituents(self.con, df)
        self.assertEqual(count, 3)

        syms_2017 = PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTY200", "2017-01-01")
        self.assertEqual(sorted(syms_2017), ["INFY", "OLDCO", "TCS"])

        syms_2019 = PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTY200", "2019-01-01")
        self.assertEqual(sorted(syms_2019), ["INFY", "TCS"])

    def test_get_constituent_tokens(self) -> None:
        """Extracting tokens returns exact active token list."""
        c1 = PointInTimeConstituent(universe_name="NIFTY50", symbol="RELIANCE", token="2885", effective_from=date(2020, 1, 1))
        c2 = PointInTimeConstituent(universe_name="NIFTY50", symbol="TCS", token="11536", effective_from=date(2020, 1, 1))
        PointInTimeUniverseManager.insert_constituent(self.con, c1)
        PointInTimeUniverseManager.insert_constituent(self.con, c2)

        tokens = PointInTimeUniverseManager.get_constituent_tokens(self.con, "NIFTY50", date(2023, 1, 1))
        self.assertEqual(sorted(tokens), ["11536", "2885"])

    def test_multi_universe_isolation(self) -> None:
        """Constituents from different index universes are strictly segregated."""
        c_n50 = PointInTimeConstituent(universe_name="NIFTY50", symbol="RELIANCE", token="2885", effective_from=date(2020, 1, 1))
        c_mid = PointInTimeConstituent(universe_name="NIFTYMIDCAP50", symbol="POLYCAB", token="9590", effective_from=date(2020, 1, 1))
        PointInTimeUniverseManager.insert_constituent(self.con, c_n50)
        PointInTimeUniverseManager.insert_constituent(self.con, c_mid)

        self.assertEqual(PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTY50", "2023-01-01"), ["RELIANCE"])
        self.assertEqual(PointInTimeUniverseManager.get_constituent_symbols(self.con, "NIFTYMIDCAP50", "2023-01-01"), ["POLYCAB"])

    def test_universe_history_retrieval(self) -> None:
        """Retrieving full universe timeline returns complete historical audit records."""
        c = PointInTimeConstituent(
            universe_name="NIFTY50", symbol="TEST", token="123", effective_from=date(2021, 1, 1), effective_until=date(2022, 1, 1), inclusion_reason="IN", exclusion_reason="OUT"
        )
        PointInTimeUniverseManager.insert_constituent(self.con, c)
        hist_df = PointInTimeUniverseManager.get_universe_history(self.con, "NIFTY50")
        self.assertEqual(len(hist_df), 1)
        self.assertEqual(hist_df["symbol"].iloc[0], "TEST")
        self.assertEqual(hist_df["inclusion_reason"].iloc[0], "IN")
        self.assertEqual(hist_df["exclusion_reason"].iloc[0], "OUT")


if __name__ == "__main__":
    unittest.main()
