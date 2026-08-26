"""Synchronized, provenance-aware research panels."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, fields
from threading import Lock
from typing import Any, ClassVar

import numpy as np
import pandas as pd
from loguru import logger

from data_platform.adjustments import PriceAdjustmentEngine
from data_platform.contracts import PriceAdjustment
from storage.duckdb_manager import DuckDBManager
from trading_stack.features import FeatureFactory
from trading_stack.calendars import MarketCalendar
from trading_stack.domain import AssetClass
from trading_stack.calendars import build_default_calendars
from validators.data_quality import DataQualityError

REQUIRED_AUTHORITATIVE_DQ_CHECKS = {
    "schema",
    "ohlc_integrity",
    "duplicates",
    "session_alignment",
    "missing_sessions",
    "timestamp_integrity",
}


@dataclass(frozen=True)
class ResearchUniverse:
    universe_name: str
    snapshot_id: str


@dataclass(frozen=True)
class ResearchDataset:
    universe_snapshot_id: str
    dataset_snapshot_ids: dict[str, str | None]
    panel: pd.DataFrame
    benchmark_symbol: str | None = None
    benchmark_provider_symbol: str | None = None
    benchmark_relationship: str | None = None
    exclusions: pd.DataFrame = field(default_factory=pd.DataFrame)
    survivorship_bias: bool = True
    universe_name: str = "NIFTY200"
    source_basis: str = "UNADJUSTED"
    canonical_basis: str = "SPLIT_ADJUSTED"
    research_basis: str = "SPLIT_ADJUSTED"
    corporate_action_version: str = "v1"
    frame_certification_id: str | None = None
    contributing_dataset_ids: tuple[str, ...] = ()
    dq_certification_ids: tuple[str, ...] = ()
    dataset_content_hashes: dict[str, str] = field(default_factory=dict)
    pit_evidence_hash: str | None = None

    @property
    def data_hash(self) -> str:
        frame = self.panel.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(frame, index=False, categorize=True).values.tobytes()
        )
        digest.update(json.dumps({
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_name": self.universe_name,
            "dataset_snapshot_ids": self.dataset_snapshot_ids,
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_provider_symbol": self.benchmark_provider_symbol,
            "benchmark_relationship": self.benchmark_relationship,
            "research_basis": self.research_basis,
            "corporate_action_version": self.corporate_action_version,
            "contributing_dataset_ids": self.contributing_dataset_ids,
            "dq_certification_ids": self.dq_certification_ids,
            "dataset_content_hashes": self.dataset_content_hashes,
            "pit_evidence_hash": self.pit_evidence_hash,
        }, sort_keys=True, default=str).encode())
        return digest.hexdigest()

    def calculate_dataset_hash(self) -> str:
        """Deterministic fingerprint of raw data + corporate action revision."""
        digest = hashlib.sha256()
        frame = self.panel.drop(columns=["benchmark_close"], errors="ignore")
        digest.update(
            pd.util.hash_pandas_object(frame, index=False, categorize=True).values.tobytes()
        )
        digest.update(json.dumps({
            "universe_snapshot_id": self.universe_snapshot_id,
            "universe_name": self.universe_name,
            "dataset_snapshot_ids": self.dataset_snapshot_ids,
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_provider_symbol": self.benchmark_provider_symbol,
            "benchmark_relationship": self.benchmark_relationship,
            "research_basis": self.research_basis,
            "corporate_action_version": self.corporate_action_version,
        }, sort_keys=True, default=str).encode())
        return digest.hexdigest()


class SynchronizedPanelBuilder:
    """Load each symbol once and build causal per-symbol features."""

    _panel_cache: ClassVar[dict[tuple[object, ...], ResearchDataset]] = {}
    _panel_cache_lock: ClassVar[Lock] = Lock()

    def __init__(
        self,
        db: DuckDBManager,
        feature_factory: FeatureFactory | None = None,
        calendar: MarketCalendar | None = None,
        strict_calendar: bool = False,
        require_authoritative_certification: bool = True,
    ) -> None:
        self.db = db
        self.feature_factory = feature_factory or FeatureFactory()
        self.calendar = calendar or build_default_calendars()[AssetClass.INDIA_EQUITY]
        self.strict_calendar = strict_calendar
        self.require_authoritative_certification = require_authoritative_certification

    def build(
        self,
        symbols: list[str],
        timeframe: str,
        *,
        universe_snapshot_id: str = "CONFIGURED_UNIVERSE",
        universe_name: str | None = None,
        benchmark_symbol: str | None = "NIFTY",
        minimum_lookback: int = 1,
        adjustment: str | PriceAdjustment = PriceAdjustment.SPLIT_ADJUSTED,
    ) -> ResearchDataset:
        """Reuse one immutable featured panel and derive strategy-specific eligibility."""

        resolved_adjustment = (
            adjustment.value if isinstance(adjustment, PriceAdjustment) else str(adjustment).upper()
        )
        resolved_universe_name = universe_name or (
            "NIFTY200" if "NIFTY200" in universe_snapshot_id.upper() or "NIFTY_200" in universe_snapshot_id.upper() else universe_snapshot_id
        )

        feature_config = tuple(
            (item.name, getattr(self.feature_factory, item.name))
            for item in fields(self.feature_factory)
        )
        key = (
            str(self.db.db_path), tuple(symbols), timeframe, universe_snapshot_id, resolved_universe_name,
            benchmark_symbol, feature_config, self.db.market_data_revision(), resolved_adjustment,
        )
        with self._panel_cache_lock:
            cached = self._panel_cache.get(key)
            if cached is None:
                cached = self._build_uncached(
                    symbols,
                    timeframe,
                    universe_snapshot_id=universe_snapshot_id,
                    universe_name=resolved_universe_name,
                    benchmark_symbol=benchmark_symbol,
                    minimum_lookback=1,
                    adjustment=resolved_adjustment,
                )
                self._panel_cache[key] = cached
        panel = cached.panel.copy()
        panel["eligible"] = panel.groupby("symbol").cumcount() + 1 >= minimum_lookback
        if "pit_eligible" in panel:
            panel["eligible"] &= panel["pit_eligible"]
        if "benchmark_close" in panel:
            panel["eligible"] &= panel["benchmark_close"].notna()
        return ResearchDataset(
            universe_snapshot_id=cached.universe_snapshot_id,
            dataset_snapshot_ids=dict(cached.dataset_snapshot_ids),
            panel=panel,
            benchmark_symbol=cached.benchmark_symbol,
            benchmark_provider_symbol=cached.benchmark_provider_symbol,
            benchmark_relationship=cached.benchmark_relationship,
            exclusions=cached.exclusions.copy(),
            survivorship_bias=cached.survivorship_bias,
            universe_name=cached.universe_name,
            source_basis=cached.source_basis,
            canonical_basis=cached.canonical_basis,
            research_basis=cached.research_basis,
            corporate_action_version=cached.corporate_action_version,
            frame_certification_id=cached.frame_certification_id,
            contributing_dataset_ids=tuple(cached.contributing_dataset_ids),
            dq_certification_ids=tuple(cached.dq_certification_ids),
            dataset_content_hashes=dict(cached.dataset_content_hashes),
            pit_evidence_hash=cached.pit_evidence_hash,
        )

    def _build_uncached(
        self,
        symbols: list[str],
        timeframe: str,
        *,
        universe_snapshot_id: str = "CONFIGURED_UNIVERSE",
        universe_name: str = "NIFTY200",
        benchmark_symbol: str | None = "NIFTY",
        minimum_lookback: int = 1,
        adjustment: str | PriceAdjustment = PriceAdjustment.SPLIT_ADJUSTED,
    ) -> ResearchDataset:
        if not symbols:
            raise ValueError("A synchronized dataset requires at least one symbol.")
        resolved_adjustment = (
            adjustment.value if isinstance(adjustment, PriceAdjustment) else str(adjustment).upper()
        )
        logger.bind(
            event="panel_build_started",
            symbol_count=len(symbols),
            timeframe=timeframe,
            universe_snapshot_id=universe_snapshot_id,
            universe_name=universe_name,
            adjustment=resolved_adjustment,
        ).info("panel_build_started")
        panels: list[pd.DataFrame] = []
        exclusions: list[dict[str, object]] = []
        dataset_ids: dict[str, str | None] = {}
        sectors = self._sector_map(symbols, universe_snapshot_id)
        resolved_benchmark, benchmark_relationship = self._resolve_benchmark(benchmark_symbol, timeframe)
        benchmark = self._load_bars(resolved_benchmark, timeframe, adjustment=resolved_adjustment) if resolved_benchmark else pd.DataFrame()
        if benchmark_symbol and benchmark.empty:
            raise ValueError(
                f"Benchmark {benchmark_symbol} {timeframe} has no stored candle data or approved provider mapping."
            )
        benchmark_close = benchmark[["timestamp", "close"]].rename(columns={"close": "benchmark_close"}) if not benchmark.empty else pd.DataFrame()
        adjustment_states: set[str] = set()
        for index, symbol in enumerate(symbols, start=1):
            bars = self._load_bars(symbol, timeframe, adjustment=resolved_adjustment)
            if bars.empty:
                exclusions.append({"symbol": symbol, "reason": "MISSING_DATA", "timestamp": pd.NaT})
                dataset_ids[symbol] = None
                continue
            bars = self._valid_sessions(bars, timeframe)
            if bars.empty:
                exclusions.append({"symbol": symbol, "reason": "NO_VALID_SESSIONS", "timestamp": pd.NaT})
                dataset_ids[symbol] = None
                continue
            adjustment_states.update(str(value) for value in bars["adjustment"].dropna().unique())
            featured = self.feature_factory.build(bars, timezone_name="Asia/Kolkata")
            featured["symbol"] = symbol
            featured["sector"] = sectors.get(symbol, "UNKNOWN")
            featured["eligible"] = featured.groupby("symbol").cumcount() + 1 >= minimum_lookback
            if not benchmark_close.empty:
                if symbol == benchmark_symbol:
                    featured["benchmark_close"] = featured["close"]
                else:
                    featured = featured.merge(benchmark_close, on="timestamp", how="left")
            panels.append(featured)
            # Rows, not a mutable "latest dataset" lookup, define provenance.
            exact_ids = [str(value) for value in bars["dataset_id"].dropna().unique() if str(value)]
            dataset_ids[symbol] = exact_ids[-1] if len(exact_ids) == 1 else None
            if index % 25 == 0 or index == len(symbols):
                logger.bind(
                    event="panel_build_progress",
                    processed_symbols=index,
                    total_symbols=len(symbols),
                    included_symbols=len(panels),
                    excluded_symbols=len(exclusions),
                    timeframe=timeframe,
                ).info("panel_build_progress")
        if len(adjustment_states) > 1:
            raise ValueError("Synchronized panels cannot mix adjusted and unadjusted series.")
        if not panels:
            raise ValueError("No requested symbols have stored candle data.")
        panel = pd.concat(panels, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        
        # Point-In-Time Universe Filtering
        survivorship_bias = True
        try:
            pit_rows: list[tuple[str, Any, Any]] = []
            if universe_name and universe_name != "CONFIGURED_UNIVERSE":
                pit_rows = self.db.conn.execute(
                    """
                    SELECT symbol, effective_from, effective_until 
                    FROM index_constituents_pit 
                    WHERE UPPER(universe_name) = ?
                    """,
                    [universe_name.upper()],
                ).fetchall()

            is_named_index = False
            if (universe_name and universe_name not in {"CONFIGURED_UNIVERSE", "CUSTOM", ""}) or (
                universe_snapshot_id and universe_snapshot_id not in {"CONFIGURED_UNIVERSE", "CUSTOM", ""}
            ):
                is_named_index = True

            if pit_rows:
                pit_df = pd.DataFrame(pit_rows, columns=["symbol", "effective_from", "effective_until"])
                pit_df["effective_from"] = pd.to_datetime(pit_df["effective_from"]).dt.date
                pit_df["effective_until"] = pd.to_datetime(pit_df["effective_until"]).dt.date
                
                panel_dates = pd.to_datetime(panel["timestamp"]).dt.tz_convert(self.calendar.zone).dt.date
                
                # Validate interval integrity
                invalid_intervals = pit_df[pit_df["effective_until"].notna() & (pit_df["effective_from"] >= pit_df["effective_until"])]
                if not invalid_intervals.empty:
                    raise RuntimeError(f"Corrupt point-in-time intervals for '{universe_name}': effective_from >= effective_until.")

                if not panel.empty:
                    min_panel_date = panel_dates.min()
                    max_panel_date = panel_dates.max()
                    min_pit_date = pit_df["effective_from"].min()
                    if min_pit_date and min_pit_date > min_panel_date:
                        raise RuntimeError(
                            f"PIT membership evidence for '{universe_name}' begins on {min_pit_date}, which does not cover requested research start date {min_panel_date}. Failing closed to prevent survivorship bias."
                        )
                    max_pit_date = pit_df["effective_until"].dropna().max()
                    if max_pit_date and max_pit_date < max_panel_date:
                        raise RuntimeError(
                            f"PIT membership evidence for '{universe_name}' ends on {max_pit_date}, which does not cover requested research end date {max_panel_date}. Failing closed to prevent survivorship bias."
                        )

                panel_syms = panel["symbol"].values
                is_member_mask = np.zeros(len(panel), dtype=bool)
                for sym, grp in pit_df.groupby("symbol"):
                    sym_indices = np.where(panel_syms == sym)[0]
                    if len(sym_indices) == 0:
                        continue
                    sym_dates = panel_dates.iloc[sym_indices].values
                    for _, row in grp.iterrows():
                        eff_from = row["effective_from"]
                        eff_until = row["effective_until"]
                        if pd.isna(eff_until) or eff_until is None:
                            in_interval = sym_dates >= eff_from
                        else:
                            in_interval = (sym_dates >= eff_from) & (sym_dates < eff_until)
                        is_member_mask[sym_indices[in_interval]] = True
                
                panel["pit_eligible"] = is_member_mask
                panel["eligible"] &= panel["pit_eligible"]
                survivorship_bias = False
            elif is_named_index:
                raise RuntimeError(
                    f"Missing point-in-time constituent history for universe '{universe_name}'. "
                    f"Point-in-time constituent history is mandatory to eliminate survivorship bias."
                )
            else:
                panel["pit_eligible"] = True
                survivorship_bias = True
        except Exception as exc:
            logger.error("PIT universe filtering failed for universe {}: {}", universe_name, exc)
            if isinstance(exc, RuntimeError):
                raise
            if universe_name and universe_name != "CONFIGURED_UNIVERSE":
                raise RuntimeError(f"Point-in-time universe lookup failed for '{universe_name}': {exc}. Failing closed to prevent survivorship bias.") from exc
            panel["pit_eligible"] = True
            survivorship_bias = True

        if "benchmark_close" in panel:
            panel["eligible"] &= panel["benchmark_close"].notna()
        reference_timestamps = set(
            pd.to_datetime(benchmark_close["timestamp"], utc=True)
            if not benchmark_close.empty else pd.to_datetime(panel["timestamp"], utc=True)
        )
        for symbol, group in panel.groupby("symbol"):
            observed = set(pd.to_datetime(group["timestamp"], utc=True))
            first, last = min(observed), max(observed)
            for timestamp in sorted(reference_timestamps.difference(observed)):
                if first <= timestamp <= last:
                    exclusions.append({
                        "symbol": symbol, "reason": "MISSING_SESSION", "timestamp": timestamp,
                    })
        latest_timestamp = panel["timestamp"].max()
        for symbol, group in panel.groupby("symbol"):
            if group["timestamp"].max() < latest_timestamp:
                exclusions.append({"symbol": symbol, "reason": "STALE_PRICE", "timestamp": group["timestamp"].max()})
        duplicates = panel.duplicated(["timestamp", "symbol"])
        if duplicates.any():
            raise ValueError("Synchronized panel contains duplicate symbol timestamps.")
        logger.bind(
            event="panel_build_finished",
            panel_rows=len(panel),
            included_symbols=int(panel["symbol"].nunique()),
            exclusion_records=len(exclusions),
            timeframe=timeframe,
            survivorship_bias=survivorship_bias,
        ).info("panel_build_finished")
        result = ResearchDataset(
            universe_snapshot_id=universe_snapshot_id,
            dataset_snapshot_ids=dataset_ids,
            panel=panel,
            benchmark_symbol=benchmark_symbol,
            benchmark_provider_symbol=resolved_benchmark,
            benchmark_relationship=benchmark_relationship,
            exclusions=pd.DataFrame(exclusions),
            survivorship_bias=survivorship_bias,
            universe_name=universe_name,
            source_basis="UNADJUSTED",
            canonical_basis="SPLIT_ADJUSTED",
            research_basis=resolved_adjustment,
            corporate_action_version="v1",
            contributing_dataset_ids=tuple(sorted({str(value) for value in panel["dataset_id"].dropna() if str(value)})),
        )
        if self.require_authoritative_certification:
            contributing_ids = list(result.contributing_dataset_ids)
            dataset_hashes: dict[str, str] = {}
            dq_certification_ids: list[str] = []
            for dataset_id in contributing_ids:
                row = self.db.conn.execute(
                    "SELECT transformation_hash, raw_hash, status, lifecycle_status FROM market_datasets WHERE dataset_id = ?",
                    [dataset_id],
                ).fetchone()
                if not row or str(row[2]) != "VERIFIED" or str(row[3]) != "CANONICAL_PROMOTED":
                    raise DataQualityError(
                        f"Dataset {dataset_id} has status={row[2] if row else 'NONE'}, "
                        f"lifecycle={row[3] if row else 'NONE'}; must be VERIFIED and CANONICAL_PROMOTED."
                    )
                if not (row[0] or row[1]):
                    raise DataQualityError(f"Dataset {dataset_id} has no immutable content hash.")
                ds_hash = str(row[0] or row[1])
                dataset_hashes[dataset_id] = ds_hash

                certs = self.db.conn.execute(
                    """SELECT certification_id, validator_version, checks_json 
                       FROM data_quality_certifications 
                       WHERE dataset_id = ? AND status = 'CERTIFIED' AND issue_count = 0 
                       ORDER BY completed_at DESC""",
                    [dataset_id],
                ).fetchall()
                matched_cert_id = None
                for c in certs:
                    c_id, val_ver, checks_json_str = str(c[0]), str(c[1] or "").strip(), str(c[2] or "{}")
                    if not val_ver:
                        continue
                    try:
                        checks_data = json.loads(checks_json_str)
                    except Exception:
                        checks_data = {}
                    if checks_data.get("dataset_content_hash") == ds_hash:
                        quality_rows = self.db.conn.execute(
                            "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?",
                            [c_id],
                        ).fetchall()
                        observed = {r[0] for r in quality_rows if int(r[1]) == 0}
                        if observed == REQUIRED_AUTHORITATIVE_DQ_CHECKS and len(quality_rows) == 6:
                            matched_cert_id = c_id
                            break
                if not matched_cert_id:
                    raise DataQualityError(f"Dataset {dataset_id} has no certified DQ evidence bound to content hash {ds_hash}.")
                dq_certification_ids.append(matched_cert_id)
            pit_evidence_hash = self._pit_evidence_hash(universe_name) if universe_name else None
            frame_certification_id = str(uuid.uuid4())
            self.db.conn.execute(
                """INSERT INTO research_frame_certifications (
                       frame_certification_id, research_frame_hash, contributing_dataset_ids_json,
                       symbol, timeframe, row_count, basis, validator_version, status, verified_at,
                       dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CERTIFIED', CURRENT_TIMESTAMP, ?, ?, ?)""",
                [
                    frame_certification_id,
                    result.data_hash,
                    json.dumps(sorted(set(contributing_ids))),
                    f"PORTFOLIO:{universe_snapshot_id}",
                    timeframe,
                    len(panel),
                    resolved_adjustment,
                    "validator-v1",
                    json.dumps(dataset_hashes, sort_keys=True),
                    json.dumps(sorted(dq_certification_ids)),
                    pit_evidence_hash,
                ],
            )
            result = ResearchDataset(
                **{**result.__dict__, "frame_certification_id": frame_certification_id,
                   "dq_certification_ids": tuple(sorted(dq_certification_ids)),
                   "dataset_content_hashes": dataset_hashes,
                   "pit_evidence_hash": pit_evidence_hash}
            )
        return result

    def _pit_evidence_hash(self, universe_name: str) -> str:
        rows = self.db.conn.execute(
            """SELECT universe_name, instrument_id, symbol, token, exchange, 
                      effective_from, effective_until, known_from, weight, 
                      inclusion_reason, exclusion_reason 
               FROM index_constituents_pit 
               WHERE UPPER(universe_name) = ? 
               ORDER BY symbol, effective_from, effective_until, instrument_id""",
            [universe_name.upper()],
        ).fetchall()
        return hashlib.sha256(json.dumps(rows, default=str, separators=(",", ":")).encode()).hexdigest()

    def _resolve_benchmark(self, symbol: str | None, timeframe: str) -> tuple[str | None, str | None]:
        if not symbol:
            return None, None
        if not self._load_bars(symbol, timeframe).empty:
            return symbol, "EXACT"
        row = self.db.conn.execute(
            """SELECT provider_symbol, relationship FROM benchmark_aliases
               WHERE canonical_symbol = ? AND approved_for_research
               ORDER BY CASE relationship WHEN 'EXACT' THEN 0 ELSE 1 END LIMIT 1""",
            [symbol],
        ).fetchone()
        return (str(row[0]), str(row[1])) if row else (symbol, None)

    def _valid_sessions(self, bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        timestamps = pd.to_datetime(bars["timestamp"], utc=True)
        if self.strict_calendar:
            validation = self.calendar.validate_bars(timestamps, timeframe)
            if validation.out_of_session_count:
                raise ValueError(
                    f"Dataset contains {validation.out_of_session_count} bars outside calendar "
                    f"{self.calendar.version}: {list(validation.out_of_session)}."
                )
        local = timestamps.dt.tz_convert(self.calendar.zone)
        if timeframe == "1d":
            valid = local.map(lambda value: self.calendar.is_trading_day(value.date()))
        else:
            valid = local.map(lambda value: self.calendar.is_session_open(value.to_pydatetime()))
        return bars.loc[valid.to_numpy()].reset_index(drop=True)

    def _load_bars(
        self,
        symbol: str | None,
        timeframe: str,
        adjustment: PriceAdjustment | str = PriceAdjustment.SPLIT_ADJUSTED,
        require_authoritative_certification: bool | None = None,
    ) -> pd.DataFrame:
        if not symbol:
            return pd.DataFrame()
        frame = self.db.conn.execute(
            """SELECT symbol, exchange, timeframe, timestamp, open, high, low, close, volume,
                      adjustment, provider_name, dataset_id
               FROM historical_candles WHERE symbol = ? AND timeframe = ? ORDER BY timestamp""",
            [symbol, timeframe],
        ).df()
        adj_enum = (
            adjustment if isinstance(adjustment, PriceAdjustment)
            else PriceAdjustment(str(getattr(adjustment, "value", adjustment)).upper())
        )
        if not frame.empty:
            ca_df = self.db.get_corporate_actions(symbol)
            frame = PriceAdjustmentEngine.adjust_ohlcv(frame, ca_df, adjustment=adj_enum)

            must_certify = self.require_authoritative_certification if require_authoritative_certification is None else require_authoritative_certification
            if must_certify:
                contributing_dataset_ids = [
                    str(x).strip() for x in frame["dataset_id"].dropna().unique() if str(x).strip()
                ]
                null_dataset_count = int(frame["dataset_id"].isna().sum()) + int((frame["dataset_id"] == "").sum())
                if null_dataset_count > 0 or not contributing_dataset_ids:
                    raise DataQualityError(
                        f"DataQualityError: {null_dataset_count} uncertified candle rows present with NULL dataset_id for {symbol} {timeframe} in panel build."
                    )
                for ds_id in contributing_dataset_ids:
                    ds_record = self.db.conn.execute(
                        "SELECT status, lifecycle_status, transformation_hash, raw_hash FROM market_datasets WHERE dataset_id = ?",
                        [ds_id],
                    ).fetchone()
                    if not ds_record or ds_record[0] != "VERIFIED" or ds_record[1] != "CANONICAL_PROMOTED":
                        raise DataQualityError(
                            f"DataQualityError: Dataset {ds_id} contributing to {symbol} {timeframe} in panel build has status={ds_record[0] if ds_record else 'NONE'}; must be VERIFIED and CANONICAL_PROMOTED."
                        )
                    ds_hash = str(ds_record[2] or ds_record[3] or "")
                    if not ds_hash:
                        raise DataQualityError(f"DataQualityError: Dataset {ds_id} has no immutable content hash.")
                    
                    certs = self.db.conn.execute(
                        """SELECT certification_id, validator_version, checks_json 
                           FROM data_quality_certifications 
                           WHERE dataset_id = ? AND status = 'CERTIFIED' AND issue_count = 0 
                           ORDER BY completed_at DESC""",
                        [ds_id],
                    ).fetchall()
                    matched_cert_id = None
                    for c in certs:
                        c_id, val_ver, checks_json_str = str(c[0]), str(c[1] or "").strip(), str(c[2] or "{}")
                        if not val_ver:
                            continue
                        try:
                            checks_data = json.loads(checks_json_str)
                        except Exception:
                            checks_data = {}
                        if checks_data.get("dataset_content_hash") == ds_hash:
                            quality_rows = self.db.conn.execute(
                                "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?",
                                [c_id],
                            ).fetchall()
                            observed = {r[0] for r in quality_rows if int(r[1]) == 0}
                            if observed == REQUIRED_AUTHORITATIVE_DQ_CHECKS and len(quality_rows) == 6:
                                matched_cert_id = c_id
                                break
                    if not matched_cert_id:
                        raise DataQualityError(
                            f"DataQualityError: Contributing dataset {ds_id} for {symbol} {timeframe} in panel build lacks active CERTIFIED batch bound to hash {ds_hash}."
                        )
        return frame

    def _latest_dataset_id(self, symbol: str, timeframe: str) -> str | None:
        row = self.db.conn.execute(
            """SELECT dataset_id FROM market_datasets 
               WHERE (canonical_symbol = ? OR symbol = ?) 
                 AND timeframe = ? 
                 AND lifecycle_status = 'CANONICAL_PROMOTED' 
                 AND status = 'VERIFIED'
               ORDER BY retrieved_at DESC LIMIT 1""",
            [symbol, symbol, timeframe],
        ).fetchone()
        return str(row[0]) if row else None

    def _sector_map(self, symbols: list[str], snapshot_id: str) -> dict[str, str]:
        try:
            rows = self.db.conn.execute(
                "SELECT symbol, provider_symbol, sector FROM universe_snapshot_members WHERE snapshot_id = ?",
                [snapshot_id],
            ).fetchall()
            requested = set(symbols)
            mapping: dict[str, str] = {}
            for symbol, provider_symbol, sector in rows:
                sector_str = str(sector).strip() if sector else ""
                for candidate in (symbol, provider_symbol):
                    if candidate is not None and str(candidate) in requested and sector_str and sector_str != "UNKNOWN":
                        mapping[str(candidate)] = sector_str
            if snapshot_id and snapshot_id != "CONFIGURED_UNIVERSE":
                is_registered_row = self.db.conn.execute(
                    "SELECT COUNT(*) FROM universe_snapshots WHERE snapshot_id = ?",
                    [snapshot_id],
                ).fetchone()
                is_registered = bool(is_registered_row and is_registered_row[0] > 0)
                if is_registered or snapshot_id.startswith("NIFTY"):
                    missing = [s for s in symbols if s not in mapping]
                    if missing:
                        raise ValueError(
                            f"Missing authoritative sector mapping for symbol(s): {missing} in snapshot '{snapshot_id}'. "
                            "Sector evidence is mandatory to enforce portfolio sector risk limits."
                        )
            return mapping
        except Exception as exc:
            logger.error("Failed to load sector mapping for snapshot {}: {}", snapshot_id, exc)
            if isinstance(exc, ValueError):
                raise
            if snapshot_id:
                raise RuntimeError(
                    f"Failed to load sector mapping for universe snapshot '{snapshot_id}': {exc}. "
                    f"Failing closed to prevent unconstrained sector exposure."
                ) from exc
            return {}
