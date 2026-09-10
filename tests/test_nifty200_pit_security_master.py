from datetime import date
import json

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

    rows = parse_security_master(SourceRecord("https://example/EQUITY_L.csv", str(source), "hash", "now"))
    assert rows[0]["instrument_id"] == "NSE-ISIN:INE123"
    assert resolve_observation(Observation(symbol="ABC", effective_date=date(2015, 1, 2)), rows).confidence == "CERTIFIED"


def test_security_master_does_not_resolve_before_listing():
    result = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2014, 12, 31)),
        [{"instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC", "valid_from": "2015-01-01"}],
    )
    assert result.instrument_id is None
    assert result.confidence == "UNRESOLVED"


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


@pytest.mark.parametrize("payload", [b"<html>Access Denied</html>", b"SYMBOL,WRONG\nABC,x\n"])
def test_security_master_rejects_non_evidence(payload):
    with pytest.raises(ValueError):
        _validate_csv(payload)
