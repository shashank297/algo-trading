# Phase 2.5 Data Model

- `AssetStatePolicy`: versioned windows, weights, normalization targets, eligibility limits, cluster rules,
  rule order, and confidence behavior. Canonical JSON produces `policy_hash`.
- `CertifiedBarEvidence`: exact dataset, content hash, DQ certification, dataset/bar availability,
  timeframe, causal cutoff, and integrity outcome for stock or benchmark bars.
- `PITMetadataEvidence`: optional provenance-bound sector/market-cap value with effective and knowledge time.
- `PITEarningsEventEvidence`: optional provenance-bound earnings timestamp with knowledge time.
- `AssetStateFeatures`: raw causal calculations and derived scores; unavailable fields remain `None`.
- `AssetStateSnapshot`: immutable decision context, features, cluster/confidence, eligibility/reasons,
  evidence manifest/hashes, model/policy identity, and audit-only creation time.
- `asset_state_snapshots`: one immutable row per deterministic `asset_state_id`, with searchable scalar
  columns and canonical JSON for complete features and evidence.

The evidence hash is SHA-256 of canonical sorted JSON. `asset_state_id` is SHA-256 of symbol, exchange,
context, as-of date, normalized decision time, evidence hash, model version, policy version, and policy hash.

