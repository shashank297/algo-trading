# Interface Contract: External Approval & Promotion Engine

## Canonical Payload Specification

The payload to be signed is constructed by serializing the canonical fields into a JSON string with sorted keys and no whitespace:

```json
{
  "approved_at": "2026-09-18T00:00:00Z",
  "approved_by": "Risk Committee Chair",
  "approved_by_type": "BOARD",
  "code_sha": "a8f383149187b8d0bbfb23253ba81c464ec8563f",
  "evidence_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "expires_at": "2026-09-25T00:00:00Z",
  "foundation_cert_id": "CERT-FOUNDATION-2026-01",
  "risk_policy_hash": "c8f1e6b8f...",
  "run_id": "RUN-20260918-001",
  "scope": "PAPER_TRADING",
  "stage": "PAPER_ACTIVE",
  "strategy_name": "vwap_momentum",
  "subject_type": "STRATEGY_RUN"
}
```

## Signing & Verification

- **Algorithm**: Ed25519 (PureEdDSA over Curve25519)
- **Input**: SHA-512 implicitly applied in Ed25519 over UTF-8 bytes of canonical JSON string.
- **Output**: 64-byte raw signature, Base64-encoded.
- **Verification**:
  - Locate public key corresponding to `issuer_key_id` in trusted issuers registry.
  - Verify signature against canonical JSON bytes.
  - Assert that `expires_at > current_utc_time`.
  - Assert that `approved_at <= current_utc_time`.
  - Fail closed if key is missing, revoked, signature is invalid, or any execution context field mismatches.
