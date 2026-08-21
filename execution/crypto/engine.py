"""Crypto execution engine — broker-agnostic via BrokerAdapter.

Architecture:
  • Receives a TradingSignal (asset_class = "crypto").
  • Enforces the global 30% crypto cap via portfolio positions.
  • Submits market orders via the injected BrokerAdapter.
  • Symbol format: BTCUSD, ETHUSD, SOLUSD, AVAXUSD (no slash in trading API).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from brain.signal import TradingSignal
from broker.interface import BrokerOrderResult

if TYPE_CHECKING:
    from broker.interface import BrokerAdapter

log = logging.getLogger(__name__)


class CryptoExecutionEngine:
    """Crypto execution through any BrokerAdapter — no Binance geo-restriction risk."""

    def __init__(
        self,
        broker: "BrokerAdapter",
        max_position_pct: float = 0.05,
        max_crypto_allocation_pct: float = 0.30,
        cash_buffer: float = 0.99,
        min_notional_usd: float = 1.0,
        fallback_equity_usd: float = 100_000.0,
    ) -> None:
        self._broker         = broker
        self._max_pos        = max_position_pct
        self._max_crypto     = max_crypto_allocation_pct
        self._cash_buffer    = cash_buffer
        self._min_notional   = min_notional_usd
        self._fallback_equity = fallback_equity_usd

    def _check_crypto_cap(self, equity: float) -> bool:
        """Return True if more crypto can be allocated (cap not reached)."""
        try:
            positions = self._broker.get_all_positions()
            crypto_value = sum(
                abs(p.market_value) for p in positions if p.asset_class == "crypto"
            )
            crypto_pct = crypto_value / max(equity, 1)
            if crypto_pct >= self._max_crypto:
                log.warning(
                    "Crypto cap reached (%.1f%% >= %.1f%%) — blocking BUY",
                    crypto_pct * 100, self._max_crypto * 100,
                )
                return False
            return True
        except Exception as exc:
            log.warning("Could not check crypto cap: %s — allowing BUY", exc)
            return True

    def execute(
        self,
        signal: TradingSignal,
        portfolio_equity: float | None = None,
    ) -> BrokerOrderResult | None:
        if signal.action == "HOLD":
            log.info("HOLD signal for %s — no order submitted", signal.symbol)
            return None

        try:
            acct   = self._broker.get_account()
            cash   = acct.cash
            equity = acct.equity or portfolio_equity or self._fallback_equity
        except Exception as exc:
            log.error("Could not fetch account for crypto execution: %s", exc)
            return None

        if signal.action == "SELL":
            positions = []
            try:
                positions = self._broker.get_all_positions()
            except Exception:
                pass
            pos = next((p for p in positions if p.symbol == signal.symbol), None)
            qty = pos.qty if pos else 0.0
            if qty <= 0:
                log.info("No open crypto position for %s — SELL skipped", signal.symbol)
                return None
            try:
                result = self._broker.close_position(signal.symbol)
                log.info("Crypto SELL: %s qty=%.6f id=%s", signal.symbol, qty, result.order_id)
                return result
            except Exception as exc:
                log.error("Crypto SELL failed for %s: %s", signal.symbol, exc)
                return None

        # BUY path
        if not self._check_crypto_cap(equity):
            return None

        notional = min(
            equity * signal.suggested_position_pct,
            equity * self._max_pos,
            cash * self._cash_buffer,
        )
        if notional < self._min_notional:
            log.warning(
                "Notional too small for %s (%.2f < %.2f min) — skipping BUY",
                signal.symbol, notional, self._min_notional,
            )
            return None

        # Fetch current price to compute qty and bracket levels
        current_price = self._broker.get_latest_crypto_price(signal.symbol)
        if current_price <= 0:
            log.warning(
                "Could not determine current price for %s — falling back to plain market order",
                signal.symbol,
            )
            try:
                result = self._broker.submit_market_order(
                    symbol=signal.symbol,
                    side="BUY",
                    notional=round(notional, 2),
                )
                log.info("Crypto BUY (no bracket): %s notional=%.2f id=%s",
                         signal.symbol, notional, result.order_id)
                return result
            except Exception as exc:
                log.error("Crypto BUY (plain) failed for %s: %s", signal.symbol, exc)
                return None

        # Compute qty from notional and price (bracket orders require qty, not notional)
        qty_to_buy        = notional / current_price
        stop_price        = round(current_price * (1 - signal.stop_loss_pct),  8)
        take_profit_price = round(current_price * (1 + signal.take_profit_pct), 8)

        try:
            result = self._broker.submit_bracket_order(
                symbol=signal.symbol,
                qty=round(qty_to_buy, 8),
                side="BUY",
                stop_price=stop_price,
                take_profit_price=take_profit_price,
            )
            log.info(
                "Crypto BUY bracket via %s: %s price=%.4f qty=%.8f stop=%.4f tp=%.4f id=%s",
                self._broker.broker_name, signal.symbol,
                current_price, result.qty, stop_price, take_profit_price, result.order_id,
            )
            return result
        except Exception as exc:
            log.error("Crypto BUY bracket failed for %s: %s — retrying without bracket", signal.symbol, exc)
            try:
                result = self._broker.submit_market_order(
                    symbol=signal.symbol,
                    side="BUY",
                    notional=round(notional, 2),
                )
                log.info("Crypto BUY (bracket fallback): %s notional=%.2f id=%s",
                         signal.symbol, notional, result.order_id)
                return result
            except Exception as exc2:
                log.error("Crypto BUY fallback also failed for %s: %s", signal.symbol, exc2)
                return None
