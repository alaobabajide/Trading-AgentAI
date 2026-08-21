"""Broker abstraction layer — abstract base classes and shared data types.

All broker-specific code lives in broker/adapters/*.
Execution engines, PortfolioFetcher, and the API layer work against these
interfaces only — adding a new broker requires no changes outside adapters/.

Data flow:
  brain/api.py
    └── _resolve_broker(user_id, cfg) → BrokerAdapter
            ├── execution/stock/engine.py  (StockExecutionEngine)
            ├── execution/crypto/engine.py (CryptoExecutionEngine)
            └── data/portfolio.py          (PortfolioFetcher)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


# ── Shared data types ─────────────────────────────────────────────────────────

@dataclass
class AccountInfo:
    equity: float
    cash: float
    buying_power: float
    last_equity: float


@dataclass
class BrokerPosition:
    symbol: str
    asset_class: Literal["stock", "crypto"]
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float


@dataclass
class BrokerOrderResult:
    order_id: str
    symbol: str
    action: Literal["BUY", "SELL"]
    qty: float
    submitted_price: float
    stop_price: float
    take_profit_price: float
    exchange: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Any = None


@dataclass
class BrokerOrder:
    order_id: str
    symbol: str
    side: str
    order_type: str
    qty: float
    filled_qty: float
    status: str
    submitted_at: datetime | None
    filled_at: datetime | None
    limit_price: float | None
    stop_price: float | None
    filled_avg_price: float | None
    client_order_id: str = ""


# ── Broker interface ──────────────────────────────────────────────────────────

class BrokerAdapter(ABC):
    """Abstract interface for all broker integrations.

    Implement all @abstractmethod methods to add a new broker.
    Optional methods (get_portfolio_history, get_latest_crypto_price,
    get_market_data_client) have safe defaults that callers handle gracefully.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Short identifier, e.g. 'alpaca', 'tastytrade', 'schwab'."""

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        """True if operating in paper/sandbox mode."""

    @abstractmethod
    def get_account(self) -> AccountInfo:
        """Return current account equity, cash, buying_power, last_equity."""

    @abstractmethod
    def get_all_positions(self) -> list[BrokerPosition]:
        """Return all open positions."""

    @abstractmethod
    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        take_profit_price: float,
    ) -> BrokerOrderResult:
        """Submit a bracket order (entry + stop-loss + take-profit).

        Raises on failure — callers catch and convert to HTTPException.
        """

    @abstractmethod
    def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> BrokerOrderResult:
        """Submit a plain market order. Pass qty XOR notional."""

    @abstractmethod
    def close_position(self, symbol: str) -> BrokerOrderResult:
        """Close the full open position for symbol at market."""

    @abstractmethod
    def get_orders(self, status: str = "open", limit: int = 50) -> list[BrokerOrder]:
        """Return order history. status: 'open' | 'all' | 'closed'."""

    def get_portfolio_history(self, period: str, timeframe: str) -> list[dict]:
        """Return equity curve as [{time, equity, pnl}].

        Default: empty list. Override for brokers that expose portfolio history.
        """
        return []

    def get_latest_crypto_price(self, symbol: str) -> float:
        """Return current mid-price for a crypto symbol (e.g. BTCUSD).

        Default: 0.0. Override for brokers that support crypto.
        """
        return 0.0

    def get_market_data_client(self, asset_class: str = "stock"):
        """Return a market data client (same interface as AlpacaMarketData).

        Default: None — callers fall back to the system-level shared client.
        Override to return a broker-specific or third-party data client.
        """
        return None
