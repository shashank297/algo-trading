"""Regression test for AI research workflow risk state queries."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from ai_research.models import ResearchGoal
from ai_research.workflow import ResearchWorkflow
from risk.engine import RiskEngine
from risk.models import CanonicalRiskPolicy
from storage.duckdb_manager import DuckDBManager


def test_ai_workflow_evaluates_market_liquidity_not_strategy_fills(tmp_path):
    """If a stock has ₹25 crore in market volume but 0 strategy fills,
    it must NOT be rejected for insufficient_daily_liquidity.
    """
    db_path = str(tmp_path / "test_research.duckdb")
    db = DuckDBManager(db_path)

    as_of = datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc)
    # Insert paper session
    db.conn.execute("""
        INSERT INTO paper_sessions (
            session_id, strategy_name, strategy_version, symbol, timeframe,
            parameters_json, starting_capital, cash, quantity, peak_equity,
            daily_start_equity, last_processed_timestamp, status, created_at, updated_at
        ) VALUES (
            'sess-001', 'TestStrat', '1.0', 'RELIANCE', '1d',
            '{}', 100000.0, 100000.0, 0.0, 100000.0,
            100000.0, ?, 'ACTIVE', ?, ?
        )
    """, [as_of, as_of, as_of])

    # Insert 25 daily candles with high market volume (100,000 shares @ 2500 = ₹25 crore daily turnover)
    for i in range(25):
        t = datetime(2026, 8, 1 + i, 15, 30, tzinfo=timezone.utc)
        db.conn.execute("""
            INSERT INTO historical_candles (
                symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume
            ) VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, 2500.0, 2520.0, 2480.0, 2500.0, 100000)
        """, [t])

    policy = CanonicalRiskPolicy(
        policy_id="policy-1",
        policy_version="1.0.0",
        effective_from="2026-01-01",
        policy_hash="9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092",
        max_position_pct=0.05,
        max_gross_exposure_pct=1.0,
        max_daily_loss_pct=0.01,
        max_drawdown_pct=0.05,
        max_sector_exposure_pct=0.20,
        max_open_positions=10,
        min_liquidity_crore=5.0,  # Requires at least 5 crore daily turnover
        max_var_pct=0.05,
    )

    engine = RiskEngine(policy=policy.to_risk_policy())
    mock_llm = MagicMock()
    workflow = ResearchWorkflow(db=db, llm=mock_llm, risk_engine=engine)

    goal = ResearchGoal(
        goal_id="goal-1",
        hypothesis="Test hypothesis",
        target_universe="NIFTY200",
        symbol="RELIANCE",
        timeframe="1d",
        paper_session_id="sess-001",
    )

    decision = workflow._authoritative_risk_decision(goal, starting_capital=100000.0)
    # The market turnover is ₹25 crore, which is > 5 crore min_liquidity_crore.
    # But strategy_fills has 0 rows. In the defective code, daily_turnover_crore is 0.0,
    # so decision.action is REJECT with 'insufficient_daily_liquidity'.
    assert "insufficient_daily_liquidity" not in decision.reasons, f"Unexpected liquidity rejection: {decision.reasons}"
