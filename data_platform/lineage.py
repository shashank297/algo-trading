"""Authoritative dataset lineage manifest and verification foundation.

Ensures every research dataset binds raw artifact hashes, transformation hashes,
provider source references, coverage boundaries, and DQ/PIT certifications.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping


HEX_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

MANDATORY_MANIFEST_FIELDS = (
    "dataset_id",
    "dataset_version",
    "provider",
    "source_reference",
    "retrieved_at",
    "coverage_start",
    "coverage_end",
    "frequency",
    "timezone",
    "calendar",
    "universe",
    "raw_artifact_hash",
    "canonical_artifact_hash",
    "transformation_version",
    "transformation_hash",
    "corporate_action_policy",
    "missing_data_policy",
    "status",
)


@dataclass(frozen=True, slots=True)
class DatasetLineageManifest:
    """Immutable record of dataset derivation and authoritative lineage."""

    manifest_id: str
    dataset_id: str
    dataset_version: str
    provider: str
    source_reference: str
    retrieved_at: str
    coverage_start: str
    coverage_end: str
    frequency: str
    timezone: str
    calendar: str
    universe: str
    raw_artifact_hash: str
    canonical_artifact_hash: str
    transformation_version: str
    transformation_hash: str
    corporate_action_policy: str
    missing_data_policy: str
    status: str
    available_at: str | None = None
    dq_certification_id: str | None = None
    pit_certification_id: str | None = None

    def compute_hash(self) -> str:
        """Compute deterministic canonical SHA-256 over all lineage attributes."""
        payload = asdict(self)
        payload.pop("manifest_id", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetLineageVerifier:
    """Fail-closed lineage manifest validation and persistence."""

    @staticmethod
    def validate_manifest(
        manifest: DatasetLineageManifest | Mapping[str, Any],
        *,
        require_certified: bool = False,
    ) -> None:
        """Verify that a manifest contains all required fields, valid hashes, and certified status."""
        data = manifest.to_dict() if isinstance(manifest, DatasetLineageManifest) else dict(manifest)

        # 1. Missing or blank field checks
        missing = [f for f in MANDATORY_MANIFEST_FIELDS if data.get(f) in (None, "", [], {})]
        if missing:
            raise ValueError(f"Incomplete dataset lineage manifest: missing {', '.join(missing)}")

        # 2. Hash formatting validation
        for hash_field in ("raw_artifact_hash", "canonical_artifact_hash", "transformation_hash"):
            val = str(data[hash_field]).strip()
            if not HEX_SHA256_PATTERN.match(val):
                raise ValueError(
                    f"Malformed {hash_field} in lineage manifest: '{val}' is not a valid 64-character SHA-256 hex string"
                )

        # 3. Source reference sanity
        if len(str(data["source_reference"]).strip()) < 3:
            raise ValueError("Dataset lineage manifest source_reference must be a valid non-empty identifier/URL")

        # 4. Coverage date ordering
        if str(data["coverage_start"]) > str(data["coverage_end"]):
            raise ValueError(
                f"Invalid coverage range in lineage manifest: start {data['coverage_start']} is after end {data['coverage_end']}"
            )

        # 5. Status validation
        status = str(data["status"]).upper().strip()
        allowed_statuses = {"COMPLETE", "CERTIFIED"} if not require_certified else {"CERTIFIED"}
        if status not in allowed_statuses:
            raise ValueError(
                f"Lineage manifest status '{status}' does not satisfy required {allowed_statuses}"
            )

    @classmethod
    def record_manifest(cls, conn: Any, manifest: DatasetLineageManifest) -> None:
        """Persist verified manifest into dataset_lineage_manifests table."""
        cls.validate_manifest(manifest)
        raw_conn = getattr(conn, "conn", conn)
        query = """
            INSERT OR REPLACE INTO dataset_lineage_manifests (
                manifest_id, dataset_id, dataset_version, provider, source_reference,
                retrieved_at, available_at, coverage_start, coverage_end, frequency,
                timezone, calendar, universe, raw_artifact_hash, canonical_artifact_hash,
                transformation_version, transformation_hash, corporate_action_policy,
                missing_data_policy, dq_certification_id, pit_certification_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        raw_conn.execute(
            query,
            [
                manifest.manifest_id,
                manifest.dataset_id,
                manifest.dataset_version,
                manifest.provider,
                manifest.source_reference,
                manifest.retrieved_at,
                manifest.available_at,
                manifest.coverage_start,
                manifest.coverage_end,
                manifest.frequency,
                manifest.timezone,
                manifest.calendar,
                manifest.universe,
                manifest.raw_artifact_hash,
                manifest.canonical_artifact_hash,
                manifest.transformation_version,
                manifest.transformation_hash,
                manifest.corporate_action_policy,
                manifest.missing_data_policy,
                manifest.dq_certification_id,
                manifest.pit_certification_id,
                manifest.status,
            ],
        )
