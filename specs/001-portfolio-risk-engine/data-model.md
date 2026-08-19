# Data Model

## Core Entities
- **TradeIntent**:
  - `symbol` (str)
  - `action` (Enum: BUY/SELL)
  - `quantity` (float)
  - `target_price` (float)
  - `stop_loss` (float)
- **RiskEvaluation**:
  - `intent` (TradeIntent)
  - `approved` (bool)
  - `rejection_reasons` (List[str])
- **PortfolioState**:
  - `cash` (float)
  - `positions` (Dict[str, Position])
  - `peak_equity` (float)
