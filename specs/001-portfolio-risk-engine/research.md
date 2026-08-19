# Phase 0: Outline & Research

## Technical Context
The project is a local-first systematic trading engine written in Python 3.12. It uses DuckDB as its primary immutable storage and does not support live execution. 
The objective is to introduce a portfolio risk engine without altering existing strategy interfaces.

## Research Findings
- **Integration Point**: The risk engine must sit between `trading_stack/strategy_library` (decision generation) and `trading_stack/paper.py` or the `event_driven` runner (trade execution).
- **Architecture Decision**: We will implement a `RiskEngine` class within the `risk/` package that wraps the execution engine. Any strategy `TradeIntent` will be routed through `RiskEngine.validate()`. If valid, it proceeds. If not, it is rejected and logged.
- **Audit Trail**: Rejected and approved intents will be logged to a new DuckDB table `risk_audit_log` managed by `storage/duckdb_manager.py`.
- **Configuration**: Risk limits (max position, max sector exposure) will be defined in `config/risk_limits.yaml`.
