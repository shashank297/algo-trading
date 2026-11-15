"""Tests point-in-time membership immediately before and at the March 31 removal of AJANTPHARM.

Verifies:
1. Canonical interval representation [effective_from, effective_until) where
   effective_from = 2016-01-29 and effective_until = 2022-03-31.
2. Active membership immediately before removal on March 30, 2022 (member).
3. Inactive non-membership at removal on March 31, 2022 (non-member).
4. PointInTimeUniverseManager DuckDB integration on March 30 vs March 31, 2022.
5. trading_stack.datasets candle filtering (filter_frame_by_pit) on March 30 vs March 31, 2022.
6. Inclusive campaign scope: both March 30 and March 31 fall within [campaign_from, campaign_to],
   confirming AJANTPHARM member on March 30, non-member on March 31, and exactly 200 constituents
   on both sessions when paired with reconstituted replacements.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from tools.nifty200_pit.intervals import active_intervals, build_intervals
from tools.nifty200_pit.models import Action, CanonicalEvent, Confidence, ConstituentInterval, ReviewStatus
import trading_stack.datasets as datasets
from trading_stack.datasets import filter_frame_by_pit

IST = ZoneInfo("Asia/Kolkata")


def _make_canonical_event(
    action: Action,
    effective_date: date,
    symbol: str = "AJANTPHARM",
    instrument_id: str = "NSE-ISIN:INE031B01049",
    isin: str = "INE031B01049",
    announcement_date: date = date(2022, 2, 24),
    known_at: datetime = datetime(2022, 2, 25, 9, 15, tzinfo=IST),
) -> CanonicalEvent:
    digest = hashlib.sha256(f"{symbol}:{action.value}:{effective_date}".encode()).hexdigest()
    return CanonicalEvent(
        index_id="NIFTY_200",
        instrument_id=instrument_id,
        isin=isin,
        symbol=symbol,
        company_name="Ajanta Pharma Limited",
        announcement_date=announcement_date,
        known_at=known_at,
        known_at_basis="DATE_ONLY_CONSERVATIVE_NEXT_SESSION",
        effective_date=effective_date,
        action=action,
        reason="RECONSTITUTION",
        source_url="https://www.niftyindices.com/Press_Release/ind_prs24022022_1.pdf",
        archive_url=None,
        source_sha256=digest,
        source_page=14,
        source_tier="A1",
        extraction_method="PDF_TEXT",
        extractor_version="v1",
        confidence=Confidence.CERTIFIED,
        review_status=ReviewStatus.ACCEPTED,
        event_hash=digest,
        synthetic=False,
    )


def test_ajantpharm_active_intervals_boundary():
    """Verify half-open interval semantics [effective_from, effective_until).

    Member on March 30, 2022; non-member on March 31, 2022.
    """
    interval = ConstituentInterval(
        interval_id="ajantpharm-interval-1",
        index_id="NIFTY_200",
        instrument_id="NSE-ISIN:INE031B01049",
        symbol_at_entry="AJANTPHARM",
        isin_at_entry="INE031B01049",
        company_name="Ajanta Pharma Limited",
        effective_from=date(2016, 1, 29),
        effective_until=date(2022, 3, 31),
        known_from=date(2016, 1, 28),
        known_at=datetime(2016, 1, 29, 9, 15, tzinfo=IST),
        reason="ANCHOR",
        entry_event_hash="anchor-hash",
        exit_event_hash="drop-hash",
        confidence=Confidence.CERTIFIED,
        dataset_version="NIFTY200_PIT_V1",
        synthetic=False,
    )

    # Immediately before removal: March 30, 2022
    active_before = active_intervals([interval], date(2022, 3, 30))
    assert len(active_before) == 1
    assert active_before[0].symbol_at_entry == "AJANTPHARM"
    assert active_before[0].instrument_id == "NSE-ISIN:INE031B01049"

    # At removal: March 31, 2022
    active_at = active_intervals([interval], date(2022, 3, 31))
    assert len(active_at) == 0

    # Historical dates within the interval
    assert len(active_intervals([interval], date(2016, 1, 29))) == 1
    assert len(active_intervals([interval], date(2018, 6, 15))) == 1
    assert len(active_intervals([interval], date(2022, 2, 28))) == 1

    # Dates outside the interval
    assert len(active_intervals([interval], date(2016, 1, 28))) == 0
    assert len(active_intervals([interval], date(2022, 4, 1))) == 0


def test_ajantpharm_build_intervals_from_events():
    """Build interval from anchor ADD / INITIAL_MEMBER and March 31 DROP events."""
    add_ev = _make_canonical_event(
        action=Action.INITIAL_MEMBER,
        effective_date=date(2016, 1, 29),
        announcement_date=date(2016, 1, 28),
        known_at=datetime(2016, 1, 29, 9, 15, tzinfo=IST),
    )
    drop_ev = _make_canonical_event(
        action=Action.DROP,
        effective_date=date(2022, 3, 31),
        announcement_date=date(2022, 2, 24),
        known_at=datetime(2022, 2, 25, 9, 15, tzinfo=IST),
    )

    result = build_intervals([add_ev, drop_ev])
    assert not result.conflicts
    assert len(result.intervals) == 1

    iv = result.intervals[0]
    assert iv.instrument_id == "NSE-ISIN:INE031B01049"
    assert iv.symbol_at_entry == "AJANTPHARM"
    assert iv.effective_from == date(2016, 1, 29)
    assert iv.effective_until == date(2022, 3, 31)

    # Check active membership
    assert active_intervals([iv], date(2022, 3, 30)) == [iv]
    assert active_intervals([iv], date(2022, 3, 31)) == []


def test_point_in_time_universe_manager_ajantpharm_boundary():
    """Verify DuckDB index_constituents_pit membership lookups via PointInTimeUniverseManager."""
    con = duckdb.connect(":memory:")
    schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
    con.execute(schema_sql)

    constituent = PointInTimeConstituent(
        universe_name="NIFTY200",
        symbol="AJANTPHARM",
        token="1001",
        instrument_id="NSE-ISIN:INE031B01049",
        exchange="NSE",
        effective_from=date(2016, 1, 29),
        effective_until=date(2022, 3, 31),
        known_from=date(2022, 2, 24),
        known_at=datetime(2022, 2, 25, 9, 15, tzinfo=timezone.utc),
        inclusion_reason="ANCHOR",
        exclusion_reason="RECONSTITUTION_DROP",
        is_authoritative=True,
    )
    PointInTimeUniverseManager.insert_constituent(con, constituent)

    # 1. March 30, 2022 (Immediately before removal): Active member
    constituents_mar30 = PointInTimeUniverseManager.get_constituents(con, "NIFTY200", "2022-03-30")
    assert len(constituents_mar30) == 1
    assert constituents_mar30[0].symbol == "AJANTPHARM"
    assert constituents_mar30[0].instrument_id == "NSE-ISIN:INE031B01049"

    symbols_mar30 = PointInTimeUniverseManager.get_constituent_symbols(con, "NIFTY200", "2022-03-30")
    assert symbols_mar30 == ["AJANTPHARM"]

    # 2. March 31, 2022 (Removal day): Non-member
    constituents_mar31 = PointInTimeUniverseManager.get_constituents(con, "NIFTY200", "2022-03-31")
    assert len(constituents_mar31) == 0

    symbols_mar31 = PointInTimeUniverseManager.get_constituent_symbols(con, "NIFTY200", "2022-03-31")
    assert symbols_mar31 == []

    con.close()


def test_filter_frame_by_pit_ajantpharm_boundary():
    """Verify candle DataFrame filtering via trading_stack.datasets.filter_frame_by_pit."""
    pit_rows = [
        (
            "NSE-ISIN:INE031B01049",
            "AJANTPHARM",
            date(2016, 1, 29),
            date(2022, 3, 31),
            date(2022, 2, 24),
            pd.Timestamp("2022-02-25T09:15:00+05:30"),
        )
    ]

    frame = pd.DataFrame([
        # March 30 bars (member)
        {"timestamp": "2022-03-30T09:15:00+05:30", "symbol": "AJANTPHARM", "instrument_id": "NSE-ISIN:INE031B01049", "close": 1800.0},
        {"timestamp": "2022-03-30T15:30:00+05:30", "symbol": "AJANTPHARM", "instrument_id": "NSE-ISIN:INE031B01049", "close": 1810.0},
        # March 31 bars (non-member)
        {"timestamp": "2022-03-31T09:15:00+05:30", "symbol": "AJANTPHARM", "instrument_id": "NSE-ISIN:INE031B01049", "close": 1790.0},
        {"timestamp": "2022-03-31T15:30:00+05:30", "symbol": "AJANTPHARM", "instrument_id": "NSE-ISIN:INE031B01049", "close": 1795.0},
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
    assert pit_hash == "test_hash"
    assert list(filtered["timestamp"]) == [
        "2022-03-30T09:15:00+05:30",
        "2022-03-30T15:30:00+05:30",
    ]
    # Verify March 31 bars are excluded
    assert not any("2022-03-31" in ts for ts in filtered["timestamp"])


def test_inclusive_campaign_scope_and_replacement_conservation():
    """Verify inclusive campaign window [2016-01-29, 2022-03-31].

    Both March 30 and March 31 are in campaign scope.
    When AJANTPHARM exits on March 31, its replacement enters on March 31,
    maintaining exact constituent population across the boundary without overlap.
    """
    campaign_from = date(2016, 1, 29)
    campaign_to = date(2022, 3, 31)

    # In-bound check
    mar30 = date(2022, 3, 30)
    mar31 = date(2022, 3, 31)
    assert campaign_from <= mar30 <= campaign_to
    assert campaign_from <= mar31 <= campaign_to

    # Interval for outgoing stock (AJANTPHARM)
    ajanta_interval = ConstituentInterval(
        interval_id="iv-ajantpharm",
        index_id="NIFTY_200",
        instrument_id="NSE-ISIN:INE031B01049",
        symbol_at_entry="AJANTPHARM",
        isin_at_entry="INE031B01049",
        company_name="Ajanta Pharma Limited",
        effective_from=campaign_from,
        effective_until=mar31,  # Exits at start of March 31
        known_from=date(2022, 2, 24),
        known_at=datetime(2022, 2, 25, 9, 15, tzinfo=IST),
        reason="RECONSTITUTION_DROP",
        entry_event_hash="entry-hash-1",
        exit_event_hash="exit-hash-1",
        confidence=Confidence.CERTIFIED,
        dataset_version="NIFTY200_PIT_V1",
        synthetic=False,
    )

    # Interval for incoming replacement stock (e.g., ABB)
    replacement_interval = ConstituentInterval(
        interval_id="iv-abb",
        index_id="NIFTY_200",
        instrument_id="NSE-ISIN:INE117A01022",
        symbol_at_entry="ABB",
        isin_at_entry="INE117A01022",
        company_name="ABB India Limited",
        effective_from=mar31,  # Enters at start of March 31
        effective_until=None,
        known_from=date(2022, 2, 24),
        known_at=datetime(2022, 2, 25, 9, 15, tzinfo=IST),
        reason="RECONSTITUTION_ADD",
        entry_event_hash="entry-hash-2",
        exit_event_hash=None,
        confidence=Confidence.CERTIFIED,
        dataset_version="NIFTY200_PIT_V1",
        synthetic=False,
    )

    stable_intervals = [
        ConstituentInterval(
            interval_id=f"iv-stable-{number}",
            index_id="NIFTY_200",
            instrument_id=f"NSE-ISIN:STABLE{number:03d}",
            symbol_at_entry="TATAMTRDVR" if number == 0 else f"STABLE{number:03d}",
            isin_at_entry=f"STABLE{number:03d}",
            company_name="Stable constituent",
            effective_from=campaign_from,
            effective_until=None,
            known_from=campaign_from,
            known_at=datetime(2016, 1, 29, 9, 15, tzinfo=IST),
            reason="ANCHOR",
            entry_event_hash=f"stable-entry-{number}",
            exit_event_hash=None,
            confidence=Confidence.CERTIFIED,
            dataset_version="NIFTY200_PIT_V1",
            synthetic=False,
        )
        for number in range(199)
    ]
    universe_intervals = [*stable_intervals, ajanta_interval, replacement_interval]

    # March 30: AJANTPHARM is in, replacement is not yet in
    mar30_active = active_intervals(universe_intervals, mar30)
    assert len(mar30_active) == 200
    assert "AJANTPHARM" in {iv.symbol_at_entry for iv in mar30_active}

    # March 31: AJANTPHARM is out, replacement is in
    mar31_active = active_intervals(universe_intervals, mar31)
    assert len(mar31_active) == 200
    assert "ABB" in {iv.symbol_at_entry for iv in mar31_active}

    # Strict non-overlap: no double-counting or vacancy on the single reconstituted slot
    assert "AJANTPHARM" in {iv.symbol_at_entry for iv in mar30_active}
    assert "TATAMTRDVR" in {iv.symbol_at_entry for iv in mar30_active}
    assert "AJANTPHARM" not in {iv.symbol_at_entry for iv in mar31_active}
    assert "TATAMTRDVR" in {iv.symbol_at_entry for iv in mar31_active}
    assert "ABB" in {iv.symbol_at_entry for iv in mar31_active}
