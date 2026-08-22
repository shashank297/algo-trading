from datetime import date, datetime, timezone

import pandas as pd
import pytest

from data_platform.contracts import (
    BarRequest,
    DatasetSnapshot,
    Instrument,
    OrderSide,
    PriceAdjustment,
    RawMarketDataset,
    compute_raw_provider_hash,
)
from risk.engine import RiskEngine
from risk.models import RiskPolicy, TradeProposal
from risk.validators import (
    DailyLossValidator,
    DrawdownValidator,
    MaxPositionsValidator,
    PortfolioExposureValidator,
    PositionSizeValidator,
    RequiredRiskStateValidator,
    RiskValidator,
    SectorExposureValidator,
    TurnoverLiquidityValidator,
    VaRValidator,
)
from storage.duckdb_manager import DuckDBManager
from storage.integrity import DatabaseIntegrityValidator, IntegrityError
from trading_stack.costs import (
    IndianDeliveryCostSchedule,
    InvalidExecutionPriceError,
    UnexecutableOrderError,
    get_cost_schedule,
)
from trading_stack.domain import AssetClass, OpeningTickObservation, infer_asset_class


def complete_proposal(**overrides):
    values = {
        "symbol": "TEST",
        "requested_notional": 10_000.0,
        "capital": 100_000.0,
        "current_position_notional": 0.0,
        "current_gross_exposure": 0.0,
        "current_sector_exposure": 0.0,
        "daily_pnl": 0.0,
        "current_drawdown": 0.0,
        "open_position_count": 0,
        "daily_turnover_crore": 10.0,
        "estimated_portfolio_var_pct": 0.001,
    }
    values.update(overrides)
    return TradeProposal(**values)


def test_risk_validators_cover_limits_and_reductions():
    policy = RiskPolicy(max_position_pct=0.05, max_gross_exposure_pct=0.10, max_sector_exposure_pct=0.05,
                        max_daily_loss_pct=0.01, max_drawdown_pct=0.10, max_open_positions=1,
                        min_liquidity_crore=5.0, max_var_pct=0.01)
    proposal = complete_proposal(
        requested_notional=20_000.0, current_gross_exposure=10_000.0,
        current_sector_exposure=5_000.0, daily_pnl=-2_000.0, current_drawdown=0.2,
        open_position_count=1, daily_turnover_crore=1.0, estimated_portfolio_var_pct=0.02,
    )
    validators = [RequiredRiskStateValidator(), PositionSizeValidator(), PortfolioExposureValidator(),
                 SectorExposureValidator(), DailyLossValidator(), DrawdownValidator(), MaxPositionsValidator(),
                 TurnoverLiquidityValidator(), VaRValidator()]
    results = [validator.evaluate(proposal, policy) for validator in validators]
    assert all(result[0] >= 0 for result in results)

    reduction = complete_proposal(order_side=OrderSide.SELL, current_position_notional=20_000.0,
                                  requested_notional=20_000.0)
    assert reduction.is_pure_risk_reduction
    assert all(validator.evaluate(reduction, policy)[0] == reduction.requested_notional for validator in validators)


def test_risk_engine_rejects_missing_and_invalid_state():
    missing = complete_proposal(current_gross_exposure=None)
    assert RiskEngine().evaluate(missing).action.value == "REJECT"
    with pytest.raises(ValueError):
        complete_proposal(open_position_count=1.5)


def test_cost_schedule_edges_and_historical_resolution():
    schedule = IndianDeliveryCostSchedule(max_allowed_drag_bps=1.0)
    assert schedule.calculate(0, OrderSide.BUY).total == 0
    assert schedule.calculate(10_000, OrderSide.SELL).dp_charge > 0
    assert get_cost_schedule(date(2011, 1, 1)).version.endswith("2010-01")
    assert get_cost_schedule(date(2000, 1, 1)).version.endswith("2010-01")
    assert get_cost_schedule(date(2025, 1, 1)).version.endswith("2024-10")
    with pytest.raises(InvalidExecutionPriceError):
        schedule.execution_price(0, OrderSide.BUY)
    with pytest.raises(UnexecutableOrderError):
        schedule.execution_price(100, OrderSide.BUY, participation=-1)
    with pytest.raises(UnexecutableOrderError):
        schedule.execution_price(100, OrderSide.BUY, participation=0.05)


def test_opening_observation_and_provider_contract_validation():
    observation = OpeningTickObservation("TEST", "NSE", "1", 100.0,
                                         exchange_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                         received_at_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
                                         sequence_number=1)
    assert observation.received_at_utc > observation.exchange_timestamp
    with pytest.raises(ValueError):
        OpeningTickObservation("", "NSE", "1", 100.0, datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        OpeningTickObservation("TEST", "NSE", "1", 0.0, datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        OpeningTickObservation("TEST", "NSE", "1", 100.0, datetime.now(timezone.utc),
                               datetime.now(timezone.utc).replace(year=2020))
    with pytest.raises(ValueError):
        OpeningTickObservation("TEST", "NSE", "1", float("nan"), datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        OpeningTickObservation("TEST", "NSE", "1", 100.0, datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        OpeningTickObservation("TEST", "NSE", "1", 100.0, datetime.now(timezone.utc), sequence_number=-1)
    with pytest.raises(ValueError):
        BarRequest(symbol="", exchange="NSE", timeframe="1d", start=datetime.now(timezone.utc), end=datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        BarRequest(symbol="TEST", exchange="", timeframe="1d", start=datetime.now(timezone.utc), end=datetime.now(timezone.utc))
    instrument = Instrument(canonical_symbol="TEST", exchange="NSE", provider_name="angel", provider_symbol="TEST")
    frame = pd.DataFrame({"timestamp": ["2026-01-01"], "open": [1], "high": [2], "low": [1], "close": [2], "volume": [1]})
    snapshot = DatasetSnapshot.from_bars(instrument=instrument, timeframe="1d", bars=frame,
                                         adjustment=PriceAdjustment.UNADJUSTED)
    assert snapshot.storage_metadata()["canonical_symbol"] == "TEST"
    with pytest.raises(ValueError):
        DatasetSnapshot.from_bars(instrument=instrument, timeframe="1d", bars=frame.drop(columns=["close"]))
    invalid_frame = frame.copy()
    invalid_frame["open"] = 0
    with pytest.raises(ValueError):
        DatasetSnapshot.from_bars(instrument=instrument, timeframe="1d", bars=invalid_frame)
    invalid_frame["volume"] = -1
    with pytest.raises(ValueError):
        DatasetSnapshot.from_bars(instrument=instrument, timeframe="1d", bars=invalid_frame)
    assert RawMarketDataset(
        "raw", "TEST", "NSE", "1d", "angel", None, None, None, "UTC",
        datetime.now(timezone.utc), "{}", "hash",
    ).bars_df.empty
    populated = RawMarketDataset(
        "raw", "TEST", "NSE", "1d", "angel", None, None, None, "UTC",
        datetime.now(timezone.utc), "{}", "hash", parsed_rows=({"close": 1},),
    )
    assert not populated.bars_df.empty
    assert compute_raw_provider_hash(b"x") == compute_raw_provider_hash("x")
    assert compute_raw_provider_hash(frame) == compute_raw_provider_hash(frame.copy())
    with pytest.raises(ValueError):
        Instrument(canonical_symbol="", exchange="NSE", provider_name="angel", provider_symbol="TEST")
    with pytest.raises(ValueError):
        Instrument(canonical_symbol="TEST", exchange="NSE", provider_name="", provider_symbol="TEST")
    with pytest.raises(ValueError):
        BarRequest(symbol="TEST", exchange="NSE", timeframe="", start=datetime.now(timezone.utc), end=datetime.now(timezone.utc))


def test_integrity_validator_empty_and_missing_tables():
    import duckdb
    conn = duckdb.connect(":memory:")
    validator = DatabaseIntegrityValidator(conn)
    results = validator.run_all_checks()
    assert len(results) == 6 and all(not result.passed for result in results)
    with pytest.raises(IntegrityError):
        validator.validate_or_raise()
    conn.close()


def test_integrity_validator_clean_migrated_database(tmp_path):
    db = DuckDBManager(str(tmp_path / "integrity.duckdb"))
    try:
        results = DatabaseIntegrityValidator(db.conn).validate_or_raise()
        assert len(results) == 6
    finally:
        db.close()


def test_integrity_validator_owned_connection_closes(tmp_path):
    path = str(tmp_path / "owned.duckdb")
    db = DuckDBManager(path)
    db.close()
    validator = DatabaseIntegrityValidator(path)
    validator.close()


def test_risk_validator_invalid_dimensions_are_rejected():
    policy = RiskPolicy()
    validator = RequiredRiskStateValidator()
    invalid_values = {
        "capital": 0.0,
        "requested_notional": -1.0,
        "current_gross_exposure": float("nan"),
        "current_sector_exposure": -1.0,
        "current_drawdown": float("inf"),
        "daily_turnover_crore": -1.0,
        "estimated_portfolio_var_pct": float("nan"),
    }
    for name, value in invalid_values.items():
        values = complete_proposal().model_dump()
        values[name] = value
        proposal = TradeProposal.model_construct(**values)
        approved, reasons = validator.evaluate(proposal, policy)
        assert approved == 0.0 and any(name in reason for reason in reasons)
    for name in ("current_gross_exposure", "current_sector_exposure", "daily_pnl", "current_drawdown",
                 "daily_turnover_crore", "estimated_portfolio_var_pct", "open_position_count"):
        proposal = TradeProposal.model_construct(**{**complete_proposal().model_dump(), name: None})
        _, reasons = validator.evaluate(proposal, policy)
        assert any(name in reason for reason in reasons)


def test_risk_validator_policy_branches():
    policy = RiskPolicy(max_position_pct=0.05, max_gross_exposure_pct=0.05, max_sector_exposure_pct=0.05,
                        max_daily_loss_pct=0.01, max_drawdown_pct=0.1, max_open_positions=1,
                        min_liquidity_crore=5.0, max_var_pct=0.01)
    cases = [
        (PositionSizeValidator(), complete_proposal(requested_notional=20_000.0), "notional_capped"),
        (PortfolioExposureValidator(), complete_proposal(current_gross_exposure=10_000.0), "gross_exposure"),
        (SectorExposureValidator(), complete_proposal(current_sector_exposure=10_000.0), "sector_exposure"),
        (DailyLossValidator(), complete_proposal(daily_pnl=-2_000.0), "DAILY_LOSS"),
        (DrawdownValidator(), complete_proposal(current_drawdown=0.2), "DRAWDOWN"),
        (MaxPositionsValidator(), complete_proposal(open_position_count=1), "max_open"),
        (TurnoverLiquidityValidator(), complete_proposal(daily_turnover_crore=1.0), "liquidity"),
        (VaRValidator(), complete_proposal(estimated_portfolio_var_pct=0.02), "var"),
    ]
    for validator, proposal, reason in cases:
        _, reasons = validator.evaluate(proposal, policy)
        assert reasons and any(reason.lower() in item.lower() for item in reasons)
    assert RiskValidator.evaluate(None, complete_proposal(), policy) is None


def test_asset_class_fallbacks():
    assert infer_asset_class("UNKNOWN", "EQ") == AssetClass.INDIA_EQUITY
    assert infer_asset_class("EUR/USD", "SPOT") == AssetClass.FOREX
