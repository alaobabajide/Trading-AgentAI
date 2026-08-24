"""STOCK Act congressional disclosure fetcher.

Primary source: Quiver Quantitative API (free tier — set quiver_api_key in Settings).
  https://api.quiverquant.com/beta/live/congresstrading

Fallback (legacy): HouseStockWatcher / SenateStockWatcher — these sites are
currently unreachable. The URLs remain configurable in Settings in case they
return or are replaced with a compatible feed.

All records are normalised into a common schema and upserted via
brain.copy_trading.upsert_congress_trades().

Called every 6 hours by the orchestrator. Set congress_refresh_hours in
Settings → Public Disclosure Tracker to change the interval.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from brain.copy_trading import upsert_congress_trades

log = logging.getLogger(__name__)

_QUIVER_BASE = "https://api.quiverquant.com/beta"


def _cfg():
    try:
        from brain.disclosure_settings import load
        return load()
    except Exception:
        from brain.disclosure_settings import DisclosureConfig
        return DisclosureConfig()


# ── Quiver Quantitative source ────────────────────────────────────────────────

def _fetch_quiver(api_key: str, timeout: int) -> list[dict]:
    """Fetch live congressional trades from Quiver Quantitative free tier."""
    try:
        r = httpx.get(
            f"{_QUIVER_BASE}/live/congresstrading",
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Authorization": f"Token {api_key}",
                "User-Agent":    "TradingAgentAI/1.0",
                "Accept":        "application/json",
            },
        )
        if r.status_code == 401:
            log.warning("Quiver Quantitative: invalid or missing API key — configure in Settings")
            return []
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as exc:
        log.warning("Quiver congress fetch error: %s", exc)
        return []


def _normalise_quiver(raw: dict) -> dict | None:
    """Map Quiver Quantitative record → internal schema."""
    member = raw.get("Representative") or raw.get("Senator") or raw.get("Name") or ""
    if not member:
        return None
    symbol = (raw.get("Ticker") or raw.get("ticker") or "").strip().upper()
    if symbol in ("", "--", "N/A", "NONE"):
        symbol = ""

    trade_type = (raw.get("Transaction") or raw.get("type") or "").lower()
    if "purchase" in trade_type or "buy" in trade_type:
        trade_type = "purchase"
    elif "sale" in trade_type or "sell" in trade_type:
        trade_type = "sale"

    chamber = raw.get("Chamber") or ("Senate" if raw.get("Senator") else "House")
    amount = raw.get("Range") or raw.get("Amount") or raw.get("amount", "")

    return {
        "member_name":      member.strip().title(),
        "party":            raw.get("Party", ""),
        "chamber":          chamber,
        "state":            raw.get("State", ""),
        "symbol":           symbol,
        "company_name":     raw.get("Asset") or raw.get("asset_description") or raw.get("Company", ""),
        "trade_type":       trade_type,
        "amount_range":     str(amount),
        "transaction_date": _parse_date(raw.get("Date") or raw.get("TransactionDate") or raw.get("transaction_date", "")),
        "disclosure_date":  _parse_date(raw.get("ReportDate") or raw.get("disclosure_date", "")),
        "comment":          raw.get("Comment") or raw.get("description") or "",
        "source":           "quiverquant",
    }


# ── Legacy fallback source ────────────────────────────────────────────────────

def _fetch_legacy(url: str, timeout: int, user_agent: str) -> list[dict]:
    """Fetch from a HouseStockWatcher-compatible JSON endpoint."""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": user_agent})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", data.get("trades", []))
    except Exception as exc:
        log.warning("Legacy congress feed failed (%s): %s", url, exc)
        return []


def _normalise_legacy_house(raw: dict) -> dict | None:
    member = raw.get("representative") or raw.get("name") or ""
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
        "member_name":      (raw.get("representative") or raw.get("name") or "").strip().title(),
        "party":            raw.get("party", ""),
        "chamber":          "House",
        "state":            raw.get("state", ""),
        "symbol":           symbol,
        "company_name":     raw.get("asset_description", raw.get("company", "")),
        "trade_type":       trade_type,
        "amount_range":     raw.get("amount", raw.get("range", "")),
        "transaction_date": _parse_date(raw.get("transaction_date") or raw.get("traded", "")),
        "disclosure_date":  _parse_date(raw.get("disclosure_date") or raw.get("disclosed", "")),
        "comment":          raw.get("comment", raw.get("description", "")),
        "source":           "housestockwatcher",
    }


def _normalise_legacy_senate(raw: dict) -> dict | None:
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
        "member_name":      member.strip().title(),
        "party":            raw.get("party", ""),
        "chamber":          "Senate",
        "state":            raw.get("state", ""),
        "symbol":           symbol,
        "company_name":     raw.get("asset_description", raw.get("company", "")),
        "trade_type":       trade_type,
        "amount_range":     raw.get("amount", raw.get("range", "")),
        "transaction_date": _parse_date(raw.get("transaction_date") or raw.get("traded", "")),
        "disclosure_date":  _parse_date(raw.get("disclosure_date") or raw.get("disclosed", "")),
        "comment":          raw.get("comment", ""),
        "source":           "senatestockwatcher",
    }


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%B %d, %Y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw[:10]


# ── Main entry point ──────────────────────────────────────────────────────────

def refresh() -> int:
    """Fetch congressional trades from the best available source and upsert.
    Returns total new rows inserted.
    """
    cfg = _cfg()
    trades: list[dict] = []

    if cfg.quiver_api_key:
        raw_records = _fetch_quiver(cfg.quiver_api_key, cfg.congress_request_timeout_secs)
        for raw in raw_records:
            t = _normalise_quiver(raw)
            if t:
                trades.append(t)
        log.info("Quiver congress fetch: %d raw records", len(raw_records))
    else:
        log.warning(
            "No Quiver Quantitative API key configured. "
            "Congressional data unavailable. Add your free key in "
            "Settings → Public Disclosure Tracker → Quiver Quantitative API Key. "
            "Register free at https://quiverquant.com"
        )
        # Attempt legacy fallback (these sites are typically unreachable)
        house_raw = _fetch_legacy(cfg.house_feed_url, cfg.congress_request_timeout_secs, cfg.edgar_user_agent)
        senate_raw = _fetch_legacy(cfg.senate_feed_url, cfg.congress_request_timeout_secs, cfg.edgar_user_agent)
        for raw in house_raw:
            t = _normalise_legacy_house(raw)
            if t:
                trades.append(t)
        for raw in senate_raw:
            t = _normalise_legacy_senate(raw)
            if t:
                trades.append(t)

    if not trades:
        log.info("Congress fetch: 0 trades returned")
        return 0

    inserted = upsert_congress_trades(trades)
    log.info("Congress fetch complete: %d raw → %d new inserted", len(trades), inserted)
    return inserted
