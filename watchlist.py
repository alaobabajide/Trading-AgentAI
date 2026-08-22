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

# Max active watch rules per user (Category C NLP alerts).
# Overridable at runtime via Settings → Brain → Max watch rules.
MAX_WATCH_RULES_DEFAULT = 10

LLM_PROVIDER_NAME = "OpenRouter"
LLM_PROVIDER_URL  = "openrouter.ai/settings/billing"

# Model IDs on OpenRouter (verify at openrouter.ai/models before changing)
TACTICAL_MODEL  = "google/gemini-2.5-flash-lite"       # 25 tactical agents — $0.10/M in, $0.40/M out
SYNTHESIS_MODEL = "deepseek/deepseek-chat-v3-0324"     # RiskManager + StrategyCoach — $0.27/M in, $1.12/M out

# ── Multi-provider LLM support ────────────────────────────────────────────────

# OpenAI-compatible base URLs for each provider.
# None = uses native SDK (Anthropic only).
# Confidence annotations: Qwen 92%, Kimi 90% — verify before use.
PROVIDER_BASE_URLS: dict[str, str | None] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai":     "https://api.openai.com/v1",
    "anthropic":  None,   # native anthropic SDK
    "deepseek":   "https://api.deepseek.com/v1",
    "xai":        "https://api.x.ai/v1",
    "qwen":       "https://dashscope.aliyuncs.com/compatible-mode/v1",  # 92% confidence
    "kimi":       "https://api.moonshot.cn/v1",                          # 90% confidence
}

PROVIDER_DISPLAY: dict[str, str] = {
    "openrouter": "OpenRouter",
    "openai":     "OpenAI",
    "anthropic":  "Anthropic",
    "deepseek":   "DeepSeek",
    "xai":        "xAI (Grok)",
    "qwen":       "Qwen (Alibaba)",
    "kimi":       "Kimi (Moonshot)",
}

PROVIDER_BILLING_URLS: dict[str, str] = {
    "openrouter": "openrouter.ai/settings/billing",
    "openai":     "platform.openai.com/account/billing",
    "anthropic":  "console.anthropic.com/settings/billing",
    "deepseek":   "platform.deepseek.com/usage",
    "xai":        "console.x.ai",
    "qwen":       "dashscope.console.aliyun.com",
    "kimi":       "platform.moonshot.cn",
}

# Curated model lists per provider — ordered best-first.
# Users may also enter a custom model ID via the "Other" option.
PROVIDER_MODELS: dict[str, list[str]] = {
    "openrouter": [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat-v3-0324",
        "deepseek/deepseek-r1",
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "meta-llama/llama-3.3-70b-instruct",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "qwen/qwen3-235b-a22b",
        "mistralai/mistral-large-2411",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o3-mini",
        "o1",
    ],
    "anthropic": [
        "claude-opus-5-20251101",
        "claude-sonnet-5-20251101",
        "claude-sonnet-4-5-20251001",
        "claude-haiku-4-5-20251001",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "xai": [
        "grok-3",
        "grok-3-mini",
        "grok-2-1212",
    ],
    "qwen": [
        "qwen-max",
        "qwen-plus",
        "qwen-turbo",
        "qwen3-235b-a22b",
    ],
    "kimi": [
        "moonshot-v1-128k",
        "moonshot-v1-32k",
        "moonshot-v1-8k",
    ],
}
