from datetime import date, datetime
from dataclasses import replace

from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.models import Action, CanonicalEvent, Confidence, ReviewStatus
from tools.nifty200_pit.validation import nifty200_expected_security_count, validate_campaign


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


def test_validator_rejects_b1_events_even_when_membership_count_matches():
    events = [_event(number) for number in range(200)]
    events[0] = replace(events[0], source_tier="B1")
    report = validate_campaign(
        build_intervals(events).intervals, events,
        trading_days=[date(2012, 1, 2)],
    )
    assert not report.passed
    assert any(reason.startswith("unconfirmed_membership_evidence:") for reason in report.reasons)


def test_documented_dvr_security_count_is_effective_on_exact_boundaries():
    assert nifty200_expected_security_count(date(2016, 3, 31)) == 200
    assert nifty200_expected_security_count(date(2016, 4, 1)) == 201
    assert nifty200_expected_security_count(date(2020, 6, 25)) == 201
    assert nifty200_expected_security_count(date(2020, 6, 26)) == 200
    assert nifty200_expected_security_count(date(2023, 9, 28)) == 200
    assert nifty200_expected_security_count(date(2023, 9, 29)) == 201
    assert nifty200_expected_security_count(date(2025, 9, 29)) == 201
    assert nifty200_expected_security_count(date(2025, 9, 30)) == 200


def test_validator_compares_against_period_specific_security_count():
    events = [_event(number) for number in range(201)]
    day = date(2016, 4, 1)
    report = validate_campaign(build_intervals(events).intervals, events,
                               trading_days=[day], expected_member_counts={day: 201})
    assert report.passed
    assert report.metrics["count_check_failures"] == 0
    assert report.metrics["daily_expected_member_counts"][day.isoformat()] == 201
