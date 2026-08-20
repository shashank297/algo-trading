-- Migration 001: Core Platform Schema Baseline
-- Contains complete baseline relational schema for Algo Trading Platform

CREATE TABLE IF NOT EXISTS instrument_master (
    token VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    name VARCHAR,
    expiry VARCHAR,
    strike DOUBLE,
    lotsize INTEGER,
    instrumenttype VARCHAR,
    exch_seg VARCHAR NOT NULL,
    tick_size DOUBLE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (token, exch_seg)
);

CREATE TABLE IF NOT EXISTS historical_candles (
    symbol VARCHAR NOT NULL,
    token VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume BIGINT NOT NULL,
    adjustment VARCHAR NOT NULL DEFAULT 'UNADJUSTED',
    provider_name VARCHAR,
    dataset_id VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS market_data_state (
    state_id INTEGER NOT NULL DEFAULT 1,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (state_id)
);

INSERT OR IGNORE INTO market_data_state (state_id, revision) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS download_log (
    id INTEGER,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    from_date TIMESTAMP,
    to_date TIMESTAMP,
    candles_fetched INTEGER,
    candles_inserted INTEGER,
    status VARCHAR,
    error_message VARCHAR,
    duration_sec DOUBLE,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quality_report (
    id INTEGER,
    symbol VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    dataset_id VARCHAR,
    check_type VARCHAR NOT NULL,
    issue_count INTEGER,
    details VARCHAR,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_universe (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    timezone VARCHAR NOT NULL,
    session_open VARCHAR NOT NULL,
    session_close VARCHAR NOT NULL,
    tradable BOOLEAN NOT NULL DEFAULT TRUE,
    lot_size INTEGER NOT NULL DEFAULT 1,
    tick_size DOUBLE NOT NULL DEFAULT 0.01,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, exchange)
);

CREATE TABLE IF NOT EXISTS feature_store (
    symbol VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    feature_group VARCHAR NOT NULL,
    feature_name VARCHAR NOT NULL,
    feature_value DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, timestamp, feature_group, feature_name)
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    mode VARCHAR NOT NULL,
    parameters_json VARCHAR NOT NULL,
    data_hash VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    notes VARCHAR,
    starting_capital DOUBLE DEFAULT 100000.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS strategy_metrics (
    run_id VARCHAR NOT NULL,
    metric_name VARCHAR NOT NULL,
    metric_value DOUBLE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, metric_name)
);

CREATE TABLE IF NOT EXISTS strategy_orders (
    order_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    quantity DOUBLE NOT NULL,
    order_type VARCHAR NOT NULL,
    time_in_force VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    requested_at TIMESTAMP NOT NULL,
    filled_at TIMESTAMP,
    limit_price DOUBLE,
    stop_price DOUBLE,
    average_fill_price DOUBLE,
    slippage_bps DOUBLE NOT NULL DEFAULT 0,
    fees DOUBLE NOT NULL DEFAULT 0,
    metadata_json VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (order_id)
);

CREATE TABLE IF NOT EXISTS strategy_fills (
    fill_id VARCHAR NOT NULL,
    order_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    quantity DOUBLE NOT NULL,
    price DOUBLE NOT NULL,
    side VARCHAR NOT NULL,
    fill_type VARCHAR NOT NULL,
    fees DOUBLE NOT NULL DEFAULT 0,
    slippage_bps DOUBLE NOT NULL DEFAULT 0,
    metadata_json VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fill_id)
);

CREATE TABLE IF NOT EXISTS paper_reconciliation (
    run_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    expected_orders INTEGER NOT NULL,
    submitted_orders INTEGER NOT NULL,
    filled_orders INTEGER NOT NULL,
    rejected_orders INTEGER NOT NULL,
    pnl DOUBLE NOT NULL,
    drift DOUBLE NOT NULL,
    notes VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, trade_date)
);

CREATE TABLE IF NOT EXISTS market_datasets (
    dataset_id VARCHAR NOT NULL PRIMARY KEY,
    parent_dataset_id VARCHAR,
    dataset_stage VARCHAR NOT NULL DEFAULT 'RAW',
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
    reasons_json JSON NOT NULL,
    policy_json JSON NOT NULL,
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

CREATE TABLE IF NOT EXISTS market_raw_packets (
    packet_id VARCHAR NOT NULL PRIMARY KEY,
    token VARCHAR,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    raw_bytes BLOB NOT NULL,
    packet_len INTEGER NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
