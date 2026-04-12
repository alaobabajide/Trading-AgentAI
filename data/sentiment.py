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
        "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
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
    def __init__(self, x_bearer_token: str = "", alpha_vantage_key: str = "") -> None:
        self._x_bearer = x_bearer_token
        self._av_key = alpha_vantage_key

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

    # ── Unified bundle ────────────────────────────────────────────────────────

    def bundle(self, symbol: str) -> SentimentBundle:
        news = (
            self.fetch_rss(symbol)
            + self.fetch_x(symbol)
            + self.fetch_earnings(symbol)
        )
        # Deduplicate by headline
        seen: set[str] = set()
        unique: list[NewsItem] = []
        for item in news:
            key = re.sub(r"\s+", " ", item.headline.lower().strip())[:80]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return SentimentBundle(symbol=symbol, items=unique)
