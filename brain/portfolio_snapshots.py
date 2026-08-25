"""Portfolio Snapshots — Supabase writer for daily NAV and benchmark tracking.

Called once daily (at or after market close) by the orchestrator to capture the
portfolio equity curve. Also fetches SPY and BTC closes for benchmark comparison.

Non-fatal: all functions catch and log exceptions.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _get_sb():
    try:
        from config import get_settings
        cfg = get_settings()
        if cfg.supabase_url and cfg.supabase_service_role_key:
            from supabase import create_client
            return create_client(cfg.supabase_url, cfg.supabase_service_role_key)
    except Exception as exc:
        log.warning("portfolio_snapshots: Supabase init failed: %s", exc)
    return None


def _fetch_benchmark_price(symbol: str) -> float | None:
    """Fetch current price via yfinance (free, no key needed)."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.debug("Benchmark price fetch failed for %s: %s", symbol, exc)
    return None


def record_daily_snapshot(
    nav:      float,
    cash:     float,
    invested: float,
    daily_pnl: float,
    positions_count: int,
    *,
    peak_nav: float = 0.0,
    initial_nav: float = 100_000.0,
    snapshot_date: date | None = None,
) -> bool:
    """Write a daily portfolio snapshot to Supabase.

    Returns True on success, False on failure.
    """
    sb = _get_sb()
    if sb is None:
        return False
    try:
        today = snapshot_date or date.today()
        prior = _get_prior_nav()

        daily_return = (nav - prior) / prior * 100 if prior and prior > 0 else 0.0
        cumulative   = (nav - initial_nav) / initial_nav * 100 if initial_nav > 0 else 0.0
        drawdown     = (nav - peak_nav) / peak_nav * 100 if peak_nav > 0 else 0.0

        spy_close = _fetch_benchmark_price("SPY")
        btc_close = _fetch_benchmark_price("BTC-USD")

        row: dict[str, Any] = {
            "snapshot_date":     today.isoformat(),
            "source":            "paper_live",
            "nav":               nav,
            "cash":              cash,
            "invested":          invested,
            "daily_pnl":         daily_pnl,
            "daily_return":      round(daily_return, 4),
            "cumulative_return": round(cumulative, 4),
            "drawdown":          round(drawdown, 4),
            "positions_count":   positions_count,
        }
        if spy_close:
            row["spy_close"] = spy_close
        if btc_close:
            row["btc_close"] = btc_close

        # Upsert (same date + source → replace)
        sb.table("portfolio_snapshots").upsert(row, on_conflict="snapshot_date,source,backtest_id").execute()
        log.info("portfolio_snapshots: recorded NAV=%.2f date=%s spy=%.2f btc=%.2f",
                 nav, today, spy_close or 0, btc_close or 0)
        return True
    except Exception as exc:
        log.warning("portfolio_snapshots: write failed: %s", exc)
        return False


def _get_prior_nav() -> float | None:
    """Fetch the most recent previously recorded live NAV (for daily return calc)."""
    sb = _get_sb()
    if sb is None:
        return None
    try:
        resp = (
            sb.table("portfolio_snapshots")
            .select("nav")
            .eq("source", "paper_live")
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        data = resp.data
        if data:
            return float(data[0]["nav"])
    except Exception:
        pass
    return None


def get_equity_curve(source: str = "paper_live", backtest_id: str | None = None,
                     days: int | None = None) -> list[dict]:
    """Return portfolio snapshots for the equity curve chart."""
    sb = _get_sb()
    if sb is None:
        return []
    try:
        q = (
            sb.table("portfolio_snapshots")
            .select("snapshot_date,nav,daily_return,cumulative_return,"
                    "drawdown,spy_close,btc_close,positions_count")
            .eq("source", source)
            .order("snapshot_date", desc=False)
        )
        if backtest_id:
            q = q.eq("backtest_id", backtest_id)
        else:
            q = q.is_("backtest_id", "null")
        if days:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
            q = q.gte("snapshot_date", cutoff)
        resp = q.execute()
        return resp.data or []
    except Exception as exc:
        log.warning("portfolio_snapshots.get_equity_curve failed: %s", exc)
        return []


def get_benchmark_comparison(days: int = 30, source: str = "paper_live",
                             current_nav: float | None = None) -> dict:
    """Return portfolio vs SPY vs BTC returns for a given period.

    When current_nav is provided and Supabase has at least 1 historical row,
    uses current_nav as the endpoint so the tile shows live data from day one.
    SPY and BTC current prices are fetched from yfinance when needed.
    """
    sb = _get_sb()
    if sb is None:
        return {}
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        resp = (
            sb.table("portfolio_snapshots")
            .select("snapshot_date,nav,spy_close,btc_close")
            .eq("source", source)
            .is_("backtest_id", "null")
            .gte("snapshot_date", cutoff)
            .order("snapshot_date", desc=False)
            .execute()
        )
        rows = resp.data or []

        # When we have at least 1 historical row and a live NAV, supplement instead of refusing
        if len(rows) < 2 and (current_nav is None or len(rows) == 0):
            return {"period_days": days, "rows": len(rows), "insufficient_data": True}

        first = rows[0] if rows else None
        end_nav = current_nav if current_nav is not None else float(rows[-1]["nav"])
        start_nav = float(first["nav"]) if first else end_nav

        port_ret = (end_nav - start_nav) / max(start_nav, 1) * 100

        # For SPY/BTC: use Supabase closes when available; fall back to yfinance spot price
        spy_ret = btc_ret = None
        last_row = rows[-1] if rows else {}
        first_spy = float(first["spy_close"]) if first and first.get("spy_close") else None
        last_spy  = float(last_row.get("spy_close") or 0) or None

        first_btc = float(first["btc_close"]) if first and first.get("btc_close") else None
        last_btc  = float(last_row.get("btc_close") or 0) or None

        # If last row is stale (not today) and current_nav was supplied, fetch live prices
        if current_nav is not None:
            try:
                import yfinance as yf
                spy_spot = yf.Ticker("SPY").fast_info.get("lastPrice") or yf.Ticker("SPY").fast_info.get("previousClose")
                btc_spot = yf.Ticker("BTC-USD").fast_info.get("lastPrice") or yf.Ticker("BTC-USD").fast_info.get("previousClose")
                if spy_spot:
                    last_spy = float(spy_spot)
                if btc_spot:
                    last_btc = float(btc_spot)
                # Use Supabase first-row prices as start; if missing, use yfinance history
                if first_spy is None and first:
                    import pandas as pd
                    hist = yf.download("SPY", start=first["snapshot_date"], end=first["snapshot_date"],
                                       progress=False, auto_adjust=True)
                    if not hist.empty:
                        first_spy = float(hist["Close"].iloc[0])
            except Exception:
                pass

        if first_spy and last_spy:
            spy_ret = (last_spy - first_spy) / first_spy * 100
        if first_btc and last_btc:
            btc_ret = (last_btc - first_btc) / first_btc * 100

        since = first["snapshot_date"] if first else datetime.now(timezone.utc).date().isoformat()
        return {
            "period_days":      days,
            "since_date":       since,
            "portfolio_return": round(port_ret, 2),
            "spy_return":       round(spy_ret, 2) if spy_ret is not None else None,
            "btc_return":       round(btc_ret, 2) if btc_ret is not None else None,
            "rows":             len(rows),
        }
    except Exception as exc:
        log.warning("portfolio_snapshots.get_benchmark_comparison failed: %s", exc)
        return {}
