"""Fail-closed checks for the reproducible NIFTY-200 PIT source corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.source_catalogue import sha256_file


REQUIREMENTS_PATH = Path("config/nifty200_pit_corpus_requirements.json")


class CorpusIncompleteError(RuntimeError):
    """Raised when required raw PIT evidence is absent or unverifiable."""


def load_corpus_requirements(root: str | Path) -> dict[str, Any]:
    path = Path(root) / REQUIREMENTS_PATH
    if not path.is_file():
        raise CorpusIncompleteError(f"CORPUS_INCOMPLETE: missing requirements manifest: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusIncompleteError(f"CORPUS_INCOMPLETE: unreadable requirements manifest: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise CorpusIncompleteError(f"CORPUS_INCOMPLETE: malformed requirements manifest: {path}")
    return payload


def _required_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise CorpusIncompleteError(
            f"CORPUS_INCOMPLETE: requirements path escapes worktree: {relative_path}"
        ) from exc
    return candidate


def verify_raw_corpus(root: str | Path, requirements: dict[str, Any]) -> list[str]:
    """Return missing or mismatched required raw source bytes."""
    root_path = Path(root).resolve()
    errors: list[str] = []
    for record in requirements["records"]:
        if not isinstance(record, dict):
            errors.append("CORPUS_INCOMPLETE: malformed source requirement record")
            continue
        source_url = str(record.get("source_url", ""))
        expected_sha = str(record.get("source_sha256", ""))
        relative_path = str(record.get("relative_path", ""))
        if not source_url or len(expected_sha) != 64 or not relative_path:
            errors.append(f"CORPUS_INCOMPLETE: malformed source requirement: {source_url}")
            continue
        try:
            path = _required_path(root_path, relative_path)
        except CorpusIncompleteError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"CORPUS_INCOMPLETE: missing_source_bytes:{source_url}:{expected_sha}")
            continue
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            errors.append(
                f"CORPUS_INCOMPLETE: source_hash_mismatch:{source_url}:"
                f"expected={expected_sha}:actual={actual_sha}"
            )
    return errors


def verify_loaded_corpus(
    requirements: dict[str, Any], sources: list[SourceRecord]
) -> list[str]:
    """Verify that the loaded catalogue exposes every required source record."""
    source_map = {(source.source_url, source.source_sha256): source for source in sources}
    errors: list[str] = []
    for record in requirements["records"]:
        if not isinstance(record, dict):
            continue
        key = (str(record.get("source_url", "")), str(record.get("source_sha256", "")))
        source = source_map.get(key)
        if source is None:
            errors.append(f"CORPUS_INCOMPLETE: missing_catalogue_record:{key[0]}:{key[1]}")
            continue
        if not Path(source.local_path).is_file():
            errors.append(f"CORPUS_INCOMPLETE: catalogue_path_missing:{source.local_path}")
    return errors


def assert_corpus_complete(root: str | Path, sources: list[SourceRecord]) -> None:
    """Fail closed before parsing when the expected corpus is incomplete."""
    requirements = load_corpus_requirements(root)
    errors = verify_raw_corpus(root, requirements)
    errors.extend(verify_loaded_corpus(requirements, sources))
    if errors:
        preview = "\n".join(errors[:20])
        suffix = f"\n... {len(errors) - 20} more" if len(errors) > 20 else ""
        raise CorpusIncompleteError(f"{preview}{suffix}")
