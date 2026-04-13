"""Layer 1 — Portfolio state.

Aggregates positions, equity, and P&L from Alpaca (stocks)
and Binance (crypto) into a single PortfolioState object used
by the Brain and Risk layers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

log = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    asset_class: Literal["stock", "crypto"]
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass
class PortfolioState:
    timestamp: datetime
    equity: float                          # total NAV
    cash: float
    buying_power: float = 0.0             # Alpaca buying power (may be 2× equity on margin)
    positions: list[Position] = field(default_factory=list)
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    crypto_allocation_pct: float = 0.0    # % of equity in crypto

    @property
    def stock_allocation_pct(self) -> float:
        return 1.0 - self.crypto_allocation_pct - (self.cash / max(self.equity, 1))

    def position(self, symbol: str) -> Position | None:
        return next((p for p in self.positions if p.symbol == symbol), None)


class PortfolioFetcher:
    def __init__(
        self,
        alpaca_api_key: str,
        alpaca_secret_key: str,
        alpaca_base_url: str,
        binance_api_key: str,
        binance_secret_key: str,
        binance_testnet: bool = True,
    ) -> None:
        self._alpaca_key = alpaca_api_key
        self._alpaca_secret = alpaca_secret_key
        self._alpaca_url = alpaca_base_url
        self._binance_key = binance_api_key
        self._binance_secret = binance_secret_key
        self._binance_testnet = binance_testnet

    # ── Alpaca ────────────────────────────────────────────────────────────────

    def _alpaca_positions(self) -> tuple[list[Position], float, float, float, float]:
        """Returns (positions, equity, cash, buying_power, daily_pnl)."""
        from alpaca.trading.client import TradingClient

        # Derive paper mode from the configured base URL so both paper and
        # live credentials work without code changes.
        is_paper = "paper" in self._alpaca_url.lower()
        client = TradingClient(self._alpaca_key, self._alpaca_secret, paper=is_paper)
        acct = client.get_account()
        equity = float(acct.equity)
        cash = float(acct.cash)
        buying_power = float(acct.buying_power) if acct.buying_power else cash
        daily_pnl = float(acct.equity) - float(acct.last_equity)

        raw_positions = client.get_all_positions()
        positions: list[Position] = []
        for p in raw_positions:
            qty = float(p.qty)
            avg_price = float(p.avg_entry_price)
            current = float(p.current_price)
            mv = float(p.market_value)
            upnl = float(p.unrealized_pl)
            positions.append(Position(
                symbol=p.symbol,
                asset_class="stock",
                qty=qty,
                avg_entry_price=avg_price,
                current_price=current,
                market_value=mv,
                unrealized_pnl=upnl,
                unrealized_pnl_pct=upnl / max(abs(qty * avg_price), 1) * 100,
            ))
        return positions, equity, cash, buying_power, daily_pnl

    # ── Binance ───────────────────────────────────────────────────────────────

    def _binance_positions(self) -> list[Position]:
        from binance.client import Client

        client = Client(self._binance_key, self._binance_secret, testnet=self._binance_testnet)
        balances = client.get_account()["balances"]
        prices = {t["symbol"]: float(t["price"]) for t in client.get_all_tickers()}

        positions: list[Position] = []
        for bal in balances:
            free = float(bal["free"])
            locked = float(bal["locked"])
            total = free + locked
            if total < 1e-8:
                continue
            asset = bal["asset"]
            if asset == "USDT":
                continue
            pair = f"{asset}USDT"
            price = prices.get(pair, 0.0)
            if price == 0:
                continue
            mv = total * price
            positions.append(Position(
                symbol=pair,
                asset_class="crypto",
                qty=total,
                avg_entry_price=price,   # Binance spot doesn't expose avg cost
                current_price=price,
                market_value=mv,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
            ))
        return positions

    # ── Unified snapshot ──────────────────────────────────────────────────────

    def snapshot(self) -> PortfolioState:
        stock_positions, equity, cash, buying_power, daily_pnl = [], 0.0, 0.0, 0.0, 0.0
        crypto_positions: list[Position] = []

        if self._alpaca_key:
            try:
                stock_positions, equity, cash, buying_power, daily_pnl = self._alpaca_positions()
            except Exception as exc:
                log.error("Alpaca portfolio fetch failed: %s", exc)

        if self._binance_key:
            try:
                crypto_positions = self._binance_positions()
            except Exception as exc:
                log.error("Binance portfolio fetch failed: %s", exc)

        all_positions = stock_positions + crypto_positions
        crypto_mv = sum(p.market_value for p in crypto_positions)
        crypto_pct = crypto_mv / max(equity, 1)

        return PortfolioState(
            timestamp=datetime.now(timezone.utc),
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            positions=all_positions,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl / max(equity - daily_pnl, 1) * 100,
            crypto_allocation_pct=crypto_pct,
        )
