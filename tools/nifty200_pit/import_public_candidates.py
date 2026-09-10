"""Ingest external reconstructions as explicitly non-authoritative observations."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def import_candidate_file(path: str | Path, *, source_name: str, output_path: str | Path) -> int:
    source = Path(path)
    if source.suffix.lower() == ".json":
        rows = json.loads(source.read_text(encoding="utf-8"))
    else:
        with source.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    converted = []
    for row in rows:
        converted.append({**row, "candidate_source": source_name, "source_tier": "B1" if source_name == "deshpanda" else "C2",
                          "synthetic": False, "confidence": "PROVISIONAL", "review_status": "UNRESOLVED"})
    output.write_text(json.dumps(converted, indent=2, default=str), encoding="utf-8")
    return len(converted)
