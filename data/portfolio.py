"""Layer 1 — Portfolio state.

Aggregates positions, equity, and P&L from Alpaca (stocks and crypto)
into a single PortfolioState object used by the Brain and Risk layers.
Crypto positions are detected by symbol suffix (BTCUSD, ETHUSD, etc.).
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
    ) -> None:
        self._alpaca_key = alpaca_api_key
        self._alpaca_secret = alpaca_secret_key
        self._alpaca_url = alpaca_base_url

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
            sym = str(p.symbol)
            # Alpaca crypto symbols end in USD (BTCUSD, ETHUSD, SOLUSD…)
            is_crypto = sym.endswith("USD") and len(sym) > 3 and not sym.startswith("USD")
            positions.append(Position(
                symbol=sym,
                asset_class="crypto" if is_crypto else "stock",
                qty=qty,
                avg_entry_price=avg_price,
                current_price=current,
                market_value=mv,
                unrealized_pnl=upnl,
                unrealized_pnl_pct=upnl / max(abs(qty * avg_price), 1) * 100,
            ))
        return positions, equity, cash, buying_power, daily_pnl

    # ── Unified snapshot ──────────────────────────────────────────────────────

    def snapshot(self) -> PortfolioState:
        all_positions, equity, cash, buying_power, daily_pnl = [], 0.0, 0.0, 0.0, 0.0

        if self._alpaca_key:
            try:
                all_positions, equity, cash, buying_power, daily_pnl = self._alpaca_positions()
            except Exception as exc:
                log.error("Alpaca portfolio fetch failed: %s", exc)

        # Crypto positions now live on Alpaca (asset_class="crypto" detected by symbol suffix).
        # Binance fetch is skipped — Railway's US IP blocks Binance regardless.
        crypto_mv = sum(p.market_value for p in all_positions if p.asset_class == "crypto")
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


