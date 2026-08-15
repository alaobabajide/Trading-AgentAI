"""Layer 1 — News & sentiment ingestion.

Sources:
  • RSS feeds (Reuters, Bloomberg, Yahoo Finance)
  • X / Twitter search (requires Bearer token)
  • Earnings calendar (Alpha Vantage free tier)
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

log = logging.getLogger(__name__)

RSS_FEEDS: dict[str, list[str]] = {
    "global": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
    ],
}

ALPHA_VANTAGE_EARNINGS = (
    "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR"
    "&horizon=3month&apikey={api_key}"
)


@dataclass
class NewsItem:
    source: str
    headline: str
    summary: str
    url: str
    published: datetime
    symbols: list[str]
    sentiment_hint: str = ""   # populated by Brain layer


@dataclass
class SentimentBundle:
    symbol: str
    items: list[NewsItem]
    raw_score: float = 0.0     # -1 bearish … +1 bullish (set by Brain)


class SentimentFetcher:
    def __init__(
        self,
        x_bearer_token: str = "",
        alpha_vantage_key: str = "",
        finnhub_api_key: str = "",
    ) -> None:
        self._x_bearer = x_bearer_token
        self._av_key = alpha_vantage_key
        self._finnhub_key = finnhub_api_key

    # ── RSS ───────────────────────────────────────────────────────────────────

    def fetch_rss(self, symbol: str, max_items: int = 20) -> list[NewsItem]:
        items: list[NewsItem] = []
        url = RSS_FEEDS["global"][0].format(symbol=symbol)
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_items]:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            items.append(NewsItem(
                source="Yahoo Finance RSS",
                headline=entry.get("title", ""),
                summary=entry.get("summary", ""),
                url=entry.get("link", ""),
                published=published,
                symbols=[symbol],
            ))
        log.debug("RSS: fetched %d items for %s", len(items), symbol)
        return items

    # ── X / Twitter ───────────────────────────────────────────────────────────

    def fetch_x(self, symbol: str, max_results: int = 50) -> list[NewsItem]:
        """Fetches recent tweets mentioning $SYMBOL via Twitter v2 API."""
        if not self._x_bearer:
            log.warning("X bearer token not set — skipping X fetch")
            return []

        query = f"${symbol} lang:en -is:retweet"
        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": query,
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,text",
        }
        headers = {"Authorization": f"Bearer {self._x_bearer}"}
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("X fetch failed: %s", exc)
            return []

        items: list[NewsItem] = []
        for tweet in data.get("data", []):
            created = datetime.fromisoformat(tweet["created_at"].replace("Z", "+00:00"))
            items.append(NewsItem(
                source="X",
                headline=tweet["text"][:120],
                summary=tweet["text"],
                url=f"https://twitter.com/i/web/status/{tweet['id']}",
                published=created,
                symbols=[symbol],
            ))
        return items

    # ── Earnings calendar ─────────────────────────────────────────────────────

    def fetch_earnings(self, symbol: str) -> list[NewsItem]:
        if not self._av_key:
            return []
        url = ALPHA_VANTAGE_EARNINGS.format(api_key=self._av_key)
        try:
            resp = httpx.get(url, timeout=10)
            text = resp.text
        except Exception as exc:
            log.error("Earnings fetch failed: %s", exc)
            return []

        items: list[NewsItem] = []
        for line in text.splitlines()[1:]:   # skip CSV header
            parts = line.split(",")
            if len(parts) < 3:
                continue
            if parts[0].upper() == symbol.upper():
                items.append(NewsItem(
                    source="Alpha Vantage Earnings",
                    headline=f"{symbol} earnings scheduled {parts[2]}",
                    summary=line,
                    url="",
                    published=datetime.now(timezone.utc),
                    symbols=[symbol],
                ))
        return items

    # ── Finnhub news (free tier, no API key required for basic endpoint) ─────

    def fetch_finnhub(self, symbol: str, max_items: int = 10) -> list[NewsItem]:
        """Fetch recent company news from Finnhub free API.

        Finnhub requires an API key (FINNHUB_API_KEY env var) for most endpoints.
        If the key is missing, returns an empty list silently so the caller's
        fallback logic can handle it without crashing.
        """
        if not self._finnhub_key:
            return []
        from datetime import timedelta
        to_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        url = "https://finnhub.io/api/v1/company-news"
        try:
            resp = httpx.get(
                url,
                params={"symbol": symbol, "from": from_date, "to": to_date,
                        "token": self._finnhub_key},
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json()
        except Exception as exc:
            log.debug("Finnhub fetch failed for %s: %s", symbol, exc)
            return []

        items: list[NewsItem] = []
        for a in articles[:max_items]:
            ts = a.get("datetime", 0)
            try:
                published = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                published = datetime.now(timezone.utc)
            items.append(NewsItem(
                source="Finnhub",
                headline=a.get("headline", "")[:200],
                summary=a.get("summary", "")[:500],
                url=a.get("url", ""),
                published=published,
                symbols=[symbol],
            ))
        log.debug("Finnhub: fetched %d items for %s", len(items), symbol)
        return items

    # ── Unified bundle ────────────────────────────────────────────────────────

    def bundle(self, symbol: str) -> SentimentBundle:
        news = (
            self.fetch_rss(symbol)
            + self.fetch_x(symbol)
            + self.fetch_earnings(symbol)
        )
        # Fallback to Finnhub when primary sources return fewer than 5 headlines
        if len(news) < 5:
            finnhub_items = self.fetch_finnhub(symbol)
            if finnhub_items:
                log.info(
                    "Sentiment fallback: %s — primary=%d headlines, adding %d from Finnhub",
                    symbol, len(news), len(finnhub_items),
                )
                news += finnhub_items
        # Deduplicate by headline
        seen: set[str] = set()
        unique: list[NewsItem] = []
        for item in news:
            key = re.sub(r"\s+", " ", item.headline.lower().strip())[:80]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return SentimentBundle(symbol=symbol, items=unique)
