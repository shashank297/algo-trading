"""Summary report generation for historical data downloads."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from utils.timezone import to_ist


class ReportGenerator:
    """Generate console-friendly and file-backed summary reports."""

    def __init__(self, log_path: str = "logs") -> None:
        """Initialize the report generator.

        Args:
            log_path: Directory where the summary file will be written.
        """

        self.log_path = Path(log_path)
        self.log_path.mkdir(parents=True, exist_ok=True)

    def generate_summary(
        self,
        results: list[dict[str, Any]],
        start_time: datetime,
        duration_seconds: float | None = None,
    ) -> str:
        """Generate, log, and persist the run summary.

        Args:
            results: Per-symbol and per-timeframe result rows.
            start_time: Run start datetime.
            duration_seconds: Optional measured runtime in seconds.

        Returns:
            str: Rendered multi-line summary text.
        """

        run_started_at = to_ist(start_time)
        unique_symbols = list(dict.fromkeys(result["symbol"] for result in results))
        unique_timeframes = list(dict.fromkeys(result["timeframe"] for result in results))
        elapsed = duration_seconds
        if elapsed is None:
            elapsed = max((datetime.now(tz=run_started_at.tzinfo) - run_started_at).total_seconds(), 0.0)

        summary_lines: list[str] = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║        AlgoTrading Phase 1 — Download Summary              ║",
            "╠══════════════════════════════════════════════════════════════╣",
            f"║ Run Date     : {run_started_at.strftime('%Y-%m-%d %H:%M:%S IST'):<45}║",
            f"║ Total Symbols: {len(unique_symbols):<45}║",
            f"║ Timeframes   : {', '.join(unique_timeframes):<45}║",
            f"║ Duration     : {self._format_duration(elapsed):<45}║",
            "╠══════════════════════════════════════════════════════════════╣",
            "║ Symbol          TF    Candles   Inserted  Status           ║",
        ]

        for result in results:
            status = self._format_status(result["status"])
            summary_lines.append(
                "║ "
                f"{result['symbol'][:14]:<14}  "
                f"{result['timeframe']:<4}  "
                f"{int(result.get('candles_fetched', 0)):,}".rjust(8)
                + "   "
                + f"{int(result.get('candles_inserted', 0)):,}".rjust(8)
                + "  "
                + f"{status:<16}"
                + "║"
            )

        summary_lines.append("╠══════════════════════════════════════════════════════════════╣")
        summary_lines.append("║ Quality Issues:                                             ║")

        quality_lines = [
            result["quality_summary"]
            for result in results
            if result.get("quality_summary") is not None
        ]
        if not quality_lines:
            summary_lines.append("║  • None                                                     ║")
        else:
            for quality_line in quality_lines:
                text = f"• {quality_line}"
                summary_lines.append(f"║  {text:<58}║")

        summary_lines.append("╚══════════════════════════════════════════════════════════════╝")

        summary = "\n".join(summary_lines)
        summary_file = self.log_path / f"summary_{run_started_at.strftime('%Y-%m-%d')}.txt"
        summary_file.write_text(summary, encoding="utf-8")
        logger.info("\n{}", summary)
        return summary

    def _format_duration(self, duration_seconds: float) -> str:
        """Format a duration in seconds to a compact human-readable string.

        Args:
            duration_seconds: Duration in seconds.

        Returns:
            str: Formatted duration.
        """

        total_seconds = int(round(duration_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _format_status(self, status: str) -> str:
        """Map an internal status to the displayed report label.

        Args:
            status: Internal status text.

        Returns:
            str: Display-ready status label.
        """

        status_map = {
            "SUCCESS": "✅ SUCCESS",
            "FAILED": "❌ FAILED",
            "PARTIAL": "⚠️ PARTIAL",
            "UP_TO_DATE": "⏭️ UP_TO_DATE",
        }
        return status_map.get(status, status)
