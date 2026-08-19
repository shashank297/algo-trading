"""Time-ordered validation helpers that avoid data leakage."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimeSplit:
    train: pd.DataFrame
    test: pd.DataFrame


def time_split(frame: pd.DataFrame, train_fraction: float = 0.7) -> TimeSplit:
    """Split chronologically, never randomly, for out-of-sample evaluation."""

    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between zero and one.")
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    split_index = max(1, min(len(ordered) - 1, int(len(ordered) * train_fraction)))
    if len(ordered) < 2:
        raise ValueError("At least two bars are required for a time split.")
    return TimeSplit(train=ordered.iloc[:split_index].copy(), test=ordered.iloc[split_index:].copy())


def walk_forward_windows(frame: pd.DataFrame, train_size: int, test_size: int) -> list[TimeSplit]:
    """Produce expanding chronological train/test windows."""

    if train_size <= 0 or test_size <= 0:
        raise ValueError("Walk-forward window sizes must be positive.")
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    windows: list[TimeSplit] = []
    cursor = train_size
    while cursor + test_size <= len(ordered):
        windows.append(TimeSplit(ordered.iloc[:cursor].copy(), ordered.iloc[cursor:cursor + test_size].copy()))
        cursor += test_size
    return windows
