"""Source-bound candidate-anchor replay; no certification or database access."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _pdf(path, text, *continuation_pages):
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_reference = writer._add_object(font)
    for content in (text, *continuation_pages):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference}),
        })
        escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                   for line in content.splitlines()]
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 10 Tf 20 760 Td 12 TL " +
                         " ".join(f"({line}) Tj T*" for line in escaped) + " ET").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


def _source(path, url, tier="A1"):
    return {"local_path": str(path), "source_url": url,
            "source_sha256": sha256(path.read_bytes()).hexdigest(), "source_tier": tier}


def _derive(inputs):
    # Import at execution time so RED reports the missing feature per regression.
    module = importlib.import_module("tools.nifty200_pit.anchor_derivation")
    return module.derive_anchor_candidate(**inputs)


@pytest.fixture
def evidence(tmp_path):
    seed_path = tmp_path / "seed.csv"
    seed_path.write_text("Company Name,Industry,Symbol,Series,ISIN Code\n"
                         "Old Ltd,Industry,OLD,EQ,INE000A01010\n"
                         "Sesa Ltd,Industry,SSLT,EQ,INE205A01025\n")
    seed = _source(seed_path, "https://web.archive.org/web/20150325063347id_/"
                   "http://nseindia.com/content/indices/ind_cnx200list.csv", "A2")
    notice_path = tmp_path / "notice.pdf"
    _pdf(notice_path, "Date: April 29, 2015\nPRESS RELEASE\n"
         "Changes shall become effective from May 29, 2015 (close of May 28, 2015).\n"
         "(1) CNX 200 Index\nThe following company is being excluded:\n"
         "Sr. No. Company Name Symbol\n1 Old Ltd. OLD\n"
         "The following company is being included:\n"
         "Sr. No. Company Name Symbol\n1 New Ltd. NEW\n(2) CNX 500 Index")
    notice = _source(notice_path, "https://www.niftyindices.com/Press_Release/review.pdf")
    rename_path = tmp_path / "rename.pdf"
    _pdf(rename_path, "Earlier Sesa Sterlite Limited\nNSE SSL T INE205A01025\n"
         "Now Vedanta Limited\nNSE VEDL INE205A01025")
    rename_source = _source(rename_path, "https://www.vedantalimited.com/report.pdf")
    rename = {**rename_source, "from_symbol": "SSLT", "to_symbol": "VEDL",
              "isin": "INE205A01025", "source_page": 1,
              "old_quote": "NSE SSL T INE205A01025", "new_quote": "NSE VEDL INE205A01025"}
    checkpoint_path = tmp_path / "checkpoint.csv"
    checkpoint_path.write_text(
        "checkpoint_date,durable_instrument_id,source_symbol,resolved_isin,identity_valid_from,"
        "identity_valid_to,identity_source_hash,identity_source_url_reference\n"
        f"2016-01-29,root:new,NEW,INE000B01010,2016-01-29,2016-01-30,{notice['source_sha256']},{notice['source_url']}\n"
        f"2016-01-29,root:se sa,VEDL,INE205A01025,2016-01-29,2016-01-30,{seed['source_sha256']},{seed['source_url']}\n"
    )
    return {"start_at": datetime.fromisoformat("2016-01-29T09:15:00+05:30"),
            "seed": seed, "notices": [notice], "renames": [rename],
            "checkpoint": _source(checkpoint_path, "urn:test:checkpoint-proof", "DERIVED"),
            "catalogue": [seed, notice, rename_source], "coverage": None}


def test_source_page_is_selected_within_the_nifty200_section(evidence):
    original = evidence["notices"][0]
    path = Path(original["local_path"])
    _pdf(path,
         "Date: April 29, 2015\nChanges shall become effective from May 29, 2015.\n"
         "(1) CNX 200 Index\nThe following company is being excluded:\n1 Old Ltd. OLD",
         "The following company is being included:\n1 New Ltd. NEW\n"
         "(2) CNX 500 Index\nThe following company is being excluded:\n1 Old Ltd. OLD",
         "The following company is being included:\n1 New Ltd. NEW")
    updated = _source(path, original["source_url"])
    evidence["notices"] = [updated]
    evidence["catalogue"] = [updated if s == original else s for s in evidence["catalogue"]]
    checkpoint = evidence["checkpoint"]
    ledger = Path(checkpoint["local_path"])
    ledger.write_text(ledger.read_text().replace(original["source_sha256"], updated["source_sha256"]))
    evidence["checkpoint"] = _source(ledger, checkpoint["source_url"], "DERIVED")

    result = _derive(evidence)

    assert {r["symbol"]: r["source_page"] for r in result["derivation"]["actions"]} == {"OLD": 1, "NEW": 2}
    assert "notice_page_attribution_not_established" not in result["missing_evidence"]
    assert result["review_status"] == "MANUAL_REVIEW"


def test_derives_source_linked_members_without_promoting_checkpoint_or_anchor(evidence):
    result = _derive(evidence)
    assert [(m["symbol"], m["instrument_id"]) for m in result["members"]] == [
        ("NEW", "root:new"), ("VEDL", "root:se sa"),
    ]
    assert result["confidence"] == "UNRESOLVED"
    assert result["review_status"] == "MANUAL_REVIEW"
    assert result["known_at"] is None
    assert result["members"][0]["valid_until"] == "2016-01-30"
    assert result["members"][0]["source_sha256"] == evidence["notices"][0]["source_sha256"]
    assert all(m["confidence"] == "UNRESOLVED" for m in result["members"])
    assert "source_coverage_not_established" in result["missing_evidence"]
    assert "identity_admission_not_established" in result["missing_evidence"]
    assert "causal_availability_not_established" in result["missing_evidence"]
    assert result["derivation"]["actions"][0]["action"] == "DROP"
    assert result["derivation"]["renames"][0]["application"] == "ENDPOINT_ALIAS_ONLY"
    assert len(result["derivation"]["source_dependencies"]) == 4


def test_deterministic_across_input_order_and_no_input_mutation(evidence):
    before = deepcopy(evidence)
    first = _derive(evidence)
    evidence["catalogue"].reverse()
    second = _derive(evidence)
    assert first == second
    assert len(first["derivation_sha256"]) == 64
    assert evidence == {**before, "catalogue": list(reversed(before["catalogue"]))}


@pytest.mark.parametrize("role", ["seed", "notice", "rename", "checkpoint"])
def test_rejects_changed_bytes_for_every_dependency(evidence, role):
    record = {"seed": evidence["seed"], "notice": evidence["notices"][0],
              "rename": evidence["renames"][0], "checkpoint": evidence["checkpoint"]}[role]
    with Path(record["local_path"]).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        _derive(evidence)


def test_rejects_missing_original_and_unregistered_url_hash_pair(evidence):
    evidence["catalogue"] = evidence["catalogue"][:-1]
    with pytest.raises(ValueError, match="source_not_registered"):
        _derive(evidence)


def test_rejects_missing_original_bytes(evidence):
    Path(evidence["notices"][0]["local_path"]).unlink()
    with pytest.raises(ValueError, match="source_missing"):
        _derive(evidence)


@pytest.mark.parametrize("drop,add,reason", [
    ("ABSENT", "NEW", "invalid_drop"), ("OLD", "SSLT", "invalid_add"),
])
def test_rejects_invalid_source_actions(evidence, drop, add, reason):
    path = Path(evidence["notices"][0]["local_path"])
    _pdf(path, "Date: April 29, 2015\nCNX 200 Index\n"
         "Changes shall become effective from May 29, 2015.\n"
         f"The following company is being excluded:\n1 Old Ltd. {drop}\n"
         f"The following company is being included:\n1 New Ltd. {add}")
    updated = _source(path, evidence["notices"][0]["source_url"])
    evidence["notices"] = [updated]
    evidence["catalogue"][1] = updated
    with pytest.raises(ValueError, match=reason):
        _derive(evidence)


@pytest.mark.parametrize("field,value", [
    ("old_quote", "NSE SSLT INE000X01010"), ("isin", "INE000X01010"),
    ("source_page", 2), ("to_symbol", "INVENTED"),
])
def test_rejects_unverifiable_rename(evidence, field, value):
    evidence["renames"][0][field] = value
    with pytest.raises(ValueError, match="rename_not_source_verified"):
        _derive(evidence)


def test_missing_rename_does_not_silently_match_checkpoint_by_isin(evidence):
    evidence["renames"] = []
    with pytest.raises(ValueError, match="checkpoint_symbol_mismatch"):
        _derive(evidence)


def test_rename_cannot_change_share_class_identity(evidence):
    path = Path(evidence["checkpoint"]["local_path"])
    path.write_text(path.read_text().replace("VEDL,INE205A01025", "VEDL,INE999A01010"))
    evidence["checkpoint"] = _source(path, "urn:test:checkpoint-proof", "DERIVED")
    with pytest.raises(ValueError, match="rename_identity_mismatch"):
        _derive(evidence)


@pytest.mark.parametrize("role", ["seed", "notice", "rename"])
def test_rejects_post_start_knowledge(evidence, role):
    if role == "seed":
        evidence["seed"]["source_url"] = evidence["seed"]["source_url"].replace(
            "20150325063347", "20160129120000")
    else:
        item = evidence["notices"][0] if role == "notice" else evidence["renames"][0]
        item["known_at"] = "2016-01-29T09:15:01+05:30"
    with pytest.raises(ValueError, match="post_start_knowledge"):
        _derive(evidence)


def test_missing_notice_never_proves_source_coverage_even_if_endpoint_matches(evidence):
    # An asserted complete flag or source count cannot establish an inventory.
    evidence["coverage"] = {"complete": True, "expected_notice_count": 1}
    result = _derive(evidence)
    assert "source_coverage_not_established" in result["missing_evidence"]
    assert result["confidence"] == "UNRESOLVED"


def test_byte_bound_inventory_detects_an_omitted_notice(evidence, tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"index_id": "NIFTY_200", "coverage_from": "2015-03-25",
        "coverage_to": "2016-01-29", "notice_sources": [
            {"source_url": evidence["notices"][0]["source_url"],
             "source_sha256": evidence["notices"][0]["source_sha256"]},
            {"source_url": "https://www.niftyindices.com/missing.pdf", "source_sha256": "a" * 64},
        ]}))
    evidence["coverage"] = _source(path, "urn:test:inventory", "DERIVED")
    result = _derive(evidence)
    assert "source_coverage_notice_set_mismatch" in result["missing_evidence"]
    assert result["known_at"] is None


def test_checkpoint_duplicate_and_wrong_day_proofs_cannot_supply_anchor(evidence):
    path = Path(evidence["checkpoint"]["local_path"])
    path.write_text(path.read_text().replace("root:se sa", "root:new"))
    evidence["checkpoint"] = _source(path, "urn:test:checkpoint-proof", "DERIVED")
    with pytest.raises(ValueError, match="duplicate_checkpoint_identity"):
        _derive(evidence)


def test_naive_start_time_is_rejected(evidence):
    evidence["start_at"] = datetime(2016, 1, 29, 9, 15)
    with pytest.raises(ValueError, match="timezone_required"):
        _derive(evidence)
