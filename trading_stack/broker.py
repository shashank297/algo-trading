"""Broker-facing adapters for backtests and paper trading."""

from __future__ import annotations

from trading_stack.backtest import ExecutionModel, PaperBroker

__all__ = ["ExecutionModel", "PaperBroker"]
