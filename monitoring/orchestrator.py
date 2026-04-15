"""Layer 4 — Orchestrator.

Runs the main event loop:
  1. Every N minutes: fetch data → call Brain API → execute signal.
  2. Continuously: update trailing stops.
  3. Daily: check retrain trigger (Sharpe < threshold).
  4. All state pushed to Prometheus.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import httpx
import schedule

from config import get_settings
from data.portfolio import PortfolioFetcher, PortfolioState
from monitoring.metrics import (
    brain_latency_histogram,
    circuit_breaker_gauge,
    crypto_allocation_gauge,
    daily_pnl_gauge,
    daily_pnl_pct_gauge,
    equity_gauge,
    order_counter,
    retrain_counter,
    signal_confidence_histogram,
    signal_counter,
    start_metrics_server,
)

log = logging.getLogger(__name__)

# Symbols to watch — extend as needed
STOCK_WATCHLIST  = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"]
ETF_WATCHLIST    = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
CRYPTO_WATCHLIST = ["BTCUSDT", "ETHUSDT"]


def _wait_for_brain(url: str, timeout_secs: int = 60) -> bool:
    """Poll /health until uvicorn is ready, up to timeout_secs."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/health", timeout=3)
            if r.status_code == 200:
                log.info("Brain API ready at %s", url)
                return True
        except Exception:
            pass
        time.sleep(2)
    log.error("Brain API did not become ready within %ds", timeout_secs)
    return False


class Orchestrator:
    def __init__(self) -> None:
        cfg = get_settings()
        self._cfg = cfg
        self._brain_url = f"http://localhost:{cfg.brain_port}"
        # Use LLM debate when Anthropic key is configured, rule-based otherwise
        self._paper_mode = not bool(cfg.anthropic_api_key)
        mode_label = "rule-based (paper)" if self._paper_mode else "LLM debate (live)"
        log.info("Orchestrator signal mode: %s", mode_label)

        self._portfolio_fetcher = PortfolioFetcher(
            cfg.alpaca_api_key, cfg.alpaca_secret_key, cfg.alpaca_base_url,
            cfg.binance_api_key, cfg.binance_secret_key, cfg.binance_testnet,
        )

        self._peak_equity: float = 0.0

    # ── Portfolio refresh ──────────────────────────────────────────────────────

    def _refresh_portfolio_metrics(self) -> PortfolioState:
        portfolio = self._portfolio_fetcher.snapshot()
        equity_gauge.set(portfolio.equity)
        daily_pnl_gauge.set(portfolio.daily_pnl)
        daily_pnl_pct_gauge.set(portfolio.daily_pnl_pct)
        crypto_allocation_gauge.set(portfolio.crypto_allocation_pct * 100)

        if portfolio.equity > self._peak_equity:
            self._peak_equity = portfolio.equity
        drawdown = (
            (self._peak_equity - portfolio.equity) / self._peak_equity * 100
            if self._peak_equity > 0 else 0.0
        )

        from monitoring.metrics import drawdown_gauge
        drawdown_gauge.set(drawdown)

        cb_active = drawdown / 100 >= self._cfg.circuit_breaker_drawdown
        circuit_breaker_gauge.set(1.0 if cb_active else 0.0)

        log.info(
            "Portfolio: equity=%.2f pnl=%.2f (%.2f%%) cash=%.2f drawdown=%.2f%% cb=%s",
            portfolio.equity, portfolio.daily_pnl, portfolio.daily_pnl_pct,
            portfolio.cash, drawdown, "ACTIVE" if cb_active else "off",
        )

        if cb_active:
            log.warning(
                "CIRCUIT BREAKER ACTIVE — drawdown %.2f%% >= %.0f%% limit. "
                "All trades blocked until equity recovers.",
                drawdown, self._cfg.circuit_breaker_drawdown * 100,
            )

        return portfolio

    # ── Signal + execution ────────────────────────────────────────────────────

    def _process_symbol(self, symbol: str, asset_class: str, portfolio: PortfolioState) -> None:
        # Skip if circuit breaker is active
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - portfolio.equity) / self._peak_equity
            if drawdown >= self._cfg.circuit_breaker_drawdown:
                log.info("SKIP %s — circuit breaker active (drawdown=%.1f%%)", symbol, drawdown * 100)
                return

        payload = {
            "symbol":        symbol,
            "asset_class":   asset_class,
            "lookback_days": 60,
            "paper_mode":    self._paper_mode,
        }
        start = time.monotonic()
        try:
            resp = httpx.post(f"{self._brain_url}/signal", json=payload, timeout=180)
            resp.raise_for_status()
            sig = resp.json()
        except Exception as exc:
            log.error("Brain API call failed for %s: %s", symbol, exc)
            return
        finally:
            elapsed = time.monotonic() - start
            brain_latency_histogram.observe(elapsed)

        action     = sig.get("action", "HOLD")
        confidence = sig.get("confidence", 0.0)
        tier       = sig.get("tier", "COLD")
        votes_for  = sig.get("votes_for_action", 0)
        conflict   = sig.get("panels_conflict", False)

        signal_counter.labels(symbol=symbol, action=action, asset_class=asset_class).inc()
        signal_confidence_histogram.observe(confidence)

        log.info(
            "Signal %-6s  %-6s  conf=%.2f  tier=%-4s  votes=%d/15  conflict=%s",
            symbol, action, confidence, tier, votes_for, conflict,
        )

        if action == "HOLD":
            log.info("  → HOLD for %s — no order submitted", symbol)
            return

        log.info("  → Submitting %s %s order via /execute …", action, symbol)

        try:
            exec_resp = httpx.post(
                f"{self._brain_url}/execute",
                json={
                    "symbol":                 symbol,
                    "asset_class":            asset_class,
                    "action":                 action,
                    "suggested_position_pct": sig.get("suggested_position_pct", 0.02),
                    "stop_loss_pct":          sig.get("stop_loss_pct",          0.02),
                    "take_profit_pct":        sig.get("take_profit_pct",        0.05),
                },
                timeout=30,
            )
            exec_resp.raise_for_status()
            result = exec_resp.json()
            log.info(
                "  ✓ ORDER PLACED — %s %s  id=%s  status=%s  notional=%s",
                action, symbol,
                result.get("order_id", "?"),
                result.get("status", "?"),
                result.get("notional", result.get("qty", "?")),
            )
            status = "submitted"
        except httpx.HTTPStatusError as exc:
            log.error(
                "  ✗ Execute rejected for %s: HTTP %d — %s",
                symbol, exc.response.status_code, exc.response.text[:300],
            )
            status = "skipped"
        except Exception as exc:
            log.error("  ✗ Execute call failed for %s: %s", symbol, exc)
            status = "skipped"

        exchange = "alpaca" if asset_class == "stock" else "binance"
        order_counter.labels(symbol=symbol, action=action, exchange=exchange, status=status).inc()

    # ── Retrain trigger ───────────────────────────────────────────────────────

    def _check_retrain(self, portfolio: PortfolioState) -> None:
        if portfolio.daily_pnl_pct < -1.0:
            log.info("Retrain trigger: daily P&L = %.2f%%", portfolio.daily_pnl_pct)
            retrain_counter.inc()

    # ── Scheduled jobs ────────────────────────────────────────────────────────

    def _run_cycle(self) -> None:
        log.info("=" * 60)
        log.info("=== Cycle start %s ===", datetime.now(timezone.utc).isoformat())
        log.info("=" * 60)

        try:
            portfolio = self._refresh_portfolio_metrics()
        except Exception as exc:
            log.error("Portfolio refresh failed: %s — using defaults", exc)
            from datetime import timezone as tz
            portfolio = PortfolioState(
                timestamp=datetime.now(timezone.utc),
                equity=100_000.0, cash=100_000.0,
            )

        self._check_retrain(portfolio)

        all_symbols = (
            [(s, "stock")  for s in STOCK_WATCHLIST] +
            [(s, "stock")  for s in ETF_WATCHLIST] +
            [(s, "crypto") for s in CRYPTO_WATCHLIST]
        )

        for sym, asset_class in all_symbols:
            try:
                self._process_symbol(sym, asset_class, portfolio)
            except Exception as exc:
                log.error("Unhandled error processing %s: %s", sym, exc)
            # Small gap between symbols to avoid rate-limiting
            time.sleep(1)

        log.info("=== Cycle complete ===")

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        # Wait for Brain API to be ready before first cycle
        if not _wait_for_brain(self._brain_url, timeout_secs=90):
            log.error("Giving up waiting for Brain API — orchestrator exiting")
            return

        try:
            start_metrics_server(port=8001)
            log.info("Metrics server started on :8001")
        except Exception as exc:
            log.warning("Metrics server failed to start (non-fatal): %s", exc)

        schedule.every(15).minutes.do(self._run_cycle)
        schedule.every(1).minutes.do(self._refresh_portfolio_metrics)

        log.info(
            "Orchestrator ready — scanning %d symbols every 15 min  mode=%s",
            len(STOCK_WATCHLIST) + len(ETF_WATCHLIST) + len(CRYPTO_WATCHLIST),
            "rule-based" if self._paper_mode else "LLM",
        )
        self._run_cycle()   # run immediately on start

        while True:
            schedule.run_pending()
            time.sleep(10)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    Orchestrator().run()
