from datetime import date, datetime

from tools.nifty200_pit.intervals import active_intervals, build_intervals
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


def test_evidenced_pre_campaign_add_survives_until_its_campaign_drop():
    entry = _event(Action.ADD, "REDINGTON", date(2011, 12, 7))
    result = build_intervals([
        entry, _event(Action.DROP, "REDINGTON", date(2012, 4, 27), "b"),
    ], horizon_start=date(2012, 1, 2), horizon_end=date(2012, 12, 31))
    assert result.conflicts == []
    assert len(result.intervals) == 1
    interval = result.intervals[0]
    assert interval.effective_from == date(2011, 12, 7)
    assert interval.effective_until == date(2012, 4, 27)
    assert interval.entry_event_hash == entry.event_hash
    assert interval.known_at == entry.known_at
    assert active_intervals(result.intervals, date(2012, 1, 2)) == [interval]
    assert active_intervals(result.intervals, date(2012, 4, 27)) == []


def test_pre_campaign_drop_does_not_seed_membership_or_leave_closed_history():
    result = build_intervals([
        _event(Action.ADD, "CLOSED", date(2011, 11, 1)),
        _event(Action.DROP, "CLOSED", date(2012, 1, 2), "b"),
        _event(Action.DROP, "NO_PRIOR_HISTORY", date(2011, 12, 7), "c"),
        _event(Action.DROP, "CAMPAIGN_GAP", date(2012, 4, 27), "d"),
    ], horizon_start=date(2012, 1, 2), horizon_end=date(2012, 12, 31))
    assert result.intervals == []
    assert len(result.conflicts) == 1
    assert result.conflicts[0].date == date(2012, 4, 27)
