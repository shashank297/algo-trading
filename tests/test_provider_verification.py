"""Tests for Phase 2.2 — CrossProviderVerifier and no-blending invariant.

These tests are fully deterministic and require no network access or real credentials.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import warnings
import pandas as pd
import pytest

from data_platform.provider_verification import (
    CrossProviderVerifier,
    ProviderDataVerificationError,
    ProviderDataVerificationWarning,
    ProviderReconciliationResult,
    VerificationSeverity,
)
from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner


UTC = timezone.utc


def _make_bar_df(
    prices: list[tuple[float, float, float, float, float]],
    start_iso: str = "2024-01-02T03:45:00Z",
    freq_min: int = 5,
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
) -> pd.DataFrame:
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    rows = []
    for i, (open_p, high_p, low_p, close_p, vol) in enumerate(prices):
        ts = start + pd.Timedelta(minutes=i * freq_min)
        rows.append(
            {
                "timestamp": ts,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": vol,
                "symbol": symbol,
                "exchange": exchange,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture()
def db(tmp_path: Path) -> Any:
    db_path = str(tmp_path / "test_provider.duckdb")
    runner = MigrationRunner(db_path)
    runner.run_migrations()
    db_mgr = DuckDBManager(db_path)
    yield db_mgr
    db_mgr.close()


@pytest.fixture()
def verifier() -> CrossProviderVerifier:
    return CrossProviderVerifier()


class TestCrossProviderVerifier:
    def test_provider_exact_match(self, verifier, db):
        """T030: Identical primary and secondary bars produce all MATCH and overall MATCH."""
        bars_primary = _make_bar_df(
            [
                (100.0, 105.0, 99.0, 102.0, 5000.0),
                (102.0, 107.0, 101.0, 106.0, 6000.0),
            ]
        )
        bars_secondary = bars_primary.copy(deep=True)

        report = verifier.verify(
            primary_bars=bars_primary,
            secondary_bars=bars_secondary,
            symbol="RELIANCE",
            exchange="NSE",
            timeframe="5m",
            primary_provider="angel_one",
            secondary_provider="nse_feed",
            severity=VerificationSeverity.WARNING,
            db=db,
            primary_dataset_id="ds_primary_1",
            secondary_dataset_id="ds_sec_1",
        )

        assert report.bars_match == 2
        assert report.bars_tolerance_match == 0
        assert report.bars_disagreement == 0
        assert report.bars_unavailable == 0
        assert report.overall_status == "MATCH"
        for outcome in report.bar_outcomes:
            assert outcome.result == ProviderReconciliationResult.MATCH

        # Check DB persistence
        records = db.get_reconciliations(symbol="RELIANCE", exchange="NSE", timeframe="5m")
        assert len(records) == 1
        assert records[0]["overall_status"] == "MATCH"
        assert records[0]["bars_match"] == 2

    def test_provider_tolerance_match(self, verifier, db):
        """T031: Secondary bars with tiny relative difference (within tolerance) produce TOLERANCE_MATCH."""
        bars_primary = _make_bar_df(
            [
                (1000.0, 1050.0, 990.0, 1020.0, 5000.0),
            ]
        )
        # 1000.0 vs 1000.05 is 0.00005 (0.005%) which is <= 0.0001 (0.01%)
        bars_secondary = _make_bar_df(
            [
                (1000.05, 1050.0, 990.0, 1020.0, 5000.0),
            ]
        )

        report = verifier.verify(
            primary_bars=bars_primary,
            secondary_bars=bars_secondary,
            symbol="RELIANCE",
            exchange="NSE",
            timeframe="5m",
            primary_provider="angel_one",
            secondary_provider="nse_feed",
            severity=VerificationSeverity.WARNING,
            db=db,
            primary_dataset_id="ds_primary_tol",
            secondary_dataset_id="ds_secondary_tol",
        )

        assert report.bars_match == 0
        assert report.bars_tolerance_match == 1
        assert report.bars_disagreement == 0
        assert report.bars_unavailable == 0
        assert report.overall_status == "PARTIAL_MATCH"
        assert report.bar_outcomes[0].result == ProviderReconciliationResult.TOLERANCE_MATCH

    def test_provider_disagreement_warning_mode(self, verifier, db):
        """T032: Disagreement beyond tolerance emits DATA_VERIFICATION_WARNING when severity=WARNING."""
        bars_primary = _make_bar_df(
            [
                (100.0, 105.0, 99.0, 102.0, 5000.0),
            ]
        )
        # 100.0 vs 110.0 is 10% diff, far above tolerance
        bars_secondary = _make_bar_df(
            [
                (110.0, 105.0, 99.0, 102.0, 5000.0),
            ]
        )

        with pytest.warns(ProviderDataVerificationWarning, match="DATA_VERIFICATION_WARNING"):
            report = verifier.verify(
                primary_bars=bars_primary,
                secondary_bars=bars_secondary,
                symbol="RELIANCE",
                exchange="NSE",
                timeframe="5m",
                primary_provider="angel_one",
                secondary_provider="nse_feed",
                severity=VerificationSeverity.WARNING,
                db=db,
                primary_dataset_id="ds_primary_warn",
                secondary_dataset_id="ds_secondary_warn",
            )

        assert report.bars_disagreement == 1
        assert report.overall_status == "DISAGREEMENT"
        assert report.bar_outcomes[0].result == ProviderReconciliationResult.DISAGREEMENT

    def test_provider_disagreement_blocking_mode(self, verifier, db):
        """T032: Disagreement beyond tolerance raises ProviderDataVerificationError when severity=BLOCKING."""
        bars_primary = _make_bar_df(
            [
                (100.0, 105.0, 99.0, 102.0, 5000.0),
            ]
        )
        bars_secondary = _make_bar_df(
            [
                (110.0, 105.0, 99.0, 102.0, 5000.0),
            ]
        )

        with pytest.raises(ProviderDataVerificationError, match="provider disagreement"):
            verifier.verify(
                primary_bars=bars_primary,
                secondary_bars=bars_secondary,
                symbol="RELIANCE",
                exchange="NSE",
                timeframe="5m",
                primary_provider="angel_one",
                secondary_provider="nse_feed",
                severity=VerificationSeverity.BLOCKING,
                db=db,
                primary_dataset_id="ds_primary_block",
                secondary_dataset_id="ds_secondary_block",
            )
        persisted = db.get_reconciliations(symbol="RELIANCE", timeframe="5m")
        assert len(persisted) == 1
        assert persisted[0]["overall_status"] == "DISAGREEMENT"
        assert persisted[0]["bars_disagreement"] == 1

    def test_unavailable_secondary_provider(self, verifier, db):
        """T033: If secondary bars are None, all bars are marked UNAVAILABLE and overall is UNAVAILABLE."""
        bars_primary = _make_bar_df(
            [
                (100.0, 105.0, 99.0, 102.0, 5000.0),
                (102.0, 107.0, 101.0, 106.0, 6000.0),
            ]
        )

        report = verifier.verify(
            primary_bars=bars_primary,
            secondary_bars=None,
            symbol="RELIANCE",
            exchange="NSE",
            timeframe="5m",
            primary_provider="angel_one",
            secondary_provider="nse_feed",
            severity=VerificationSeverity.WARNING,
            db=db,
            primary_dataset_id="ds_primary_unavail",
            secondary_dataset_id=None,
        )

        assert report.bars_match == 0
        assert report.bars_tolerance_match == 0
        assert report.bars_disagreement == 0
        assert report.bars_unavailable == 2
        assert report.overall_status == "UNAVAILABLE"
        for outcome in report.bar_outcomes:
            assert outcome.result == ProviderReconciliationResult.UNAVAILABLE
            assert outcome.secondary_ohlcv is None
        persisted = db.get_reconciliations(symbol="RELIANCE", timeframe="5m")
        assert persisted[0]["secondary_dataset_id"] is None

    @pytest.mark.parametrize("column,value", [("open", float("nan")), ("close", float("inf")), ("volume", float("nan"))])
    def test_non_finite_secondary_is_disagreement(self, verifier, db, column, value):
        primary = _make_bar_df([(100.0, 105.0, 99.0, 102.0, 5000.0)])
        secondary = primary.copy()
        secondary.loc[0, column] = value
        with pytest.warns(ProviderDataVerificationWarning):
            report = verifier.verify(
                primary_bars=primary, secondary_bars=secondary, symbol="RELIANCE", exchange="NSE", timeframe="5m",
                primary_provider="angel_one", secondary_provider="nse_feed", db=db,
                primary_dataset_id="primary-finite", secondary_dataset_id="secondary-invalid",
            )
        assert report.bar_outcomes[0].result == ProviderReconciliationResult.DISAGREEMENT
        assert report.bar_outcomes[0].field_deltas[column] is None

    @pytest.mark.parametrize("column,value", [("open", float("nan")), ("close", float("inf")), ("volume", -1.0)])
    def test_invalid_primary_fails_before_reconciliation(self, verifier, db, column, value):
        primary = _make_bar_df([(100.0, 105.0, 99.0, 102.0, 5000.0)])
        primary.loc[0, column] = value
        with pytest.raises(ValueError, match="Canonical primary"):
            verifier.verify(
                primary_bars=primary, secondary_bars=None, symbol="RELIANCE", exchange="NSE", timeframe="5m",
                primary_provider="angel_one", secondary_provider="nse_feed", db=db,
                primary_dataset_id="primary-invalid",
            )
        assert db.get_reconciliations(symbol="RELIANCE", timeframe="5m") == []

    def test_no_provider_blending_invariant(self, verifier, db):
        """T034: Verification never blends (averages or synthetically combines) primary and secondary data."""
        bars_primary = _make_bar_df(
            [
                (100.0, 105.0, 99.0, 102.0, 5000.0),
                (102.0, 107.0, 101.0, 106.0, 6000.0),
            ]
        )
        bars_secondary = _make_bar_df(
            [
                (120.0, 125.0, 119.0, 122.0, 9000.0),
                (122.0, 127.0, 121.0, 126.0, 9900.0),
            ]
        )

        original_primary_open_0 = float(bars_primary["open"].iloc[0])
        original_primary_close_0 = float(bars_primary["close"].iloc[0])
        original_primary_vol_0 = float(bars_primary["volume"].iloc[0])

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ProviderDataVerificationWarning)
            report = verifier.verify(
                primary_bars=bars_primary,
                secondary_bars=bars_secondary,
                symbol="RELIANCE",
                exchange="NSE",
                timeframe="5m",
                primary_provider="angel_one",
                secondary_provider="nse_feed",
                severity=VerificationSeverity.WARNING,
                db=db,
                primary_dataset_id="ds_primary_noblend",
                secondary_dataset_id="ds_secondary_noblend",
            )

        # 1. Primary DataFrame object was not altered in-place
        assert float(bars_primary["open"].iloc[0]) == original_primary_open_0
        assert float(bars_primary["close"].iloc[0]) == original_primary_close_0
        assert float(bars_primary["volume"].iloc[0]) == original_primary_vol_0

        # 2. Outcome recorded pure primary values without synthetic averaging
        assert report.bar_outcomes[0].primary_ohlcv["open"] == 100.0
        assert report.bar_outcomes[0].primary_ohlcv["close"] == 102.0
        # Specifically NOT (100.0 + 120.0) / 2 = 110.0
        assert report.bar_outcomes[0].primary_ohlcv["open"] != 110.0
