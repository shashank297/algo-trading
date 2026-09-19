# External Approval Security Remediation Report

This report documents the design, cryptographic architecture, and enforcement mechanisms implemented to secure the promotion boundary between backtesting and paper trading execution.

## 1. Cryptographic Signature Architecture

### Asymmetric Algorithm
- **Algorithm**: Ed25519 (PureEdDSA over Curve25519, standard RFC 8032)
- **Library**: `cryptography.hazmat.primitives.asymmetric.ed25519`
- **Keys**: 32-byte public keys encoded in standard Base64; signatures are 64 bytes in Base64.
- **Security Guarantee**: Non-repudiation and cryptographic integrity. Approval signatures can only be minted by authorized human/board authorities possessing the private key outside the repository. No private keys are ever stored or committed in the repository.

### Canonical Payload Specification
To ensure deterministic verification across platforms, timestamps, and architectures, the signed payload is constructed using canonical JSON serialization:
- Keys are sorted alphabetically.
- Separators are canonical without whitespace: `( ",", ":" )`.
- Timestamps (`approved_at`, `expires_at`) are strictly normalized to UTC ISO-8601 strings.
- Encoded as UTF-8 bytes.

### Included Fields in Signed Payload
The following 19 fields form the canonical signed payload:
1. `approved_at` (Normalized UTC ISO string)
2. `approved_by_identifier` (Human/Board authority name/title)
3. `approved_by_type` (`HUMAN` or `BOARD`)
4. `approved_stage` (`PAPER_CANDIDATE` or `PAPER_ACTIVE`)
5. `code_sha` (Target Git commit SHA)
6. `evidence_hash` (Target research data snapshot digest)
7. `expires_at` (Normalized UTC ISO string)
8. `foundation_certification_id` (Active foundation certification bundle)
9. `issuer_key_id` (Identifier of authorized verification key)
10. `promotion_review_id` (Promotion review record ID)
11. `requested_stage` (Target requested stage)
12. `risk_policy_hash` (Active risk policy contract hash)
13. `risk_policy_id` (Active risk policy identifier)
14. `run_id` (Specific strategy run ID)
15. `scope` (Authorization scope, e.g. `PAPER_TRADING`)
16. `status` (Must be `ACTIVE`)
17. `strategy_candidate_id` (Candidate identifier if applicable)
18. `strategy_name` (Strategy name)
19. `subject_type` (`STRATEGY_RUN` or `STRATEGY_CANDIDATE`)

### Excluded Fields
- **`signature`**: Excluded to avoid circular / self-referential signature generation.
- **`approval_id`**: Excluded because it is a database record identifier assigned upon persistence and is not part of the immutable governance authorization content.

---

## 2. Trusted Issuer Configuration & Key Lookup

Trusted verification keys are configured out-of-band in `config/trusted_issuers.yaml`.

```yaml
issuers:
  board-governance-primary:
    issuer_name: "Investment & Risk Oversight Committee"
    issuer_type: "BOARD"
    public_key_ed25519_base64: "Z68M37YOam03RkxgsZMVSrA2/m/tbqtCIjd72M+JOeo="
    status: "ACTIVE"
    valid_from: "2026-01-01T00:00:00Z"
    expires_at: "2028-01-01T00:00:00Z"
```

### Key Lifecycle & Revocation
The verifier evaluates key metadata during signature verification:
- Rejects unknown key IDs: `PermissionError("Unknown or untrusted approval issuer key ID: ...")`
- Rejects non-active keys: `PermissionError("Approval issuer key '...' is not active (status: 'REVOKED')")`
- Rejects unstarted or expired keys: `PermissionError("Approval issuer key '...' has expired")`

---

## 3. Callsite Binding & Fail-Closed Gates

`PromotionEngine.assert_paper_authorized()` enforces strict fail-closed binding for all 9 execution context parameters:
1. `run_id`: Exact match with executing run.
2. `strategy_name`: Exact match with executing strategy.
3. `stage`: Must match the human-approved review stage (`PAPER_CANDIDATE` or `PAPER_ACTIVE`). Candidate evidence cannot authorize active paper trading.
4. `foundation_certification_id`: Resolved from `strategy_runs.frame_certification_id` or passed explicitly.
5. `risk_policy_hash`: Resolved from canonical risk policy configuration or passed explicitly.
6. `code_sha`: Resolved from Git `HEAD` or environment variable `CODE_SHA`.
7. `evidence_hash`: Resolved from `strategy_runs.data_hash`.
8. `scope`: Bound to execution scope (`PAPER_TRADING`).
9. `subject_type`: Bound to execution subject (`STRATEGY_RUN`).

### Fail-Closed Behavior
If any of these 9 fields cannot be authoritatively resolved, the promotion engine immediately raises `PermissionError` and halts execution.

---

## 4. Test Verification Summary

The test suite in `tests/test_approval_regression.py` validates 19 scenarios:
- Stage mismatch rejection (`PAPER_CANDIDATE` cannot authorize `PAPER_ACTIVE`).
- Identifier filtering (AI/bot identifiers rejected).
- Completeness validation (every required field missing causes fail-closed rejection).
- Temporal bounds (future approvals rejected, expired approvals rejected, inverted timestamps rejected).
- Status checks (revoked approvals rejected).
- Target matching (mismatched run ID, strategy name, risk hash, code SHA, evidence hash, scope, subject type).
- Tamper detection (altering any signed field invalidates Ed25519 signature).
- Key store checks (unknown key ID, expired key, revoked key rejected).
- Full end-to-end integration via `PromotionEngine.assert_paper_authorized()` with DuckDB persistence.
