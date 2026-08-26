"""Four-agent research workflow over deterministic project tools only."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ai_research.llm import LLMClient
from ai_research.models import AgentOutput, ResearchGoal
from experiments.manager import ExperimentManager
from experiments.models import ExperimentSpec
from orchestration.engine import TaskOrchestrator
from risk.engine import RiskEngine
from risk.models import RiskAction, RiskDecision, TradeProposal
from storage.duckdb_manager import DuckDBManager
from trading_stack.features import FeatureFactory


class ResearchWorkflow:
    """Coordinates analysts without exposing arbitrary code, SQL, or broker tools."""

    def __init__(self, db: DuckDBManager, llm: LLMClient, risk_engine: RiskEngine | None = None) -> None:
        self.db = db
        self.llm = llm
        self.risk_engine = risk_engine or RiskEngine()
        self.tasks = TaskOrchestrator(db)
        self.experiments = ExperimentManager(db)

    def run(self, goal: ResearchGoal, starting_capital: float = 100_000.0) -> dict[str, Any]:
        """Run manager, technical, quant, and risk roles with a complete audit trail."""

        if (
            hasattr(self.llm, "input_cost_per_million")
            and (
                getattr(self.llm, "input_cost_per_million") is None
                or getattr(self.llm, "output_cost_per_million") is None
            )
        ):
            raise RuntimeError(
                "OpenAI model pricing must be configured before running budgeted research agents."
            )
        self._spent_cost_usd = 0.0
        self._spent_tokens = 0

        _, data_context = self.tasks.run_task(
            goal_id=goal.goal_id,
            task_name="verified_data_snapshot",
            executor=lambda: self._data_context(goal),
            assigned_agent="research_manager",
            input_payload=goal.model_dump(mode="json"),
        )
        assert data_context is not None
        technical = self._run_agent(goal, "technical_analyst", data_context)
        _, experiment_result = self.tasks.run_task(
            goal_id=goal.goal_id,
            task_name="deterministic_backtest",
            executor=lambda: self.experiments.run(
                ExperimentSpec(
                    strategy_name=goal.strategy_name.lower(),
                    universe=[goal.symbol],
                    timeframe=goal.timeframe.lower(),
                    mode="event-driven",
                    parameters=goal.parameters,
                    llm_config={"model": self.llm.model_name},
                ),
                starting_capital=starting_capital,
            ),
            assigned_agent="quant_analyst",
            input_payload={"strategy": goal.strategy_name, "symbol": goal.symbol},
        )
        assert experiment_result is not None
        quant_context = self._experiment_context(experiment_result)
        quant = self._run_agent(goal, "quant_analyst", {**data_context, **quant_context})
        risk = self._authoritative_risk_decision(goal, starting_capital)
        self.db.log_risk_decision(risk.storage_payload(experiment_id=experiment_result["experiment_id"]))
        risk_output = self._run_agent(
            goal,
            "risk_analyst",
            {"risk_decision": risk.model_dump(mode="json"), **quant_context},
        )
        synthesis = self._run_agent(
            goal,
            "research_manager",
            {
                "technical": technical.model_dump(mode="json"),
                "quant": quant.model_dump(mode="json"),
                "risk": risk_output.model_dump(mode="json"),
                "paper_approved": goal.paper_approved,
            },
        )
        return {
            "goal_id": goal.goal_id,
            "technical": technical,
            "quant": quant,
            "risk": risk_output,
            "synthesis": synthesis,
            "experiment_id": experiment_result["experiment_id"],
            "paper_eligible": bool(goal.paper_approved and goal.paper_session_id and risk.approved_notional > 0),
        }

    def _authoritative_risk_decision(self, goal: ResearchGoal, starting_capital: float) -> RiskDecision:
        """Use an explicitly bound paper ledger or make the result non-executable."""
        if not goal.paper_session_id:
            return RiskDecision(
                symbol=goal.symbol, action=RiskAction.REJECT, requested_notional=starting_capital * 0.05,
                approved_notional=0.0, reasons=["MISSING_AUTHORITATIVE_PAPER_SESSION"], policy=self.risk_engine.policy,
            )
        row = self.db.conn.execute(
            """SELECT cash, quantity, peak_equity, daily_start_equity, last_processed_timestamp, status
               FROM paper_sessions WHERE session_id = ? AND symbol = ?""",
            [goal.paper_session_id, goal.symbol],
        ).fetchone()
        if not row or str(row[5]) != "ACTIVE" or row[4] is None:
            return RiskDecision(
                symbol=goal.symbol, action=RiskAction.REJECT, requested_notional=starting_capital * 0.05,
                approved_notional=0.0, reasons=["MISSING_OR_INACTIVE_AUTHORITATIVE_RISK_STATE"], policy=self.risk_engine.policy,
            )
        price_row = self.db.conn.execute(
            "SELECT close FROM historical_candles WHERE symbol = ? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
            [goal.symbol, row[4]],
        ).fetchone()
        if not price_row or float(price_row[0]) <= 0:
            return RiskDecision(
                symbol=goal.symbol, action=RiskAction.REJECT, requested_notional=starting_capital * 0.05,
                approved_notional=0.0, reasons=["MISSING_AUTHORITATIVE_MARK_PRICE"], policy=self.risk_engine.policy,
            )
        price = float(price_row[0])
        equity = float(row[0]) + float(row[1]) * price
        closes = self.db.conn.execute(
            "SELECT close FROM historical_candles WHERE symbol = ? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 21",
            [goal.symbol, row[4]],
        ).fetchall()
        if len(closes) < 21:
            return RiskDecision(
                symbol=goal.symbol, action=RiskAction.REJECT, requested_notional=starting_capital * 0.05,
                approved_notional=0.0, reasons=["INSUFFICIENT_AUTHORITATIVE_VAR_HISTORY"], policy=self.risk_engine.policy,
            )
        prices = [float(value[0]) for value in reversed(closes)]
        returns = [(prices[index] / prices[index - 1]) - 1.0 for index in range(1, len(prices))]
        mean = sum(returns) / len(returns)
        volatility = (sum((value - mean) ** 2 for value in returns) / len(returns)) ** 0.5
        turnover = self.db.conn.execute(
            "SELECT COALESCE(SUM(ABS(quantity * price)), 0) FROM strategy_fills WHERE run_id = ? AND CAST(timestamp AS DATE) = CAST(? AS DATE)",
            [goal.paper_session_id, row[4]],
        ).fetchone()
        return self.risk_engine.evaluate(TradeProposal(
            symbol=goal.symbol, requested_notional=equity * 0.05, capital=equity,
            current_position_notional=float(row[1]) * price,
            current_gross_exposure=abs(float(row[1]) * price),
            daily_pnl=equity - float(row[3] or equity),
            current_drawdown=max((float(row[2] or equity) - equity) / max(float(row[2] or equity), 1e-12), 0.0),
            current_sector_exposure=abs(float(row[1]) * price), open_position_count=int(abs(float(row[1])) > 0),
            daily_turnover_crore=float(turnover[0] or 0.0) / 10_000_000.0 if turnover else 0.0,
            estimated_portfolio_var_pct=1.65 * volatility,
        ))

    def _data_context(self, goal: ResearchGoal) -> dict[str, Any]:
        frame = self.db.get_candles(goal.symbol, goal.timeframe.lower())
        features = FeatureFactory().build(frame)
        latest = features.iloc[-1]
        return {
            "symbol": goal.symbol,
            "timeframe": goal.timeframe,
            "bars": len(features),
            "latest_close": float(latest["close"]),
            "trend_strength": float(latest["trend_strength"]),
            "volatility": float(latest["volatility"]),
            "data_source": "DuckDB canonical cache",
        }

    def _experiment_context(self, experiment_result: dict[str, Any]) -> dict[str, Any]:
        result = experiment_result["outcome"]["result"]
        return {"experiment_id": experiment_result["experiment_id"], "metrics": result.metrics.__dict__, "run_id": result.run_id}

    def _run_agent(self, goal: ResearchGoal, agent_name: str, context: dict[str, Any]) -> AgentOutput:
        prompt = json.dumps(
            {
                "goal": goal.model_dump(mode="json"),
                "context": context,
                "instructions": "Use only supplied context. Classify every claim. Do not claim unobserved prices or backtest results.",
            },
            default=str,
            sort_keys=True,
        )
        task_id = str(uuid.uuid4())
        agent_run_id = str(uuid.uuid4())
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        started_at = datetime.now(timezone.utc)
        self.db.log_agent_run(
            {
                "agent_run_id": agent_run_id,
                "task_id": task_id,
                "agent_name": agent_name,
                "model_name": self.llm.model_name,
                "status": "RUNNING",
                "prompt_hash": prompt_hash,
                "started_at": started_at,
            },
        )
        try:
            estimated_input_tokens = max(len(prompt) // 4, 1)
            remaining_tokens = goal.max_tokens - self._spent_tokens
            max_output_tokens = min(4_096, remaining_tokens - estimated_input_tokens)
            input_price = getattr(self.llm, "input_cost_per_million", None)
            output_price = getattr(self.llm, "output_cost_per_million", None)

            def invoke() -> dict[str, Any]:
                if remaining_tokens <= estimated_input_tokens:
                    raise RuntimeError("Research-agent token budget exhausted before request.")
                if input_price is not None and output_price is not None:
                    maximum_request_cost = (
                        estimated_input_tokens * float(input_price)
                        + max_output_tokens * float(output_price)
                    ) / 1_000_000
                    if self._spent_cost_usd + maximum_request_cost > goal.max_cost_usd:
                        raise RuntimeError("Research-agent maximum request cost exceeds the remaining budget.")
                completed = self.llm.complete(
                    agent_name, prompt, AgentOutput, max_output_tokens=max_output_tokens,
                )
                return {
                    "output": completed.model_dump(mode="json"),
                    "token_usage": int(getattr(self.llm, "last_token_usage", 0)),
                    "cost_usd": float(getattr(self.llm, "last_cost_usd", 0.0)),
                }

            _, task_output = self.tasks.run_task(
                goal_id=goal.goal_id,
                task_name=f"{agent_name}_analysis",
                executor=invoke,
                assigned_agent=agent_name,
                input_payload={"context_keys": sorted(context), "prompt_hash": prompt_hash},
                task_id=task_id,
            )
            if task_output is None:
                raise RuntimeError("Agent task completed without output.")
            output = AgentOutput.model_validate(task_output["output"])
            token_usage = int(task_output["token_usage"])
            cost_usd = float(task_output["cost_usd"])
            if self._spent_cost_usd + cost_usd > goal.max_cost_usd:
                raise RuntimeError("Research-agent cost budget exceeded.")
            self._spent_cost_usd += cost_usd
            self._spent_tokens += token_usage
            if self._spent_tokens > goal.max_tokens:
                raise RuntimeError("Research-agent token budget exceeded.")
            if output.asset == "UNKNOWN":
                output = output.model_copy(update={"asset": goal.symbol})
            self.db.log_agent_output(
                agent_run_id,
                output.model_dump_json(),
                json.dumps([claim.model_dump(mode="json") for claim in output.claims]),
            )
            self.db.log_agent_run(
                {
                    "agent_run_id": agent_run_id,
                    "task_id": task_id,
                    "agent_name": agent_name,
                    "model_name": self.llm.model_name,
                    "status": "SUCCEEDED",
                    "prompt_hash": prompt_hash,
                    "token_usage": token_usage,
                    "cost_usd": cost_usd,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                },
            )
            self.db.update_research_task(task_id, token_usage=token_usage, cost_usd=cost_usd)
            return output
        except Exception:
            self.db.log_agent_run(
                {
                    "agent_run_id": agent_run_id,
                    "task_id": task_id,
                    "agent_name": agent_name,
                    "model_name": self.llm.model_name,
                    "status": "FAILED",
                    "prompt_hash": prompt_hash,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                },
            )
            raise
