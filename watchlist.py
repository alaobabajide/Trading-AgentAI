"""Shared watchlist definitions — single source of truth for both brain/api.py and monitoring/orchestrator.py."""
from __future__ import annotations

STOCK_WATCHLIST = [
    # ── Mega-cap tech / AI ────────────────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    # ── Growth tech / cloud / SaaS ────────────────────────────────────────────
    "NFLX", "ADBE", "CRM", "NOW", "SNOW", "SHOP", "UBER", "WDAY", "ORCL",
    # ── Semiconductors (high-beta) ────────────────────────────────────────────
    "AMD", "MU", "QCOM", "AMAT", "KLAC",
    # ── Cybersecurity / AI infra ──────────────────────────────────────────────
    "PANW", "CRWD", "PLTR", "DDOG", "NET", "ZS", "COIN",
    # ── Financials ────────────────────────────────────────────────────────────
    "JPM", "V", "MA", "GS", "BX", "BLK", "SCHW", "KKR",
    # ── Healthcare / biotech ─────────────────────────────────────────────────
    "LLY", "UNH", "AMGN", "TMO", "ISRG",
    # ── Consumer ─────────────────────────────────────────────────────────────
    "COST", "HD", "NKE", "SBUX",
    # ── Energy ───────────────────────────────────────────────────────────────
    "XOM", "OXY",
    # ── Industrials ──────────────────────────────────────────────────────────
    "GE", "CAT",
]

ETF_WATCHLIST = [
    # ── Broad US market ───────────────────────────────────────────────────────
    "SPY", "QQQ", "VTI", "IWM",
    # ── International ─────────────────────────────────────────────────────────
    "EEM", "EWJ", "FXI", "EWZ",
    # ── Fixed income (signal-generating) ─────────────────────────────────────
    "TLT", "HYG", "JNK",
    # ── Commodities ───────────────────────────────────────────────────────────
    "GLD", "SLV", "USO",
    # ── All 11 SPDR sector ETFs ───────────────────────────────────────────────
    "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
    # ── Thematic / high-volatility ────────────────────────────────────────────
    "ARKK", "SOXX", "SMH", "IBB", "KWEB",
]

# Alpaca crypto format (BTCUSD, not BTCUSDT) — no Binance geo-block
CRYPTO_WATCHLIST = ["BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "DOGEUSD", "LTCUSD"]

# Vote thresholds for signal tiers (27-agent pool)
HOT_MIN_VOTES  = 17   # ≥17 weighted votes aligned → HOT
WARM_MIN_VOTES = 13   # 13–16 weighted votes aligned → WARM (raised from 11 — 38% too permissive)
AGENT_COUNT    = 27   # total agents in the debate pool

# Orchestrator cycle interval (minutes)
CYCLE_INTERVAL_MINUTES = 30

LLM_PROVIDER_NAME = "OpenRouter"
LLM_PROVIDER_URL  = "openrouter.ai/settings/billing"

# Model IDs on OpenRouter (verify at openrouter.ai/models before changing)
TACTICAL_MODEL  = "google/gemini-2.5-flash-lite"       # 25 tactical agents — $0.10/M in, $0.40/M out
SYNTHESIS_MODEL = "deepseek/deepseek-chat-v3-0324"     # RiskManager + StrategyCoach — $0.27/M in, $1.12/M out
