"""Polygon.io market data adapter.

Drop-in alternative to AlpacaMarketData for equity bar data and quotes.
Uses the Polygon REST API v2/v3 via httpx (already in requirements).

Coverage:
  • Daily OHLCV bars (adjusted) — /v2/aggs
  • Latest NBBO quote + snapshot — /v2/snapshot

Free tier: 15-min delayed real-time data, unlimited historical.
Starter+ plans: real-time data.

Crypto is intentionally NOT implemented here — Alpaca covers crypto with
no geo-blocks and no additional key; this adapter focuses on equities.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from data.market_data import Bar, Quote, MarketSnapshot

log = logging.getLogger(__name__)

_BASE = "https://api.polygon.io"
_TIMEOUT = 15.0  # seconds


class PolygonMarketData:
    """Equity market data via Polygon.io REST API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Polygon API key is required")
        self._api_key = api_key

    def _get(self, path: str, **params) -> dict:
        """GET {_BASE}/{path} with error propagation."""
        url = f"{_BASE}{path}"
        params["apiKey"] = self._api_key
        try:
            resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Polygon request timed out: {path}") from exc
        if resp.status_code == 403:
            raise PermissionError("Polygon API key invalid or expired (HTTP 403)")
        if resp.status_code == 429:
            raise RuntimeError("Polygon rate limit exceeded — upgrade plan or add POLYGON_API_KEY")
        if not resp.is_success:
            raise RuntimeError(f"Polygon API error {resp.status_code} for {path}: {resp.text[:200]}")
        return resp.json()

    # ── Bars ──────────────────────────────────────────────────────────────────

    def get_bars(self, symbol: str, days: int = 60) -> list[Bar]:
        """Fetch adjusted daily OHLCV bars from Polygon."""
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days + 5)  # buffer for weekends / holidays
        from_str = start.strftime("%Y-%m-%d")
        to_str   = end.strftime("%Y-%m-%d")

        try:
            data = self._get(
                f"/v2/aggs/ticker/{symbol.upper()}/range/1/day/{from_str}/{to_str}",
                adjusted="true",
                sort="asc",
                limit=min(days + 20, 50000),
            )
        except Exception as exc:
            log.warning("Polygon bars failed for %s: %s", symbol, exc)
            raise

        results = data.get("results") or []
        if not results:
            status = data.get("status", "")
            log.warning("Polygon returned no bars for %s (status=%s)", symbol, status)
            return []

        bars: list[Bar] = []
        for r in results:
            ts = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc)
            bars.append(Bar(
                symbol=symbol,
                timestamp=ts,
                open=float(r.get("o", 0)),
                high=float(r.get("h", 0)),
                low=float(r.get("l", 0)),
                close=float(r.get("c", 0)),
                volume=float(r.get("v", 0)),
                asset_class="stock",
            ))
        return bars

    def get_intraday_bars(self, symbol: str, hours: int = 48) -> list[Bar]:
        """Fetch hourly OHLCV bars via Polygon (1-hour aggregates)."""
        end   = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours + 2)
        from_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str   = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            data = self._get(
                f"/v2/aggs/ticker/{symbol.upper()}/range/1/hour/{from_str}/{to_str}",
                adjusted="true",
                sort="asc",
                limit=hours + 10,
            )
        except Exception as exc:
            log.warning("Polygon intraday bars failed for %s: %s", symbol, exc)
            return []

        bars: list[Bar] = []
        for r in (data.get("results") or []):
            ts = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc)
            bars.append(Bar(
                symbol=symbol,
                timestamp=ts,
                open=float(r.get("o", 0)),
                high=float(r.get("h", 0)),
                low=float(r.get("l", 0)),
                close=float(r.get("c", 0)),
                volume=float(r.get("v", 0)),
                asset_class="stock",
            ))
        return bars

    # ── Latest quote ──────────────────────────────────────────────────────────

    def get_latest_quote(self, symbol: str) -> Quote | None:
        """Fetch last NBBO quote via the Polygon snapshot endpoint."""
        try:
            data = self._get(
                f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}",
            )
            ticker_data = data.get("ticker", {})
            last_quote  = ticker_data.get("lastQuote", {})
            last_trade  = ticker_data.get("lastTrade", {})

            # lastQuote: P = ask, p = bid  (Polygon uses lowercase for bid, uppercase for ask)
            ask = float(last_quote.get("P", 0) or 0)
            bid = float(last_quote.get("p", 0) or 0)

            # Fall back to last trade price if quote is empty
            if ask == 0 and bid == 0:
                price = float(last_trade.get("p", 0) or last_trade.get("P", 0) or 0)
                if price > 0:
                    bid = ask = price

            if ask == 0 and bid == 0:
                return None

            # Timestamp is in nanoseconds
            ts_ns = last_quote.get("t", 0) or last_trade.get("t", 0) or 0
            ts = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc) if ts_ns else datetime.now(timezone.utc)

            return Quote(
                symbol=symbol,
                timestamp=ts,
                bid=bid,
                ask=ask,
                mid=(bid + ask) / 2,
                asset_class="stock",
            )
        except Exception as exc:
            log.debug("Polygon snapshot failed for %s: %s", symbol, exc)
            return None

    # ── Snapshot ─────────────────────────────────────────────────────────────

    def snapshot(self, symbol: str, days: int = 60) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            asset_class="stock",
            bars=self.get_bars(symbol, days),
            latest_quote=self.get_latest_quote(symbol),
        )
