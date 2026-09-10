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
    report = validate_campaign(intervals, [_event(number) for number in range(200)], campaign_from=date(2012, 1, 2), campaign_to=date(2012, 1, 3), trading_days=[date(2012, 1, 2), date(2012, 1, 3)])
    assert report.passed
    assert report.metrics["trading_days_checked"] == 2


def test_missing_membership_blocks_certification():
    intervals = build_intervals([_event(number) for number in range(199)]).intervals
    report = validate_campaign(intervals, [_event(number) for number in range(199)], campaign_from=date(2012, 1, 2), campaign_to=date(2012, 1, 2), trading_days=[date(2012, 1, 2)])
    assert not report.passed
    assert any(reason.startswith("member_count") for reason in report.reasons)
