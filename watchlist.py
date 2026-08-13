"""Shared watchlist definitions — single source of truth for both brain/api.py and monitoring/orchestrator.py."""
from __future__ import annotations

STOCK_WATCHLIST = [
    # ── Mega-cap tech / AI (>$1T market cap) ──────────────────────────────────
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "ORCL",
    # ── Growth tech / cloud / SaaS ────────────────────────────────────────────
    "NFLX", "ADBE", "CRM", "NOW", "SNOW", "SHOP", "UBER", "WDAY",
    # ── Semiconductors / hardware ──────────────────────────────────────────────
    "AMD", "MU", "TXN", "QCOM", "INTC", "AMAT", "KLAC", "DELL",
    # ── Cybersecurity / AI infra ──────────────────────────────────────────────
    "PANW", "CRWD", "PLTR", "DDOG", "NET", "ZS", "COIN",
    # ── Financials ────────────────────────────────────────────────────────────
    "JPM", "V", "MA", "BAC", "GS", "MS", "WFC", "C", "AXP", "BX", "BLK",
    "SCHW", "MCO", "SPGI", "KKR",
    # ── Healthcare / pharma / biotech ─────────────────────────────────────────
    "LLY", "JNJ", "UNH", "ABBV", "MRK", "AMGN", "TMO", "ISRG", "PFE", "MDT",
    # ── Consumer discretionary ────────────────────────────────────────────────
    "WMT", "COST", "HD", "LOW", "MCD", "SBUX", "NKE", "TGT",
    # ── Consumer staples ──────────────────────────────────────────────────────
    "PG", "KO", "PEP", "PM", "CVS",
    # ── Energy ────────────────────────────────────────────────────────────────
    "XOM", "CVX", "OXY", "SLB", "COP",
    # ── Industrials / aerospace / defence ─────────────────────────────────────
    "GE", "CAT", "DE", "HON", "RTX", "LMT", "GD", "BA", "UPS", "FDX", "ETN",
    # ── Telecom / media ───────────────────────────────────────────────────────
    "VZ", "T", "CMCSA",
    # ── REITs / real estate ───────────────────────────────────────────────────
    "PLD", "AMT", "DLR", "WELL",
    # ── Diversified / conglomerate ────────────────────────────────────────────
    "IBM", "MMM", "LIN", "NEE", "ADP", "F", "GM",
]

ETF_WATCHLIST = [
    # ── Broad US market ────────────────────────────────────────────────────────
    "SPY", "VOO", "IVV", "QQQ", "VTI", "IWM", "DIA", "MDY",
    # ── International ─────────────────────────────────────────────────────────
    "VEA", "EEM", "IEMG", "VWO", "EWJ", "EWZ", "FXI",
    # ── Fixed income ──────────────────────────────────────────────────────────
    "BND", "AGG", "TLT", "LQD", "HYG", "JNK", "TIP", "SHY",
    # ── Commodities ───────────────────────────────────────────────────────────
    "GLD", "IAU", "SLV", "USO", "DBC",
    # ── All 11 SPDR sector ETFs ────────────────────────────────────────────────
    "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
    # ── Thematic / specialty ───────────────────────────────────────────────────
    "ARKK", "SOXX", "SMH", "IBB", "CIBR", "VNQ", "SCHD", "KWEB", "ICLN", "BOTZ", "GDX",
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

# Model IDs on OpenRouter (verify at openrouter.ai/models before changing)
TACTICAL_MODEL  = "google/gemini-2.5-flash-lite"       # 25 tactical agents — $0.10/M in, $0.40/M out
SYNTHESIS_MODEL = "deepseek/deepseek-chat-v3-0324"     # RiskManager + StrategyCoach — $0.27/M in, $1.12/M out
