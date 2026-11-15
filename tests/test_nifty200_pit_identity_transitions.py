"""A dated change can end an old observation without certifying a new interval."""

from datetime import date
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from tools.nifty200_pit import identity_transitions
from tools.nifty200_pit.build_public_dataset import parse_security_master
from tools.nifty200_pit.models import SourceRecord


@pytest.fixture
def notice(tmp_path, monkeypatch):
    path = tmp_path / "notice.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(600, 600)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 500 Td (Equity Shares ONE OLDISIN NEWISIN) Tj 0 -20 Td (The New ISIN shall be effective for trades done on and from the Ex-date i.e. January 5, 2016.) Tj ET")
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    url = "https://www.msei.in/fixture.pdf"
    monkeypatch.setattr(identity_transitions, "TRANSITIONS", (("ONE", "OLDISIN", "NEWISIN", date(2016, 1, 5), url, digest),))
    return {"source_url": url, "source_sha256": digest, "source_tier": "A1", "local_path": str(path)}


def test_old_boundary_uses_notice_without_promoting_or_stretching_rows(notice):
    old = {"symbol": "ONE", "isin": "OLDISIN", "series": "EQ", "snapshot_date": "2015-01-01",
           "valid_from": "2000-01-01", "valid_until": None, "confidence": "UNRESOLVED"}
    new = {**old, "isin": "NEWISIN", "snapshot_date": "2016-01-06"}
    rows, audit = identity_transitions.apply_transition_boundaries([old, new], [notice])
    assert old["valid_until"] is None
    assert rows[0]["valid_until"] == "2016-01-05"
    assert rows[0]["confidence"] == "UNRESOLVED"
    assert rows[1]["valid_from"] == "2016-01-05"
    assert rows[1]["confidence"] == "UNRESOLVED"
    assert new["valid_from"] == "2000-01-01"
    assert audit[0]["source_sha256"] == notice["source_sha256"]


def test_successor_boundary_never_extends_validity_or_changes_other_series(notice):
    successor = {
        "symbol": "ONE", "isin": "NEWISIN", "series": "EQ",
        "valid_from": "2010-01-01", "snapshot_date": "2016-01-06",
        "has_explicit_historical_interval": False, "review_status": "MANUAL_REVIEW",
    }
    other_series = {**successor, "series": "IL"}
    later = {**successor, "valid_from": "2016-01-06"}
    rows, audit = identity_transitions.apply_transition_boundaries([successor, other_series, later], [notice])
    assert rows[0]["valid_from"] == "2016-01-05"
    assert rows[0]["review_status"] == "MANUAL_REVIEW"
    assert rows[0]["has_explicit_historical_interval"] is False
    assert rows[1:] == [other_series, later]
    assert audit[0]["previous_valid_from"] == "2010-01-01"


def test_missing_authority_does_not_change_master(notice):
    row = {"symbol": "ONE", "isin": "OLDISIN", "series": "EQ"}
    assert identity_transitions.apply_transition_boundaries([row], [notice | {"source_tier": "B1"}]) == ([row], [])


def test_yesbank_nse_trade_date_bounds_later_listing_snapshot():
    digest = "a4d156c72902691a12f3693d812774384f982e768b0909023e9171eb3ef209cc"
    path = Path(__file__).resolve().parents[1] / "data" / "raw" / "nifty200_pit_public_sources" / "raw" / "a4" / f"{digest}.pdf"
    if not path.is_file():
        pytest.skip("requires the registered NSE Clearing circular corpus")
    source = {
        "source_url": "https://nsearchives.nseindia.com/content/circulars/CMPT43834.pdf",
        "source_sha256": digest, "source_tier": "A1", "local_path": str(path),
    }
    successor = {
        "symbol": "YESBANK", "isin": "INE528G01035", "series": "EQ",
        "valid_from": "2005-07-12", "snapshot_date": "2021-05-16",
        "confidence": "UNRESOLVED", "review_status": "MANUAL_REVIEW",
    }
    predecessor = {**successor, "isin": "INE528G01027", "valid_from": "2017-09-21",
                   "snapshot_date": "2020-03-13"}
    rows, audit = identity_transitions.apply_transition_boundaries([predecessor, successor], [source])
    assert rows[0]["valid_until"] == rows[1]["valid_from"] == "2020-03-16"
    assert rows[1]["review_status"] == "MANUAL_REVIEW"
    for row in audit:
        assert row["source_page"] == 1
        assert row["source_sha256"] == digest


def test_ajantpharm_boundary_uses_adjacent_nse_equity_sessions():
    directory = Path(__file__).resolve().parents[1] / "data/raw/nifty200_pit_public_sources/raw"
    sources = []
    for day, digest in (
        ("09AUG2012", "a87eecb3503634167298bed84d9dfbc1d5b1d0d747faf99d90c525cacb22efb1"),
        ("10AUG2012", "37c18b9ac6eec7168a26e438b6f8ab7d8020961569015753f146d97ed666122c"),
    ):
        path = directory / digest[:2] / f"{digest}.zip"
        if not path.is_file():
            pytest.skip("requires the registered NSE daily files")
        sources.append({
            "source_url": f"https://nsearchives.nseindia.com/content/historical/EQUITIES/2012/AUG/cm{day}bhav.csv.zip",
            "source_sha256": digest, "source_tier": "A1", "local_path": str(path),
        })
    old = {"symbol": "AJANTPHARM", "isin": "INE031B01015", "series": "EQ",
           "valid_from": "2000-05-29", "valid_until": None, "snapshot_date": "2011-10-30",
           "review_status": "MANUAL_REVIEW", "confidence": "UNRESOLVED"}
    rows, audit = identity_transitions.apply_transition_boundaries([old], sources)
    assert rows[0]["valid_until"] == "2012-08-10"
    assert old["valid_until"] is None
    assert rows[0]["review_status"] == "MANUAL_REVIEW"
    assert audit[0]["prior_source_sha256"] == sources[0]["source_sha256"]
    assert audit[0]["source_sha256"] == sources[1]["source_sha256"]
    assert identity_transitions.apply_transition_boundaries([old], sources[1:]) == ([old], [])


def test_ajantpharm_mse_ex_date_does_not_override_nse_trade_observations(tmp_path, monkeypatch):
    """NSE EQ identity remains old through Mar 20 and changes on Mar 23, 2015."""
    from zipfile import ZIP_DEFLATED, ZipFile
    import io

    mse_digest = "d2ddab08e167a24a322a0c3f394565f40592ab5f4014be2fa94cbd5bd60bfad6"
    mse_path = (Path(__file__).resolve().parents[1] / "data/raw/nifty200_pit_public_sources/raw/d2" /
                f"{mse_digest}.pdf")
    if not mse_path.is_file():
        pytest.skip("requires the registered MSE corporate-action circular")
    mse = {
        "source_url": "https://www.msei.in/SX-Content/Circulars/2015/March/Circular-2781.pdf",
        "source_sha256": mse_digest, "source_tier": "A1", "local_path": str(mse_path),
    }

    observations = (("19MAR2015", "INE031B01031"), ("20MAR2015", "INE031B01031"),
                    ("23MAR2015", "INE031B01049"))
    sessions = []
    sources = [mse]
    for day, isin in observations:
        member = f"cm{day}bhav.csv"
        session = date(int(day[5:]), 3, int(day[:2]))
        stamp = session.strftime("%d-%b-%Y").upper()
        payload = f"SYMBOL,SERIES,ISIN,TIMESTAMP\nAJANTPHARM,EQ,{isin},{stamp}\n".encode()
        zipped = io.BytesIO()
        with ZipFile(zipped, "w", ZIP_DEFLATED) as archive:
            archive.writestr(member, payload)
        data = zipped.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        path = tmp_path / f"{digest}.zip"
        path.write_bytes(data)
        url = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/MAR/{member}.zip"
        sessions.append((day, isin, digest))
        sources.append({"source_url": url, "source_sha256": digest, "source_tier": "A1",
                        "local_path": str(path)})

    monkeypatch.setattr(identity_transitions, "_AJANTA_2015_SESSIONS", tuple(sessions), raising=False)
    rows, audit = identity_transitions.apply_transition_boundaries([
        {"symbol": "AJANTPHARM", "isin": "INE031B01031", "series": "EQ", "valid_from": "2000-05-29",
         "valid_until": None, "snapshot_date": "2014-01-01", "confidence": "UNRESOLVED"},
        {"symbol": "AJANTPHARM", "isin": "INE031B01049", "series": "EQ", "valid_from": "2000-05-29",
         "snapshot_date": "2015-03-23", "confidence": "UNRESOLVED"},
    ], sources)

    assert rows[0]["valid_until"] == "2015-03-23"
    assert rows[1]["valid_from"] == "2015-03-23"
    assert all(item["confidence_changed"] is False for item in audit)


def test_ajantpharm_registered_split_timeline_records_exact_nse_isins_and_hashes():
    root = Path(__file__).resolve().parents[1]
    catalogue = json.loads((root / "data/raw/nifty200_pit_public_sources/source_catalogue.json").read_text(
        encoding="utf-8"))
    expected = {
        "2012-08-09": ("INE031B01015", "a87eecb3503634167298bed84d9dfbc1d5b1d0d747faf99d90c525cacb22efb1"),
        "2012-08-10": ("INE031B01031", "37c18b9ac6eec7168a26e438b6f8ab7d8020961569015753f146d97ed666122c"),
        "2012-08-13": ("INE031B01031", "6cf8b5ef21f6976e17c808a158497c7961f2a30793e154492f53c291b4c1eb66"),
        "2015-03-19": ("INE031B01031", "da295c74d69cd74e2df4e33a356913a4fdae654c7dd84df98280d3a8c2212858"),
        "2015-03-20": ("INE031B01031", "d876d3d801afc7c3c315d319f9e96c55f64ab4dfc32074377ca9f2c0a6554271"),
        "2015-03-23": ("INE031B01049", "0e0bf3ba4fbd4e51385f3d91f3f816a2478385cd06d1fd79edf2b6108be5d5a3"),
    }
    for session, (expected_isin, digest) in expected.items():
        date_token = date.fromisoformat(session).strftime("%d%b%Y").upper()
        member = f"cm{date_token}bhav.csv"
        exchange_year = session[:4]
        month = "AUG" if session[5:7] == "08" else "MAR"
        url = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{exchange_year}/{month}/{member}.zip"
        entries = [row for row in catalogue if row["source_url"] == url]
        assert len(entries) == 1
        source = entries[0]
        path = Path(source["local_path"])
        path = path if path.is_absolute() else root / path
        assert source["source_tier"] == "A1"
        assert source["source_sha256"] == digest
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        with ZipFile(path) as archive:
            assert archive.testzip() is None
            with archive.open(member) as stream:
                rows = list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig")))
        equity = [row for row in rows if row["SYMBOL"].strip() == "AJANTPHARM" and
                  row["SERIES"].strip() == "EQ"]
        assert len(equity) == 1
        assert equity[0]["TIMESTAMP"].strip() == date.fromisoformat(session).strftime("%d-%b-%Y").upper()
        assert equity[0]["ISIN"].strip() == expected_isin
        assert int(equity[0]["TOTTRDQTY"]) > 0


def test_ajantpharm_duplicate_registered_transition_source_fails_closed():
    root = Path(__file__).resolve().parents[1]
    catalogue = json.loads((root / "data/raw/nifty200_pit_public_sources/source_catalogue.json").read_text(
        encoding="utf-8"))
    target = "https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/MAR/cm23MAR2015bhav.csv.zip"
    sources = [row for row in catalogue if row["source_url"] in {
        "https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/MAR/cm19MAR2015bhav.csv.zip",
        "https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/MAR/cm20MAR2015bhav.csv.zip",
        target,
    }]
    duplicate = next(row for row in sources if row["source_url"] == target)
    with pytest.raises(ValueError, match="transition_duplicate_source:AJANTPHARM"):
        identity_transitions.apply_transition_boundaries([], sources + [duplicate])


def test_ajantpharm_conflicting_eq_rows_in_verified_source_fail_closed(tmp_path, monkeypatch):
    from zipfile import ZIP_DEFLATED, ZipFile

    sessions = ("19MAR2015", "20MAR2015", "23MAR2015")
    isins = ("INE031B01031", "INE031B01031", "INE031B01049")
    sources = []
    registered = []
    for session, isin in zip(sessions, isins):
        member = f"cm{session}bhav.csv"
        records = [("AJANTPHARM", "EQ", isin, f"{session[:2]}-MAR-2015")]
        if session == "20MAR2015":
            records.append(("AJANTPHARM", "EQ", "INE031B01049", "20-MAR-2015"))
        payload = "SYMBOL,SERIES,ISIN,TIMESTAMP\n" + "".join(",".join(row) + "\n" for row in records)
        archive_path = tmp_path / member.replace(".csv", ".zip")
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            archive.writestr(member, payload)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        year_month = "2015/MAR"
        source = {"source_url": f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{year_month}/{member}.zip",
                  "source_sha256": digest, "source_tier": "A1", "local_path": str(archive_path)}
        sources.append(source)
        registered.append((session, isin, digest))

    monkeypatch.setattr(identity_transitions, "_AJANTA_2015_SESSIONS", tuple(registered), raising=False)
    with pytest.raises(ValueError, match="transition_source_semantics:AJANTPHARM"):
        identity_transitions.apply_transition_boundaries([], sources)


def test_changed_notice_bytes_fail_closed(notice):
    Path(notice["local_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="transition_source_hash"):
        identity_transitions.apply_transition_boundaries([], [notice])


def test_later_old_isin_observation_remains_a_conflict(notice):
    row = {"symbol": "ONE", "isin": "OLDISIN", "series": "EQ", "snapshot_date": "2016-01-06"}
    with pytest.raises(ValueError, match="post_transition_old_isin"):
        identity_transitions.apply_transition_boundaries([row], [notice])


def test_non_equity_scope_and_earlier_end_are_preserved(notice):
    rows = [{"symbol": "ONE", "isin": "OLDISIN", "series": "IL"},
            {"symbol": "ONE", "isin": "OLDISIN", "series": "EQ", "valid_until": "2015-01-02"}]
    assert identity_transitions.apply_transition_boundaries(rows, [notice]) == (rows, [])


def test_master_parser_preserves_scope_even_when_symbol_and_isin_repeat(tmp_path):
    path = tmp_path / "EQUITY_L.csv"
    path.write_text("SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,ISIN NUMBER\n"
                    "ONE,One Limited,EQ,01-JAN-2010,INE000A01010\n"
                    "ONE,One Limited,IL,01-JAN-2010,INE000A01010\n")
    source = SourceRecord(source_url="https://www.nseindia.com/content/equities/EQUITY_L.csv",
                          local_path=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          retrieved_at="2015-01-01T00:00:00Z", document_date="2015-01-01")
    rows = parse_security_master(source)
    assert [r["series"] for r in rows] == ["EQ", "IL"]


def test_missing_series_is_restored_only_from_matching_registered_bytes(notice, tmp_path):
    path = tmp_path / "master.csv"
    path.write_text("SYMBOL,ISIN NUMBER,SERIES\nONE,OLDISIN,EQ\n")
    source = {"source_url": "https://www.nseindia.com/master.csv", "source_tier": "A1",
              "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "local_path": str(path)}
    row = {"symbol": "ONE", "isin": "OLDISIN", "series": None,
           "source_url": source["source_url"], "source_sha256": source["source_sha256"]}
    rows, audit = identity_transitions.apply_transition_boundaries([row], [notice, source])
    assert rows[0]["series"] == "EQ"
    assert rows[0]["valid_until"] == "2016-01-05"
    assert audit[0]["series_restored_from_source"] is True
    path.write_text("SYMBOL,ISIN NUMBER,SERIES\nONE,OLDISIN,IL\n")
    with pytest.raises(ValueError, match="transition_observation_source_hash"):
        identity_transitions.apply_transition_boundaries([row], [notice, source])


def test_collapsed_eq_il_observations_are_restored_separately(notice, tmp_path):
    path = tmp_path / "master.csv"
    path.write_text("SYMBOL,ISIN NUMBER,SERIES\nONE,OLDISIN,EQ\nONE,OLDISIN,IL\n")
    source = {"source_url": "https://www.nseindia.com/master.csv", "source_tier": "A1",
              "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "local_path": str(path)}
    row = {"symbol": "ONE", "isin": "OLDISIN", "series": None,
           "source_url": source["source_url"], "source_sha256": source["source_sha256"]}
    rows, _ = identity_transitions.apply_transition_boundaries([row], [notice, source])
    assert len(rows) == 2
    by_series = {r["series"]: r for r in rows}
    assert by_series["EQ"]["valid_until"] == "2016-01-05"
    assert by_series["IL"].get("valid_until") is None
    assert row["series"] is None
