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

    def execute(
        self,
        signal: TradingSignal,
        portfolio_equity: float = 100_000.0,
    ) -> CryptoOrderResult | None:
        from alpaca.trading.requests import MarketOrderRequest
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
            log.info(
                "Crypto BUY: %s notional=%.2f qty=%.6f id=%s",
                signal.symbol, notional, qty, order.id,
            )
            return CryptoOrderResult(
                symbol=signal.symbol,
                order_id=str(order.id),
                action="BUY",
                qty=qty,
                submitted_price=price,
                stop_price=0.0,
                take_profit_price=0.0,
                exchange=exchange_label,
                timestamp=datetime.now(timezone.utc),
                raw=order,
            )
        except Exception as exc:
            log.error("Crypto BUY failed for %s: %s", signal.symbol, exc)
            return None
