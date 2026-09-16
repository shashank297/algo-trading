from datetime import date
from types import SimpleNamespace
import zipfile

from tools.nifty200_pit.build_public_dataset import _blocker_ledger, _monthly_gap_rows
from tools.nifty200_pit.models import Conflict, Observation, SourceRecord
from tools.nifty200_pit.source_catalogue import sha256_file


def _monthly_source(tmp_path, *, member=None, data=b"<html>Error 404</html>"):
    path = tmp_path / "monthly.zip"
    if member:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, data)
    else:
        path.write_bytes(data)
    return SourceRecord(
        "https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataApr2022.zip",
        str(path), sha256_file(path), "2026-09-16T00:00:00+00:00",
    )


def _monthly_result(source):
    coverage = [{"period": "2022-04", "snapshot_member_count": "0", "status": "BLOCKED"}]
    gaps = _monthly_gap_rows(coverage, [], [], [source])
    ledger = _blocker_ledger(SimpleNamespace(reasons=["2022-04:0"]), conflicts=[],
                             events=[], snapshots=[], coverage=coverage, sources=[source])
    return gaps[0], ledger[0]


def test_other_index_archive_is_not_a_found_nifty200_snapshot(tmp_path):
    gap, blocker = _monthly_result(_monthly_source(tmp_path, member="Nifty50.pdf"))
    assert gap["official_snapshot_found"] == "FALSE"
    assert gap["status"] == "A_ARCHIVE_WITHOUT_NIFTY200_MEMBER"
    assert blocker["blocker_type"] == "MONTHLY_SNAPSHOT_MISSING"
    assert "NIFTY-200" in blocker["root_cause"]


def test_html_error_with_zip_url_is_a_source_failure_not_parser_failure(tmp_path):
    gap, blocker = _monthly_result(_monthly_source(tmp_path))
    assert gap["official_snapshot_found"] == "FALSE"
    assert gap["status"] == "E_HTML_RESPONSE_NOT_ARCHIVE"
    assert blocker["blocker_type"] == "SOURCE_DOWNLOAD_FAILURE"


def test_zero_rows_from_candidate_member_require_extraction_review(tmp_path):
    gap, blocker = _monthly_result(_monthly_source(tmp_path, member="CNX200.pdf"))
    assert gap["official_snapshot_found"] == "FALSE"
    assert gap["status"] == "B_CANDIDATE_MEMBER_ZERO_ROWS"
    assert blocker["blocker_type"] == "SOURCE_EXTRACTION_REVIEW"


def test_monthly_hash_mismatch_cannot_prove_absence_of_target_member(tmp_path):
    source = _monthly_source(tmp_path, member="Nifty50.pdf")
    from pathlib import Path
    Path(source.local_path).write_bytes(b"replaced")
    gap, blocker = _monthly_result(source)
    assert gap["status"] == "E_SOURCE_HASH_MISMATCH"
    assert blocker["blocker_type"] == "SOURCE_DOWNLOAD_FAILURE"


def _removal_ledger(prior_events):
    observation = Observation(symbol="BATAINDIA", instrument_id="NEW-ID", isin="NEW-ISIN",
                              effective_date=date(2024, 3, 28), action="DROP", observation_id="drop")
    conflict = Conflict("absent", date(2024, 3, 28), "CRITICAL", "REMOVAL_OF_ABSENT_MEMBER",
                        "Cannot remove an inactive instrument.", observation_ids=["drop"])
    return _blocker_ledger(SimpleNamespace(reasons=["unresolved_conflict:absent"]),
                          conflicts=[conflict], events=prior_events, observations=[observation],
                          snapshots=[], coverage=[], sources=[])[0]


def test_absent_removal_does_not_prove_initial_anchor_membership():
    row = _removal_ledger([])
    assert row["blocker_type"] == "MISSING_MEMBERSHIP_HISTORY"
    assert "not established" in row["root_cause"]


def test_prior_different_isin_add_is_a_transition_candidate_not_an_anchor_gap():
    event = SimpleNamespace(symbol="BATAINDIA", index_id="NIFTY_200", action="ADD",
                            instrument_id="OLD-ID", isin="OLD-ISIN", event_hash="prior-hash",
                            effective_date=date(2012, 4, 27))
    row = _removal_ledger([event])
    assert row["blocker_type"] == "HISTORICAL_ISIN_CHANGE"
    assert "prior-hash" in row["notes"]
    assert row["resolution_status"] == "UNRESOLVED"
    event.index_id = "NIFTY_500"
    assert _removal_ledger([event])["blocker_type"] == "MISSING_MEMBERSHIP_HISTORY"
