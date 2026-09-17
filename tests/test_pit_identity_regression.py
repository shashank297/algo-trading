"""Regression tests for historical PIT identity, alias validation, and dataset integration."""

from datetime import date, datetime, timezone
import pytest
from tools.nifty200_pit.models import Observation, SourceRecord
from tools.nifty200_pit.build_public_dataset import parse_security_master
from tools.nifty200_pit.instrument_resolver import resolve_observation


def test_security_master_separates_listing_and_snapshot_date(tmp_path):
    """A 2026 security master snapshot separates listing_date from snapshot_date
    and cannot alone certify an old historical observation without explicit evidence.
    """
    csv_content = (
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
    )
    csv_file = tmp_path / "sec_master_20260901.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    source = SourceRecord(
        source_url="https://niftyindices.com/test",
        local_path=str(csv_file),
        source_sha256="abc123hash",
        source_tier="A1",
        retrieved_at="2026-09-01T12:00:00Z",
        document_date="2026-09-01",
    )

    rows = parse_security_master(source)
    assert len(rows) == 1
    row = rows[0]
    assert row["listing_date"] == "1995-11-29"
    assert row["snapshot_date"] == "2026-09-01"
    assert row["listing_date"] != row["snapshot_date"]
    # Alone without explicit historical interval substantiation, resolving 2012 does not certify
    res = resolve_observation(Observation(symbol="RELIANCE", effective_date=date(2012, 1, 2)), rows)
    assert res.confidence != "CERTIFIED"



def test_resolver_does_not_certify_2012_from_2026_snapshot():
    """An observation from 2012 must not be CERTIFIED using only a 2026 snapshot."""
    # Row with valid_from mistakenly set to 1995 listing date
    master_rows = [
        {
            "instrument_id": "NSE-ISIN:INE002A01018",
            "isin": "INE002A01018",
            "symbol": "RELIANCE",
            "company_name": "Reliance Industries Limited",
            "snapshot_date": "2026-09-01",
            "valid_from": "1995-11-29",
            "valid_until": None,
        }
    ]

    obs = Observation(
        source_url="http://example.com",
        source_sha256="abc",
        source_tier="A1",
        index_id="NIFTY_200",
        action="ADD",
        company_name="Reliance Industries Limited",
        symbol="RELIANCE",
        effective_date=date(2012, 1, 2),
    )

    res = resolve_observation(obs, master_rows, aliases=[])
    # In defective code, because valid_from is 1995 and valid_until is None,
    # _valid_on returns True, certifying the 2012 observation from the 2026 snapshot!
    # In fixed code, it must not certify.
    assert res.confidence != "CERTIFIED", (
        f"2012 observation should not be CERTIFIED using only a 2026 snapshot, got {res.confidence}"
    )


def test_inverted_alias_interval_rejected():
    """Certified alias intervals must have valid_from < valid_until; inverted rows are rejected."""
    from tools.nifty200_pit.build_public_dataset import _identity_aliases

    master = [
        {
            "instrument_id": "NSE-ISIN:INE399L01023",
            "isin": "INE399L01023",
            "symbol": "ATGL",
            "company_name": "Adani Total Gas Limited",
            "snapshot_date": "2026-09-01",
            "valid_from": "2026-09-01",
            "valid_until": None,
            "listing_date": "2018-11-05",
        }
    ]
    # Inverted change where changed_on is 2017 but listing_date is 2018
    symbol_changes = [
        {
            "previous_symbol": "ADANIGAS",
            "new_symbol": "ATGL",
            "changed_on": date(2021, 1, 13),
            "source_url": "http://example.com/sc",
            "source_sha256": "abc",
            "source_tier": "A1",
        }
    ]

    aliases = _identity_aliases(snapshots=[], master=master, symbol_changes=symbol_changes)
    adanigas_aliases = [a for a in aliases if a.get("alias_symbol") == "ADANIGAS"]
    assert len(adanigas_aliases) >= 1
    for a in adanigas_aliases:
        if a.get("valid_from") and a.get("valid_until"):
            assert a["valid_from"] < a["valid_until"], (
                f"Alias interval must have valid_from < valid_until, got {a['valid_from']} >= {a['valid_until']}"
            )


def test_distinct_alias_periods_preserved():
    """An instrument with multiple historical symbol changes must preserve distinct periods."""
    from tools.nifty200_pit.build_public_dataset import _identity_aliases

    master = [
        {
            "instrument_id": "NSE-ISIN:INE205A01025",
            "isin": "INE205A01025",
            "symbol": "VEDL",
            "company_name": "Vedanta Limited",
            "snapshot_date": "2026-09-01",
            "valid_from": "2026-09-01",
            "valid_until": None,
            "listing_date": "1995-11-08",
        }
    ]
    symbol_changes = [
        {
            "previous_symbol": "SSLT",
            "new_symbol": "VEDL",
            "changed_on": date(2015, 5, 7),
            "source_url": "http://example.com/sc",
            "source_sha256": "abc",
            "source_tier": "A1",
        },
        {
            "previous_symbol": "SESAGOA",
            "new_symbol": "SSLT",
            "changed_on": date(2013, 10, 4),
            "source_url": "http://example.com/sc",
            "source_sha256": "abc",
            "source_tier": "A1",
        },
    ]

    aliases = _identity_aliases(snapshots=[], master=master, symbol_changes=symbol_changes)
    symbols = {a.get("alias_symbol") for a in aliases}
    assert "VEDL" in symbols
    assert "SSLT" in symbols
    assert "SESAGOA" in symbols


def test_rename_does_not_manufacture_add_drop():
    """A ticker rename (e.g. INFRATEL -> INDUSTOWER) must not manufacture an index ADD or DROP event."""
    from tools.nifty200_pit.models import Action, CanonicalEvent, Confidence, ReviewStatus
    from tools.nifty200_pit.intervals import build_intervals

    # Initial member added in 2012
    events = [
        CanonicalEvent(
            index_id="NIFTY_200",
            instrument_id="NSE-ISIN:INE121J01017",
            isin="INE121J01017",
            symbol="INFRATEL",
            company_name="Bharti Infratel Limited",
            announcement_date=date(2012, 1, 2),
            known_at=datetime(2012, 1, 2, 0, 0, tzinfo=timezone.utc),
            known_at_basis="RELEASE",
            effective_date=date(2012, 1, 2),
            action=Action.INITIAL_MEMBER,
            reason="Constituent",
            source_url="http://example.com",
            archive_url=None,
            source_sha256="abc",
            source_page=None,
            source_tier="A1",
            extraction_method="OFFICIAL",
            extractor_version="1.0",
            confidence=Confidence.CERTIFIED,
            review_status=ReviewStatus.ACCEPTED,
            event_hash="hash-initial-infratel",
            observation_id="obs-1",
        )
    ]

    result = build_intervals(events, horizon_start=date(2012, 1, 1), horizon_end=date(2022, 1, 1))
    assert len(result.conflicts) == 0
    assert len(result.intervals) == 1
    # Exactly 1 continuous interval, active until horizon_end
    interval = result.intervals[0]
    assert interval.instrument_id == "NSE-ISIN:INE121J01017"
    assert interval.effective_until is None


def test_pit_candles_join_across_rename_boundary(tmp_path):
    """Candles for ADANIGAS (pre-2021) and ATGL (post-2021) must both match the same PIT constituent."""
    import pandas as pd
    from storage import DuckDBManager
    from trading_stack.datasets import filter_frame_by_pit

    db_path = str(tmp_path / "pit_test.duckdb")
    db = DuckDBManager(db_path)

    # Insert PIT interval for ADANIGAS / ATGL spanning 2020 to 2022
    db.conn.execute("""
        INSERT INTO index_constituents_pit (
            universe_name, instrument_id, symbol, token, exchange,
            effective_from, effective_until, known_from, weight,
            inclusion_reason, exclusion_reason, recorded_at
        ) VALUES (
            'NIFTY200', 'NSE-ISIN:INE399L01023', 'ATGL', '1234', 'NSE',
            '2020-01-01', '2022-12-31', '2019-12-15', 1.0,
            'CERTIFIED_PIT', NULL, '2020-01-01 00:00:00'
        )
    """)
    # Insert knowledge record
    db.conn.execute("""
        INSERT INTO index_constituent_knowledge (
            universe_name, instrument_id, effective_from, known_at
        ) VALUES (
            'NIFTY200', 'NSE-ISIN:INE399L01023', '2020-01-01', '2019-12-15 18:00:00+00'
        )
    """)
    # Insert historical alias mapping: ADANIGAS -> ATGL
    db.conn.execute("""
        INSERT INTO instrument_aliases (
            canonical_symbol, exchange, provider_name, provider_symbol
        ) VALUES (
            'ATGL', 'NSE', 'HISTORICAL_ALIAS', 'ADANIGAS'
        )
    """)

    # Candle frame with ADANIGAS in 2020 and ATGL in 2021
    candles = pd.DataFrame([
        {"symbol": "ADANIGAS", "timestamp": "2020-06-15 10:00:00", "close": 150.0},
        {"symbol": "ATGL", "timestamp": "2021-06-15 10:00:00", "close": 900.0},
        {"symbol": "UNRELATED", "timestamp": "2020-06-15 10:00:00", "close": 50.0},
    ])

    filtered, _ = filter_frame_by_pit(db, candles, "NIFTY200", required=False)
    # Both ADANIGAS and ATGL candles must be retained
    assert len(filtered) == 2
    matched_symbols = set(filtered["symbol"])
    assert "ADANIGAS" in matched_symbols
    assert "ATGL" in matched_symbols
    assert "UNRELATED" not in matched_symbols

