from datetime import date

from tools.nifty200_pit.causality import derive_known_at


def test_same_day_date_only_event_requires_manual_review():
    known_at, basis, review = derive_known_at(date(2024, 1, 2), effective_date=date(2024, 1, 2))
    assert known_at is None
    assert basis == "DATE_ONLY_SAME_DAY_REVIEW"
    assert review == "same_day_effective_date_without_source_time"


def test_known_at_uses_special_session_and_explicit_exchange_closure():
    from tools.nifty200_pit.causality import next_trading_session_open
    from trading_stack.calendars import SessionOverride, build_nse_calendar

    calendar = build_nse_calendar(overrides=(
        SessionOverride(date(2024, 1, 20), "SPECIAL_SESSION", "test official live session"),
        SessionOverride(date(2024, 1, 22), "CLOSED", "test official closure"),
    ))
    assert next_trading_session_open(date(2024, 1, 19), calendar=calendar).date() == date(2024, 1, 20)
    assert next_trading_session_open(date(2024, 1, 20), calendar=calendar).date() == date(2024, 1, 23)
