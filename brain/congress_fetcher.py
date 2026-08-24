"""STOCK Act congressional disclosure fetcher.

Primary source: Bargo.ai free REST API — no API key required.
  https://www.bargo.ai/free-apis/congress/v1/trades
  Covers House + Senate STOCK Act filings, deduplicated and enriched with
  per-trade price performance. Anonymous access, open CORS, 3-month rolling window.

Fallback: Quiver Quantitative (requires free API key — configure in Settings).
  https://api.quiverquant.com/beta/live/congresstrading

Legacy: HouseStockWatcher / SenateStockWatcher — URLs kept configurable but
  these sites are no longer reachable (DNS failure as of 2026-08).

Called every 6 hours by the orchestrator. Configure congress_refresh_hours in
Settings → Public Disclosure Tracker to change the interval.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from brain.copy_trading import upsert_congress_trades

log = logging.getLogger(__name__)

_BARGO_URL  = "https://www.bargo.ai/free-apis/congress/v1/trades"
_QUIVER_URL = "https://api.quiverquant.com/beta/live/congresstrading"


def _cfg():
    try:
        from brain.disclosure_settings import load
        return load()
    except Exception:
        from brain.disclosure_settings import DisclosureConfig
        return DisclosureConfig()


# ── Bargo source (primary, no key needed) ────────────────────────────────────

def _fetch_bargo(url: str, timeout: int) -> list[dict]:
    """Fetch from Bargo.ai free API. Returns 3-month rolling window."""
    trades: list[dict] = []
    page = 1
    limit = 500
    try:
        while True:
            r = httpx.get(
                url,
                params={"limit": limit, "page": page},
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "TradingAgentAI/1.0",
                    "Accept":     "application/json",
                },
            )
            if r.status_code == 429:
                log.warning("Bargo API rate-limited — will retry next cycle")
                break
            r.raise_for_status()
            data = r.json()
            batch = data.get("trades", [])
            trades.extend(batch)
            if len(batch) < limit:
                break
            page += 1
    except Exception as exc:
        log.warning("Bargo congress fetch error: %s", exc)
    log.info("Bargo fetch: %d trades across %d page(s)", len(trades), page)
    return trades


def _normalise_bargo(raw: dict) -> dict | None:
    member = raw.get("member") or ""
    if not member:
        return None
    symbol = (raw.get("ticker") or "").strip().upper()
    if symbol in ("", "--", "N/A", "NONE"):
        symbol = ""
    trade_type = (raw.get("type") or "").lower()
    if "purchase" in trade_type or "buy" in trade_type:
        trade_type = "purchase"
    elif "sale" in trade_type or "sell" in trade_type:
        trade_type = "sale"
    chamber = (raw.get("chamber") or "").title()  # "house" → "House"
    return {
        "member_name":      member.strip().title(),
        "party":            raw.get("party", ""),
        "chamber":          chamber,
        "state":            raw.get("state", ""),
        "symbol":           symbol,
        "company_name":     raw.get("asset", ""),
        "trade_type":       trade_type,
        "amount_range":     raw.get("amount_range", ""),
        "transaction_date": _parse_date(raw.get("transaction_date", "")),
        "disclosure_date":  _parse_date(raw.get("disclosure_date", "")),
        "comment":          _perf_comment(raw),
        "source":           "bargo",
    }


def _perf_comment(raw: dict) -> str:
    """Encode the Bargo per-trade performance fields into the comment column."""
    parts = []
    if raw.get("perf_pct") is not None:
        parts.append(f"Perf since trade: {raw['perf_pct']:+.1f}%")
    if raw.get("outcome"):
        parts.append(f"Outcome: {raw['outcome']}")
    if raw.get("est_price") and raw.get("recent_price"):
        parts.append(f"Est price: ${raw['est_price']:.2f} → ${raw['recent_price']:.2f}")
    return " | ".join(parts)


# ── Quiver Quantitative fallback ─────────────────────────────────────────────

def _fetch_quiver(api_key: str, timeout: int) -> list[dict]:
    try:
        r = httpx.get(
            _QUIVER_URL,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Authorization": f"Token {api_key}",
                "User-Agent":    "TradingAgentAI/1.0",
                "Accept":        "application/json",
            },
        )
        if r.status_code == 401:
            log.warning("Quiver: invalid API key — check Settings")
            return []
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as exc:
        log.warning("Quiver congress fetch error: %s", exc)
        return []


def _normalise_quiver(raw: dict) -> dict | None:
    member = raw.get("Representative") or raw.get("Senator") or raw.get("Name") or ""
    if not member:
        return None
    symbol = (raw.get("Ticker") or "").strip().upper()
    if symbol in ("", "--", "N/A", "NONE"):
        symbol = ""
    trade_type = (raw.get("Transaction") or "").lower()
    if "purchase" in trade_type or "buy" in trade_type:
        trade_type = "purchase"
    elif "sale" in trade_type or "sell" in trade_type:
        trade_type = "sale"
    return {
        "member_name":      member.strip().title(),
        "party":            raw.get("Party", ""),
        "chamber":          raw.get("Chamber", ""),
        "state":            raw.get("State", ""),
        "symbol":           symbol,
        "company_name":     raw.get("Asset") or raw.get("asset_description", ""),
        "trade_type":       trade_type,
        "amount_range":     str(raw.get("Range") or raw.get("Amount", "")),
        "transaction_date": _parse_date(raw.get("Date") or raw.get("TransactionDate", "")),
        "disclosure_date":  _parse_date(raw.get("ReportDate", "")),
        "comment":          raw.get("Comment", ""),
        "source":           "quiverquant",
    }


# ── Legacy feed fallback ─────────────────────────────────────────────────────

def _fetch_legacy(url: str, timeout: int, user_agent: str) -> list[dict]:
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": user_agent})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", data.get("trades", []))
    except Exception as exc:
        log.warning("Legacy congress feed failed (%s): %s", url, exc)
        return []


def _normalise_legacy(raw: dict, chamber: str) -> dict | None:
    key = "representative" if chamber == "House" else "senator"
    member = raw.get(key) or raw.get("name") or ""
    if not member:
        return None
    symbol = (raw.get("ticker") or "").strip().upper()
    if symbol in ("", "--", "N/A"):
        symbol = ""
    trade_type = (raw.get("type") or "").lower()
    if "purchase" in trade_type or "buy" in trade_type:
        trade_type = "purchase"
    elif "sale" in trade_type or "sell" in trade_type:
        trade_type = "sale"
    return {
        "member_name":      member.strip().title(),
        "party":            raw.get("party", ""),
        "chamber":          chamber,
        "state":            raw.get("state", ""),
        "symbol":           symbol,
        "company_name":     raw.get("asset_description", raw.get("company", "")),
        "trade_type":       trade_type,
        "amount_range":     raw.get("amount", raw.get("range", "")),
        "transaction_date": _parse_date(raw.get("transaction_date") or raw.get("traded", "")),
        "disclosure_date":  _parse_date(raw.get("disclosure_date") or raw.get("disclosed", "")),
        "comment":          raw.get("comment", ""),
        "source":           "housestockwatcher" if chamber == "House" else "senatestockwatcher",
    }


# ── Shared helper ────────────────────────────────────────────────────────────

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


# ── Main entry point ─────────────────────────────────────────────────────────

def refresh() -> int:
    """Fetch congressional trades from the best available source.
    Priority: Bargo (no key) → Quiver (key configured) → legacy feeds.
    Returns total new rows inserted.
    """
    cfg = _cfg()
    trades: list[dict] = []

    # 1. Try Bargo (primary — always available, no key)
    bargo_url = getattr(cfg, "bargo_feed_url", _BARGO_URL) or _BARGO_URL
    raw_bargo = _fetch_bargo(bargo_url, cfg.congress_request_timeout_secs)
    for raw in raw_bargo:
        t = _normalise_bargo(raw)
        if t:
            trades.append(t)

    if trades:
        inserted = upsert_congress_trades(trades)
        log.info("Congress refresh (Bargo): %d raw → %d new inserted", len(trades), inserted)
        return inserted

    # 2. Quiver fallback (if key configured)
    if cfg.quiver_api_key:
        log.info("Bargo returned 0 — trying Quiver Quantitative fallback")
        for raw in _fetch_quiver(cfg.quiver_api_key, cfg.congress_request_timeout_secs):
            t = _normalise_quiver(raw)
            if t:
                trades.append(t)

    # 3. Legacy feed fallback (typically unreachable)
    if not trades:
        log.warning("All primary sources returned 0 — trying legacy feeds (may be unreachable)")
        for raw in _fetch_legacy(cfg.house_feed_url, cfg.congress_request_timeout_secs, cfg.edgar_user_agent):
            t = _normalise_legacy(raw, "House")
            if t:
                trades.append(t)
        for raw in _fetch_legacy(cfg.senate_feed_url, cfg.congress_request_timeout_secs, cfg.edgar_user_agent):
            t = _normalise_legacy(raw, "Senate")
            if t:
                trades.append(t)

    if not trades:
        log.info("Congress fetch: 0 trades from all sources")
        return 0

    inserted = upsert_congress_trades(trades)
    log.info("Congress refresh: %d raw → %d new inserted", len(trades), inserted)
    return inserted
