"""Verified, atomic backup and restore for the canonical DuckDB database."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


class DatabaseBackupService:
    """Create and restore single-file DuckDB backups with integrity manifests."""

    def backup(self, database: str | Path, destination: str | Path) -> dict[str, Any]:
        source = Path(database).resolve()
        target = Path(destination).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Database not found: {source}")
        if source == target:
            raise ValueError("Backup destination must differ from the source database.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        if temporary.exists():
            temporary.unlink()
        connection = duckdb.connect(str(source))
        try:
            connection.execute("CHECKPOINT")
            source_counts = self._critical_counts(connection)
        finally:
            connection.close()
        shutil.copy2(source, temporary)
        copied = self.verify(temporary, expected_counts=source_counts)
        os.replace(temporary, target)
        manifest = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database": str(source),
            "backup_file": target.name,
            "sha256": self._sha256(target),
            "size_bytes": target.stat().st_size,
            "table_count": copied["table_count"],
            "critical_counts": source_counts,
        }
        manifest_path = self.manifest_path(target)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return manifest

    def restore(
        self,
        backup: str | Path,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        source = Path(backup).resolve()
        target = Path(destination).resolve()
        manifest = self._load_manifest(source)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Restore destination already exists: {target}")
        if self._sha256(source) != manifest["sha256"]:
            raise ValueError("Backup hash does not match its manifest.")
        verified = self.verify(source, expected_counts=manifest["critical_counts"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".restore-partial")
        if temporary.exists():
            temporary.unlink()
        shutil.copy2(source, temporary)
        try:
            self.verify(temporary, expected_counts=manifest["critical_counts"])
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {"destination": str(target), **verified}

    def verify(
        self,
        database: str | Path,
        *,
        expected_counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        path = Path(database).resolve()
        connection = duckdb.connect(str(path), read_only=True)
        try:
            connection.execute("SELECT 1").fetchone()
            table_count_row = connection.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchone()
            if table_count_row is None:
                raise RuntimeError("DuckDB did not return a table count during verification.")
            table_count = int(table_count_row[0])
            counts = self._critical_counts(connection)
        finally:
            connection.close()
        if expected_counts is not None and counts != expected_counts:
            raise ValueError(f"Backup row-count verification failed: expected {expected_counts}, got {counts}")
        return {"database": str(path), "table_count": table_count, "critical_counts": counts}

    @staticmethod
    def manifest_path(backup: Path) -> Path:
        return backup.with_suffix(backup.suffix + ".manifest.json")

    def _load_manifest(self, backup: Path) -> dict[str, Any]:
        manifest_path = self.manifest_path(backup)
        if not backup.is_file() or not manifest_path.is_file():
            raise FileNotFoundError("Backup file and manifest are both required for restore.")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    @staticmethod
    def _critical_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
        existing = {
            row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        critical = ("historical_candles", "market_datasets", "experiments", "strategy_runs")
        counts: dict[str, int] = {}
        for table in critical:
            if table not in existing:
                continue
            row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            if row is None:
                raise RuntimeError(f"DuckDB did not return a row count for {table}.")
            counts[table] = int(row[0])
        return counts

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
