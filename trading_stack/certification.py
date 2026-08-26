"""Run certification service producing immutable certification bundles."""

from __future__ import annotations

import hashlib
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
            "SELECT strategy_name, symbol, timeframe, mode, data_hash, notes, frame_certification_id FROM strategy_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if run_row is None:
            raise ValueError(f"Cannot certify unknown run_id: {run_id}")

        _, symbol_str, timeframe, mode, data_hash, notes, stored_frame_certification_id = (
            str(run_row[0]), str(run_row[1]), str(run_row[2]), str(run_row[3]), str(run_row[4]), str(run_row[5] or ""), run_row[6]
        )
        try:
            run_metadata = json.loads(notes) if notes else {}
        except json.JSONDecodeError:
            run_metadata = {}
        # The run column is authoritative. Notes are retained only for
        # readability and must not select evidence for a new run.
        frame_certification_id = str(stored_frame_certification_id) if stored_frame_certification_id else run_metadata.get("frame_certification_id")

        bundle_id = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc)
        evidence_records: list[dict[str, Any]] = []

        # Load exact research frame certification
        frame_dataset_ids: list[str] = []
        dataset_hashes: dict[str, str] = {}
        dq_certification_ids: list[str] = []
        frame_pit_hash: str | None = None
        frame_row = None
        if frame_certification_id:
            frame_row = self.db.conn.execute(
                """SELECT research_frame_hash, symbol, timeframe, status,
                          contributing_dataset_ids_json, dataset_evidence_json,
                          dq_certification_ids_json, pit_evidence_hash
                   FROM research_frame_certifications
                   WHERE frame_certification_id = ?""",
                [frame_certification_id],
            ).fetchone()
            if frame_row:
                try:
                    frame_dataset_ids = [str(v) for v in json.loads(str(frame_row[4] or "[]")) if v]
                except Exception:
                    frame_dataset_ids = []
                try:
                    dataset_hashes = json.loads(str(frame_row[5] or "{}"))
                except Exception:
                    dataset_hashes = {}
                try:
                    dq_certification_ids = [str(v) for v in json.loads(str(frame_row[6] or "[]")) if v]
                except Exception:
                    dq_certification_ids = []
                frame_pit_hash = str(frame_row[7]) if frame_row[7] else None

        # 1. DATA_LINEAGE
        lineage_status = "PASS"
        lineage_details: dict[str, Any] = {"symbol": symbol_str, "timeframe": timeframe}
        try:
            if not frame_certification_id:
                lineage_status = "FAIL"
                lineage_details["reason"] = "Run has no exact frame_certification_id."
            elif not frame_row or str(frame_row[3]) != "CERTIFIED":
                lineage_status = "FAIL"
                lineage_details["reason"] = "Referenced frame certification is missing or not certified."
            elif str(frame_row[0]) != data_hash or str(frame_row[1]) != symbol_str or str(frame_row[2]) != timeframe:
                lineage_status = "FAIL"
                lineage_details["reason"] = "Run data hash or scope does not match its frame certification."
            elif not frame_dataset_ids:
                lineage_status = "FAIL"
                lineage_details["reason"] = "Frame certification has no contributing dataset IDs."
            else:
                lineage_details["contributing_datasets"] = frame_dataset_ids
                lineage_details["frame_certification_id"] = frame_certification_id
                for ds_id in frame_dataset_ids:
                    ds = self.db.conn.execute(
                        "SELECT status, lifecycle_status, transformation_hash, raw_hash FROM market_datasets WHERE dataset_id = ?",
                        [ds_id],
                    ).fetchone()
                    if not ds or str(ds[0]) != "VERIFIED" or str(ds[1]) != "CANONICAL_PROMOTED":
                        lineage_status = "FAIL"
                        lineage_details["unverified_dataset"] = ds_id
                        break
                    current_hash = str(ds[2] or ds[3] or "")
                    if dataset_hashes and dataset_hashes.get(ds_id) and dataset_hashes.get(ds_id) != current_hash:
                        lineage_status = "FAIL"
                        lineage_details["hash_mismatch"] = f"Dataset {ds_id} hash {current_hash} != frame hash {dataset_hashes.get(ds_id)}"
                        break
        except Exception as exc:
            lineage_status = "FAIL"
            lineage_details["error"] = str(exc)

        evidence_records.append({
            "category": "DATA_LINEAGE",
            "status": lineage_status,
            "evidence": lineage_details,
        })

        # 2. DATA_QUALITY
        dq_status = "PASS"
        dq_details: dict[str, Any] = {}
        try:
            if lineage_status == "FAIL":
                dq_status = "FAIL"
                dq_details["reason"] = "Lineage verification failed; DQ cannot pass."
            elif not dq_certification_ids:
                dq_status = "FAIL"
                dq_details["reason"] = "Frame certification contains no bound DQ certification IDs."
            else:
                covered_datasets: set[str] = set()
                for cert_id in dq_certification_ids:
                    cert_row = self.db.conn.execute(
                        "SELECT dataset_id, status, issue_count, validator_version, checks_json FROM data_quality_certifications WHERE certification_id = ?",
                        [cert_id],
                    ).fetchone()
                    if not cert_row or str(cert_row[1]) != "CERTIFIED" or int(cert_row[2]) > 0 or not str(cert_row[3] or "").strip():
                        dq_status = "FAIL"
                        dq_details["invalid_certification"] = cert_id
                        break
                    cert_ds_id = str(cert_row[0])
                    covered_datasets.add(cert_ds_id)
                    if cert_ds_id not in frame_dataset_ids:
                        dq_status = "FAIL"
                        dq_details["unbound_dataset_in_cert"] = cert_ds_id
                        break
                    try:
                        checks_payload = json.loads(str(cert_row[4] or "{}"))
                    except Exception:
                        checks_payload = {}
                    expected_hash = dataset_hashes.get(cert_ds_id)
                    if expected_hash and checks_payload.get("dataset_content_hash") and checks_payload.get("dataset_content_hash") != expected_hash:
                        dq_status = "FAIL"
                        dq_details["cert_content_hash_mismatch"] = cert_id
                        break

                    # Verify exact 6 child checks
                    quality_rows = self.db.conn.execute(
                        "SELECT check_type, issue_count FROM quality_report WHERE certification_id = ?",
                        [cert_id],
                    ).fetchall()
                    observed_checks = {r[0] for r in quality_rows if int(r[1]) == 0}
                    missing_checks = {"schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"} - observed_checks
                    if missing_checks or len(quality_rows) != 6:
                        dq_status = "FAIL"
                        dq_details["missing_checks"] = list(missing_checks)
                        dq_details["failing_cert"] = cert_id
                        break

                if dq_status == "PASS" and covered_datasets != set(frame_dataset_ids):
                    dq_status = "FAIL"
                    dq_details["uncovered_datasets"] = list(set(frame_dataset_ids) - covered_datasets)
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

            # Verify exact research frame certification exists and is certified
            if not frame_certification_id or not frame_row or str(frame_row[3]) != "CERTIFIED" or str(frame_row[0]) != data_hash:
                causality_status = "FAIL"
                causality_details["research_frame_certified"] = False
            else:
                causality_details["research_frame_certified"] = True
        except Exception as exc:
            causality_status = "FAIL"
            causality_details["error"] = str(exc)

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
                pit_rows = self.db.conn.execute(
                    """SELECT universe_name, instrument_id, symbol, token, exchange, 
                              effective_from, effective_until, known_from, weight, 
                              inclusion_reason, exclusion_reason 
                       FROM index_constituents_pit 
                       WHERE UPPER(universe_name) = ? 
                       ORDER BY symbol, effective_from, effective_until, instrument_id""",
                    [universe_name.upper()],
                ).fetchall()
                if not pit_rows:
                    pit_status = "FAIL"
                    pit_details["reason"] = f"No PIT constituent history available for universe {universe_name}."
                else:
                    expected_pit_hash = hashlib.sha256(json.dumps(pit_rows, default=str, separators=(",", ":")).encode()).hexdigest()
                    if frame_pit_hash and frame_pit_hash != expected_pit_hash:
                        pit_status = "FAIL"
                        pit_details["pit_hash_mismatch"] = f"Frame PIT hash {frame_pit_hash} != recomputed {expected_pit_hash}"
                    else:
                        pit_details["pit_records"] = len(pit_rows)
                        pit_details["pit_evidence_hash"] = expected_pit_hash
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
            oos_status = "FAIL"
            oos_details["error"] = str(exc)

        evidence_records.append({
            "category": "OOS_WALK_FORWARD",
            "status": oos_status,
            "evidence": oos_details,
        })

        # Write all 5 certification rows within a single atomic transaction
        with self.db.transaction():
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
