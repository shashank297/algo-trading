# Phase 2.7 conditional strategy evidence

Conditional strategy evidence is based only on OOS results and historical point-in-time context. Phase 2.7 does not select or allocate strategies.

Each persisted OOS equity observation is joined to the latest operational regime event and asset-state snapshot whose decision and persistence timestamps are no later than the observation timestamp. Missing context fails closed; no current or latest classification is substituted.

`available_at` is the completed strategy-run timestamp, not the market observation timestamp. Historical consumers must query `strategy_conditional_evidence` with `available_at <= decision_time`; no latest-evidence fallback is permitted.

The evidence hierarchy is global, strategy×regime, strategy×asset cluster, and strategy×regime×asset cluster. Fine-grained cells remain visible but are marked insufficient unless they meet the versioned sample policy. The deterministic shrinkage formula is `n / (n + prior) * raw + prior / (n + prior) * global`.

Net return is reconstructed from the persisted OOS gross return and its realized `walk_forward_trade_attribution` cost. Cost-model identity is resolved only from the unique successful `research_trials_log` record whose immutable metrics link it to the run. Missing or ambiguous trial, version, hash, strategy-version, or data-hash lineage fails closed; current configuration is never used as a historical fallback.
