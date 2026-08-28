from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from storage.duckdb_manager import DuckDBManager
import trading_stack.asset_state as asset_state_module
from trading_stack.asset_state import (
    AssetBehaviorCluster,
    AssetEligibility,
    AssetStateEngine,
    AssetStateFeatures,
    AssetStatePolicy,
    AssetStateService,
    AssetStateSnapshot,
    CertifiedBarEvidence,
    EligibilityReason,
    PITEarningsEventEvidence,
    PITMetadataEvidence,
)
from trading_stack.market_regime import MarketContextType


def _bars(
    *,
    count: int = 130,
    start: str = "2025-01-01",
    daily_return: float = 0.003,
    volume: float = 2_000_000.0,
) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=count, freq="D", tz="UTC") + pd.Timedelta(hours=10)
    closes = 100.0 * np.power(1.0 + daily_return, np.arange(count, dtype=float))
    previous = np.r_[closes[0], closes[:-1]]
    opens = previous * 1.001
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": np.maximum(opens, closes) * 1.01,
            "low": np.minimum(opens, closes) * 0.99,
            "close": closes,
            "volume": np.full(count, volume),
            "candle_available_at": timestamps,
        }
    )


def _evidence(name: str, bars: pd.DataFrame, **overrides: Any) -> CertifiedBarEvidence:
    values: dict[str, Any] = {
        "dataset_id": f"{name}-dataset",
        "content_hash": f"{name}-hash",
        "certification_id": f"{name}-cert",
        "timeframe": "1d",
        "dataset_available_at": bars["candle_available_at"].max().isoformat(),
        "last_bar_timestamp": bars["timestamp"].max().isoformat(),
        "last_bar_available_at": bars["candle_available_at"].max().isoformat(),
        "cutoff_applied": bars["candle_available_at"].max().isoformat(),
    }
    values.update(overrides)
    return CertifiedBarEvidence(**values)


def _constituent(symbol: str = "RELIANCE") -> PointInTimeConstituent:
    return PointInTimeConstituent(
        universe_name="NIFTY200",
        symbol=symbol,
        token="123",
        effective_from=date(2020, 1, 1),
        known_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 1, tzinfo=UTC),
    )


def _evaluate(
    asset_bars: pd.DataFrame | None = None,
    benchmark_bars: pd.DataFrame | None = None,
    decision_time: datetime | None = None,
    **kwargs: Any,
) -> AssetStateSnapshot:
    asset = asset_bars if asset_bars is not None else _bars()
    benchmark = benchmark_bars if benchmark_bars is not None else _bars(daily_return=0.002)
    decision_timestamp = pd.Timestamp(
        decision_time
        or max(asset["candle_available_at"].max(), benchmark["candle_available_at"].max())
    )
    asset_evidence: CertifiedBarEvidence = kwargs.pop("asset_evidence_override", _evidence("asset", asset))
    benchmark_evidence: CertifiedBarEvidence = kwargs.pop("benchmark_evidence_override", _evidence("benchmark", benchmark))
    constituent: PointInTimeConstituent | None = kwargs.pop("constituent", _constituent())
    return AssetStateEngine().evaluate(
        symbol="RELIANCE",
        exchange="NSE",
        universe_name="NIFTY200",
        benchmark_symbol="NIFTY200",
        as_of=decision_timestamp.date(),
        decision_time=decision_timestamp.to_pydatetime(),
        context_type=MarketContextType.EOD,
        asset_bars=asset,
        benchmark_bars=benchmark,
        asset_evidence=asset_evidence,
        benchmark_evidence=benchmark_evidence,
        constituent=constituent,
        **kwargs,
    )


def _features(**overrides: float | None) -> AssetStateFeatures:
    values: dict[str, float | None] = {
        "trend_strength": 0.20,
        "momentum_20": 0.10,
        "momentum_60": 0.20,
        "momentum_120": 0.30,
        "relative_strength": 0.05,
        "realized_volatility": 0.20,
        "atr": 2.0,
        "normalized_atr": 0.02,
        "beta": 1.0,
        "latest_traded_value": 600_000_000.0,
        "median_traded_value_20": 600_000_000.0,
        "total_turnover_20": 12_000_000_000.0,
        "volume_behavior": 1.0,
        "gap_frequency": 0.05,
        "mean_reversion_tendency": 0.10,
        "trend_persistence": 0.70,
        "trend_score": 0.50,
        "momentum_score": 0.50,
        "volatility_score": 0.40,
        "liquidity_score": 1.0,
        "gap_risk_score": 0.25,
        "mean_reversion_score": 0.10,
        "relative_strength_score": 0.33,
    }
    values.update(overrides)
    return AssetStateFeatures(**values)


@pytest.mark.parametrize(
    ("overrides", "market_cap", "expected"),
    [
        (
            {"beta": 1.20, "trend_score": 0.50, "momentum_score": 0.40, "trend_persistence": 0.60},
            None,
            AssetBehaviorCluster.HIGH_BETA_TRENDING,
        ),
        (
            {"volatility_score": 0.35, "trend_score": 0.40, "momentum_score": 0.30, "trend_persistence": 0.55},
            None,
            AssetBehaviorCluster.LOW_VOL_TRENDING,
        ),
        (
            {"volatility_score": 0.65, "mean_reversion_score": 0.35, "trend_persistence": 0.45, "trend_score": 0.0},
            None,
            AssetBehaviorCluster.HIGH_VOL_MEAN_REVERTING,
        ),
        (
            {"median_traded_value_20": 49_999_999.0, "liquidity_score": 0.09},
            None,
            AssetBehaviorCluster.LOW_LIQUIDITY,
        ),
        (
            {"trend_score": 0.0, "momentum_score": 0.0},
            "LARGE",
            AssetBehaviorCluster.LIQUID_LARGE_CAP,
        ),
        (
            {"trend_score": 0.0, "momentum_score": 0.0, "trend_persistence": 0.2},
            None,
            AssetBehaviorCluster.MIXED_UNCLASSIFIED,
        ),
    ],
)
def test_cluster_rules_and_exact_boundaries(
    overrides: dict[str, float | None], market_cap: str | None, expected: AssetBehaviorCluster
) -> None:
    cluster, confidence, detail = AssetStateEngine().classify(_features(**overrides), market_cap)
    assert cluster is expected
    assert 0.0 <= confidence <= 1.0
    assert detail["selected"] == expected.value


def test_snapshot_calculates_features_and_deterministic_identity() -> None:
    first = _evaluate()
    second = _evaluate()
    assert first.asset_state_id == second.asset_state_id
    assert first.input_evidence_hash == second.input_evidence_hash
    assert first.eligibility is AssetEligibility.ELIGIBLE
    assert first.features.momentum_120 is not None
    assert first.features.beta is not None
    assert first.features.atr is not None
    assert first.sector is None
    assert first.market_cap_bucket is None
    assert first.earnings_proximity is None


def test_future_bar_mutation_and_insertion_do_not_change_snapshot() -> None:
    asset = _bars()
    benchmark = _bars(daily_return=0.002)
    baseline = _evaluate(asset, benchmark)
    decision_time = asset["candle_available_at"].max().to_pydatetime()
    asset_evidence = _evidence("asset", asset)
    future_time = asset["timestamp"].max() + pd.Timedelta(days=1)
    future = asset.iloc[-1:].copy()
    future["timestamp"] = future_time
    future["candle_available_at"] = future_time
    future["close"] = 1_000_000.0
    mutated = pd.concat([asset, future], ignore_index=True)
    changed = _evaluate(
        mutated,
        benchmark,
        decision_time=decision_time,
        asset_evidence_override=asset_evidence,
    )
    assert changed.asset_state_id == baseline.asset_state_id
    assert changed.features == baseline.features


def test_policy_and_model_versions_change_identity() -> None:
    baseline = _evaluate()
    changed_policy = _evaluate(policy=AssetStatePolicy(policy_version="2.5.1"))
    changed_model = _evaluate(model_version="asset-state-v2")
    assert changed_policy.asset_state_id != baseline.asset_state_id
    assert changed_model.asset_state_id != baseline.asset_state_id


def test_eligibility_fails_closed_for_history_liquidity_and_integrity() -> None:
    short = _bars(count=120)
    history = _evaluate(short, _bars(count=120, daily_return=0.002))
    assert history.eligibility is AssetEligibility.INELIGIBLE
    assert EligibilityReason.INSUFFICIENT_HISTORY.value in history.eligibility_reasons

    illiquid = _evaluate(_bars(volume=1_000.0), _bars(daily_return=0.002))
    assert illiquid.behavior_cluster is AssetBehaviorCluster.LOW_LIQUIDITY
    assert EligibilityReason.INSUFFICIENT_LIQUIDITY.value in illiquid.eligibility_reasons

    asset = _bars()
    unhealthy = _evaluate(
        asset,
        _bars(daily_return=0.002),
        asset_evidence_override=_evidence(
            "bad", asset, integrity_failure=True, integrity_failure_reason="EXPLICIT_DQ_FAILURE"
        ),
    )
    assert EligibilityReason.DATA_INTEGRITY_FAILURE.value in unhealthy.eligibility_reasons


def test_invalid_price_and_uncertified_data_are_ineligible() -> None:
    invalid = _bars()
    invalid.loc[invalid.index[-1], "close"] = 0.0
    snapshot = _evaluate(invalid, _bars(daily_return=0.002))
    assert EligibilityReason.INVALID_PRICE.value in snapshot.eligibility_reasons

    asset = _bars()
    uncertified = _evaluate(
        asset,
        _bars(daily_return=0.002),
        asset_evidence_override=replace(_evidence("asset", asset), certification_id=None),
    )
    assert EligibilityReason.UNCERTIFIED_DATA.value in uncertified.eligibility_reasons

    future_evidence = replace(
        _evidence("asset", asset),
        dataset_available_at=(asset["timestamp"].max() + pd.Timedelta(seconds=1)).isoformat(),
    )
    future = _evaluate(
        asset,
        _bars(daily_return=0.002),
        asset_evidence_override=future_evidence,
    )
    assert EligibilityReason.UNCERTIFIED_DATA.value in future.eligibility_reasons


def test_optional_pit_metadata_is_causal_and_never_fabricated() -> None:
    decision = _bars()["timestamp"].max().to_pydatetime()
    sector = PITMetadataEvidence(
        metadata_id="sector-1",
        field="sector",
        value="ENERGY",
        content_hash="sector-hash",
        certification_id="sector-cert",
        effective_from=date(2020, 1, 1),
        effective_until=None,
        known_at=decision - timedelta(days=1),
    )
    cap = replace(sector, metadata_id="cap-1", field="market_cap_bucket", value="LARGE")
    event = PITEarningsEventEvidence(
        event_id="earnings-1",
        event_at=decision + timedelta(days=7),
        known_at=decision - timedelta(days=2),
        content_hash="event-hash",
        certification_id="event-cert",
    )
    admitted = _evaluate(sector_metadata=sector, market_cap_metadata=cap, earnings_events=[event])
    assert admitted.sector == "ENERGY"
    assert admitted.market_cap_bucket == "LARGE"
    assert admitted.earnings_proximity == 7

    future_sector = replace(sector, value="FUTURE", known_at=decision + timedelta(seconds=1))
    future_event = replace(event, event_id="future", known_at=decision + timedelta(seconds=1))
    rejected = _evaluate(sector_metadata=future_sector, earnings_events=[future_event])
    assert rejected.sector is None
    assert rejected.earnings_proximity is None


def test_future_benchmark_data_cannot_leak() -> None:
    asset = _bars()
    benchmark = _bars(daily_return=0.002)
    baseline = _evaluate(asset, benchmark)
    decision_time = asset["candle_available_at"].max().to_pydatetime()
    benchmark_evidence = _evidence("benchmark", benchmark)
    future = benchmark.iloc[-1:].copy()
    future["timestamp"] += pd.Timedelta(days=1)
    future["candle_available_at"] += pd.Timedelta(days=1)
    future["close"] = 0.01
    changed = _evaluate(
        asset,
        pd.concat([benchmark, future], ignore_index=True),
        decision_time=decision_time,
        benchmark_evidence_override=benchmark_evidence,
    )
    assert changed.asset_state_id == baseline.asset_state_id
    assert changed.features.relative_strength == baseline.features.relative_strength


def test_storage_is_idempotent_restart_safe_and_conflicts_fail(tmp_path) -> None:
    path = str(tmp_path / "asset-state.duckdb")
    snapshot = _evaluate()
    db = DuckDBManager(path)
    db.persist_asset_state_snapshot(snapshot)
    db.persist_asset_state_snapshot(snapshot)
    row = db.get_asset_state_snapshot(snapshot.asset_state_id)
    assert row is not None
    assert row["behavior_cluster"] == snapshot.behavior_cluster.value
    assert json.loads(row["input_evidence_manifest_json"])["symbol"] == "RELIANCE"
    assert len(db.list_asset_state_snapshots(symbol="RELIANCE")) == 1
    db.close()

    reopened = DuckDBManager(path)
    assert reopened.get_asset_state_snapshot(snapshot.asset_state_id) is not None
    conflicting = replace(snapshot, cluster_confidence=max(0.0, snapshot.cluster_confidence - 0.1))
    with pytest.raises(ValueError, match="Conflicting immutable asset state snapshot"):
        reopened.persist_asset_state_snapshot(conflicting)
    reopened.close()


class _FakeDB:
    def __init__(
        self,
        asset: pd.DataFrame,
        benchmark: pd.DataFrame,
        valid_certifications: set[str] | None = None,
    ) -> None:
        self.asset = asset
        self.benchmark = benchmark
        self.calls: list[dict[str, Any]] = []
        self.persisted: Any = None
        self.valid_certifications: set[str] = valid_certifications or set()

    def load_regime_bars(self, symbol: str, timeframe: str, decision_time: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"symbol": symbol, "timeframe": timeframe, **kwargs})
        bars = self.benchmark if symbol == "NIFTY200" else self.asset
        return {
            "bars": bars.copy(),
            "dataset_id": f"{symbol}-dataset",
            "content_hash": f"{symbol}-hash",
            "certification_id": f"{symbol}-cert",
            "cutoff_applied": decision_time,
            "timeframe": "1d",
            "dataset_available_at": bars["candle_available_at"].max().isoformat(),
            "last_bar_timestamp": bars["timestamp"].max().isoformat(),
            "last_bar_available_at": bars["candle_available_at"].max().isoformat(),
            "integrity_failure": False,
            "integrity_failure_reason": None,
        }

    def is_certification_valid(
        self,
        certification_id: str,
        *,
        content_hash: str | None = None,
        decision_time: Any | None = None,
    ) -> bool:
        return certification_id in self.valid_certifications

    def persist_asset_state_snapshot(self, snapshot: Any) -> None:
        self.persisted = snapshot


def test_service_reuses_authoritative_pit_and_certified_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _bars()
    benchmark = _bars(daily_return=0.002)
    db = _FakeDB(asset, benchmark)
    monkeypatch.setattr(
        PointInTimeUniverseManager,
        "get_constituents",
        classmethod(lambda cls, conn, universe_name, as_of, as_of_knowledge=None: [_constituent()]),
    )
    snapshot = AssetStateService(db).evaluate(
        symbol="RELIANCE",
        exchange="NSE",
        universe_name="NIFTY200",
        benchmark_symbol="NIFTY200",
        as_of=asset["timestamp"].max().date(),
        decision_time=asset["timestamp"].max().to_pydatetime(),
        context_type=MarketContextType.INTRADAY,
        persist=True,
    )
    assert snapshot.eligibility is AssetEligibility.ELIGIBLE
    assert db.persisted is snapshot
    assert [call["symbol"] for call in db.calls] == ["RELIANCE", "NIFTY200"]
    assert all(call["context_type"] == "INTRADAY" for call in db.calls)
    assert all(call["intraday"] is False for call in db.calls)


def test_service_missing_pit_membership_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _bars()
    db = _FakeDB(asset, _bars(daily_return=0.002))
    monkeypatch.setattr(
        PointInTimeUniverseManager,
        "get_constituents",
        classmethod(lambda cls, conn, universe_name, as_of, as_of_knowledge=None: []),
    )
    snapshot = AssetStateService(db).evaluate(
        symbol="RELIANCE",
        exchange="NSE",
        universe_name="NIFTY200",
        benchmark_symbol="NIFTY200",
        as_of=asset["timestamp"].max().date(),
        decision_time=asset["timestamp"].max().to_pydatetime(),
        context_type=MarketContextType.EOD,
    )
    assert snapshot.eligibility is AssetEligibility.INELIGIBLE
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value in snapshot.eligibility_reasons


@pytest.mark.parametrize(
    "changes",
    [
        {"minimum_history_sessions": 120},
        {"momentum_windows": (20, 60)},
        {"momentum_weights": (0.2, 0.3, 0.4)},
        {"momentum_targets": (0.1, 0.2)},
        {"minimum_median_traded_value": 0.0},
        {"minimum_median_traded_value": 100.0, "full_liquidity_traded_value": 99.0},
        {"cluster_rule_order": (AssetBehaviorCluster.MIXED_UNCLASSIFIED.value,)},
    ],
)
def test_policy_validation_fails_closed(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        AssetStatePolicy(**changes)


def test_naive_decision_time_is_rejected() -> None:
    asset = _bars()
    with pytest.raises(ValueError, match="timezone-aware"):
        _evaluate(asset, _bars(daily_return=0.002), decision_time=datetime(2025, 5, 1))


def test_empty_and_missing_columns_preserve_missing_evidence() -> None:
    empty = pd.DataFrame()
    benchmark = _bars()
    snapshot = AssetStateEngine().evaluate(
        symbol="RELIANCE",
        exchange="NSE",
        universe_name="NIFTY200",
        benchmark_symbol="NIFTY200",
        as_of=benchmark["timestamp"].max().date(),
        decision_time=benchmark["timestamp"].max().to_pydatetime(),
        context_type=MarketContextType.EOD,
        asset_bars=empty,
        benchmark_bars=benchmark.drop(columns="candle_available_at"),
        asset_evidence=CertifiedBarEvidence.from_loader_result({"cutoff_applied": "cutoff"}),
        benchmark_evidence=CertifiedBarEvidence.from_loader_result({"cutoff_applied": "cutoff"}),
        constituent=None,
    )
    assert snapshot.features == AssetStateFeatures()
    assert EligibilityReason.MISSING_CAUSAL_BARS.value in snapshot.eligibility_reasons
    assert EligibilityReason.MISSING_BENCHMARK_EVIDENCE.value in snapshot.eligibility_reasons
    assert snapshot.input_hashes["asset_causal_bars"]


def test_optional_windows_remain_none_until_sufficient() -> None:
    asset = _bars(count=25)
    benchmark = _bars(count=25, daily_return=0.0)
    snapshot = _evaluate(asset, benchmark)
    assert snapshot.features.momentum_20 is not None
    assert snapshot.features.momentum_60 is None
    assert snapshot.features.beta is None
    assert snapshot.features.gap_frequency is None
    assert snapshot.features.mean_reversion_score is None


def test_metadata_outside_effective_interval_and_naive_values_are_ignored() -> None:
    decision = _bars()["timestamp"].max().to_pydatetime()
    expired = PITMetadataEvidence(
        metadata_id="expired",
        field="sector",
        value="ENERGY",
        content_hash="hash",
        certification_id="cert",
        effective_from=date(2020, 1, 1),
        effective_until=date(2021, 1, 1),
        known_at=decision - timedelta(days=1),
    )
    naive_event = PITEarningsEventEvidence(
        event_id="naive",
        event_at=datetime(2025, 6, 1),
        known_at=datetime(2025, 5, 1),
        content_hash="hash",
        certification_id="cert",
    )
    snapshot = _evaluate(sector_metadata=expired, earnings_events=[naive_event])
    assert snapshot.sector is None
    assert snapshot.earnings_proximity is None


def test_future_and_legacy_null_pit_membership_fail_closed() -> None:
    bars = _bars()
    decision = bars["timestamp"].max().to_pydatetime()
    future_member = replace(
        _constituent(),
        known_from=decision.date(),
        known_at=decision + timedelta(seconds=1),
    )
    future = _evaluate(constituent=future_member)
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value in future.eligibility_reasons
    legacy = _evaluate(constituent=replace(_constituent(), known_from=None, known_at=None))
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value in legacy.eligibility_reasons


def test_storage_listing_filters_and_limit_validation(tmp_path) -> None:
    db = DuckDBManager(str(tmp_path / "filters.duckdb"))
    snapshot = _evaluate()
    db.persist_asset_state_snapshot(snapshot)
    assert db.list_asset_state_snapshots(
        exchange="NSE",
        context_type="EOD",
        as_of=snapshot.as_of,
        behavior_cluster=snapshot.behavior_cluster.value,
        eligibility=snapshot.eligibility.value,
        model_version=snapshot.model_version,
    )
    assert db.list_asset_state_snapshots(symbol="MISSING") == []
    with pytest.raises(ValueError, match="positive"):
        db.list_asset_state_snapshots(limit=0)
    db.close()


def test_numeric_and_canonical_edge_contracts() -> None:
    assert asset_state_module._aligned_returns(pd.DataFrame(), pd.DataFrame()).empty
    assert asset_state_module._return_over(pd.Series([0.0, 1.0]), 1) is None
    with pytest.raises(ValueError, match="high must exceed"):
        asset_state_module._range_score(1.0, 1.0, 1.0)
    assert asset_state_module._positive_support(None, 1.0) == 0.0
    assert asset_state_module._positive_support(0.0, 0.0) == 1.0
    assert asset_state_module._positive_support(-1.0, 0.0) == 0.0
    assert asset_state_module._negative_support(None, 1.0) == 0.0
    assert asset_state_module._negative_support(0.5, 1.0) == 1.0
    assert asset_state_module._canonical_value(AssetEligibility.ELIGIBLE) == "ELIGIBLE"
    assert asset_state_module._canonical_value(np.int64(2)) == 2
    with pytest.raises(ValueError, match="timezone-aware"):
        asset_state_module._canonical_value(datetime(2025, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        asset_state_module._canonical_value(pd.Timestamp("2025-01-01"))


def test_missing_uncomputable_liquidity_fails_closed() -> None:
    # 15 bars: fewer than liquidity window (20), so median_traded_value_20 is None
    short_bars = _bars(count=15)
    snapshot = _evaluate(short_bars, _bars(count=15, daily_return=0.002))
    assert snapshot.features.median_traded_value_20 is None
    assert snapshot.eligibility is AssetEligibility.INELIGIBLE
    assert EligibilityReason.INSUFFICIENT_LIQUIDITY.value in snapshot.eligibility_reasons

    # All volume NaN: median_traded_value_20 is None even with 130 bars
    nan_volume = _bars(count=130)
    nan_volume["volume"] = np.nan
    nan_snapshot = _evaluate(nan_volume, _bars(count=130, daily_return=0.002))
    assert nan_snapshot.features.median_traded_value_20 is None
    assert nan_snapshot.eligibility is AssetEligibility.INELIGIBLE
    assert EligibilityReason.INSUFFICIENT_LIQUIDITY.value in nan_snapshot.eligibility_reasons


def test_service_enforces_authoritative_metadata_certification(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _bars()
    benchmark = _bars(daily_return=0.002)
    decision = asset["timestamp"].max().to_pydatetime()
    db_path = str(tmp_path / "cert_test.duckdb")
    db = DuckDBManager(db_path)

    # Insert one real valid certification in data_quality_certifications
    real_cert_id = "real-cert-123"
    real_hash = "sector-hash-123"
    checks_json = json.dumps({"dataset_content_hash": real_hash})
    db.conn.execute(
        """INSERT INTO data_quality_certifications (
            certification_id, dataset_id, validator_version, check_count,
            issue_count, checks_json, status, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            real_cert_id, "sector-dataset", "1.0.0", 6, 0,
            checks_json, "CERTIFIED", decision - timedelta(days=2), decision - timedelta(days=1),
        ],
    )

    monkeypatch.setattr(
        PointInTimeUniverseManager,
        "get_constituents",
        classmethod(lambda cls, conn, universe_name, as_of, as_of_knowledge=None: [_constituent()]),
    )
    monkeypatch.setattr(
        db,
        "load_regime_bars",
        lambda symbol, **kwargs: {
            "bars": (benchmark if symbol == "NIFTY200" else asset).copy(),
            "dataset_id": f"{symbol}-dataset",
            "content_hash": f"{symbol}-hash",
            "certification_id": f"{symbol}-cert",
            "cutoff_applied": kwargs.get("decision_time", ""),
            "timeframe": "1d",
            "dataset_available_at": asset["candle_available_at"].max().isoformat(),
            "last_bar_timestamp": asset["timestamp"].max().isoformat(),
            "last_bar_available_at": asset["candle_available_at"].max().isoformat(),
            "integrity_failure": False,
            "integrity_failure_reason": None,
        },
    )

    valid_sector = PITMetadataEvidence(
        metadata_id="sec-1",
        field="sector",
        value="FINANCIALS",
        content_hash=real_hash,
        certification_id=real_cert_id,
        effective_from=date(2020, 1, 1),
        effective_until=None,
        known_at=decision - timedelta(days=1),
    )
    fake_sector = replace(valid_sector, certification_id="fake-cert-unregistered")
    fake_event = PITEarningsEventEvidence(
        event_id="earn-fake",
        event_at=decision + timedelta(days=5),
        known_at=decision - timedelta(days=2),
        content_hash="fake-hash",
        certification_id="fake-cert-unregistered",
    )

    service = AssetStateService(db)

    # 1. Unregistered certification IDs are rejected and remain None / excluded
    rejected_snapshot = service.evaluate(
        symbol="RELIANCE",
        exchange="NSE",
        universe_name="NIFTY200",
        benchmark_symbol="NIFTY200",
        as_of=asset["timestamp"].max().date(),
        decision_time=decision,
        context_type=MarketContextType.EOD,
        sector_metadata=fake_sector,
        earnings_events=[fake_event],
    )
    assert rejected_snapshot.sector is None
    assert rejected_snapshot.earnings_proximity is None
    assert rejected_snapshot.input_evidence["metadata"]["sector"] is None
    assert rejected_snapshot.input_evidence["metadata"]["earnings_events"] == []

    # 2. Registered authoritative certification is admitted
    admitted_snapshot = service.evaluate(
        symbol="RELIANCE",
        exchange="NSE",
        universe_name="NIFTY200",
        benchmark_symbol="NIFTY200",
        as_of=asset["timestamp"].max().date(),
        decision_time=decision,
        context_type=MarketContextType.EOD,
        sector_metadata=valid_sector,
    )
    assert admitted_snapshot.sector == "FINANCIALS"
    assert admitted_snapshot.input_evidence["metadata"]["sector"] is not None

    # 3. Direct raw connection fallback in AssetStateService
    raw_service = AssetStateService(db.conn)
    assert raw_service._verify_certification(real_cert_id, real_hash, decision) is True
    assert raw_service._verify_certification(real_cert_id, "mismatched-hash", decision) is False
    assert raw_service._verify_certification("fake-cert", real_hash, decision) is False
    assert raw_service._verify_certification(None, None, decision) is False

    # 4. Certification with issues or non-CERTIFIED status fails
    db.conn.execute(
        """INSERT INTO data_quality_certifications (
            certification_id, dataset_id, validator_version, check_count,
            issue_count, checks_json, status, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            "failed-cert", "sector-dataset", "1.0.0", 6, 1,
            checks_json, "FAILED", decision - timedelta(days=2), decision - timedelta(days=1),
        ],
    )
    assert db.is_certification_valid("failed-cert") is False
    assert raw_service._verify_certification("failed-cert", real_hash, decision) is False

    # 5. Invalid/broken DB connection gracefully fails closed
    class _BrokenDB:
        conn = None
    assert AssetStateService(_BrokenDB())._verify_certification("real-cert", None, decision) is False

    db.close()


def test_pit_membership_historical_known_from_requires_strict_known_at() -> None:
    bars = _bars()
    decision = bars["timestamp"].max().to_pydatetime()

    # Historical known_from (years before decision date) but known_at is None -> FAILS CLOSED
    historical_no_known_at = replace(
        _constituent(),
        known_from=date(2020, 1, 1),
        known_at=None,
    )
    res_no_known_at = _evaluate(constituent=historical_no_known_at, decision_time=decision)
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value in res_no_known_at.eligibility_reasons

    # Historical known_from but known_at is naive -> FAILS CLOSED
    historical_naive_known_at = replace(
        _constituent(),
        known_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 1),
    )
    res_naive = _evaluate(constituent=historical_naive_known_at, decision_time=decision)
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value in res_naive.eligibility_reasons

    # Historical known_from but known_at is in the future relative to decision_time -> FAILS CLOSED
    historical_future_known_at = replace(
        _constituent(),
        known_from=date(2020, 1, 1),
        known_at=decision + timedelta(seconds=1),
    )
    res_future = _evaluate(constituent=historical_future_known_at, decision_time=decision)
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value in res_future.eligibility_reasons

    # Historical known_from with valid causal timezone-aware known_at <= decision_time -> ADMITTED
    historical_valid = replace(
        _constituent(),
        known_from=date(2020, 1, 1),
        known_at=decision - timedelta(days=10),
    )
    res_valid = _evaluate(constituent=historical_valid, decision_time=decision)
    assert EligibilityReason.MISSING_PIT_EVIDENCE.value not in res_valid.eligibility_reasons
    assert res_valid.eligibility is AssetEligibility.ELIGIBLE
