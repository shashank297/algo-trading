"""Point-in-Time (PIT) Universe Management Engine.

Provides survivorship-bias-free historical index and universe constituent tracking.
Guarantees that strategies and backtests only see instruments that were active members
of the universe on any given historical date t, with durable canonical instrument identity
and announcement-time (known_from) isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class PointInTimeConstituent:
    """Point-in-time constituent membership record with canonical instrument identity."""

    universe_name: str
    symbol: str
    token: str
    instrument_id: str = ""
    exchange: str = "NSE"
    effective_from: date = date(2000, 1, 1)
    effective_until: date | None = None
    known_from: date | None = None
    known_at: datetime | None = None
    weight: float | None = None
    inclusion_reason: str | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id:
            # Generate deterministic canonical instrument identity
            canonical = f"{self.exchange.upper()}:{self.symbol.upper()}:EQ"
            object.__setattr__(self, "instrument_id", canonical)
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError(
                f"effective_until ({self.effective_until}) must be strictly after effective_from ({self.effective_from}) "
                f"for constituent {self.symbol} in {self.universe_name}."
            )

    @property
    def is_active_indefinitely(self) -> bool:
        return self.effective_until is None


class PointInTimeUniverseManager:
    """Institutional manager for survivorship-bias-free point-in-time universe lookups."""

    @classmethod
    def canonical_instrument_id(cls, exchange: str, symbol: str, series: str = "EQ") -> str:
        """Derive standard canonical instrument identifier."""
        return f"{exchange.upper().strip()}:{symbol.upper().strip()}:{series.upper().strip()}"

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
        allow_overlap: bool = False,
    ) -> None:
        """Insert a constituent membership record into DuckDB with interval overlap validation."""
        raw_conn = cls._get_raw_conn(conn)
        
        # Overlap validation
        if not allow_overlap:
            cls._validate_no_interval_overlap(raw_conn, constituent)

        raw_conn.execute(
            """
            INSERT OR REPLACE INTO index_constituents_pit (
                universe_name, instrument_id, symbol, token, exchange, effective_from,
                effective_until, known_from, known_at, weight, inclusion_reason, exclusion_reason,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                constituent.universe_name.upper(),
                constituent.instrument_id.upper(),
                constituent.symbol.upper(),
                str(constituent.token),
                constituent.exchange.upper(),
                constituent.effective_from.isoformat(),
                constituent.effective_until.isoformat() if constituent.effective_until else None,
                constituent.known_from.isoformat() if constituent.known_from else None,
                constituent.known_at.isoformat() if constituent.known_at else None,
                constituent.weight,
                constituent.inclusion_reason,
                constituent.exclusion_reason,
                datetime.now(timezone.utc).isoformat(),
            ],
        )

    @classmethod
    def _validate_no_interval_overlap(
        cls,
        raw_conn: Any,
        constituent: PointInTimeConstituent,
    ) -> None:
        """Ensure the new interval [effective_from, effective_until) does not overlap existing records."""
        query = """
            SELECT effective_from, effective_until
            FROM index_constituents_pit
            WHERE universe_name = ?
              AND instrument_id = ?
              AND effective_from != ?
        """
        rows = raw_conn.execute(
            query,
            [
                constituent.universe_name.upper(),
                constituent.instrument_id.upper(),
                constituent.effective_from.isoformat(),
            ],
        ).fetchall()

        new_start = constituent.effective_from
        new_end = constituent.effective_until or date(9999, 12, 31)

        for r in rows:
            exist_start = pd.Timestamp(r[0]).date()
            exist_end = pd.Timestamp(r[1]).date() if r[1] is not None else date(9999, 12, 31)

            # Check overlap condition: max(start1, start2) < min(end1, end2)
            if max(new_start, exist_start) < min(new_end, exist_end):
                raise ValueError(
                    f"Overlapping PIT membership interval detected for {constituent.instrument_id} in {constituent.universe_name}: "
                    f"New [{new_start}, {new_end}) overlaps existing [{exist_start}, {exist_end})."
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
                known_from = cls._normalize_date(row["known_from"]) if pd.notna(row.get("known_from")) else None
                inst_id = str(row.get("instrument_id", ""))
                const = PointInTimeConstituent(
                    universe_name=str(row["universe_name"]),
                    symbol=str(row["symbol"]),
                    token=str(row.get("token", "")),
                    instrument_id=inst_id,
                    exchange=str(row.get("exchange", "NSE")),
                    effective_from=eff_from,
                    effective_until=eff_until,
                    known_from=known_from,
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
        as_of_knowledge: date | datetime | str | None = None,
    ) -> list[PointInTimeConstituent]:
        """Fetch exact point-in-time constituents active on date as_of without survivorship bias."""
        raw_conn = cls._get_raw_conn(conn)
        target_date = cls._normalize_date(as_of)
        
        query = """
            SELECT universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from, known_at, weight, inclusion_reason, exclusion_reason
            FROM index_constituents_pit
            WHERE universe_name = ?
              AND effective_from <= ?
              AND (effective_until IS NULL OR effective_until > ?)
        """
        params: list[Any] = [universe_name.upper(), target_date.isoformat(), target_date.isoformat()]

        if as_of_knowledge is not None:
            knowledge_timestamp = pd.Timestamp(as_of_knowledge)
            if knowledge_timestamp.tzinfo is None:
                knowledge_timestamp = knowledge_timestamp.tz_localize("Asia/Kolkata")
            knowledge_date = knowledge_timestamp.date()
            query += """ AND (
                known_from IS NULL
                OR known_from < ?
                OR (known_from = ? AND known_at IS NOT NULL AND known_at <= ?)
            )"""
            params.extend([knowledge_date.isoformat(), knowledge_date.isoformat(), knowledge_timestamp.isoformat()])

        query += " ORDER BY symbol ASC"
        rows = raw_conn.execute(query, params).fetchall()
        
        result: list[PointInTimeConstituent] = []
        for r in rows:
            eff_from = pd.Timestamp(r[5]).date()
            eff_until = pd.Timestamp(r[6]).date() if r[6] is not None else None
            known_from = pd.Timestamp(r[7]).date() if r[7] is not None else None
            result.append(
                PointInTimeConstituent(
                    universe_name=r[0],
                    instrument_id=r[1],
                    symbol=r[2],
                    token=r[3],
                    exchange=r[4],
                    effective_from=eff_from,
                    effective_until=eff_until,
                    known_from=known_from,
                    known_at=pd.Timestamp(r[8]).to_pydatetime() if r[8] is not None else None,
                    weight=r[9],
                    inclusion_reason=r[10],
                    exclusion_reason=r[11],
                )
            )
        return result

    @classmethod
    def get_constituent_symbols(
        cls,
        conn: Any,
        universe_name: str,
        as_of: date | datetime | str,
        as_of_knowledge: date | datetime | str | None = None,
    ) -> list[str]:
        """Return list of active symbols for the specified universe on date as_of."""
        constituents = cls.get_constituents(conn, universe_name, as_of, as_of_knowledge=as_of_knowledge)
        return [c.symbol for c in constituents]

    @classmethod
    def get_constituent_tokens(
        cls,
        conn: Any,
        universe_name: str,
        as_of: date | datetime | str,
        as_of_knowledge: date | datetime | str | None = None,
    ) -> list[str]:
        """Return list of active instrument tokens for the specified universe on date as_of."""
        constituents = cls.get_constituents(conn, universe_name, as_of, as_of_knowledge=as_of_knowledge)
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
            SELECT universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from, weight, inclusion_reason, exclusion_reason
            FROM index_constituents_pit
            WHERE universe_name = ?
            ORDER BY effective_from ASC, symbol ASC
        """
        return raw_conn.execute(query, [universe_name.upper()]).df()
