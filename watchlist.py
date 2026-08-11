"""Shared watchlist definitions — single source of truth for both brain/api.py and monitoring/orchestrator.py."""
from __future__ import annotations

STOCK_WATCHLIST = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
    # Growth tech / cloud / fintech
    "NFLX", "ADBE", "CRM", "AMD", "COIN", "SHOP", "UBER",
    # Semiconductors
    "INTC", "QCOM", "AVGO", "MU", "TXN",
    # Financials
    "JPM", "GS", "MS", "BAC", "BX", "V", "MA",
    # Healthcare / pharma
    "JNJ", "UNH", "LLY", "ABBV", "AMGN",
    # Consumer / retail
    "WMT", "COST", "HD", "NKE", "SBUX", "MCD",
    # Energy
    "XOM", "CVX", "OXY",
]

ETF_WATCHLIST = [
    "SPY", "QQQ", "IWM",              # broad market
    "GLD", "SLV",                      # metals
    "TLT", "HYG",                      # fixed income
    "XLE", "XLF", "XLK",              # sector originals
    "XLV", "XLP", "XLI", "XLU",       # defensive sectors
    "VTI",                             # total market
    "ARKK",                            # thematic innovation
    "EEM", "VEA",                      # international
]

# Alpaca crypto format (BTCUSD, not BTCUSDT) — no Binance geo-block
CRYPTO_WATCHLIST = ["BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "DOGEUSD", "LTCUSD"]

# Vote thresholds for signal tiers (27-agent pool)
HOT_MIN_VOTES  = 17   # ≥17 weighted votes aligned → HOT
WARM_MIN_VOTES = 11   # 11–16 weighted votes aligned → WARM
AGENT_COUNT    = 27   # total agents in the debate pool

# Orchestrator cycle interval (minutes)
CYCLE_INTERVAL_MINUTES = 15

LLM_PROVIDER_NAME = "OpenRouter"
LLM_PROVIDER_URL  = "openrouter.ai/settings/billing"
