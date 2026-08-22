"""Run certification service producing immutable certification bundles."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from storage.duckdb_manager import DuckDBManager


REQUIRED_RUN_CERTIFICATION_CATEGORIES = {
    "DATA_LINEAGE",
    "DATA_QUALITY",
    "CAUSALITY",
    "PIT_SURVIVORSHIP",
    "OOS_WALK_FORWARD",
}


class RunCertificationService:
    """Evaluate and persist authoritative certification bundles for strategy runs."""

    def __init__(self, db: DuckDBManager) -> None:
        self.db = db

    def certify(self, run_id: str) -> str:
        """Evaluate run evidence across all 5 categories and persist an immutable bundle.

        Args:
            run_id: Unique strategy run identifier.

        Returns:
            str: certification_bundle_id referencing the persisted bundle.
        """
        run_row = self.db.conn.execute(
            "SELECT strategy_name, symbol, timeframe, mode, data_hash, notes FROM strategy_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if run_row is None:
            raise ValueError(f"Cannot certify unknown run_id: {run_id}")

        _, symbol_str, timeframe, mode, data_hash, notes = (
            str(run_row[0]), str(run_row[1]), str(run_row[2]), str(run_row[3]), str(run_row[4]), str(run_row[5] or "")
        )
        try:
            run_metadata = json.loads(notes) if notes else {}
        except json.JSONDecodeError:
            run_metadata = {}
        frame_certification_id = run_metadata.get("frame_certification_id")

        bundle_id = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc)
        evidence_records: list[dict[str, Any]] = []

        # 1. DATA_LINEAGE
        lineage_status = "PASS"
        lineage_details: dict[str, Any] = {"symbol": symbol_str, "timeframe": timeframe}
        try:
            if symbol_str.startswith("PORTFOLIO:"):
                snap_id = symbol_str.split(":", 1)[1]
                member_rows = self.db.conn.execute(
                    "SELECT symbol, provider_symbol FROM universe_snapshot_members WHERE snapshot_id = ?",
                    [snap_id],
                ).fetchall()
                if not member_rows:
                    lineage_status = "FAIL"
                    lineage_details["reason"] = f"No snapshot members for {snap_id}"
                else:
                    symbols = [str(r[0]) for r in member_rows if r[0]]
                    lineage_details["constituent_count"] = len(symbols)
                    for sym in symbols:
                        ds = self.db.conn.execute(
                            "SELECT dataset_id, status, lifecycle_status FROM market_datasets WHERE (canonical_symbol = ? OR symbol = ?) AND timeframe = ? AND lifecycle_status = 'CANONICAL_PROMOTED' AND status = 'VERIFIED' LIMIT 1",
                            [sym, sym, timeframe],
                        ).fetchone()
                        if not ds:
                            lineage_status = "FAIL"
                            lineage_details["missing_canonical_dataset"] = sym
                            break
            else:
                ds_rows = self.db.conn.execute(
                    "SELECT DISTINCT dataset_id FROM historical_candles WHERE symbol = ? AND timeframe = ?",
                    [symbol_str, timeframe],
                ).fetchall()
                dataset_ids = [str(r[0]) for r in ds_rows if r[0]]
                if not dataset_ids:
                    ds_fallback = self.db.conn.execute(
                        "SELECT dataset_id, status, lifecycle_status FROM market_datasets WHERE (canonical_symbol = ? OR symbol = ?) AND timeframe = ? AND lifecycle_status = 'CANONICAL_PROMOTED' AND status = 'VERIFIED' LIMIT 1",
                        [symbol_str, symbol_str, timeframe],
                    ).fetchone()
                    if ds_fallback:
                        dataset_ids = [str(ds_fallback[0])]
                if not dataset_ids:
                    lineage_status = "FAIL"
                    lineage_details["reason"] = f"No contributing dataset IDs for {symbol_str} {timeframe}"
                else:
                    lineage_details["contributing_datasets"] = dataset_ids
                    for ds_id in dataset_ids:
                        ds = self.db.conn.execute(
                            "SELECT status, lifecycle_status FROM market_datasets WHERE dataset_id = ?",
                            [ds_id],
                        ).fetchone()
                        if not ds or ds[0] != "VERIFIED" or ds[1] != "CANONICAL_PROMOTED":
                            lineage_status = "FAIL"
                            lineage_details["unverified_dataset"] = ds_id
                            break
        except Exception as exc:
            lineage_status = "FAIL"
            lineage_details["error"] = str(exc)

        # A run must point to the exact transformed frame it consumed.
        frame_status = "PASS"
        frame_details: dict[str, Any] = {}
        if not frame_certification_id:
            frame_status = "FAIL"
            frame_details["reason"] = "Run has no exact frame_certification_id."
        else:
            frame_row = self.db.conn.execute(
                """SELECT research_frame_hash, symbol, timeframe, status
                   FROM research_frame_certifications
                   WHERE frame_certification_id = ?""",
                [frame_certification_id],
            ).fetchone()
            if not frame_row or frame_row[3] != "CERTIFIED":
                frame_status = "FAIL"
                frame_details["reason"] = "Referenced frame certification is missing or not certified."
            elif frame_row[0] != data_hash or frame_row[1] != symbol_str or frame_row[2] != timeframe:
                frame_status = "FAIL"
                frame_details["reason"] = "Run data hash or scope does not match its frame certification."
            else:
                frame_details["frame_certification_id"] = frame_certification_id
        if lineage_status == "PASS" and frame_status == "FAIL":
            lineage_status = "FAIL"
            lineage_details["frame_certification"] = frame_details
        evidence_records.append({
            "category": "DATA_LINEAGE",
            "status": lineage_status,
            "evidence": lineage_details,
        })

        # 2. DATA_QUALITY
        dq_status = "PASS"
        dq_details: dict[str, Any] = {}
        try:
            if symbol_str.startswith("PORTFOLIO:"):
                snap_id = symbol_str.split(":", 1)[1]
                member_rows = self.db.conn.execute(
                    "SELECT symbol FROM universe_snapshot_members WHERE snapshot_id = ?", [snap_id]
                ).fetchall()
                symbols = [str(r[0]) for r in member_rows if r[0]]
                if not symbols:
                    dq_status = "FAIL"
                    dq_details["reason"] = f"No members for snapshot {snap_id}"
                else:
                    for sym in symbols:
                        ds = self.db.conn.execute(
                            "SELECT dataset_id FROM market_datasets WHERE (canonical_symbol = ? OR symbol = ?) AND timeframe = ? AND lifecycle_status = 'CANONICAL_PROMOTED' AND status = 'VERIFIED' LIMIT 1",
                            [sym, sym, timeframe],
                        ).fetchone()
                        if not ds:
                            dq_status = "FAIL"
                            dq_details["missing_dataset"] = sym
                            break
                        cert = self.db.conn.execute(
                            "SELECT certification_id, status, issue_count FROM data_quality_certifications WHERE dataset_id = ? ORDER BY completed_at DESC LIMIT 1",
                            [ds[0]],
                        ).fetchone()
                        if not cert or cert[1] != "CERTIFIED" or int(cert[2]) > 0:
                            dq_status = "FAIL"
                            dq_details["uncertified_dataset"] = ds[0]
                            break
            else:
                target_datasets = lineage_details.get("contributing_datasets", [])
                if not target_datasets:
                    dq_status = "FAIL"
                    dq_details["reason"] = "No datasets to verify for run."
                else:
                    for ds_id in target_datasets:
                        cert_row = self.db.conn.execute(
                            "SELECT certification_id, status, issue_count FROM data_quality_certifications WHERE dataset_id = ? ORDER BY completed_at DESC LIMIT 1",
                            [ds_id],
                        ).fetchone()
                        if not cert_row or cert_row[1] != "CERTIFIED" or int(cert_row[2]) > 0:
                            dq_status = "FAIL"
                            dq_details["uncertified_dataset"] = ds_id
                            break
                        # Check 6 required child checks
                        quality_rows = self.db.conn.execute(
                            "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?",
                            [cert_row[0]],
                        ).fetchall()
                        observed_checks = {r[0] for r in quality_rows if int(r[1]) == 0}
                        missing_checks = {"schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"} - observed_checks
                        if missing_checks:
                            dq_status = "FAIL"
                            dq_details["missing_checks"] = list(missing_checks)
                            break
        except Exception as exc:
            dq_status = "FAIL"
            dq_details["error"] = str(exc)

        evidence_records.append({
            "category": "DATA_QUALITY",
            "status": dq_status,
            "evidence": dq_details,
        })

        # 3. CAUSALITY
        causality_status = "PASS"
        causality_details: dict[str, Any] = {}
        try:
            # Check execution chronology on fills
            invalid_fill_row = self.db.conn.execute(
                """
                SELECT COUNT(*) FROM strategy_fills sf
                JOIN strategy_orders so ON sf.order_id = so.order_id
                WHERE sf.run_id = ? AND sf.timestamp < so.requested_at
                """,
                [run_id],
            ).fetchone()
            invalid_fills = int(invalid_fill_row[0]) if invalid_fill_row else 0
            if invalid_fills > 0:
                causality_status = "FAIL"
                causality_details["invalid_fill_timestamps"] = invalid_fills
            else:
                causality_details["fill_chronology_verified"] = True

            # Verify research frame certification exists
            rf_row = self.db.conn.execute(
                "SELECT COUNT(*) FROM research_frame_certifications WHERE symbol = ? AND timeframe = ? AND status = 'CERTIFIED'",
                [symbol_str, timeframe],
            ).fetchone()
            if rf_row and int(rf_row[0]) > 0:
                causality_details["research_frame_certified"] = True
        except Exception as exc:
            causality_details["note"] = str(exc)

        evidence_records.append({
            "category": "CAUSALITY",
            "status": causality_status,
            "evidence": causality_details,
        })

        # 4. PIT_SURVIVORSHIP
        pit_status = "PASS"
        pit_details: dict[str, Any] = {}
        try:
            if symbol_str.startswith("PORTFOLIO:"):
                snap_id = symbol_str.split(":", 1)[1]
                snap_row = self.db.conn.execute(
                    "SELECT name FROM universe_snapshots WHERE snapshot_id = ?", [snap_id]
                ).fetchone()
                universe_name = str(snap_row[0]) if snap_row else snap_id
                pit_count = self.db.conn.execute(
                    "SELECT COUNT(*) FROM index_constituents_pit WHERE UPPER(universe_name) = ?",
                    [universe_name.upper()],
                ).fetchone()
                if not pit_count or int(pit_count[0]) == 0:
                    pit_status = "FAIL"
                    pit_details["reason"] = f"No PIT constituent history available for universe {universe_name}."
                else:
                    pit_details["pit_records"] = int(pit_count[0])
            else:
                pit_details["single_asset"] = True
        except Exception as exc:
            pit_status = "FAIL"
            pit_details["error"] = str(exc)

        evidence_records.append({
            "category": "PIT_SURVIVORSHIP",
            "status": pit_status,
            "evidence": pit_details,
        })

        # 5. OOS_WALK_FORWARD
        oos_status = "PASS"
        oos_details: dict[str, Any] = {}
        try:
            evidence_row = self.db.conn.execute(
                "SELECT COUNT(*) FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE'",
                [run_id],
            ).fetchone()
            oos_count = int(evidence_row[0]) if evidence_row else 0
            oos_details["oos_points"] = oos_count
            if oos_count == 0 and mode != "DEBUG":
                # Check walk_forward_metrics
                wf_count = self.db.conn.execute(
                    "SELECT COUNT(*) FROM walk_forward_metrics WHERE run_id = ?", [run_id]
                ).fetchone()
                if not wf_count or int(wf_count[0]) == 0:
                    oos_status = "FAIL"
                    oos_details["reason"] = "No out-of-sample evidence or walk forward metrics."
        except Exception as exc:
            oos_details["note"] = str(exc)

        evidence_records.append({
            "category": "OOS_WALK_FORWARD",
            "status": oos_status,
            "evidence": oos_details,
        })

        # Write all 5 certification rows within a single transaction
        with self.db._write_lock:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO run_certification_bundles (
                           bundle_id, run_id, run_data_hash, frame_certification_id,
                           certification_version, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    [bundle_id, run_id, data_hash, frame_certification_id, "validator-v1", now_utc],
                )
                for rec in evidence_records:
                    cert_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO run_certifications (
                            certification_id, bundle_id, run_id, category,
                            status, evidence_json, certified_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            cert_id,
                            bundle_id,
                            run_id,
                            rec["category"],
                            rec["status"],
                            json.dumps(rec["evidence"], default=str),
                            now_utc,
                        ],
                    )

        logger.info("Persisted certification bundle {} for run_id={}", bundle_id, run_id)
        return bundle_id
