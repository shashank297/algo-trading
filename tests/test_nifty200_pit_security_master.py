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



def test_current_security_master_does_not_backdate_from_listing_date():
    result = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2026, 3, 30)),
        [{
            "instrument_id": "NSE-ISIN:INE123",
            "isin": "INE123",
            "symbol": "ABC",
            "valid_from": "2024-01-01",
            "snapshot_date": "2026-09-09",
            "observed_snapshot_date": "2026-09-09",
            "validity_basis": "CURRENT_SNAPSHOT_ONLY",
            "has_explicit_historical_interval": False,
        }],
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_current_security_master_certifies_at_snapshot_date_and_after():
    row = {
        "instrument_id": "NSE-ISIN:INE123",
        "isin": "INE123",
        "symbol": "ABC",
        "valid_from": "2024-01-01",
        "snapshot_date": "2026-09-09",
        "observed_snapshot_date": "2026-09-09",
        "validity_basis": "CURRENT_SNAPSHOT_ONLY",
        "has_explicit_historical_interval": False,
    }

    at_snapshot = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2026, 9, 9)), [row]
    )
    after_snapshot = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2026, 9, 10)), [row]
    )

    assert at_snapshot.instrument_id == "NSE-ISIN:INE123"
    assert at_snapshot.confidence == "CERTIFIED"
    assert after_snapshot.instrument_id == "NSE-ISIN:INE123"
    assert after_snapshot.confidence == "CERTIFIED"


def test_explicit_historical_interval_certifies_pre_snapshot_observation():
    result = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2026, 3, 30)),
        [{
            "instrument_id": "NSE-ISIN:INE123",
            "isin": "INE123",
            "symbol": "ABC",
            "valid_from": "2024-01-01",
            "valid_until": "2026-09-09",
            "snapshot_date": "2026-09-09",
            "validity_basis": "CURRENT_SNAPSHOT_ONLY",
            "has_explicit_historical_interval": True,
        }],
    )

    assert result.instrument_id == "NSE-ISIN:INE123"
    assert result.confidence == "CERTIFIED"


def test_archived_snapshot_obeys_its_observation_date():
    row = {
        "instrument_id": "NSE-ISIN:INE123",
        "isin": "INE123",
        "symbol": "ABC",
        "valid_from": "2015-01-02",
        "snapshot_date": "2015-01-02",
        "observed_snapshot_date": "2015-01-02",
        "validity_basis": "ARCHIVED_INDEX_SNAPSHOT_DATE_ONLY",
        "has_explicit_historical_interval": False,
    }

    before = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2015, 1, 1)), [row]
    )
    on_snapshot = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2015, 1, 2)), [row]
    )

    assert before.instrument_id is None
    assert on_snapshot.instrument_id == "NSE-ISIN:INE123"
    assert on_snapshot.confidence == "CERTIFIED"


def test_manual_review_master_row_cannot_certify():
    result = resolve_observation(
        Observation(symbol="ABC", effective_date=date(2026, 9, 9)),
        [{
            "instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC",
            "snapshot_date": "2026-09-09", "valid_from": "2026-09-09",
            "source_tier": "B1", "confidence": "MANUAL_REVIEW", "review_status": "MANUAL_REVIEW",
        }],
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_contradictory_explicit_isin_fails_closed():
    result = resolve_observation(
        Observation(symbol="ABC", isin="INE999", effective_date=date(2026, 9, 9)),
        [{
            "instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC",
            "snapshot_date": "2026-09-09", "valid_from": "2026-09-09",
        }],
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_missing_effective_date_cannot_period_certify():
    result = resolve_observation(
        Observation(symbol="ABC"),
        [{
            "instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC",
            "snapshot_date": "2026-09-09", "valid_from": "2026-09-09",
        }],
    )
    assert result.instrument_id is None
    assert result.confidence == "MANUAL_REVIEW"


def test_duplicate_same_instrument_isin_evidence_is_deduplicated():
    row = {
        "instrument_id": "NSE-ISIN:INE123", "isin": "INE123", "symbol": "ABC",
        "snapshot_date": "2026-09-09", "valid_from": "2026-09-09",
    }
    result = resolve_observation(
        Observation(isin="INE123", effective_date=date(2026, 9, 9)), [row, dict(row)]
    )
    assert result.instrument_id == "NSE-ISIN:INE123"
    assert result.confidence == "CERTIFIED"


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


# ---------------------------------------------------------------------------
# Forward-validity regression tests (FIND-01 MISSING_DURABLE_IDENTITY fix)
# ---------------------------------------------------------------------------

_FORWARD_MASTER_ROW = {
    "instrument_id": "NSE-ISIN:INE1",
    "isin": "INE1",
    "symbol": "NEW",
    "company_name": "New Co Ltd",
    "valid_from": "2019-10-30",
    "valid_until": None,
    "has_explicit_historical_interval": True,
    "snapshot_date": "2026-09-19",
    "confidence": "CERTIFIED",
    "review_status": "ACCEPTED",
}


def test_official_symbol_change_establishes_forward_validity():
    """A certified forward-validity row allows the resolver to certify the
    new symbol for dates on or after the official change date."""
    result = resolve_observation(
        Observation(symbol="NEW", effective_date=date(2019, 10, 30)),
        [_FORWARD_MASTER_ROW],
    )
    assert result.instrument_id == "NSE-ISIN:INE1"
    assert result.confidence == "CERTIFIED"


def test_resolver_accepts_new_symbol_on_and_after_change_date():
    """Post-change symbol resolves to CERTIFIED on and after the effective date."""
    on_date = resolve_observation(
        Observation(symbol="NEW", effective_date=date(2019, 10, 30)),
        [_FORWARD_MASTER_ROW],
    )
    after_date = resolve_observation(
        Observation(symbol="NEW", effective_date=date(2025, 3, 28)),
        [_FORWARD_MASTER_ROW],
    )
    assert on_date.instrument_id == "NSE-ISIN:INE1"
    assert on_date.confidence == "CERTIFIED"
    assert after_date.instrument_id == "NSE-ISIN:INE1"
    assert after_date.confidence == "CERTIFIED"


def test_resolver_rejects_new_symbol_before_change_date():
    """Post-change symbol must NOT resolve before the official change date."""
    result = resolve_observation(
        Observation(symbol="NEW", effective_date=date(2019, 10, 29)),
        [_FORWARD_MASTER_ROW],
    )
    assert result.instrument_id is None


def test_poonawalla_resolves_after_symbol_change():
    """POONAWALLA (ex-MAGMA) resolves to INE511C01022 from 2021-08-05 onward."""
    poonawalla_row = {
        "instrument_id": "NSE-ISIN:INE511C01022",
        "isin": "INE511C01022",
        "symbol": "POONAWALLA",
        "company_name": "Poonawalla Fincorp Ltd.",
        "valid_from": "2021-08-05",
        "valid_until": None,
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
        "identity_event_type": "OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD",
    }
    # Post-change observation certifies
    after = resolve_observation(
        Observation(symbol="POONAWALLA", effective_date=date(2025, 3, 28)),
        [poonawalla_row],
    )
    assert after.instrument_id == "NSE-ISIN:INE511C01022"
    assert after.confidence == "CERTIFIED"

    # Pre-change observation does NOT certify under POONAWALLA
    before = resolve_observation(
        Observation(symbol="POONAWALLA", effective_date=date(2021, 8, 4)),
        [poonawalla_row],
    )
    assert before.instrument_id is None


def test_360one_resolves_after_symbol_change():
    """360ONE (ex-IIFLWAM) resolves to INE466L01038 from 2023-01-23 onward."""
    threesixty_row = {
        "instrument_id": "NSE-ISIN:INE466L01038",
        "isin": "INE466L01038",
        "symbol": "360ONE",
        "company_name": "360 ONE WAM Ltd.",
        "valid_from": "2023-01-23",
        "valid_until": None,
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
        "identity_event_type": "OFFICIAL_SYMBOL_CHANGE_CERTIFIED_FORWARD",
    }
    after = resolve_observation(
        Observation(symbol="360ONE", effective_date=date(2025, 9, 30)),
        [threesixty_row],
    )
    assert after.instrument_id == "NSE-ISIN:INE466L01038"
    assert after.confidence == "CERTIFIED"

    before = resolve_observation(
        Observation(symbol="360ONE", effective_date=date(2023, 1, 20)),
        [threesixty_row],
    )
    assert before.instrument_id is None


def test_patanjali_resolves_after_name_change():
    """PATANJALI (ex-RUCHISOYA) resolves to INE619A01035 from 2022-07-13 onward."""
    patanjali_row = {
        "instrument_id": "NSE-ISIN:INE619A01035",
        "isin": "INE619A01035",
        "symbol": "PATANJALI",
        "company_name": "Patanjali Foods Ltd.",
        "valid_from": "2022-07-13",
        "valid_until": None,
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
        "identity_event_type": "OFFICIAL_NAME_CHANGE_CERTIFIED_FORWARD",
    }
    after = resolve_observation(
        Observation(symbol="PATANJALI", effective_date=date(2022, 9, 30)),
        [patanjali_row],
    )
    assert after.instrument_id == "NSE-ISIN:INE619A01035"
    assert after.confidence == "CERTIFIED"

    before = resolve_observation(
        Observation(symbol="PATANJALI", effective_date=date(2022, 7, 12)),
        [patanjali_row],
    )
    assert before.instrument_id is None


def test_no_isin_cross_contamination_ruchisoya_patanjali():
    """Pre-CIRP RUCHISOYA (INE619A01027) and post-rename PATANJALI (INE619A01035)
    must remain completely distinct and never cross-resolve.
    """
    ruchisoya_row = {
        "instrument_id": "NSE-ISIN:INE619A01027",
        "isin": "INE619A01027",
        "symbol": "RUCHISOYA",
        "company_name": "Ruchi Soya Industries Ltd.",
        "valid_from": "2002-01-01",
        "valid_until": "2019-11-20",
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
    }
    patanjali_row = {
        "instrument_id": "NSE-ISIN:INE619A01035",
        "isin": "INE619A01035",
        "symbol": "PATANJALI",
        "company_name": "Patanjali Foods Ltd.",
        "valid_from": "2022-07-13",
        "valid_until": None,
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
    }
    master = [ruchisoya_row, patanjali_row]

    ruchi_result = resolve_observation(
        Observation(symbol="RUCHISOYA", effective_date=date(2013, 4, 1)), master
    )
    assert ruchi_result.instrument_id == "NSE-ISIN:INE619A01027"
    assert ruchi_result.isin == "INE619A01027"

    patanjali_result = resolve_observation(
        Observation(symbol="PATANJALI", effective_date=date(2022, 9, 30)), master
    )
    assert patanjali_result.instrument_id == "NSE-ISIN:INE619A01035"
    assert patanjali_result.isin == "INE619A01035"

    # Cross-resolution must fail
    ruchi_as_patanjali = resolve_observation(
        Observation(symbol="RUCHISOYA", isin="INE619A01035", effective_date=date(2013, 4, 1)), master
    )
    assert ruchi_as_patanjali.instrument_id is None


def test_no_isin_cross_contamination_iiflwam_360one():
    """Pre-split IIFLWAM (INE466L01020) and post-rename 360ONE (INE466L01038)
    must remain completely distinct and never cross-resolve.
    """
    iiflwam_row = {
        "instrument_id": "NSE-ISIN:INE466L01020",
        "isin": "INE466L01020",
        "symbol": "IIFLWAM",
        "company_name": "IIFL Wealth Management Ltd.",
        "valid_from": "2019-09-19",
        "valid_until": "2023-01-23",
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
    }
    threesixty_row = {
        "instrument_id": "NSE-ISIN:INE466L01038",
        "isin": "INE466L01038",
        "symbol": "360ONE",
        "company_name": "360 ONE WAM Ltd.",
        "valid_from": "2023-01-23",
        "valid_until": None,
        "has_explicit_historical_interval": True,
        "confidence": "CERTIFIED",
        "review_status": "ACCEPTED",
    }
    master = [iiflwam_row, threesixty_row]

    iifl_result = resolve_observation(
        Observation(symbol="IIFLWAM", effective_date=date(2022, 1, 1)), master
    )
    assert iifl_result.instrument_id == "NSE-ISIN:INE466L01020"

    threesixty_result = resolve_observation(
        Observation(symbol="360ONE", effective_date=date(2025, 9, 30)), master
    )
    assert threesixty_result.instrument_id == "NSE-ISIN:INE466L01038"

    # Must not cross-contaminate
    cross = resolve_observation(
        Observation(symbol="IIFLWAM", isin="INE466L01038", effective_date=date(2022, 1, 1)), master
    )
    assert cross.instrument_id is None
