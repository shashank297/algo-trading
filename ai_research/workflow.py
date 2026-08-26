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
from risk.models import TradeProposal
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
        risk = self.risk_engine.evaluate(
            TradeProposal(
                symbol=goal.symbol,
                requested_notional=starting_capital * 0.05,
                capital=starting_capital,
                current_position_notional=0.0,
                current_gross_exposure=0.0,
                daily_pnl=0.0,
                current_drawdown=0.0,
                current_sector_exposure=0.0,
                open_position_count=0,
                daily_turnover_crore=0.0,
                estimated_portfolio_var_pct=0.01,
            ),
        )
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
            "paper_eligible": bool(goal.paper_approved and risk.approved_notional > 0),
        }

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
