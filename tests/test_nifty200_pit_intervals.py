from datetime import date, datetime

from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.models import Action, CanonicalEvent, Confidence, ReviewStatus


def _event(action, instrument="SEC-1", when=date(2011, 7, 19), digest="a"):
    return CanonicalEvent("NIFTY_200", instrument, None, instrument, None, date(2011, 7, 18), datetime(2011, 7, 19, 9, 15),
                          "DATE_ONLY_CONSERVATIVE_NEXT_SESSION", when, action, "anchor", "https://nse.example/a", None,
                          digest * 64, 1, "A1", "PDF_TEXT", "v1", Confidence.CERTIFIED, ReviewStatus.ACCEPTED, digest * 64)


def test_intervals_are_exclusive_and_support_reentry():
    result = build_intervals([_event(Action.INITIAL_MEMBER), _event(Action.DROP, when=date(2012, 1, 2), digest="b"),
                              _event(Action.ADD, when=date(2012, 2, 1), digest="c")])
    assert not result.conflicts
    assert [(row.effective_from, row.effective_until) for row in result.intervals] == [(date(2011, 7, 19), date(2012, 1, 2)), (date(2012, 2, 1), None)]


def test_duplicate_add_is_rejected():
    result = build_intervals([_event(Action.INITIAL_MEMBER), _event(Action.ADD, when=date(2011, 8, 1), digest="b")])
    assert any(conflict.conflict_type == "DUPLICATE_ADD" for conflict in result.conflicts)
