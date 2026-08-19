"""Refresh versioned market-session quality evidence from stored candles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import configured_nse_calendar, load_yaml, validate_config  # noqa: E402
from storage import DuckDBManager  # noqa: E402
from utils.timezone import get_ist_now  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="market_data.duckdb")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--timeframe", choices=("1m", "1d"), required=True)
    parser.add_argument("--universe-snapshot", required=True)
    parser.add_argument("--benchmark", default="NIFTY200")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_yaml(str(PROJECT_ROOT / args.config))
    validate_config(config)
    calendar = configured_nse_calendar(config)
    db_path = Path(args.database)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db = DuckDBManager(str(db_path))
    try:
        members = db.conn.execute(
            """SELECT DISTINCT provider_symbol
               FROM universe_snapshot_members
               WHERE snapshot_id = ? AND active_to IS NULL
                 AND data_eligible AND provider_symbol IS NOT NULL
               ORDER BY provider_symbol""",
            [args.universe_snapshot],
        ).fetchall()
        benchmark = db.conn.execute(
            """SELECT provider_symbol FROM benchmark_aliases
               WHERE canonical_symbol = ? AND approved_for_research
               ORDER BY CASE relationship WHEN 'EXACT' THEN 0 ELSE 1 END LIMIT 1""",
            [args.benchmark],
        ).fetchone()
        symbols = [str(row[0]) for row in members]
        if benchmark and str(benchmark[0]) not in symbols:
            symbols.append(str(benchmark[0]))

        reports = []
        for symbol in symbols:
            timestamps = db.conn.execute(
                """SELECT timestamp FROM historical_candles
                   WHERE symbol = ? AND timeframe = ? ORDER BY timestamp""",
                [symbol, args.timeframe],
            ).df()["timestamp"]
            if timestamps.empty:
                continue
            result = calendar.validate_bars(timestamps, args.timeframe)
            reports.append({
                "symbol": symbol,
                "timeframe": args.timeframe,
                "checks": {"session_alignment": {
                    "count": result.out_of_session_count,
                    "out_of_session": list(result.out_of_session),
                    "missing_sessions": list(result.missing_sessions),
                    "expected_interruptions": list(result.expected_interruptions),
                    "calendar_version": calendar.version,
                }},
                "checked_at": get_ist_now(),
            })
        db.log_quality_report(reports)
        print(json.dumps({
            "calendar_version": calendar.version,
            "timeframe": args.timeframe,
            "validated_symbols": len(reports),
            "out_of_session_bars": sum(
                report["checks"]["session_alignment"]["count"] for report in reports
            ),
        }, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
