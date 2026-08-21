"""Alpaca broker adapter — implements BrokerAdapter using alpaca-py.

Extracts all Alpaca SDK calls from execution engines, portfolio fetcher,
and api.py into one place.  The rest of the system imports BrokerAdapter
only and is broker-agnostic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from broker.interface import (
    AccountInfo, BrokerAdapter, BrokerOrder, BrokerOrderResult, BrokerPosition,
)

log = logging.getLogger(__name__)

_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_LIVE_BASE_URL  = "https://api.alpaca.markets"


class AlpacaBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by Alpaca's trading API (alpaca-py)."""

    def __init__(self, api_key: str, secret_key: str, base_url: str) -> None:
        from alpaca.trading.client import TradingClient
        self._api_key    = api_key
        self._secret_key = secret_key
        self._base_url   = base_url
        self._paper      = "paper" in base_url.lower()
        self._trading    = TradingClient(api_key, secret_key, paper=self._paper)

    @property
    def broker_name(self) -> str:
        return "alpaca"

    @property
    def is_paper(self) -> bool:
        return self._paper

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> AccountInfo:
        acct = self._trading.get_account()
        equity       = float(acct.equity or 0)
        last_equity  = float(acct.last_equity or equity or 1.0)
        cash         = float(acct.cash or 0)
        buying_power = float(acct.buying_power or cash)
        return AccountInfo(
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            last_equity=last_equity,
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_all_positions(self) -> list[BrokerPosition]:
        raw = self._trading.get_all_positions()
        result: list[BrokerPosition] = []
        for p in raw:
            sym  = str(p.symbol)
            # Alpaca crypto symbols end in USD (BTCUSD, ETHUSD, SOLUSD…)
            is_crypto = sym.endswith("USD") and len(sym) > 3 and not sym.startswith("USD")
            qty        = float(p.qty or 0)
            avg_price  = float(p.avg_entry_price or 0)
            cur_price  = float(p.current_price or 0)
            mv         = float(p.market_value or 0)
            upnl       = float(p.unrealized_pl or 0)
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
        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        alpaca_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=alpaca_side,
            time_in_force=TimeInForce.GTC,
            order_class="bracket",
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=take_profit_price),
        )
        order = self._trading.submit_order(order_req)
        exchange = "alpaca_paper" if self._paper else "alpaca_live"
        filled_price = float(getattr(order, "filled_avg_price", 0) or 0)
        return BrokerOrderResult(
            order_id=str(order.id),
            symbol=symbol,
            action=side,
            qty=float(qty),
            submitted_price=filled_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            raw=order,
        )

    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        alpaca_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        if qty > 0:
            order_req = MarketOrderRequest(
                symbol=symbol,
                qty=round(qty, 8),
                side=alpaca_side,
                time_in_force=TimeInForce.GTC,
            )
        else:
            order_req = MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=alpaca_side,
                time_in_force=TimeInForce.GTC,
            )
        order = self._trading.submit_order(order_req)
        exchange = "alpaca_paper" if self._paper else "alpaca_live"
        filled_qty   = float(getattr(order, "qty", qty) or qty)
        filled_price = float(getattr(order, "filled_avg_price", 0) or 0)
        return BrokerOrderResult(
            order_id=str(order.id),
            symbol=symbol,
            action=side,
            qty=filled_qty,
            submitted_price=filled_price,
            stop_price=0.0,
            take_profit_price=0.0,
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            raw=order,
        )

    def close_position(self, symbol: str) -> BrokerOrderResult:
        order = self._trading.close_position(symbol)
        exchange = "alpaca_paper" if self._paper else "alpaca_live"
        qty   = float(getattr(order, "qty", 0) or 0)
        price = float(getattr(order, "filled_avg_price", 0) or 0)
        return BrokerOrderResult(
            order_id=str(order.id),
            symbol=symbol,
            action="SELL",
            qty=qty,
            submitted_price=price,
            stop_price=0.0,
            take_profit_price=0.0,
            exchange=exchange,
            timestamp=datetime.now(timezone.utc),
            raw=order,
        )

    # ── Order history ─────────────────────────────────────────────────────────

    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        status_map = {
            "open":   QueryOrderStatus.OPEN,
            "all":    QueryOrderStatus.ALL,
            "closed": QueryOrderStatus.CLOSED,
        }
        qs = status_map.get(status, QueryOrderStatus.OPEN)
        raw = self._trading.get_orders(filter=GetOrdersRequest(status=qs, limit=limit))
        result: list[BrokerOrder] = []
        for o in raw:
            result.append(BrokerOrder(
                order_id=str(o.id),
                client_order_id=str(o.client_order_id or ""),
                symbol=o.symbol,
                side=o.side.value if o.side else "unknown",
                order_type=o.type.value if o.type else "unknown",
                qty=float(o.qty or 0),
                filled_qty=float(o.filled_qty or 0),
                status=o.status.value if o.status else "unknown",
                submitted_at=o.submitted_at,
                filled_at=o.filled_at,
                limit_price=float(o.limit_price) if o.limit_price else None,
                stop_price=float(o.stop_price) if o.stop_price else None,
                filled_avg_price=float(o.filled_avg_price) if o.filled_avg_price else None,
            ))
        return result

    # ── Portfolio history (Alpaca-native API) ─────────────────────────────────

    def get_portfolio_history(self, period: str, timeframe: str) -> list[dict]:
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        hist = self._trading.get_portfolio_history(
            GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
        )
        timestamps = hist.timestamp or []
        equities   = hist.equity   or []
        if not timestamps or not equities or len(timestamps) != len(equities):
            return []

        pts: list[dict] = []
        last_equity: float | None = None
        for ts, eq in zip(timestamps, equities):
            if eq is not None:
                last_equity = float(eq)
            if last_equity is None:
                continue
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            pts.append({"time": dt.isoformat(), "equity": last_equity, "pnl": 0.0})
        return pts

    # ── Crypto price ──────────────────────────────────────────────────────────

    def get_latest_crypto_price(self, symbol: str) -> float:
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoLatestQuoteRequest
            client = CryptoHistoricalDataClient()
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
            log.debug("Could not fetch latest crypto price for %s: %s", symbol, exc)
        return 0.0

    # ── Market data client ────────────────────────────────────────────────────

    def get_market_data_client(self, asset_class: str = "stock"):
        """Return the Alpaca market data client for this user's credentials."""
        if asset_class == "crypto":
            from data.market_data import AlpacaCryptoMarketData
            return AlpacaCryptoMarketData(self._api_key, self._secret_key)
        from data.market_data import AlpacaMarketData
        return AlpacaMarketData(self._api_key, self._secret_key)
