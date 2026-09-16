from datetime import date, datetime, time

import pandas as pd

from trading_stack.calendars import SessionOverride, build_nse_calendar


def test_closed_override_removes_minutes_from_provider_session():
    day = date(2024, 1, 22)
    calendar = build_nse_calendar(overrides=(SessionOverride(day, "CLOSED", "NSE CMTR60338"),))
    assert not calendar.is_trading_day(day)
    assert calendar.iter_trading_days(day, day) == []
    assert calendar.expected_minute_index(day, day).empty


def test_special_session_interruptions_agree_across_calendar_apis():
    day = date(2024, 3, 2)
    calendar = build_nse_calendar(overrides=(
        SessionOverride(day, "SPECIAL_SESSION", "NSE MSD60677", time(9, 15), time(12, 30)),
        SessionOverride(day, "INTERRUPTION", "NSE MSD60677", time(10), time(11, 30)),
    ))
    pause = datetime.fromisoformat("2024-03-02T10:30:00+05:30")
    assert not calendar.is_session_open(pause)
    assert not calendar.is_session_open(datetime.fromisoformat("2024-03-02T10:00:00+05:30"))
    assert calendar.is_session_open(datetime.fromisoformat("2024-03-02T11:30:00+05:30"))
    assert len(calendar.expected_minute_index(day, day)) == 105
    assert not calendar.validate_bars(pd.Series([pause]), "1m").valid


def test_special_hours_override_provider_hours_on_an_existing_weekday():
    day = date(2024, 1, 23)
    # Synthetic unit-test schedule, not historical evidence.
    calendar = build_nse_calendar(overrides=(
        SessionOverride(day, "SPECIAL_SESSION", "test-only shortened hours", time(18), time(19)),
    ))
    minutes = calendar.expected_minute_index(day, day)
    assert len(minutes) == 60
    assert minutes[0].hour == 18
    assert not calendar.is_session_open(datetime.fromisoformat("2024-01-23T10:00:00+05:30"))
