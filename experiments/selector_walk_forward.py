"""Phase 2.10 deterministic meta-selector walk-forward splits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class MetaSplit:
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    final_oos_start: datetime
    final_oos_end: datetime
    purge_periods: int
    embargo_periods: int


def split_meta_walk_forward(
    start: datetime,
    end: datetime,
    *,
    train_fraction: float = 0.50,
    validation_fraction: float = 0.25,
    purge_periods: int = 0,
    embargo_periods: int = 0,
) -> MetaSplit:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("walk-forward bounds must be timezone-aware")
    if start >= end:
        raise ValueError("walk-forward start must precede end")
    if not 0 < train_fraction < 1 or not 0 <= validation_fraction < 1:
        raise ValueError("fractions must be bounded")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train + validation fractions must leave final OOS")
    if purge_periods < 0 or embargo_periods < 0:
        raise ValueError("purge and embargo must be non-negative")

    total = end - start
    train_end = start + total * train_fraction
    validation_start = train_end + timedelta(days=purge_periods)
    validation_end = start + total * (train_fraction + validation_fraction)
    final_oos_start = validation_end + timedelta(days=embargo_periods)
    if validation_start >= validation_end or final_oos_start >= end:
        raise ValueError("purge/embargo leave no validation or final OOS span")
    return MetaSplit(
        train_start=start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        final_oos_start=final_oos_start,
        final_oos_end=end,
        purge_periods=purge_periods,
        embargo_periods=embargo_periods,
    )
