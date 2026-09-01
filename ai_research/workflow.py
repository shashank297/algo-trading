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
        self.experiments = ExperimentManager(db, risk_engine=self.risk_engine)

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
            "paper_eligible": bool(
                goal.paper_approved
                and (goal.paper_session_id or goal.paper_portfolio_session_id)
                and risk.approved_notional > 0
            ),
        }

    def _authoritative_risk_decision(self, goal: ResearchGoal, starting_capital: float) -> RiskDecision:
        """Use an explicitly bound paper ledger or make the result non-executable."""
        if goal.paper_portfolio_session_id:
            return self._portfolio_risk_decision(goal, starting_capital)
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

    def _portfolio_risk_decision(self, goal: ResearchGoal, starting_capital: float) -> RiskDecision:
        """Evaluate an AI proposal against all persisted holdings in a portfolio session."""
        session_id = str(goal.paper_portfolio_session_id)
        session = self.db.conn.execute(
            """SELECT cash, peak_equity, daily_start_equity, last_processed_timestamp, status, universe_snapshot_id
               FROM paper_portfolio_sessions WHERE session_id = ?""",
            [session_id],
        ).fetchone()
        if not session or str(session[4]) != "ACTIVE" or session[3] is None:
            return self._reject_authoritative(goal, starting_capital, "MISSING_OR_INACTIVE_AUTHORITATIVE_PORTFOLIO_STATE")
        holdings = self.db.conn.execute(
            "SELECT symbol, quantity FROM paper_portfolio_holdings WHERE session_id = ? AND quantity <> 0",
            [session_id],
        ).fetchall()
        symbols = {goal.symbol, *(str(row[0]) for row in holdings)}
        marks = self._authoritative_marks(symbols, session[3])
        if marks is None:
            return self._reject_authoritative(goal, starting_capital, "MISSING_AUTHORITATIVE_PORTFOLIO_MARK_PRICE")
        sectors = self._authoritative_sectors(symbols, str(session[5]))
        if sectors is None:
            return self._reject_authoritative(goal, starting_capital, "MISSING_AUTHORITATIVE_SECTOR_STATE")
        quantities = {str(symbol): float(quantity) for symbol, quantity in holdings}
        gross_exposure = sum(abs(quantity * marks[symbol]) for symbol, quantity in quantities.items())
        sector_exposure = sum(
            abs(quantity * marks[symbol]) for symbol, quantity in quantities.items()
            if sectors[symbol] == sectors[goal.symbol]
        )
        equity = float(session[0]) + sum(quantity * marks[symbol] for symbol, quantity in quantities.items())
        if equity <= 0:
            return self._reject_authoritative(goal, starting_capital, "NON_POSITIVE_AUTHORITATIVE_PORTFOLIO_EQUITY")
        volatility = self._portfolio_volatility(quantities, marks, session[3])
        if volatility is None:
            return self._reject_authoritative(goal, starting_capital, "INSUFFICIENT_AUTHORITATIVE_PORTFOLIO_VAR_HISTORY")
        turnover = self.db.conn.execute(
            """SELECT COALESCE(SUM(ABS(quantity * price)), 0) FROM strategy_fills
               WHERE run_id = ? AND CAST(timestamp AS DATE) = CAST(? AS DATE)""",
            [session_id, session[3]],
        ).fetchone()
        peak = float(session[1] or equity)
        return self.risk_engine.evaluate(TradeProposal(
            symbol=goal.symbol,
            requested_notional=equity * 0.05,
            capital=equity,
            current_position_notional=quantities.get(goal.symbol, 0.0) * marks[goal.symbol],
            current_gross_exposure=gross_exposure,
            daily_pnl=equity - float(session[2] or equity),
            current_drawdown=max((peak - equity) / max(peak, 1e-12), 0.0),
            current_sector_exposure=sector_exposure,
            open_position_count=len(quantities),
            daily_turnover_crore=float(turnover[0] or 0.0) / 10_000_000.0 if turnover is not None else 0.0,
            estimated_portfolio_var_pct=1.65 * volatility,
        ))

    def _reject_authoritative(self, goal: ResearchGoal, capital: float, reason: str) -> RiskDecision:
        return RiskDecision(
            symbol=goal.symbol, action=RiskAction.REJECT, requested_notional=capital * 0.05,
            approved_notional=0.0, reasons=[reason], policy=self.risk_engine.policy,
        )

    def _authoritative_marks(self, symbols: set[str], as_of: Any) -> dict[str, float] | None:
        marks: dict[str, float] = {}
        for symbol in symbols:
            row = self.db.conn.execute(
                "SELECT close FROM historical_candles WHERE symbol = ? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
                [symbol, as_of],
            ).fetchone()
            if not row or float(row[0]) <= 0:
                return None
            marks[symbol] = float(row[0])
        return marks

    def _authoritative_sectors(self, symbols: set[str], snapshot_id: str) -> dict[str, str] | None:
        rows = self.db.conn.execute(
            "SELECT symbol, sector FROM universe_snapshot_members WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchall()
        sectors = {str(symbol): str(sector) for symbol, sector in rows if sector and str(sector) != "UNKNOWN"}
        return sectors if symbols.issubset(sectors) else None

    def _portfolio_volatility(
        self, quantities: dict[str, float], marks: dict[str, float], as_of: Any,
    ) -> float | None:
        active = {symbol: quantity for symbol, quantity in quantities.items() if quantity != 0}
        if not active:
            return None
        rows = self.db.conn.execute(
            """SELECT symbol, timestamp, close FROM historical_candles
               WHERE symbol IN (SELECT UNNEST(?)) AND timestamp <= ? ORDER BY timestamp DESC""",
            [list(active), as_of],
        ).fetchall()
        series: dict[str, list[float]] = {symbol: [] for symbol in active}
        for symbol, _, close in rows:
            values = series[str(symbol)]
            if len(values) < 21:
                values.append(float(close))
        if any(len(values) < 21 for values in series.values()):
            return None
        weights_total = sum(abs(quantity * marks[symbol]) for symbol, quantity in active.items())
        returns = [0.0] * 20
        for symbol, quantity in active.items():
            prices = list(reversed(series[symbol]))
            weight = abs(quantity * marks[symbol]) / weights_total
            for index in range(1, 21):
                returns[index - 1] += weight * ((prices[index] / prices[index - 1]) - 1.0)
        mean = sum(returns) / len(returns)
        return (sum((value - mean) ** 2 for value in returns) / len(returns)) ** 0.5

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
