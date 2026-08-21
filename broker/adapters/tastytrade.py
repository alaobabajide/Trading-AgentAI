"""tastytrade broker adapter — implements BrokerAdapter using the tastytrade SDK.

Credentials flow:
  brain/tastytrade_creds.py → TastytradeBrokerAdapter(username, password, account_number, paper)

Session management:
  Sessions are created lazily on first use and cached per adapter instance.
  Auth errors trigger session invalidation; the next call reconnects automatically.

Bracket orders:
  tastytrade does not support native bracket orders in a single API call.
  submit_bracket_order() places a market entry + GTC stop-loss stop order.
  The take-profit price is recorded in BrokerOrderResult but NOT submitted,
  to avoid an open OCO conflict if both stop and TP were active simultaneously.
  Phase C+: replace with conditional order pairs once OCO is exposed in the SDK.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)


def _f(value, default: float = 0.0) -> float:
    """Safely convert Decimal / str / None to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return default


class TastytradeBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by tastytrade's trading API."""

    def __init__(
        self,
        username: str,
        password: str,
        account_number: str | None = None,
        paper: bool = True,
    ) -> None:
        self._username        = username
        self._password        = password
        self._account_number  = account_number
        self._paper           = paper
        self._session         = None
        self._account         = None
        self._lock            = threading.Lock()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def broker_name(self) -> str:
        return "tastytrade_paper" if self._paper else "tastytrade_live"

    @property
    def is_paper(self) -> bool:
        return self._paper

    # ── Session management ────────────────────────────────────────────────────

    def _get(self):
        """Return (session, account), connecting lazily if needed."""
        if self._session is None or self._account is None:
            with self._lock:
                if self._session is None or self._account is None:
                    self._connect()
        return self._session, self._account

    def _connect(self) -> None:
        if self._paper:
            from tastytrade import Session as TastySession
            session = TastySession(self._username, self._password)
        else:
            from tastytrade import ProductionSession
            session = ProductionSession(self._username, self._password)

        from tastytrade.account import Account
        accounts = Account.get_accounts(session)
        if not accounts:
            raise RuntimeError("No tastytrade accounts found — check credentials")

        if self._account_number:
            acct = next(
                (a for a in accounts if a.account_number == self._account_number),
                None,
            )
            if acct is None:
                available = [a.account_number for a in accounts]
                raise ValueError(f"Account '{self._account_number}' not found. Available: {available}")
        else:
            acct = accounts[0]

        self._session = session
        self._account = acct
        log.info("tastytrade session opened — account %s (paper=%s)", acct.account_number, self._paper)

    def _on_auth_error(self, exc: Exception) -> None:
        """Invalidate the session on 401/token-expired so the next call reconnects."""
        msg = str(exc).lower()
        if any(k in msg for k in ("401", "unauthorized", "expired", "forbidden", "token")):
            log.warning("tastytrade session invalidated — will reconnect on next call")
            with self._lock:
                self._session = None
                self._account = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _inst(symbol: str):
        from tastytrade.order import InstrumentType
        return InstrumentType.CRYPTOCURRENCY if "/" in symbol else InstrumentType.EQUITY

    @staticmethod
    def _dec(value: float) -> Decimal:
        return Decimal(str(round(value, 8)))

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        session, account = self._get()
        try:
            bal = account.get_balances(session)
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        equity = _f(bal.net_liquidating_value)
        cash   = _f(bal.cash_balance)
        buying_power = _f(
            getattr(bal, "derivative_buying_power", None)
            or getattr(bal, "equity_buying_power", None)
            or cash
        )
        # Approximate last_equity from daily P&L components
        day_real  = _f(getattr(bal, "realized_day_gain",   None))
        day_unrl  = _f(getattr(bal, "unrealized_day_gain", None))
        last_eq   = (equity - day_real - day_unrl) or equity

        return AccountInfo(
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            last_equity=last_eq,
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_all_positions(self) -> list[BrokerPosition]:
        session, account = self._get()
        try:
            raw = account.get_positions(session)
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        result: list[BrokerPosition] = []
        for pos in raw:
            qty = _f(pos.quantity)
            if qty == 0:
                continue
            sym       = str(pos.symbol)
            avg_price = _f(pos.average_open_price)
            cur_price = _f(getattr(pos, "close_price", None) or avg_price)
            mv        = _f(getattr(pos, "market_value", None) or qty * cur_price)
            upnl      = _f(getattr(pos, "unrealized_day_gain", None) or (mv - qty * avg_price))
            inst_str  = str(getattr(pos, "instrument_type", "")).lower()
            is_crypto = "crypto" in inst_str
            result.append(BrokerPosition(
                symbol=sym,
                asset_class="crypto" if is_crypto else "stock",
                qty=qty,
                avg_entry_price=avg_price,
                current_price=cur_price,
                market_value=mv,
                unrealized_pnl=upnl,
            ))
        return result

    # ── Order submission ──────────────────────────────────────────────────────

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        from tastytrade.order import (
            NewOrder, Leg, OrderAction, OrderTimeInForce, OrderType,
        )
        session, account = self._get()
        inst = self._inst(symbol)

        entry_action = OrderAction.BUY_TO_OPEN if side == "BUY" else OrderAction.SELL_TO_OPEN

        entry_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[Leg(
                instrument_type=inst,
                symbol=symbol,
                quantity=self._dec(qty),
                action=entry_action,
            )],
        )
        try:
            entry_resp = account.place_order(session, entry_order, dry_run=False)
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        entry_id = str(getattr(entry_resp.order, "id", "") or "")

        # Protective stop-loss (GTC) — does not submit TP to avoid open OCO conflict
        if stop_price > 0 and side == "BUY":
            try:
                sl_order = NewOrder(
                    time_in_force=OrderTimeInForce.GTC,
                    order_type=OrderType.STOP,
                    stop_trigger=self._dec(stop_price),
                    legs=[Leg(
                        instrument_type=inst,
                        symbol=symbol,
                        quantity=self._dec(qty),
                        action=OrderAction.SELL_TO_CLOSE,
                    )],
                )
                account.place_order(session, sl_order, dry_run=False)
                log.info("tastytrade stop-loss placed at %.4f for %s x%.4f", stop_price, symbol, qty)
            except Exception as exc:
                log.warning("tastytrade stop-loss submission failed (entry already placed): %s", exc)

        exchange = "tastytrade_paper" if self._paper else "tastytrade_live"
        return BrokerOrderResult(
            order_id=entry_id,
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=0.0,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            raw=entry_resp,
        )

    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        from tastytrade.order import NewOrder, Leg, OrderAction, OrderTimeInForce, OrderType

        session, account = self._get()
        inst   = self._inst(symbol)
        action = OrderAction.BUY_TO_OPEN if side == "BUY" else OrderAction.SELL_TO_CLOSE

        # tastytrade has no notional orders — estimate qty from current position price
        if qty == 0 and notional > 0:
            try:
                positions = account.get_positions(session)
                pos = next((p for p in positions if str(p.symbol) == symbol), None)
                cur_price = _f(getattr(pos, "close_price", None)) if pos else 0.0
                if cur_price > 0:
                    qty = round(notional / cur_price, 8)
            except Exception:
                pass
            if qty == 0:
                raise ValueError(f"Cannot determine qty for notional order on {symbol}: price unavailable")

        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[Leg(
                instrument_type=inst,
                symbol=symbol,
                quantity=self._dec(qty),
                action=action,
            )],
        )
        try:
            resp = account.place_order(session, order, dry_run=False)
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        order_id = str(getattr(resp.order, "id", "") or "")
        exchange  = "tastytrade_paper" if self._paper else "tastytrade_live"
        return BrokerOrderResult(
            order_id=order_id,
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=0.0,
            stop_price=0.0,
            take_profit_price=0.0,
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            raw=resp,
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        from tastytrade.order import NewOrder, Leg, OrderAction, OrderTimeInForce, OrderType

        session, account = self._get()
        try:
            positions = account.get_positions(session)
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        pos = next((p for p in positions if str(p.symbol) == symbol), None)
        if pos is None:
            raise ValueError(f"No open tastytrade position for {symbol}")

        qty    = abs(_f(pos.quantity))
        inst   = self._inst(symbol)
        action = (
            OrderAction.SELL_TO_CLOSE if _f(pos.quantity) > 0 else OrderAction.BUY_TO_CLOSE
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[Leg(
                instrument_type=inst,
                symbol=symbol,
                quantity=self._dec(qty),
                action=action,
            )],
        )
        try:
            resp = account.place_order(session, order, dry_run=False)
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        order_id = str(getattr(resp.order, "id", "") or "")
        exchange  = "tastytrade_paper" if self._paper else "tastytrade_live"
        return BrokerOrderResult(
            order_id=order_id,
            symbol=symbol,
            action="SELL",
            qty=qty,
            submitted_price=0.0,
            stop_price=0.0,
            take_profit_price=0.0,
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            raw=resp,
        )

    # ── Order history ─────────────────────────────────────────────────────────

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        session, account = self._get()
        try:
            if status == "open":
                raw = (
                    account.get_live_orders(session)
                    if hasattr(account, "get_live_orders")
                    else account.get_orders(session)
                )
            else:
                raw = (
                    account.get_order_history(session)
                    if hasattr(account, "get_order_history")
                    else account.get_orders(session)
                )
        except Exception as exc:
            self._on_auth_error(exc)
            raise

        result: list[BrokerOrder] = []
        for o in raw[:limit]:
            legs = getattr(o, "legs", []) or []
            leg0 = legs[0] if legs else None
            sym  = str(getattr(leg0, "symbol", None) or getattr(o, "symbol", "?"))
            side = str(getattr(leg0, "action", "")).replace("_", " ").lower()
            qty  = _f(getattr(leg0, "quantity", None) or 0)
            result.append(BrokerOrder(
                order_id=str(getattr(o, "id", "") or ""),
                symbol=sym,
                side=side,
                order_type=str(getattr(o, "order_type", "market")),
                qty=qty,
                filled_qty=_f(getattr(o, "filled_quantity", None) or 0),
                status=str(getattr(o, "status", "unknown")),
                submitted_at=getattr(o, "received_at", None),
                filled_at=getattr(o, "updated_at", None),
                limit_price=_f(getattr(o, "price", None)) or None,
                stop_price=_f(getattr(o, "stop_trigger", None)) or None,
                filled_avg_price=_f(getattr(o, "price", None)) or None,
            ))
        return result
