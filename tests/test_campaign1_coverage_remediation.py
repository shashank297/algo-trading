"""Targeted test suite to remediate critical path coverage gates for Campaign 1.

Specifically covers branches in:
- trading_stack/promotion.py (permission checks, evaluation edge branches, paper active)
- trading_stack/pipeline.py (data quality checks, trade attribution, paper risk, asset class lookup)
- trading_stack/datasets.py (panel builder duplicates, PIT fail closed, authoritative DQ evidence)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from risk.engine import RiskEngine
from storage.duckdb_manager import DuckDBManager
from trading_stack.backtest import ExecutionModel
from trading_stack.datasets import SynchronizedPanelBuilder
from trading_stack.domain import AssetClass
from trading_stack.pipeline import DataQualityError, StrategyPipeline
from trading_stack.promotion import PromotionEngine, PromotionStage
from validators.data_quality import DataQualityError as PanelDataQualityError


@pytest.fixture
def clean_db(tmp_path):
    """Provides an isolated DuckDB instance with all required schema tables initialized via migrations."""
    db_file = tmp_path / "test_remediation.duckdb"
    db = DuckDBManager(str(db_file))
    yield db
    db.close()


# =========================================================================
# Part 1: trading_stack/promotion.py branch coverage
# =========================================================================

def test_promotion_stage_mismatch_raises_permission_error(clean_db):
    engine = PromotionEngine(clean_db)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev1', 'run1', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    mock_appr = MagicMock()
    with pytest.raises(PermissionError, match="does not match expected stage"):
        engine.assert_paper_authorized(
            run_id="run1",
            strategy_name="trend",
            approval_evidence=mock_appr,
            expected_stage="PAPER_ACTIVE",
        )


def test_promotion_missing_approval_evidence_raises(clean_db):
    engine = PromotionEngine(clean_db)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev1', 'run1', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    with pytest.raises(PermissionError, match="lacks authoritative external human/board approval evidence"):
        engine.assert_paper_authorized(
            run_id="run1",
            strategy_name="trend",
            approval_evidence=None,
        )


def test_promotion_review_id_mismatch_raises(clean_db):
    engine = PromotionEngine(clean_db)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev1', 'run1', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    mock_appr = MagicMock()
    with pytest.raises(PermissionError, match="does not match expected promotion review"):
        engine.assert_paper_authorized(
            run_id="run1",
            strategy_name="trend",
            approval_evidence=mock_appr,
            expected_promotion_review_id="rev2",
        )


def test_promotion_foundation_cert_checks(clean_db, monkeypatch):
    engine = PromotionEngine(clean_db)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev1', 'run1', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    mock_appr = MagicMock()

    # 1. No active foundation cert
    with pytest.raises(PermissionError, match="requires an active PASS foundation certification"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
        )

    # 2. Insert active cert with empty code_sha
    clean_db.conn.execute("""
        INSERT INTO foundation_certifications (
            foundation_certification_id, artifact_version, generated_at, status,
            code_sha, lineage_status, risk_policy_id, risk_policy_hash,
            gates_json, derived_flags_json, artifact_sha256, artifact_json, is_active, recorded_at
        ) VALUES ('fc_1', 'v1', CURRENT_TIMESTAMP, 'PASS', '', 'PASS', 'pol_1', 'hash_1', '[]', '{}', 'art_hash', '{}', true, CURRENT_TIMESTAMP)
    """)
    with pytest.raises(PermissionError, match="has no authoritative code identity"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
        )

    # 3. Update cert with code_sha but runtime CODE_SHA is unset
    clean_db.conn.execute("UPDATE foundation_certifications SET code_sha = 'sha_100' WHERE foundation_certification_id = 'fc_1'")
    monkeypatch.delenv("CODE_SHA", raising=False)
    with pytest.raises(PermissionError, match="requires an explicit runtime CODE_SHA identity"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
        )

    # 4. Runtime CODE_SHA doesn't match active cert
    monkeypatch.setenv("CODE_SHA", "sha_200")
    with pytest.raises(PermissionError, match="does not match the runtime CODE_SHA"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
        )

    # 5. Runtime CODE_SHA matches, but expected_foundation_cert_id differs
    monkeypatch.setenv("CODE_SHA", "sha_100")
    with pytest.raises(PermissionError, match="is not the active certification"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
            expected_foundation_cert_id="fc_other",
        )

    # 6. Expected code_sha differs from runtime
    with pytest.raises(PermissionError, match="is not the runtime code identity"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
            expected_code_sha="sha_mismatch",
        )


def test_promotion_risk_policy_mismatches_and_missing_context(clean_db, monkeypatch):
    engine = PromotionEngine(clean_db)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev1', 'run1', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    mock_appr = MagicMock()
    monkeypatch.setenv("CODE_SHA", "sha_100")
    clean_db.conn.execute("""
        INSERT INTO foundation_certifications (
            foundation_certification_id, artifact_version, generated_at, status,
            code_sha, lineage_status, risk_policy_id, risk_policy_hash,
            gates_json, derived_flags_json, artifact_sha256, artifact_json, is_active, recorded_at
        ) VALUES ('fc_1', 'v1', CURRENT_TIMESTAMP, 'PASS', 'sha_100', 'PASS', 'CANONICAL_V1', 'hash_canon', '[]', '{}', 'art_hash', '{}', true, CURRENT_TIMESTAMP)
    """)


    # Risk policy ID mismatch
    with pytest.raises(PermissionError, match="is not the canonical active policy"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
            expected_risk_policy_id="WRONG_POLICY_ID",
        )

    # Risk policy hash mismatch
    with pytest.raises(PermissionError, match="is not the canonical active policy hash"):
        engine.assert_paper_authorized(
            run_id="run1", strategy_name="trend", approval_evidence=mock_appr,
            expected_risk_policy_hash="WRONG_HASH",
        )

    # Missing context when run_row has no evidence hash
    clean_db.conn.execute("""
        INSERT INTO strategy_runs (run_id, strategy_name, symbol, asset_class, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id)
        VALUES ('run_empty', 'trend', 'RELIANCE', 'EQUITY', '1d', 'BACKTEST', '{}', '', 'COMPLETED', CURRENT_TIMESTAMP, 'frame-1')
    """)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev_empty', 'run_empty', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    with pytest.raises(PermissionError, match="Paper authorization failed closed: unresolvable authoritative context"):
        engine.assert_paper_authorized(
            run_id="run_empty", strategy_name="trend", approval_evidence=mock_appr,
            expected_evidence_hash=None,
        )


def test_promotion_evaluation_edge_branches(clean_db):
    engine = PromotionEngine(clean_db)
    run_id = "eval_run_1"

    # Seed strategy_runs
    clean_db.conn.execute("""
        INSERT INTO strategy_runs (run_id, strategy_name, symbol, asset_class, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id)
        VALUES ('eval_run_1', 'trend', 'RELIANCE', 'EQUITY', '1d', 'event-driven', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, 'frame-1')
    """)
    clean_db.conn.execute("""
        INSERT INTO run_certification_bundles (bundle_id, run_id, run_data_hash, frame_certification_id, certification_version, created_at)
        VALUES ('b1', 'eval_run_1', 'h_data', 'frame-1', 'v1.0', CURRENT_TIMESTAMP)
    """)
    for cat in ["DATA_LINEAGE", "DATA_QUALITY", "CAUSALITY", "PIT_SURVIVORSHIP", "OOS_WALK_FORWARD"]:
        clean_db.conn.execute("""
            INSERT INTO run_certifications (certification_id, bundle_id, run_id, category, status, evidence_json, certified_at)
            VALUES (?, 'b1', 'eval_run_1', ?, 'PASS', '{}', CURRENT_TIMESTAMP)
        """, [f"c1_{cat}", cat])

    # Setup walk_forward_metrics with all required columns
    clean_db.conn.execute("""
        INSERT INTO walk_forward_metrics (run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value)
        VALUES ('eval_run_1', 'fold1', '2025-12-31', '2026-01-01', '2026-01-10', 'sharpe', 1.5)
    """)
    clean_db.conn.execute("""
        INSERT INTO walk_forward_metrics (run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value)
        VALUES ('eval_run_1', 'fold1', '2025-12-31', '2026-01-01', '2026-01-10', 'trades', 50.0)
    """)

    # 1. Equity curve with identical returns (ret_std == 0, ret_mean > 0)
    timestamps = [
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc),
    ]
    for ts, eq in zip(timestamps, [100.0, 110.0, 121.0]):
        clean_db.conn.execute("""
            INSERT INTO strategy_equity_curve (run_id, timestamp, equity, gross_return, net_return, drawdown, gross_exposure, evidence_level, fold_id)
            VALUES ('eval_run_1', ?, ?, 0.1, 0.1, 0.0, 0.0, 'OUT_OF_SAMPLE', 'fold1')
        """, [ts, eq])

    result = engine.review(
        run_id=run_id,
        human_approved=True,
        paper_activation=True,
    )
    assert result is not None
    assert "stage" in result

    # 2. Equity curve with zero change (ret_mean == 0, ret_std == 0)
    run_id_flat = "eval_flat"
    clean_db.conn.execute("""
        INSERT INTO strategy_runs (run_id, strategy_name, symbol, asset_class, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id)
        VALUES ('eval_flat', 'trend', 'RELIANCE', 'EQUITY', '1d', 'event-driven', '{}', 'h_data2', 'COMPLETED', CURRENT_TIMESTAMP, 'frame-2')
    """)
    clean_db.conn.execute("""
        INSERT INTO run_certification_bundles (bundle_id, run_id, run_data_hash, frame_certification_id, certification_version, created_at)
        VALUES ('b2', 'eval_flat', 'h_data2', 'frame-2', 'v1.0', CURRENT_TIMESTAMP)
    """)
    for cat in ["DATA_LINEAGE", "DATA_QUALITY", "CAUSALITY", "PIT_SURVIVORSHIP", "OOS_WALK_FORWARD"]:
        clean_db.conn.execute("""
            INSERT INTO run_certifications (certification_id, bundle_id, run_id, category, status, evidence_json, certified_at)
            VALUES (?, 'b2', 'eval_flat', ?, 'PASS', '{}', CURRENT_TIMESTAMP)
        """, [f"c2_{cat}", cat])

    clean_db.conn.execute("""
        INSERT INTO walk_forward_metrics (run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value)
        VALUES ('eval_flat', 'fold1', '2025-12-31', '2026-01-01', '2026-01-10', 'sharpe', 0.0)
    """)
    for ts in timestamps:
        clean_db.conn.execute("""
            INSERT INTO strategy_equity_curve (run_id, timestamp, equity, gross_return, net_return, drawdown, gross_exposure, evidence_level, fold_id)
            VALUES ('eval_flat', ?, 100.0, 0.0, 0.0, 0.0, 0.0, 'OUT_OF_SAMPLE', 'fold1')
        """, [ts])

    flat_res = engine.review(
        run_id=run_id_flat,
    )
    assert flat_res["stage"] == PromotionStage.RESEARCH_ONLY.value


# =========================================================================
# Part 2: trading_stack/pipeline.py branch coverage
# =========================================================================

def test_pipeline_load_candles_empty_raises(clean_db):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=False)
    with pytest.raises(ValueError, match="No stored candles found for UNKNOWN_SYMBOL"):
        pipeline.load_candles("UNKNOWN_SYMBOL", "1d")


def test_pipeline_pit_filter_empty_raises(clean_db, monkeypatch):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=False)
    clean_db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id, created_at)
        VALUES ('SYM_PIT', '1001', 'NSE', '1d', CURRENT_TIMESTAMP, 100, 105, 95, 102, 1000, 'UNADJUSTED', 'angelone', 'DS1', CURRENT_TIMESTAMP)
    """)
    monkeypatch.setattr(
        "trading_stack.pipeline.filter_frame_by_pit",
        lambda db, frame, univ, required: (pd.DataFrame(), "pit_hash"),
    )
    with pytest.raises(ValueError, match="No PIT-eligible candles found"):
        pipeline.load_candles("SYM_PIT", "1d")


@pytest.fixture
def admitted_pit_candles(monkeypatch):
    """Isolate candle quality checks from the earlier PIT admission gate."""
    def filter_admitted_candles(db, frame, universe_name, **kwargs):
        assert kwargs["required"] is True
        return frame, "test-pit-evidence-hash"

    monkeypatch.setattr("trading_stack.pipeline.filter_frame_by_pit", filter_admitted_candles)


def test_pipeline_authoritative_dq_null_dataset_raises(clean_db, admitted_pit_candles):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=True)
    clean_db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id, created_at)
        VALUES ('SYM_NULL', '1002', 'NSE', '1d', CURRENT_TIMESTAMP, 100, 105, 95, 102, 1000, 'UNADJUSTED', 'angelone', NULL, CURRENT_TIMESTAMP)
    """)
    with pytest.raises(DataQualityError, match="uncertified candle rows present with NULL dataset_id"):
        pipeline.load_candles("SYM_NULL", "1d", require_authoritative_certification=True)


def test_pipeline_authoritative_dq_unverified_dataset_raises(clean_db, admitted_pit_candles):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=True)
    clean_db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id, created_at)
        VALUES ('SYM_UNV', '1003', 'NSE', '1d', CURRENT_TIMESTAMP, 100, 105, 95, 102, 1000, 'UNADJUSTED', 'angelone', 'DS_RAW', CURRENT_TIMESTAMP)
    """)
    clean_db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status)
        VALUES ('DS_RAW', 'SYM_UNV', 'SYM_UNV', 'NSE', '1d', 'angelone', 'h1', 'RAW_RECORDED', 'RAW_RECORDED')
    """)
    with pytest.raises(DataQualityError, match="must be VERIFIED and CANONICAL_PROMOTED"):
        pipeline.load_candles("SYM_UNV", "1d", require_authoritative_certification=True)


def test_pipeline_authoritative_dq_nohash_raises(clean_db, admitted_pit_candles):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=True)
    clean_db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id, created_at)
        VALUES ('SYM_NOHASH', '1004', 'NSE', '1d', CURRENT_TIMESTAMP, 100, 105, 95, 102, 1000, 'UNADJUSTED', 'angelone', 'DS_NOHASH', CURRENT_TIMESTAMP)
    """)
    clean_db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, transformation_hash, status, lifecycle_status)
        VALUES ('DS_NOHASH', 'SYM_NOHASH', 'SYM_NOHASH', 'NSE', '1d', 'angelone', '', '', 'VERIFIED', 'CANONICAL_PROMOTED')
    """)
    with pytest.raises(DataQualityError, match="has no immutable content hash"):
        pipeline.load_candles("SYM_NOHASH", "1d", require_authoritative_certification=True)


def test_pipeline_authoritative_dq_nocert_raises(clean_db, admitted_pit_candles):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=True)
    clean_db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id, created_at)
        VALUES ('SYM_NOCERT', '1005', 'NSE', '1d', CURRENT_TIMESTAMP, 100, 105, 95, 102, 1000, 'UNADJUSTED', 'angelone', 'DS_NOCERT', CURRENT_TIMESTAMP)
    """)
    clean_db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, transformation_hash, status, lifecycle_status)
        VALUES ('DS_NOCERT', 'SYM_NOCERT', 'SYM_NOCERT', 'NSE', '1d', 'angelone', 'hash_cert', 'hash_cert', 'VERIFIED', 'CANONICAL_PROMOTED')
    """)
    with pytest.raises(DataQualityError, match="lacks active CERTIFIED batch bound to hash"):
        pipeline.load_candles("SYM_NOCERT", "1d", require_authoritative_certification=True)


def test_pipeline_composed_frame_dq_integrity_violations(clean_db, admitted_pit_candles):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=True)

    clean_db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, transformation_hash, status, lifecycle_status)
        VALUES ('DS_OK', 'SYM_OHLC_BAD', 'SYM_OHLC_BAD', 'NSE', '1d', 'angelone', 'hash_ok', 'hash_ok', 'VERIFIED', 'CANONICAL_PROMOTED')
    """)
    clean_db.conn.execute("""
        INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
        VALUES ('CERT_1', 'DS_OK', 'v1.0', 6, 0, '{"dataset_content_hash": "hash_ok"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    for i, check in enumerate(["timestamp_integrity", "ohlc_integrity", "missing_sessions", "duplicates", "schema", "session_alignment"], start=1):
        clean_db.conn.execute("""
            INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id)
            VALUES (?, 'SYM_OHLC_BAD', '1d', 'DS_OK', ?, 0, '{}', CURRENT_TIMESTAMP, 'CERT_1')
        """, [1000 + i, check])

    # OHLC violation: high < low
    clean_db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id, created_at)
        VALUES ('SYM_OHLC_BAD', '1006', 'NSE', '1d', CURRENT_TIMESTAMP, 100, 90, 95, 102, 1000, 'UNADJUSTED', 'angelone', 'DS_OK', CURRENT_TIMESTAMP)
    """)
    with pytest.raises(DataQualityError, match="contains OHLC integrity violations"):
        pipeline.load_candles("SYM_OHLC_BAD", "1d", require_authoritative_certification=True)


def test_pipeline_trade_attribution_and_helpers(clean_db):
    pipeline = StrategyPipeline(db=clean_db, require_authoritative_certification=False)

    mock_result = MagicMock()
    mock_result.run_id = "run_attr_1"
    mock_result.symbol = "RELIANCE"
    mock_result.orders = pd.DataFrame([
        {"order_id": "o1", "symbol": "RELIANCE", "side": "BUY", "quantity": 10, "metadata_json": json.dumps({"reason": "TREND_ENTRY", "delta_position": 0.5})},
        {"order_id": "o2", "symbol": "RELIANCE", "side": "SELL", "quantity": 10, "metadata_json": json.dumps({"reason": "EXIT_TARGET", "delta_position": 0.0})},
    ])
    mock_result.fills = pd.DataFrame([
        {
            "fill_id": "f1", "order_id": "o1", "side": "BUY", "quantity": 10, "price": 100.0,
            "timestamp": "2026-01-01 09:15:00+05:30", "fees": 5.0,
            "metadata_json": json.dumps({"cost_components": {"total_cost": 5.0, "brokerage": 2.0, "stt": 2.0, "exchange_transaction": 0.5, "sebi": 0.1, "ipft": 0.0, "dp_charge": 0.0, "stamp_duty": 0.2, "gst": 0.2, "spread": 0.0, "slippage": 0.0, "market_impact": 0.0}}),
        },
        {
            "fill_id": "f2", "order_id": "o2", "side": "SELL", "quantity": 10, "price": 110.0,
            "timestamp": "2026-01-02 15:30:00+05:30", "fees": 6.0,
            "metadata_json": json.dumps({"cost_components": {"total_cost": 6.0, "brokerage": 2.0, "stt": 2.5, "exchange_transaction": 0.5, "sebi": 0.1, "ipft": 0.0, "dp_charge": 0.0, "stamp_duty": 0.3, "gst": 0.6, "spread": 0.0, "slippage": 0.0, "market_impact": 0.0}}),
        },
    ])

    model = ExecutionModel(spread_bps=2.0, slippage_bps=3.0)
    attr_df, rt_df, cost_df = pipeline._persist_single_asset_attribution(mock_result, model, persist=True)

    assert len(attr_df) == 2
    assert len(rt_df) == 1
    assert rt_df.iloc[0]["net_pnl"] == pytest.approx(100.0 - 5.0 - 6.0)
    assert len(cost_df) == 2

    # Helper coverage: lookup asset class
    clean_db.conn.execute("""
        INSERT INTO market_universe (symbol, exchange, asset_class, currency, timezone, session_open, session_close, tradable, lot_size, tick_size)
        VALUES ('TCS', 'NSE', 'INDIA_EQUITY', 'INR', 'Asia/Kolkata', '09:15', '15:30', TRUE, 1, 0.05)
    """)
    assert pipeline._lookup_asset_class(symbol="TCS", exchange="NSE") == AssetClass.INDIA_EQUITY
    assert pipeline._lookup_asset_class(symbol="UNKNOWN", exchange="BSE") == AssetClass.INDIA_EQUITY

    # Helper coverage: latest dataset id
    clean_db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, transformation_hash, status, lifecycle_status, retrieved_at)
        VALUES ('DS_TCS_1', 'TCS', 'TCS', 'NSE', '1d', 'angelone', 'hash1', 'hash1', 'VERIFIED', 'CANONICAL_PROMOTED', CURRENT_TIMESTAMP)
    """)
    assert pipeline._latest_dataset_id("TCS", "1d") == "DS_TCS_1"


def test_pipeline_apply_paper_risk(clean_db):
    risk_engine = RiskEngine()
    pipeline = StrategyPipeline(db=clean_db, risk_engine=risk_engine, require_authoritative_certification=False)

    mock_result = MagicMock()
    mock_result.run_id = "paper_risk_run"
    mock_result.orders = pd.DataFrame([
        {"order_id": "po1", "symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1500.0, "average_fill_price": 1500.0, "requested_at": "2026-01-01 09:20:00+00"},
        {"order_id": "po2", "symbol": "INFY", "side": "SELL", "quantity": 10, "price": 1550.0, "average_fill_price": 1550.0, "requested_at": "2026-01-01 15:15:00+00"},
    ])

    pipeline._apply_paper_risk(mock_result, starting_capital=100_000.0)
    decisions = clean_db.conn.execute("SELECT COUNT(*) FROM risk_decisions WHERE run_id = 'paper_risk_run'").fetchone()
    assert decisions is not None and decisions[0] >= 2


# =========================================================================
# Part 3: trading_stack/datasets.py branch coverage
# =========================================================================

def test_panel_builder_duplicates_and_failures(clean_db, monkeypatch):
    builder = SynchronizedPanelBuilder(db=clean_db, require_authoritative_certification=False)

    mock_bars = pd.DataFrame([
        {"symbol": "DUP_SYM", "timestamp": "2026-01-01 10:00:00", "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000, "dataset_id": "D1", "adjustment": "UNADJUSTED"},
        {"symbol": "DUP_SYM", "timestamp": "2026-01-01 10:00:00", "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000, "dataset_id": "D1", "adjustment": "UNADJUSTED"},
    ])
    monkeypatch.setattr(builder, "_load_bars", lambda *args, **kwargs: mock_bars)
    monkeypatch.setattr(builder, "_resolve_benchmark", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(builder, "_sector_map", lambda *args, **kwargs: {"DUP_SYM": "FINANCIAL_SERVICES"})

    with pytest.raises(ValueError, match="Synchronized panel contains duplicate symbol timestamps"):
        builder.build(["DUP_SYM"], "1d", benchmark_symbol=None)

    # PIT lookup failure fails closed
    monkeypatch.setattr(
        "trading_stack.datasets.filter_frame_by_pit",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("PIT index corrupt")),
    )
    with pytest.raises(RuntimeError, match="(Point-in-time universe lookup failed|Missing point-in-time constituent history)"):
        builder.build(["DUP_SYM"], "1d", benchmark_symbol=None, universe_snapshot_id="NIFTY200_CORRUPT")


def test_panel_builder_authoritative_certification_failures(clean_db, monkeypatch):
    auth_builder = SynchronizedPanelBuilder(db=clean_db, require_authoritative_certification=True)

    mock_panel = pd.DataFrame([
        {"symbol": "S1", "timestamp": "2026-01-01 10:00:00", "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000, "dataset_id": "DS_PANEL_BAD", "adjustment": "UNADJUSTED"},
    ])
    monkeypatch.setattr(auth_builder, "_load_bars", lambda *args, **kwargs: mock_panel)
    monkeypatch.setattr(auth_builder, "_resolve_benchmark", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(auth_builder, "_sector_map", lambda *args, **kwargs: {"S1": "FINANCIAL_SERVICES"})

    # 1. Unverified dataset in market_datasets
    clean_db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, transformation_hash, status, lifecycle_status)
        VALUES ('DS_PANEL_BAD', 'S1', 'S1', 'NSE', '1d', 'angelone', 'h1', 'h1', 'INVALID', 'RAW_RECORDED')
    """)
    with pytest.raises(PanelDataQualityError, match="must be VERIFIED and CANONICAL_PROMOTED"):
        auth_builder.build(["S1"], "1d", benchmark_symbol=None)

    # 2. Verified dataset without immutable hash
    clean_db.conn.execute("""
        UPDATE market_datasets
        SET status = 'VERIFIED', lifecycle_status = 'CANONICAL_PROMOTED', transformation_hash = '', raw_hash = ''
        WHERE dataset_id = 'DS_PANEL_BAD'
    """)
    with pytest.raises(PanelDataQualityError, match="has no immutable content hash"):
        auth_builder.build(["S1"], "1d", benchmark_symbol=None)

    # 3. Verified dataset with hash, but no certified DQ record
    clean_db.conn.execute("""
        UPDATE market_datasets
        SET transformation_hash = 'panel_hash_1', raw_hash = 'panel_hash_1'
        WHERE dataset_id = 'DS_PANEL_BAD'
    """)
    with pytest.raises(PanelDataQualityError, match="has no certified DQ evidence bound to content hash"):
        auth_builder.build(["S1"], "1d", benchmark_symbol=None)


# =========================================================================
# Part 4: Additional high-impact coverage boosts for >= 95% threshold
# =========================================================================

def test_promotion_missing_context_variations(clean_db, monkeypatch):
    engine = PromotionEngine(clean_db)
    clean_db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at)
        VALUES ('rev_empty_id', '', 'trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', TRUE, CURRENT_TIMESTAMP)
    """)
    mock_appr = MagicMock()
    monkeypatch.setenv("CODE_SHA", "sha_ctx")
    clean_db.conn.execute("""
        INSERT INTO foundation_certifications (
            foundation_certification_id, artifact_version, generated_at, status,
            code_sha, lineage_status, risk_policy_id, risk_policy_hash,
            gates_json, derived_flags_json, artifact_sha256, artifact_json, is_active, recorded_at
        ) VALUES ('fc_ctx', 'v1', CURRENT_TIMESTAMP, 'PASS', 'sha_ctx', 'PASS', 'CANONICAL_V1', 'hash_canon', '[]', '{}', 'art_hash', '{}', true, CURRENT_TIMESTAMP)
    """)

    # Missing run_id
    with pytest.raises(PermissionError, match="unresolvable authoritative context \\['run_id'\\]"):
        engine.assert_paper_authorized(
            run_id="", strategy_name="trend", approval_evidence=mock_appr,
            expected_evidence_hash="h1",
        )


def test_statistical_tests_reduce_execution_children():
    from experiments.statistical_tests import _aggregate_campaign_root_evidence

    root = {"trial_id": "root_1", "status": "PENDING"}

    # 1. No children -> returns root dict
    assert _aggregate_campaign_root_evidence(root, []) == root

    # 2. No successful children -> returns status=FAILED
    failed_children = [
        {"trial_id": "c1", "status": "FAILED", "metrics": {}},
        {"trial_id": "c2", "status": "ERROR", "metrics": {}},
    ]
    res_failed = _aggregate_campaign_root_evidence(root, failed_children)
    assert res_failed["status"] == "FAILED"

    # 3. Successful children with string metrics (valid and invalid json) and numeric values
    succ_children = [
        {
            "trial_id": "c1",
            "status": "SUCCEEDED",
            "metrics_json": json.dumps({"sharpe": 1.5, "max_drawdown": 0.10, "trade_count": 20, "other": "not_num"}),
        },
        {
            "trial_id": "c2",
            "status": "SUCCEEDED",
            "metrics": {"sharpe": 2.5, "max_drawdown": 0.20, "trade_count": 30, "empty_key": None},
        },
        {
            "trial_id": "c3",
            "status": "SUCCEEDED",
            "metrics_json": "{invalid_json_here",
        },
    ]
    res_succ = _aggregate_campaign_root_evidence(root, succ_children)
    assert res_succ["status"] == "SUCCEEDED"
    assert res_succ["child_evidence_aggregation"] == "ordered_successful_mean_v1"
    assert res_succ["metrics"]["sharpe"] == pytest.approx(2.0)
    assert res_succ["metrics"]["max_drawdown"] == pytest.approx(0.10)
    assert res_succ["metrics"]["trade_count"] == 50.0

    # 4. Partial success
    mixed_children = [
        {"trial_id": "c1", "status": "SUCCEEDED", "metrics": {"sharpe": 1.0}},
        {"trial_id": "c2", "status": "FAILED", "metrics": {}},
    ]
    res_mixed = _aggregate_campaign_root_evidence(root, mixed_children)
    assert res_mixed["status"] == "FAILED"


def test_datasets_pit_eligibility_and_alias_coverage(clean_db):
    from trading_stack.datasets import (
        _pit_alias_rows,
        _pit_eligibility_mask,
        filter_frame_by_pit,
    )

    # 1. _pit_alias_rows failure with required=True
    mock_db = MagicMock()
    mock_db.conn.execute.side_effect = RuntimeError("DB fail")
    with pytest.raises(RuntimeError, match="Required instrument alias history is unavailable"):
        _pit_alias_rows(mock_db, required=True)

    # 2. _pit_eligibility_mask when no rows and required=False -> returns True series
    test_frame = pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-01-05 10:00:00", tz="Asia/Kolkata")],
        "symbol": ["RELIANCE"],
        "close": [2500.0],
    })
    mask, _ = _pit_eligibility_mask(clean_db, test_frame, "UNIV_EMPTY", timezone_name="Asia/Kolkata", required=False)
    assert mask.all()

    # 3. _pit_eligibility_mask with incomplete knowledge fields
    clean_db.conn.execute("""
        INSERT INTO index_constituents_pit (universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from)
        VALUES ('UNIV_INCOMPLETE', 'I1', 'RELIANCE', '101', 'NSE', '2026-01-01', '2026-12-31', NULL)
    """)
    with pytest.raises(RuntimeError, match="incomplete knowledge-time fields"):
        _pit_eligibility_mask(clean_db, test_frame, "UNIV_INCOMPLETE", timezone_name="Asia/Kolkata", required=True, require_knowledge=True)

    # 4. Corrupt interval effective_from >= effective_until
    clean_db.conn.execute("""
        INSERT INTO index_constituents_pit (universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from)
        VALUES ('UNIV_CORRUPT', 'I2', 'RELIANCE', '102', 'NSE', '2026-12-31', '2026-01-01', '2026-01-01')
    """)
    with pytest.raises(RuntimeError, match="effective_from >= effective_until"):
        _pit_eligibility_mask(clean_db, test_frame, "UNIV_CORRUPT", timezone_name="Asia/Kolkata", required=True, require_knowledge=False)

    # 5. Overlapping intervals
    clean_db.conn.execute("""
        INSERT INTO index_constituents_pit (universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from)
        VALUES ('UNIV_OVERLAP', 'I3', 'RELIANCE', '103', 'NSE', '2026-01-01', '2026-06-30', '2026-01-01'),
               ('UNIV_OVERLAP', 'I3', 'RELIANCE', '103', 'NSE', '2026-05-01', '2026-12-31', '2026-01-01')
    """)
    with pytest.raises(RuntimeError, match="Overlapping point-in-time intervals"):
        _pit_eligibility_mask(clean_db, test_frame, "UNIV_OVERLAP", timezone_name="Asia/Kolkata", required=True, require_knowledge=False)

    # 6. Alias lacking snapshot bound
    clean_db.conn.execute("""
        INSERT INTO instrument_alias_history (
            alias_id, instrument_id, alias_symbol, exchange,
            valid_from, valid_until, snapshot_date, observed_snapshot_date,
            validity_basis, has_explicit_historical_interval, source_sha256,
            confidence, resolution_status
        ) VALUES (
            'a_bad', 'I4', 'RELIANCE', 'NSE',
            '2026-01-01', '2026-12-31', NULL, NULL,
            'CIRCULAR', FALSE, 'hash_src',
            'CERTIFIED', 'ACCEPTED'
        )
    """)
    clean_db.conn.execute("""
        INSERT INTO index_constituents_pit (universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from)
        VALUES ('UNIV_ALIAS_TEST', 'I4', 'RELIANCE', '104', 'NSE', '2026-01-01', '2026-12-31', '2026-01-01')
    """)
    clean_db.conn.execute("""
        INSERT INTO index_constituent_knowledge (universe_name, instrument_id, effective_from, known_at)
        VALUES ('UNIV_ALIAS_TEST', 'I4', '2026-01-01', '2026-01-01 00:00:00+05:30')
    """)
    with pytest.raises(RuntimeError, match="lacks a snapshot bound"):
        filter_frame_by_pit(clean_db, test_frame, "UNIV_ALIAS_TEST", required=True)

    # 7. Corrupt alias interval: snapshot > valid_until when has_explicit_historical_interval is False
    clean_db.conn.execute("DELETE FROM instrument_alias_history WHERE alias_id = 'a_bad'")
    clean_db.conn.execute("""
        INSERT INTO instrument_alias_history (
            alias_id, instrument_id, alias_symbol, exchange,
            valid_from, valid_until, snapshot_date, observed_snapshot_date,
            validity_basis, has_explicit_historical_interval, source_sha256,
            confidence, resolution_status
        ) VALUES (
            'a_corrupt', 'I4', 'RELIANCE', 'NSE',
            '2026-01-01', '2026-06-01', '2026-08-01', '2026-08-01',
            'CIRCULAR', FALSE, 'hash_src',
            'CERTIFIED', 'ACCEPTED'
        )
    """)
    with pytest.raises(RuntimeError, match="Corrupt instrument alias interval"):
        filter_frame_by_pit(clean_db, test_frame, "UNIV_ALIAS_TEST", required=True)

    # 8. Certified alias successfully resolved and filtered
    clean_db.conn.execute("DELETE FROM instrument_alias_history WHERE alias_id = 'a_corrupt'")
    clean_db.conn.execute("""
        INSERT INTO instrument_alias_history (
            alias_id, instrument_id, alias_symbol, exchange,
            valid_from, valid_until, snapshot_date, observed_snapshot_date,
            validity_basis, has_explicit_historical_interval, source_sha256,
            confidence, resolution_status
        ) VALUES (
            'a_ok', 'I4', 'RELIANCE', 'NSE',
            '2026-01-01', '2026-12-31', '2026-01-01', '2026-01-01',
            'CIRCULAR', TRUE, 'hash_src',
            'CERTIFIED', 'ACCEPTED'
        )
    """)
    filtered_df, pit_hash = filter_frame_by_pit(clean_db, test_frame, "UNIV_ALIAS_TEST", required=True)
    assert not filtered_df.empty
    assert pit_hash is not None
