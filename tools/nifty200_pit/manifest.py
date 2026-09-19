"""Deterministic evidence artifact and manifest generation."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import csv
from pathlib import Path
import subprocess
from typing import Any, Iterable

from tools.nifty200_pit.source_catalogue import sha256_file


def _row(value: Any) -> dict[str, Any]:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    result = dict(value)
    for key, item in list(result.items()):
        if hasattr(item, "value"):
            result[key] = item.value
        elif isinstance(item, (list, dict)):
            result[key] = json.dumps(item, sort_keys=True, default=str)
        elif hasattr(item, "isoformat"):
            result[key] = item.isoformat()
    return result


def write_table(path: str | Path, values: Iterable[Any]) -> Path:
    """Write a parquet table using DuckDB, avoiding a pyarrow runtime dependency."""
    import pandas as pd
    import duckdb

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [_row(value) for value in values]
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame({"_empty": pd.Series(dtype="string")})
    connection = duckdb.connect(":memory:")
    try:
        connection.register("incoming_frame", frame)
        safe_path = str(destination).replace("'", "''")
        connection.execute(f"COPY incoming_frame TO '{safe_path}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return destination


def read_table(path: str | Path):
    """Read an artifact through DuckDB so parquet works without pandas engines."""
    import duckdb

    connection = duckdb.connect(":memory:")
    try:
        safe_path = str(Path(path)).replace("'", "''")
        return connection.execute(f"SELECT * FROM read_parquet('{safe_path}')").df()
    finally:
        connection.close()


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _git_identity(root: Path) -> dict[str, Any]:
    """Describe the exact repository state that generated an artifact package."""
    head = _git_sha(root)
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        source_suffixes = {".py", ".pyi", ".sql", ".yaml", ".yml", ".toml", ".json"}
        source_files: list[tuple[str, str]] = []
        for relative in sorted(path for path in untracked if Path(path).suffix.lower() in source_suffixes):
            candidate = root / relative
            if candidate.is_file():
                source_files.append((relative, sha256_file(candidate)))
        working_tree_payload = {
            "head_sha": head,
            "status": status,
            "tracked_diff": diff,
            "untracked_source_hashes": source_files,
        }
        working_tree_hash = hashlib.sha256(
            json.dumps(working_tree_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        dirty = bool(status.strip())
        return {
            "head_sha": head,
            "dirty": dirty,
            "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
            "working_tree_sha256": working_tree_hash,
            "execution_id": f"UNCOMMITTED:{working_tree_hash}" if dirty else head,
        }
    except (OSError, subprocess.CalledProcessError):
        return {
            "head_sha": head,
            "dirty": None,
            "status_sha256": "UNKNOWN",
            "working_tree_sha256": "UNKNOWN",
            "execution_id": f"UNKNOWN:{head}",
        }


def build_manifest(
    artifact_dir: str | Path,
    *,
    source_records: Iterable[Any],
    validation_report: Any,
    identity_map_hash: str = "",
    parser_git_sha: str = "UNKNOWN",
    campaign_from: str = "2012-01-01",
    campaign_to: str = "2026-08-31",
    known_at_policy: str = "DATE_ONLY_CONSERVATIVE_NEXT_SESSION",
) -> dict[str, Any]:
    directory = Path(artifact_dir)
    code_identity = _git_identity(directory.parent.parent)
    files = {}
    for path in sorted(directory.iterdir() if directory.exists() else []):
        if path.is_file() and path.name not in {"evidence_manifest.json", "sha256sums.txt"}:
            files[path.name] = sha256_file(path)
    report = validation_report.to_dict() if hasattr(validation_report, "to_dict") else dict(validation_report)
    generated_at = datetime.now(timezone.utc).isoformat()
    execution_id = code_identity["execution_id"]
    return {
        "manifest_version": "NIFTY200_PIT_V1",
        "generated_at": generated_at,
        "build_id": hashlib.sha256(f"{generated_at}|{execution_id}".encode("utf-8")).hexdigest(),
        "date_range": {"campaign_from": campaign_from, "campaign_to": campaign_to},
        "build_configuration": {
            "expected_member_count": 200,
            "calendar": "NSE verified trading calendar",
            "known_at_policy": known_at_policy,
            "identity_policy": "EXACT_PERIOD_VALID_OR_OFFICIAL_ACCEPTED_ALIAS_ONLY",
            "b1_policy": "PROVISIONAL_SEARCH_INDEX_ONLY",
        },
        "known_at_policy": known_at_policy,
        "parser_git_sha": parser_git_sha if parser_git_sha != "UNKNOWN" else execution_id,
        "code_identity": code_identity,
        "identity_map_hash": identity_map_hash,
        "source_hashes": [_row(record).get("source_sha256", "") for record in source_records],
        "artifact_hashes": files,
        "unresolved_conflict_count": int(report.get("metrics", {}).get("high_critical_conflicts", 0)),
        "validation_status": report.get("status", "BLOCKED"),
        "validation_report": report,
        "automated_validation": "AUTOMATED_VALIDATION_PASS" if report.get("status") == "PASS" else "AUTOMATED_VALIDATION_BLOCKED",
        "independent_qa": "NOT_ASSERTED",
        "campaign_readiness": "PASS" if report.get("status") == "PASS" else "BLOCKED",
        "stage_a_started": False,
        "approved_for_import": False,
    }


def write_artifacts(
    artifact_dir: str | Path,
    *,
    source_records: Iterable[Any],
    observations: Iterable[Any],
    raw_observations: Iterable[Any] = (),
    observation_lineage: Iterable[Any] = (),
    events: Iterable[Any],
    aliases: Iterable[Any],
    intervals: Iterable[Any],
    monthly_snapshots: Iterable[Any],
    event_date_snapshots: Iterable[Any] = (),
    conflicts: Iterable[Any] = (),
    validation_report: Any,
    identity_map_hash: str = "",
    parser_git_sha: str = "UNKNOWN",
    campaign_from: str = "2012-01-01",
    campaign_to: str = "2026-08-31",
) -> tuple[Path, dict[str, Any]]:
    directory = Path(artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source_rows = list(source_records)
    raw_observation_rows = list(raw_observations)
    lineage_rows = list(observation_lineage)
    alias_rows = list(aliases)
    names = {
        "source_catalogue.parquet": source_rows,
        "raw_event_observations.parquet": raw_observation_rows,
        "event_observations.parquet": list(observations),
        "observation_lineage.parquet": lineage_rows,
        "events_canonical.parquet": list(events),
        "instrument_aliases.parquet": alias_rows,
        "constituent_intervals.parquet": list(intervals),
        "monthly_snapshots.parquet": list(monthly_snapshots),
        "event_date_snapshots.parquet": list(event_date_snapshots),
        "conflict_report.parquet": list(conflicts),
    }
    for name, rows in names.items():
        write_table(directory / name, rows)
    report = validation_report.to_dict() if hasattr(validation_report, "to_dict") else dict(validation_report)
    (directory / "validation_report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    daily_counts = report.get("metrics", {}).get("daily_member_counts", {})
    expected_counts = report.get("metrics", {}).get("expected_member_counts", {})
    with (directory / "coverage_report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "member_count", "required_member_count", "status"])
        for as_of, count in sorted(daily_counts.items()):
            expected = int(expected_counts.get(as_of, 200))
            writer.writerow([as_of, count, expected, "PASS" if count == expected else "BLOCKED"])
    with (directory / "instrument_resolution_report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["instrument_id", "isin", "symbol", "resolution_status"])
        for alias in alias_rows:
            row = _row(alias)
            writer.writerow([row.get("instrument_id", ""), row.get("isin", ""), row.get("symbol", row.get("alias_symbol", "")), row.get("confidence", "")])
    manifest = build_manifest(directory, source_records=source_rows, validation_report=report,
                              identity_map_hash=identity_map_hash, parser_git_sha=parser_git_sha,
                              campaign_from=campaign_from, campaign_to=campaign_to)
    manifest_path = directory / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    checksum_lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(directory.iterdir()) if path.is_file() and path.name != "sha256sums.txt"]
    (directory / "sha256sums.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    (directory / "README.md").write_text(
        "# NIFTY-200 PIT evidence package\n\n"
        "Generated from immutable source evidence. `BLOCKED` packages are not importable.\n"
        "Automated validation does not represent independent QA or risk approval.\n", encoding="utf-8"
    )
    return manifest_path, manifest
