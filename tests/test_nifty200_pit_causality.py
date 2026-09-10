from datetime import date

from tools.nifty200_pit.causality import derive_known_at


def test_same_day_date_only_event_requires_manual_review():
    known_at, basis, review = derive_known_at(date(2024, 1, 2), effective_date=date(2024, 1, 2))
    assert known_at is None
    assert basis == "DATE_ONLY_SAME_DAY_REVIEW"
    assert review == "same_day_effective_date_without_source_time"
