"""Prometheus metrics registry.

Exposes an HTTP endpoint on PROMETHEUS_PORT so Prometheus can scrape:
  • Equity gauge
  • Daily P&L gauge
  • Drawdown gauge
  • Crypto allocation gauge
  • Signal count by action
  • Order count by exchange and status
  • Brain API latency histogram
"""
from __future__ import annotations

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

# ── Portfolio gauges ───────────────────────────────────────────────────────────
equity_gauge = Gauge("trading_equity_usd", "Total portfolio equity in USD")
cash_gauge = Gauge("trading_cash_usd", "Available cash in USD")
daily_pnl_gauge = Gauge("trading_daily_pnl_usd", "Daily P&L in USD")
daily_pnl_pct_gauge = Gauge("trading_daily_pnl_pct", "Daily P&L as a percentage")
drawdown_gauge = Gauge("trading_drawdown_pct", "Current drawdown from peak (%)")
crypto_allocation_gauge = Gauge(
    "trading_crypto_allocation_pct",
    "Percentage of equity allocated to crypto",
)

# ── Signal counters ────────────────────────────────────────────────────────────
signal_counter = Counter(
    "trading_signals_total",
    "Number of signals generated",
    ["symbol", "action", "asset_class"],
)
signal_confidence_histogram = Histogram(
    "trading_signal_confidence",
    "Distribution of signal confidence scores",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ── Order counters ─────────────────────────────────────────────────────────────
order_counter = Counter(
    "trading_orders_total",
    "Number of orders submitted",
    ["symbol", "action", "exchange", "status"],
)

# ── Brain API latency ──────────────────────────────────────────────────────────
brain_latency_histogram = Histogram(
    "trading_brain_latency_seconds",
    "End-to-end latency of Brain signal generation",
    buckets=[1, 2, 5, 10, 20, 30, 60],
)

# ── Circuit breaker ────────────────────────────────────────────────────────────
circuit_breaker_gauge = Gauge(
    "trading_circuit_breaker_active",
    "1 if the circuit breaker is tripped, 0 otherwise",
)

# ── Retrain loop ───────────────────────────────────────────────────────────────
retrain_counter = Counter(
    "trading_retrain_cycles_total",
    "Number of retrain cycles completed",
)


def start_metrics_server(port: int = 8001) -> None:
    """Start the Prometheus HTTP scrape endpoint."""
    start_http_server(port)
