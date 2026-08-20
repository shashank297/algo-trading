"""Consistent operational severity for market-data validation results."""

from __future__ import annotations

from typing import Any


CHECK_SEVERITY = {
    "schema": "CRITICAL",
    "duplicates": "CRITICAL",
    "future_timestamps": "CRITICAL",
    "null_values": "CRITICAL",
    "ohlc_integrity": "CRITICAL",
    "timestamp_integrity": "CRITICAL",
    "missing_candles": "ERROR",
    "session_alignment": "ERROR",
    "missing_sessions": "ERROR",
    "anomalies": "WARNING",
}


def summarize_quality(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Annotate checks and return blocking, warning, and paging totals."""

    totals = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0}
    has_check_failure = False
    for name, result in checks.items():
        if result.get("status") == "CHECK_FAILED":
            severity = "CRITICAL"
            result["check_executed"] = False
            has_check_failure = True
        else:
            severity = CHECK_SEVERITY.get(name, "ERROR")
        result["severity"] = severity
        totals[severity] += int(result.get("count", 0))

    if totals["CRITICAL"] or has_check_failure:
        status = "CRITICAL"
    elif totals["ERROR"]:
        status = "ERROR"
    elif totals["WARNING"]:
        status = "WARNING"
    else:
        status = "HEALTHY"
    return {
        "passed": totals["CRITICAL"] == 0 and totals["ERROR"] == 0 and not has_check_failure,
        "status": status,
        "blocking_issue_count": totals["CRITICAL"] + totals["ERROR"],
        "warning_count": totals["WARNING"],
        "page_operator": totals["CRITICAL"] > 0 or has_check_failure,
        "has_check_failure": has_check_failure,
    }
