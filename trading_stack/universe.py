"""Operational checks for immutable NIFTY 200 research universes."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any

from storage import DuckDBManager


def _required_row(row: tuple[Any, ...] | None, description: str) -> tuple[Any, ...]:
    if row is None:
        raise RuntimeError(f"DuckDB returned no row for {description}.")
    return row


@dataclass(frozen=True)
class UniverseReadiness:
    snapshot_id: str
    member_count: int
    token_count: int
    symbols_with_data: int
    symbols_with_lookback: int
    benchmark_symbol: str
    benchmark_provider_symbol: str | None
    benchmark_relationship: str | None
    calendar_exception_count: int
    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class UniverseResearchService:
    """Report whether a snapshot can support synchronized portfolio research."""

    def __init__(self, db: DuckDBManager) -> None:
        self.db = db

    def register_benchmark(
        self,
        canonical_symbol: str,
        provider_symbol: str,
        *,
        relationship: str = "EXACT",
        source: str,
        approved_for_research: bool = False,
        notes: str | None = None,
    ) -> None:
        relationship = relationship.upper()
        if relationship not in {"EXACT", "PROXY"}:
            raise ValueError("Benchmark relationship must be EXACT or PROXY.")
        self.db._replace_rows("benchmark_aliases", [{
            "canonical_symbol": canonical_symbol.upper(),
            "provider_symbol": provider_symbol.upper(),
            "relationship": relationship,
            "source": source,
            "approved_for_research": approved_for_research,
            "notes": notes,
        }])

    def readiness(
        self,
        snapshot_id: str,
        *,
        timeframe: str = "1d",
        benchmark_symbol: str = "NIFTY",
        minimum_bars: int = 253,
        minimum_eligible_fraction: float = 0.80,
    ) -> UniverseReadiness:
        if not 0 < minimum_eligible_fraction <= 1:
            raise ValueError("minimum_eligible_fraction must be in (0, 1].")
        snapshot = self.db.conn.execute(
            "SELECT name FROM universe_snapshots WHERE snapshot_id = ?", [snapshot_id],
        ).fetchone()
        if snapshot is None:
            raise ValueError(f"Universe snapshot not found: {snapshot_id}")
        member_count, token_count = _required_row(self.db.conn.execute(
            """SELECT COUNT(*), COUNT(provider_token) FROM universe_snapshot_members
               WHERE snapshot_id = ? AND active_to IS NULL AND data_eligible""",
            [snapshot_id],
        ).fetchone(), "universe member counts")
        coverage = _required_row(self.db.conn.execute(
            """SELECT SUM(CASE WHEN bar_count > 0 THEN 1 ELSE 0 END),
                      SUM(CASE WHEN bar_count >= ? THEN 1 ELSE 0 END)
               FROM (
                   SELECT m.symbol, COUNT(c.timestamp) bar_count
                   FROM universe_snapshot_members m
                   LEFT JOIN historical_candles c
                     ON c.symbol = m.provider_symbol AND c.timeframe = ?
                   WHERE m.snapshot_id = ? AND m.active_to IS NULL AND m.data_eligible
                   GROUP BY m.symbol
               )""",
            [minimum_bars, timeframe, snapshot_id],
        ).fetchone(), "universe coverage counts")
        benchmark = self.db.conn.execute(
            """SELECT provider_symbol, relationship FROM benchmark_aliases
               WHERE canonical_symbol = ? AND approved_for_research
               ORDER BY CASE relationship WHEN 'EXACT' THEN 0 ELSE 1 END LIMIT 1""",
            [benchmark_symbol],
        ).fetchone()
        provider_symbol = str(benchmark[0]) if benchmark else benchmark_symbol
        relationship = str(benchmark[1]) if benchmark else "EXACT"
        benchmark_rows = _required_row(self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_candles WHERE symbol = ? AND timeframe = ?",
            [provider_symbol, timeframe],
        ).fetchone(), "benchmark row count")[0]
        calendar_exceptions = _required_row(self.db.conn.execute(
            """SELECT COALESCE(SUM(issue_count), 0) FROM (
                   SELECT issue_count,
                           ROW_NUMBER() OVER (PARTITION BY symbol, timeframe, check_type ORDER BY checked_at DESC) rank
                    FROM quality_report
                    WHERE timeframe = ? AND check_type = 'session_alignment'
                      AND (
                          symbol IN (
                              SELECT symbol FROM universe_snapshot_members WHERE snapshot_id = ?
                              UNION
                              SELECT provider_symbol FROM universe_snapshot_members WHERE snapshot_id = ?
                          )
                          OR symbol = ?
                      )
                ) WHERE rank = 1""",
            [timeframe, snapshot_id, snapshot_id, provider_symbol],
        ).fetchone(), "calendar exception count")[0]
        blockers: list[str] = []
        warnings: list[str] = []
        if int(member_count) != 200:
            blockers.append(f"SNAPSHOT_MEMBER_COUNT:{member_count}")
        if int(token_count) < int(member_count):
            blockers.append(f"MISSING_PROVIDER_TOKENS:{int(member_count) - int(token_count)}")
        symbols_with_data = int(coverage[0] or 0)
        symbols_with_lookback = int(coverage[1] or 0)
        if symbols_with_data < int(member_count):
            blockers.append(f"MISSING_MEMBER_DATA:{int(member_count) - symbols_with_data}")
        required_eligible = math.ceil(int(member_count) * minimum_eligible_fraction)
        if symbols_with_lookback < required_eligible:
            blockers.append(f"INSUFFICIENT_ELIGIBLE_UNIVERSE:{symbols_with_lookback}/{required_eligible}")
        elif symbols_with_lookback < int(member_count):
            warnings.append(f"SHORT_LISTING_HISTORY:{int(member_count) - symbols_with_lookback}")
        if int(benchmark_rows) < minimum_bars:
            blockers.append(f"BENCHMARK_LOOKBACK:{benchmark_rows}")
        if int(calendar_exceptions or 0) > 0:
            blockers.append(f"UNRESOLVED_CALENDAR_EXCEPTIONS:{int(calendar_exceptions)}")
        return UniverseReadiness(
            snapshot_id=snapshot_id,
            member_count=int(member_count),
            token_count=int(token_count),
            symbols_with_data=symbols_with_data,
            symbols_with_lookback=symbols_with_lookback,
            benchmark_symbol=benchmark_symbol,
            benchmark_provider_symbol=provider_symbol,
            benchmark_relationship=relationship,
            calendar_exception_count=int(calendar_exceptions or 0),
            ready=not blockers,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )
