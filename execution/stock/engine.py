"""Stock execution engine — NautilusTrader + Alpaca.

Architecture:
  • Receives a TradingSignal from the Brain API.
  • Applies ATR sizing and risk controls.
  • Submits bracket orders (entry + stop-loss + take-profit) via Alpaca.
  • Manages trailing stops on open positions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from brain.signal import TradingSignal
from execution.stock.risk import RiskControls, SizingResult, TrailingStopManager

log = logging.getLogger(__name__)


@dataclass
class OrderResult:
    symbol: str
    order_id: str
    action: str
    qty: int
    submitted_price: float
    stop_price: float
    take_profit_price: float
    timestamp: datetime
    raw: Any = None


class StockExecutionEngine:
    """Wraps Alpaca's trading API with NautilusTrader-style risk controls."""

    def __init__(
        self,
        alpaca_api_key: str,
        alpaca_secret_key: str,
        alpaca_base_url: str,
        max_position_pct: float = 0.05,
        circuit_breaker_drawdown: float = 0.10,
    ) -> None:
        from alpaca.trading.client import TradingClient

        is_paper = "paper" in alpaca_base_url.lower()
        self._trading = TradingClient(alpaca_api_key, alpaca_secret_key, paper=is_paper)
        self._trailing = TrailingStopManager()
        self._risk: RiskControls | None = None
        self._max_pos = max_position_pct
        self._cb_drawdown = circuit_breaker_drawdown

    def _get_risk(self) -> RiskControls:
        """Lazily refresh equity-based risk controls."""
        acct = self._trading.get_account()
        equity = float(acct.equity)
        daily_pnl_pct = (float(acct.equity) - float(acct.last_equity)) / float(acct.last_equity) * 100
        rc = RiskControls(equity, self._max_pos, self._cb_drawdown)
        rc.check_circuit_breaker(daily_pnl_pct)
        return rc

    def execute(
        self,
        signal: TradingSignal,
        bars_highs: list[float],
        bars_lows: list[float],
        bars_closes: list[float],
    ) -> OrderResult | None:
        if signal.action == "HOLD":
            log.info("HOLD signal for %s — no order submitted", signal.symbol)
            return None

        risk = self._get_risk()
        if risk._triggered:
            log.warning("Circuit breaker active — refusing to execute %s", signal.symbol)
            return None

        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        # Current price comes from the last bar close passed in by the caller
        current_price = bars_closes[-1] if bars_closes else 0.0
        if current_price <= 0:
            log.error("Cannot execute: invalid current price for %s", signal.symbol)
            return None

        sizing: SizingResult = risk.size_position(
            symbol=signal.symbol,
            current_price=current_price,
            highs=bars_highs,
            lows=bars_lows,
            closes=bars_closes,
            signal_position_pct=signal.suggested_position_pct,
            stop_loss_pct=signal.stop_loss_pct,
            take_profit_pct=signal.take_profit_pct,
        )

        if sizing.shares == 0:
            log.warning("Sizing resulted in 0 shares for %s", signal.symbol)
            return None

        side = OrderSide.BUY if signal.action == "BUY" else OrderSide.SELL

        order_req = MarketOrderRequest(
            symbol=signal.symbol,
            qty=sizing.shares,
            side=side,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            stop_loss=StopLossRequest(stop_price=sizing.stop_price),
            take_profit=TakeProfitRequest(limit_price=sizing.take_profit_price),
        )

        try:
            order = self._trading.submit_order(order_req)
            if signal.action == "BUY":
                self._trailing.register(signal.symbol, current_price)

            log.info(
                "Order submitted: %s %d %s @ market stop=%.2f tp=%.2f id=%s",
                side.value, sizing.shares, signal.symbol,
                sizing.stop_price, sizing.take_profit_price, order.id,
            )
            return OrderResult(
                symbol=signal.symbol,
                order_id=str(order.id),
                action=signal.action,
                qty=sizing.shares,
                submitted_price=current_price,
                stop_price=sizing.stop_price,
                take_profit_price=sizing.take_profit_price,
                timestamp=datetime.now(timezone.utc),
                raw=order,
            )
        except Exception as exc:
            log.error("Order submission failed for %s: %s", signal.symbol, exc)
            return None

    def update_trailing_stops(self, symbol: str, current_price: float) -> None:
        """Call periodically to ratchet trailing stops."""
        new_stop = self._trailing.update(symbol, current_price)
        if new_stop is not None:
            self._update_stop_order(symbol, new_stop)

    def _update_stop_order(self, symbol: str, new_stop: float) -> None:
        """Replace the open stop order for a position."""
        try:
            positions = self._trading.get_all_positions()
            for pos in positions:
                if pos.symbol == symbol:
                    orders = self._trading.get_orders()
                    for order in orders:
                        if str(order.symbol) == symbol and str(order.order_type) == "stop":
                            from alpaca.trading.requests import ReplaceOrderRequest
                            self._trading.replace_order_by_id(
                                order.id,
                                ReplaceOrderRequest(stop_price=new_stop),
                            )
                            log.info("Trailing stop updated: %s new_stop=%.4f", symbol, new_stop)
        except Exception as exc:
            log.error("Trailing stop update failed for %s: %s", symbol, exc)
