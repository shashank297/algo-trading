CREATE TABLE IF NOT EXISTS instrument_master (
    token VARCHAR NOT NULL, -- Angel One instrument token
    symbol VARCHAR NOT NULL, -- Exchange trading symbol
    name VARCHAR, -- Human-readable instrument name
    expiry VARCHAR, -- Contract expiry when applicable
    strike DOUBLE, -- Strike price for derivatives
    lotsize INTEGER, -- Exchange lot size
    instrumenttype VARCHAR, -- Instrument type such as EQ, FUT, OPT
    exch_seg VARCHAR NOT NULL, -- Exchange segment such as NSE or BSE
    tick_size DOUBLE, -- Minimum tick size
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Last upsert timestamp
    PRIMARY KEY (token, exch_seg)
);

CREATE TABLE IF NOT EXISTS historical_candles (
    symbol VARCHAR NOT NULL, -- Configured trading symbol
    token VARCHAR NOT NULL, -- Instrument token used for the download
    exchange VARCHAR NOT NULL, -- Exchange segment for the candle
    timeframe VARCHAR NOT NULL, -- Local timeframe label such as 1m or 1d
    timestamp TIMESTAMPTZ NOT NULL, -- Candle timestamp in IST
    open DOUBLE NOT NULL, -- Candle open price
    high DOUBLE NOT NULL, -- Candle high price
    low DOUBLE NOT NULL, -- Candle low price
    close DOUBLE NOT NULL, -- Candle close price
    volume BIGINT NOT NULL, -- Traded volume
    adjustment VARCHAR NOT NULL DEFAULT 'UNADJUSTED',
    provider_name VARCHAR,
    dataset_id VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (symbol, timeframe, timestamp)
);

ALTER TABLE historical_candles ADD COLUMN IF NOT EXISTS adjustment VARCHAR DEFAULT 'UNADJUSTED';
ALTER TABLE historical_candles ADD COLUMN IF NOT EXISTS provider_name VARCHAR;
ALTER TABLE historical_candles ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;

CREATE TABLE IF NOT EXISTS market_data_state (
    state_id INTEGER NOT NULL DEFAULT 1,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (state_id)
);

INSERT OR IGNORE INTO market_data_state (state_id, revision) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS download_log (
    id INTEGER, -- Optional local identifier for future use
    symbol VARCHAR NOT NULL, -- Downloaded symbol
    exchange VARCHAR NOT NULL, -- Exchange used for the request
    timeframe VARCHAR NOT NULL, -- Timeframe label such as 1m or 1d
    from_date TIMESTAMP, -- Requested start timestamp
    to_date TIMESTAMP, -- Requested end timestamp
    candles_fetched INTEGER, -- Number of candles returned by SmartAPI
    candles_inserted INTEGER, -- Number of new candles inserted into DuckDB
    status VARCHAR, -- SUCCESS, PARTIAL, FAILED, or UP_TO_DATE
    error_message VARCHAR, -- Failure reason when present
    duration_sec DOUBLE, -- Elapsed runtime for the request
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Audit creation timestamp
);

CREATE TABLE IF NOT EXISTS quality_report (
    id INTEGER, -- Optional local identifier for future use
    symbol VARCHAR NOT NULL, -- Validated symbol
    timeframe VARCHAR NOT NULL, -- Validated timeframe label
    dataset_id VARCHAR, -- Canonical promoted dataset identifier
    check_type VARCHAR NOT NULL, -- Quality check name
    issue_count INTEGER, -- Number of issues found for this check
    details VARCHAR, -- JSON-serialized check details
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Validation timestamp
);

ALTER TABLE quality_report ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;

CREATE TABLE IF NOT EXISTS market_universe (
    symbol VARCHAR NOT NULL, -- Canonical trading symbol
    exchange VARCHAR NOT NULL, -- Exchange or venue
    asset_class VARCHAR NOT NULL, -- INDIA_EQUITY, INDIA_INDEX, FOREX, CRYPTO, US_EQUITY
    currency VARCHAR NOT NULL, -- Settlement currency
    timezone VARCHAR NOT NULL, -- Trading timezone
    session_open VARCHAR NOT NULL, -- Session start time in HH:MM
    session_close VARCHAR NOT NULL, -- Session end time in HH:MM
    tradable BOOLEAN NOT NULL DEFAULT TRUE, -- Whether live trading is enabled
    lot_size INTEGER NOT NULL DEFAULT 1, -- Contract or share lot size
    tick_size DOUBLE NOT NULL DEFAULT 0.01, -- Minimum price increment
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Last refresh timestamp
    PRIMARY KEY (symbol, exchange)
);

CREATE TABLE IF NOT EXISTS feature_store (
    symbol VARCHAR NOT NULL, -- Canonical trading symbol
    timeframe VARCHAR NOT NULL, -- Bar timeframe label
    timestamp TIMESTAMPTZ NOT NULL, -- Feature timestamp
    feature_group VARCHAR NOT NULL, -- Feature family label
    feature_name VARCHAR NOT NULL, -- Feature column name
    feature_value DOUBLE, -- Numeric feature value
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (symbol, timeframe, timestamp, feature_group, feature_name)
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id VARCHAR NOT NULL, -- Deterministic or generated run identifier
    strategy_name VARCHAR NOT NULL, -- Strategy implementation name
    asset_class VARCHAR NOT NULL, -- Market family for the run
    symbol VARCHAR NOT NULL, -- Trading symbol or basket label
    timeframe VARCHAR NOT NULL, -- Selected timeframe
    mode VARCHAR NOT NULL, -- vectorized, event-driven, or paper
    parameters_json VARCHAR NOT NULL, -- Serialized strategy parameters
    data_hash VARCHAR NOT NULL, -- Hash of the input data snapshot
    status VARCHAR NOT NULL, -- STARTED, COMPLETED, FAILED
    started_at TIMESTAMP NOT NULL, -- Run start timestamp
    finished_at TIMESTAMP, -- Run end timestamp
    notes VARCHAR, -- Human-readable notes
    starting_capital DOUBLE DEFAULT 100000.0, -- Initial cash allocation for the run
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS strategy_metrics (
    run_id VARCHAR NOT NULL, -- Foreign key to strategy_runs
    metric_name VARCHAR NOT NULL, -- Metric label
    metric_value DOUBLE NOT NULL, -- Metric value
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (run_id, metric_name)
);

CREATE TABLE IF NOT EXISTS strategy_orders (
    order_id VARCHAR NOT NULL, -- Unique order identifier
    run_id VARCHAR NOT NULL, -- Related strategy run
    symbol VARCHAR NOT NULL, -- Trading symbol
    side VARCHAR NOT NULL, -- BUY or SELL
    quantity DOUBLE NOT NULL, -- Requested quantity
    order_type VARCHAR NOT NULL, -- MARKET, LIMIT, STOP, BRACKET
    time_in_force VARCHAR NOT NULL, -- DAY, IOC, GTC
    status VARCHAR NOT NULL, -- CREATED, SUBMITTED, FILLED, CANCELLED, REJECTED
    requested_at TIMESTAMP NOT NULL, -- Order request timestamp
    filled_at TIMESTAMP, -- Fill timestamp
    limit_price DOUBLE, -- Optional limit price
    stop_price DOUBLE, -- Optional stop price
    average_fill_price DOUBLE, -- Executed average price
    slippage_bps DOUBLE NOT NULL DEFAULT 0, -- Simulated slippage in basis points
    fees DOUBLE NOT NULL DEFAULT 0, -- Fees paid
    metadata_json VARCHAR, -- Additional serialized metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (order_id)
);

CREATE TABLE IF NOT EXISTS strategy_fills (
    fill_id VARCHAR NOT NULL, -- Unique fill identifier
    order_id VARCHAR NOT NULL, -- Related order identifier
    run_id VARCHAR NOT NULL, -- Related strategy run
    symbol VARCHAR NOT NULL, -- Trading symbol
    timestamp TIMESTAMP NOT NULL, -- Fill timestamp
    quantity DOUBLE NOT NULL, -- Filled quantity
    price DOUBLE NOT NULL, -- Fill price
    side VARCHAR NOT NULL, -- BUY or SELL
    fill_type VARCHAR NOT NULL, -- PAPER, BACKTEST, LIVE
    fees DOUBLE NOT NULL DEFAULT 0, -- Fees paid
    slippage_bps DOUBLE NOT NULL DEFAULT 0, -- Applied slippage
    metadata_json VARCHAR, -- Additional serialized metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (fill_id)
);

CREATE TABLE IF NOT EXISTS paper_reconciliation (
    run_id VARCHAR NOT NULL, -- Related strategy run
    trade_date DATE NOT NULL, -- Reconciliation date
    expected_orders INTEGER NOT NULL, -- Expected order count
    submitted_orders INTEGER NOT NULL, -- Submitted order count
    filled_orders INTEGER NOT NULL, -- Filled order count
    rejected_orders INTEGER NOT NULL, -- Rejected order count
    pnl DOUBLE NOT NULL, -- Mark-to-market PnL
    drift DOUBLE NOT NULL, -- Paper vs expected drift
    notes VARCHAR, -- Human-readable notes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Insert timestamp
    PRIMARY KEY (run_id, trade_date)
);

-- Append-only strategy intent ledger. Reconciliation compares this independently
-- persisted target against fill-derived positions, never mutable run metrics.
CREATE TABLE IF NOT EXISTS paper_position_intents (
    intent_id VARCHAR NOT NULL PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    desired_quantity DOUBLE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (session_id, symbol, as_of)
);

CREATE TABLE IF NOT EXISTS lineage_backfill_rejections (
    run_id VARCHAR NOT NULL PRIMARY KEY,
    legacy_frame_certification_id VARCHAR,
    rejection_reason VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

-- Immutable provenance for normalized market-data snapshots. Historical candles
-- remain the compatibility cache used by the original ingestion pipeline.
CREATE TABLE IF NOT EXISTS market_datasets (
    dataset_id VARCHAR NOT NULL PRIMARY KEY,
    parent_dataset_id VARCHAR,
    dataset_stage VARCHAR NOT NULL DEFAULT 'RAW', -- 'RAW', 'CANONICAL'
    symbol VARCHAR,
    canonical_symbol VARCHAR,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    provider_symbol VARCHAR,
    provider_token VARCHAR,
    declared_adjustment VARCHAR,
    adjustment VARCHAR DEFAULT 'UNADJUSTED',
    timezone VARCHAR DEFAULT 'Asia/Kolkata',
    retrieved_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    lifecycle_status VARCHAR NOT NULL DEFAULT 'RAW_RECORDED',
    status VARCHAR DEFAULT 'VALID',
    raw_hash VARCHAR NOT NULL,
    transformation_hash VARCHAR,
    hash_algorithm VARCHAR NOT NULL DEFAULT 'SHA256',
    hash_version VARCHAR NOT NULL DEFAULT 'raw-provider-v1',
    row_count INTEGER NOT NULL DEFAULT 0,
    metadata_json VARCHAR DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS parent_dataset_id VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS dataset_stage VARCHAR DEFAULT 'RAW';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS symbol VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS canonical_symbol VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS provider_token VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS declared_adjustment VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR DEFAULT 'RAW_RECORDED';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS hash_algorithm VARCHAR DEFAULT 'SHA256';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS hash_version VARCHAR DEFAULT 'raw-provider-v1';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS row_count INTEGER DEFAULT 0;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS raw_bar_observations (
    raw_dataset_id VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    timestamp_raw VARCHAR,
    open_raw VARCHAR,
    high_raw VARCHAR,
    low_raw VARCHAR,
    close_raw VARCHAR,
    volume_raw VARCHAR,
    raw_row_json VARCHAR NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (raw_dataset_id, source_row_number)
);

ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS raw_dataset_id VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS source_row_number BIGINT DEFAULT 0;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS timestamp_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS open_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS high_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS low_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS close_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS volume_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS raw_row_json VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS provider_attempts (
    attempt_id VARCHAR NOT NULL,
    dataset_id VARCHAR,
    provider_name VARCHAR NOT NULL,
    request_json VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    error_message VARCHAR,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    PRIMARY KEY (attempt_id)
);

CREATE TABLE IF NOT EXISTS instrument_aliases (
    canonical_symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    provider_symbol VARCHAR NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (canonical_symbol, exchange, provider_name)
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    universe_json VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    mode VARCHAR NOT NULL,
    parameters_json VARCHAR NOT NULL,
    feature_version VARCHAR NOT NULL,
    cost_model_json VARCHAR NOT NULL,
    benchmark_symbol VARCHAR,
    data_hash VARCHAR,
    source_revision VARCHAR NOT NULL,
    llm_config_json VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    notes VARCHAR,
    PRIMARY KEY (experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    experiment_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    dataset_id VARCHAR,
    role VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (experiment_id, run_id)
);

CREATE TABLE IF NOT EXISTS research_tasks (
    task_id VARCHAR NOT NULL,
    goal_id VARCHAR NOT NULL,
    parent_task_id VARCHAR,
    task_name VARCHAR NOT NULL,
    assigned_agent VARCHAR,
    state VARCHAR NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 0,
    timeout_seconds INTEGER,
    input_json VARCHAR NOT NULL,
    output_json VARCHAR,
    error_message VARCHAR,
    token_usage INTEGER NOT NULL DEFAULT 0,
    cost_usd DOUBLE NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    PRIMARY KEY (task_id)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    agent_run_id VARCHAR NOT NULL,
    task_id VARCHAR NOT NULL,
    agent_name VARCHAR NOT NULL,
    model_name VARCHAR,
    status VARCHAR NOT NULL,
    prompt_hash VARCHAR NOT NULL,
    token_usage INTEGER NOT NULL DEFAULT 0,
    cost_usd DOUBLE NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    PRIMARY KEY (agent_run_id)
);

CREATE TABLE IF NOT EXISTS agent_outputs (
    agent_run_id VARCHAR NOT NULL,
    output_json VARCHAR NOT NULL,
    evidence_json VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_run_id)
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id VARCHAR NOT NULL,
    run_id VARCHAR,
    experiment_id VARCHAR,
    symbol VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    requested_notional DOUBLE NOT NULL,
    approved_notional DOUBLE NOT NULL,
    reasons_json VARCHAR NOT NULL,
    policy_json VARCHAR NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (decision_id)
);

CREATE TABLE IF NOT EXISTS universe_snapshots (
    snapshot_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    effective_date DATE NOT NULL,
    content_hash VARCHAR NOT NULL,
    survivorship_bias BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_id)
);

CREATE TABLE IF NOT EXISTS universe_snapshot_members (
    snapshot_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    provider_symbol VARCHAR,
    provider_token VARCHAR,
    company_name VARCHAR,
    sector VARCHAR NOT NULL DEFAULT 'UNKNOWN',
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    active_from DATE,
    active_to DATE,
    liquidity_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    data_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    paper_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (snapshot_id, symbol)
);

CREATE TABLE IF NOT EXISTS dataset_snapshot_groups (
    group_id VARCHAR NOT NULL,
    universe_snapshot_id VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    benchmark_symbol VARCHAR,
    data_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (group_id)
);

CREATE TABLE IF NOT EXISTS dataset_snapshot_group_members (
    group_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    dataset_id VARCHAR,
    exclusion_reason VARCHAR,
    PRIMARY KEY (group_id, symbol)
);

CREATE TABLE IF NOT EXISTS experiment_jobs (
    job_key VARCHAR NOT NULL,
    experiment_id VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    strategy_scope VARCHAR NOT NULL,
    symbol VARCHAR,
    universe_snapshot_id VARCHAR,
    fold_id VARCHAR,
    parameters_hash VARCHAR NOT NULL,
    cost_model_version VARCHAR NOT NULL,
    data_revision BIGINT NOT NULL DEFAULT 0,
    source_revision VARCHAR,
    state VARCHAR NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 2,
    run_id VARCHAR,
    error_message VARCHAR,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    PRIMARY KEY (job_key)
);

ALTER TABLE experiment_jobs ADD COLUMN IF NOT EXISTS data_revision BIGINT DEFAULT 0;
ALTER TABLE experiment_jobs ADD COLUMN IF NOT EXISTS source_revision VARCHAR;
ALTER TABLE experiment_jobs ADD COLUMN IF NOT EXISTS data_from TIMESTAMPTZ;
ALTER TABLE experiment_jobs ADD COLUMN IF NOT EXISTS data_to TIMESTAMPTZ;
ALTER TABLE experiment_jobs ADD COLUMN IF NOT EXISTS bar_count BIGINT;

CREATE TABLE IF NOT EXISTS portfolio_positions (
    run_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL,
    quantity DOUBLE NOT NULL,
    market_value DOUBLE NOT NULL,
    cash DOUBLE,
    equity DOUBLE,
    gross_exposure DOUBLE NOT NULL,
    daily_pnl DOUBLE,
    PRIMARY KEY (run_id, timestamp, symbol)
);

CREATE TABLE IF NOT EXISTS portfolio_rebalances (
    rebalance_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    signal_timestamp TIMESTAMPTZ NOT NULL,
    execution_timestamp TIMESTAMPTZ NOT NULL,
    buy_turnover DOUBLE NOT NULL,
    sell_turnover DOUBLE NOT NULL,
    total_turnover DOUBLE NOT NULL,
    replacement_pct DOUBLE NOT NULL,
    target_count INTEGER NOT NULL,
    PRIMARY KEY (rebalance_id)
);

CREATE TABLE IF NOT EXISTS trade_attribution (
    run_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    realized_pnl DOUBLE NOT NULL,
    cost DOUBLE NOT NULL,
    target_weight DOUBLE NOT NULL,
    PRIMARY KEY (run_id, timestamp, symbol, side)
);

CREATE TABLE IF NOT EXISTS trade_round_trips (
    trade_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    entry_timestamp TIMESTAMPTZ NOT NULL,
    exit_timestamp TIMESTAMPTZ NOT NULL,
    quantity DOUBLE NOT NULL,
    entry_price DOUBLE NOT NULL,
    exit_price DOUBLE NOT NULL,
    entry_cost DOUBLE NOT NULL,
    exit_cost DOUBLE NOT NULL,
    gross_pnl DOUBLE NOT NULL,
    net_pnl DOUBLE NOT NULL,
    holding_period_days DOUBLE NOT NULL,
    entry_reason VARCHAR NOT NULL,
    exit_reason VARCHAR NOT NULL,
    exit_classification VARCHAR NOT NULL,
    PRIMARY KEY (trade_id)
);

CREATE TABLE IF NOT EXISTS walk_forward_trade_attribution (
    run_id VARCHAR NOT NULL,
    fold_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    realized_pnl DOUBLE NOT NULL,
    cost DOUBLE NOT NULL,
    target_weight DOUBLE NOT NULL,
    quantity DOUBLE NOT NULL,
    gross_pnl DOUBLE NOT NULL,
    holding_period_days DOUBLE,
    exit_classification VARCHAR,
    PRIMARY KEY (run_id, fold_id, timestamp, symbol, side)
);

CREATE TABLE IF NOT EXISTS walk_forward_round_trips (
    trade_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    fold_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    entry_timestamp TIMESTAMPTZ NOT NULL,
    exit_timestamp TIMESTAMPTZ NOT NULL,
    quantity DOUBLE NOT NULL,
    entry_price DOUBLE NOT NULL,
    exit_price DOUBLE NOT NULL,
    entry_cost DOUBLE NOT NULL,
    exit_cost DOUBLE NOT NULL,
    gross_pnl DOUBLE NOT NULL,
    net_pnl DOUBLE NOT NULL,
    holding_period_days DOUBLE NOT NULL,
    entry_reason VARCHAR NOT NULL,
    exit_reason VARCHAR NOT NULL,
    exit_classification VARCHAR NOT NULL,
    PRIMARY KEY (trade_id, fold_id)
);

CREATE TABLE IF NOT EXISTS fill_cost_components (
    run_id VARCHAR NOT NULL,
    fill_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    brokerage DOUBLE NOT NULL,
    stt DOUBLE NOT NULL,
    exchange_transaction DOUBLE NOT NULL,
    sebi DOUBLE NOT NULL,
    ipft DOUBLE NOT NULL DEFAULT 0,
    dp_charge DOUBLE NOT NULL DEFAULT 0,
    gst DOUBLE NOT NULL,
    stamp_duty DOUBLE NOT NULL,
    spread DOUBLE NOT NULL,
    slippage DOUBLE NOT NULL,
    market_impact DOUBLE NOT NULL,
    total_cost DOUBLE NOT NULL,
    PRIMARY KEY (fill_id)
);

CREATE TABLE IF NOT EXISTS strategy_correlations (
    analysis_id VARCHAR NOT NULL,
    strategy_a VARCHAR NOT NULL,
    strategy_b VARCHAR NOT NULL,
    return_correlation DOUBLE,
    signal_overlap DOUBLE,
    holdings_overlap DOUBLE,
    trade_overlap DOUBLE,
    drawdown_overlap DOUBLE,
    regime_correlation_json VARCHAR,
    cluster_id VARCHAR,
    evidence_level VARCHAR NOT NULL DEFAULT 'OUT_OF_SAMPLE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (analysis_id, strategy_a, strategy_b)
);

CREATE TABLE IF NOT EXISTS strategy_equity_curve (
    run_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    equity DOUBLE NOT NULL,
    gross_return DOUBLE NOT NULL,
    net_return DOUBLE NOT NULL,
    drawdown DOUBLE NOT NULL,
    gross_exposure DOUBLE NOT NULL,
    evidence_level VARCHAR NOT NULL DEFAULT 'IN_SAMPLE',
    fold_id VARCHAR NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, timestamp, evidence_level, fold_id)
);

CREATE TABLE IF NOT EXISTS walk_forward_metrics (
    run_id VARCHAR NOT NULL,
    fold_id VARCHAR NOT NULL,
    train_end TIMESTAMPTZ NOT NULL,
    test_start TIMESTAMPTZ NOT NULL,
    test_end TIMESTAMPTZ NOT NULL,
    metric_name VARCHAR NOT NULL,
    metric_value DOUBLE NOT NULL,
    PRIMARY KEY (run_id, fold_id, metric_name)
);

CREATE TABLE IF NOT EXISTS walk_forward_folds (
    run_id VARCHAR NOT NULL,
    fold_id VARCHAR NOT NULL,
    train_start TIMESTAMPTZ NOT NULL,
    train_end TIMESTAMPTZ NOT NULL,
    test_start TIMESTAMPTZ NOT NULL,
    test_end TIMESTAMPTZ NOT NULL,
    selected_parameters_json VARCHAR NOT NULL,
    candidate_count INTEGER NOT NULL,
    training_score DOUBLE,
    train_data_hash VARCHAR NOT NULL,
    test_data_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, fold_id)
);

CREATE TABLE IF NOT EXISTS promotion_reviews (
    review_id VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    run_id VARCHAR,
    stage VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    score DOUBLE NOT NULL,
    reasons_json VARCHAR NOT NULL,
    human_approved BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (review_id)
);

CREATE TABLE IF NOT EXISTS benchmark_aliases (
    canonical_symbol VARCHAR NOT NULL,
    provider_symbol VARCHAR NOT NULL,
    relationship VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    approved_for_research BOOLEAN NOT NULL DEFAULT FALSE,
    notes VARCHAR,
    PRIMARY KEY (canonical_symbol, provider_symbol)
);

CREATE TABLE IF NOT EXISTS paper_sessions (
    session_id VARCHAR NOT NULL,
    approved_run_id VARCHAR,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    parameters_json VARCHAR NOT NULL,
    starting_capital DOUBLE NOT NULL,
    cash DOUBLE NOT NULL,
    quantity DOUBLE NOT NULL DEFAULT 0,
    average_cost DOUBLE NOT NULL DEFAULT 0,
    peak_equity DOUBLE,
    daily_start_date DATE,
    daily_start_equity DOUBLE,
    last_processed_timestamp TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id)
);

CREATE TABLE IF NOT EXISTS scheduled_operations (
    operation_id VARCHAR NOT NULL,
    operation_type VARCHAR NOT NULL,
    subject_id VARCHAR,
    status VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    details_json VARCHAR NOT NULL,
    error_message VARCHAR,
    PRIMARY KEY (operation_id)
);

ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS peak_equity DOUBLE;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS daily_start_date DATE;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS daily_start_equity DOUBLE;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS approved_run_id VARCHAR;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS entry_timestamp TIMESTAMPTZ;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS entry_reason VARCHAR;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS entry_cost_pool DOUBLE DEFAULT 0;
ALTER TABLE paper_sessions ADD COLUMN IF NOT EXISTS entry_execution_cost_pool DOUBLE DEFAULT 0;

CREATE TABLE IF NOT EXISTS paper_pending_targets (
    session_id VARCHAR NOT NULL,
    signal_timestamp TIMESTAMPTZ NOT NULL,
    target_position DOUBLE NOT NULL,
    signal VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    feature_snapshot VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id)
);

CREATE TABLE IF NOT EXISTS paper_portfolio_sessions (
    session_id VARCHAR NOT NULL,
    approved_run_id VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    universe_snapshot_id VARCHAR NOT NULL,
    benchmark_symbol VARCHAR,
    timeframe VARCHAR NOT NULL,
    parameters_json VARCHAR NOT NULL,
    starting_capital DOUBLE NOT NULL,
    cash DOUBLE NOT NULL,
    peak_equity DOUBLE NOT NULL,
    daily_start_date DATE,
    daily_start_equity DOUBLE,
    last_processed_timestamp TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id)
);

CREATE TABLE IF NOT EXISTS paper_portfolio_holdings (
    session_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    quantity DOUBLE NOT NULL,
    average_cost DOUBLE NOT NULL,
    entry_timestamp TIMESTAMPTZ,
    entry_reason VARCHAR,
      entry_cost_pool DOUBLE NOT NULL DEFAULT 0,
      entry_execution_cost_pool DOUBLE NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id, symbol)
  );

ALTER TABLE paper_portfolio_holdings ADD COLUMN IF NOT EXISTS entry_execution_cost_pool DOUBLE DEFAULT 0;

CREATE TABLE IF NOT EXISTS paper_portfolio_pending_targets (
    session_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    signal_timestamp TIMESTAMPTZ NOT NULL,
    target_weight DOUBLE NOT NULL,
    signal VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    score DOUBLE,
    rank DOUBLE,
    feature_snapshot VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id, symbol)
);

CREATE TABLE IF NOT EXISTS market_calendar_versions (
    calendar_id VARCHAR NOT NULL,
    market VARCHAR NOT NULL,
    timezone VARCHAR NOT NULL,
    session_open VARCHAR NOT NULL,
    session_close VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    verified_through DATE NOT NULL,
    content_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (calendar_id)
);

CREATE TABLE IF NOT EXISTS market_session_overrides (
    calendar_id VARCHAR NOT NULL,
    session_date DATE NOT NULL,
    override_type VARCHAR NOT NULL,
    start_time VARCHAR,
    end_time VARCHAR,
    reason VARCHAR NOT NULL,
    PRIMARY KEY (calendar_id, session_date, override_type, start_time)
);

ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS trade_overlap DOUBLE;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS regime_correlation_json VARCHAR;
ALTER TABLE portfolio_rebalances ADD COLUMN IF NOT EXISTS replacement_pct DOUBLE DEFAULT 0;
ALTER TABLE fill_cost_components ADD COLUMN IF NOT EXISTS timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS quantity DOUBLE DEFAULT 0;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS price DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS average_cost DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS gross_pnl DOUBLE DEFAULT 0;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS entry_timestamp TIMESTAMPTZ;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS holding_period_days DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS exit_classification VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS run_id_a VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS run_id_b VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS symbol_a VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS symbol_b VARCHAR;
ALTER TABLE fill_cost_components ADD COLUMN IF NOT EXISTS ipft DOUBLE DEFAULT 0;
ALTER TABLE fill_cost_components ADD COLUMN IF NOT EXISTS dp_charge DOUBLE DEFAULT 0;

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id VARCHAR NOT NULL,
    run_id VARCHAR,
    experiment_id VARCHAR,
    symbol VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    requested_notional DOUBLE NOT NULL,
    approved_notional DOUBLE NOT NULL,
    reasons_json JSON NOT NULL,
    policy_json JSON NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (decision_id)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id VARCHAR NOT NULL PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    action_type VARCHAR NOT NULL,
    ex_date DATE NOT NULL,
    record_date DATE,
    announcement_date DATE,
    payment_date DATE,
    share_multiplier DOUBLE NOT NULL DEFAULT 1.0,
    bonus_new_shares DOUBLE,
    bonus_existing_shares DOUBLE,
    old_face_value DOUBLE,
    new_face_value DOUBLE,
    dividend_amount DOUBLE DEFAULT 0.0,
    currency VARCHAR DEFAULT 'INR',
    purpose VARCHAR,
    source VARCHAR NOT NULL,
    source_event_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'ACTIVE',
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS action_id VARCHAR;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS share_multiplier DOUBLE DEFAULT 1.0;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS bonus_new_shares DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS bonus_existing_shares DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS old_face_value DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS new_face_value DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS source_event_id VARCHAR;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'ACTIVE';

CREATE TABLE IF NOT EXISTS market_ticks (
    exchange VARCHAR NOT NULL,
    token VARCHAR NOT NULL,
    symbol VARCHAR,
    mode VARCHAR NOT NULL,
    exchange_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    sequence_number BIGINT,
    ltp DOUBLE NOT NULL,
    volume BIGINT,
    open_interest BIGINT,
    feed_latency_ms DOUBLE,
    PRIMARY KEY (exchange, token, received_at, sequence_number)
);

CREATE TABLE IF NOT EXISTS market_bars (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume DOUBLE NOT NULL,
    turnover DOUBLE NOT NULL,
    is_final BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, exchange, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS source_basis_detections (
    detection_id VARCHAR NOT NULL PRIMARY KEY,
    dataset_id VARCHAR,
    instrument_id VARCHAR NOT NULL,
    symbol VARCHAR,
    action_ids VARCHAR NOT NULL,
    action_types VARCHAR NOT NULL,
    ex_date DATE NOT NULL,
    expected_multiplier DOUBLE NOT NULL,
    pre_close DOUBLE,
    ex_open DOUBLE,
    ex_close DOUBLE,
    observed_ratio DOUBLE,
    log_distance_raw DOUBLE,
    log_distance_adjusted DOUBLE,
    hypothesis_separation DOUBLE,
    missing_trading_sessions INTEGER,
    calendar_gap_days INTEGER,
    turnover_ratio DOUBLE,
    volume_ratio DOUBLE,
    detection VARCHAR NOT NULL,
    inferred_basis VARCHAR NOT NULL,
    evidence_strength DOUBLE NOT NULL,
    evidence_codes VARCHAR,
    reasons VARCHAR,
    policy_version VARCHAR NOT NULL,
    detector_version VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_semantics_admissions (
    admission_id VARCHAR NOT NULL PRIMARY KEY,
    dataset_id VARCHAR,
    instrument_id VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    price_adjustment VARCHAR NOT NULL,
    volume_adjustment VARCHAR NOT NULL,
    validation_status VARCHAR NOT NULL,
    pre_override_status VARCHAR,
    override_reason VARCHAR,
    evidence_strength DOUBLE NOT NULL,
    num_raw INTEGER NOT NULL DEFAULT 0,
    num_adjusted INTEGER NOT NULL DEFAULT 0,
    num_ambiguous INTEGER NOT NULL DEFAULT 0,
    num_insufficient INTEGER NOT NULL DEFAULT 0,
    semantics_hash VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    detector_version VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS index_constituents_pit (
    universe_name VARCHAR NOT NULL,
    instrument_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    token VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    effective_from DATE NOT NULL,
    effective_until DATE,
    known_from DATE,
    weight DOUBLE,
    inclusion_reason VARCHAR,
    exclusion_reason VARCHAR,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (universe_name, instrument_id, effective_from)
);


CREATE TABLE IF NOT EXISTS live_market_data_quarantine (
    quarantine_id VARCHAR NOT NULL PRIMARY KEY,
    token VARCHAR NOT NULL,
    symbol VARCHAR,
    exchange VARCHAR NOT NULL,
    tick_timestamp TIMESTAMPTZ NOT NULL,
    received_timestamp TIMESTAMPTZ NOT NULL,
    action VARCHAR NOT NULL,
    reasons VARCHAR NOT NULL,
    last_price DOUBLE,
    volume DOUBLE,
    raw_payload_json VARCHAR,
    quarantined_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS historical_market_data_quarantine (
    quarantine_id VARCHAR NOT NULL PRIMARY KEY,
    raw_dataset_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    raw_hash VARCHAR NOT NULL,
    malformed_row_count INTEGER NOT NULL,
    quarantined_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS historical_market_data_quarantine_issues (
    quarantine_id VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    event_timestamp TIMESTAMPTZ,
    reason_code VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (quarantine_id, source_row_number, reason_code)
);

ALTER TABLE strategy_runs ADD COLUMN IF NOT EXISTS starting_capital DOUBLE DEFAULT 100000.0;

CREATE TABLE IF NOT EXISTS experiment_families (
    experiment_family_id VARCHAR PRIMARY KEY,
    definition_hash VARCHAR NOT NULL,
    definition_json VARCHAR NOT NULL,
    maximum_trials BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS research_trials_log (
    trial_id VARCHAR PRIMARY KEY,
    experiment_family_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    trial_json VARCHAR NOT NULL,
    metrics_json VARCHAR,
    metrics_hash VARCHAR,
    error_message VARCHAR,
    invalidation_reason VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    parent_trial_id VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_trials_family_status ON research_trials_log(experiment_family_id, status);

