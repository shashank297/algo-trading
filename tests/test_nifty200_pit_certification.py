from datetime import date, datetime

from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.models import Action, CanonicalEvent, Confidence, ReviewStatus
from tools.nifty200_pit.validation import validate_campaign


def _event(number):
    key = f"SEC-{number:03d}"
    digest = f"{number:064x}"[-64:]
    return CanonicalEvent("NIFTY_200", key, None, key, None, date(2011, 7, 18), datetime(2011, 7, 19, 9, 15),
                          "DATE_ONLY_CONSERVATIVE_NEXT_SESSION", date(2011, 7, 19), Action.INITIAL_MEMBER, "launch",
                          "https://nse.example/launch.pdf", None, digest, 1, "A1", "PDF_TEXT", "v1", Confidence.CERTIFIED,
                          ReviewStatus.ACCEPTED, digest)


def test_exact_member_count_is_required():
    intervals = build_intervals([_event(number) for number in range(200)]).intervals
    report = validate_campaign(intervals, [_event(number) for number in range(200)], campaign_from=date(2012, 1, 2), campaign_to=date(2012, 1, 3), trading_days=[date(2012, 1, 2), date(2012, 1, 3)], calendar_provenance="test-calendar", calendar_certified=True)
    assert report.passed
    assert report.metrics["trading_days_checked"] == 2


def test_missing_membership_blocks_certification():
    intervals = build_intervals([_event(number) for number in range(199)]).intervals
    report = validate_campaign(intervals, [_event(number) for number in range(199)], campaign_from=date(2012, 1, 2), campaign_to=date(2012, 1, 2), trading_days=[date(2012, 1, 2)], calendar_provenance="test-calendar", calendar_certified=True)
    assert not report.passed
    assert any(reason.startswith("member_count") for reason in report.reasons)


def test_count_validation_is_not_evaluable_without_initial_anchor():
    intervals = build_intervals([_event(number) for number in range(1)]).intervals
    report = validate_campaign(
        intervals,
        [_event(0)],
        campaign_from=date(2012, 1, 2),
        campaign_to=date(2012, 1, 2),
        trading_days=[date(2012, 1, 2)],
        initial_anchor_established=False,
        calendar_provenance="test-calendar",
        calendar_certified=True,
    )

    assert not report.passed
    assert "initial_anchor_not_established" in report.reasons
    assert not any(reason.startswith("member_count:") for reason in report.reasons)
    assert report.metrics["count_validation_evaluable"] is False
    assert report.metrics["count_check_failures"] == 0


def test_empty_session_input_is_blocked():
    report = validate_campaign(
        [], [], campaign_from=date(2012, 1, 2), campaign_to=date(2012, 1, 3),
        trading_days=[], calendar_provenance="test-calendar", calendar_certified=True,
    )
    assert not report.passed
    assert "trading_days_empty" in report.reasons


def test_missing_calendar_provenance_is_blocked():
    report = validate_campaign(
        [], [], campaign_from=date(2012, 1, 2), campaign_to=date(2012, 1, 2),
        trading_days=[date(2012, 1, 2)], calendar_certified=False,
    )
    assert not report.passed
    assert "calendar_not_certified" in report.reasons
