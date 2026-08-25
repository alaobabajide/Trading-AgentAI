"""Backtest Supabase engine — wraps runner.py and persists results to Supabase.

Writes to:
  backtest_runs       — one row per run, aggregate metrics
  signal_snapshots    — one row per trade entry (source='backtest_rule')
  portfolio_snapshots — daily NAV rows (source='backtest')

Called by POST /backtest/run in brain/api.py.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def run_backtest(
    name: str,
    start_date: str,
    end_date: str | None,
    symbols: str | list[str] = "all",
    initial_equity: float = 100_000.0,
) -> dict[str, Any]:
    """Run a rule-based backtest and persist results to Supabase.

    Returns a summary dict with the run_id and key metrics.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    # ── Resolve symbol list ──────────────────────────────────────────────────
    from watchlist import STOCK_WATCHLIST, ETF_WATCHLIST
    if symbols == "all" or symbols == ["all"]:
        # Crypto tickers in the watchlist are Alpaca format (BTCUSD), not yfinance
        # format (BTC-USD). The rule-based runner uses yfinance, so crypto is excluded.
        resolved = list(STOCK_WATCHLIST) + list(ETF_WATCHLIST)
    elif isinstance(symbols, str):
        resolved = [symbols]
    else:
        resolved = list(symbols)

    # ── Supabase client ──────────────────────────────────────────────────────
    sb = _get_supabase()

    # ── Insert pending run row ───────────────────────────────────────────────
    run_id = str(uuid.uuid4())
    run_row: dict[str, Any] = {
        "id":           run_id,
        "name":         name,
        "status":       "running",
        "start_date":   start_date,
        "end_date":     end_date or date.today().isoformat(),
        "engine":       "rule_based",
        "initial_nav":  initial_equity,
        "symbol_universe": resolved,
        "config": {
            "symbols":       resolved,
            "initial_equity": initial_equity,
        },
    }
    if sb:
        try:
            sb.table("backtest_runs").insert(run_row).execute()
        except Exception as exc:
            log.warning("backtest_runs insert pending: %s", exc)

    # ── Run the backtest ─────────────────────────────────────────────────────
    try:
        from backtest.runner import run_backtest as _run_backtest
        # Compute years from start_date to end_date
        from datetime import date as _date
        _start = _date.fromisoformat(start_date)
        _end   = _date.fromisoformat(end_date) if end_date else _date.today()
        years  = max(1, round((_end - _start).days / 365))
        result = _run_backtest(
            symbols=resolved,
            years=years,
            initial_equity=initial_equity,
        )
    except Exception as exc:
        log.error("backtest run failed: %s", exc)
        _update_run(sb, run_id, {"status": "failed", "error_message": str(exc)})
        return {"run_id": run_id, "status": "failed", "error": str(exc)}

    # ── Persist signal snapshots (one per trade) ─────────────────────────────
    if sb and result.trades:
        _write_signal_snapshots(sb, run_id, result.trades)

    # ── Persist portfolio NAV curve ──────────────────────────────────────────
    if sb and result.equity_curve:
        _write_portfolio_snapshots(sb, run_id, result.equity_curve)

    # ── Update run row with final metrics ────────────────────────────────────
    spy_ret = getattr(result, "benchmark_return_pct", None)
    final_row: dict[str, Any] = {
        "status":            "completed",
        "final_nav":         result.final_equity,
        "total_return":      result.total_return_pct / 100.0,
        "annualized_return": result.annualised_return_pct / 100.0,
        "max_drawdown":      result.max_drawdown_pct / 100.0,
        "sharpe_ratio":      result.sharpe_ratio,
        "win_rate":          result.win_rate_pct,
        "total_trades":      result.total_trades,
        "profit_factor":     result.profit_factor,
        "spy_return":        spy_ret / 100.0 if spy_ret is not None else None,
        "btc_return":        None,
    }
    _update_run(sb, run_id, final_row)

    return {
        "run_id":            run_id,
        "status":            "completed",
        "total_return_pct":  result.total_return_pct,
        "annualized_return_pct": result.annualised_return_pct,
        "sharpe_ratio":      result.sharpe_ratio,
        "max_drawdown_pct":  result.max_drawdown_pct,
        "win_rate_pct":      result.win_rate_pct,
        "total_trades":      result.total_trades,
        "final_equity":      result.final_equity,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_supabase():
    try:
        from config import get_settings
        cfg = get_settings()
        if not cfg.supabase_url or not cfg.supabase_service_role_key:
            return None
        from supabase import create_client
        return create_client(cfg.supabase_url, cfg.supabase_service_role_key)
    except Exception as exc:
        log.warning("backtest supabase client: %s", exc)
        return None


def _update_run(sb, run_id: str, data: dict) -> None:
    if not sb:
        return
    try:
        sb.table("backtest_runs").update(data).eq("id", run_id).execute()
    except Exception as exc:
        log.warning("backtest_runs update: %s", exc)


def _write_signal_snapshots(sb, run_id: str, trades) -> None:
    rows = []
    for t in trades:
        try:
            rows.append({
                "symbol":         t.symbol,
                "asset_class":    "stock",
                "action":         t.action,
                "source":         "backtest_rule",
                "backtest_id":    run_id,
                "entry_price":    t.entry_price,
                "sim_date":       t.entry_date,
                "tier":           getattr(t, "tier", "WARM"),
                "outcome":        _classify_outcome(t.pnl_pct, t.action),
                "return_final":   t.pnl_pct * (-1 if t.action == "SELL" else 1),
            })
        except Exception:
            continue

    if not rows:
        return

    chunk = 100
    for i in range(0, len(rows), chunk):
        try:
            sb.table("signal_snapshots").insert(rows[i:i+chunk]).execute()
        except Exception as exc:
            log.warning("signal_snapshots backtest insert: %s", exc)


def _write_portfolio_snapshots(sb, run_id: str, equity_curve: list[dict]) -> None:
    rows = []
    peak = 0.0
    for point in equity_curve:
        nav = float(point.get("equity", point.get("nav", 0)))
        if nav > peak:
            peak = nav
        dd = (nav - peak) / max(peak, 1) * 100 if peak > 0 else 0.0
        rows.append({
            "snapshot_date":  point.get("date", ""),
            "source":         "backtest",
            "backtest_id":    run_id,
            "nav":            nav,
            "drawdown":       dd,
        })

    chunk = 200
    for i in range(0, len(rows), chunk):
        try:
            sb.table("portfolio_snapshots").upsert(
                rows[i:i+chunk],
                on_conflict="snapshot_date,source,backtest_id",
            ).execute()
        except Exception as exc:
            log.warning("portfolio_snapshots backtest upsert: %s", exc)


def _classify_outcome(pnl_pct: float, action: str) -> str:
    effective = pnl_pct * (-1 if action == "SELL" else 1)
    if effective >= 5.0:
        return "WIN"
    if effective <= -2.0:
        return "LOSS"
    return "NEUTRAL"
