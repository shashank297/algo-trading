from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

START = "2012-01-02"
END = "2026-08-20"
PARSER_VERSION = "zero-cost-extract-v1"
INDEX_RE = re.compile(r"\b(?:NIFTY|CNX)\s*200\b", re.I)
EFFECTIVE_RE = re.compile(
    r"(?:effective\s+from|w\.?e\.?f\.?)\s+"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})",
    re.I,
)

def pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for c in iter(lambda: f.read(1024*1024), b""):
            h.update(c)
    return h.hexdigest()

def extract_nifty200_section(text: str) -> str:
    lines = [" ".join(x.split()) for x in text.splitlines()]
    hits = [i for i, line in enumerate(lines) if INDEX_RE.search(line)]
    if not hits:
        return ""
    # Preserve a conservative window around each hit. This is candidate evidence only.
    parts = []
    for i in hits:
        lo, hi = max(0, i-8), min(len(lines), i+80)
        parts.append("\n".join(lines[lo:hi]))
    return "\n---SECTION---\n".join(parts)

def inspect_monthly_zip(zip_path: Path):
    out = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                low = name.lower()
                if not low.endswith((".csv",".txt",".xls",".xlsx")):
                    continue
                data = z.read(name)
                # Cheap first-pass textual scan.
                decoded = None
                for enc in ("utf-8-sig","utf-8","cp1252","latin1"):
                    try:
                        decoded = data.decode(enc)
                        break
                    except Exception:
                        pass
                if decoded and INDEX_RE.search(decoded):
                    matches = [ln for ln in decoded.splitlines() if INDEX_RE.search(ln)]
                    out.append({
                        "zip_file": str(zip_path),
                        "member": name,
                        "evidence_type": "text_match",
                        "match_count": len(matches),
                        "sample": " | ".join(matches[:10])[:4000],
                    })
                    continue

                # Structured Excel fallback.
                if low.endswith((".xls",".xlsx")):
                    try:
                        bio = io.BytesIO(data)
                        sheets = pd.read_excel(bio, sheet_name=None, header=None)
                        for sheet, df in sheets.items():
                            s = df.astype(str)
                            mask = s.apply(lambda col: col.str.contains(INDEX_RE, na=False)).any(axis=1)
                            if mask.any():
                                sample = s.loc[mask].head(20).to_csv(index=False, header=False)
                                out.append({
                                    "zip_file": str(zip_path),
                                    "member": f"{name}::{sheet}",
                                    "evidence_type": "excel_match",
                                    "match_count": int(mask.sum()),
                                    "sample": sample[:4000],
                                })
                    except Exception as e:
                        out.append({
                            "zip_file": str(zip_path), "member": name,
                            "evidence_type": "excel_parse_error",
                            "match_count": 0, "sample": str(e)[:1000],
                        })
    except Exception as e:
        out.append({
            "zip_file": str(zip_path), "member": "",
            "evidence_type": "zip_parse_error", "match_count": 0, "sample": str(e)[:1000],
        })
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    raw = root / "data" / "raw" / "nifty200_pit_public_sources"
    derived = root / "data" / "derived" / "nifty200_pit"
    reports = root / "reports"
    derived.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    # Press release candidate extraction.
    pr_rows = []
    prdir = raw / "press_releases" / "candidates"
    if prdir.exists():
        for path in sorted(prdir.iterdir()):
            if not path.is_file():
                continue
            try:
                if path.suffix.lower() == ".pdf":
                    text = pdf_text(path)
                else:
                    # Some links may return HTML.
                    text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                pr_rows.append({
                    "source_file": str(path),"sha256":sha(path),"contains_nifty200":False,
                    "effective_date_text":"","candidate_section":"","parse_error":str(e),
                    "parser_version":PARSER_VERSION,
                })
                continue
            section = extract_nifty200_section(text)
            eff = EFFECTIVE_RE.search(text)
            pr_rows.append({
                "source_file": str(path),
                "sha256": sha(path),
                "contains_nifty200": bool(section),
                "effective_date_text": eff.group(1) if eff else "",
                "candidate_section": section[:20000],
                "parse_error": "",
                "parser_version": PARSER_VERSION,
            })

    pr_out = derived / "press_release_candidates.csv"
    with pr_out.open("w", newline="", encoding="utf-8") as f:
        fields = ["source_file","sha256","contains_nifty200","effective_date_text",
                  "candidate_section","parse_error","parser_version"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(pr_rows)

    # Monthly checkpoint candidates.
    snap_rows = []
    mdir = raw / "monthly_weightage"
    if mdir.exists():
        for z in sorted(mdir.glob("*.zip")):
            snap_rows.extend(inspect_monthly_zip(z))
    snap_out = derived / "monthly_snapshot_candidates.csv"
    with snap_out.open("w", newline="", encoding="utf-8") as f:
        fields = ["zip_file","member","evidence_type","match_count","sample"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(snap_rows)

    # Fail-closed coverage seed. It intentionally starts unresolved.
    coverage = [
        {
            "period_start":"2012-01-02","period_end":"2013-03-31",
            "planned_primary_evidence":"IndexInclExcl.xls + official press releases + backward reconstruction from first official monthly snapshot",
            "status":"UNRESOLVED_GAP","qa_note":"Must prove every membership mutation and bootstrap snapshot."
        },
        {
            "period_start":"2013-04-01","period_end":"2020-07-31",
            "planned_primary_evidence":"IndexInclExcl.xls + official monthly constituent/weightage checkpoints + press releases",
            "status":"UNRESOLVED_GAP","qa_note":"Require zero unexplained monthly reconciliation differences."
        },
        {
            "period_start":"2020-08-01","period_end":"2022-03-31",
            "planned_primary_evidence":"official monthly constituent/weightage checkpoints + official press releases",
            "status":"UNRESOLVED_GAP","qa_note":"Exact effective dates must be sourced from first-party notices."
        },
        {
            "period_start":"2022-04-01","period_end":"2026-08-20",
            "planned_primary_evidence":"official NSE Indices press releases + first-party constituent checkpoints where available",
            "status":"UNRESOLVED_GAP","qa_note":"Capture periodic reviews plus corporate-action/delisting/suspension changes."
        },
    ]
    cov_out = derived / "coverage_matrix_seed.csv"
    with cov_out.open("w", newline="", encoding="utf-8") as f:
        fields = ["period_start","period_end","planned_primary_evidence","status","qa_note"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(coverage)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required_horizon": {"start": START, "end": END},
        "press_release_files_scanned": len(pr_rows),
        "press_release_files_containing_nifty200": sum(str(r["contains_nifty200"]).lower()=="true" for r in pr_rows),
        "monthly_candidate_records": len(snap_rows),
        "disposition": "BLOCKED",
        "reason": "Candidate extraction is not certification. Coverage remains UNRESOLVED_GAP until event normalization and independent reconciliation are complete.",
        "safety": {
            "strategy": "NO", "backtest": "NO", "paper_session": "NO", "broker_api": "NO",
            "credential": "NO", "order": "NO", "live_endpoint": "NO", "capital_deployment": "NO"
        }
    }
    (reports / "nifty200_zero_cost_pit_extraction_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
