from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping

from data_platform.contracts import OrderSide


class ExecutionReasonCode(str, Enum):
    """Machine-readable execution policy outcome and rejection codes."""

    MAX_EXECUTION_DRAG_EXCEEDED = "MAX_EXECUTION_DRAG_EXCEEDED"
    MAX_PARTICIPATION_EXCEEDED = "MAX_PARTICIPATION_EXCEEDED"
    INVALID_EXECUTION_PRICE = "INVALID_EXECUTION_PRICE"
    ORDER_RESIZED_FOR_LIQUIDITY = "ORDER_RESIZED_FOR_LIQUIDITY"


class UnexecutableOrderError(RuntimeError):
    """Raised when execution drag or participation exceeds executable policy thresholds."""

    def __init__(
        self,
        reason_code: ExecutionReasonCode | str,
        estimated_drag_bps: float,
        max_drag_bps: float,
        participation: float | None = None,
    ) -> None:
        self.reason_code = str(getattr(reason_code, "value", reason_code))
        self.estimated_drag_bps = float(estimated_drag_bps)
        self.max_drag_bps = float(max_drag_bps)
        self.participation = float(participation) if participation is not None else None
        super().__init__(
            f"Execution rejected ({self.reason_code}): estimated drag {self.estimated_drag_bps:.2f} bps "
            f"exceeds limit {self.max_drag_bps:.2f} bps (participation={self.participation})"
        )


class InvalidExecutionPriceError(RuntimeError):
    """Raised when execution price calculation violates non-negativity or finiteness."""

    pass


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    exchange_transaction: float
    sebi: float
    ipft: float
    dp_charge: float
    gst: float
    stamp_duty: float
    spread: float
    slippage: float
    market_impact: float

    @property
    def statutory_and_broker_fees(self) -> float:
        return (
            self.brokerage + self.stt + self.exchange_transaction + self.sebi
            + self.ipft + self.dp_charge + self.gst + self.stamp_duty
        )

    @property
    def execution_drag(self) -> float:
        """Costs represented in the execution price rather than debited from cash."""

        return self.spread + self.slippage + self.market_impact

    @property
    def total(self) -> float:
        return sum(asdict(self).values())


@dataclass(frozen=True)
class TransactionCostConfig:
    """Provider-neutral, explicit transaction-cost assumptions.

    Rates are basis points of executed notional; fixed charges are in the
    configured currency. Zero-cost operation is opt-in so a missing cost
    model cannot silently make a backtest permissive.
    """

    version: str
    brokerage_bps: float = 0.0
    brokerage_min: float = 0.0
    brokerage_max: float | None = None
    buy_tax_bps: float = 0.0
    sell_tax_bps: float = 0.0
    exchange_bps: float = 0.0
    regulatory_bps: float = 0.0
    other_bps: float = 0.0
    buy_fixed: float = 0.0
    sell_fixed: float = 0.0
    gst_rate: float = 0.0
    buy_stamp_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    impact_bps_at_full_participation: float = 0.0
    max_participation: float = 1.0
    allow_zero_costs: bool = False

    def with_multiplier(self, multiplier: float, *, version: str) -> "TransactionCostConfig":
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("multiplier must be positive and finite")
        values = asdict(self)
        values["version"] = version
        values["allow_zero_costs"] = self.allow_zero_costs
        for key in (
            "brokerage_bps", "brokerage_min", "brokerage_max", "buy_tax_bps",
            "sell_tax_bps", "exchange_bps", "regulatory_bps", "other_bps",
            "buy_fixed", "sell_fixed", "buy_stamp_bps", "spread_bps",
            "slippage_bps", "impact_bps_at_full_participation",
        ):
            if values[key] is not None:
                values[key] *= multiplier
        return TransactionCostConfig(**values)


@dataclass(frozen=True)
class TransactionCostResult:
    """Auditable component reconciliation for one executed order."""

    version: str
    notional: float
    side: str
    participation: float
    components: dict[str, float]

    @property
    def execution_drag(self) -> float:
        return self.components["spread"] + self.components["slippage"] + self.components["market_impact"]

    @property
    def total(self) -> float:
        return sum(self.components.values())


class TransactionCostCalculator:
    """Calculate explicit, side-aware costs without broker-specific code."""

    def __init__(self, config: TransactionCostConfig) -> None:
        if not config.version.strip():
            raise ValueError("version must be non-empty")
        if not math.isfinite(config.max_participation) or config.max_participation <= 0:
            raise ValueError("max_participation must be positive and finite")
        self.config = config

    def calculate(
        self,
        notional: float,
        side: OrderSide,
        participation: float = 0.0,
    ) -> TransactionCostResult:
        if not math.isfinite(notional) or notional < 0:
            raise ValueError("notional must be finite and non-negative")
        if not math.isfinite(participation) or participation < 0:
            raise ValueError("participation must be finite and non-negative")
        charge_fields = (
            "brokerage_bps", "brokerage_min", "brokerage_max", "buy_tax_bps",
            "sell_tax_bps", "exchange_bps", "regulatory_bps", "other_bps",
            "buy_fixed", "sell_fixed", "gst_rate", "buy_stamp_bps", "spread_bps",
            "slippage_bps", "impact_bps_at_full_participation",
        )
        if not self.config.allow_zero_costs and not any(
            getattr(self.config, field) not in (None, 0.0) for field in charge_fields
        ):
            raise ValueError("zero-cost configuration requires allow_zero_costs=True")
        c = self.config
        brokerage = max(c.brokerage_min, notional * c.brokerage_bps / 10_000) if notional else 0.0
        if c.brokerage_max is not None:
            brokerage = min(c.brokerage_max, brokerage)
        tax_bps = c.buy_tax_bps if side == OrderSide.BUY else c.sell_tax_bps
        fixed = c.buy_fixed if side == OrderSide.BUY else c.sell_fixed
        impact_bps = c.impact_bps_at_full_participation * min(participation, c.max_participation) / c.max_participation
        exchange = notional * c.exchange_bps / 10_000
        regulatory = notional * c.regulatory_bps / 10_000
        other = notional * c.other_bps / 10_000
        gst = c.gst_rate * (brokerage + exchange + regulatory + other + fixed)
        components = {
            "brokerage": brokerage,
            "tax": notional * tax_bps / 10_000,
            "exchange": exchange,
            "regulatory": regulatory,
            "other": other,
            "fixed_charge": fixed if notional else 0.0,
            "gst": gst,
            "stamp_duty": notional * c.buy_stamp_bps / 10_000 if side == OrderSide.BUY else 0.0,
            "spread": notional * c.spread_bps / 10_000,
            "slippage": notional * c.slippage_bps / 10_000,
            "market_impact": notional * impact_bps / 10_000,
        }
        return TransactionCostResult(
            version=c.version,
            notional=notional,
            side=str(getattr(side, "value", side)),
            participation=participation,
            components=components,
        )


@dataclass(frozen=True)
class IndianDeliveryCostSchedule:
    """Configurable Angel One/NSE delivery assumptions; rates are not strategy code."""

    version: str = "angel-nse-delivery-2026-04"
    effective_from: date = date(2026, 4, 1)
    brokerage_rate_bps: float = 10.0
    brokerage_min: float = 5.0
    brokerage_max: float = 20.0
    stt_buy_bps: float = 10.0
    stt_sell_bps: float = 10.0
    exchange_transaction_bps: float = 0.30699
    sebi_bps: float = 0.01
    ipft_bps: float = 0.00001
    dp_charge_sell: float = 20.0
    gst_rate: float = 0.18
    stamp_duty_buy_bps: float = 1.5
    spread_bps: float = 2.0
    slippage_bps: float = 3.0
    impact_bps_at_full_participation: float = 10.0
    max_volume_participation: float = 0.05
    max_allowed_drag_bps: float = 500.0  # 5% maximum allowable execution drag ceiling
    minimum_daily_traded_value: float = 1_000_000.0

    def calculate(self, notional: float, side: OrderSide, participation: float = 0.0) -> CostBreakdown:
        notional = abs(float(notional))
        brokerage = min(self.brokerage_max, max(self.brokerage_min, notional * self.brokerage_rate_bps / 10_000)) if notional else 0.0
        stt_rate = self.stt_buy_bps if side == OrderSide.BUY else self.stt_sell_bps
        exchange = notional * self.exchange_transaction_bps / 10_000
        sebi = notional * self.sebi_bps / 10_000
        ipft = notional * self.ipft_bps / 10_000
        dp_charge = self.dp_charge_sell if side == OrderSide.SELL and notional else 0.0
        gst = self.gst_rate * (brokerage + exchange + sebi + ipft + dp_charge)
        impact_bps = self.impact_bps_at_full_participation * min(max(participation, 0.0), self.max_volume_participation) / max(self.max_volume_participation, 1e-12)
        return CostBreakdown(
            brokerage=brokerage,
            stt=notional * stt_rate / 10_000,
            exchange_transaction=exchange,
            sebi=sebi,
            ipft=ipft,
            dp_charge=dp_charge,
            gst=gst,
            stamp_duty=notional * self.stamp_duty_buy_bps / 10_000 if side == OrderSide.BUY else 0.0,
            spread=notional * self.spread_bps / 10_000,
            slippage=notional * self.slippage_bps / 10_000,
            market_impact=notional * impact_bps / 10_000,
        )

    def execution_price(self, price: float, side: OrderSide, participation: float = 0.0) -> float:
        if not math.isfinite(price) or price <= 0:
            raise InvalidExecutionPriceError(f"Execution price input must be positive finite float, got {price}")
        if not math.isfinite(participation) or participation < 0:
            raise UnexecutableOrderError(
                reason_code=ExecutionReasonCode.MAX_PARTICIPATION_EXCEEDED,
                estimated_drag_bps=0.0,
                max_drag_bps=self.max_allowed_drag_bps,
                participation=participation,
            )

        impact_bps = self.impact_bps_at_full_participation * min(max(participation, 0.0), self.max_volume_participation) / max(self.max_volume_participation, 1e-12)
        total_bps = self.spread_bps + self.slippage_bps + impact_bps
        if total_bps > self.max_allowed_drag_bps:
            raise UnexecutableOrderError(
                reason_code=ExecutionReasonCode.MAX_EXECUTION_DRAG_EXCEEDED,
                estimated_drag_bps=total_bps,
                max_drag_bps=self.max_allowed_drag_bps,
                participation=participation,
            )

        multiplier = 1 + total_bps / 10_000 if side == OrderSide.BUY else 1 - total_bps / 10_000
        exec_price = float(price * multiplier)
        if not math.isfinite(exec_price) or exec_price <= 0:
            raise InvalidExecutionPriceError(
                f"Calculated execution price {exec_price} is non-positive or non-finite for price {price} and drag {total_bps:.2f} bps"
            )
        return exec_price


DEFAULT_COST_SCHEDULES: tuple[IndianDeliveryCostSchedule, ...] = (
    IndianDeliveryCostSchedule(
        version="angel-nse-delivery-2010-01",
        effective_from=date(2010, 1, 1),
        stt_buy_bps=12.5,
        stt_sell_bps=12.5,
        exchange_transaction_bps=0.325,
    ),
    IndianDeliveryCostSchedule(
        version="angel-nse-delivery-2016-06",
        effective_from=date(2016, 6, 1),
        stt_buy_bps=10.0,
        stt_sell_bps=10.0,
        exchange_transaction_bps=0.325,
    ),
    IndianDeliveryCostSchedule(
        version="angel-nse-delivery-2024-10",
        effective_from=date(2024, 10, 1),
        stt_buy_bps=10.0,
        stt_sell_bps=10.0,
        exchange_transaction_bps=0.297,
    ),
    IndianDeliveryCostSchedule(
        version="angel-nse-delivery-2026-04",
        effective_from=date(2026, 4, 1),
        stt_buy_bps=10.0,
        stt_sell_bps=10.0,
        exchange_transaction_bps=0.30699,
    ),
)


def get_cost_schedule(as_of: date | datetime | None = None) -> IndianDeliveryCostSchedule:
    """Resolve the active cost schedule as of a specific trade date."""
    if as_of is None:
        return DEFAULT_COST_SCHEDULES[-1]
    ref_date = as_of.date() if isinstance(as_of, datetime) else as_of
    applicable = [s for s in DEFAULT_COST_SCHEDULES if s.effective_from <= ref_date]
    return applicable[-1] if applicable else DEFAULT_COST_SCHEDULES[0]


def explicit_fixed_cost_schedule(
    cost_model: Mapping[str, Any] | None,
) -> IndianDeliveryCostSchedule | None:
    """Build a fixed schedule only for an explicitly labelled stress run."""

    values = dict(cost_model or {})
    mode = values.get("cost_mode") or values.get("mode")
    marked_stress = bool(values.get("fixed_cost_stress")) or mode == "FIXED_COST_STRESS"
    nested = values.get("indian_delivery_costs")
    if isinstance(nested, Mapping):
        values = {**values, **nested}
        marked_stress = marked_stress or bool(nested.get("fixed_cost_stress")) or nested.get("cost_mode") == "FIXED_COST_STRESS"
    if not marked_stress:
        return None
    allowed = set(IndianDeliveryCostSchedule.__dataclass_fields__)
    return IndianDeliveryCostSchedule(**{key: value for key, value in values.items() if key in allowed})




