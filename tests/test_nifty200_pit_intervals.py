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


def test_amtekauto_zero_length_interval_is_rejected():
    """Regression: AMTEKAUTO effective_from == effective_until (2014-09-19 ADD / 2014-09-19 DROP).

    Root cause: Both ADD and DROP events share the same effective_date for AMTEKAUTO.
    The interval builder routes this to SAME_DAY_EVENT_COLLISION before a zero-length
    interval can be emitted, which is the correct fail-closed behavior.  The instrument
    must NOT appear as a closed constituent interval with zero or negative length.
    """
    add_event = _event(Action.ADD, instrument="AMTEKAUTO", when=date(2014, 9, 19), digest="add")
    drop_event = _event(Action.DROP, instrument="AMTEKAUTO", when=date(2014, 9, 19), digest="drp")
    result = build_intervals([add_event, drop_event])
    # Same-day ADD+DROP routes through SAME_DAY_EVENT_COLLISION, the correct rejection path
    assert any(c.conflict_type == "SAME_DAY_EVENT_COLLISION" for c in result.conflicts), (
        "Expected SAME_DAY_EVENT_COLLISION conflict for AMTEKAUTO same-day ADD/DROP"
    )
    # The structural importer must never see a closed zero-length interval
    for interval in result.intervals:
        if interval.effective_until is not None:
            assert interval.effective_from < interval.effective_until, (
                f"Zero-length closed interval found: {interval.instrument_id} "
                f"{interval.effective_from} to {interval.effective_until}"
            )


def test_no_zero_length_or_negative_closed_intervals_ever_emitted():
    """Any same-day ADD/DROP must always fail closed — no zero-length or negative closed intervals.

    The interval builder routes same (instrument, effective_date) multi-events to
    SAME_DAY_EVENT_COLLISION (the AMTEKAUTO root cause). The NON_POSITIVE_INTERVAL guard
    fires separately when a DROP with a later-but-equal date slips through.
    Either way, the output intervals must never contain effective_from >= effective_until.
    """
    add_event = _event(Action.ADD, instrument="SEC-NPT", when=date(2015, 9, 1), digest="npt1")
    drop_event = _event(Action.DROP, instrument="SEC-NPT", when=date(2015, 9, 1), digest="npt2")
    result = build_intervals([add_event, drop_event])
    # Both paths (SAME_DAY_EVENT_COLLISION and NON_POSITIVE_INTERVAL) are fail-closed
    assert result.conflicts, "A same-day ADD/DROP must always produce a conflict"
    for interval in result.intervals:
        if interval.effective_until is not None:
            assert interval.effective_from < interval.effective_until, (
                f"Zero-length closed interval found: {interval.instrument_id} "
                f"{interval.effective_from} to {interval.effective_until}"
            )


def test_same_day_add_drop_two_events_raises_collision_conflict():
    """Two different events for the same instrument on the same date must collide."""
    add_event = _event(Action.ADD, instrument="SEC-X", when=date(2015, 3, 1), digest="ev1")
    # Simulate a second ADD (e.g., from a different source) on the same day
    add_event2 = _event(Action.ADD, instrument="SEC-X", when=date(2015, 3, 1), digest="ev2")
    result = build_intervals([add_event, add_event2])
    # Both events have same instrument+date → collision
    assert any(c.conflict_type == "SAME_DAY_EVENT_COLLISION" for c in result.conflicts)
