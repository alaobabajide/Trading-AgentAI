"""Charles Schwab broker adapter — implements BrokerAdapter via Schwab Trader API.

Authentication: OAuth 2.0 (Authorization Code flow).
  • App Key + App Secret: system-level env vars (SCHWAB_APP_KEY / SCHWAB_APP_SECRET).
  • Per-user: access_token (30-min lifetime) + refresh_token (7-day lifetime),
    encrypted at rest in brain/schwab_creds.py.
  • _resolve_broker() in brain/api.py refreshes the access token before constructing
    this adapter, so the adapter is always initialised with a fresh token.

Bracket orders: Schwab supports native TRIGGER/OCO orders, giving proper
one-cancels-other semantics (both stop-loss and take-profit active simultaneously).

Crypto: NOT supported by Schwab — get_latest_crypto_price() returns 0.0.

API base: https://api.schwabapi.com
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Literal

import httpx

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)

_TRADER_BASE = "https://api.schwabapi.com/trader/v1"
_MD_BASE     = "https://api.schwabapi.com/marketdata/v1"
_TIMEOUT     = 15.0


def _ts(value) -> datetime | None:
    """Parse an ISO-8601 string to datetime, or return None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


class SchwabBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by Schwab's Individual Trader API."""

    def __init__(
        self,
        access_token: str,
        account_hash: str | None = None,
    ) -> None:
        self._token       = access_token
        self._acct_hash   = account_hash  # populated lazily on first API call if None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def broker_name(self) -> str:
        return "schwab"

    @property
    def is_paper(self) -> bool:
        return False   # Schwab Individual API is live-only

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, url: str, **params) -> dict | list:
        resp = httpx.get(url, headers=self._headers(), params=params, timeout=_TIMEOUT)
        if resp.status_code == 401:
            raise PermissionError("Schwab access token expired — reconnect in Settings")
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, json_body: dict) -> httpx.Response:
        resp = httpx.post(url, headers=self._headers(), json=json_body, timeout=_TIMEOUT)
        if resp.status_code == 401:
            raise PermissionError("Schwab access token expired — reconnect in Settings")
        resp.raise_for_status()
        return resp

    def _delete(self, url: str) -> None:
        resp = httpx.delete(url, headers=self._headers(), timeout=_TIMEOUT)
        if resp.status_code == 401:
            raise PermissionError("Schwab access token expired — reconnect in Settings")
        if resp.status_code not in (200, 204):
            resp.raise_for_status()

    # ── Account hash resolution ───────────────────────────────────────────────

    def _get_account_hash(self) -> str:
        """Resolve the account hash lazily from the accounts endpoint."""
        if self._acct_hash:
            return self._acct_hash
        data = self._get(f"{_TRADER_BASE}/accounts")
        accounts = data if isinstance(data, list) else []
        if not accounts:
            raise RuntimeError("No Schwab accounts found for this access token")
        # Use hashValue (the encrypted identifier used in API calls)
        self._acct_hash = accounts[0].get("hashValue") or accounts[0].get("encryptedId") or ""
        if not self._acct_hash:
            raise RuntimeError("Schwab account hash not available — check account type")
        log.info("Schwab account hash resolved (first account)")
        return self._acct_hash

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        data = self._get(f"{_TRADER_BASE}/accounts", fields="positions")
        accounts = data if isinstance(data, list) else []
        if not accounts:
            raise RuntimeError("No Schwab account data returned")

        acct = accounts[0]
        if not self._acct_hash:
            self._acct_hash = acct.get("hashValue") or acct.get("encryptedId") or ""

        sec = acct.get("securitiesAccount", {})
        cur = sec.get("currentBalances", {})
        ini = sec.get("initialBalances", {})

        equity       = float(cur.get("liquidationValue", 0) or 0)
        cash         = float(cur.get("cashBalance", 0) or 0)
        buying_power = float(cur.get("buyingPower", cash) or cash)
        last_equity  = float(ini.get("liquidationValue", equity) or equity)

        return AccountInfo(
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            last_equity=last_equity,
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_all_positions(self) -> list[BrokerPosition]:
        data = self._get(f"{_TRADER_BASE}/accounts", fields="positions")
        accounts = data if isinstance(data, list) else []
        if not accounts:
            return []

        acct = accounts[0]
        if not self._acct_hash:
            self._acct_hash = acct.get("hashValue") or acct.get("encryptedId") or ""

        sec       = acct.get("securitiesAccount", {})
        positions = sec.get("positions", []) or []
        result: list[BrokerPosition] = []

        for pos in positions:
            instrument = pos.get("instrument", {})
            symbol     = str(instrument.get("symbol", "?"))
            qty        = float(pos.get("longQuantity", 0) or 0) - float(pos.get("shortQuantity", 0) or 0)
            if qty == 0:
                continue
            avg_price = float(pos.get("averageLongPrice") or pos.get("averagePrice") or 0)
            mv        = float(pos.get("marketValue", 0) or 0)
            cur_price = (mv / abs(qty)) if qty != 0 and mv != 0 else avg_price
            upnl      = float(pos.get("longOpenProfitLoss", 0) or pos.get("currentDayProfitLoss", 0) or 0)
            asset_type = str(instrument.get("assetType", "")).upper()
            is_crypto  = asset_type == "CRYPTOCURRENCY"
            result.append(BrokerPosition(
                symbol=symbol,
                asset_class="crypto" if is_crypto else "stock",
                qty=qty,
                avg_entry_price=avg_price,
                current_price=cur_price,
                market_value=mv,
                unrealized_pnl=upnl,
            ))
        return result

    # ── Order submission ──────────────────────────────────────────────────────

    def _leg(self, symbol: str, qty: float, instruction: str) -> dict:
        return {
            "instruction": instruction,
            "quantity":    round(abs(qty), 8),
            "instrument":  {"symbol": symbol, "assetType": "EQUITY"},
        }

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        account_hash = self._get_account_hash()
        instruction  = "BUY" if side == "BUY" else "SELL"
        close_instr  = "SELL" if side == "BUY" else "BUY"

        order = {
            "orderType":         "MARKET",
            "session":           "NORMAL",
            "duration":          "DAY",
            "orderStrategyType": "TRIGGER",
            "orderLegCollection": [self._leg(symbol, qty, instruction)],
            "childOrderStrategies": [
                {
                    "orderStrategyType": "OCO",
                    "childOrderStrategies": [
                        # Stop-loss
                        {
                            "orderType":         "STOP",
                            "session":           "NORMAL",
                            "duration":          "GOOD_TILL_CANCEL",
                            "stopPrice":         round(stop_price, 4),
                            "orderStrategyType": "SINGLE",
                            "orderLegCollection": [self._leg(symbol, qty, close_instr)],
                        },
                        # Take-profit
                        {
                            "orderType":         "LIMIT",
                            "session":           "NORMAL",
                            "duration":          "GOOD_TILL_CANCEL",
                            "price":             round(take_profit_price, 4),
                            "orderStrategyType": "SINGLE",
                            "orderLegCollection": [self._leg(symbol, qty, close_instr)],
                        },
                    ],
                }
            ],
        }

        resp     = self._post(f"{_TRADER_BASE}/accounts/{account_hash}/orders", order)
        location = resp.headers.get("Location", "")
        order_id = location.rsplit("/", 1)[-1] if location else ""

        return BrokerOrderResult(
            order_id=order_id,
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=0.0,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            exchange="schwab",
            timestamp=datetime.now(timezone.utc),
            raw={"order_id": order_id, "location": location},
        )

    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        account_hash = self._get_account_hash()

        # Schwab doesn't support notional (fractional share) orders on equities
        if qty == 0 and notional > 0:
            try:
                quote_data = self._get(f"{_MD_BASE}/quotes", symbols=symbol)
                price = float(
                    (quote_data.get(symbol, {}) or {})
                    .get("quote", {})
                    .get("lastPrice", 0)
                    or 0
                )
                if price > 0:
                    qty = round(notional / price)
            except Exception:
                pass
            if qty == 0:
                raise ValueError(f"Cannot determine integer quantity for {symbol} — price unavailable")

        instruction = "BUY" if side == "BUY" else "SELL"
        order = {
            "orderType":         "MARKET",
            "session":           "NORMAL",
            "duration":          "DAY",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [self._leg(symbol, qty, instruction)],
        }

        resp     = self._post(f"{_TRADER_BASE}/accounts/{account_hash}/orders", order)
        location = resp.headers.get("Location", "")
        order_id = location.rsplit("/", 1)[-1] if location else ""

        return BrokerOrderResult(
            order_id=order_id,
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=0.0,
            stop_price=0.0,
            take_profit_price=0.0,
            exchange="schwab",
            timestamp=datetime.now(timezone.utc),
            raw={"order_id": order_id},
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        positions = self.get_all_positions()
        pos = next((p for p in positions if p.symbol == symbol), None)
        if pos is None:
            raise ValueError(f"No open Schwab position for {symbol}")
        side = "SELL" if pos.qty > 0 else "BUY"
        return self.submit_market_order(symbol, side, qty=abs(pos.qty))

    # ── Order history ─────────────────────────────────────────────────────────

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        account_hash = self._get_account_hash()
        now       = int(time.time())
        from_time = datetime.fromtimestamp(now - 86400 * 90, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to_time   = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        schwab_status = "WORKING" if status == "open" else "ALL"
        try:
            data = self._get(
                f"{_TRADER_BASE}/accounts/{account_hash}/orders",
                status=schwab_status,
                fromEnteredTime=from_time,
                toEnteredTime=to_time,
                maxResults=limit,
            )
        except Exception as exc:
            log.warning("Schwab order history failed: %s", exc)
            return []

        orders = data if isinstance(data, list) else []
        result: list[BrokerOrder] = []
        for o in orders[:limit]:
            legs = o.get("orderLegCollection") or []
            leg0 = legs[0] if legs else {}
            sym  = str((leg0.get("instrument") or {}).get("symbol", "?"))
            instr = str(leg0.get("instruction", "")).lower()
            qty   = float(leg0.get("quantity", 0) or 0)
            result.append(BrokerOrder(
                order_id=str(o.get("orderId", "") or ""),
                symbol=sym,
                side=instr,
                order_type=str(o.get("orderType", "market")).lower(),
                qty=qty,
                filled_qty=float(o.get("filledQuantity", 0) or 0),
                status=str(o.get("status", "unknown")).lower(),
                submitted_at=_ts(o.get("enteredTime")),
                filled_at=_ts(o.get("closeTime")),
                limit_price=float(o.get("price", 0) or 0) or None,
                stop_price=float(o.get("stopPrice", 0) or 0) or None,
                filled_avg_price=float(o.get("price", 0) or 0) or None,
            ))
        return result
