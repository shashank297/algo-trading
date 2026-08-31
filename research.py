"""CLI entrypoint for strategy research, backtesting, and paper runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from main import apply_env_overrides, configured_nse_calendar, load_yaml, validate_config, validate_symbols
from ai_research import OpenAIResearchClient, ResearchGoal, ResearchWorkflow
from experiments import (
    ExperimentManager,
    ExperimentSpec,
    MassExperimentManager,
    MassExperimentSpec,
    RobustnessEvaluator,
    RobustnessPolicy,
)

from data_platform.universe import PointInTimeUniverseManager
from risk.engine import RiskEngine
from risk.models import RiskPolicy
from storage import DuckDBManager
from trading_stack.domain import StrategyScope
from trading_stack.pipeline import StrategyPipeline
from trading_stack.promotion import PromotionEngine
from trading_stack.rca import RCAEngine
from trading_stack.strategies import StrategyRegistry
from trading_stack.universe import UniverseResearchService

from utils import LoggerSetup


PROJECT_ROOT = Path(__file__).resolve().parent


def _list_phase2_7_conditional_evidence_read_only(
    db_path: Path, decision_time: datetime, *, strategy_name: str | None = None
) -> list[dict[str, Any]]:
    if pd.Timestamp(decision_time).tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    conn = duckdb.connect(database=str(db_path), read_only=True)
    try:
        query = "SELECT * FROM strategy_conditional_evidence WHERE available_at <= ?"
        params: list[Any] = [decision_time]
        if strategy_name is not None:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        return conn.execute(query + " ORDER BY available_at, evidence_id", params).fetchdf().to_dict("records")
    finally:
        conn.close()


def _list_phase2_8_to_2_10_read_only(
    db_path: Path,
    table: str,
    decision_time: datetime,
    *,
    horizon: str | None = None,
    strategy_name: str | None = None,
) -> list[dict[str, Any]]:
    if pd.Timestamp(decision_time).tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    allowed_tables = {
        "strategy_scorecards": "available_at",
        "selector_decisions": "decision_time",
        "meta_selector_runs": "available_at",
    }
    if table not in allowed_tables:
        raise ValueError(f"Unsupported read-only Phase 2.8-2.10 table: {table}")
    cutoff_column = allowed_tables[table]
    conn = duckdb.connect(database=str(db_path), read_only=True)
    try:
        query = f"SELECT * FROM {table} WHERE {cutoff_column} <= ?"
        params: list[Any] = [decision_time]
        if horizon is not None and table in {"strategy_scorecards", "selector_decisions"}:
            query += " AND horizon = ?"
            params.append(horizon)
        if strategy_name is not None and table == "strategy_scorecards":
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        return conn.execute(query + f" ORDER BY {cutoff_column}", params).fetchdf().to_dict("records")
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a strategy against stored market data.")
    parser.add_argument(
        "--command",
        default="backtest",
        choices=[
            "backtest",
            "experiment",
            "portfolio-experiment",
            "mass-research",
            "agent-research",
            "paper",
            "rca",
            "promote",
            "inspect",
            "universe-status",
            "benchmark-register",
            "research-trials",
            # Phase 2.2 — Multi-timeframe data
            "build-derived-bars",
            "verify-market-provider",
            # Phase 2.3 — Market context & regime
            "market-regime",
            # Phase 2.6 — Statistical research framework
            "robustness",
            "strategy-regime-analysis",
            "strategy-scorecards",
            "selector-decisions",
            "meta-selector-runs",
        ],
        help="Workflow to run. Existing calls default to backtest.",
    )
    parser.add_argument("--strategy", default="trend_following", choices=StrategyRegistry.available())
    parser.add_argument(
        "--strategies", default="", help="Comma-separated strategy names for mass research; defaults to --strategy."
    )
    parser.add_argument("--symbol", default=None, help="Trading symbol from config/symbols.yaml")
    parser.add_argument(
        "--timeframe", default="1d", choices=["1m", "5m", "15m", "30m", "60m", "1d"], help="Target timeframe"
    )
    parser.add_argument(
        "--mode", default="vectorized", choices=["vectorized", "event-driven", "paper"], help="Execution mode"
    )
    parser.add_argument("--capital", type=float, default=100_000.0, help="Starting capital")
    parser.add_argument("--params", default="{}", help="JSON encoded strategy parameters")
    parser.add_argument("--costs", default="{}", help="JSON execution-cost model override")
    parser.add_argument("--goal", default="", help="Optional human-readable research goal")
    parser.add_argument(
        "--paper-approved", action="store_true", help="Record human approval for paper eligibility only"
    )
    parser.add_argument("--llm-model", default=None, help="OpenAI model for structured research agents")
    parser.add_argument(
        "--universe", default="", help="Comma-separated symbols; defaults to configured equity symbols."
    )
    parser.add_argument("--universe-snapshot", default="CONFIGURED_UNIVERSE")
    parser.add_argument("--benchmark", default="NIFTY200")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--run-ids", default="", help="Comma-separated run IDs for RCA.")
    parser.add_argument("--run-id", default="", help="Run ID for promotion review.")
    parser.add_argument(
        "--paper-activate",
        action="store_true",
        help="Activate an approved PAPER_CANDIDATE; never enables live trading.",
    )
    parser.add_argument("--benchmark-provider", default="", help="Provider symbol used by benchmark-register.")
    parser.add_argument("--benchmark-relationship", default="EXACT", choices=["EXACT", "PROXY"])
    parser.add_argument("--benchmark-source", default="operator-configured")
    parser.add_argument("--approve-benchmark", action="store_true")
    parser.add_argument(
        "--risk-override-max-pos", type=float, default=None, help="Override max position percentage in risk policy"
    )
    parser.add_argument("--experiment-family-id", default=None, help="Experiment family ID for research trial registry")
    parser.add_argument("--trial-id", default=None, help="Research trial ID for inspection")
    parser.add_argument(
        "--status",
        default=None,
        help="Filter research trials by status (e.g. PLANNED, RUNNING, SUCCEEDED, FAILED, INVALIDATED, CANCELLED)",
    )
    # Phase 2.2 — Multi-timeframe data
    parser.add_argument("--source-dataset", default=None, help="Canonical source dataset_id for build-derived-bars")
    parser.add_argument(
        "--derived-timeframe",
        default=None,
        choices=["5m", "15m", "30m", "60m"],
        help="Deprecated alias for --timeframe when building derived bars",
    )
    parser.add_argument(
        "--primary-provider", default=None, help="Primary (canonical) provider name for verify-market-provider"
    )
    parser.add_argument(
        "--secondary-provider", default=None, help="Secondary (observational) provider name for verify-market-provider"
    )
    parser.add_argument(
        "--primary-dataset", default=None, help="Canonical primary dataset_id for verify-market-provider"
    )
    parser.add_argument(
        "--secondary-dataset", default=None, help="Observational secondary dataset_id for verify-market-provider"
    )
    parser.add_argument(
        "--verification-severity",
        default="WARNING",
        choices=["WARNING", "BLOCKING"],
        help="How to handle provider disagreements",
    )
    parser.add_argument("--start-date", default=None, help="Start date for data range (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="End date for data range (YYYY-MM-DD)")
    # Phase 2.3 — Market context & regime
    parser.add_argument("--as-of", default=None, help="As-of evaluation date for market-regime (YYYY-MM-DD)")
    parser.add_argument(
        "--context", default="EOD", choices=["EOD", "INTRADAY"], help="Context type for market-regime (EOD or INTRADAY)"
    )
    parser.add_argument("--decision-time", default=None, help="Point-in-time decision ISO timestamp for market-regime")
    parser.add_argument("--market", default="NSE", help="Market identifier for market-regime (default: NSE)")
    # Phase 2.6 — Statistical research framework
    parser.add_argument("--robustness-id", default=None, help="Robustness evaluation ID for inspection")
    parser.add_argument("--purge-window", type=int, default=None, help="Purge window in bars for nested walk-forward")
    parser.add_argument(
        "--embargo-window", type=int, default=None, help="Embargo window in bars for nested walk-forward"
    )
    parser.add_argument(
        "--evidence-at", default=None, help="Causal evidence cutoff ISO timestamp for strategy-regime-analysis"
    )
    parser.add_argument("--database-path", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_file = PROJECT_ROOT / "config" / "config.yaml"
    if not config_file.is_file():
        config_file = PROJECT_ROOT / "config" / "config.example.yaml"
    config = apply_env_overrides(load_yaml(str(config_file)))
    if args.command != "strategy-regime-analysis":
        validate_config(config)
    symbols = validate_symbols(load_yaml(str(PROJECT_ROOT / "config" / "symbols.yaml")))
    symbol = args.symbol or str(symbols[0]["symbol"])
    configured_equities = [
        str(item["symbol"]) for item in symbols if str(item.get("instrument_type", "")).upper() == "EQUITY"
    ]
    requested_universe = [value.strip().upper() for value in args.universe.split(",") if value.strip()]
    parameters: dict[str, Any] = json.loads(args.params)
    cost_model: dict[str, float] = json.loads(args.costs)
    research_config = config.get("research", {})
    project_logger = LoggerSetup.setup(config, component="research", command=args.command)
    started_at = time.perf_counter()
    project_logger.info("operation_started")

    db_path = Path(args.database_path or config["database"]["path"])
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path).resolve()
    if args.command == "strategy-regime-analysis":
        cutoff = (
            datetime.fromisoformat(args.evidence_at.replace("Z", "+00:00"))
            if args.evidence_at
            else datetime.now(ZoneInfo("UTC"))
        )
        if cutoff.tzinfo is None:
            raise ValueError("--evidence-at must include a timezone offset")
        evidence = _list_phase2_7_conditional_evidence_read_only(db_path, cutoff, strategy_name=args.strategy)
        print(
            json.dumps(
                {
                    "cutoff": cutoff.isoformat(),
                    "strategy": args.strategy,
                    "evidence": evidence,
                    "explanation": "Only net-of-cost OUT_OF_SAMPLE evidence available at or before the cutoff is shown.",
                },
                default=str,
                indent=2,
            )
        )
        return 0
    if args.command in {"strategy-scorecards", "selector-decisions", "meta-selector-runs"}:
        cutoff = (
            datetime.fromisoformat(args.evidence_at.replace("Z", "+00:00"))
            if args.evidence_at
            else datetime.now(ZoneInfo("UTC"))
        )
        if cutoff.tzinfo is None:
            raise ValueError("--evidence-at must include a timezone offset")
        table = {
            "strategy-scorecards": "strategy_scorecards",
            "selector-decisions": "selector_decisions",
            "meta-selector-runs": "meta_selector_runs",
        }[args.command]
        report_rows = _list_phase2_8_to_2_10_read_only(
            db_path,
            table,
            cutoff,
            horizon=args.timeframe if args.command != "meta-selector-runs" else None,
            strategy_name=args.strategy if args.command == "strategy-scorecards" else None,
        )
        print(
            json.dumps(
                {
                    "cutoff": cutoff.isoformat(),
                    "command": args.command,
                    "rows": report_rows,
                    "explanation": "Read-only PIT query; no latest fallback and no DuckDB migration/checkpoint side effects.",
                },
                default=str,
                indent=2,
            )
        )
        return 0
    db = DuckDBManager(str(db_path))
    try:
        if requested_universe:
            universe = requested_universe
        elif args.universe_snapshot != "CONFIGURED_UNIVERSE" and args.command != "market-regime":
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
        # Phase 2.2 — Build derived bars
        if args.command == "build-derived-bars":
            from data_platform.resampling import SessionBarResampler  # noqa: PLC0415

            if not args.source_dataset:
                parser.error("--source-dataset is required for build-derived-bars")
            if not args.symbol:
                parser.error("--symbol is required for build-derived-bars")

            target_timeframe = args.derived_timeframe or args.timeframe
            if args.derived_timeframe and args.timeframe != "1d" and args.derived_timeframe != args.timeframe:
                parser.error("--derived-timeframe conflicts with --timeframe")
            if target_timeframe not in {"5m", "15m", "30m", "60m"}:
                parser.error("build-derived-bars requires --timeframe 5m, 15m, 30m, or 60m")
            start_ts, end_ts = _local_date_range(args.start_date, args.end_date)

            cal = india_calendar
            resampler = SessionBarResampler()
            try:
                cert = resampler.derive_and_certify(
                    source_dataset_id=args.source_dataset,
                    target_timeframe=target_timeframe,
                    calendar=cal,
                    db=db,
                    symbol=args.symbol,
                    exchange="NSE",
                    start_ts=start_ts,
                    end_ts=end_ts,
                )
                print(
                    json.dumps(
                        {
                            "status": cert.dq_status,
                            "derived_dataset_id": cert.derived_dataset_id,
                            "symbol": cert.symbol,
                            "timeframe": cert.timeframe,
                            "row_count": cert.row_count,
                            "content_hash": cert.content_hash,
                            "resampler_version": cert.resampler_version,
                            "calendar_version": cert.calendar_version,
                            "source_dataset_ids": cert.source_dataset_ids,
                            "dq_report": cert.dq_report,
                        },
                        default=str,
                        indent=2,
                    )
                )
            except Exception as exc:
                print(json.dumps({"status": "DQ_FAILED", "error": str(exc)}, indent=2))
                return 1
            return 0

        # Phase 2.2 — Cross-provider verification
        if args.command == "verify-market-provider":
            from data_platform.provider_verification import CrossProviderVerifier, VerificationSeverity  # noqa: PLC0415

            if not args.symbol:
                parser.error("--symbol is required for verify-market-provider")
            if not args.primary_provider:
                parser.error("--primary-provider is required for verify-market-provider")
            if not args.secondary_provider:
                parser.error("--secondary-provider is required for verify-market-provider")
            if not args.primary_dataset:
                parser.error("--primary-dataset is required for verify-market-provider")

            target_timeframe = args.derived_timeframe or args.timeframe
            if args.derived_timeframe and args.timeframe != "1d" and args.derived_timeframe != args.timeframe:
                parser.error("--derived-timeframe conflicts with --timeframe")
            start_ts, end_ts = _local_date_range(args.start_date, args.end_date)

            primary_bars = db.load_provider_verification_dataset(
                dataset_id=args.primary_dataset,
                symbol=args.symbol,
                exchange="NSE",
                timeframe=target_timeframe,
                provider_name=args.primary_provider,
                require_canonical=True,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            if primary_bars.empty:
                raise ValueError(
                    f"No primary bars found for {args.symbol}/{args.derived_timeframe}/{args.primary_provider}."
                )

            secondary_bars = None
            if args.secondary_dataset:
                secondary_bars = db.load_provider_verification_dataset(
                    dataset_id=args.secondary_dataset,
                    symbol=args.symbol,
                    exchange="NSE",
                    timeframe=target_timeframe,
                    provider_name=args.secondary_provider,
                    require_canonical=False,
                    start_ts=start_ts,
                    end_ts=end_ts,
                )

            severity = VerificationSeverity(args.verification_severity)
            verifier = CrossProviderVerifier()
            try:
                verif_report = verifier.verify(
                    primary_bars=primary_bars,
                    secondary_bars=secondary_bars if secondary_bars is not None and not secondary_bars.empty else None,
                    symbol=args.symbol,
                    exchange=str(primary_bars["exchange"].iloc[0]) if "exchange" in primary_bars.columns else "NSE",
                    timeframe=target_timeframe,
                    primary_provider=args.primary_provider,
                    secondary_provider=args.secondary_provider,
                    severity=severity,
                    tolerance=None,
                    db=db,
                    primary_dataset_id=args.primary_dataset,
                    secondary_dataset_id=args.secondary_dataset,
                )
                print(
                    json.dumps(
                        {
                            "reconciliation_id": verif_report.reconciliation_id,
                            "symbol": verif_report.symbol,
                            "timeframe": verif_report.timeframe,
                            "primary_provider": verif_report.primary_provider,
                            "secondary_provider": verif_report.secondary_provider,
                            "total_bars_primary": verif_report.total_bars_primary,
                            "bars_match": verif_report.bars_match,
                            "bars_tolerance_match": verif_report.bars_tolerance_match,
                            "bars_disagreement": verif_report.bars_disagreement,
                            "bars_unavailable": verif_report.bars_unavailable,
                            "overall_status": verif_report.overall_status,
                        },
                        default=str,
                        indent=2,
                    )
                )
                return 1 if verif_report.bars_disagreement > 0 and severity == VerificationSeverity.BLOCKING else 0
            except Exception as exc:
                print(json.dumps({"status": "VERIFICATION_FAILED", "error": str(exc)}, indent=2))
                return 1

        if args.command == "market-regime":
            from trading_stack.market_regime import MarketContextType, MarketRegimeEngine
            from trading_stack.regime_transition import (
                RegimeTransitionEngine,
                RegimeTransitionPolicy,
                StressEvidence,
            )

            if args.universe_snapshot == "CONFIGURED_UNIVERSE":
                raise ValueError(
                    "market-regime requires an authoritative PIT universe identity; "
                    "CONFIGURED_UNIVERSE is not valid for historical causal breadth."
                )
            if requested_universe:
                raise ValueError(
                    "market-regime derives its complete breadth universe from the authoritative "
                    "PIT snapshot; --universe is not permitted."
                )

            as_of_str = args.as_of or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
            context_type = MarketContextType(args.context.upper())
            decision_time_str = args.decision_time
            if not decision_time_str:
                if context_type == MarketContextType.INTRADAY:
                    decision_time_str = f"{as_of_str}T10:00:00+05:30"
                else:
                    decision_time_str = f"{as_of_str}T15:30:00+05:30"

            pit_members = PointInTimeUniverseManager.get_constituents(
                db,
                args.universe_snapshot,
                as_of_str,
                as_of_knowledge=decision_time_str,
            )
            universe = [member.symbol for member in pit_members]
            pit_by_symbol = {member.symbol: member for member in pit_members}
            if not universe:
                raise ValueError(
                    f"No causally-known PIT constituents for universe {args.universe_snapshot} at {decision_time_str}."
                )

            bench_sym = args.benchmark

            # --- Phase 2.3 PIT-certified data loading ---
            # Benchmark daily bars — only from VERIFIED + CANONICAL_PROMOTED datasets
            bench_result = db.load_regime_bars(
                bench_sym, "1d", decision_time_str, exchange="NSE", context_type=context_type.value
            )
            bench_daily = bench_result["bars"]

            def loaded_evidence(result: dict[str, Any], symbol: str, *, unavailable_reason: str) -> dict[str, Any]:
                if result["bars"].empty:
                    return {"available": False, "reason": unavailable_reason}
                return {
                    "available": True,
                    "symbol": symbol,
                    "timeframe": result["timeframe"],
                    "dataset_id": result["dataset_id"],
                    "content_hash": result["content_hash"],
                    "certification_id": result.get("certification_id"),
                    "cutoff_applied": result["cutoff_applied"],
                    "dataset_available_at": result.get("dataset_available_at"),
                    "last_bar_timestamp": result.get("last_bar_timestamp"),
                    "last_bar_available_at": result.get("last_bar_available_at"),
                }

            # Benchmark intraday bars — finest certified intraday tf available
            bench_intraday = None
            benchmark_intraday_evidence = {"available": False, "reason": "NOT_INTRADAY_CONTEXT"}
            if context_type == MarketContextType.INTRADAY:
                intra_result = db.load_regime_bars(
                    bench_sym,
                    "1m",
                    decision_time_str,
                    exchange="NSE",
                    intraday=True,
                    context_type=context_type.value,
                )
                if not intra_result["bars"].empty:
                    bench_intraday = intra_result["bars"]
                benchmark_intraday_evidence = loaded_evidence(
                    intra_result,
                    bench_sym,
                    unavailable_reason="NO_CAUSAL_CERTIFIED_INTRADAY_BENCHMARK",
                )

            # VIX bars — check common VIX symbols
            vix_df = None
            vix_dataset_id = None
            vix_content_hash = None
            vix_evidence = {"available": False, "reason": "NO_CAUSAL_CERTIFIED_VIX"}
            for vix_sym in ("INDIA VIX", "INDIAVIX", "NIFTY VIX", "VIX"):
                vix_result = db.load_regime_bars(vix_sym, "1d", decision_time_str, exchange="NSE")
                if not vix_result["bars"].empty:
                    vix_df = vix_result["bars"]
                    vix_dataset_id = vix_result["dataset_id"]
                    vix_content_hash = vix_result["content_hash"]
                    vix_evidence = loaded_evidence(
                        vix_result,
                        vix_sym,
                        unavailable_reason="NO_CAUSAL_CERTIFIED_VIX",
                    )
                    break

            # Universe bars — ALL PIT members (no truncation)
            universe_daily = {}
            universe_manifest_members = []
            for sym in universe:
                u_result = db.load_regime_bars(sym, "1d", decision_time_str, exchange="NSE")
                member = pit_by_symbol[sym]
                effective_from = getattr(member, "effective_from", None)
                effective_until = getattr(member, "effective_until", None)
                known_from = getattr(member, "known_from", None)
                known_at = getattr(member, "known_at", None)
                member_manifest = {
                    "symbol": sym,
                    "effective_from": effective_from.isoformat() if effective_from is not None else None,
                    "effective_until": effective_until.isoformat() if effective_until is not None else None,
                    "known_from": known_from.isoformat() if known_from is not None else None,
                    "known_at": known_at.isoformat() if known_at is not None else None,
                }
                if not u_result["bars"].empty:
                    universe_daily[sym] = u_result["bars"]
                    member_manifest.update(
                        loaded_evidence(
                            u_result,
                            sym,
                            unavailable_reason="NO_CAUSAL_CERTIFIED_BARS",
                        )
                    )
                else:
                    member_manifest.update({"usable": False, "reason": "NO_CAUSAL_CERTIFIED_BARS"})
                if not u_result["bars"].empty:
                    member_manifest["usable"] = True
                universe_manifest_members.append(member_manifest)
            universe_manifest_members.sort(key=lambda member: member["symbol"])
            universe_manifest = {
                "universe_name": args.universe_snapshot,
                "members": universe_manifest_members,
                "total_member_count": len(universe),
                "usable_member_count": len(universe_daily),
                "cutoff": decision_time_str,
            }
            universe_content_hash = hashlib.sha256(
                json.dumps(universe_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()

            engine = MarketRegimeEngine(market_calendar=india_calendar)
            snapshot = engine.evaluate_market_regime(
                market=args.market,
                benchmark=bench_sym,
                context_type=context_type,
                as_of=as_of_str,
                decision_time=decision_time_str,
                benchmark_daily_bars=bench_daily,
                benchmark_intraday_bars=bench_intraday,
                universe_daily_bars=universe_daily if universe_daily else None,
                pit_universe_members=universe if universe else None,
                vix_bars=vix_df,
                evidence_metadata={
                    "universe_snapshot_id": (
                        args.universe_snapshot if args.universe_snapshot != "CONFIGURED_UNIVERSE" else None
                    ),
                    # Certified dataset provenance for audit hash
                    "benchmark_dataset_id": bench_result["dataset_id"],
                    "benchmark_content_hash": bench_result["content_hash"],
                    "vix_dataset_id": vix_dataset_id,
                    "vix_content_hash": vix_content_hash,
                    "cutoff_timestamp": bench_result["cutoff_applied"],
                    "universe_content_hash": universe_content_hash,
                    "universe_manifest": universe_manifest,
                    "benchmark_certification_id": bench_result.get("certification_id"),
                    "benchmark_daily_evidence": loaded_evidence(
                        bench_result,
                        bench_sym,
                        unavailable_reason="NO_CAUSAL_CERTIFIED_BENCHMARK",
                    ),
                    "benchmark_intraday_evidence": benchmark_intraday_evidence,
                    "vix_evidence": vix_evidence,
                },
            )
            transition_policy = RegimeTransitionPolicy.from_config(
                research_config.get("regime_transition"),
                context_type=context_type,
            )
            prior_transition_state = db.get_regime_transition_state(
                args.market,
                bench_sym,
                context_type,
            )
            prior_risk_state = db.get_operational_risk_state(
                args.market,
                bench_sym,
                context_type,
            )
            stress_evidence = None
            if transition_policy.stress_override_enabled:
                benchmark_loss = None
                extreme_gap = None
                if len(bench_daily) >= 2:
                    ordered_benchmark = bench_daily.copy()
                    sort_column = "timestamp" if "timestamp" in ordered_benchmark.columns else "date"
                    ordered_benchmark = ordered_benchmark.sort_values(sort_column)
                    previous_close = float(ordered_benchmark["close"].iloc[-2])
                    if context_type == MarketContextType.INTRADAY:
                        if bench_intraday is not None and not bench_intraday.empty and previous_close > 0:
                            intraday = bench_intraday.copy()
                            session_date = pd.Timestamp(as_of_str).date()
                            intraday = intraday[
                                pd.to_datetime(intraday["timestamp"]).dt.date == session_date
                            ].sort_values("timestamp")
                            if not intraday.empty:
                                benchmark_loss = max(0.0, 1.0 - float(intraday["close"].iloc[-1]) / previous_close)
                                extreme_gap = abs(float(intraday["open"].iloc[0]) / previous_close - 1.0)
                    else:
                        latest_close = float(ordered_benchmark["close"].iloc[-1])
                        latest_open = float(ordered_benchmark["open"].iloc[-1])
                        if previous_close > 0:
                            benchmark_loss = max(0.0, 1.0 - latest_close / previous_close)
                            extreme_gap = abs(latest_open / previous_close - 1.0)
                stress_evidence = StressEvidence(
                    observed_at=decision_time_str,
                    benchmark_loss=benchmark_loss,
                    volatility_shock=snapshot.features.volatility_shock_ratio,
                    extreme_gap=extreme_gap,
                    liquidity_collapse=snapshot.features.liquidity_deterioration,
                    market_data_integrity_failure=any(
                        result.get("integrity_failure", False)
                        for result in (
                            bench_result,
                            intra_result if context_type == MarketContextType.INTRADAY else {},
                            vix_result,
                        )
                    ),
                )
            transition = RegimeTransitionEngine(transition_policy).evaluate(
                snapshot,
                prior_state=prior_transition_state,
                prior_risk_state=prior_risk_state,
                stress_evidence=stress_evidence,
            )
            db.persist_regime_transition(snapshot, transition)
            output = snapshot.to_dict()
            output.update(transition.to_dict())
            print(json.dumps(output, default=str, indent=2))
            return 0

        if args.command == "benchmark-register":
            if not args.benchmark_provider:
                parser.error("--benchmark-provider is required for benchmark-register")
            universe_service.register_benchmark(
                args.benchmark,
                args.benchmark_provider,
                relationship=args.benchmark_relationship,
                source=args.benchmark_source,
                approved_for_research=args.approve_benchmark,
            )
            print(
                json.dumps(
                    {
                        "benchmark": args.benchmark,
                        "provider_symbol": args.benchmark_provider,
                        "relationship": args.benchmark_relationship,
                        "approved": args.approve_benchmark,
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "universe-status":
            if args.universe_snapshot == "CONFIGURED_UNIVERSE":
                raise ValueError("universe-status requires --universe-snapshot with an immutable snapshot ID.")
            readiness = universe_service.readiness(
                args.universe_snapshot,
                timeframe=args.timeframe,
                benchmark_symbol=args.benchmark,
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
                    strategy=args.strategy
                    if args.strategy != "trend_following" or (argv and "--strategy" in argv)
                    else None,
                    status=args.status,
                )
                print(
                    json.dumps(
                        {
                            "family_id": args.experiment_family_id,
                            "summary": summary,
                            "trials": trials,
                        },
                        default=str,
                        indent=2,
                    )
                )
                return 0
            families = db.list_experiment_families()
            trials = db.list_research_trials(
                family_id=None,
                strategy=args.strategy
                if args.strategy != "trend_following" or (argv and "--strategy" in argv)
                else None,
                status=args.status,
            )
            print(
                json.dumps(
                    {
                        "families": families,
                        "trials": trials,
                        "total_families": len(families),
                        "total_trials": len(trials),
                    },
                    default=str,
                    indent=2,
                )
            )
            return 0
        if args.command == "robustness":
            if args.robustness_id:
                record = db.get_robustness_evaluation(args.robustness_id)
                if not record:
                    raise ValueError(f"Robustness evaluation '{args.robustness_id}' not found.")
                print(json.dumps(record, default=str, indent=2))
                return 0

            rob_policy_dict = research_config.get("statistical_robustness", {})
            policy = RobustnessPolicy(**rob_policy_dict) if rob_policy_dict else RobustnessPolicy()
            rob_evaluator = RobustnessEvaluator(db, policy=policy, india_calendar=india_calendar)

            experiment_universe = (
                universe
                if args.strategy in StrategyRegistry.available()
                and StrategyRegistry.metadata(args.strategy).scope == StrategyScope.CROSS_SECTIONAL
                else [symbol]
            )
            experiment_costs = cost_model or (
                research_config.get("indian_delivery_costs", {})
                if args.strategy in StrategyRegistry.available()
                and StrategyRegistry.metadata(args.strategy).scope == StrategyScope.CROSS_SECTIONAL
                else research_config.get("costs", {})
            )

            parent_run_id = (
                f"rob-{hashlib.sha256(f'{args.strategy}-{args.timeframe}-{time.time()}'.encode()).hexdigest()[:12]}"
            )
            spec = ExperimentSpec(
                strategy_name=args.strategy,
                universe=experiment_universe,
                timeframe=args.timeframe,
                mode=args.mode,
                parameters=parameters,
                cost_model=experiment_costs,
                universe_snapshot_id=args.universe_snapshot,
                benchmark_symbol=args.benchmark or None,
                experiment_family_id=args.experiment_family_id,
            )

            train_sz = int(rob_policy_dict.get("train_size", 252))
            val_sz = int(rob_policy_dict.get("val_size", 63))
            test_sz = int(rob_policy_dict.get("test_size", 63))
            bundle = rob_evaluator.evaluate(
                parent_run_id=parent_run_id,
                spec=spec,
                train_size=train_sz,
                val_size=val_sz,
                test_size=test_sz,
                purge_window=args.purge_window,
                embargo_window=args.embargo_window,
                starting_capital=args.capital,
            )
            print(json.dumps(bundle.model_dump(mode="json"), default=str, indent=2))
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
            print(
                json.dumps(
                    {
                        "analysis_id": report.analysis_id,
                        "effective_independent_bets": report.effective_independent_bets,
                        "correlations": report.correlations.to_dict(orient="records"),
                        "strategy_summary": report.strategy_summary.to_dict(orient="records"),
                    },
                    default=str,
                    indent=2,
                )
            )
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
                    strategy_names=strategy_names,
                    universe=universe,
                    timeframe=args.timeframe,
                    mode=args.mode,
                    universe_snapshot_id=args.universe_snapshot,
                    benchmark_symbol=args.benchmark or None,
                    parameters={name: parameters for name in strategy_names},
                    cost_model=cost_model or research_config.get("indian_delivery_costs", {}),
                    cost_model_version=str(
                        research_config.get("indian_delivery_costs", {}).get("version", "angel-nse-delivery-2026-04")
                    ),
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
                    args.universe_snapshot,
                    timeframe=args.timeframe,
                    benchmark_symbol=args.benchmark,
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
                raise ValueError(
                    "Forward paper sessions require --run-id for a human-approved PAPER_CANDIDATE or PAPER_ACTIVE run."
                )
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
            print(
                json.dumps(
                    {
                        "session_id": forward.session_id,
                        "status": forward.status,
                        "strategy": forward.strategy_name,
                        "symbol": forward.symbol,
                        "timeframe": forward.timeframe,
                        "processed_bars": forward.processed_bars,
                        "orders": len(forward.orders),
                        "fills": len(forward.fills),
                        "cash": forward.cash,
                        "quantity": forward.quantity,
                        "equity": forward.equity,
                        "pending_signal_timestamp": forward.pending_signal_timestamp,
                        "paper_summary": forward.paper_summary,
                    },
                    default=str,
                    indent=2,
                )
            )
            return 0
        if "forward_portfolio_result" in outcome:
            forward = outcome["forward_portfolio_result"]
            print(
                json.dumps(
                    {
                        "session_id": forward.session_id,
                        "status": forward.status,
                        "strategy": forward.strategy_name,
                        "universe_snapshot_id": forward.universe_snapshot_id,
                        "timeframe": forward.timeframe,
                        "processed_sessions": forward.processed_sessions,
                        "orders": len(forward.orders),
                        "fills": len(forward.fills),
                        "cash": forward.cash,
                        "holdings": forward.holdings,
                        "equity": forward.equity,
                        "pending_signal_timestamp": forward.pending_signal_timestamp,
                        "paper_summary": forward.paper_summary,
                    },
                    default=str,
                    indent=2,
                )
            )
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


def _local_date_range(start_date: str | None, end_date: str | None) -> tuple[datetime | None, datetime | None]:
    """Translate inclusive local trading dates into a half-open UTC range."""
    if not start_date and not end_date:
        return None, None
    if not start_date or not end_date:
        raise ValueError("--start-date and --end-date must be supplied together.")
    zone = ZoneInfo("Asia/Kolkata")
    start = datetime.fromisoformat(start_date).replace(tzinfo=zone)
    end = datetime.fromisoformat(end_date).replace(tzinfo=zone) + timedelta(days=1)
    if end <= start:
        raise ValueError("--end-date must not precede --start-date.")
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


if __name__ == "__main__":
    raise SystemExit(main())
