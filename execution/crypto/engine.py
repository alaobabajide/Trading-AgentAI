"""Crypto execution engine — Alpaca trading API.

Architecture:
  • Receives a TradingSignal (asset_class = "crypto").
  • Enforces the global 30 % crypto cap using Alpaca portfolio.
  • Submits market orders via Alpaca (same API key as stocks — no Binance geo-block).
  • Symbol format: BTCUSD, ETHUSD, SOLUSD, AVAXUSD (no slash in trading API).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from brain.signal import TradingSignal

log = logging.getLogger(__name__)


@dataclass
class CryptoOrderResult:
    symbol: str
    order_id: str
    action: str
    qty: float
    submitted_price: float
    stop_price: float
    take_profit_price: float
    exchange: str
    timestamp: datetime
    raw: Any = None


class CryptoExecutionEngine:
    """Crypto execution via Alpaca — same account, same API key, no geo-restrictions."""

    def __init__(
        self,
        alpaca_api_key: str,
        alpaca_secret_key: str,
        alpaca_base_url: str = "https://paper-api.alpaca.markets",
        max_position_pct: float = 0.05,
        max_crypto_allocation_pct: float = 0.30,
        # Legacy Binance kwargs accepted but ignored — kept for callers that pass them
        binance_api_key: str = "",
        binance_secret_key: str = "",
        testnet: bool = True,
    ) -> None:
        from alpaca.trading.client import TradingClient
        is_paper = "paper" in alpaca_base_url.lower()
        self._trading      = TradingClient(alpaca_api_key, alpaca_secret_key, paper=is_paper)
        self._max_pos      = max_position_pct
        self._max_crypto   = max_crypto_allocation_pct
        self._is_paper     = is_paper

    def _get_account(self):
        return self._trading.get_account()

    def _get_position_qty(self, symbol: str) -> float:
        try:
            positions = self._trading.get_all_positions()
            for p in positions:
                if p.symbol == symbol:
                    return float(p.qty or 0)
        except Exception:
            pass
        return 0.0

    def _check_crypto_cap(self, equity: float) -> bool:
        """Return True if more crypto can be allocated (cap not reached)."""
        try:
            positions = self._trading.get_all_positions()
            crypto_value = 0.0
            for p in positions:
                sym = p.symbol or ""
                # Alpaca crypto symbols end in USD (BTCUSD, ETHUSD, etc.)
                if sym.endswith("USD") and len(sym) > 3:
                    crypto_value += float(p.market_value or 0)
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

    def _get_latest_price(self, symbol: str) -> float:
        """Fetch current mid-price via Alpaca crypto data API (no auth required)."""
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoLatestQuoteRequest
            client = CryptoHistoricalDataClient()
            # Alpaca data API expects symbol with slash: BTC/USD
            data_symbol = symbol[:-3] + "/" + symbol[-3:] if symbol.endswith("USD") else symbol
            quotes = client.get_crypto_latest_quote(
                CryptoLatestQuoteRequest(symbol_or_symbols=data_symbol)
            )
            if quotes and data_symbol in quotes:
                q = quotes[data_symbol]
                ask = float(getattr(q, "ask_price", 0) or 0)
                bid = float(getattr(q, "bid_price", 0) or 0)
                if ask > 0 and bid > 0:
                    return (ask + bid) / 2
                return ask or bid
        except Exception as exc:
            log.debug("Could not fetch latest price for %s: %s", symbol, exc)
        return 0.0

    def execute(
        self,
        signal: TradingSignal,
        portfolio_equity: float = 100_000.0,
    ) -> CryptoOrderResult | None:
        from alpaca.trading.requests import (
            MarketOrderRequest, TakeProfitRequest, StopLossRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce

        if signal.action == "HOLD":
            log.info("HOLD signal for %s — no order submitted", signal.symbol)
            return None

        try:
            acct   = self._get_account()
            cash   = float(acct.cash or 0)
            equity = float(acct.equity or portfolio_equity)
        except Exception as exc:
            log.error("Could not fetch Alpaca account for crypto execution: %s", exc)
            return None

        exchange_label = "alpaca_paper_crypto" if self._is_paper else "alpaca_live_crypto"

        if signal.action == "SELL":
            qty = self._get_position_qty(signal.symbol)
            if qty <= 0:
                log.info("No open crypto position for %s — SELL skipped", signal.symbol)
                return None
            try:
                order = self._trading.close_position(signal.symbol)
                log.info("Crypto SELL: %s qty=%.6f id=%s", signal.symbol, qty, order.id)
                return CryptoOrderResult(
                    symbol=signal.symbol,
                    order_id=str(order.id),
                    action="SELL",
                    qty=qty,
                    submitted_price=float(getattr(order, "filled_avg_price", 0) or 0),
                    stop_price=0.0,
                    take_profit_price=0.0,
                    exchange=exchange_label,
                    timestamp=datetime.now(timezone.utc),
                    raw=order,
                )
            except Exception as exc:
                log.error("Crypto SELL failed for %s: %s", signal.symbol, exc)
                return None

        # BUY path
        if not self._check_crypto_cap(equity):
            return None

        notional = min(
            equity * signal.suggested_position_pct,
            equity * self._max_pos,
            cash * 0.99,
        )
        if notional < 1.0:
            log.warning("Notional too small for %s (%.2f) — skipping BUY", signal.symbol, notional)
            return None

        # Fetch current price to compute qty and bracket levels
        current_price = self._get_latest_price(signal.symbol)
        if current_price <= 0:
            log.warning("Could not determine current price for %s — falling back to plain market order", signal.symbol)
            try:
                order_req = MarketOrderRequest(
                    symbol=signal.symbol,
                    notional=round(notional, 2),
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                )
                order = self._trading.submit_order(order_req)
                qty   = float(getattr(order, "qty", 0) or 0)
                price = float(getattr(order, "filled_avg_price", 0) or 0)
                log.info("Crypto BUY (no bracket): %s notional=%.2f qty=%.8f id=%s",
                         signal.symbol, notional, qty, order.id)
                return CryptoOrderResult(
                    symbol=signal.symbol, order_id=str(order.id), action="BUY",
                    qty=qty, submitted_price=price, stop_price=0.0, take_profit_price=0.0,
                    exchange=exchange_label, timestamp=datetime.now(timezone.utc), raw=order,
                )
            except Exception as exc:
                log.error("Crypto BUY (plain) failed for %s: %s", signal.symbol, exc)
                return None

        # Compute qty from notional and price (bracket orders require qty, not notional)
        qty = notional / current_price
        stop_price       = round(current_price * (1 - signal.stop_loss_pct), 8)
        take_profit_price = round(current_price * (1 + signal.take_profit_pct), 8)

        try:
            order_req = MarketOrderRequest(
                symbol=signal.symbol,
                qty=round(qty, 8),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC,
                order_class="bracket",
                stop_loss=StopLossRequest(stop_price=stop_price),
                take_profit=TakeProfitRequest(limit_price=take_profit_price),
            )
            order = self._trading.submit_order(order_req)
            filled_qty   = float(getattr(order, "qty", qty) or qty)
            filled_price = float(getattr(order, "filled_avg_price", current_price) or current_price)
            log.info(
                "Crypto BUY bracket: %s price=%.4f qty=%.8f stop=%.4f tp=%.4f id=%s",
                signal.symbol, current_price, filled_qty, stop_price, take_profit_price, order.id,
            )
            return CryptoOrderResult(
                symbol=signal.symbol,
                order_id=str(order.id),
                action="BUY",
                qty=filled_qty,
                submitted_price=filled_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                exchange=exchange_label,
                timestamp=datetime.now(timezone.utc),
                raw=order,
            )
        except Exception as exc:
            log.error("Crypto BUY bracket failed for %s: %s — retrying without bracket", signal.symbol, exc)
            # Fallback: plain market order without bracket
            try:
                order_req = MarketOrderRequest(
                    symbol=signal.symbol,
                    notional=round(notional, 2),
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                )
                order = self._trading.submit_order(order_req)
                qty_out = float(getattr(order, "qty", 0) or 0)
                price_out = float(getattr(order, "filled_avg_price", 0) or 0)
                log.info("Crypto BUY (bracket fallback): %s notional=%.2f id=%s",
                         signal.symbol, notional, order.id)
                return CryptoOrderResult(
                    symbol=signal.symbol, order_id=str(order.id), action="BUY",
                    qty=qty_out, submitted_price=price_out, stop_price=0.0, take_profit_price=0.0,
                    exchange=exchange_label, timestamp=datetime.now(timezone.utc), raw=order,
                )
            except Exception as exc2:
                log.error("Crypto BUY fallback also failed for %s: %s", signal.symbol, exc2)
                return None
