"""Point-in-Time (PIT) Universe Management Engine.

Provides survivorship-bias-free historical index and universe constituent tracking.
Guarantees that strategies and backtests only see instruments that were active members
of the universe on any given historical date t, with durable canonical instrument identity
and announcement-time (known_from) isolation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class PointInTimeConstituent:
    """Point-in-time constituent membership record with canonical instrument identity."""

    universe_name: str
    symbol: str
    token: str = ""
    instrument_id: str = ""
    exchange: str = "NSE"
    effective_from: date = date(2000, 1, 1)
    effective_until: date | None = None
    known_from: date | None = None
    known_at: datetime | None = None
    weight: float | None = None
    inclusion_reason: str | None = None
    exclusion_reason: str | None = None
    is_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.is_authoritative:
            canonical_fallback = f"{self.exchange.upper()}:{self.symbol.upper()}:EQ"
            if not self.instrument_id or self.instrument_id.strip() == "" or self.instrument_id.strip().upper() == canonical_fallback:
                raise ValueError(
                    f"Authoritative PIT constituent requires an explicit durable instrument identity "
                    f"(such as ISIN or provider security ID); symbol-derived identity '{canonical_fallback}' is prohibited for {self.symbol}."
                )
        elif not self.instrument_id:
            # Generate deterministic canonical instrument identity for non-authoritative/diagnostic use
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
    def _ensure_knowledge_table(cls, raw_conn: Any) -> None:
        """Provide precise known-time storage for direct in-memory PIT callers."""
        raw_conn.execute(
            """CREATE TABLE IF NOT EXISTS index_constituent_knowledge (
                universe_name VARCHAR NOT NULL,
                instrument_id VARCHAR NOT NULL,
                effective_from DATE NOT NULL,
                known_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (universe_name, instrument_id, effective_from)
            )"""
        )

    @classmethod
    def insert_constituent(
        cls,
        conn: Any,
        constituent: PointInTimeConstituent,
        allow_overlap: bool = False,
        require_authoritative_identity: bool = False,
    ) -> None:
        """Insert a constituent membership record into DuckDB with interval overlap validation."""
        raw_conn = cls._get_raw_conn(conn)
        cls._ensure_knowledge_table(raw_conn)

        if require_authoritative_identity or constituent.is_authoritative:
            canonical_fallback = f"{constituent.exchange.upper()}:{constituent.symbol.upper()}:EQ"
            if not constituent.instrument_id or constituent.instrument_id.strip() == "" or constituent.instrument_id.strip().upper() == canonical_fallback:
                raise ValueError(
                    f"Authoritative PIT constituent requires an explicit durable instrument identity "
                    f"(such as ISIN or provider security ID); symbol-derived identity '{canonical_fallback}' is prohibited for {constituent.symbol}."
                )

        # Overlap validation
        if not allow_overlap:
            cls._validate_no_interval_overlap(raw_conn, constituent)

        raw_conn.execute(
            """
            INSERT OR REPLACE INTO index_constituents_pit (
                universe_name, instrument_id, symbol, token, exchange, effective_from,
                effective_until, known_from, weight, inclusion_reason, exclusion_reason,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                constituent.weight,
                constituent.inclusion_reason,
                constituent.exclusion_reason,
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        if constituent.known_at is not None:
            raw_conn.execute(
                """INSERT OR REPLACE INTO index_constituent_knowledge
                   (universe_name, instrument_id, effective_from, known_at) VALUES (?, ?, ?, ?)""",
                [constituent.universe_name.upper(), constituent.instrument_id.upper(),
                 constituent.effective_from.isoformat(), constituent.known_at.isoformat()],
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
        require_authoritative_identity: bool = False,
    ) -> int:
        """Bulk insert multiple PIT membership records."""
        raw_conn = cls._get_raw_conn(conn)
        cls._ensure_knowledge_table(raw_conn)
        if isinstance(records, pd.DataFrame):
            df = records.copy()
            if "universe_name" not in df.columns or "symbol" not in df.columns or "effective_from" not in df.columns:
                raise ValueError("DataFrame must contain universe_name, symbol, and effective_from columns")
            count = 0
            for _, row in df.iterrows():
                eff_from = cls._normalize_date(row["effective_from"])
                eff_until = cls._normalize_date(row["effective_until"]) if pd.notna(row.get("effective_until")) else None
                known_from = cls._normalize_date(row["known_from"]) if pd.notna(row.get("known_from")) else None
                known_at = (
                    pd.Timestamp(row["known_at"]).to_pydatetime()
                    if ("known_at" in row and pd.notna(row.get("known_at")))
                    else None
                )
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
                    known_at=known_at,
                    weight=float(row["weight"]) if pd.notna(row.get("weight")) else None,
                    inclusion_reason=str(row.get("inclusion_reason")) if pd.notna(row.get("inclusion_reason")) else None,
                    exclusion_reason=str(row.get("exclusion_reason")) if pd.notna(row.get("exclusion_reason")) else None,
                    is_authoritative=require_authoritative_identity,
                )
                cls.insert_constituent(raw_conn, const, require_authoritative_identity=require_authoritative_identity)
                count += 1
            return count
        else:
            for const in records:
                cls.insert_constituent(raw_conn, const, require_authoritative_identity=require_authoritative_identity)
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
        cls._ensure_knowledge_table(raw_conn)
        target_date = cls._normalize_date(as_of)
        
        query = """
            SELECT pit.universe_name, pit.instrument_id, pit.symbol, pit.token, pit.exchange,
                   pit.effective_from, pit.effective_until, pit.known_from, knowledge.known_at,
                   pit.weight, pit.inclusion_reason, pit.exclusion_reason
            FROM index_constituents_pit pit
            LEFT JOIN index_constituent_knowledge knowledge
              ON knowledge.universe_name = pit.universe_name
             AND knowledge.instrument_id = pit.instrument_id
             AND knowledge.effective_from = pit.effective_from
            WHERE pit.universe_name = ?
              AND pit.effective_from <= ?
              AND (pit.effective_until IS NULL OR pit.effective_until > ?)
        """
        params: list[Any] = [universe_name.upper(), target_date.isoformat(), target_date.isoformat()]

        if as_of_knowledge is not None:
            knowledge_timestamp = pd.Timestamp(as_of_knowledge)
            if knowledge_timestamp.tzinfo is None:
                knowledge_timestamp = knowledge_timestamp.tz_localize("Asia/Kolkata")
            knowledge_date = knowledge_timestamp.date()
            query += """ AND (
                pit.known_from < ?
                OR (pit.known_from = ? AND knowledge.known_at IS NOT NULL AND knowledge.known_at <= ?)
            )
            AND (
                knowledge.known_at IS NULL OR knowledge.known_at <= ?
            )
            """
            params.extend([
                knowledge_date.isoformat(),
                knowledge_date.isoformat(),
                knowledge_timestamp.isoformat(),
                knowledge_timestamp.isoformat(),
            ])

        query += " ORDER BY pit.symbol ASC"
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


class PITEventType(StrEnum):
    """Institutional PIT membership event types."""
    ADDITION = "ADDITION"
    REMOVAL = "REMOVAL"
    REBALANCE = "REBALANCE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    DELISTING = "DELISTING"
    SUSPENSION = "SUSPENSION"


@dataclass(frozen=True, slots=True)
class AuthoritativePITEvent:
    """Provider-neutral authoritative PIT event import record."""
    universe_name: str
    index_code: str
    instrument_id: str
    isin: str
    symbol_at_event: str
    security_name: str
    exchange: str
    instrument_type: str
    announcement_at: datetime
    effective_from: date
    effective_until: date | None
    event_type: PITEventType | str
    inclusion_status: str
    source_identifier: str
    source_version: str
    retrieved_at: datetime
    batch_hash: str

    def __post_init__(self) -> None:
        if not self.instrument_id or not self.instrument_id.strip():
            raise ValueError("AuthoritativePITEvent requires non-empty instrument_id")
        if not self.isin or not self.isin.strip():
            raise ValueError("AuthoritativePITEvent requires non-empty isin")
        if not self.symbol_at_event or not self.symbol_at_event.strip():
            raise ValueError("AuthoritativePITEvent requires non-empty symbol_at_event")
        if not self.source_identifier or not self.source_identifier.strip():
            raise ValueError("AuthoritativePITEvent requires non-empty source_identifier")
        if not self.batch_hash or not self.batch_hash.strip():
            raise ValueError("AuthoritativePITEvent requires non-empty batch_hash")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = str(self.event_type.value if isinstance(self.event_type, PITEventType) else self.event_type)
        d["announcement_at"] = self.announcement_at.isoformat()
        d["effective_from"] = self.effective_from.isoformat()
        d["effective_until"] = self.effective_until.isoformat() if self.effective_until else None
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


class PITCertificationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_EXTERNAL_DATA = "BLOCKED_EXTERNAL_DATA"


@dataclass(frozen=True)
class PITCertificationRecord:
    pit_certification_id: str
    universe_name: str
    horizon_start: date
    horizon_end: date
    status: PITCertificationStatus
    reasons: list[str]
    evidence_hash: str
    certified_at: str


class PITCertificationService:
    """Validates PIT coverage, identity continuity, intervals, and returns certification."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def certify_universe(
        self,
        universe_name: str,
        start_date: date,
        end_date: date,
        min_required_constituents: int = 1,
    ) -> PITCertificationRecord:
        """Evaluate PIT dataset integrity across requested horizon.
        
        Fails closed as BLOCKED_EXTERNAL_DATA when authoritative membership is unavailable.
        """
        raw_conn = PointInTimeUniverseManager._get_raw_conn(self.conn)
        query = """
            SELECT COUNT(DISTINCT instrument_id), COUNT(*)
            FROM index_constituents_pit
            WHERE universe_name = ?
              AND effective_from <= ?
              AND (effective_until IS NULL OR effective_until >= ?)
        """
        row = raw_conn.execute(query, [universe_name.upper(), end_date.isoformat(), start_date.isoformat()]).fetchone()
        distinct_instruments = int(row[0]) if row else 0
        total_records = int(row[1]) if row else 0

        reasons: list[str] = []
        if total_records == 0 or distinct_instruments < min_required_constituents:
            status = PITCertificationStatus.BLOCKED_EXTERNAL_DATA
            reasons.append(
                f"Authoritative historical PIT membership for {universe_name} across "
                f"[{start_date}, {end_date}] is unpopulated or insufficient "
                f"(observed {distinct_instruments} instruments, required {min_required_constituents})."
            )
        else:
            # Check for invalid interval overlaps
            overlap_query = """
                SELECT a.instrument_id, a.symbol
                FROM index_constituents_pit a
                JOIN index_constituents_pit b
                  ON a.universe_name = b.universe_name
                 AND a.instrument_id = b.instrument_id
                 AND a.effective_from < b.effective_from
                 AND (a.effective_until IS NULL OR a.effective_until > b.effective_from)
                WHERE a.universe_name = ?
            """
            overlaps = raw_conn.execute(overlap_query, [universe_name.upper()]).fetchall()
            if overlaps:
                status = PITCertificationStatus.FAIL
                reasons.append(f"Found {len(overlaps)} overlapping PIT intervals in {universe_name}.")
            else:
                status = PITCertificationStatus.PASS
                reasons.append("PIT interval integrity and constituent coverage verified.")

        canonical = json.dumps({
            "universe_name": universe_name.upper(),
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "status": status.value,
            "distinct_instruments": distinct_instruments,
            "reasons": reasons,
        }, sort_keys=True)
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        cert_id = f"pit-cert-{universe_name.lower()}-{evidence_hash[:12]}"

        return PITCertificationRecord(
            pit_certification_id=cert_id,
            universe_name=universe_name.upper(),
            horizon_start=start_date,
            horizon_end=end_date,
            status=status,
            reasons=reasons,
            evidence_hash=evidence_hash,
            certified_at=datetime.now(timezone.utc).isoformat(),
        )
