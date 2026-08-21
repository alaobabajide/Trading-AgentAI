"""Stock execution engine — broker-agnostic via BrokerAdapter.

Architecture:
  • Receives a TradingSignal from the Brain API.
  • Applies ATR sizing and risk controls.
  • Submits bracket orders via the injected BrokerAdapter.
  • Manages trailing stops on open positions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from brain.signal import TradingSignal
from broker.interface import BrokerOrderResult
from execution.stock.risk import RiskControls, TrailingStopManager

if TYPE_CHECKING:
    from broker.interface import BrokerAdapter

log = logging.getLogger(__name__)


class StockExecutionEngine:
    """Executes stock trades through any BrokerAdapter implementation."""

    def __init__(
        self,
        broker: "BrokerAdapter",
        max_position_pct: float = 0.05,
        circuit_breaker_drawdown: float = 0.10,
        trailing_stop_pct: float = 0.015,
        atr_multiplier: float = 1.5,
        atr_stop_floor: float = 0.005,
        atr_stop_cap: float = 0.04,
    ) -> None:
        self._broker          = broker
        self._trailing        = TrailingStopManager(trail_pct=trailing_stop_pct)
        self._risk: RiskControls | None = None
        self._max_pos         = max_position_pct
        self._cb_drawdown     = circuit_breaker_drawdown
        self._atr_multiplier  = atr_multiplier
        self._atr_stop_floor  = atr_stop_floor
        self._atr_stop_cap    = atr_stop_cap

    def _get_risk(self) -> RiskControls:
        """Lazily refresh equity-based risk controls."""
        acct       = self._broker.get_account()
        equity     = acct.equity
        last_eq    = acct.last_equity if acct.last_equity else equity or 1.0
        if last_eq == 0:
            last_eq = equity or 1.0
        daily_pnl_pct = (equity - last_eq) / last_eq * 100
        try:
            positions = self._broker.get_all_positions()
            deployed  = sum(abs(p.market_value) for p in positions)
            available = max(0.0, equity - deployed)
        except Exception:
            available = equity
        rc = RiskControls(available, self._max_pos, self._cb_drawdown)
        rc.check_circuit_breaker(daily_pnl_pct)
        return rc

    def execute(
        self,
        signal: TradingSignal,
        bars_highs: list[float],
        bars_lows: list[float],
        bars_closes: list[float],
    ) -> BrokerOrderResult | None:
        if signal.action == "HOLD":
            log.info("HOLD signal for %s — no order submitted", signal.symbol)
            return None

        risk = self._get_risk()
        if risk.is_triggered:
            log.warning("Circuit breaker active — refusing to execute %s", signal.symbol)
            return None

        if signal.action == "SELL":
            return self._broker.close_position(signal.symbol)

        # BUY: size the position then submit a bracket order
        current_price = bars_closes[-1] if bars_closes else 0.0
        if current_price <= 0:
            log.error("Cannot execute: invalid current price for %s", signal.symbol)
            return None

        sizing = risk.size_position(
            symbol=signal.symbol,
            current_price=current_price,
            highs=bars_highs,
            lows=bars_lows,
            closes=bars_closes,
            signal_position_pct=signal.suggested_position_pct,
            stop_loss_pct=signal.stop_loss_pct,
            take_profit_pct=signal.take_profit_pct,
            atr_multiplier=self._atr_multiplier,
            atr_stop_floor=self._atr_stop_floor,
            atr_stop_cap=self._atr_stop_cap,
        )

        if sizing is None:
            log.warning("Insufficient available capital to size %s — order skipped", signal.symbol)
            return None
        if sizing.shares == 0:
            log.warning("Sizing resulted in 0 shares for %s", signal.symbol)
            return None

        result = self._broker.submit_bracket_order(
            symbol=signal.symbol,
            qty=sizing.shares,
            side="BUY",
            stop_price=sizing.stop_price,
            take_profit_price=sizing.take_profit_price,
        )
        result.submitted_price = current_price  # use live price, not fill (market order)
        self._trailing.register(signal.symbol, current_price)

        log.info(
            "BUY bracket submitted via %s: %d %s @ market stop=%.2f tp=%.2f id=%s",
            self._broker.broker_name, sizing.shares, signal.symbol,
            sizing.stop_price, sizing.take_profit_price, result.order_id,
        )
        return result
