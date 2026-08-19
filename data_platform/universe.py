"""Point-in-Time (PIT) Universe Management Engine.

Provides survivorship-bias-free historical index and universe constituent tracking.
Guarantees that strategies and backtests only see instruments that were active members
of the universe on any given historical date t.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class PointInTimeConstituent:
    """Point-in-time constituent membership record."""

    universe_name: str
    symbol: str
    token: str
    exchange: str = "NSE"
    effective_from: date = date(2000, 1, 1)
    effective_until: date | None = None
    weight: float | None = None
    inclusion_reason: str | None = None
    exclusion_reason: str | None = None

    @property
    def is_active_indefinitely(self) -> bool:
        return self.effective_until is None


class PointInTimeUniverseManager:
    """Institutional manager for survivorship-bias-free point-in-time universe lookups."""

    @classmethod
    def _normalize_date(cls, dt_val: date | datetime | str) -> date:
        """Convert string, datetime, or date into a standard date object."""
        if isinstance(dt_val, str):
            return pd.Timestamp(dt_val).date()
        elif isinstance(dt_val, datetime):
            return dt_val.date()
        return dt_val

    @classmethod
    def _get_raw_conn(cls, conn: Any) -> Any:
        if conn is None:
            raise ValueError("Database connection must not be None")
        raw = getattr(conn, "conn", conn)
        if raw is None or not hasattr(raw, "execute"):
            raise ValueError("Provided connection must support .execute()")
        return raw

    @classmethod
    def insert_constituent(
        cls,
        conn: Any,
        constituent: PointInTimeConstituent,
    ) -> None:
        """Insert or replace a constituent membership record in DuckDB."""
        raw_conn = cls._get_raw_conn(conn)
        raw_conn.execute(
            """
            INSERT OR REPLACE INTO index_constituents_pit (
                universe_name, symbol, token, exchange, effective_from,
                effective_until, weight, inclusion_reason, exclusion_reason,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                constituent.universe_name.upper(),
                constituent.symbol.upper(),
                str(constituent.token),
                constituent.exchange.upper(),
                constituent.effective_from.isoformat(),
                constituent.effective_until.isoformat() if constituent.effective_until else None,
                constituent.weight,
                constituent.inclusion_reason,
                constituent.exclusion_reason,
                datetime.now(timezone.utc).isoformat(),
            ],
        )

    @classmethod
    def bulk_insert_constituents(
        cls,
        conn: Any,
        records: list[PointInTimeConstituent] | pd.DataFrame,
    ) -> int:
        """Bulk insert multiple PIT membership records."""
        raw_conn = cls._get_raw_conn(conn)
        if isinstance(records, pd.DataFrame):
            df = records.copy()
            if "universe_name" not in df.columns or "symbol" not in df.columns or "effective_from" not in df.columns:
                raise ValueError("DataFrame must contain universe_name, symbol, and effective_from columns")
            count = 0
            for _, row in df.iterrows():
                eff_from = cls._normalize_date(row["effective_from"])
                eff_until = cls._normalize_date(row["effective_until"]) if pd.notna(row.get("effective_until")) else None
                const = PointInTimeConstituent(
                    universe_name=str(row["universe_name"]),
                    symbol=str(row["symbol"]),
                    token=str(row.get("token", "")),
                    exchange=str(row.get("exchange", "NSE")),
                    effective_from=eff_from,
                    effective_until=eff_until,
                    weight=float(row["weight"]) if pd.notna(row.get("weight")) else None,
                    inclusion_reason=str(row.get("inclusion_reason")) if pd.notna(row.get("inclusion_reason")) else None,
                    exclusion_reason=str(row.get("exclusion_reason")) if pd.notna(row.get("exclusion_reason")) else None,
                )
                cls.insert_constituent(raw_conn, const)
                count += 1
            return count
        else:
            for const in records:
                cls.insert_constituent(raw_conn, const)
            return len(records)

    @classmethod
    def get_constituents(
        cls,
        conn: Any,
        universe_name: str,
        as_of: date | datetime | str,
    ) -> list[PointInTimeConstituent]:
        """Fetch exact point-in-time constituents active on date as_of without survivorship bias."""
        raw_conn = cls._get_raw_conn(conn)
        target_date = cls._normalize_date(as_of)
        
        query = """
            SELECT universe_name, symbol, token, exchange, effective_from, effective_until, weight, inclusion_reason, exclusion_reason
            FROM index_constituents_pit
            WHERE universe_name = ?
              AND effective_from <= ?
              AND (effective_until IS NULL OR effective_until > ?)
            ORDER BY symbol ASC
        """
        rows = raw_conn.execute(query, [universe_name.upper(), target_date.isoformat(), target_date.isoformat()]).fetchall()
        
        result: list[PointInTimeConstituent] = []
        for r in rows:
            eff_from = pd.Timestamp(r[4]).date()
            eff_until = pd.Timestamp(r[5]).date() if r[5] is not None else None
            result.append(
                PointInTimeConstituent(
                    universe_name=r[0],
                    symbol=r[1],
                    token=r[2],
                    exchange=r[3],
                    effective_from=eff_from,
                    effective_until=eff_until,
                    weight=r[6],
                    inclusion_reason=r[7],
                    exclusion_reason=r[8],
                )
            )
        return result

    @classmethod
    def get_constituent_symbols(
        cls,
        conn: Any,
        universe_name: str,
        as_of: date | datetime | str,
    ) -> list[str]:
        """Return list of active symbols for the specified universe on date as_of."""
        constituents = cls.get_constituents(conn, universe_name, as_of)
        return [c.symbol for c in constituents]

    @classmethod
    def get_constituent_tokens(
        cls,
        conn: Any,
        universe_name: str,
        as_of: date | datetime | str,
    ) -> list[str]:
        """Return list of active instrument tokens for the specified universe on date as_of."""
        constituents = cls.get_constituents(conn, universe_name, as_of)
        return [c.token for c in constituents if c.token]

    @classmethod
    def get_universe_history(
        cls,
        conn: Any,
        universe_name: str,
    ) -> pd.DataFrame:
        """Return complete historical timeline of additions and removals for a universe."""
        raw_conn = cls._get_raw_conn(conn)
        query = """
            SELECT universe_name, symbol, token, exchange, effective_from, effective_until, weight, inclusion_reason, exclusion_reason
            FROM index_constituents_pit
            WHERE universe_name = ?
            ORDER BY effective_from ASC, symbol ASC
        """
        return raw_conn.execute(query, [universe_name.upper()]).df()
