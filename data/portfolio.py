"""Layer 1 — Portfolio state.

Aggregates positions, equity, and P&L from any broker via BrokerAdapter
into a single PortfolioState object used by the Brain and Risk layers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from broker.interface import BrokerAdapter

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
    buying_power: float = 0.0             # broker buying power (may be 2× equity on margin)
    positions: list[Position] = field(default_factory=list)
    daily_pnl: float = 0.0               # equity - last_equity (total NAV change vs yesterday's close)
    daily_pnl_pct: float = 0.0
    open_pnl_today: float = 0.0          # sum of intraday unrealized P&L on open positions (vs yesterday's close)
    realized_pnl_today: float = 0.0      # daily_pnl minus open_pnl_today = P&L from positions closed today
    crypto_allocation_pct: float = 0.0   # % of equity in crypto

    @property
    def stock_allocation_pct(self) -> float:
        return 1.0 - self.crypto_allocation_pct - (self.cash / max(self.equity, 1))

    def position(self, symbol: str) -> Position | None:
        return next((p for p in self.positions if p.symbol == symbol), None)


class PortfolioFetcher:
    def __init__(self, broker: "BrokerAdapter") -> None:
        self._broker = broker

    def snapshot(self) -> PortfolioState:
        all_positions: list[Position] = []
        equity = cash = buying_power = daily_pnl = open_pnl_today = 0.0

        try:
            acct         = self._broker.get_account()
            equity       = acct.equity
            cash         = acct.cash
            buying_power = acct.buying_power
            last_equity  = acct.last_equity if acct.last_equity else equity or 1.0
            daily_pnl    = equity - last_equity

            for bp in self._broker.get_all_positions():
                cost_basis      = abs(bp.qty * bp.avg_entry_price)
                upnl_pct        = bp.unrealized_pnl / max(cost_basis, 1) * 100
                open_pnl_today += getattr(bp, "unrealized_intraday_pnl", 0.0)
                all_positions.append(Position(
                    symbol=bp.symbol,
                    asset_class=bp.asset_class,
                    qty=bp.qty,
                    avg_entry_price=bp.avg_entry_price,
                    current_price=bp.current_price,
                    market_value=bp.market_value,
                    unrealized_pnl=bp.unrealized_pnl,
                    unrealized_pnl_pct=upnl_pct,
                ))
        except Exception as exc:
            log.error("Portfolio fetch failed (%s): %s", self._broker.broker_name, exc)

        crypto_mv  = sum(p.market_value for p in all_positions if p.asset_class == "crypto")
        crypto_pct = crypto_mv / max(equity, 1)

        return PortfolioState(
            timestamp=datetime.now(timezone.utc),
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            positions=all_positions,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl / max(equity - daily_pnl, 1) * 100,
            open_pnl_today=open_pnl_today,
            realized_pnl_today=daily_pnl - open_pnl_today,
            crypto_allocation_pct=crypto_pct,
        )
