"""Immutable, content-addressed source storage and catalogue helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.nifty200_pit.models import SourceRecord


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SourceCatalogue:
    """Store source bytes under their hash without ever overwriting them."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.raw_root = self.root / "raw"
        self.records: list[SourceRecord] = []

    def add_bytes(
        self,
        data: bytes,
        *,
        source_url: str,
        extension: str = ".bin",
        archive_url: str | None = None,
        source_tier: str = "A1",
        content_type: str = "",
        http_status: int | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        document_date: str | None = None,
        retrieved_at: str | None = None,
    ) -> SourceRecord:
        digest = sha256_bytes(data)
        suffix = extension if extension.startswith(".") else f".{extension}"
        destination = self.raw_root / digest[:2] / f"{digest}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and sha256_file(destination) != digest:
            raise ValueError(f"Content-addressed source collision at {destination}")
        if not destination.exists():
            destination.write_bytes(data)
        record = SourceRecord(
            source_url=source_url,
            original_url=source_url,
            archive_url=archive_url,
            local_path=str(destination),
            source_sha256=digest,
            retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
            content_type=content_type,
            http_status=http_status,
            etag=etag,
            last_modified=last_modified,
            document_date=document_date,
            file_size=len(data),
            source_tier=source_tier,
        )
        self.records.append(record)
        return record

    def add_file(self, path: str | Path, **metadata: Any) -> SourceRecord:
        source = Path(path)
        data = source.read_bytes()
        return self.add_bytes(data, extension=source.suffix or ".bin", **metadata)

    def verify(self, records: list[SourceRecord] | None = None) -> list[str]:
        errors: list[str] = []
        for record in records or self.records:
            path = Path(record.local_path)
            if not path.is_file():
                errors.append(f"missing_source:{record.source_sha256}")
            elif sha256_file(path) != record.source_sha256:
                errors.append(f"hash_mismatch:{record.source_sha256}")
        return errors

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path else self.root / "source_catalogue.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps([r.to_dict() for r in self.records], indent=2), encoding="utf-8")
        return destination


def copy_immutable(source: str | Path, destination: str | Path) -> Path:
    """Copy a source only when the destination is absent or byte-identical."""
    source_path, destination_path = Path(source), Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        if sha256_file(source_path) != sha256_file(destination_path):
            raise FileExistsError(f"Refusing to overwrite non-identical source: {destination_path}")
        return destination_path
    shutil.copyfile(source_path, destination_path)
    return destination_path
