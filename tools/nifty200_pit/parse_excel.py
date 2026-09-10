"""Structured workbook parsing helpers for source snapshots."""

from __future__ import annotations

from typing import Any


def parse_inclusion_exclusion_frame(frame: Any) -> list[dict[str, Any]]:
    """Convert a pandas-like frame into raw rows without applying identity guesses."""
    if not hasattr(frame, "to_dict"):
        raise TypeError("frame must provide to_dict(orient='records')")
    rows = frame.to_dict(orient="records")
    result = []
    for row in rows:
        normalised = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
        result.append(normalised)
    return result


def read_workbook(path: str):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required to read workbooks") from exc
    return pd.read_excel(path, sheet_name=None, header=None)
