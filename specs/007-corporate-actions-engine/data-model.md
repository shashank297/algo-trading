# Data Model & Interface Contracts: Corporate Actions

## 1. PriceAdjustment Enum

```python
class PriceAdjustment(str, Enum):
    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    BACK_ADJUSTED = "BACK_ADJUSTED"
    TOTAL_RETURN = "TOTAL_RETURN"
```

## 2. Database Schema (`corporate_actions`)

```sql
CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id VARCHAR NOT NULL PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    action_type VARCHAR NOT NULL,        -- 'SPLIT', 'BONUS', 'CONSOLIDATION', 'DIVIDEND'
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
```

## 3. Python Data Model

```python
@dataclass(frozen=True)
class CorporateActionRecord:
    action_id: str
    symbol: str
    action_type: str
    ex_date: date
    share_multiplier: float = 1.0
    exchange: str = "NSE"
    record_date: date | None = None
    announcement_date: date | None = None
    payment_date: date | None = None
    bonus_new_shares: float | None = None
    bonus_existing_shares: float | None = None
    old_face_value: float | None = None
    new_face_value: float | None = None
    dividend_amount: float = 0.0
    currency: str = "INR"
    purpose: str | None = None
    source: str = "NSE"
    source_event_id: str | None = None
    status: str = "ACTIVE"
```
