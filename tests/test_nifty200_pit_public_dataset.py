from datetime import date

from tools.nifty200_pit.build_public_dataset import (
    _annual_coverage,
    _coverage,
    _csv_snapshot_rows,
    _snapshot_date,
)
from tools.nifty200_pit.models import SourceRecord


def _source() -> SourceRecord:
    return SourceRecord(
        source_url="https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataApr2013.zip",
        local_path="unused", source_sha256="a" * 64, retrieved_at="2026-09-06T00:00:00+00:00",
    )


def test_snapshot_date_uses_explicit_report_date_before_fallback():
    assert _snapshot_date("Constituents of CNX 200\nApril 30, 2014", date(2014, 4, 1)) == date(2014, 4, 30)


def test_csv_snapshot_parser_retains_source_member_and_company_name():
    rows = _csv_snapshot_rows(
        b"18-04-2013,CNX 200,MCDOWELL-N,United Spirits Ltd.,BREW/DISTILLERIES,2095.75\n",
        _source(), "indices_dataApr2013/cnx200_Apr2013.csv", date(2013, 4, 1),
    )
    assert rows[0]["snapshot_date"] == "2013-04-18"
    assert rows[0]["symbol"] == "MCDOWELL-N"
    assert rows[0]["company_name"] == "United Spirits Ltd."
    assert rows[0]["source_member"].endswith("cnx200_Apr2013.csv")


def test_coverage_is_blocked_for_missing_or_non_200_months():
    rows = _coverage([
        {"snapshot_date": "2013-04-18", "symbol": f"S{i}"} for i in range(200)
    ])
    april = next(row for row in rows if row["period"] == "2013-04")
    may = next(row for row in rows if row["period"] == "2013-05")
    assert april["status"] == "PASS"
    assert may["status"] == "BLOCKED"


def test_annual_coverage_aggregates_monthly_status_without_certifying_gaps():
    rows = _annual_coverage([
        {"period": "2012-01", "status": "BLOCKED"},
        {"period": "2012-02", "status": "PASS"},
    ])
    assert rows == [{
        "year": "2012", "months_expected": "2", "months_with_200_members": "1",
        "status": "BLOCKED", "qa_note": "year contains missing or non-200 checkpoints",
    }]
