"""Tests point-in-time membership, invariant ISIN identity, and rights separation for BHARTIARTL.

Verifies:
1. Canonical interval representation [effective_from, effective_until) where
   effective_from = 2016-01-29 and effective_until is None (unbroken constituent).
2. Continuous active membership throughout the entire Campaign 1 window (2016-01-29 to 2022-03-31).
3. Presence across all 75 monthly checkpoints in bounded package with:
   - symbol = 'BHARTIARTL'
   - isin = 'INE397D01024'
   - series = 'EQ'
   - confidence = 'CERTIFIED'
   - review_status = 'ACCEPTED'
4. Strict separation of 2021 Rights Issue partly-paid equity shares:
   - ISIN: IN9397D01014
   - Symbol: AIRTELPP
   - Series: E1
   - Zero presence in NIFTY 200 index constituents or intervals.
5. Integration with PointInTimeUniverseManager and datasets filter_frame_by_pit.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import pytest

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from tools.nifty200_pit.intervals import active_intervals
from tools.nifty200_pit.models import Confidence, ConstituentInterval
import trading_stack.datasets as datasets
from trading_stack.datasets import filter_frame_by_pit

IST = ZoneInfo("Asia/Kolkata")


def test_bhartiartl_active_interval_invariance():
    """Verify BHARTIARTL is active on all campaign dates and invariant across 2016-2022."""
    interval = ConstituentInterval(
        interval_id="iv-bhartiartl-primary",
        index_id="NIFTY_200",
        instrument_id="NSE-ISIN:INE397D01024",
        symbol_at_entry="BHARTIARTL",
        isin_at_entry="INE397D01024",
        company_name="Bharti Airtel Limited",
        effective_from=date(2016, 1, 29),
        effective_until=None,
        known_from=date(2016, 1, 28),
        known_at=datetime(2016, 1, 29, 9, 15, tzinfo=IST),
        reason="ANCHOR",
        entry_event_hash="anchor-hash-bharti",
        exit_event_hash=None,
        confidence=Confidence.CERTIFIED,
        dataset_version="NIFTY200_PIT_V1",
        synthetic=False,
    )

    # Active on opening anchor date
    active_open = active_intervals([interval], date(2016, 1, 29))
    assert len(active_open) == 1
    assert active_open[0].symbol_at_entry == "BHARTIARTL"
    assert active_open[0].isin_at_entry == "INE397D01024"

    # Active on key intermediate dates
    assert len(active_intervals([interval], date(2018, 6, 15))) == 1
    assert len(active_intervals([interval], date(2020, 3, 23))) == 1
    assert len(active_intervals([interval], date(2021, 10, 29))) == 1

    # Active on terminal date
    active_terminal = active_intervals([interval], date(2022, 3, 31))
    assert len(active_terminal) == 1
    assert active_terminal[0].symbol_at_entry == "BHARTIARTL"

    # Pre-campaign date is not active
    assert len(active_intervals([interval], date(2016, 1, 28))) == 0


def test_bhartiartl_75_checkpoints_in_bounded_package():
    """Verify BHARTIARTL presence in all 75 checkpoints of the clean bounded package."""
    pkg_dir = Path("artifacts/campaign1_pit_m5_clean_a")
    checkpoints_path = pkg_dir / "checkpoints.json"
    if not checkpoints_path.exists():
        pytest.skip("Clean bounded package artifacts not found")

    with open(checkpoints_path, "r", encoding="utf-8") as f:
        checkpoints = json.load(f)

    assert len(checkpoints) == 75, f"Expected 75 checkpoints, found {len(checkpoints)}"

    for cp in checkpoints:
        cp_date = cp["date"]
        matches = [m for m in cp["members"] if m.get("symbol") == "BHARTIARTL"]
        assert len(matches) == 1, f"BHARTIARTL missing or duplicate on {cp_date}"
        m = matches[0]
        assert m["isin"] == "INE397D01024"
        assert m["instrument_id"] == "NSE-ISIN:INE397D01024"
        assert m["confidence"] == "CERTIFIED"
        assert m["review_status"] == "ACCEPTED"


def test_bhartiartl_rights_partly_paid_separation():
    """Verify 2021 rights partly paid shares (IN9397D01014) are excluded from index constituents."""
    pkg_dir = Path("artifacts/campaign1_pit_m5_clean_a")
    if not pkg_dir.exists():
        pytest.skip("Package dir not found")

    with open(pkg_dir / "checkpoints.json", "r", encoding="utf-8") as f:
        checkpoints = json.load(f)

    for cp in checkpoints:
        isins = {m.get("isin") for m in cp["members"]}
        symbols = {m.get("symbol") for m in cp["members"]}
        assert "IN9397D01014" not in isins, f"Partly paid ISIN leaked into checkpoint {cp['date']}"
        assert "AIRTELPP" not in symbols, f"Partly paid symbol leaked into checkpoint {cp['date']}"
        assert "BHARTIARTLPP" not in symbols, f"Partly paid symbol leaked into checkpoint {cp['date']}"

    # Also check intervals.json
    with open(pkg_dir / "intervals.json", "r", encoding="utf-8") as f:
        intervals = json.load(f)

    interval_isins = {iv.get("isin_at_entry") for iv in intervals}
    assert "IN9397D01014" not in interval_isins


def test_bhartiartl_pit_universe_manager_integration():
    """Verify PointInTimeUniverseManager returns BHARTIARTL across opening and closing dates."""
    con = duckdb.connect(":memory:")
    schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
    con.execute(schema_sql)

    constituent = PointInTimeConstituent(
        universe_name="NIFTY200",
        symbol="BHARTIARTL",
        token="10604",
        instrument_id="NSE-ISIN:INE397D01024",
        exchange="NSE",
        effective_from=date(2016, 1, 29),
        effective_until=None,
        known_from=date(2016, 1, 28),
        known_at=datetime(2016, 1, 29, 9, 15, tzinfo=timezone.utc),
        inclusion_reason="ANCHOR",
        exclusion_reason=None,
        is_authoritative=True,
    )
    PointInTimeUniverseManager.insert_constituent(con, constituent)

    # 1. Opening date 2016-01-29: Active member
    constituents_open = PointInTimeUniverseManager.get_constituents(con, "NIFTY200", "2016-01-29")
    assert len(constituents_open) == 1
    assert constituents_open[0].symbol == "BHARTIARTL"
    assert constituents_open[0].instrument_id == "NSE-ISIN:INE397D01024"

    # 2. Terminal date 2022-03-31: Active member
    constituents_term = PointInTimeUniverseManager.get_constituents(con, "NIFTY200", "2022-03-31")
    assert len(constituents_term) == 1
    assert constituents_term[0].symbol == "BHARTIARTL"

    # 3. Before campaign open 2016-01-28: Non-member
    constituents_pre = PointInTimeUniverseManager.get_constituents(con, "NIFTY200", "2016-01-28")
    assert len(constituents_pre) == 0

    con.close()


def test_bhartiartl_filter_frame_by_pit():
    """Verify candle DataFrame filtering preserves BHARTIARTL and excludes non-member instruments."""
    pit_rows = [
        (
            "NSE-ISIN:INE397D01024",
            "BHARTIARTL",
            date(2016, 1, 29),
            None,
            date(2016, 1, 28),
            pd.Timestamp("2016-01-29T09:15:00+05:30"),
        )
    ]

    frame = pd.DataFrame([
        # BHARTIARTL on 2021-11-30 (member)
        {"timestamp": "2021-11-30T15:30:00+05:30", "symbol": "BHARTIARTL", "instrument_id": "NSE-ISIN:INE397D01024", "close": 728.25},
        # AIRTELPP on 2021-11-30 (non-member)
        {"timestamp": "2021-11-30T15:30:00+05:30", "symbol": "AIRTELPP", "instrument_id": "NSE-ISIN:IN9397D01014", "close": 390.80},
        # BHARTIARTL on 2022-03-31 (member)
        {"timestamp": "2022-03-31T15:30:00+05:30", "symbol": "BHARTIARTL", "instrument_id": "NSE-ISIN:INE397D01024", "close": 754.95},
        # AIRTELPP on 2022-03-31 (non-member)
        {"timestamp": "2022-03-31T15:30:00+05:30", "symbol": "AIRTELPP", "instrument_id": "NSE-ISIN:IN9397D01014", "close": 395.95},
    ])

    with patch.object(datasets, "_pit_rows", return_value=pit_rows), patch.object(
        datasets, "_pit_alias_rows", return_value=[]
    ), patch.object(
        datasets, "pit_evidence_hash", return_value="test_hash"
    ):
        filtered, pit_hash = filter_frame_by_pit(
            db=None,
            frame=frame,
            universe_name="NIFTY_200",
            timezone_name="Asia/Kolkata",
            required=False,
        )

    assert len(filtered) == 2
    assert set(filtered["symbol"]) == {"BHARTIARTL"}
    assert "AIRTELPP" not in set(filtered["symbol"])
