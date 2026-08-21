"""Kraken broker adapter — spot crypto via REST API v0.

Auth: HMAC-SHA512 with base64-encoded API secret.
Paper trading: Not supported for Kraken spot (live only).
Bracket orders: Main market order + conditional SL close, then a separate
  take-profit order. Both are active after entry fill.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import logging
import time
import urllib.parse
from typing import Any, Literal

import httpx

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)
_BASE = "https://api.kraken.com"

_PAIR_MAP: dict[str, str] = {
    "BTC":   "XXBTZUSD",
    "ETH":   "XETHZUSD",
    "SOL":   "SOLUSD",
    "ADA":   "ADAUSD",
    "DOT":   "DOTUSD",
    "MATIC": "MATICUSD",
    "LINK":  "LINKUSD",
    "UNI":   "UNIUSD",
    "LTC":   "XLTCZUSD",
    "XRP":   "XXRPZUSD",
    "DOGE":  "XDOGEZUSD",
    "AVAX":  "AVAXUSD",
    "ATOM":  "ATOMUSD",
}

_FIAT = {"ZUSD", "USD", "ZEUR", "EUR", "ZGBP", "GBP", "ZCAD", "CAD", "ZJPY", "JPY"}


class KrakenBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by Kraken REST API v0 (spot)."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key    = api_key
        self._api_secret = api_secret

    @property
    def broker_name(self) -> str:
        return "kraken"

    @property
    def is_paper(self) -> bool:
        return False

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _sign(self, url_path: str, data: dict) -> dict[str, str]:
        nonce    = str(int(time.time() * 1000))
        data["nonce"] = nonce
        post_str = urllib.parse.urlencode(data)
        encoded  = (nonce + post_str).encode()
        message  = url_path.encode() + hashlib.sha256(encoded).digest()
        mac      = _hmac.new(base64.b64decode(self._api_secret), message, hashlib.sha512)
        return {
            "API-Key":  self._api_key,
            "API-Sign": base64.b64encode(mac.digest()).decode(),
        }

    def _private(self, path: str, data: dict | None = None) -> Any:
        data    = dict(data or {})
        headers = self._sign(path, data)
        with httpx.Client(timeout=20) as c:
            res = c.post(f"{_BASE}{path}", data=data, headers=headers)
        res.raise_for_status()
        body = res.json()
        if body.get("error"):
            raise RuntimeError(f"Kraken: {body['error']}")
        return body.get("result", {})

    def _public(self, path: str, params: dict | None = None) -> Any:
        with httpx.Client(timeout=10) as c:
            res = c.get(f"{_BASE}{path}", params=params or {})
        res.raise_for_status()
        body = res.json()
        if body.get("error"):
            raise RuntimeError(f"Kraken: {body['error']}")
        return body.get("result", {})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pair(self, symbol: str) -> str:
        return _PAIR_MAP.get(symbol.upper(), f"{symbol.upper()}USD")

    def _normalize(self, asset: str) -> str:
        if len(asset) == 4 and asset[0] in ("X", "Z"):
            return asset[1:]
        return asset

    # ── BrokerAdapter ─────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        balance = self._private("/0/private/Balance")
        usd = float(balance.get("ZUSD", balance.get("USD", 0.0)))
        return AccountInfo(equity=usd, cash=usd, buying_power=usd, last_equity=usd)

    def get_all_positions(self) -> list[BrokerPosition]:
        balance   = self._private("/0/private/Balance")
        positions: list[BrokerPosition] = []
        for asset, qty_str in balance.items():
            if asset in _FIAT:
                continue
            qty = float(qty_str)
            if qty <= 0:
                continue
            positions.append(BrokerPosition(
                symbol=self._normalize(asset),
                asset_class="crypto",
                qty=qty,
                avg_entry_price=0.0,
                current_price=0.0,
                market_value=0.0,
                unrealized_pnl=0.0,
            ))
        return positions

    def get_latest_crypto_price(self, symbol: str) -> float:
        try:
            ticker = self._public("/0/public/Ticker", {"pair": self._pair(symbol)})
            for data in ticker.values():
                return float(data["c"][0])
        except Exception as exc:
            log.warning("Kraken price fetch failed for %s: %s", symbol, exc)
        return 0.0

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        pair    = self._pair(symbol)
        kside   = "buy" if side == "BUY" else "sell"
        cl_side = "sell" if side == "BUY" else "buy"

        # Entry with conditional stop-loss close
        data: dict[str, Any] = {
            "pair":             pair,
            "type":             kside,
            "ordertype":        "market",
            "volume":           str(qty),
            "close[ordertype]": "stop-loss",
            "close[price]":     str(stop_price),
        }
        result   = self._private("/0/private/AddOrder", data)
        txids    = result.get("txid", [])
        order_id = txids[0] if txids else f"kraken-{int(time.time())}"

        # Separate take-profit order
        try:
            self._private("/0/private/AddOrder", {
                "pair":      pair,
                "type":      cl_side,
                "ordertype": "take-profit",
                "price":     str(take_profit_price),
                "volume":    str(qty),
            })
        except Exception as exc:
            log.warning("Kraken TP placement failed (SL is active): %s", exc)

        return BrokerOrderResult(
            order_id=order_id, symbol=symbol, action=side, qty=qty,
            submitted_price=0.0, stop_price=stop_price,
            take_profit_price=take_profit_price, exchange="kraken",
        )

    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        if qty == 0.0 and notional > 0:
            price = self.get_latest_crypto_price(symbol)
            qty   = round(notional / price, 8) if price else 0.0
        result   = self._private("/0/private/AddOrder", {
            "pair": self._pair(symbol), "type": "buy" if side == "BUY" else "sell",
            "ordertype": "market", "volume": str(qty),
        })
        txids    = result.get("txid", [])
        order_id = txids[0] if txids else f"kraken-{int(time.time())}"
        return BrokerOrderResult(
            order_id=order_id, symbol=symbol, action=side, qty=qty,
            submitted_price=0.0, stop_price=0.0, take_profit_price=0.0,
            exchange="kraken",
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        balance = self._private("/0/private/Balance")
        qty = 0.0
        for asset, qty_str in balance.items():
            if self._normalize(asset).upper() == symbol.upper():
                qty = float(qty_str)
                break
        return self.submit_market_order(symbol, "SELL", qty=qty)

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        if status == "open":
            raw = self._private("/0/private/OpenOrders").get("open", {})
        else:
            raw = self._private("/0/private/ClosedOrders").get("closed", {})
        orders: list[BrokerOrder] = []
        for txid, o in list(raw.items())[:limit]:
            descr = o.get("descr", {})
            orders.append(BrokerOrder(
                order_id=txid,
                symbol=descr.get("pair", ""),
                side=descr.get("type", "").upper(),
                order_type=descr.get("ordertype", ""),
                qty=float(o.get("vol", 0)),
                filled_qty=float(o.get("vol_exec", 0)),
                status=o.get("status", ""),
                submitted_at=None,
                filled_at=None,
                limit_price=None,
                stop_price=float(o.get("stopprice", 0)) or None,
                filled_avg_price=float(o.get("price", 0)) or None,
            ))
        return orders
