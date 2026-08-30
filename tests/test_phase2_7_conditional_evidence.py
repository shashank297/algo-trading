from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from storage import DuckDBManager
from trading_stack.conditional_evidence import ConditionalEvidencePolicy, ConditionalEvidenceService


UTC = timezone.utc


def _db(path: str = ":memory:") -> DuckDBManager:
    db = DuckDBManager(path)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    db.conn.execute(
        """INSERT INTO strategy_runs
           (run_id,strategy_name,asset_class,symbol,timeframe,mode,parameters_json,data_hash,status,started_at,finished_at,starting_capital)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            "run",
            "trend_following",
            "EQUITY",
            "ABC",
            "1d",
            "event-driven",
            "{}",
            "data",
            "COMPLETED",
            start,
            start + timedelta(days=100),
            100000.0,
        ],
    )
    for day in range(40):
        stamp = start + timedelta(days=day + 1)
        db.conn.execute(
            "INSERT INTO strategy_equity_curve VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["run", stamp, 100000.0, 0.02, 0.01, 0.0, 0.0, "OUT_OF_SAMPLE", "f1" if day < 20 else "f2"],
        )
        db.conn.execute(
            "INSERT INTO walk_forward_trade_attribution VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["run", "f1" if day < 20 else "f2", stamp, "ABC", "BUY", "test", 100.0, 10.0, 1.0, 1.0, 110.0, 1.0, "TEST"],
        )
        db.conn.execute(
            "INSERT INTO market_regime_snapshots (regime_id,market,benchmark,context_type,as_of,decision_time,raw_regime,confidence,trend_score,volatility_score,breadth_score,stress_score,input_evidence_json,input_evidence_hash,model_version,policy_version,policy_hash,calendar_version,missing_evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                f"raw{day}",
                "NSE",
                "NIFTY",
                "EOD",
                stamp.date(),
                stamp,
                "BULL_LOW_VOL",
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                "{}",
                "h",
                "v",
                "p",
                "h",
                "cal",
                "[]",
                stamp,
            ],
        )
        db.conn.execute(
            "INSERT INTO regime_transition_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"rt{day}",
                "NSE",
                "NIFTY",
                "EOD",
                stamp,
                f"raw{day}",
                None,
                "BULL",
                stamp,
                1,
                1.0,
                "INITIALIZED",
                "test",
                "BULL",
                "p",
                "h",
                stamp,
            ],
        )
        db.conn.execute(
            "INSERT INTO asset_state_snapshots (asset_state_id,symbol,exchange,context_type,as_of,decision_time,behavior_cluster,cluster_confidence,eligibility,eligibility_reasons_json,features_json,input_evidence_manifest_json,input_evidence_hash,input_hashes_json,model_version,policy_version,policy_hash,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"as{day}",
                "ABC",
                "NSE",
                "EOD",
                stamp.date(),
                stamp,
                "TRENDING",
                1.0,
                "ELIGIBLE",
                "[]",
                "{}",
                "{}",
                "h",
                "{}",
                "v",
                "p",
                "h",
                stamp,
            ],
        )
    db.conn.execute(
        "INSERT INTO research_trials_log (trial_id,experiment_family_id,status,trial_json,metrics_json,created_at,finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "trial",
            "family",
            "SUCCEEDED",
            '{"strategy_version":"strategy-v1","data_hash":"data","cost_model_version":"cost-v1","cost_model_hash":"cost-hash"}',
            '{"run_id":"run"}',
            start,
            start + timedelta(days=100),
        ],
    )
    return db


def _global_row(db: DuckDBManager) -> tuple:
    return db.conn.execute(
        "SELECT evidence_hash,evidence_status,raw_conditional_metric,global_metric,shrinkage_weight,shrunk_metric,cost_model_version,cost_model_hash,strategy_version,total_cost,net_return FROM strategy_conditional_evidence WHERE aggregation_level='GLOBAL'"
    ).fetchone()


def test_t01_oos_only_rows() -> None:
    db = _db()
    ids = ConditionalEvidenceService(db).materialize("run")
    assert len(ids) == 4
    assert db.conn.execute("SELECT COUNT(*) FROM strategy_conditional_observations").fetchone()[0] == 40
    rows = db.list_phase2_7_conditional_evidence_at(datetime(2025, 1, 1, tzinfo=UTC))
    assert {row["aggregation_level"] for row in rows} == {"GLOBAL", "REGIME", "ASSET_CLUSTER", "REGIME_ASSET_CLUSTER"}


def test_t02_training_in_sample_exclusion() -> None:
    baseline = _db()
    ConditionalEvidenceService(baseline).materialize("run")
    expected = _global_row(baseline)[0]
    changed = _db()
    changed.conn.execute(
        "INSERT INTO strategy_equity_curve VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["run", datetime(2023, 1, 1, tzinfo=UTC), 100000.0, 99.0, 99.0, 0.0, 0.0, "IN_SAMPLE", "train"],
    )
    ConditionalEvidenceService(changed).materialize("run")
    assert _global_row(changed)[0] == expected


def test_t03_future_regime_mutation() -> None:
    db = _db()
    ids = ConditionalEvidenceService(db).materialize("run")
    future = datetime(2026, 1, 1, tzinfo=UTC)
    db.conn.execute(
        "UPDATE regime_transition_events SET operational_regime_after='BEAR' WHERE decision_time > ?", [future]
    )
    assert ConditionalEvidenceService(db).materialize("run") == ids


def test_t04_future_asset_state_mutation() -> None:
    db = _db()
    ids = ConditionalEvidenceService(db).materialize("run")
    future = datetime(2026, 1, 1, tzinfo=UTC)
    db.conn.execute("UPDATE asset_state_snapshots SET behavior_cluster='ILLIQUID' WHERE decision_time > ?", [future])
    assert ConditionalEvidenceService(db).materialize("run") == ids


def test_t05_available_at_cutoff() -> None:
    db = _db()
    ConditionalEvidenceService(db).materialize("run")
    assert not db.list_phase2_7_conditional_evidence_at(datetime(2024, 2, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        db.list_phase2_7_conditional_evidence_at(datetime(2025, 1, 1))


def test_t06_tiny_sample_insufficient() -> None:
    db = _db()
    ConditionalEvidenceService(
        db, ConditionalEvidencePolicy(minimum_observations=100, minimum_trades=0, minimum_folds=1, minimum_span_days=1)
    ).materialize("run")
    assert _global_row(db)[1] == "INSUFFICIENT_CONDITIONAL_EVIDENCE"


def test_t07_tiny_sample_shrinkage() -> None:
    db = _db()
    policy = ConditionalEvidencePolicy(
        minimum_observations=100, minimum_trades=0, minimum_folds=2, minimum_span_days=1, prior_observations=100
    )
    ConditionalEvidenceService(db, policy).materialize("run")
    row = db.conn.execute(
        "SELECT evidence_status, raw_conditional_metric, shrunk_metric FROM strategy_conditional_evidence WHERE aggregation_level='GLOBAL'"
    ).fetchone()
    assert row[0] == "INSUFFICIENT_CONDITIONAL_EVIDENCE"
    assert row[2] == pytest.approx(row[1])


def test_t08_large_sample_has_more_conditional_weight() -> None:
    large = _db()
    ConditionalEvidenceService(large, ConditionalEvidencePolicy(minimum_trades=0, prior_observations=100)).materialize(
        "run"
    )
    small = _db()
    small.conn.execute("DELETE FROM strategy_equity_curve WHERE timestamp > ?", [datetime(2024, 1, 6, tzinfo=UTC)])
    small.conn.execute(
        "DELETE FROM walk_forward_trade_attribution WHERE timestamp > ?", [datetime(2024, 1, 6, tzinfo=UTC)]
    )
    ConditionalEvidenceService(
        small,
        ConditionalEvidencePolicy(
            minimum_observations=1, minimum_trades=0, minimum_folds=1, minimum_span_days=1, prior_observations=100
        ),
    ).materialize("run")
    assert _global_row(large)[4] > _global_row(small)[4]


def test_t09_strategy_by_regime() -> None:
    db = _db()
    ConditionalEvidenceService(db).materialize("run")
    assert (
        db.conn.execute(
            "SELECT COUNT(*) FROM strategy_conditional_evidence WHERE aggregation_level='REGIME' AND market_regime='BULL'"
        ).fetchone()[0]
        == 1
    )


def test_t10_strategy_by_asset_cluster() -> None:
    db = _db()
    ConditionalEvidenceService(db).materialize("run")
    assert (
        db.conn.execute(
            "SELECT COUNT(*) FROM strategy_conditional_evidence WHERE aggregation_level='ASSET_CLUSTER' AND asset_cluster='TRENDING'"
        ).fetchone()[0]
        == 1
    )


def test_t11_strategy_regime_asset_and_granular_gate() -> None:
    db = _db()
    ConditionalEvidenceService(db, ConditionalEvidencePolicy(minimum_observations=50, minimum_trades=0)).materialize(
        "run"
    )
    row = db.conn.execute(
        "SELECT evidence_status FROM strategy_conditional_evidence WHERE aggregation_level='REGIME_ASSET_CLUSTER'"
    ).fetchone()
    assert row[0] == "INSUFFICIENT_CONDITIONAL_EVIDENCE"


def test_t12_execution_cost_effect() -> None:
    low = _db()
    ConditionalEvidenceService(low).materialize("run")
    high = _db()
    high.conn.execute("UPDATE walk_forward_trade_attribution SET cost=1000")
    ConditionalEvidenceService(high).materialize("run")
    assert _global_row(high)[10] < _global_row(low)[10]


def test_t13_deterministic_evidence_hash() -> None:
    left = _db()
    right = _db()
    ConditionalEvidenceService(left).materialize("run")
    ConditionalEvidenceService(right).materialize("run")
    assert _global_row(left)[0] == _global_row(right)[0]


def test_t14_changed_oos_result_changes_hash() -> None:
    left = _db()
    ConditionalEvidenceService(left).materialize("run")
    right = _db()
    right.conn.execute(
        "UPDATE strategy_equity_curve SET gross_return=.03 WHERE timestamp=(SELECT MIN(timestamp) FROM strategy_equity_curve)"
    )
    ConditionalEvidenceService(right).materialize("run")
    assert _global_row(left)[0] != _global_row(right)[0]


def test_t15_no_in_sample_fallback() -> None:
    db = _db()
    db.conn.execute("UPDATE strategy_equity_curve SET evidence_level='IN_SAMPLE'")
    with pytest.raises(ValueError, match="OUT_OF_SAMPLE"):
        ConditionalEvidenceService(db).materialize("run")


def test_t16_missing_regime_fails_closed() -> None:
    db = _db()
    db.conn.execute("DELETE FROM regime_transition_events")
    with pytest.raises(ValueError, match="Every OOS observation"):
        ConditionalEvidenceService(db).materialize("run")


def test_t17_missing_asset_state_fails_closed() -> None:
    db = _db()
    db.conn.execute("DELETE FROM asset_state_snapshots")
    with pytest.raises(ValueError, match="Every OOS observation"):
        ConditionalEvidenceService(db).materialize("run")


def test_t18_temporal_span_gate() -> None:
    db = _db()
    ConditionalEvidenceService(
        db, ConditionalEvidencePolicy(minimum_observations=1, minimum_trades=0, minimum_folds=1, minimum_span_days=1000)
    ).materialize("run")
    assert _global_row(db)[1] == "INSUFFICIENT_CONDITIONAL_EVIDENCE"


def test_t19_strategy_versions_are_isolated() -> None:
    first = _db()
    ConditionalEvidenceService(first).materialize("run")
    second = _db()
    second.conn.execute(
        "UPDATE research_trials_log SET trial_json=?",
        [
            json.dumps(
                {
                    "strategy_version": "strategy-v2",
                    "data_hash": "data",
                    "cost_model_version": "cost-v1",
                    "cost_model_hash": "cost-hash",
                }
            )
        ],
    )
    ConditionalEvidenceService(second).materialize("run")
    assert _global_row(first)[8] != _global_row(second)[8]


def test_t20_deterministic_rerun() -> None:
    db = _db()
    first = ConditionalEvidenceService(db).materialize("run")
    second = ConditionalEvidenceService(db).materialize("run")
    assert first == second
    assert db.conn.execute("SELECT COUNT(*) FROM strategy_conditional_evidence").fetchone()[0] == 4


def test_authoritative_cost_lineage_and_missing_lineage_fail_closed() -> None:
    db = _db()
    ConditionalEvidenceService(db).materialize("run")
    assert _global_row(db)[6:8] == ("cost-v1", "cost-hash")
    missing = _db()
    missing.conn.execute("UPDATE research_trials_log SET trial_json='{}'")
    with pytest.raises(ValueError, match="cost/data lineage"):
        ConditionalEvidenceService(missing).materialize("run")


def test_phase2_7_cli_is_read_only_end_to_end(tmp_path: Path) -> None:
    database = tmp_path / "phase27.duckdb"
    db = _db(str(database))
    ConditionalEvidenceService(db).materialize("run")
    protected = ("strategy_runs", "promotion_reviews", "strategy_orders", "paper_sessions")
    before = {table: db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in protected}
    db.close()
    result = subprocess.run(
        [
            sys.executable,
            "research.py",
            "--command",
            "strategy-regime-analysis",
            "--strategy",
            "trend_following",
            "--evidence-at",
            "2025-01-01T00:00:00+00:00",
            "--database-path",
            str(database),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    for field in (
        "strategy_version",
        "aggregation_level",
        "observation_count",
        "trade_count",
        "fold_count",
        "raw_conditional_metric",
        "global_metric",
        "effective_sample_size",
        "shrinkage_weight",
        "shrunk_metric",
        "evidence_status",
        "available_at",
        "evidence_hash",
        "cost_model_version",
        "cost_model_hash",
        "lineage_json",
    ):
        assert field in result.stdout
    reopened = DuckDBManager(str(database))
    after = {table: reopened.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in protected}
    assert after == before
