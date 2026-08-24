"""STOCK Act congressional disclosure fetcher.

Polls the free HouseStockWatcher and SenateStockWatcher JSON APIs,
normalises trade records, and upserts them into the disclosure DB via
brain.copy_trading.upsert_congress_trades().

Tracked members (≥80 % confidence) are filtered automatically;
all other members are stored too so the feed is useful as a
general-purpose disclosure tracker.

Called every 6 hours by the orchestrator (non-blocking, runs in a
background thread). Rate-limit: at most 2 requests per run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from brain.copy_trading import upsert_congress_trades

log = logging.getLogger(__name__)

def _cfg():
    try:
        from brain.disclosure_settings import load
        return load()
    except Exception:
        from brain.disclosure_settings import DisclosureConfig
        return DisclosureConfig()


def _fetch_json(url: str) -> list[dict]:
    cfg = _cfg()
    try:
        r = httpx.get(url, timeout=cfg.congress_request_timeout_secs, follow_redirects=True,
                      headers={"User-Agent": cfg.edgar_user_agent})
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return data.get("data", data.get("trades", []))
    except Exception as exc:
        log.warning("Congress fetch failed (%s): %s", url, exc)
        return []


def _normalise_house(raw: dict) -> dict | None:
    """Map HouseStockWatcher record → internal schema."""
    member = raw.get("representative") or raw.get("name") or ""
    if not member:
        return None
    symbol = raw.get("ticker", "").strip().upper()
    if symbol in ("", "--", "N/A"):
        symbol = ""
    trade_type = raw.get("type", "").lower()
    # Normalise to purchase / sale
    if "purchase" in trade_type or "buy" in trade_type:
        trade_type = "purchase"
    elif "sale" in trade_type or "sell" in trade_type:
        trade_type = "sale"
    return {
        "member_name":       member.strip().title(),
        "party":             raw.get("party", ""),
        "chamber":           "House",
        "state":             raw.get("state", ""),
        "symbol":            symbol,
        "company_name":      raw.get("asset_description", raw.get("company", "")),
        "trade_type":        trade_type,
        "amount_range":      raw.get("amount", raw.get("range", "")),
        "transaction_date":  _parse_date(raw.get("transaction_date") or raw.get("traded", "")),
        "disclosure_date":   _parse_date(raw.get("disclosure_date") or raw.get("disclosed", "")),
        "comment":           raw.get("comment", raw.get("description", "")),
        "source":            "housestockwatcher",
    }


def _normalise_senate(raw: dict) -> dict | None:
    """Map SenateStockWatcher record → internal schema."""
    member = raw.get("senator") or raw.get("name") or ""
    if not member:
        return None
    symbol = raw.get("ticker", "").strip().upper()
    if symbol in ("", "--", "N/A"):
        symbol = ""
    trade_type = raw.get("type", "").lower()
    if "purchase" in trade_type or "buy" in trade_type:
        trade_type = "purchase"
    elif "sale" in trade_type or "sell" in trade_type:
        trade_type = "sale"
    return {
        "member_name":       member.strip().title(),
        "party":             raw.get("party", ""),
        "chamber":           "Senate",
        "state":             raw.get("state", ""),
        "symbol":            symbol,
        "company_name":      raw.get("asset_description", raw.get("company", "")),
        "trade_type":        trade_type,
        "amount_range":      raw.get("amount", raw.get("range", "")),
        "transaction_date":  _parse_date(raw.get("transaction_date") or raw.get("traded", "")),
        "disclosure_date":   _parse_date(raw.get("disclosure_date") or raw.get("disclosed", "")),
        "comment":           raw.get("comment", ""),
        "source":            "senatestockwatcher",
    }


def _parse_date(raw: str) -> str:
    """Best-effort ISO-date parse from various source formats."""
    if not raw:
        return ""
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%B %d, %Y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw[:10]  # fall back to raw prefix


def refresh() -> int:
    """Fetch both chambers and upsert all trades. Returns total new rows inserted."""
    cfg = _cfg()
    house_raw  = _fetch_json(cfg.house_feed_url)
    senate_raw = _fetch_json(cfg.senate_feed_url)

    trades: list[dict] = []
    for raw in house_raw:
        t = _normalise_house(raw)
        if t:
            trades.append(t)
    for raw in senate_raw:
        t = _normalise_senate(raw)
        if t:
            trades.append(t)

    if not trades:
        log.info("Congress fetch: no records returned from either source")
        return 0

    inserted = upsert_congress_trades(trades)
    log.info("Congress fetch complete: %d raw records → %d new inserted", len(trades), inserted)
    return inserted
