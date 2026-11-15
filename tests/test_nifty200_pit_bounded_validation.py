from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json

import pytest

from tools.nifty200_pit.intervals import build_intervals
from tools.nifty200_pit.models import Action, CanonicalEvent, Confidence, ReviewStatus
from tools.nifty200_pit.validation import validate_campaign


IST = timezone(timedelta(hours=5, minutes=30))


def _event(number):
    return CanonicalEvent(
        index_id="NIFTY_200", instrument_id=f"SEC-{number}", isin=None,
        symbol=f"SEC{number}", company_name=None,
        announcement_date=date(2019, 12, 27),
        known_at=datetime(2019, 12, 30, 9, 15, tzinfo=IST),
        known_at_basis="DATE_ONLY_CONSERVATIVE_NEXT_SESSION",
        effective_date=date(2019, 12, 30), action=Action.INITIAL_MEMBER,
        reason="fixture", source_url="https://www.nseindia.com/fixture",
        archive_url=None, source_sha256=f"{number + 1:064x}", source_page=1,
        source_tier="A1", extraction_method="PDF_TEXT", extractor_version="test",
        confidence=Confidence.CERTIFIED, review_status=ReviewStatus.ACCEPTED,
        event_hash=f"{number + 1:064x}",
    )


@pytest.mark.parametrize("change", [
    {"known_at": datetime(2030, 1, 1, tzinfo=IST)},
    {"known_at": datetime(2019, 12, 30, 12, tzinfo=timezone(timedelta(hours=-12)))},
    {"review_status": ReviewStatus.MANUAL_REVIEW},
    {"confidence": Confidence.PROVISIONAL},
])
def test_validator_rejects_ineligible_events_even_with_certified_intervals(change):
    events = [_event(i) for i in range(200)]
    intervals = build_intervals(events).intervals
    changed = [replace(events[0], **change), *events[1:]]
    report = validate_campaign(
        intervals, changed, campaign_from=date(2020, 1, 2),
        campaign_to=date(2020, 1, 3),
        trading_days=[date(2020, 1, 2), date(2020, 1, 3)],
        initial_anchor_established=True, calendar_certified=True,
        calendar_provenance="test fixture",
    )
    assert not report.passed


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def package(tmp_path):
    source = tmp_path / "official.txt"
    source.write_text("Artificial exchange evidence fixture", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    url = "https://www.nseindia.com/fixture"
    proof = {"source_sha256": digest, "source_url": url,
             "confidence": "CERTIFIED", "review_status": "ACCEPTED"}
    members = [{"instrument_id": f"SEC-{i}", "symbol": f"SEC{i}", "isin": f"INE{i:06d}001",
                "valid_from": "2019-12-27", "valid_until": None,
                "has_explicit_historical_interval": True, **proof} for i in range(200)]
    anchor = {"date": "2020-01-02", "known_at": "2020-01-02T09:00:00+05:30",
              "members": members, "applied_event_hashes": [], **proof}
    refs = {}
    refs["anchor"] = _write(tmp_path / "anchor.json", anchor)
    events = [replace(_event(i), source_sha256=digest, isin=members[i]["isin"]) for i in range(200)]
    intervals = build_intervals(events).intervals
    values = {
        "events": [e.to_dict() for e in events],
        "intervals": [r.to_dict() for r in intervals], "conflicts": [],
        "continuity": [],
        "identities": members,
        "checkpoints": [{"date": d, "members": members, **proof} for d in ["2020-01-02", "2020-01-03"]],
        "calendar": {"coverage_from": "2019-12-27", "coverage_to": "2020-01-03", **proof,
                     "count_evidence": [{"evidence_type": "MEMBERSHIP_COUNT", "index_id": "NIFTY_200",
                                         "coverage_from": "2019-12-27", "coverage_to": "2020-01-06",
                                         "expected_member_count": 200, **proof}],
                     "records": [{"date": d.isoformat(), "is_session": d.weekday() < 5,
                                  "open_at": d.isoformat() + "T09:15:00+05:30" if d.weekday() < 5 else None,
                                  "expected_member_count": 200, "count_source_sha256": digest,
                                  "source_sha256": digest} for d in [date(2019, 12, 27) + timedelta(days=i) for i in range(8)]]},
        "source_catalogue": [{"local_path": str(source), "source_sha256": digest,
                              "source_url": url, "source_tier": "A1", "document_date": "2019-12-27", "status": "downloaded"}],
    }
    for name, value in values.items():
        refs[name] = _write(tmp_path / (name + ".json"), value)
    manifest = {"schema_version": 1, "index_id": "NIFTY_200",
                "campaign_from": "2020-01-02", "campaign_to": "2020-01-03", "artifacts": refs}
    path = tmp_path / "package.json"
    _write(path, manifest)
    return path


def _mutate(package, name, change):
    manifest = json.loads(package.read_text(encoding="utf-8"))
    path = package.parent / manifest["artifacts"][name]["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    manifest["artifacts"][name] = _write(path, value)
    _write(package, manifest)


def _validate(package):
    from tools.nifty200_pit.bounded_validation import validate_bounded_package
    return validate_bounded_package(package, campaign_from=date(2020, 1, 2), campaign_to=date(2020, 1, 3))


def _dated_source(package, name, publication_date, timestamp=None):
    path = package.parent / (name + ".txt")
    path.write_text("Artificial dated evidence: " + name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    url = "https://www.nseindia.com/" + name
    _mutate(package, "source_catalogue", lambda rows: rows.append({
        "local_path": str(path), "source_url": url, "source_sha256": digest,
        "source_tier": "A1", "document_date": publication_date,
        "publication_timestamp": timestamp,
    }))
    return digest, url


def test_complete_bound_package_executes_validator(package):
    report = _validate(package)
    assert report.passed, report.reasons
    assert report.metrics["trading_days_checked"] == 2


def test_incomplete_calendar_cannot_be_asserted_complete(package):
    _mutate(package, "calendar", lambda data: data["records"].pop())
    report = _validate(package)
    assert not report.passed
    assert any("calendar_coverage" in r for r in report.reasons)


def test_same_count_wrong_checkpoint_members_blocks(package):
    data = json.loads((package.parent / "identities.json").read_text())
    other = dict(data[0], instrument_id="OTHER", symbol="OTHER", isin="INE999999001")
    _mutate(package, "identities", lambda rows: rows.append(other))
    _mutate(package, "checkpoints", lambda rows: rows[-1]["members"].__setitem__(0, other))
    report = _validate(package)
    assert not report.passed
    assert any("checkpoint_members" in r for r in report.reasons)


def test_tampered_input_hash_blocks(package):
    (package.parent / "events.json").write_text("[]", encoding="utf-8")
    assert any("artifact_hash" in r for r in _validate(package).reasons)


def test_anchor_known_after_start_blocks(package):
    _mutate(package, "anchor", lambda row: row.update(known_at="2020-01-03T09:00:00+05:30"))
    assert any("anchor_causality" in r for r in _validate(package).reasons)


def test_certified_label_cannot_override_unresolved_anchor_evidence(package):
    _mutate(package, "anchor", lambda row: row.update(
        missing_evidence=["causal_availability_not_established"],
    ))
    result = _validate(package)
    assert "bounded_input:anchor_derivation_evidence_unresolved" in result.reasons
    assert result.metrics["actual_validator_executed"] is False


@pytest.mark.parametrize("change,reason", [
    (lambda rows: rows[0].update(review_status="MANUAL_REVIEW"), "non_certifiable_event"),
    (lambda rows: rows[0].update(known_at="2030-01-01T09:15:00+05:30"), "event_causality"),
    (lambda rows: rows[0].update(known_at="2019-12-30T09:16:00+05:30"), "event_causality"),
    (lambda rows: rows[0].update(known_at="2019-12-30T09:15:00"), "timezone_required"),
    (lambda rows: rows[0].update(source_sha256="f" * 64), "unregistered_authority"),
])
def test_bounded_event_eligibility_and_causality(package, change, reason):
    _mutate(package, "events", change)
    assert any(reason in r for r in _validate(package).reasons)


def test_raw_source_tampering_blocks(package):
    (package.parent / "official.txt").write_text("changed")
    assert any("source_hashes" in r for r in _validate(package).reasons)


def test_missing_checkpoint_blocks(package):
    _mutate(package, "checkpoints", lambda rows: rows.pop())
    assert any("checkpoint_coverage" in r for r in _validate(package).reasons)


@pytest.mark.parametrize("conflict_date", [None, "2019-12-31", "2020-01-03"])
def test_undated_prebound_and_inbound_conflicts_remain_blocking(package, conflict_date):
    _mutate(package, "conflicts", lambda rows: rows.append({
        "conflict_id": "retained", "date": conflict_date, "severity": "CRITICAL",
        "conflict_type": "TEST", "message": "Requires evidence disposition",
    }))
    assert "unresolved_conflict:retained" in _validate(package).reasons


def test_postbound_conflict_is_reported_as_outside_scope(package):
    _mutate(package, "conflicts", lambda rows: rows.append({
        "conflict_id": "future", "date": "2020-01-06", "severity": "CRITICAL",
        "conflict_type": "TEST", "message": "After bounded horizon",
    }))
    report = _validate(package)
    assert report.passed, report.reasons
    assert report.metrics["post_bound_conflict_ids"] == ["future"]


def test_competing_open_identity_evidence_is_not_ignored(package):
    def change(rows):
        rows.append(dict(rows[0], instrument_id="COMPETITOR", isin="INE999999001", valid_from=None))
    _mutate(package, "identities", change)
    assert any("identity_interval_unproven" in r for r in _validate(package).reasons)


def test_201_member_period_preserves_distinct_dvr(package):
    rows = json.loads((package.parent / "identities.json").read_text())
    member = dict(rows[0], instrument_id="SEC-200", symbol="TATAMTRDVR", isin="IN9155A01020")
    extra = replace(_event(200), symbol="TATAMTRDVR", isin=member["isin"], source_sha256=member["source_sha256"])
    _mutate(package, "identities", lambda rows: rows.append(member))
    _mutate(package, "anchor", lambda data: data["members"].append(member))
    _mutate(package, "checkpoints", lambda rows: [r["members"].append(member) for r in rows])
    _mutate(package, "events", lambda rows: rows.append(extra.to_dict()))
    _mutate(package, "intervals", lambda rows: rows.append(build_intervals([extra]).intervals[0].to_dict()))
    _mutate(package, "calendar", lambda data: [r.update(expected_member_count=201)
        for r in data["records"] + data["count_evidence"]])
    report = _validate(package)
    assert report.passed, report.reasons
    assert set(report.metrics["daily_member_counts"].values()) == {201}


def test_reviewed_continuity_is_consumed_without_membership_events(package):
    identities = json.loads((package.parent / "identities.json").read_text())
    new = dict(identities[0], instrument_id="NEW-0", isin="INE999999001", valid_from="2020-01-03")
    _mutate(package, "identities", lambda rows: (rows[0].update(valid_until="2020-01-03"), rows.append(new)))
    _mutate(package, "checkpoints", lambda rows: rows[-1]["members"].__setitem__(0, new))
    link = {k: new[k] for k in ["source_sha256", "source_url", "confidence", "review_status"]}
    link.update(from_instrument_id="SEC-0", to_instrument_id="NEW-0",
                effective_date="2020-01-03", known_at="2020-01-02T09:15:00+05:30")
    _mutate(package, "continuity", lambda rows: rows.append(link))
    report = _validate(package)
    assert report.passed, report.reasons


def test_interval_and_event_knowledge_must_agree(package):
    _mutate(package, "intervals", lambda rows: rows[0].update(known_at="2019-12-27T09:00:00+05:30"))
    assert any("interval_entry_lineage" in r for r in _validate(package).reasons)


def test_repeated_validation_has_identical_semantics(package):
    first, second = _validate(package), _validate(package)
    assert first.passed and second.passed
    assert first.metrics == second.metrics
    assert first.reasons == second.reasons


def test_cli_executes_bounded_path_without_creating_legacy_outputs(package, capsys):
    from tools.nifty200_pit.cli import main
    untouched = package.parent / "unused-root"
    output = package.parent / "new-report.json"
    args = ["--root", str(untouched), "validate", "--evidence-package", str(package),
            "--campaign-from", "2020-01-02", "--campaign-to", "2020-01-03", "--output", str(output)]
    assert main(args) == 0
    assert not untouched.exists()
    assert json.loads(output.read_text())["metrics"]["actual_validator_executed"]
    with pytest.raises(FileExistsError):
        main(args)
    capsys.readouterr()


def test_seed_intervals_use_anchor_lineage_without_synthetic_events(package):
    manifest = json.loads(package.read_text())
    ref = "ANCHOR:" + manifest["artifacts"]["anchor"]["sha256"]
    def change(rows):
        for row in rows:
            row.update(entry_event_hash=ref, effective_from="2020-01-02", known_from="2020-01-02",
                       known_at="2020-01-02T09:00:00+05:30")
    _mutate(package, "events", lambda rows: rows.clear())
    _mutate(package, "intervals", change)
    report = _validate(package)
    assert report.passed, report.reasons
    assert report.metrics["event_count"] == 0


def test_source_publication_after_anchor_cannot_establish_availability(package):
    _mutate(package, "source_catalogue", lambda rows: rows[0].update(document_date="2020-01-03"))
    assert any("source_publication_not_established" in r for r in _validate(package).reasons)


def test_missing_package_artifact_is_not_evaluable(package):
    manifest = json.loads(package.read_text())
    del manifest["artifacts"]["calendar"]
    _write(package, manifest)
    report = _validate(package)
    assert not report.passed
    assert report.metrics["actual_validator_executed"] is False


def test_replay_add_and_drop_matches_exact_checkpoint(package):
    from tools.nifty200_pit.cli import _event as deserialize
    rows = json.loads((package.parent / "identities.json").read_text())
    member = dict(rows[0], instrument_id="SEC-200", symbol="SEC200", isin="INE999999001", valid_from="2020-01-03")
    digest, url = _dated_source(package, "dec31-release", "2019-12-31")
    additions = []
    for number, action in [(0, Action.DROP), (200, Action.ADD)]:
        base = _event(number)
        additions.append(replace(base, action=action, source_sha256=digest, source_url=url,
            isin=rows[0]["isin"] if number == 0 else member["isin"],
            event_hash=f"{number + 1001:064x}", announcement_date=date(2019, 12, 31),
            known_at=datetime(2020, 1, 1, 9, 15, tzinfo=IST), effective_date=date(2020, 1, 3)))
    _mutate(package, "identities", lambda data: data.append(member))
    _mutate(package, "events", lambda data: data.extend(e.to_dict() for e in additions))
    _mutate(package, "checkpoints", lambda data: data[-1]["members"].__setitem__(0, member))
    events = [deserialize(r) for r in json.loads((package.parent / "events.json").read_text())]
    _mutate(package, "intervals", lambda data: (data.clear(), data.extend(r.to_dict() for r in build_intervals(events).intervals)))
    report = _validate(package)
    assert report.passed, report.reasons


def test_interval_future_exit_is_preserved_and_explicitly_outside_scope(package):
    _mutate(package, "intervals", lambda rows: rows[0].update(
        effective_until="2020-01-06", exit_event_hash="f" * 64))
    report = _validate(package)
    assert report.passed, report.reasons
    assert len(report.metrics["post_bound_interval_exit_ids"]) == 1


def test_start_date_event_must_agree_with_seed(package):
    rows = json.loads((package.parent / "identities.json").read_text())
    member = dict(rows[0], instrument_id="SEC-200", symbol="SEC200", isin="INE999999001")
    digest, url = _dated_source(package, "start-release", "2019-12-31")
    event = replace(_event(200), action=Action.ADD, effective_date=date(2020, 1, 2),
                    announcement_date=date(2019, 12, 31), known_at=datetime(2020, 1, 1, 9, 15, tzinfo=IST),
                    isin=member["isin"], source_sha256=digest, source_url=url)
    _mutate(package, "identities", lambda data: data.append(member))
    _mutate(package, "events", lambda data: data.append(event.to_dict()))
    _mutate(package, "anchor", lambda data: data["applied_event_hashes"].append(event.event_hash))
    assert any("anchor_event_postcondition" in r for r in _validate(package).reasons)


def test_identity_competitor_between_checkpoints_blocks(package):
    manifest = json.loads(package.read_text())
    manifest["campaign_to"] = "2020-01-06"
    _write(package, manifest)
    def calendar_change(data):
        data["coverage_to"] = "2020-01-06"
        for i in range(3):
            day = date(2020, 1, 4) + timedelta(days=i)
            data["records"].append(dict(data["records"][-1], date=day.isoformat(),
                is_session=day.weekday() < 5, open_at=day.isoformat() + "T09:15:00+05:30" if day.weekday() < 5 else None))
    _mutate(package, "calendar", calendar_change)
    _mutate(package, "checkpoints", lambda data: data[-1].update(date="2020-01-06"))
    _mutate(package, "identities", lambda data: data.append(dict(data[0], instrument_id="COMPETITOR",
        isin="INE999999001", valid_from="2020-01-03", valid_until="2020-01-04", review_status="MANUAL_REVIEW")))
    from tools.nifty200_pit.bounded_validation import validate_bounded_package
    report = validate_bounded_package(package, campaign_from=date(2020, 1, 2), campaign_to=date(2020, 1, 6))
    assert not report.passed


@pytest.mark.parametrize("field,value", [("symbol_at_entry", "OTHER"), ("isin_at_entry", "INE999999001")])
def test_interval_identity_fields_match_entry_evidence(package, field, value):
    _mutate(package, "intervals", lambda rows: rows[0].update({field: value}))
    assert not _validate(package).passed


def test_publication_cannot_borrow_date_from_different_untrusted_record(package):
    def change(rows):
        rows[0]["document_date"] = "2020-01-03"
        rows.append(dict(rows[0], source_url="https://untrusted.example", source_tier="E", document_date="2019-12-27"))
    _mutate(package, "source_catalogue", change)
    assert not _validate(package).passed


def test_date_only_source_does_not_prove_same_day_preopen_availability(package):
    digest, url = _dated_source(package, "anchor-date-only", "2020-01-02")
    _mutate(package, "anchor", lambda data: data.update(source_sha256=digest, source_url=url))
    assert any("source_publication_not_established" in r for r in _validate(package).reasons)


def test_exact_source_timestamp_can_establish_same_day_anchor_availability(package):
    digest, url = _dated_source(package, "anchor-exact", "2020-01-02", "2020-01-02T08:00:00+05:30")
    _mutate(package, "anchor", lambda data: data.update(source_sha256=digest, source_url=url))
    report = _validate(package)
    assert report.passed, report.reasons


@pytest.mark.parametrize("same_day", [False, True])
def test_exact_publication_chronology(package, same_day):
    source = package.parent / "timed-source.txt"
    source.write_text("Artificial exact publication evidence")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    publication = "2019-12-30T08:00:00+05:30" if same_day else "2019-12-28T08:00:00+05:30"
    _mutate(package, "source_catalogue", lambda rows: rows.append({
        "local_path": str(source), "source_url": "https://www.nseindia.com/timed-fixture",
        "source_sha256": digest, "source_tier": "A1", "document_date": publication[:10],
        "publication_timestamp": publication,
    }))
    def change(rows):
        rows[0].update(known_at_basis="EXACT_SOURCE_TIMESTAMP",
            source_sha256=digest, source_url="https://www.nseindia.com/timed-fixture",
            announcement_date="2019-12-30" if same_day else "2019-12-29",
            known_at="2019-12-30T08:00:00+05:30" if same_day else "2019-12-28T08:00:00+05:30")
    _mutate(package, "events", change)
    _mutate(package, "intervals", lambda rows: rows[0].update(
        known_from="2019-12-30" if same_day else "2019-12-29",
        known_at="2019-12-30T08:00:00+05:30" if same_day else "2019-12-28T08:00:00+05:30"))
    report = _validate(package)
    assert report.passed is same_day, report.reasons


def test_same_day_alias_collision_requires_ordering_evidence(package):
    from tools.nifty200_pit.cli import _event as deserialize
    identities = json.loads((package.parent / "identities.json").read_text())
    new = dict(identities[0], instrument_id="NEW-0", isin="INE999999001", valid_from="2020-01-03")
    _mutate(package, "identities", lambda data: (data[0].update(valid_until="2020-01-03"), data.append(new)))
    _mutate(package, "checkpoints", lambda data: data[-1]["members"].__setitem__(0, new))
    link = {k: new[k] for k in ["source_sha256", "source_url", "confidence", "review_status"]}
    link.update(from_instrument_id="SEC-0", to_instrument_id="NEW-0",
                effective_date="2020-01-03", known_at="2020-01-02T09:15:00+05:30")
    _mutate(package, "continuity", lambda data: data.append(link))
    digest, url = _dated_source(package, "alias-release", "2019-12-31")
    extra = [replace(_event(0), instrument_id=identity, isin=new["isin"], action=action,
        source_sha256=digest, source_url=url, effective_date=date(2020, 1, 3),
        announcement_date=date(2019, 12, 31), known_at=datetime(2020, 1, 1, 9, 15, tzinfo=IST),
        event_hash=f"{1000+i:064x}") for i, (identity, action) in enumerate([("SEC-0", Action.DROP), ("NEW-0", Action.ADD)])]
    _mutate(package, "events", lambda data: data.extend(e.to_dict() for e in extra))
    events = [deserialize(r) for r in json.loads((package.parent / "events.json").read_text())]
    _mutate(package, "intervals", lambda data: (data.clear(), data.extend(r.to_dict() for r in build_intervals(events).intervals)))
    report = _validate(package)
    assert any("same_day_event_collision" in r for r in report.reasons)


def test_documented_symbol_rename_preserves_historical_interval_fields(package):
    identities = json.loads((package.parent / "identities.json").read_text())
    renamed = dict(identities[0], symbol="RENAMED", valid_from="2020-01-03")
    _mutate(package, "identities", lambda data: (data[0].update(valid_until="2020-01-03"), data.append(renamed)))
    _mutate(package, "checkpoints", lambda data: data[-1]["members"].__setitem__(0, renamed))
    link = {k: renamed[k] for k in ["source_sha256", "source_url", "confidence", "review_status", "isin"]}
    link.update(from_instrument_id="SEC-0", to_instrument_id="SEC-0", from_symbol="SEC0", to_symbol="RENAMED",
                effective_date="2020-01-03", known_at="2020-01-02T09:15:00+05:30")
    _mutate(package, "continuity", lambda data: data.append(link))
    report = _validate(package)
    assert report.passed, report.reasons


def test_exact_basis_from_existing_causality_helper_is_supported(package):
    from tools.nifty200_pit.causality import derive_known_at
    stamp, basis, reason = derive_known_at(date(2019, 12, 30), exact_timestamp=datetime(2019, 12, 30, 8, tzinfo=IST))
    assert reason is None and basis == "EXACT_SOURCE_TIMESTAMP"
    assert stamp is not None
    digest, url = _dated_source(package, "existing-timestamp-policy", "2019-12-30", stamp.isoformat())
    _mutate(package, "events", lambda rows: rows[0].update(source_sha256=digest, source_url=url,
        known_at_basis=basis, announcement_date="2019-12-30", known_at=stamp.isoformat()))
    _mutate(package, "intervals", lambda rows: rows[0].update(known_from="2019-12-30", known_at=stamp.isoformat()))
    report = _validate(package)
    assert report.passed, report.reasons


def test_bounded_producer_assembles_all_roles_with_calendar_amendments(tmp_path):
    from pathlib import Path
    from tools.nifty200_pit.bounded_producer import assemble_bounded_package
    from tools.nifty200_pit.bounded_validation import validate_bounded_package

    workspace_root = Path(__file__).resolve().parent.parent
    catalogue = workspace_root / "data/raw/nifty200_pit_public_sources/source_catalogue.json"
    if not catalogue.is_file():
        pytest.skip("Requires the registered NSE source corpus outside Git")
    result = assemble_bounded_package(
        root=workspace_root,
        campaign_from=date(2016, 1, 29),
        campaign_to=date(2022, 3, 31),
        output_dir=tmp_path / "bounded_pkg",
        overwrite=True,
    )

    manifest = result.manifest
    assert manifest["index_id"] == "NIFTY_200"
    required = {"source_catalogue", "anchor", "calendar", "identities", "continuity", "events", "intervals", "checkpoints", "conflicts"}
    assert set(manifest["artifacts"].keys()) == required

    calendar = json.loads((tmp_path / "bounded_pkg" / "calendar.json").read_text(encoding="utf-8"))
    records_by_date = {r["date"]: r for r in calendar["records"]}

    # Budget Saturday 2020-02-01 is open with 09:15 open time
    budget_sat = records_by_date["2020-02-01"]
    assert budget_sat["is_session"] is True
    assert "09:15:00" in budget_sat["open_at"]

    # Elections 2019-04-29 and 2019-10-21 are closed
    assert records_by_date["2019-04-29"]["is_session"] is False
    assert records_by_date["2019-10-21"]["is_session"] is False

    # Muhurat sessions have verified primary circular opening times
    assert "18:30:00" in records_by_date["2016-10-30"]["open_at"]
    assert "18:30:00" in records_by_date["2017-10-19"]["open_at"]
    assert "17:30:00" in records_by_date["2018-11-07"]["open_at"]
    assert "18:15:00" in records_by_date["2019-10-27"]["open_at"]
    assert "18:15:00" in records_by_date["2020-11-14"]["open_at"]
    assert "18:15:00" in records_by_date["2021-11-04"]["open_at"]

    # Tata Motors DVR 201-member window
    assert records_by_date["2016-03-31"]["expected_member_count"] == 200
    assert records_by_date["2016-04-01"]["expected_member_count"] == 201
    assert records_by_date["2020-06-25"]["expected_member_count"] == 201
    assert records_by_date["2020-06-26"]["expected_member_count"] == 200

    # Identities preserve 1-day checkpoint validity without promotion
    identities = json.loads((tmp_path / "bounded_pkg" / "identities.json").read_text(encoding="utf-8"))
    unresolved_rows = [i for i in identities if i.get("confidence") == "UNRESOLVED"]
    assert len(unresolved_rows) > 0
    assert all(r["review_status"] == "MANUAL_REVIEW" for r in unresolved_rows)

    # Missing or unadmitted count evidence blocks before anchor timestamps.
    report = validate_bounded_package(
        result.package_path,
        campaign_from=date(2016, 1, 29),
        campaign_to=date(2022, 3, 31),
    )
    assert not report.passed
    assert any(reason in report.reasons for reason in [
        "bounded_input:member_count_evidence_missing", "bounded_input:evidence_not_accepted",
    ])
    assert report.metrics["actual_validator_executed"] is False



def test_calendar_source_alone_cannot_prove_member_count(package):
    _mutate(package, "calendar", lambda data: data.pop("count_evidence"))
    report = _validate(package)
    assert not report.passed
    assert report.metrics["actual_validator_executed"] is False
    assert any("member_count_evidence" in r for r in report.reasons)


@pytest.mark.parametrize("change", [
    {"evidence_type": "TRADING_CALENDAR"},
    {"index_id": "NIFTY_50"},
    {"expected_member_count": 201},
    {"expected_member_count": 200.0},
    {"coverage_from": "2020-01-03"},
    {"coverage_to": "2020-01-02"},
    {"coverage_from": "2020-01-04", "coverage_to": "2020-01-03"},
    {"confidence": "PROVISIONAL"},
    {"review_status": "MANUAL_REVIEW"},
    {"source_url": "https://unregistered.example/count"},
    {"source_sha256": "f" * 64},
])
def test_count_proof_requires_admitted_matching_semantics(package, change):
    _mutate(package, "calendar", lambda data: data["count_evidence"][0].update(change))
    report = _validate(package)
    assert not report.passed
    assert report.metrics["actual_validator_executed"] is False


def test_conflicting_count_evidence_blocks_even_when_one_proof_matches(package):
    _mutate(package, "calendar", lambda data: data["count_evidence"].append(
        dict(data["count_evidence"][0], expected_member_count=201)))
    assert not _validate(package).passed


def test_count_source_reference_cannot_substitute_calendar_source(package):
    digest, url = _dated_source(package, "holiday-only", "2019-12-27")
    _mutate(package, "calendar", lambda data: [r.update(count_source_sha256=digest)
        for r in data["records"]])
    assert not _validate(package).passed


def test_dated_count_proofs_cover_inclusive_boundaries(package):
    def split(data):
        proof = data["count_evidence"][0]
        data["count_evidence"] = [dict(proof, coverage_from="2020-01-02", coverage_to="2020-01-02"),
                                  dict(proof, coverage_from="2020-01-03", coverage_to="2020-01-03")]
    _mutate(package, "calendar", split)
    report = _validate(package)
    assert report.passed, report.reasons


def test_duplicate_same_isin_in_anchor_blocks_fail_closed(package):
    _mutate(package, "anchor", lambda data: data["members"].__setitem__(
        1, dict(data["members"][0], instrument_id="SEC-1-DUP")
    ))
    report = _validate(package)
    assert not report.passed
    assert any("duplicate_member_identity" in r for r in report.reasons)


def test_duplicate_same_isin_in_checkpoints_blocks_fail_closed(package):
    _mutate(package, "checkpoints", lambda data: data[0]["members"].__setitem__(
        1, dict(data[0]["members"][0], instrument_id="SEC-1-DUP")
    ))
    report = _validate(package)
    assert not report.passed
    assert any("duplicate_member_identity" in r for r in report.reasons)


def test_competing_candidate_different_isin_blocks_fail_closed(package):
    data = json.loads((package.parent / "identities.json").read_text())
    competing = dict(data[0], isin="INE999999002")
    _mutate(package, "identities", lambda rows: rows.append(competing))
    report = _validate(package)
    assert not report.passed
    assert any("competing_identity" in r for r in report.reasons)


def test_competing_candidate_different_instrument_id_blocks_fail_closed(package):
    data = json.loads((package.parent / "identities.json").read_text())
    competing = dict(data[0], instrument_id="SEC-OTHER")
    _mutate(package, "identities", lambda rows: rows.append(competing))
    report = _validate(package)
    assert not report.passed
    assert any("competing_identity" in r for r in report.reasons)


def test_competing_candidate_unresolved_status_blocks_fail_closed(package):
    data = json.loads((package.parent / "identities.json").read_text())
    competing = dict(
        data[0], instrument_id="COMPETITOR", isin="INE999999003",
        confidence="UNRESOLVED", review_status="MANUAL_REVIEW",
    )
    _mutate(package, "identities", lambda rows: rows.append(competing))
    report = _validate(package)
    assert not report.passed
    assert any("evidence_not_accepted" in r or "identity_interval_unproven" in r for r in report.reasons)


def test_competing_continuity_mappings_block_fail_closed(package):
    data = json.loads((package.parent / "identities.json").read_text())
    link1 = {
        "from_instrument_id": "SEC-0", "to_instrument_id": "NEW-A",
        "effective_date": "2020-01-03", "known_at": "2020-01-02T09:15:00+05:30",
        "source_sha256": data[0]["source_sha256"], "source_url": data[0]["source_url"],
        "confidence": "CERTIFIED", "review_status": "ACCEPTED",
    }
    link2 = {
        "from_instrument_id": "SEC-0", "to_instrument_id": "NEW-B",
        "effective_date": "2020-01-03", "known_at": "2020-01-02T09:15:00+05:30",
        "source_sha256": data[0]["source_sha256"], "source_url": data[0]["source_url"],
        "confidence": "CERTIFIED", "review_status": "ACCEPTED",
    }
    _mutate(package, "continuity", lambda rows: rows.extend([link1, link2]))
    report = _validate(package)
    assert not report.passed
    assert any("competing_continuity" in r for r in report.reasons)


def test_competing_symbol_transitions_block_fail_closed(package):
    data = json.loads((package.parent / "identities.json").read_text())
    new_a = dict(data[0], symbol="NEW-A", valid_from="2020-01-03")
    new_b = dict(data[0], symbol="NEW-B", valid_from="2020-01-03")
    _mutate(package, "identities", lambda rows: (rows[0].update(valid_until="2020-01-03"), rows.extend([new_a, new_b])))
    _mutate(package, "checkpoints", lambda rows: rows[-1]["members"].__setitem__(0, new_a))
    link1 = {
        "from_instrument_id": "SEC-0", "to_instrument_id": "SEC-0",
        "from_symbol": "SEC0", "to_symbol": "NEW-A", "isin": data[0]["isin"],
        "effective_date": "2020-01-03", "known_at": "2020-01-02T09:15:00+05:30",
        "source_sha256": data[0]["source_sha256"], "source_url": data[0]["source_url"],
        "confidence": "CERTIFIED", "review_status": "ACCEPTED",
    }
    link2 = {
        "from_instrument_id": "SEC-0", "to_instrument_id": "SEC-0",
        "from_symbol": "SEC0", "to_symbol": "NEW-B", "isin": data[0]["isin"],
        "effective_date": "2020-01-03", "known_at": "2020-01-02T09:15:00+05:30",
        "source_sha256": data[0]["source_sha256"], "source_url": data[0]["source_url"],
        "confidence": "CERTIFIED", "review_status": "ACCEPTED",
    }
    _mutate(package, "continuity", lambda rows: rows.extend([link1, link2]))
    report = _validate(package)
    assert not report.passed
    assert any("competing_symbol_transition" in r for r in report.reasons)


def test_overlapping_active_intervals_for_same_instrument_block_fail_closed(package):
    _mutate(package, "intervals", lambda rows: rows.append(
        dict(rows[0], interval_id="SEC-0-OVERLAP")
    ))
    report = _validate(package)
    assert not report.passed
    assert any("interval_overlap:SEC-0" in r or "duplicate_active_instrument" in r for r in report.reasons)
