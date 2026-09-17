# Phase 1 Data Model: Platform Remediation & Audit Controls

**Feature**: `009-platform-audit-remediation`

## Entity Relationships & Data Structures

### 1. Risk Evaluation Contract (`risk/models.py`)
```python
@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    requested_notional: float
    capital: float
    current_position_notional: float = 0.0
    ...

    @property
    def is_same_direction_increase(self) -> bool:
        """True if the proposed trade increases the magnitude of the current position in the same direction."""
        if self.current_position_notional == 0:
            return True
        return (self.current_position_notional > 0 and self.requested_notional > 0) or \
               (self.current_position_notional < 0 and self.requested_notional < 0)
```

### 2. External Approval Evidence Contract (`trading_stack/approval.py`)
```python
@dataclass(frozen=True)
class ExternalApprovalEvidence:
    approval_id: str
    approval_type: str
    subject_type: str
    run_id: str
    strategy_name: str
    requested_stage: str
    approved_stage: str
    approved_by_type: str
    approved_by_identifier: str
    approved_at: datetime
    expires_at: datetime
    scope: str
    status: str
    foundation_certification_id: str | None = None
    risk_policy_id: str | None = None
    risk_policy_hash: str | None = None
    code_sha: str | None = None
    evidence_hash: str | None = None
```

### 3. PIT Instrument Alias Schema (`tools/nifty200_pit/models.py`)
```python
@dataclass(frozen=True)
class InstrumentAlias:
    instrument_id: str
    symbol: str
    alias_symbol: str
    valid_from: date
    valid_until: date | None
    confidence: str # 'CERTIFIED' | 'MANUAL_REVIEW'

    def __post_init__(self):
        if self.valid_until is not None and self.valid_from >= self.valid_until:
            raise ValueError(f"Inverted alias validity interval: {self.valid_from} >= {self.valid_until}")
```
