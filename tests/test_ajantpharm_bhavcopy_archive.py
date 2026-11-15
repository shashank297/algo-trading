from zipfile import ZipFile

import pytest

from tools.nifty200_pit.build_public_dataset import parse_bhavcopy_identities
from tools.nifty200_pit.models import SourceRecord
from tools.nifty200_pit.source_catalogue import sha256_file


@pytest.mark.parametrize("stamp", ["13-JUL-2020", "13-Jul-20"])
def test_nested_ajantpharm_bhavcopy_preserves_exact_daily_identity(tmp_path, stamp):
    member = "cm13JUL2020bhav.csv/cm13JUL2020bhav.csv"
    path = tmp_path / "cm13JUL2020bhav.csv.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(member, "SYMBOL,SERIES,ISIN,TIMESTAMP\n" f"AJANTPHARM,EQ,INE031B01049,{stamp}\n")
    source = SourceRecord(
        source_url="https://nsearchives.nseindia.com/content/historical/EQUITIES/2020/JUL/cm13JUL2020bhav.csv.zip",
        local_path=str(path),
        source_sha256=sha256_file(path),
        retrieved_at="2026-11-14T18:59:18.735034+00:00",
        document_date="2020-07-13",
    )
    row, = parse_bhavcopy_identities(source, identity_keys={("2020-07-13", "AJANTPHARM")})
    assert row["instrument_id"] == "NSE-ISIN:INE031B01049"
    assert row["valid_from"] == "2020-07-13"
    assert row["valid_until"] == "2020-07-14"
    assert row["source_member"] == member
    assert row["source_sha256"] == source.source_sha256
    assert row["has_explicit_historical_interval"] is True


def test_short_bhavcopy_date_cannot_override_registered_session(tmp_path):
    path = tmp_path / "cm13JUL2020bhav.csv.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("cm13JUL2020bhav.csv", "SYMBOL,SERIES,ISIN,TIMESTAMP\nAJANTPHARM,EQ,INE031B01049,14-Jul-20\n")
    source = SourceRecord(
        source_url="https://nsearchives.nseindia.com/content/historical/EQUITIES/2020/JUL/cm13JUL2020bhav.csv.zip",
        local_path=str(path),
        source_sha256=sha256_file(path),
        retrieved_at="2026-11-14T18:59:18.735034+00:00",
        document_date="2020-07-13",
    )
    with pytest.raises(ValueError, match="Bhavcopy timestamp disagrees with catalogue"):
        parse_bhavcopy_identities(source)
