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


def get_benchmark_comparison(days: int = 30, source: str = "paper_live") -> dict:
    """Return portfolio vs SPY vs BTC returns for a given period."""
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
        if len(rows) < 2:
            return {"period_days": days, "rows": len(rows), "insufficient_data": True}

        first, last = rows[0], rows[-1]
        port_ret = (float(last["nav"]) - float(first["nav"])) / float(first["nav"]) * 100

        spy_ret = btc_ret = None
        if first.get("spy_close") and last.get("spy_close"):
            spy_ret = (float(last["spy_close"]) - float(first["spy_close"])) / float(first["spy_close"]) * 100
        if first.get("btc_close") and last.get("btc_close"):
            btc_ret = (float(last["btc_close"]) - float(first["btc_close"])) / float(first["btc_close"]) * 100

        return {
            "period_days":      days,
            "since_date":       first["snapshot_date"],
            "portfolio_return": round(port_ret, 2),
            "spy_return":       round(spy_ret, 2) if spy_ret is not None else None,
            "btc_return":       round(btc_ret, 2) if btc_ret is not None else None,
            "rows":             len(rows),
        }
    except Exception as exc:
        log.warning("portfolio_snapshots.get_benchmark_comparison failed: %s", exc)
        return {}
