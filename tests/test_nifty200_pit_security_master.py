from datetime import date
import io
import json
import zipfile

import pytest

from tools.nifty200_pit import harvest_security_master
from tools.nifty200_pit.harvest_security_master import _validate_csv
from tools.nifty200_pit.instrument_resolver import resolve_observation
from tools.nifty200_pit.models import Observation


def test_security_master_identity_is_period_valid(tmp_path):
    source = tmp_path / "EQUITY_L.csv"
    source.write_text(
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        "ABC,ABC Industries,EQ,01-Jan-2015,10,1,INE123,10\n",
        encoding="utf-8",
    )
    from tools.nifty200_pit.build_public_dataset import parse_security_master
    from tools.nifty200_pit.models import SourceRecord

    rows = parse_security_master(SourceRecord("https://example/EQUITY_L.csv", str(source), "hash", "2026-09-17T00:00:00+00:00"))
    assert rows[0]["instrument_id"] == "NSE-ISIN:INE123"
    assert rows[0]["valid_from"] == "2015-01-01"
    assert resolve_observation(Observation(symbol="ABC", effective_date=date(2015, 1, 2)), rows).confidence == "CERTIFIED"


def test_security_master_does_not_resolve_before_listing():
    result = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2014, 12, 31)),
        [{"instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC", "valid_from": "2015-01-01"}],
    )
    assert result.instrument_id is None
    assert result.confidence == "UNRESOLVED"


def test_security_master_resolves_unique_exact_company_name_in_period():
    result = resolve_observation(
        Observation(company_name="ABC Industries Ltd.", effective_date=date(2015, 1, 2)),
        [{"instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC",
          "company_name": "ABC Industries Ltd.", "valid_from": "2015-01-01"}],
    )
    assert result.instrument_id == "NSE-ISIN:INE123"
    assert result.confidence == "CERTIFIED"
    assert result.method == "EXACT_COMPANY_NAME_DATE"


def test_security_master_uses_latest_archived_snapshot_for_duplicate_symbol():
    result = resolve_observation(
        Observation(symbol="NESTLEIND", effective_date=date(2021, 1, 1)),
        [
            {"instrument_id": "NSE-ISIN:INE239A01016", "isin": "INE239A01016", "symbol": "NESTLEIND",
             "valid_from": "2010-01-08", "snapshot_date": "2017-07-04"},
            {"instrument_id": "NSE-ISIN:INE239A01024", "isin": "INE239A01024", "symbol": "NESTLEIND",
             "valid_from": "2023-08-01", "snapshot_date": None},
        ],
    )
    assert result.instrument_id == "NSE-ISIN:INE239A01016"
    assert result.method == "HISTORICAL_SYMBOL_DATE"


def test_current_listing_date_does_not_end_older_snapshot_before_snapshot_date():
    result = resolve_observation(
        Observation(symbol="BATAINDIA", effective_date=date(2012, 4, 27)),
        [
            {"instrument_id": "NSE-ISIN:INE176A01010", "symbol": "BATAINDIA", "valid_from": "2003-06-18",
             "valid_until": None, "snapshot_date": "2011-10-30"},
            {"instrument_id": "NSE-ISIN:INE176A01028", "symbol": "BATAINDIA", "valid_from": "2003-06-18",
             "valid_until": None, "snapshot_date": None},
        ],
    )
    assert result.instrument_id == "NSE-ISIN:INE176A01010"
    assert result.confidence == "CERTIFIED"


def test_security_master_deduplicates_same_instrument_across_snapshots():
    result = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2018, 1, 1)),
        [
            {"instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC", "valid_from": "2010-01-01",
             "snapshot_date": None},
            {"instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC", "valid_from": "2010-01-01",
             "snapshot_date": "2017-07-04"},
        ],
    )
    assert result.instrument_id == "NSE-ISIN:INE123"
    assert result.confidence == "CERTIFIED"


def test_security_master_resolves_dvr_company_label_to_dvr_security():
    result = resolve_observation(
        Observation(company_name="Tata Motors Ltd DVR", effective_date=date(2016, 4, 1)),
        [
            {"instrument_id": "NSE-ISIN:INE155A01022", "isin": "INE155A01022", "symbol": "TATAMOTORS",
             "company_name": "Tata Motors Limited", "valid_from": "1998-07-22"},
            {"instrument_id": "NSE-ISIN:IN9155A01020", "isin": "IN9155A01020", "symbol": "TATAMTRDVR",
             "company_name": "Tata Motors Limited", "valid_from": "2008-11-05"},
        ],
    )
    assert result.instrument_id == "NSE-ISIN:IN9155A01020"
    assert result.confidence == "CERTIFIED"


def test_security_master_normalizes_exchange_company_abbreviations():
    result = resolve_observation(
        Observation(company_name="Mangalore Refinery & Petrochemicals Ltd.", effective_date=date(2013, 4, 1)),
        [{"instrument_id": "NSE-ISIN:INE103A01014", "isin": "INE103A01014", "symbol": "MRPL",
          "company_name": "Mangalore Refinery and Petrochemicals Limited", "valid_from": "2000-01-01"}],
    )
    assert result.instrument_id == "NSE-ISIN:INE103A01014"
    assert result.confidence == "CERTIFIED"


def test_security_master_normalizes_ltd_spelling_for_exact_company_match():
    result = resolve_observation(
        Observation(symbol="AUROPHARM", company_name="Aurobindo Pharma Ltd.", effective_date=date(2023, 9, 29)),
        [{"instrument_id": "NSE-ISIN:INE406A01037", "isin": "INE406A01037", "symbol": "AUROPHARMA",
          "company_name": "Aurobindo Pharma Limited", "valid_from": "2000-07-19"}],
    )
    assert result.instrument_id == "NSE-ISIN:INE406A01037"
    assert result.method == "EXACT_COMPANY_NAME_DATE"


def test_harvester_stores_and_deduplicates_content_addressed_source(tmp_path, monkeypatch):
    payload = (
        b"SYMBOL,NAME OF COMPANY,DATE OF LISTING,ISIN NUMBER\n"
        b"ABC,ABC Industries,01-JAN-2015,INE123\n"
    )

    class Response:
        status = 200
        headers = {"Content-Type": "text/csv", "ETag": "etag-1"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(harvest_security_master, "urlopen", lambda *args, **kwargs: Response())
    first = harvest_security_master.harvest(tmp_path)
    second = harvest_security_master.harvest(tmp_path)
    catalogue_path = tmp_path / "data/raw/nifty200_pit_public_sources/source_catalogue.json"
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    assert first.source_sha256 == second.source_sha256
    assert len(catalogue) == 1
    assert (tmp_path / "data/raw/nifty200_pit_public_sources/raw" / first.source_sha256[:2] / f"{first.source_sha256}.csv").is_file()


def test_symbol_change_harvester_is_content_addressed(tmp_path, monkeypatch):
    payload = (
        b"Company Name,Previous Symbol,New Symbol,Date\n"
        b"Future Enterprises Limited,PANTALOONR,FRL,11-APR-2013\n"
    )

    class Response:
        status = 200
        headers = {"Content-Type": "text/csv", "ETag": "etag-symbol-1"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(harvest_security_master, "urlopen", lambda *args, **kwargs: Response())
    first = harvest_security_master.harvest_symbol_changes(tmp_path)
    second = harvest_security_master.harvest_symbol_changes(tmp_path)

    assert first.source_sha256 == second.source_sha256
    assert first.source_url.endswith("symbolchange.csv")


def test_historical_security_master_harvester_preserves_archive_provenance(tmp_path, monkeypatch):
    payload = (
        b"SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        b"ABC,ABC Industries,EQ,01-JAN-2010,10,1,INE123,10\n"
    )

    class Response:
        status = 200
        headers = {"Content-Type": "text/csv"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(harvest_security_master, "urlopen", lambda *args, **kwargs: Response())
    record = harvest_security_master.harvest_historical(tmp_path)

    assert record.source_tier == "A2"
    assert record.document_date == "2011-10-30"
    assert record.archive_url and "web.archive.org" in record.archive_url


def test_archived_security_master_row_keeps_historical_provenance(tmp_path):
    source = tmp_path / "EQUITY_L.csv"
    source.write_text(
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        "ABC,ABC Industries,EQ,01-Jan-2010,10,1,INE123,10\n",
        encoding="utf-8",
    )
    from tools.nifty200_pit.build_public_dataset import parse_security_master, HISTORICAL_SECURITY_MASTER_URL
    from tools.nifty200_pit.models import SourceRecord

    rows = parse_security_master(SourceRecord(
        HISTORICAL_SECURITY_MASTER_URL, str(source), "hash", "2026-09-17", source_tier="A2", document_date="2011-10-30",
    ))
    assert rows[0]["source_tier"] == "A2"
    assert rows[0]["instrument_id"] == "NSE-ISIN:INE123"
    assert rows[0]["snapshot_date"] == "2011-10-30"
    assert rows[0]["valid_from"] == "2010-01-01"
    assert rows[0]["valid_until"] is None


def test_symbol_change_alias_resolves_exact_multi_hop_chain():
    from tools.nifty200_pit.build_public_dataset import _identity_aliases

    master = [{
        "instrument_id": "NSE-ISIN:INE200",
        "isin": "INE200",
        "symbol": "GVT&D",
        "company_name": "GE Vernova T&D India Limited",
        "valid_from": "2008-06-30",
        "valid_until": None,
        "source_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
        "source_sha256": "master-hash",
        "source_tier": "A1",
    }]
    changes = [
        {"previous_symbol": "ALSTOMT&D", "new_symbol": "GET&D", "changed_on": date(2016, 9, 14),
         "source_url": "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
         "source_sha256": "changes-hash", "source_tier": "A1"},
        {"previous_symbol": "GET&D", "new_symbol": "GVT&D", "changed_on": date(2024, 11, 5),
         "source_url": "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
         "source_sha256": "changes-hash", "source_tier": "A1"},
    ]

    aliases = _identity_aliases([{"symbol": "ALSTOMT&D", "snapshot_date": "2015-05-29"}], master, changes)
    assert sum(row["alias_symbol"] == "ALSTOMT&D" for row in aliases) == 1
    alias = next(row for row in aliases if row["alias_symbol"] == "ALSTOMT&D")
    assert alias["instrument_id"] == "NSE-ISIN:INE200"
    assert alias["confidence"] == "CERTIFIED"
    assert alias["valid_until"] == "2016-09-14"


def test_symbol_change_alias_ignores_duplicate_snapshot_rows_for_same_target():
    from tools.nifty200_pit.build_public_dataset import _identity_aliases

    master = [
        {"instrument_id": "NSE-ISIN:INE200", "isin": "INE200", "symbol": "FEL",
         "company_name": "Future Enterprises Limited", "valid_from": "2008-06-30",
         "valid_until": None, "source_url": "current", "source_sha256": "a", "source_tier": "A1"},
        {"instrument_id": "NSE-ISIN:INE200", "isin": "INE200", "symbol": "FEL",
         "company_name": "Future Enterprises Limited", "valid_from": "2008-06-30",
         "valid_until": None, "snapshot_date": "2017-07-04", "source_url": "archive",
         "source_sha256": "b", "source_tier": "A2"},
    ]
    changes = [{"previous_symbol": "FRL", "new_symbol": "FEL", "changed_on": date(2016, 5, 13),
                "source_url": "changes", "source_sha256": "c", "source_tier": "A1"}]

    aliases = _identity_aliases([], master, changes)
    alias = next(row for row in aliases if row["alias_symbol"] == "FRL")
    assert alias["instrument_id"] == "NSE-ISIN:INE200"
    assert alias["confidence"] == "CERTIFIED"


def test_workbook_observation_is_retained_but_not_reconciled_when_release_confirms_it():
    from dataclasses import replace
    from tools.nifty200_pit.build_public_dataset import _suppress_redundant_workbook_observations

    workbook = Observation(
        company_name="Gruh Finance Ltd.", effective_date=date(2015, 3, 27), action="ADD",
        source_tier="A1", extraction_method="OFFICIAL_XLS",
    )
    release = Observation(
        instrument_id="NSE-ISIN:INE781B01015", symbol="GRUH", company_name="Gruh Finance Ltd.*",
        announcement_date=date(2015, 2, 20), effective_date=date(2015, 3, 27), action="ADD",
        source_tier="A1", extraction_method="PDF_TEXT", confidence="CERTIFIED", review_status="ACCEPTED",
    )

    assert _suppress_redundant_workbook_observations([workbook, release]) == [release]
    unresolved = replace(release, review_status="UNRESOLVED")
    assert _suppress_redundant_workbook_observations([workbook, unresolved]) == [workbook, unresolved]
    superseded = replace(release, review_status="SUPERSEDED")
    assert _suppress_redundant_workbook_observations([workbook, superseded]) == [workbook, superseded]


@pytest.mark.parametrize("payload", [b"<html>Access Denied</html>", b"SYMBOL,WRONG\nABC,x\n"])
def test_security_master_rejects_non_evidence(payload):
    with pytest.raises(ValueError):
        _validate_csv(payload)


def _bhavcopy_payload(timestamp="01-APR-2016"):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("cm01APR2016bhav.csv", (
            "SYMBOL,SERIES,TIMESTAMP,ISIN\n"
            f"NBCC,EQ,{timestamp},INE095N01015\n"
            f"NBCC,ND,{timestamp},INE095N07012\n"
            f"INVALID,EQ,{timestamp},UNKNOWN\n"
        ))
    return payload.getvalue()


def test_bhavcopy_identity_is_exact_day_evidence_not_membership(tmp_path):
    from tools.nifty200_pit.build_public_dataset import parse_bhavcopy_identities
    from tools.nifty200_pit.models import SourceRecord

    path = tmp_path / "bhav.zip"
    path.write_bytes(_bhavcopy_payload())
    source = SourceRecord("https://archives.nseindia.com/bhav.zip", str(path), "hash", "now",
                          document_date="2016-04-01", source_tier="A1")
    rows = parse_bhavcopy_identities(source)
    assert len(rows) == 1
    assert rows[0]["identity_event_type"] == "DATED_BHAVCOPY_IDENTITY"
    assert "action" not in rows[0]
    assert rows[0]["series"] == "EQ"
    for day in (date(2016, 3, 31), date(2016, 4, 2)):
        assert resolve_observation(Observation(symbol="NBCC", effective_date=day), rows).instrument_id is None
    resolved = resolve_observation(Observation(symbol="NBCC", effective_date=date(2016, 4, 1)), rows)
    assert resolved.isin == "INE095N01015"


def test_bhavcopy_identity_filter_retains_only_requested_date_symbols(tmp_path):
    import zipfile
    from tools.nifty200_pit.build_public_dataset import parse_bhavcopy_identities
    from tools.nifty200_pit.models import SourceRecord

    archive = tmp_path / "cm01JAN2020bhav.csv.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("cm01JAN2020bhav.csv", "SYMBOL,SERIES,TIMESTAMP,ISIN\nKEEP,EQ,01-Jan-2020,INE123456789\nDROP,EQ,01-Jan-2020,INE987654321\n")
    rows = parse_bhavcopy_identities(SourceRecord(
        "https://example.test/bhav.zip", str(archive), "hash", "now",
        document_date="2020-01-01",
    ), identity_keys={("2020-01-01", "KEEP")})
    assert [row["symbol"] for row in rows] == ["KEEP"]


def test_bhavcopy_parser_rejects_wrong_catalogue_date(tmp_path):
    from tools.nifty200_pit.build_public_dataset import parse_bhavcopy_identities
    from tools.nifty200_pit.models import SourceRecord

    path = tmp_path / "bhav.zip"
    path.write_bytes(_bhavcopy_payload())
    source = SourceRecord("official", str(path), "hash", "now", document_date="2016-04-02")
    with pytest.raises(ValueError, match="timestamp disagrees"):
        parse_bhavcopy_identities(source)


@pytest.mark.parametrize("wrong_date", [False, True])
def test_bhavcopy_harvester_validates_session_before_cataloguing(tmp_path, monkeypatch, wrong_date):
    class Response:
        status = 200
        headers = {"Content-Type": "application/zip"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return _bhavcopy_payload("04-APR-2016" if wrong_date else "01-APR-2016")

    monkeypatch.setattr(harvest_security_master, "urlopen", lambda *args, **kwargs: Response())
    if wrong_date:
        with pytest.raises(ValueError, match="timestamp disagrees"):
            harvest_security_master.harvest_bhavcopy_identity(tmp_path, session_date=date(2016, 4, 1))
        assert not (tmp_path / "data/raw/nifty200_pit_public_sources/source_catalogue.json").exists()
    else:
        first = harvest_security_master.harvest_bhavcopy_identity(tmp_path, session_date=date(2016, 4, 1))
        second = harvest_security_master.harvest_bhavcopy_identity(tmp_path, session_date=date(2016, 4, 1))
        assert first.source_sha256 == second.source_sha256
        assert first.source_url.endswith("/2016/APR/cm01APR2016bhav.csv.zip")
        assert first.document_date == "2016-04-01"
        assert first.source_tier == "A1"
