-- Phases 2.8-2.10: immutable causal scorecards, selector decisions, and meta replay.

CREATE TABLE IF NOT EXISTS strategy_scorecards (
    scorecard_id VARCHAR PRIMARY KEY,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    horizon VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    global_evidence_id VARCHAR,
    conditional_evidence_id VARCHAR,
    eligibility_status VARCHAR NOT NULL,
    rejection_reasons_json JSON NOT NULL,
    performance_score DOUBLE NOT NULL,
    downside_score DOUBLE NOT NULL,
    fold_consistency_score DOUBLE NOT NULL,
    parameter_robustness_score DOUBLE NOT NULL,
    cost_robustness_score DOUBLE NOT NULL,
    breadth_score DOUBLE NOT NULL,
    paper_score DOUBLE NOT NULL,
    regime_compatibility_score DOUBLE NOT NULL,
    asset_compatibility_score DOUBLE NOT NULL,
    drawdown_penalty DOUBLE NOT NULL,
    turnover_penalty DOUBLE NOT NULL,
    correlation_penalty DOUBLE NOT NULL,
    capacity_penalty DOUBLE NOT NULL,
    uncertainty_penalty DOUBLE NOT NULL,
    overall_score DOUBLE NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    scorecard_version VARCHAR NOT NULL,
    scorecard_policy_version VARCHAR NOT NULL,
    scorecard_policy_hash VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    evidence_ids_json JSON NOT NULL,
    explanation_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_strategy_scorecards_cutoff ON strategy_scorecards(horizon, available_at);
CREATE INDEX IF NOT EXISTS idx_strategy_scorecards_strategy_cutoff ON strategy_scorecards(strategy_name, strategy_version, available_at);
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS performance_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS downside_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS fold_consistency_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS parameter_robustness_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS cost_robustness_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS breadth_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS paper_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS regime_compatibility_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS asset_compatibility_score DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS drawdown_penalty DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS turnover_penalty DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS correlation_penalty DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS capacity_penalty DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS uncertainty_penalty DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS scorecard_policy_version VARCHAR DEFAULT 'unknown';
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS scorecard_policy_hash VARCHAR DEFAULT 'unknown';
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS evidence_ids_json JSON DEFAULT '{}';
ALTER TABLE strategy_scorecards ADD COLUMN IF NOT EXISTS explanation_json JSON DEFAULT '{}';

CREATE TABLE IF NOT EXISTS selector_decisions (
    selector_decision_id VARCHAR PRIMARY KEY,
    decision_time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL,
    horizon VARCHAR NOT NULL,
    market_regime VARCHAR,
    regime_confidence DOUBLE NOT NULL,
    asset_cluster VARCHAR,
    decision VARCHAR NOT NULL,
    selected_strategies_json JSON NOT NULL,
    weights_json JSON NOT NULL,
    candidate_scorecards_json JSON NOT NULL,
    current_incumbent_strategy VARCHAR,
    expected_benefit_estimate DOUBLE NOT NULL,
    uncertainty DOUBLE NOT NULL,
    switch_required BOOLEAN NOT NULL,
    estimated_switch_cost DOUBLE NOT NULL,
    switch_buffer DOUBLE NOT NULL,
    decision_reasons_json JSON NOT NULL,
    rejection_reasons_json JSON NOT NULL,
    selector_policy_version VARCHAR NOT NULL,
    selector_policy_hash VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    evidence_ids_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (decision IN ('SELECT', 'ENSEMBLE', 'ABSTAIN'))
);
CREATE INDEX IF NOT EXISTS idx_selector_decisions_time ON selector_decisions(symbol, horizon, decision_time);
ALTER TABLE selector_decisions ADD COLUMN IF NOT EXISTS regime_confidence DOUBLE DEFAULT 0.0;
ALTER TABLE selector_decisions ADD COLUMN IF NOT EXISTS current_incumbent_strategy VARCHAR;
ALTER TABLE selector_decisions ADD COLUMN IF NOT EXISTS expected_benefit_estimate DOUBLE DEFAULT 0.0;
ALTER TABLE selector_decisions ADD COLUMN IF NOT EXISTS selector_policy_hash VARCHAR DEFAULT 'unknown';
ALTER TABLE selector_decisions ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE selector_decisions ADD COLUMN IF NOT EXISTS evidence_ids_json JSON DEFAULT '{}';

CREATE TABLE IF NOT EXISTS meta_selector_runs (
    meta_run_id VARCHAR PRIMARY KEY,
    policy_version VARCHAR NOT NULL,
    selector_policy_version VARCHAR NOT NULL,
    selector_policy_hash VARCHAR NOT NULL,
    scorecard_policy_version VARCHAR,
    meta_split VARCHAR NOT NULL,
    purge_periods BIGINT NOT NULL,
    embargo_periods BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    verdict VARCHAR NOT NULL,
    metrics_json JSON NOT NULL,
    baselines_json JSON NOT NULL,
    stress_results_json JSON NOT NULL,
    attribution_json JSON NOT NULL,
    checkpoint_json JSON DEFAULT '{}',
    checkpoint_hash VARCHAR DEFAULT 'unknown',
    evidence_hash VARCHAR NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE meta_selector_runs ADD COLUMN IF NOT EXISTS checkpoint_json JSON DEFAULT '{}';
ALTER TABLE meta_selector_runs ADD COLUMN IF NOT EXISTS checkpoint_hash VARCHAR DEFAULT 'unknown';

CREATE TABLE IF NOT EXISTS meta_selector_equity_curve (
    meta_run_id VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    equity DOUBLE NOT NULL,
    net_return DOUBLE NOT NULL,
    drawdown DOUBLE NOT NULL,
    position DOUBLE NOT NULL,
    decision VARCHAR NOT NULL,
    PRIMARY KEY(meta_run_id, timestamp)
);

CREATE TABLE IF NOT EXISTS meta_selector_decisions (
    meta_run_id VARCHAR NOT NULL,
    selector_decision_id VARCHAR NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    PRIMARY KEY(meta_run_id, selector_decision_id)
);

CREATE TABLE IF NOT EXISTS meta_selector_switches (
    meta_run_id VARCHAR NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    old_strategy VARCHAR,
    new_strategy VARCHAR,
    switching_cost DOUBLE NOT NULL,
    sells_first_json JSON NOT NULL,
    buys_after_sells_json JSON NOT NULL,
    PRIMARY KEY(meta_run_id, decision_time, new_strategy)
);

CREATE TABLE IF NOT EXISTS meta_selector_attribution (
    meta_run_id VARCHAR NOT NULL,
    attribution_type VARCHAR NOT NULL,
    value DOUBLE NOT NULL,
    PRIMARY KEY(meta_run_id, attribution_type)
);
