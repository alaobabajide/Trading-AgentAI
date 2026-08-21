"""Coinbase Advanced Trade broker adapter — crypto via REST API v3.

Auth: Coinbase Cloud Developer Platform (CDP) ES256 JWT.
  api_key_name:  "organizations/{org_id}/apiKeys/{key_id}"
  private_key:   EC P-256 PEM private key

Paper trading: Not supported (sandbox requires separate CDP credentials).
Bracket orders: Entry market order, then separate SL (stop-limit GTC) and
  TP (limit GTC) orders. Coinbase does not support native one-call brackets.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

import httpx

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)
_BASE = "https://api.coinbase.com"


class CoinbaseBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by Coinbase Advanced Trade API v3."""

    def __init__(self, api_key_name: str, private_key_pem: str) -> None:
        self._api_key = api_key_name
        self._pem     = private_key_pem.replace("\\n", "\n")

    @property
    def broker_name(self) -> str:
        return "coinbase"

    @property
    def is_paper(self) -> bool:
        return False

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _jwt(self, method: str, path: str) -> str:
        import jwt as _jwt
        now = int(time.time())
        return _jwt.encode(
            {
                "sub": self._api_key,
                "iss": "cdp",
                "nbf": now,
                "exp": now + 120,
                "uri": f"{method} api.coinbase.com{path}",
            },
            self._pem,
            algorithm="ES256",
            headers={"kid": self._api_key, "nonce": str(now)},
        )

    def _headers(self, method: str, path: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._jwt(method, path)}",
            "Content-Type":  "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> Any:
        with httpx.Client(timeout=20) as c:
            res = c.get(
                f"{_BASE}{path}",
                headers=self._headers("GET", path),
                params=params or {},
            )
        res.raise_for_status()
        return res.json()

    def _post(self, path: str, body: dict) -> Any:
        import json
        with httpx.Client(timeout=20) as c:
            res = c.post(
                f"{_BASE}{path}",
                headers=self._headers("POST", path),
                content=json.dumps(body),
            )
        res.raise_for_status()
        return res.json()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _product_id(self, symbol: str) -> str:
        sym = symbol.upper()
        if "-" in sym:
            return sym
        if sym.endswith("USD"):
            return f"{sym[:-3]}-USD"
        return f"{sym}-USD"

    # ── BrokerAdapter ─────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        data = self._get("/api/v3/brokerage/accounts")
        usd  = sum(
            float(a.get("available_balance", {}).get("value", 0))
            for a in data.get("accounts", [])
            if a.get("currency") == "USD"
        )
        return AccountInfo(equity=usd, cash=usd, buying_power=usd, last_equity=usd)

    def get_all_positions(self) -> list[BrokerPosition]:
        data      = self._get("/api/v3/brokerage/accounts")
        positions: list[BrokerPosition] = []
        for acct in data.get("accounts", []):
            currency = acct.get("currency", "")
            if currency == "USD":
                continue
            qty = float(acct.get("available_balance", {}).get("value", 0))
            if qty <= 0:
                continue
            positions.append(BrokerPosition(
                symbol=currency,
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
            pid  = self._product_id(symbol)
            data = self._get("/api/v3/brokerage/best_bid_ask", {"product_ids": pid})
            for pb in data.get("pricebooks", []):
                bids, asks = pb.get("bids", []), pb.get("asks", [])
                if bids and asks:
                    return (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
        except Exception as exc:
            log.warning("Coinbase price fetch failed for %s: %s", symbol, exc)
        return 0.0

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        pid     = self._product_id(symbol)
        cl_side = "SELL" if side == "BUY" else "BUY"
        ts      = int(time.time())

        # Entry
        entry = self._post("/api/v3/brokerage/orders", {
            "client_order_id":     f"ta-entry-{ts}",
            "product_id":          pid,
            "side":                side,
            "order_configuration": {"market_market_ioc": {"base_size": str(qty)}},
        })
        order_id = (
            entry.get("success_response", {}).get("order_id")
            or entry.get("order_id", f"cb-{ts}")
        )

        # Stop-loss
        stop_dir = "STOP_DIRECTION_STOP_DOWN" if side == "BUY" else "STOP_DIRECTION_STOP_UP"
        try:
            self._post("/api/v3/brokerage/orders", {
                "client_order_id": f"ta-sl-{ts}",
                "product_id":      pid,
                "side":            cl_side,
                "order_configuration": {
                    "stop_limit_stop_limit_gtc": {
                        "base_size":      str(qty),
                        "limit_price":    str(stop_price),
                        "stop_price":     str(stop_price),
                        "stop_direction": stop_dir,
                    },
                },
            })
        except Exception as exc:
            log.warning("Coinbase SL order failed: %s", exc)

        # Take-profit
        try:
            self._post("/api/v3/brokerage/orders", {
                "client_order_id": f"ta-tp-{ts}",
                "product_id":      pid,
                "side":            cl_side,
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size":   str(qty),
                        "limit_price": str(take_profit_price),
                        "post_only":   False,
                    },
                },
            })
        except Exception as exc:
            log.warning("Coinbase TP order failed: %s", exc)

        return BrokerOrderResult(
            order_id=order_id, symbol=symbol, action=side, qty=qty,
            submitted_price=0.0, stop_price=stop_price,
            take_profit_price=take_profit_price, exchange="coinbase",
        )

    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        pid = self._product_id(symbol)
        if qty > 0:
            order_conf = {"market_market_ioc": {"base_size": str(qty)}}
        else:
            order_conf = {"market_market_ioc": {"quote_size": str(notional)}}
        ts   = int(time.time())
        resp = self._post("/api/v3/brokerage/orders", {
            "client_order_id":     f"ta-mkt-{ts}",
            "product_id":          pid,
            "side":                side,
            "order_configuration": order_conf,
        })
        order_id = (
            resp.get("success_response", {}).get("order_id")
            or resp.get("order_id", f"cb-{ts}")
        )
        return BrokerOrderResult(
            order_id=order_id, symbol=symbol, action=side,
            qty=qty if qty > 0 else notional,
            submitted_price=0.0, stop_price=0.0, take_profit_price=0.0,
            exchange="coinbase",
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        data    = self._get("/api/v3/brokerage/accounts")
        sym_key = symbol.upper().removesuffix("USD")
        qty     = 0.0
        for acct in data.get("accounts", []):
            if acct.get("currency", "").upper() == sym_key:
                qty = float(acct.get("available_balance", {}).get("value", 0))
                break
        return self.submit_market_order(symbol, "SELL", qty=qty)

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        params: dict[str, Any] = {"limit": str(limit)}
        if status == "open":
            params["order_status"] = "OPEN"
        data = self._get("/api/v3/brokerage/orders/historical/batch", params)
        orders: list[BrokerOrder] = []
        for o in data.get("orders", []):
            cfg  = o.get("order_configuration", {})
            lim  = cfg.get("limit_limit_gtc") or cfg.get("limit_limit_gtd") or {}
            stop = cfg.get("stop_limit_stop_limit_gtc") or {}
            orders.append(BrokerOrder(
                order_id=o.get("order_id", ""),
                symbol=o.get("product_id", "").replace("-", ""),
                side=o.get("side", ""),
                order_type=o.get("order_type", ""),
                qty=float(o.get("base_size") or 0),
                filled_qty=float(o.get("filled_size") or 0),
                status=o.get("status", "").lower(),
                submitted_at=None,
                filled_at=None,
                limit_price=float(lim.get("limit_price", 0)) or None,
                stop_price=float(stop.get("stop_price", 0)) or None,
                filled_avg_price=float(o.get("average_filled_price") or 0) or None,
            ))
        return orders
