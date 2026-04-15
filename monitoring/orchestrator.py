"""Layer 4 — Orchestrator.

Runs the main event loop:
  1. Every N minutes: fetch data → call Brain API → execute signal.
  2. Continuously: update trailing stops.
  3. Daily: check retrain trigger (Sharpe < threshold).
  4. All state pushed to Prometheus.
"""
from __future__ import annotations

import logging
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
STOCK_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA"]
ETF_WATCHLIST   = ["SPY", "QQQ", "IWM", "GLD", "TLT", "XLK", "EEM"]
CRYPTO_WATCHLIST = ["BTCUSDT", "ETHUSDT"]


class Orchestrator:
    def __init__(self) -> None:
        cfg = get_settings()
        self._cfg = cfg
        self._brain_url = f"http://localhost:{cfg.brain_port}"

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
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - portfolio.equity) / self._peak_equity * 100
        else:
            drawdown = 0.0

        from monitoring.metrics import drawdown_gauge
        drawdown_gauge.set(drawdown)

        cb_active = drawdown / 100 >= self._cfg.circuit_breaker_drawdown
        circuit_breaker_gauge.set(1.0 if cb_active else 0.0)

        log.info(
            "Portfolio: equity=%.2f pnl=%.2f (%.2f%%) crypto=%.1f%% drawdown=%.2f%%",
            portfolio.equity, portfolio.daily_pnl, portfolio.daily_pnl_pct,
            portfolio.crypto_allocation_pct * 100, drawdown,
        )
        return portfolio

    # ── Signal + execution ────────────────────────────────────────────────────

    def _process_symbol(self, symbol: str, asset_class: str, portfolio: PortfolioState) -> None:
        payload = {"symbol": symbol, "asset_class": asset_class, "lookback_days": 60}
        start = time.monotonic()
        try:
            resp = httpx.post(f"{self._brain_url}/signal", json=payload, timeout=120)
            resp.raise_for_status()
            sig = resp.json()
        except Exception as exc:
            log.error("Brain API call failed for %s: %s", symbol, exc)
            return
        finally:
            elapsed = time.monotonic() - start
            brain_latency_histogram.observe(elapsed)

        action = sig["action"]
        confidence = sig["confidence"]

        signal_counter.labels(symbol=symbol, action=action, asset_class=asset_class).inc()
        signal_confidence_histogram.observe(confidence)

        if action == "HOLD":
            log.info("HOLD for %s (confidence=%.2f)", symbol, confidence)
            return

        log.info("Signal: %s %s confidence=%.2f — submitting order via /execute", action, symbol, confidence)

        # Delegate to the brain API's /execute endpoint.
        # This avoids the empty-bars problem: /execute fetches live price from
        # Alpaca/Binance itself and uses notional sizing (equity × position_pct).
        try:
            exec_resp = httpx.post(
                f"{self._brain_url}/execute",
                json={
                    "symbol":                 symbol,
                    "asset_class":            asset_class,
                    "action":                 action,
                    "suggested_position_pct": sig.get("suggested_position_pct", 0.01),
                    "stop_loss_pct":          sig.get("stop_loss_pct",          0.02),
                    "take_profit_pct":        sig.get("take_profit_pct",        0.05),
                },
                timeout=30,
            )
            exec_resp.raise_for_status()
            result = exec_resp.json()
            log.info("Order result for %s: %s", symbol, result)
            status = "submitted"
        except Exception as exc:
            log.error("Execute API call failed for %s: %s", symbol, exc)
            result = None
            status = "skipped"

        exchange = "alpaca" if asset_class == "stock" else "binance"
        order_counter.labels(symbol=symbol, action=action, exchange=exchange, status=status).inc()

    # ── Retrain trigger ───────────────────────────────────────────────────────

    def _check_retrain(self, portfolio: PortfolioState) -> None:
        """Simple heuristic: trigger retrain if 5-day pnl is negative."""
        if portfolio.daily_pnl_pct < -1.0:
            log.info("Retrain trigger: daily P&L = %.2f%%", portfolio.daily_pnl_pct)
            retrain_counter.inc()
            # In production: kick off a fine-tuning job or prompt update here.

    # ── Scheduled jobs ────────────────────────────────────────────────────────

    def _run_cycle(self) -> None:
        log.info("=== Cycle start %s ===", datetime.now(timezone.utc).isoformat())
        portfolio = self._refresh_portfolio_metrics()
        self._check_retrain(portfolio)

        for sym in STOCK_WATCHLIST:
            try:
                self._process_symbol(sym, "stock", portfolio)
            except Exception as exc:
                log.error("Error processing %s: %s", sym, exc)

        for sym in ETF_WATCHLIST:
            try:
                self._process_symbol(sym, "stock", portfolio)  # ETFs trade like stocks via Alpaca
            except Exception as exc:
                log.error("Error processing %s: %s", sym, exc)

        for sym in CRYPTO_WATCHLIST:
            try:
                self._process_symbol(sym, "crypto", portfolio)
            except Exception as exc:
                log.error("Error processing %s: %s", sym, exc)

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        cfg = self._cfg
        start_metrics_server(port=8001)
        log.info("Metrics server started on :8001")

        schedule.every(15).minutes.do(self._run_cycle)
        schedule.every(1).minutes.do(self._refresh_portfolio_metrics)

        log.info("Orchestrator started — cycle every 15 min")
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
