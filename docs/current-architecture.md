# Current Architecture

## 1. System Overview
The platform is a research-first systematic trading engine. It is strictly segmented into provider integrations (Angel One), local deterministic storage (DuckDB), and a decoupled execution simulator. 

## 2. Core Operational Flow
```text
Angel One -> SmartAPI clients -> validation -> historical_candles -> features
-> strategy -> vector or event backtest -> run/order/fill records
```

## 3. Target Research Architecture (Paper Mode)
```text
User / CLI
  -> local task orchestrator
  -> data platform -> DuckDB cache and immutable dataset provenance
  -> synchronized features -> single-asset fan-out / cross-sectional ranking
  -> vector screening / authoritative portfolio event replay
  -> walk-forward evidence -> RCA clusters -> deterministic risk -> paper broker

Research Manager
  -> Technical Analyst + Quant Analyst -> Risk Analyst -> structured synthesis
```

## 4. Design Boundaries & Constraints
- **Local Persistence Only**: DuckDB (`market_data.duckdb`) is the only persistence layer. It is a single-writer file, meaning multi-process ingestion and research jobs must be orchestrated carefully.
- **No Live Trading**: Live order routing remains entirely unavailable by design. The environment is strictly for deterministic backtesting and paper simulation.
- **Agent Sandboxing**: AI research agents receive stored evidence and constrained tool results only. No LLM can access credentials, run broker actions, or autonomously promote a strategy to live paper states.
- **Immutable Provenance**: Every fulfilled request comes from exactly one provider snapshot; vendor data is never blended synthetically.
