from datetime import date

from liquid_universe_spec import END, START, fail_closed_reasons, validate_rows


def base_row():
    return {
        "symbol": "ABC",
        "as_of": START,
        "effective_from": START,
        "isin": "INE123456789",
        "security_type": "EQUITY",
        "nse_listed": True,
        "isin_verified": True,
        "suspended_or_delisted": False,
        "median_daily_turnover": 10_000_000.0,
        "trading_days": 200,
        "turnover_window_end": date(2011, 12, 31),
        "observation_complete": True,
        "source_url": "https://www.nseindia.com/example.csv",
        "source_sha256": "a" * 64,
    }


def test_complete_row_is_accepted_deterministically():
    row = base_row()
    assert fail_closed_reasons(row, min_turnover=1_000_000, min_trading_days=150) == []
    assert validate_rows([row], min_turnover=1_000_000, min_trading_days=150)["accepted_rows"] == 1


def test_missing_pit_evidence_is_rejected():
    row = base_row()
    row["observation_complete"] = False
    row["source_sha256"] = ""
    reasons = fail_closed_reasons(row, min_turnover=1_000_000, min_trading_days=150)
    assert "liquidity_or_observation_incomplete" in reasons
    assert "missing_source_hash" in reasons


def test_current_only_constituent_cannot_pass():
    row = base_row()
    row["effective_from"] = None
    row["as_of"] = END
    assert "missing_effective_date" in fail_closed_reasons(row, min_turnover=1_000_000, min_trading_days=150)


def test_missing_as_of_is_an_explicit_fail_closed_rejection():
    row = base_row()
    del row["as_of"]

    reasons = fail_closed_reasons(row, min_turnover=1_000_000, min_trading_days=150)

    assert "missing_as_of" in reasons


def test_non_numeric_turnover_is_an_explicit_fail_closed_rejection():
    row = base_row()
    row["median_daily_turnover"] = "not-a-number"

    reasons = fail_closed_reasons(row, min_turnover=1_000_000, min_trading_days=150)

    assert "invalid_median_daily_turnover" in reasons


def test_malformed_source_metadata_is_rejected():
    row = base_row()
    row["source_url"] = "not a url"
    row["source_sha256"] = "not-a-sha"

    reasons = fail_closed_reasons(row, min_turnover=1_000_000, min_trading_days=150)

    assert "invalid_source_url" in reasons
    assert "invalid_source_hash" in reasons


def test_validate_rows_returns_rejections_for_malformed_rows_without_raising():
    row = base_row()
    del row["as_of"]
    row["median_daily_turnover"] = "not-a-number"
    row["source_url"] = "not a url"
    row["source_sha256"] = "not-a-sha"

    result = validate_rows([row], min_turnover=1_000_000, min_trading_days=150)

    assert result["accepted_rows"] == 0
    assert result["rejected_rows"] == 1
    assert {
        "missing_as_of",
        "invalid_median_daily_turnover",
        "invalid_source_url",
        "invalid_source_hash",
    }.issubset(result["rejections"][0]["reasons"])
