"""Hash-bound, review-only derivation of a starting membership candidate.

Inputs are explicit primary catalogue URL/hash/path records, an archive CSV,
native-text notice PDFs, a checkpoint identity-ledger CSV/hash, and endpoint
rename quotes (source_page, from/to_symbol, isin, old_quote, new_quote).
Actions and dates are reparsed from verified bytes, never caller assertions.

Missing proof remains explicit: independent complete notice coverage, causal
public availability, dated rename/identity continuity, and checkpoint identity
admission. Six notices, endpoint equality and complete=True prove none of these.
Optional coverage JSON (index_id, coverage_from/to, notice_sources URL/hash pairs)
detects inventory omissions; it cannot certify itself. Results always remain
UNRESOLVED/MANUAL_REVIEW with known_at=None. Endpoint aliases are not membership
events or guessed exchange rename dates. Count admission is a separate gate.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
from typing import Any

from tools.nifty200_pit.parse_pdf import (
    INDEX_HEADING_RE, extract_nifty200_sections, extract_pdf_pages,
    find_document_date, parse_nifty200_text,
)


def _stamp(value: str | datetime) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timezone_required")
    return stamp


def _pair(record: dict[str, Any]) -> tuple[str, str]:
    return record["source_url"], record["source_sha256"]


def _verified(record: dict[str, Any]) -> bytes:
    try:
        content = Path(record["local_path"]).read_bytes()
    except OSError as exc:
        raise ValueError(f"source_missing:{record['source_url']}") from exc
    if hashlib.sha256(content).hexdigest() != record["source_sha256"]:
        raise ValueError(f"source_hash_mismatch:{record['source_url']}")
    return content


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def derive_anchor_candidate(
    *,
    start_at: datetime,
    seed: dict[str, Any],
    notices: list[dict[str, Any]],
    renames: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    catalogue: list[dict[str, Any]],
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay verified sources into checkpoint-linked, never admitted members.

    Invalid custody, actions, aliases or endpoint sets raise ValueError. Unknown
    coverage, identity admission and availability remain in missing_evidence.
    Caller-owned records and the filesystem are never modified.
    """
    start_at = _stamp(start_at)
    day = start_at.date()
    dependencies: dict[tuple[str, str, str], dict[str, str]] = {}
    missing = {"source_coverage_not_established", "identity_admission_not_established",
               "causal_availability_not_established", "anchor_admission_required"}

    def read(record: dict[str, Any], role: str, *, primary: bool = True) -> bytes:
        for field in ("known_at", "publication_timestamp"):
            if record.get(field) and _stamp(record[field]) > start_at:
                raise ValueError(f"post_start_knowledge:{role}")
        if primary:
            matches = [r for r in catalogue if _pair(r) == _pair(record)
                       and r.get("source_tier") in {"A1", "A2"}]
            if not matches:
                raise ValueError(f"source_not_registered:{record['source_url']}")
            for registered in matches:
                for field in ("known_at", "publication_timestamp"):
                    if registered.get(field) and _stamp(registered[field]) > start_at:
                        raise ValueError(f"post_start_knowledge:{role}")
        content = _verified(record)
        dependencies[(role, *_pair(record))] = {
            "role": role, "source_url": record["source_url"],
            "source_sha256": record["source_sha256"],
        }
        return content

    capture = re.search(r"/web/(\d{14})(?:id_)?/", seed["source_url"])
    if capture is None:
        raise ValueError("archive_capture_timestamp_missing")
    seed_at = datetime.strptime(capture[1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if seed_at > start_at:
        raise ValueError("post_start_knowledge:seed")
    seed_rows = list(csv.DictReader(StringIO(read(seed, "seed").decode("utf-8-sig"))))
    active: dict[str, str | None] = {}
    for row in seed_rows:
        symbol, isin = row["Symbol"].strip(), row["ISIN Code"].strip()
        if not symbol or not isin or row["Series"].strip() != "EQ" or symbol in active:
            raise ValueError("invalid_seed_member")
        active[symbol] = isin
    if not active:
        raise ValueError("seed_empty")

    actions: list[dict[str, Any]] = []
    notice_pairs = [_pair(notice) for notice in notices]
    if len(set(notice_pairs)) != len(notice_pairs):
        raise ValueError("duplicate_notice_source")
    for notice in sorted(notices, key=_pair):
        pages = extract_pdf_pages(read(notice, "notice"))
        page_lines = [page.splitlines() for page in pages]
        text = "\n".join(line for lines in page_lines for line in lines)
        index_lines: set[int] = set()
        for offset, section in extract_nifty200_sections(text):
            heading, *lines = section.splitlines()
            if INDEX_HEADING_RE.fullmatch(heading):
                index_lines.update(range(offset + 1, offset + 1 + len(lines)))
        source_pages: list[tuple[int, list[str]]] = []
        offset = 0
        for notice_page, lines in enumerate(page_lines, 1):
            source_pages.append((notice_page, [
                _compact(line) if offset + i in index_lines else "" for i, line in enumerate(lines)
            ]))
            offset += len(lines)
        rows = parse_nifty200_text(
            text, source_url=notice["source_url"], source_sha256=notice["source_sha256"],
            announcement_date=find_document_date(notice["source_url"], text),
        )
        if not rows or any(not r.symbol or not r.effective_date or
                           r.action not in {"ADD", "DROP"} for r in rows):
            raise ValueError("notice_actions_unverifiable")
        for observation in rows:
            assert observation.effective_date is not None
            if not seed_at.date() < observation.effective_date <= day:
                raise ValueError("action_outside_derivation_range")
            if observation.announcement_date and observation.announcement_date > day:
                raise ValueError("post_start_knowledge:announcement")
            exact_row = [_compact(line) for line in (observation.raw_text or "").splitlines()]
            matches = [
                page_number for page_number, lines in source_pages
                for i in range(len(lines)) if exact_row and lines[i:i + len(exact_row)] == exact_row
            ]
            if len(matches) != 1:
                missing.add("notice_page_attribution_not_established")
            actions.append({
                "symbol": observation.symbol, "action": str(observation.action),
                "effective_date": observation.effective_date.isoformat(),
                "announcement_date": observation.announcement_date.isoformat() if observation.announcement_date else None,
                "source_url": notice["source_url"], "source_sha256": notice["source_sha256"],
                "source_page": matches[0] if len(matches) == 1 else None,
                "raw_text": observation.raw_text,
                # Parser-derived next-session times are not publication proof.
                "known_at": notice.get("known_at"),
            })
    actions.sort(key=lambda r: (r["effective_date"], r["action"] == "ADD",
                               r["source_sha256"], r["symbol"]))
    for action in actions:
        symbol = action["symbol"]
        if action["action"] == "DROP":
            if symbol not in active:
                raise ValueError(f"invalid_drop:{symbol}")
            del active[symbol]
        else:
            if symbol in active:
                raise ValueError(f"invalid_add:{symbol}")
            active[symbol] = None  # No identity inferred from a membership notice.

    alias_steps = []
    for rename in sorted(renames, key=lambda r: (r["from_symbol"], r["to_symbol"])):
        pages = extract_pdf_pages(read(rename, "rename"))
        page_number = rename.get("source_page")
        old, new, isin = rename["from_symbol"], rename["to_symbol"], rename["isin"]
        if type(page_number) is not int or not 1 <= page_number <= len(pages):
            raise ValueError("rename_not_source_verified")
        page = _compact(pages[page_number - 1])
        for quote, symbol in ((rename.get("old_quote", ""), old),
                              (rename.get("new_quote", ""), new)):
            compact = _compact(quote)
            if not compact or compact not in page or symbol + isin not in compact:
                raise ValueError("rename_not_source_verified")
        if not isin or old == new or old not in active or new in active:
            raise ValueError("rename_not_source_verified")
        if active[old] != isin:
            raise ValueError("rename_identity_mismatch")
        active[new] = active.pop(old)
        alias_steps.append({
            "from_symbol": old, "to_symbol": new, "isin": isin,
            "source_url": rename["source_url"], "source_sha256": rename["source_sha256"],
            "source_page": page_number, "old_quote": rename["old_quote"],
            "new_quote": rename["new_quote"], "application": "ENDPOINT_ALIAS_ONLY",
            "effective_date": None, "known_at": rename.get("known_at"),
        })
    if alias_steps:
        missing.add("dated_rename_continuity_not_established")

    proof_bytes = read(checkpoint, "checkpoint", primary=False)
    proof_rows = [r for r in csv.DictReader(StringIO(proof_bytes.decode("utf-8-sig")))
                  if r["checkpoint_date"] == day.isoformat()]
    if not proof_rows:
        raise ValueError("starting_checkpoint_missing")
    for field in ("source_symbol", "durable_instrument_id", "resolved_isin"):
        values = [r[field] for r in proof_rows]
        if any(not v for v in values) or len(set(values)) != len(values):
            raise ValueError("duplicate_checkpoint_identity")
    if {r["source_symbol"] for r in proof_rows} != set(active):
        raise ValueError("checkpoint_symbol_mismatch")
    members = []
    for row in sorted(proof_rows, key=lambda r: r["source_symbol"]):
        symbol = row["source_symbol"]
        if any(a["to_symbol"] == symbol for a in alias_steps) and active[symbol] != row["resolved_isin"]:
            raise ValueError("rename_identity_mismatch")
        identity_ref = {"source_url": row["identity_source_url_reference"],
                        "source_sha256": row["identity_source_hash"]}
        if not any(_pair(r) == _pair(identity_ref) for r in catalogue):
            raise ValueError("checkpoint_identity_source_not_registered")
        valid_from, valid_until = row["identity_valid_from"], row["identity_valid_to"] or None
        if not valid_from or date.fromisoformat(valid_from) > day or (
                valid_until and day >= date.fromisoformat(valid_until)):
            missing.add("checkpoint_identity_not_period_valid")
        members.append({
            "symbol": symbol, "instrument_id": row["durable_instrument_id"],
            "isin": row["resolved_isin"], "valid_from": valid_from,
            "valid_until": valid_until, "has_explicit_historical_interval": False,
            "source_url": identity_ref["source_url"], "source_sha256": identity_ref["source_sha256"],
            "confidence": "UNRESOLVED", "review_status": "MANUAL_REVIEW",
        })

    inventory = None
    if coverage and all(coverage.get(k) for k in ("source_url", "source_sha256", "local_path")):
        inventory = json.loads(read(coverage, "coverage", primary=False))
        if (inventory.get("index_id") != "NIFTY_200" or
                inventory.get("coverage_from") != seed_at.date().isoformat() or
                inventory.get("coverage_to") != day.isoformat()):
            missing.add("source_coverage_range_mismatch")
        expected = [_pair(r) for r in inventory.get("notice_sources", [])]
        if len(expected) != len(set(expected)) or set(expected) != set(notice_pairs):
            missing.add("source_coverage_notice_set_mismatch")
        missing.add("source_coverage_inventory_admission_required")

    result: dict[str, Any] = {
        "index_id": "NIFTY_200", "date": day.isoformat(), "known_at": None,
        "confidence": "UNRESOLVED", "review_status": "MANUAL_REVIEW",
        "source_url": seed["source_url"], "source_sha256": seed["source_sha256"],
        "members": members, "missing_evidence": sorted(missing),
        "derivation": {
            "schema_version": 1, "start_at": start_at.isoformat(),
            "seed_capture_at": seed_at.isoformat(), "seed_member_count": len(seed_rows),
            "actions": actions, "renames": alias_steps,
            "checkpoint_proof_sha256": checkpoint["source_sha256"],
            "source_dependencies": sorted(dependencies.values(), key=lambda r: (
                r["role"], r["source_url"], r["source_sha256"])),
            "coverage_inventory": inventory,
        },
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["derivation_sha256"] = hashlib.sha256(encoded).hexdigest()
    return result
