"""Command-line orchestration for the NIFTY-200 PIT evidence pipeline."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from tools.nifty200_pit.harvest_nse import harvest_nse
from tools.nifty200_pit.harvest_wayback import discover_captures
from tools.nifty200_pit.instrument_resolver import resolve_observations
from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.manifest import write_artifacts
from tools.nifty200_pit.models import Action, CanonicalEvent, Observation, SourceRecord
from tools.nifty200_pit.parse_pdf import parse_nifty200_text
from tools.nifty200_pit.reconciliation import reconcile_observations
from tools.nifty200_pit.validation import validate_campaign, verify_source_hashes


def _paths(root: Path) -> tuple[Path, Path, Path]:
    raw = root / "data" / "raw" / "nifty200_pit_public_sources"
    derived = root / "data" / "derived" / "nifty200_pit"
    artifacts = root / "artifacts" / "nifty200_pit_v1"
    for path in (raw, derived, artifacts):
        path.mkdir(parents=True, exist_ok=True)
    return raw, derived, artifacts


def _dump(path: Path, values: list[Any]) -> None:
    path.write_text(json.dumps([value.to_dict() if hasattr(value, "to_dict") else value for value in values], indent=2, default=str), encoding="utf-8")


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _observation(row: dict[str, Any]) -> Observation:
    for key in ("announcement_date", "effective_date"):
        if row.get(key):
            row[key] = date.fromisoformat(str(row[key])[:10])
    if row.get("known_at"):
        row["known_at"] = datetime.fromisoformat(str(row["known_at"]))
    return Observation(**row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("harvest-nse", "harvest-wayback", "import-candidates", "parse", "resolve-instruments", "reconcile", "build-intervals", "validate", "manifest"):
        command = sub.add_parser(name)
        if name == "harvest-wayback":
            command.add_argument("--url", action="append", required=True)
        elif name == "import-candidates":
            command.add_argument("--file", required=True)
            command.add_argument("--source", required=True)
        elif name == "resolve-instruments":
            command.add_argument("--instrument-master", required=True)
        elif name == "reconcile":
            command.add_argument("--fail-on-official-conflict", action="store_true")
        elif name == "build-intervals":
            command.add_argument("--index", default="NIFTY_200")
        elif name == "validate":
            command.add_argument("--campaign-from", default="2012-01-01")
            command.add_argument("--campaign-to", default="2026-08-31")
            command.add_argument("--require-member-count", type=int, default=200)
        elif name == "manifest":
            command.add_argument("--output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    raw, derived, artifacts = _paths(root)
    if args.command == "harvest-nse":
        print(f"Harvested {len(harvest_nse(root))} official source records")
    elif args.command == "harvest-wayback":
        captures = [capture for url in args.url for capture in discover_captures(url)]
        (derived / "wayback_captures.json").write_text(json.dumps(captures, indent=2), encoding="utf-8")
        print(f"Discovered {len(captures)} Wayback captures")
    elif args.command == "import-candidates":
        from tools.nifty200_pit.import_public_candidates import import_candidate_file
        count = import_candidate_file(args.file, source_name=args.source, output_path=derived / f"{args.source}_candidates.json")
        print(f"Imported {count} non-authoritative candidate rows")
    elif args.command == "parse":
        catalogue_rows = _load(raw / "source_catalogue.json")
        observations = []
        for source in catalogue_rows:
            path = Path(source["local_path"])
            if path.suffix.lower() == ".pdf":
                from tools.nifty200_pit.parse_pdf import extract_pdf_text
                text = extract_pdf_text(path)
            else:
                text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
            observations.extend(parse_nifty200_text(text, source_url=source["source_url"], source_sha256=source["source_sha256"], source_tier=source.get("source_tier", "A1")))
        _dump(derived / "event_observations.json", observations)
        print(f"Parsed {len(observations)} candidate observations")
    elif args.command == "resolve-instruments":
        with Path(args.instrument_master).open(encoding="utf-8", newline="") as handle:
            master = list(csv.DictReader(handle))
        observations = [_observation(row) for row in _load(derived / "event_observations.json")]
        resolved = resolve_observations(observations, master)
        _dump(derived / "event_observations_resolved.json", resolved)
        print(f"Resolved {len(resolved)} observations")
    elif args.command == "reconcile":
        observations = [_observation(row) for row in _load(derived / "event_observations_resolved.json") or _load(derived / "event_observations.json")]
        result = reconcile_observations(observations, fail_on_official_conflict=args.fail_on_official_conflict)
        _dump(derived / "events_canonical.json", result.events)
        _dump(derived / "conflicts.json", result.conflicts)
        print(f"Canonical events: {len(result.events)}; conflicts: {len(result.conflicts)}")
    elif args.command == "build-intervals":
        events = [_event(row) for row in _load(derived / "events_canonical.json") if row.get("index_id", args.index) == args.index]
        result = build_intervals(events)
        _dump(derived / "constituent_intervals.json", result.intervals)
        _dump(derived / "interval_conflicts.json", result.conflicts)
        print(f"Built {len(result.intervals)} intervals; conflicts: {len(result.conflicts)}")
    elif args.command == "validate":
        events = [_event(row) for row in _load(derived / "events_canonical.json")]
        intervals = [_interval(row) for row in _load(derived / "constituent_intervals.json")]
        report = validate_campaign(intervals, events, campaign_from=date.fromisoformat(args.campaign_from), campaign_to=date.fromisoformat(args.campaign_to), required_member_count=args.require_member_count, conflicts=_load(derived / "conflicts.json"), source_hash_errors=verify_source_hashes([SourceRecord(**row) for row in _load(raw / "source_catalogue.json")]))
        (derived / "validation_report.json").write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return 0 if report.passed else 2
    elif args.command == "manifest":
        report_data = json.loads((derived / "validation_report.json").read_text(encoding="utf-8")) if (derived / "validation_report.json").exists() else {"status": "BLOCKED", "metrics": {}, "reasons": ["validation_not_run"]}
        source_records = [SourceRecord(**row) for row in _load(raw / "source_catalogue.json")]
        manifest_path, _ = write_artifacts(artifacts, source_records=source_records, observations=_load(derived / "event_observations.json"), events=_load(derived / "events_canonical.json"), aliases=_load(derived / "instrument_aliases.json"), intervals=_load(derived / "constituent_intervals.json"), monthly_snapshots=[], conflicts=_load(derived / "conflicts.json"), validation_report=report_data)
        if args.output:
            Path(args.output).write_bytes(manifest_path.read_bytes())
        print(f"Wrote {manifest_path}")
    return 0


def _event(row: dict[str, Any]) -> CanonicalEvent:
    for key in ("announcement_date", "effective_date"):
        row[key] = date.fromisoformat(str(row[key])[:10])
    row["known_at"] = datetime.fromisoformat(str(row["known_at"]))
    row["action"] = Action(str(row["action"]))
    row["confidence"] = row.get("confidence", "UNRESOLVED")
    row["review_status"] = row.get("review_status", "UNRESOLVED")
    from tools.nifty200_pit.models import Confidence, ReviewStatus
    row["confidence"] = Confidence(row["confidence"])
    row["review_status"] = ReviewStatus(row["review_status"])
    return CanonicalEvent(**row)


def _interval(row: dict[str, Any]):
    from tools.nifty200_pit.models import ConstituentInterval, Confidence
    for key in ("effective_from", "effective_until", "known_from"):
        if row.get(key):
            row[key] = date.fromisoformat(str(row[key])[:10])
    row["known_at"] = datetime.fromisoformat(str(row["known_at"]))
    row["confidence"] = Confidence(row["confidence"])
    return ConstituentInterval(**row)


if __name__ == "__main__":
    raise SystemExit(main())
