"""Interactive Brokers broker adapter — implements BrokerAdapter via ib_insync.

Connection model: IB Gateway (or TWS) must be running externally.
The adapter connects synchronously per-request — IB Gateway allows multiple
connections with different clientIds so concurrent users don't block each other.

Authentication lives in IB Gateway itself (user logs into Gateway/TWS once).
No credentials are stored by this adapter.

Default port:
  4001 — IB Gateway live
  4002 — IB Gateway paper (preferred; adapter defaults to 4002)
  7496 — TWS live
  7497 — TWS paper

Crypto: supported via PAXOS exchange. Symbol must be the base asset (e.g. "BTC",
not "BTC/USD"). Quotes use snapshot market data; may require market data subscription.

Bracket orders: IBKR supports native bracket via linked parentId orders — parent
market order + OCO take-profit limit + stop-loss stop, all transmitted together.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Literal

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10   # seconds
_MD_TIMEOUT      = 5    # seconds to wait for market data snapshot


def _ib_import():
    try:
        import ib_insync
        return ib_insync
    except ImportError as exc:
        raise RuntimeError(
            "ib_insync is required for Interactive Brokers — install it with: pip install ib_insync"
        ) from exc


def _make_contract(ibs, symbol: str, asset_class: str):
    """Return an IBKR Contract for the given symbol and asset class."""
    if asset_class == "crypto":
        return ibs.Crypto(symbol.replace("/USD", "").replace("-USD", ""), "PAXOS", "USD")
    return ibs.Stock(symbol, "SMART", "USD")


class IBKRBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by Interactive Brokers via ib_insync.

    Each public method opens a fresh IB connection, performs the operation,
    and disconnects. This is slightly slower than a persistent connection but
    is safe for multi-user scenarios where each user may have different settings.
    """

    def __init__(
        self,
        host:       str  = "127.0.0.1",
        port:       int  = 4002,
        client_id:  int  = 1,
        account_id: str  = "",
        paper:      bool = True,
    ) -> None:
        self._host       = host
        self._port       = port
        self._client_id  = client_id
        self._account_id = account_id   # empty → auto-detected on first call
        self._paper      = paper

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def broker_name(self) -> str:
        return "ibkr"

    @property
    def is_paper(self) -> bool:
        return self._paper

    # ── Connection helpers ────────────────────────────────────────────────────

    def _connect(self):
        """Return a connected IB instance. Caller must call ib.disconnect()."""
        ibs = _ib_import()
        ib  = ibs.IB()
        try:
            ib.connect(
                self._host, self._port,
                clientId=self._client_id,
                readonly=False,
                timeout=_CONNECT_TIMEOUT,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to IB Gateway at {self._host}:{self._port} — "
                f"ensure IB Gateway is running and API connections are enabled: {exc}"
            ) from exc
        if not self._account_id:
            accts = ib.managedAccounts()
            self._account_id = accts[0] if accts else ""
        return ib

    def _acct(self) -> str:
        return self._account_id or ""

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        ib = self._connect()
        try:
            ib.reqAccountUpdates(True, self._acct())
            ib.sleep(1.0)   # allow account data to arrive
            vals = {v.tag: v.value for v in ib.accountValues(self._acct())}

            equity       = float(vals.get("NetLiquidation",  0) or 0)
            cash         = float(vals.get("CashBalance",     0) or 0)
            buying_power = float(vals.get("BuyingPower",  cash) or cash)
            last_equity  = float(vals.get("PreviousDayEquityWithLoanValue", equity) or equity)
        finally:
            ib.disconnect()

        return AccountInfo(
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            last_equity=last_equity,
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_all_positions(self) -> list[BrokerPosition]:
        ib = self._connect()
        try:
            positions = ib.positions(self._acct())
        finally:
            ib.disconnect()

        result: list[BrokerPosition] = []
        for pos in positions:
            contract   = pos.contract
            qty        = float(pos.position or 0)
            if qty == 0:
                continue
            avg_price  = float(pos.avgCost or 0)
            asset_type = str(getattr(contract, "secType", "STK")).upper()
            is_crypto  = asset_type == "CRYPTO"
            # Market value and unrealized P&L not available from positions()
            # without subscribing to market data per position
            result.append(BrokerPosition(
                symbol=str(contract.symbol or "?"),
                asset_class="crypto" if is_crypto else "stock",
                qty=qty,
                avg_entry_price=avg_price,
                current_price=avg_price,   # best-effort without live quote
                market_value=qty * avg_price,
                unrealized_pnl=0.0,
            ))
        return result

    # ── Market data (snapshot) ────────────────────────────────────────────────

    def _snapshot_price(self, ib, contract) -> float:
        """Return latest mid-price via a market data snapshot (no subscription needed)."""
        ibs = _ib_import()
        ticker = ib.reqMktData(contract, "", snapshot=True, regulatorySnapshot=False)
        deadline = time.monotonic() + _MD_TIMEOUT
        while time.monotonic() < deadline:
            ib.sleep(0.2)
            if ticker.last and ticker.last > 0:
                return float(ticker.last)
            if ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                return float((ticker.bid + ticker.ask) / 2)
        ib.cancelMktData(ticker.contract)
        return 0.0

    def get_latest_crypto_price(self, symbol: str) -> float:
        ibs = _ib_import()
        clean_sym = symbol.replace("/USD", "").replace("-USD", "").replace("USD", "")
        contract  = ibs.Crypto(clean_sym, "PAXOS", "USD")
        ib = self._connect()
        try:
            price = self._snapshot_price(ib, contract)
        finally:
            ib.disconnect()
        return price

    # ── Order submission ──────────────────────────────────────────────────────

    def _place_bracket(
        self,
        ib,
        contract,
        action:            str,
        qty:               float,
        stop_price:        float,
        take_profit_price: float,
    ) -> str:
        """Place a native IBKR bracket order and return the parent order ID."""
        ibs         = _ib_import()
        reverse_act = "SELL" if action == "BUY" else "BUY"

        parent = ibs.MarketOrder(action, qty)
        parent.orderId  = ib.client.getReqId()
        parent.transmit = False

        tp = ibs.LimitOrder(reverse_act, qty, round(take_profit_price, 4))
        tp.orderId  = ib.client.getReqId()
        tp.parentId = parent.orderId
        tp.transmit = False

        sl = ibs.StopOrder(reverse_act, qty, round(stop_price, 4))
        sl.orderId  = ib.client.getReqId()
        sl.parentId = parent.orderId
        sl.tif      = "GTC"
        sl.transmit = True   # transmit=True on last order sends all three at once

        for order in (parent, tp, sl):
            ib.placeOrder(contract, order)

        ib.sleep(1.0)   # allow acknowledgement
        return str(parent.orderId)

    def submit_bracket_order(
        self,
        symbol:            str,
        qty:               float,
        side:              Literal["BUY", "SELL"],
        stop_price:        float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        asset_class = "crypto" if "/" in symbol or symbol.endswith("USD") else "stock"
        ib       = self._connect()
        try:
            contract = _make_contract(_ib_import(), symbol, asset_class)
            order_id = self._place_bracket(ib, contract, side, qty, stop_price, take_profit_price)
        finally:
            ib.disconnect()

        return BrokerOrderResult(
            order_id=order_id,
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=0.0,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            exchange="ibkr",
            timestamp=datetime.now(timezone.utc),
            raw={"order_id": order_id},
        )

    def submit_market_order(
        self,
        symbol:   str,
        side:     Literal["BUY", "SELL"],
        qty:      float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        ibs         = _ib_import()
        asset_class = "crypto" if "/" in symbol or symbol.endswith("USD") else "stock"
        ib = self._connect()
        try:
            contract = _make_contract(ibs, symbol, asset_class)

            if qty == 0 and notional > 0:
                price = self._snapshot_price(ib, contract)
                if price > 0:
                    qty = round(notional / price, 8 if asset_class == "crypto" else 0)
                if qty == 0:
                    raise ValueError(f"Cannot determine quantity for {symbol} — price unavailable")

            order    = ibs.MarketOrder(side, qty)
            order.orderId = ib.client.getReqId()
            trade    = ib.placeOrder(contract, order)
            ib.sleep(1.0)
            order_id = str(order.orderId)
        finally:
            ib.disconnect()

        return BrokerOrderResult(
            order_id=order_id,
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=0.0,
            stop_price=0.0,
            take_profit_price=0.0,
            exchange="ibkr",
            timestamp=datetime.now(timezone.utc),
            raw={"order_id": order_id},
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        positions = self.get_all_positions()
        pos = next((p for p in positions if p.symbol == symbol), None)
        if pos is None:
            raise ValueError(f"No open IBKR position for {symbol}")
        side = "SELL" if pos.qty > 0 else "BUY"
        return self.submit_market_order(symbol, side, qty=abs(pos.qty))

    # ── Order history ─────────────────────────────────────────────────────────

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        ib = self._connect()
        try:
            if status == "open":
                raw_trades = ib.openTrades()
            else:
                raw_trades = list(ib.trades())
                ib.reqCompletedOrders(apiOnly=True)
                ib.sleep(0.5)
                raw_trades = list(ib.trades())
        except Exception as exc:
            log.warning("IBKR order history failed: %s", exc)
            raw_trades = []
        finally:
            ib.disconnect()

        result: list[BrokerOrder] = []
        for trade in raw_trades[:limit]:
            order    = trade.order
            contract = trade.contract
            log_entry = trade.log[-1] if trade.log else None
            filled_at = None
            if log_entry and hasattr(log_entry, "time"):
                filled_at = log_entry.time

            o_status = str(trade.orderStatus.status or "unknown").lower()
            result.append(BrokerOrder(
                order_id=str(order.orderId or ""),
                symbol=str(contract.symbol or "?"),
                side=str(order.action or "").lower(),
                order_type=str(order.orderType or "market").lower(),
                qty=float(order.totalQuantity or 0),
                filled_qty=float(trade.orderStatus.filled or 0),
                status=o_status,
                submitted_at=None,
                filled_at=filled_at,
                limit_price=float(order.lmtPrice or 0) or None,
                stop_price=float(order.auxPrice or 0) or None,
                filled_avg_price=float(trade.orderStatus.avgFillPrice or 0) or None,
            ))
        return result
