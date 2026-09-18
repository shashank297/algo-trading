# Phase 1 Data Model: Entities & Schemas

## 1. Approval Entities

### `ExternalApprovalEvidence`
Container representing an external governance approval for strategy stage promotion.

```python
class ExternalApprovalEvidence(BaseModel):
    approval_id: str
    run_id: str
    strategy_name: str
    stage: str  # e.g., "PAPER_ACTIVE"
    foundation_cert_id: str
    risk_policy_hash: str
    code_sha: str
    evidence_hash: str
    scope: str
    subject_type: str
    approved_by: str
    approved_by_type: Literal["HUMAN", "BOARD"]
    approved_at: datetime
    expires_at: datetime
    issuer_key_id: str
    signature: str  # Base64-encoded Ed25519 signature
```

### `TrustedIssuerKeyStore`
Configuration mapping issuer key identifiers to authorized public keys.

```yaml
trusted_issuers:
  board-key-primary:
    public_key_ed25519_base64: "MCowBQYDK2VwNyADI..."
    description: "Investment Committee Board Signer"
    status: "ACTIVE"
    expires_at: "2027-12-31T23:59:59Z"
```

---

## 2. PIT Historical Alias Entity

### `InstrumentAliasHistory`
Historical alias record tied to a durable `instrument_id`.

| Field | Type | Description |
|-------|------|-------------|
| `instrument_id` | `VARCHAR` | Durable canonical instrument identifier |
| `alias_symbol` | `VARCHAR` | Historical trading ticker |
| `exchange` | `VARCHAR` | Exchange (e.g. `NSE`) |
| `valid_from` | `DATE` | Start of validity (inclusive) |
| `valid_until` | `DATE` | End of validity (exclusive or date-bounded) |
| `source_url` | `VARCHAR` | Originating announcement or filing |
| `source_sha256` | `VARCHAR` | Hash of source document |
| `confidence` | `VARCHAR` | High / Medium / Low |
| `resolution_status`| `VARCHAR` | CERTIFIED / MANUAL_REVIEW / REJECTED |

---

## 3. Constituent Interval Entity

### `ConstituentInterval`
Representation of an instrument's active membership in the Nifty 200 index.

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `instrument_id` | `VARCHAR` | NOT NULL | Durable instrument ID |
| `effective_from` | `DATE` | NOT NULL | Start date (inclusive) |
| `effective_until` | `DATE` | NOT NULL | End date (exclusive), MUST satisfy `effective_from < effective_until` |
| `provenance_id` | `VARCHAR` | NOT NULL | Linked canonical event or anchor |
