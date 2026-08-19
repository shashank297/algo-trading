from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum

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





