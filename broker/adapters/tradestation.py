"""TradeStation broker adapter — equities + futures via REST API v3.

Auth: OAuth 2.0 access token managed in brain/tradestation_creds.py.
Paper trading: TradeStation SIM accounts (account IDs prefixed "SIM").
  Pass paper=True to signal paper mode; account_number controls which
  account is used.
Bracket orders: Single OSO/BRK linked order group — entry market order
  with two child orders (stop-market SL + limit TP) submitted atomically.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)
_BASE = "https://api.tradestation.com/v3"


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


class TradeStationBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by TradeStation REST API v3."""

    def __init__(self, access_token: str, account_number: str, paper: bool = False) -> None:
        self._token   = access_token
        self._account = account_number
        self._paper   = paper

    @property
    def broker_name(self) -> str:
        return "tradestation"

    @property
    def is_paper(self) -> bool:
        return self._paper

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> Any:
        with httpx.Client(timeout=20) as c:
            res = c.get(f"{_BASE}{path}", headers=self._headers(), params=params or {})
        res.raise_for_status()
        return res.json()

    def _post(self, path: str, body: dict) -> Any:
        import json
        with httpx.Client(timeout=20) as c:
            res = c.post(
                f"{_BASE}{path}",
                headers=self._headers(),
                content=json.dumps(body),
            )
        res.raise_for_status()
        return res.json()

    # ── BrokerAdapter ─────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        data = self._get(f"/brokerage/accounts/{self._account}/balances")
        bals = data.get("Balances", [])
        bal  = bals[0] if bals else {}
        eq   = _f(bal.get("RealTimeEquity") or bal.get("Equity"))
        cash = _f(bal.get("CashBalance"))
        bp   = _f(bal.get("BuyingPower") or bal.get("CashBalance"))
        return AccountInfo(equity=eq, cash=cash, buying_power=bp, last_equity=eq)

    def get_all_positions(self) -> list[BrokerPosition]:
        data = self._get(f"/brokerage/accounts/{self._account}/positions")
        positions: list[BrokerPosition] = []
        for p in data.get("Positions", []):
            asset_type = p.get("AssetType", "").lower()
            positions.append(BrokerPosition(
                symbol=p.get("Symbol", ""),
                asset_class="stock" if asset_type in ("stock", "etf", "equity") else "crypto",
                qty=_f(p.get("Quantity")),
                avg_entry_price=_f(p.get("AveragePrice")),
                current_price=_f(p.get("Last")),
                market_value=_f(p.get("MarketValue")),
                unrealized_pnl=_f(p.get("UnrealizedProfitLoss")),
            ))
        return positions

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        cl_side = "SELL" if side == "BUY" else "BUY"
        int_qty = str(int(qty)) if qty == int(qty) else str(qty)

        def _leg(order_type: str, trade_action: str, duration: str = "GTC", **extra) -> dict:
            o: dict[str, Any] = {
                "AccountID":   self._account,
                "Symbol":      symbol,
                "Quantity":    int_qty,
                "OrderType":   order_type,
                "TradeAction": trade_action,
                "TimeInForce": {"Duration": duration},
                "Route":       "Intelligent",
            }
            o.update(extra)
            return o

        # BRK group: entry + TP + SL submitted atomically via ordergroups
        body: dict[str, Any] = {
            "Type": "BRK",
            "Orders": [
                _leg("Market",     side,    "DAY"),
                _leg("Limit",      cl_side, "GTC", LimitPrice=str(take_profit_price)),
                _leg("StopMarket", cl_side, "GTC", StopPrice=str(stop_price)),
            ],
        }
        resp     = self._post("/orderexecution/ordergroups", body)
        orders   = resp.get("Orders", [{}])
        order_id = orders[0].get("OrderID", "") if orders else ""

        return BrokerOrderResult(
            order_id=order_id, symbol=symbol, action=side, qty=qty,
            submitted_price=0.0, stop_price=stop_price,
            take_profit_price=take_profit_price, exchange="tradestation",
        )

    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        if qty == 0.0:
            raise ValueError("TradeStation requires share quantity — fractional/notional orders not supported")
        int_qty = str(int(qty)) if qty == int(qty) else str(qty)
        body: dict[str, Any] = {
            "AccountID":   self._account,
            "Symbol":      symbol,
            "Quantity":    int_qty,
            "OrderType":   "Market",
            "TradeAction": side,
            "TimeInForce": {"Duration": "DAY"},
            "Route":       "Intelligent",
        }
        resp     = self._post("/orderexecution/orders", body)
        orders   = resp.get("Orders", [{}])
        order_id = orders[0].get("OrderID", "") if orders else ""

        return BrokerOrderResult(
            order_id=order_id, symbol=symbol, action=side, qty=qty,
            submitted_price=0.0, stop_price=0.0, take_profit_price=0.0,
            exchange="tradestation",
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        data = self._get(f"/brokerage/accounts/{self._account}/positions")
        qty, side = 0.0, "SELL"
        for p in data.get("Positions", []):
            if p.get("Symbol", "").upper() == symbol.upper():
                raw_qty = _f(p.get("Quantity"))
                qty  = abs(raw_qty)
                side = "SELL" if raw_qty > 0 else "BUY"
                break
        return self.submit_market_order(symbol, side, qty=qty)  # type: ignore[arg-type]

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        path = f"/brokerage/accounts/{self._account}/orders" if status == "open" \
               else f"/brokerage/accounts/{self._account}/orders/historical"
        data = self._get(path, {"pageSize": str(limit)})
        orders: list[BrokerOrder] = []
        for o in data.get("Orders", [])[:limit]:
            ts  = o.get("OpenedDateTime")
            ft  = o.get("ClosedDateTime")
            legs = o.get("Legs", [{}])
            leg  = legs[0] if legs else {}
            submitted_at = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            filled_at    = datetime.fromisoformat(ft.replace("Z", "+00:00")) if ft else None
            orders.append(BrokerOrder(
                order_id=o.get("OrderID", ""),
                symbol=leg.get("Symbol", "") or o.get("Symbol", ""),
                side=leg.get("BuyOrSell", "").upper(),
                order_type=o.get("OrderType", ""),
                qty=_f(o.get("Quantity")),
                filled_qty=_f(o.get("FilledQuantity")),
                status=o.get("StatusDescription", "").lower(),
                submitted_at=submitted_at,
                filled_at=filled_at,
                limit_price=_f(o.get("LimitPrice")) or None,
                stop_price=_f(o.get("StopPrice")) or None,
                filled_avg_price=_f(o.get("FilledPrice")) or None,
            ))
        return orders
