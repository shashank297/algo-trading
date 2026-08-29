-- Phase 2.6: Immutable statistical robustness evaluation bundles.

CREATE TABLE IF NOT EXISTS strategy_robustness_evaluations (
    robustness_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    experiment_family_id VARCHAR,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    selected_trial_id VARCHAR,
    evidence_status VARCHAR NOT NULL,
    psr_json JSON NOT NULL,
    dsr_json JSON NOT NULL,
    bootstrap_json JSON NOT NULL,
    monte_carlo_json JSON NOT NULL,
    cost_stress_json JSON NOT NULL,
    execution_stress_json JSON NOT NULL,
    parameter_robustness_json JSON NOT NULL,
    nested_folds_json JSON NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    data_hash VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_robustness_lookup
    ON strategy_robustness_evaluations(strategy_name, strategy_version, run_id);
CREATE INDEX IF NOT EXISTS idx_robustness_family
    ON strategy_robustness_evaluations(experiment_family_id);
CREATE INDEX IF NOT EXISTS idx_robustness_evidence
    ON strategy_robustness_evaluations(evidence_hash);
