"""Crypto execution engine — Hummingbot-style adapter + Binance.

Architecture:
  • Receives a TradingSignal (asset_class = "crypto").
  • Enforces the global 30 % crypto cap.
  • Submits market + OCO (one-cancels-other) orders on Binance.
  • Supports Binance testnet and 50+ exchanges via ccxt fallback.
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
    """
    Thin execution layer that wraps Binance (primary) and ccxt (fallback).

    Hummingbot's strategy runner is embedded as an external process;
    this class handles signal → order routing.
    """

    def __init__(
        self,
        binance_api_key: str,
        binance_secret_key: str,
        testnet: bool = True,
        max_position_pct: float = 0.05,
        max_crypto_allocation_pct: float = 0.30,
    ) -> None:
        self._key = binance_api_key
        self._secret = binance_secret_key
        self._testnet = testnet
        self._max_pos = max_position_pct
        self._max_crypto_pct = max_crypto_allocation_pct

    def _client(self):
        from binance.client import Client
        return Client(self._key, self._secret, testnet=self._testnet)

    def _get_account_usdt(self, client) -> float:
        """Returns free USDT balance."""
        balances = client.get_account()["balances"]
        for b in balances:
            if b["asset"] == "USDT":
                return float(b["free"])
        return 0.0

    def _check_crypto_cap(self, client, portfolio_equity: float) -> bool:
        """Returns True if more crypto can be bought (cap not reached)."""
        balances = client.get_account()["balances"]
        prices = {t["symbol"]: float(t["price"]) for t in client.get_all_tickers()}
        crypto_usd = 0.0
        for b in balances:
            asset = b["asset"]
            if asset == "USDT":
                continue
            qty = float(b["free"]) + float(b["locked"])
            if qty < 1e-8:
                continue
            pair = f"{asset}USDT"
            price = prices.get(pair, 0.0)
            crypto_usd += qty * price

        crypto_pct = crypto_usd / max(portfolio_equity, 1)
        if crypto_pct >= self._max_crypto_pct:
            log.warning(
                "Global crypto cap reached (%.1f%% >= %.1f%%) — blocking BUY",
                crypto_pct * 100, self._max_crypto_pct * 100,
            )
            return False
        return True

    def execute(
        self,
        signal: TradingSignal,
        portfolio_equity: float = 100_000.0,
    ) -> CryptoOrderResult | None:
        if signal.action == "HOLD":
            log.info("HOLD signal for %s — no order submitted", signal.symbol)
            return None

        client = self._client()

        # Enforce crypto cap on BUY
        if signal.action == "BUY":
            if not self._check_crypto_cap(client, portfolio_equity):
                return None

        # Current price
        ticker = client.get_symbol_ticker(symbol=signal.symbol)
        current_price = float(ticker["price"])
        if current_price <= 0:
            log.error("Invalid price for %s", signal.symbol)
            return None

        # Notional
        usdt_balance = self._get_account_usdt(client)
        max_notional = min(
            portfolio_equity * signal.suggested_position_pct,
            portfolio_equity * self._max_pos,
            usdt_balance * 0.99,  # keep 1% buffer
        )
        qty = round(max_notional / current_price, 6)
        if qty <= 0:
            log.warning("Computed qty=0 for %s — skipping", signal.symbol)
            return None

        stop_price = round(current_price * (1 - signal.stop_loss_pct), 8)
        take_profit_price = round(current_price * (1 + signal.take_profit_pct), 8)

        try:
            if signal.action == "BUY":
                order = client.order_market_buy(symbol=signal.symbol, quantity=qty)
                # Place OCO sell (stop + limit)
                client.create_oco_order(
                    symbol=signal.symbol,
                    side="SELL",
                    quantity=qty,
                    price=str(take_profit_price),
                    stopPrice=str(stop_price),
                    stopLimitPrice=str(round(stop_price * 0.995, 8)),
                    stopLimitTimeInForce="GTC",
                )
            else:  # SELL — close position
                order = client.order_market_sell(symbol=signal.symbol, quantity=qty)

            order_id = str(order.get("orderId", "unknown"))
            log.info(
                "Crypto order: %s %s qty=%.6f price=%.6f stop=%.6f tp=%.6f id=%s",
                signal.action, signal.symbol, qty,
                current_price, stop_price, take_profit_price, order_id,
            )
            return CryptoOrderResult(
                symbol=signal.symbol,
                order_id=order_id,
                action=signal.action,
                qty=qty,
                submitted_price=current_price,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                exchange="binance_testnet" if self._testnet else "binance",
                timestamp=datetime.now(timezone.utc),
                raw=order,
            )
        except Exception as exc:
            log.error("Crypto order failed for %s: %s", signal.symbol, exc)
            return None

    # ── ccxt multi-exchange fallback ──────────────────────────────────────────

    def execute_via_ccxt(
        self,
        exchange_id: str,
        signal: TradingSignal,
        portfolio_equity: float = 100_000.0,
    ) -> CryptoOrderResult | None:
        """Fallback execution via ccxt — supports 50+ exchanges."""
        try:
            import ccxt
        except ImportError:
            log.error("ccxt not installed — pip install ccxt")
            return None

        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            log.error("Unknown ccxt exchange: %s", exchange_id)
            return None

        exchange = exchange_cls({
            "apiKey": self._key,
            "secret": self._secret,
            "options": {"defaultType": "spot"},
        })
        if self._testnet and hasattr(exchange, "set_sandbox_mode"):
            exchange.set_sandbox_mode(True)

        pair = f"{signal.symbol[:3]}/{signal.symbol[3:]}"  # BTCUSDT → BTC/USDT
        ticker = exchange.fetch_ticker(pair)
        current_price = ticker["last"]
        max_notional = portfolio_equity * min(signal.suggested_position_pct, self._max_pos)
        amount = round(max_notional / current_price, 6)

        side = "buy" if signal.action == "BUY" else "sell"
        order = exchange.create_market_order(pair, side, amount)
        return CryptoOrderResult(
            symbol=signal.symbol,
            order_id=str(order["id"]),
            action=signal.action,
            qty=amount,
            submitted_price=current_price,
            stop_price=round(current_price * (1 - signal.stop_loss_pct), 8),
            take_profit_price=round(current_price * (1 + signal.take_profit_pct), 8),
            exchange=exchange_id,
            timestamp=datetime.now(timezone.utc),
            raw=order,
        )
