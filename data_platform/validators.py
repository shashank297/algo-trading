"""Exhaustive structural validator for raw market data providers."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

from data_platform.contracts import RawValidationIssue, RawValidationResult


class RawStructuralValidator:
    """Validate provider records for OHLC bounds, finiteness, positivity, timestamp integrity, and schema conformance."""

    REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")

    @classmethod
    def validate(cls, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | pd.DataFrame) -> RawValidationResult:
        """Exhaustively validate every provider row without silent dropping."""
        if isinstance(rows, pd.DataFrame):
            row_dicts = rows.to_dict(orient="records")
        else:
            row_dicts = list(rows)

        issues: list[RawValidationIssue] = []
        seen_timestamps: set[Any] = set()
        malformed_rows: set[int] = set()

        for idx, row in enumerate(row_dicts):
            row_num = int(row.get("source_row_number", idx))
            event_ts: datetime | None = None

            # 1. Schema check
            missing = [f for f in cls.REQUIRED_FIELDS if f not in row or row[f] is None]
            if missing:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=None,
                        reason_code="UNEXPECTED_SCHEMA",
                    )
                )
                malformed_rows.add(row_num)
                continue

            # 2. Timestamp check
            raw_ts = row.get("timestamp")
            if raw_ts is None or str(raw_ts).strip() == "" or str(raw_ts).lower() == "nan":
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=None,
                        reason_code="TIMESTAMP_MISSING",
                    )
                )
                malformed_rows.add(row_num)
            else:
                try:
                    event_ts = pd.to_datetime(raw_ts, utc=True).to_pydatetime()
                    if event_ts in seen_timestamps:
                        issues.append(
                            RawValidationIssue(
                                source_row_number=row_num,
                                event_timestamp=event_ts,
                                reason_code="TIMESTAMP_DUPLICATE",
                            )
                        )
                        malformed_rows.add(row_num)
                    else:
                        seen_timestamps.add(event_ts)
                except Exception:
                    issues.append(
                        RawValidationIssue(
                            source_row_number=row_num,
                            event_timestamp=None,
                            reason_code="TIMESTAMP_INVALID",
                        )
                    )
                    malformed_rows.add(row_num)

            # 3. Numeric parsing and finiteness
            parsed_vals: dict[str, float] = {}
            parse_failed = False
            for field in ("open", "high", "low", "close", "volume"):
                raw_val = row.get(field)
                try:
                    val = float(raw_val)
                    if math.isnan(val) or math.isinf(val):
                        issues.append(
                            RawValidationIssue(
                                source_row_number=row_num,
                                event_timestamp=event_ts,
                                reason_code=f"{field.upper()}_NON_FINITE",
                            )
                        )
                        malformed_rows.add(row_num)
                        parse_failed = True
                    else:
                        parsed_vals[field] = val
                except (ValueError, TypeError):
                    issues.append(
                        RawValidationIssue(
                            source_row_number=row_num,
                            event_timestamp=event_ts,
                            reason_code="NUMERIC_PARSE_FAILED",
                        )
                    )
                    malformed_rows.add(row_num)
                    parse_failed = True

            if parse_failed:
                continue

            o = parsed_vals["open"]
            h = parsed_vals["high"]
            l = parsed_vals["low"]
            c = parsed_vals["close"]
            v = parsed_vals["volume"]

            # 4. Positivity checks
            if o <= 0:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="OPEN_NON_POSITIVE",
                    )
                )
                malformed_rows.add(row_num)
            if h <= 0:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="HIGH_NON_POSITIVE",
                    )
                )
                malformed_rows.add(row_num)
            if l <= 0:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="LOW_NON_POSITIVE",
                    )
                )
                malformed_rows.add(row_num)
            if c <= 0:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="CLOSE_NON_POSITIVE",
                    )
                )
                malformed_rows.add(row_num)
            if v < 0:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="VOLUME_NEGATIVE",
                    )
                )
                malformed_rows.add(row_num)

            # 5. OHLC Invariant Bounds
            if h < o:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="HIGH_BELOW_OPEN",
                    )
                )
                malformed_rows.add(row_num)
            if h < c:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="HIGH_BELOW_CLOSE",
                    )
                )
                malformed_rows.add(row_num)
            if l > o:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="LOW_ABOVE_OPEN",
                    )
                )
                malformed_rows.add(row_num)
            if l > c:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="LOW_ABOVE_CLOSE",
                    )
                )
                malformed_rows.add(row_num)
            if h < l:
                issues.append(
                    RawValidationIssue(
                        source_row_number=row_num,
                        event_timestamp=event_ts,
                        reason_code="HIGH_BELOW_LOW",
                    )
                )
                malformed_rows.add(row_num)

        return RawValidationResult(
            is_valid=len(issues) == 0,
            issues=tuple(issues),
            malformed_row_count=len(malformed_rows),
        )
