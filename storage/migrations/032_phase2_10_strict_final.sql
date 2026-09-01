CREATE TABLE IF NOT EXISTS phase2_10_causal_risk_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL,
    exposure DOUBLE NOT NULL,
    sector_exposure JSON NOT NULL,
    daily_pnl DOUBLE NOT NULL,
    drawdown DOUBLE NOT NULL,
    var_inputs JSON NOT NULL,
    var_result DOUBLE NOT NULL,
    open_positions JSON NOT NULL,
    instrument_liquidity JSON NOT NULL,
    rolling_returns JSON NOT NULL,
    rolling_volatility DOUBLE NOT NULL,
    data_hash VARCHAR NOT NULL,
    snapshot_hash VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS phase2_10_empirical_acceptance (
    acceptance_id VARCHAR PRIMARY KEY,
    meta_run_id VARCHAR NOT NULL,
    certificate_id VARCHAR NOT NULL,
    certificate_hash VARCHAR NOT NULL,
    execution_hash VARCHAR NOT NULL,
    verdict VARCHAR NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL,
    acceptance_hash VARCHAR NOT NULL
);
