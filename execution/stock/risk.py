"""Stock execution risk controls.

Implements:
  • ATR-based position sizing
  • Trailing stop management
  • Circuit breaker (daily drawdown halt)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
import ta

log = logging.getLogger(__name__)


@dataclass
class SizingResult:
    shares: int
    notional: float
    stop_price: float
    take_profit_price: float
    atr: float


class RiskControls:
    def __init__(
        self,
        equity: float,
        max_position_pct: float = 0.05,
        circuit_breaker_drawdown: float = 0.10,
    ) -> None:
        self.equity = equity
        self.max_position_pct = max_position_pct
        self.circuit_breaker_drawdown = circuit_breaker_drawdown
        self._triggered = False

    def check_circuit_breaker(self, daily_pnl_pct: float) -> bool:
        """Returns True if the breaker is now tripped."""
        drawdown = -daily_pnl_pct / 100.0  # positive when losing money; gains never trip the breaker
        if drawdown >= self.circuit_breaker_drawdown:
            if not self._triggered:
                log.critical(
                    "CIRCUIT BREAKER TRIPPED — daily drawdown %.1f%% >= limit %.1f%%",
                    drawdown * 100, self.circuit_breaker_drawdown * 100,
                )
            self._triggered = True
        return self._triggered

    def reset_circuit_breaker(self) -> None:
        self._triggered = False
        log.info("Circuit breaker reset (manual override)")

    def size_position(
        self,
        symbol: str,
        current_price: float,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        signal_position_pct: float,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.05,
        atr_multiplier: float = 2.0,
    ) -> SizingResult:
        """ATR-based position sizing.

        Uses 2× ATR as the stop distance.  Notional is capped at
        max_position_pct × equity.
        """
        if self._triggered:
            log.warning("Circuit breaker active — sizing to 0 for %s", symbol)
            return SizingResult(0, 0.0, current_price, current_price, 0.0)

        # ATR
        atr = 0.0
        if len(closes) >= 14:
            h = pd.Series(highs)
            l = pd.Series(lows)
            c = pd.Series(closes)
            atr_series = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
            atr = float(atr_series.iloc[-1])

        # Stop distance: max of ATR-based or fixed percentage
        atr_stop = atr_multiplier * atr if atr > 0 else current_price * stop_loss_pct
        stop_distance = max(atr_stop, current_price * stop_loss_pct)
        stop_price = round(current_price - stop_distance, 4)
        take_profit_price = round(current_price + current_price * take_profit_pct, 4)

        # Notional cap
        max_notional = self.equity * min(signal_position_pct, self.max_position_pct)
        shares = max(1, int(max_notional / current_price))
        notional = shares * current_price

        log.info(
            "Size %s: qty=%d price=%.2f stop=%.2f tp=%.2f atr=%.4f notional=%.2f",
            symbol, shares, current_price, stop_price, take_profit_price, atr, notional,
        )
        return SizingResult(
            shares=shares,
            notional=notional,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            atr=atr,
        )


class TrailingStopManager:
    """Tracks open positions and updates trailing stops."""

    def __init__(self, trail_pct: float = 0.015) -> None:
        self.trail_pct = trail_pct
        self._peaks: dict[str, float] = {}

    def update(self, symbol: str, current_price: float) -> float | None:
        """Returns a new stop price if the trail has moved, else None."""
        peak = self._peaks.get(symbol, current_price)
        if current_price > peak:
            self._peaks[symbol] = current_price
            new_stop = round(current_price * (1 - self.trail_pct), 4)
            log.debug("Trailing stop %s: peak=%.2f new_stop=%.2f", symbol, current_price, new_stop)
            return new_stop
        return None

    def register(self, symbol: str, price: float) -> None:
        self._peaks[symbol] = price

    def remove(self, symbol: str) -> None:
        self._peaks.pop(symbol, None)
