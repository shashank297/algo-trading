from datetime import date, time
from itertools import permutations
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

import trading_stack.datasets as datasets
from trading_stack.calendars import SessionOverride, build_nse_calendar
from tools.import_nifty200_pit import insert_aliases, load_aliases
from tools.nifty200_pit.build_public_dataset import _identity_aliases
from tools.nifty200_pit.manifest import write_table


def _pit_rows():
    return [
        (
            "ID-C", "OTHER", date(2020, 1, 1), None, date(2020, 1, 1),
            pd.Timestamp("2019-12-31T00:00:00Z"),
        )
    ]


def _frame(timestamp: str = "2025-01-02T10:00:00+05:30") -> pd.DataFrame:
    return pd.DataFrame([{"timestamp": timestamp, "symbol": "SAME"}])


def test_alias_identity_is_invariant_to_row_order_and_sticky_when_ambiguous():
    aliases = [
        ("ID-A", "SAME", date(2020, 1, 1), None, date(2020, 1, 1), None, "EXPLICIT", True, "a" * 64),
        ("ID-B", "SAME", date(2020, 1, 1), None, date(2020, 1, 1), None, "EXPLICIT", True, "b" * 64),
        ("ID-C", "SAME", date(2020, 1, 1), None, date(2020, 1, 1), None, "EXPLICIT", True, "c" * 64),
    ]

    for ordering in permutations(aliases):
        with patch.object(datasets, "_pit_rows", return_value=_pit_rows()), patch.object(
            datasets, "_pit_alias_rows", return_value=list(ordering)
        ), patch.object(
            datasets, "pit_evidence_hash", return_value="hash"
        ):
            eligible, _ = datasets._pit_eligibility_mask(
                None, _frame(), "NIFTY_200", timezone_name=ZoneInfo("Asia/Kolkata"),
                required=True,
            )
        assert not bool(eligible.iloc[0])


def test_duplicate_alias_evidence_for_one_instrument_remains_eligible():
    aliases = [
        ("ID-C", "SAME", date(2020, 1, 1), None, date(2020, 1, 1), None, "EXPLICIT", True, "a" * 64),
        ("ID-C", "SAME", date(2021, 1, 1), None, date(2021, 1, 1), None, "EXPLICIT", True, "b" * 64),
    ]
    with patch.object(datasets, "_pit_rows", return_value=_pit_rows()), patch.object(
        datasets, "_pit_alias_rows", return_value=aliases
    ), patch.object(
        datasets, "pit_evidence_hash", return_value="hash"
    ):
        eligible, _ = datasets._pit_eligibility_mask(
            None, _frame(), "NIFTY_200", timezone_name=ZoneInfo("Asia/Kolkata"),
            required=True,
        )
    assert bool(eligible.iloc[0])


def test_current_snapshot_alias_cannot_backdate_into_earlier_bars():
    alias = (
        "ID-C", "SAME", date(2012, 1, 1), None, date(2026, 9, 9), None,
        "CURRENT_SNAPSHOT_ONLY", False, "a" * 64,
    )
    with patch.object(datasets, "_pit_rows", return_value=_pit_rows()), patch.object(
        datasets, "_pit_alias_rows", return_value=[alias]
    ), patch.object(
        datasets, "pit_evidence_hash", return_value="hash"
    ):
        before_snapshot, _ = datasets._pit_eligibility_mask(
            None, _frame("2025-01-02T10:00:00+05:30"), "NIFTY_200",
            timezone_name=ZoneInfo("Asia/Kolkata"), required=True,
        )
        after_snapshot, _ = datasets._pit_eligibility_mask(
            None, _frame("2026-09-09T10:00:00+05:30"), "NIFTY_200",
            timezone_name=ZoneInfo("Asia/Kolkata"), required=True,
        )
    assert not bool(before_snapshot.iloc[0])
    assert bool(after_snapshot.iloc[0])


def test_temporal_alias_survives_export_import_and_dataset_join(tmp_path):
    exported = _identity_aliases(
        snapshots=[{
            "symbol": "SAME",
            "snapshot_date": "2026-09-09",
            "company_name": "Same Industries",
            "source_url": "https://example.test/nifty200-2026-09-09.csv",
            "source_sha256": "a" * 64,
        }],
        master=[{
            "instrument_id": "ID-C",
            "isin": "INE000000000",
            "symbol": "SAME",
            "company_name": "Same Industries",
            "listing_date": "2012-01-01",
            "snapshot_date": "2026-09-09",
            "observed_snapshot_date": "2026-09-09",
            "valid_from": "2012-01-01",
            "valid_until": None,
            "identity_event_type": "CURRENT_SECURITY_MASTER",
            "source_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            "source_sha256": "b" * 64,
            "source_tier": "A1",
            "confidence": "CERTIFIED",
            "has_explicit_historical_interval": False,
        }],
    )
    alias_path = tmp_path / "instrument_aliases.parquet"
    write_table(alias_path, exported)
    aliases = load_aliases(alias_path)
    assert len(aliases) == 1
    assert aliases[0]["validity_basis"] == "CURRENT_SNAPSHOT_ONLY"
    assert str(aliases[0]["valid_from"])[:10] == "2026-09-09"

    import duckdb

    connection = duckdb.connect(":memory:")
    try:
        assert insert_aliases(connection, aliases) == 1
        db = SimpleNamespace(conn=connection)
        pit_rows = [
            (
                "ID-C", "LEGACY", date(2012, 1, 1), None, date(2012, 1, 1),
                pd.Timestamp("2012-01-01T00:00:00Z"),
            )
        ]
        before = _frame("2025-01-02T10:00:00+05:30")
        after = _frame("2026-09-09T10:00:00+05:30")
        with patch.object(datasets, "_pit_rows", return_value=pit_rows), patch.object(
            datasets, "pit_evidence_hash", return_value="hash"
        ):
            before_eligible, _ = datasets._pit_eligibility_mask(
                db, before, "NIFTY_200", timezone_name=ZoneInfo("Asia/Kolkata"), required=True
            )
            after_eligible, _ = datasets._pit_eligibility_mask(
                db, after, "NIFTY_200", timezone_name=ZoneInfo("Asia/Kolkata"), required=True
            )
        assert not bool(before_eligible.iloc[0])
        assert bool(after_eligible.iloc[0])
    finally:
        connection.close()


class _StubNSEProvider:
    def schedule(self, *, start_date, end_date):
        return pd.DataFrame(
            {
                "market_open": [pd.Timestamp("2024-01-01T03:45:00Z"), pd.Timestamp("2024-01-03T03:45:00Z")],
                "market_close": [pd.Timestamp("2024-01-01T10:00:00Z"), pd.Timestamp("2024-01-03T10:00:00Z")],
            },
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")]),
        )


def test_nse_calendar_overrides_are_consistent_across_all_apis():
    calendar = build_nse_calendar(overrides=(
        SessionOverride(date(2024, 1, 1), "CLOSED", "exchange closure"),
        SessionOverride(date(2024, 1, 2), "SPECIAL_SESSION", "special session", start_time=time(10, 0), end_time=time(12, 0)),
    ))
    calendar.provider = _StubNSEProvider()

    assert not calendar.is_trading_day(date(2024, 1, 1))
    assert calendar.is_trading_day(date(2024, 1, 2))
    assert calendar.iter_trading_days(date(2024, 1, 1), date(2024, 1, 3)) == [date(2024, 1, 2), date(2024, 1, 3)]
    bounds = calendar.session_bounds(date(2024, 1, 2))
    assert bounds.start.hour == 10 and bounds.end.hour == 12
    expected = calendar.expected_minute_index(date(2024, 1, 1), date(2024, 1, 3))
    assert expected[0].hour == 10
    validation = calendar.validate_bars(
        pd.Series(["2024-01-02T04:30:00Z", "2024-01-03T03:45:00Z"]), "1d"
    )
    assert validation.valid
