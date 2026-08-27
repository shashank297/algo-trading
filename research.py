"""CLI entrypoint for strategy research, backtesting, and paper runs."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from main import apply_env_overrides, configured_nse_calendar, load_yaml, validate_config, validate_symbols
from ai_research import OpenAIResearchClient, ResearchGoal, ResearchWorkflow
from experiments import ExperimentManager, ExperimentSpec, MassExperimentManager, MassExperimentSpec
from risk.engine import RiskEngine
from risk.models import RiskPolicy
from storage import DuckDBManager
from trading_stack.pipeline import StrategyPipeline
from trading_stack.promotion import PromotionEngine
from trading_stack.rca import RCAEngine
from trading_stack.strategies import StrategyRegistry
from trading_stack.universe import UniverseResearchService
from utils import LoggerSetup

PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a strategy against stored market data.")
    parser.add_argument(
        "--command",
        default="backtest",
        choices=["backtest", "experiment", "portfolio-experiment", "mass-research", "agent-research", "paper", "rca", "promote", "inspect", "universe-status", "benchmark-register", "research-trials"],
        help="Workflow to run. Existing calls default to backtest.",
    )
    parser.add_argument("--strategy", default="trend_following", choices=StrategyRegistry.available())
    parser.add_argument("--strategies", default="", help="Comma-separated strategy names for mass research; defaults to --strategy.")
    parser.add_argument("--symbol", default=None, help="Trading symbol from config/symbols.yaml")
    parser.add_argument("--timeframe", default="1d", choices=["1m", "1d"], help="Target timeframe")
    parser.add_argument("--mode", default="vectorized", choices=["vectorized", "event-driven", "paper"], help="Execution mode")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Starting capital")
    parser.add_argument("--params", default="{}", help="JSON encoded strategy parameters")
    parser.add_argument("--costs", default="{}", help="JSON execution-cost model override")
    parser.add_argument("--goal", default="", help="Optional human-readable research goal")
    parser.add_argument("--paper-approved", action="store_true", help="Record human approval for paper eligibility only")
    parser.add_argument("--llm-model", default=None, help="OpenAI model for structured research agents")
    parser.add_argument("--universe", default="", help="Comma-separated symbols; defaults to configured equity symbols.")
    parser.add_argument("--universe-snapshot", default="CONFIGURED_UNIVERSE")
    parser.add_argument("--benchmark", default="NIFTY200")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--run-ids", default="", help="Comma-separated run IDs for RCA.")
    parser.add_argument("--run-id", default="", help="Run ID for promotion review.")
    parser.add_argument("--paper-activate", action="store_true", help="Activate an approved PAPER_CANDIDATE; never enables live trading.")
    parser.add_argument("--benchmark-provider", default="", help="Provider symbol used by benchmark-register.")
    parser.add_argument("--benchmark-relationship", default="EXACT", choices=["EXACT", "PROXY"])
    parser.add_argument("--benchmark-source", default="operator-configured")
    parser.add_argument("--approve-benchmark", action="store_true")
    parser.add_argument("--risk-override-max-pos", type=float, default=None, help="Override max position percentage in risk policy")
    parser.add_argument("--experiment-family-id", default=None, help="Experiment family ID for research trial registry")
    parser.add_argument("--trial-id", default=None, help="Research trial ID for inspection")
    parser.add_argument("--status", default=None, help="Filter research trials by status (e.g. PLANNED, RUNNING, SUCCEEDED, FAILED, INVALIDATED, CANCELLED)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = apply_env_overrides(load_yaml(str(PROJECT_ROOT / "config" / "config.yaml")))
    validate_config(config)
    symbols = validate_symbols(load_yaml(str(PROJECT_ROOT / "config" / "symbols.yaml")))
    symbol = args.symbol or str(symbols[0]["symbol"])
    configured_equities = [str(item["symbol"]) for item in symbols if str(item.get("instrument_type", "")).upper() == "EQUITY"]
    requested_universe = [value.strip().upper() for value in args.universe.split(",") if value.strip()]
    parameters: dict[str, Any] = json.loads(args.params)
    cost_model: dict[str, float] = json.loads(args.costs)
    research_config = config.get("research", {})
    project_logger = LoggerSetup.setup(config, component="research", command=args.command)
    started_at = time.perf_counter()
    project_logger.info("operation_started")

    db_path = Path(config["database"]["path"])
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path).resolve()
    db = DuckDBManager(str(db_path))
    try:
        if requested_universe:
            universe = requested_universe
        elif args.universe_snapshot != "CONFIGURED_UNIVERSE":
            rows = db.conn.execute(
                """
                SELECT provider_symbol
                FROM universe_snapshot_members
                WHERE snapshot_id = ?
                  AND active_to IS NULL
                  AND liquidity_eligible
                  AND data_eligible
                  AND paper_eligible
                  AND provider_symbol IS NOT NULL
                ORDER BY symbol
                """,
                [args.universe_snapshot],
            ).fetchall()
            universe = [str(row[0]) for row in rows]
            if not universe:
                raise ValueError(f"Universe snapshot has no eligible members: {args.universe_snapshot}")
        else:
            universe = configured_equities
        
        risk_policy_kwargs = research_config.get("risk", {})
        if args.risk_override_max_pos is not None:
            risk_policy_kwargs["max_position_pct"] = args.risk_override_max_pos
            
        risk_engine = RiskEngine(RiskPolicy(**risk_policy_kwargs))
        india_calendar = configured_nse_calendar(config)
        pipeline = StrategyPipeline(db, risk_engine=risk_engine, india_calendar=india_calendar)
        universe_service = UniverseResearchService(db)
        if args.command == "benchmark-register":
            if not args.benchmark_provider:
                parser.error("--benchmark-provider is required for benchmark-register")
            universe_service.register_benchmark(
                args.benchmark, args.benchmark_provider,
                relationship=args.benchmark_relationship,
                source=args.benchmark_source,
                approved_for_research=args.approve_benchmark,
            )
            print(json.dumps({
                "benchmark": args.benchmark, "provider_symbol": args.benchmark_provider,
                "relationship": args.benchmark_relationship, "approved": args.approve_benchmark,
            }, indent=2))
            return 0
        if args.command == "universe-status":
            if args.universe_snapshot == "CONFIGURED_UNIVERSE":
                raise ValueError("universe-status requires --universe-snapshot with an immutable snapshot ID.")
            readiness = universe_service.readiness(
                args.universe_snapshot, timeframe=args.timeframe, benchmark_symbol=args.benchmark,
            )
            print(json.dumps(readiness.as_dict(), default=str, indent=2))
            return 0
        if args.command == "research-trials":
            if args.trial_id:
                trial = db.get_research_trial(args.trial_id)
                if not trial:
                    raise ValueError(f"Research trial '{args.trial_id}' not found.")
                print(json.dumps(trial, default=str, indent=2))
                return 0
            if args.experiment_family_id:
                summary = db.research_trial_summary(args.experiment_family_id)
                trials = db.list_research_trials(
                    family_id=args.experiment_family_id,
                    strategy=args.strategy if args.strategy != "trend_following" or (argv and "--strategy" in argv) else None,
                    status=args.status,
                )
                print(json.dumps({
                    "family_id": args.experiment_family_id,
                    "summary": summary,
                    "trials": trials,
                }, default=str, indent=2))
                return 0
            families = db.list_experiment_families()
            trials = db.list_research_trials(
                family_id=None,
                strategy=args.strategy if args.strategy != "trend_following" or (argv and "--strategy" in argv) else None,
                status=args.status,
            )
            print(json.dumps({
                "families": families,
                "trials": trials,
                "total_families": len(families),
                "total_trials": len(trials),
            }, default=str, indent=2))
            return 0
        if args.command == "inspect":
            rows = db.conn.execute(
                """
                SELECT experiment_id, strategy_name, status, started_at, finished_at
                FROM experiments ORDER BY started_at DESC LIMIT 20
                """,
            ).fetchall()
            print(json.dumps({"experiments": rows}, default=str, indent=2))
            return 0
        if args.command == "rca":
            run_ids = [value.strip() for value in args.run_ids.split(",") if value.strip()]
            report = RCAEngine(db).analyze(run_ids)
            print(json.dumps({
                "analysis_id": report.analysis_id,
                "effective_independent_bets": report.effective_independent_bets,
                "correlations": report.correlations.to_dict(orient="records"),
                "strategy_summary": report.strategy_summary.to_dict(orient="records"),
            }, default=str, indent=2))
            return 0
        if args.command == "promote":
            review = PromotionEngine(db).review(
                args.run_id,
                human_approved=args.paper_approved,
                paper_activation=args.paper_activate,
            )
            print(json.dumps(review, default=str, indent=2))
            return 0
        if args.command == "mass-research":
            strategy_names = [value.strip() for value in args.strategies.split(",") if value.strip()] or [args.strategy]
            mass_result = MassExperimentManager(db, india_calendar).run(
                MassExperimentSpec(
                    strategy_names=strategy_names, universe=universe, timeframe=args.timeframe,
                    mode=args.mode, universe_snapshot_id=args.universe_snapshot,
                    benchmark_symbol=args.benchmark or None,
                    parameters={name: parameters for name in strategy_names},
                    cost_model=cost_model or research_config.get("indian_delivery_costs", {}),
                    cost_model_version=str(research_config.get("indian_delivery_costs", {}).get("version", "angel-nse-delivery-2026-04")),
                    max_workers=args.max_workers,
                    experiment_family_id=args.experiment_family_id,
                ),
                starting_capital=args.capital,
            )
            print(json.dumps(mass_result, default=str, indent=2))
            return 0
        if args.command == "agent-research":
            workflow = ResearchWorkflow(
                db,
                OpenAIResearchClient(
                    args.llm_model or research_config.get("openai_model", "gpt-5-mini"),
                    timeout_seconds=float(research_config.get("agent_timeout_seconds", 30)),
                    input_cost_per_million=research_config.get("openai_input_cost_per_million"),
                    output_cost_per_million=research_config.get("openai_output_cost_per_million"),
                ),
                risk_engine=risk_engine,
            )
            agent_result = workflow.run(
                ResearchGoal(
                    symbol=symbol,
                    timeframe=args.timeframe,
                    strategy_name=args.strategy,
                    parameters=parameters,
                    max_cost_usd=float(research_config.get("agent_max_cost_usd", 1.0)),
                    max_tokens=int(research_config.get("agent_max_tokens", 20_000)),
                    paper_approved=args.paper_approved,
                ),
                starting_capital=args.capital,
            )
            print(json.dumps(agent_result, default=lambda value: value.model_dump(mode="json"), indent=2))
            return 0
        if args.command in {"experiment", "portfolio-experiment"}:
            experiment_universe = universe if args.command == "portfolio-experiment" else [symbol]
            if args.command == "portfolio-experiment" and args.universe_snapshot != "CONFIGURED_UNIVERSE":
                readiness = universe_service.readiness(
                    args.universe_snapshot, timeframe=args.timeframe, benchmark_symbol=args.benchmark,
                    minimum_bars=StrategyRegistry.metadata(args.strategy).required_lookback,
                )
                if not readiness.ready:
                    raise ValueError(f"Universe is not research-ready: {', '.join(readiness.blockers)}")
            experiment_costs = cost_model or (
                research_config.get("indian_delivery_costs", {})
                if args.command == "portfolio-experiment"
                else research_config.get("costs", {})
            )
            experiment = ExperimentManager(db, india_calendar=india_calendar).run(
                ExperimentSpec(
                    strategy_name=args.strategy,
                    universe=experiment_universe,
                    timeframe=args.timeframe,
                    mode=args.mode,
                    parameters=parameters,
                    cost_model=experiment_costs,
                    universe_snapshot_id=args.universe_snapshot,
                    benchmark_symbol=args.benchmark or None,
                    experiment_family_id=args.experiment_family_id,
                ),
                starting_capital=args.capital,
            )
            outcome = experiment["outcome"]
        elif args.command == "paper" or args.mode == "paper":
            if not args.run_id:
                raise ValueError("Forward paper sessions require --run-id for a human-approved PAPER_CANDIDATE or PAPER_ACTIVE run.")
            outcome = pipeline.run_paper_session(
                strategy_name=args.strategy,
                approved_run_id=args.run_id,
                symbol=symbol,
                timeframe=args.timeframe,
                universe=universe,
                universe_snapshot_id=args.universe_snapshot,
                benchmark_symbol=args.benchmark,
                parameters=parameters,
                starting_capital=args.capital,
                cost_model=cost_model or research_config.get("indian_delivery_costs", {}),
            )
        else:
            outcome = pipeline.run(
                strategy_name=args.strategy,
                symbol=symbol,
                timeframe=args.timeframe,
                mode=args.mode,
                parameters=parameters,
                starting_capital=args.capital,
                cost_model=cost_model or research_config.get("costs", {}),
            )
        if "forward_result" in outcome:
            forward = outcome["forward_result"]
            print(json.dumps({
                "session_id": forward.session_id, "status": forward.status,
                "strategy": forward.strategy_name, "symbol": forward.symbol,
                "timeframe": forward.timeframe, "processed_bars": forward.processed_bars,
                "orders": len(forward.orders), "fills": len(forward.fills),
                "cash": forward.cash, "quantity": forward.quantity, "equity": forward.equity,
                "pending_signal_timestamp": forward.pending_signal_timestamp,
                "paper_summary": forward.paper_summary,
            }, default=str, indent=2))
            return 0
        if "forward_portfolio_result" in outcome:
            forward = outcome["forward_portfolio_result"]
            print(json.dumps({
                "session_id": forward.session_id, "status": forward.status,
                "strategy": forward.strategy_name,
                "universe_snapshot_id": forward.universe_snapshot_id,
                "timeframe": forward.timeframe,
                "processed_sessions": forward.processed_sessions,
                "orders": len(forward.orders), "fills": len(forward.fills),
                "cash": forward.cash, "holdings": forward.holdings,
                "equity": forward.equity,
                "pending_signal_timestamp": forward.pending_signal_timestamp,
                "paper_summary": forward.paper_summary,
            }, default=str, indent=2))
            return 0
        result = outcome["result"]
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "strategy": result.strategy_name,
                    "symbol": result.symbol,
                    "timeframe": result.timeframe,
                    "mode": result.mode,
                    "metrics": result.metrics.__dict__,
                    "orders": len(result.orders),
                    "fills": len(result.fills),
                    "equity_end": float(result.equity_curve["equity"].iloc[-1]),
                    "paper_summary": outcome.get("paper_summary"),
                },
                default=str,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        project_logger.error("operation_failed error_type={} error={}", type(exc).__name__, str(exc))
        raise
    finally:
        db.close()
        project_logger.info("operation_finished duration_seconds={:.3f}", time.perf_counter() - started_at)


if __name__ == "__main__":
    raise SystemExit(main())
