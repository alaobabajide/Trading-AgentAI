"""Layer 1 — Market data.

Pulls OHLCV bars and live quotes from Alpaca (equities) and
Binance (crypto).  Returns plain dataclasses so the Brain layer
has no exchange dependency.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

import pandas as pd

log = logging.getLogger(__name__)


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    asset_class: Literal["stock", "crypto"]


@dataclass
class Quote:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    mid: float
    asset_class: Literal["stock", "crypto"]


@dataclass
class MarketSnapshot:
    symbol: str
    asset_class: Literal["stock", "crypto"]
    bars: list[Bar]           # last N daily bars
    latest_quote: Quote | None = None
    extra: dict = field(default_factory=dict)


# ── Alpaca equity data ─────────────────────────────────────────────────────────

class AlpacaMarketData:
    """Wraps alpaca-py's StockHistoricalDataClient."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        from alpaca.data import StockHistoricalDataClient

        self._client = StockHistoricalDataClient(api_key, secret_key)

    def get_bars(self, symbol: str, days: int = 60) -> list[Bar]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        bars: list[Bar] = []

        # Try SIP feed first (paper accounts get SIP access), fall back to IEX
        for feed in (DataFeed.SIP, DataFeed.IEX):
            try:
                req  = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=start,
                    end=end,
                    feed=feed,
                )
                resp = self._client.get_stock_bars(req)
                df: pd.DataFrame = resp.df
                if not df.empty:
                    break   # got data — stop trying
                log.debug("Empty bars from %s feed for %s, trying next feed", feed, symbol)
            except Exception as exc:
                log.debug("Feed %s failed for %s (%s), trying next", feed, symbol, exc)
                df = pd.DataFrame()

        if df.empty:
            log.warning("No bar data returned for %s after trying all feeds", symbol)
            return bars

        # Multi-index: (symbol, timestamp) → flatten
        if isinstance(df.index, pd.MultiIndex):
            df = df.loc[symbol] if symbol in df.index.get_level_values(0) else df.droplevel(0)

        for ts, row in df.iterrows():
            bars.append(Bar(
                symbol=symbol,
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                asset_class="stock",
            ))
        return bars

    def get_latest_quote(self, symbol: str) -> Quote | None:
        from alpaca.data.requests import StockLatestQuoteRequest
        from alpaca.data.enums import DataFeed

        req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
        resp = self._client.get_stock_latest_quote(req)
        q = resp.get(symbol)
        if q is None:
            return None
        bid = float(q.bid_price or 0)
        ask = float(q.ask_price or 0)
        return Quote(
            symbol=symbol,
            timestamp=q.timestamp,
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2,
            asset_class="stock",
        )

    def snapshot(self, symbol: str, days: int = 60) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            asset_class="stock",
            bars=self.get_bars(symbol, days),
            latest_quote=self.get_latest_quote(symbol),
        )


# ── Binance crypto data ────────────────────────────────────────────────────────

class BinanceMarketData:
    """Wraps python-binance's AsyncClient for crypto data."""

    def __init__(self, api_key: str, secret_key: str, testnet: bool = True) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._testnet = testnet

    def _client(self):
        from binance.client import Client
        client = Client(self._api_key, self._secret_key, testnet=self._testnet)
        return client

    def get_bars(self, symbol: str, days: int = 60) -> list[Bar]:
        """symbol format: BTCUSDT"""
        from binance.client import Client

        client = self._client()
        klines = client.get_historical_klines(
            symbol,
            Client.KLINE_INTERVAL_1DAY,
            f"{days} day ago UTC",
        )
        bars: list[Bar] = []
        for k in klines:
            ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            bars.append(Bar(
                symbol=symbol,
                timestamp=ts,
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                asset_class="crypto",
            ))
        return bars

    def get_latest_quote(self, symbol: str) -> Quote | None:
        client = self._client()
        ticker = client.get_symbol_ticker(symbol=symbol)
        price = float(ticker["price"])
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bid=price,
            ask=price,
            mid=price,
            asset_class="crypto",
        )

    def snapshot(self, symbol: str, days: int = 60) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            asset_class="crypto",
            bars=self.get_bars(symbol, days),
            latest_quote=self.get_latest_quote(symbol),
        )
