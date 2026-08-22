"""Tests for provider lineage, experiments, risk, orchestration, and agents."""

from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ai_research import FakeLLMClient, OpenAIResearchClient, ResearchGoal, ResearchWorkflow
from data_platform import BarRequest, DataPlatform, DatasetSnapshot, DuckDBCacheProvider, Instrument, PriceAdjustment, ProviderRegistry
from data_platform.providers import ProviderUnavailable
from data_platform.providers import OpenBBHttpProvider
from experiments import ExperimentManager, ExperimentSpec
from orchestration import TaskOrchestrator, TaskState
from risk import RiskEngine, RiskPolicy, TradeProposal
from storage.duckdb_manager import DuckDBManager
from trading_stack.backtest import VectorizedBacktester
from trading_stack.features import FeatureFactory
from trading_stack.pipeline import StrategyPipeline
from trading_stack.strategies import StrategyRegistry
from trading_stack.validation import time_split, walk_forward_windows


class StaticProvider:
    """Small provider fixture used to prove registry fallback behavior."""

    name = "static"

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        return DatasetSnapshot.from_bars(
            instrument=Instrument(
                canonical_symbol=request.symbol,
                exchange=request.exchange,
                provider_name=self.name,
                provider_symbol=request.provider_symbol or request.symbol,
            ),
            timeframe=request.timeframe,
            bars=self.frame,
            adjustment=request.adjustment,
            timezone_name=request.timezone,
            metadata={"fixture": True},
        )


class FailingProvider:
    name = "failing"

    def fetch_bars(self, request: BarRequest) -> DatasetSnapshot:
        raise RuntimeError("provider unavailable")


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def get(self, url: str, params: dict[str, object], timeout: int) -> FakeResponse:
        return FakeResponse(
            {
                "results": [
                    {
                        "date": "2026-08-10T09:15:00Z",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1000,
                    },
                ],
            },
        )


class ResearchPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DuckDBManager(str(Path(self.temp_dir.name) / "research.duckdb"))
        self.frame = self._bars(30)
        self.db.upsert_candles(self.frame, "NIFTY", "26000", "NSE", "1d", adjustment="UNADJUSTED", dataset_id="ds_nifty")
        self.db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_nifty', 'NIFTY', 'NIFTY', 'NSE', '1d', 'ANGEL', 'h1', 'VERIFIED', 'CANONICAL_PROMOTED');")
        self.db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_nifty', 'ds_nifty', 'validator-v1', 6, 0, '{}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
        for i, check in enumerate(["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"], start=1):
            self.db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (?, 'NIFTY', '1d', 'ds_nifty', ?, 0, '{}', CURRENT_TIMESTAMP, 'cert_nifty');", [i, check])

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_provider_fallback_records_provenance_and_alias(self) -> None:
        request = self._request()
        platform = DataPlatform(self.db, ProviderRegistry([FailingProvider(), StaticProvider(self.frame)], self.db))

        snapshot = platform.fetch_and_store(request)

        self.assertEqual(snapshot.provenance.provider_name, "static")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM market_datasets WHERE provider_name = 'static'").fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM raw_bar_observations").fetchone()[0], len(self.frame))
        statuses = self.db.conn.execute("SELECT status FROM provider_attempts ORDER BY started_at").fetchall()
        self.assertEqual([row[0] for row in statuses], ["FAILED", "SUCCEEDED"])
        alias = self.db.conn.execute("SELECT provider_symbol FROM instrument_aliases").fetchone()[0]
        self.assertEqual(alias, "NIFTY")

    def test_openbb_http_adapter_normalizes_without_openbb_dependency(self) -> None:
        snapshot = OpenBBHttpProvider("http://localhost:6900", session=FakeSession()).fetch_bars(self._request())

        self.assertEqual(snapshot.instrument.provider_name, "openbb")
        self.assertEqual(len(snapshot.bars), 1)
        self.assertEqual(snapshot.bars["timestamp"].dt.tz.zone if hasattr(snapshot.bars["timestamp"].dt.tz, "zone") else str(snapshot.bars["timestamp"].dt.tz), "UTC")

    def test_duckdb_cache_provider_returns_one_homogeneous_snapshot(self) -> None:
        snapshot = DuckDBCacheProvider(self.db).fetch_bars(self._request())

        self.assertEqual(snapshot.provenance.provider_name, "duckdb_cache")
        self.assertTrue(snapshot.provenance.metadata["legacy_provenance"])
        self.assertEqual(snapshot.provenance.adjustment, PriceAdjustment.UNADJUSTED)

    def test_duckdb_cache_rejects_materially_incomplete_interval(self) -> None:
        request = BarRequest(
            symbol="NIFTY", exchange="NSE", timeframe="1d",
            start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            end=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(ProviderUnavailable, "incomplete"):
            DuckDBCacheProvider(self.db).fetch_bars(request)

    def test_canonical_candles_reject_mixed_adjustments(self) -> None:
        with self.assertRaisesRegex(ValueError, "Cannot mix adjustment states"):
            self.db.upsert_candles(
                self.frame, "NIFTY", "26000", "NSE", "1d",
                adjustment="SPLIT_ADJUSTED", provider_name="fixture",
            )

    def test_risk_policy_returns_pass_modify_and_reject(self) -> None:
        engine = RiskEngine(RiskPolicy(max_position_pct=0.05, max_daily_loss_pct=0.005))
        base_state = {
            "current_gross_exposure": 0.0,
            "current_sector_exposure": 0.0,
            "daily_pnl": 0.0,
            "current_drawdown": 0.0,
            "open_position_count": 0,
            "daily_turnover_crore": 10.0,
            "estimated_portfolio_var_pct": 0.01,
        }
        passed = engine.evaluate(TradeProposal(symbol="NIFTY", requested_notional=1_000, capital=100_000, **base_state))
        modified = engine.evaluate(TradeProposal(symbol="NIFTY", requested_notional=10_000, capital=100_000, **base_state))
        rejected = engine.evaluate(TradeProposal(symbol="NIFTY", requested_notional=1_000, capital=100_000, **{**base_state, "daily_pnl": -1_000}))

        self.assertEqual(passed.action.value, "PASS")
        self.assertEqual(modified.action.value, "MODIFY")
        self.assertEqual(modified.approved_notional, 5_000)
        self.assertEqual(rejected.action.value, "REJECT")

    def test_experiment_persists_reproducibility_inputs(self) -> None:
        outcome = ExperimentManager(self.db, Path(__file__).resolve().parent.parent).run(
            ExperimentSpec(strategy_name="trend_following", universe=["NIFTY"], timeframe="1d"),
        )

        row = self.db.conn.execute(
            "SELECT status, data_hash, source_revision FROM experiments WHERE experiment_id = ?",
            [outcome["experiment_id"]],
        ).fetchone()
        self.assertEqual(row[0], "SUCCEEDED")
        self.assertTrue(row[1])
        self.assertTrue(row[2])
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM experiment_runs").fetchone()[0], 1)
        self.assertIsNotNone(outcome["outcome"]["result"].metrics.sortino)
        self.assertIsNotNone(outcome["outcome"]["result"].metrics.profit_factor)

    def test_task_retry_cancel_and_agent_workflow_are_auditable(self) -> None:
        orchestrator = TaskOrchestrator(self.db)
        attempts = {"count": 0}

        def flaky() -> dict[str, object]:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("retry once")
            return {"ok": True}

        task_id, output = orchestrator.run_task(goal_id="goal-1", task_name="retry", executor=flaky, max_retries=1)
        waiting_id, _ = orchestrator.run_task(
            goal_id="goal-1",
            task_name="approval",
            executor=lambda: {"unused": True},
            requires_approval=True,
        )
        orchestrator.cancel_task(waiting_id)
        self.assertEqual(output, {"ok": True})
        self.assertEqual(
            self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [task_id]).fetchone()[0],
            TaskState.SUCCEEDED.value,
        )
        self.assertEqual(
            self.db.conn.execute("SELECT state FROM research_tasks WHERE task_id = ?", [waiting_id]).fetchone()[0],
            TaskState.CANCELLED.value,
        )
        with self.assertRaisesRegex(ValueError, "SUCCEEDED"):
            orchestrator.cancel_task(task_id)

        responses = {
            role: {
                "agent": role,
                "asset": "NIFTY",
                "signal": "HOLD",
                "confidence": 0.5,
                "claims": [{"kind": "FACT", "statement": "Derived only from provided deterministic context.", "data_sources": ["DuckDB"]}],
                "risks": ["fixture"],
            }
            for role in ("technical_analyst", "quant_analyst", "risk_analyst", "research_manager")
        }
        report = ResearchWorkflow(self.db, FakeLLMClient(responses)).run(
            ResearchGoal(symbol="NIFTY", timeframe="1d", strategy_name="trend_following"),
        )
        self.assertFalse(report["paper_eligible"])
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM agent_runs WHERE status = 'SUCCEEDED'").fetchone()[0], 4)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM agent_outputs").fetchone()[0], 4)

    def test_task_timeout_is_enforced_before_callable_returns(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            TaskOrchestrator(self.db).run_task(
                goal_id="goal-timeout", task_name="bounded",
                executor=lambda: (time.sleep(0.2) or {"late": True}),
                timeout_seconds=0.05,
            )
        self.assertLess(time.monotonic() - started, 0.15)

    def test_real_agent_gateway_fails_closed_without_pricing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "pricing must be configured"):
            ResearchWorkflow(self.db, OpenAIResearchClient(client=object())).run(
                ResearchGoal(symbol="NIFTY", timeframe="1d"),
            )

    def test_validation_helpers_and_adjustment_guard_prevent_leakage(self) -> None:
        split = time_split(self.frame)
        windows = walk_forward_windows(self.frame, train_size=10, test_size=5)
        self.assertLess(split.train["timestamp"].max(), split.test["timestamp"].min())
        self.assertGreaterEqual(len(windows), 1)

        mixed = FeatureFactory().build(self.frame)
        mixed["adjustment"] = ["UNADJUSTED"] * (len(mixed) - 1) + ["SPLIT_ADJUSTED"]
        with self.assertRaisesRegex(ValueError, "cannot mix"):
            VectorizedBacktester().run(
                StrategyRegistry.create("trend_following"),
                mixed,
                symbol="NIFTY",
                timeframe="1d",
            )

    def test_paper_session_records_risk_before_reconciliation(self) -> None:
        self.db._replace_rows("promotion_reviews", [{
            "review_id": "paper-approval", "strategy_name": "trend_following",
            "run_id": "approved-run", "stage": "PAPER_ACTIVE", "decision": "PASS",
            "score": 1.0, "reasons_json": "[]", "human_approved": True,
            "reviewed_at": datetime.now(timezone.utc),
        }])
        outcome = StrategyPipeline(self.db, require_authoritative_certification=False).run_paper_session(
            strategy_name="trend_following",
            approved_run_id="approved-run",
            symbol="NIFTY",
            timeframe="1d",
        )

        self.assertIn("paper_summary", outcome)
        self.assertEqual(outcome["forward_result"].status, "BOOTSTRAPPED")
        self.assertIn("paper-forward:", outcome["forward_result"].session_id)
        self.assertEqual(len(outcome["forward_result"].fills), 0)
        self.assertEqual(outcome["paper_summary"]["filled_orders"], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM paper_reconciliation").fetchone()[0], 1)

    def _request(self) -> BarRequest:
        return BarRequest(
            symbol="NIFTY",
            exchange="NSE",
            timeframe="1d",
            start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end=datetime(2026, 9, 1, tzinfo=timezone.utc),
            adjustment=PriceAdjustment.UNADJUSTED,
        )

    @staticmethod
    def _bars(periods: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-08-01", periods=periods, freq="D", tz="UTC"),
                "open": [100 + index for index in range(periods)],
                "high": [101 + index for index in range(periods)],
                "low": [99 + index for index in range(periods)],
                "close": [100.5 + index for index in range(periods)],
                "volume": [1_000 + index for index in range(periods)],
            },
        )
