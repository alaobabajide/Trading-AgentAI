"""Centralised config — reads from environment / .env file."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # OpenRouter — primary LLM gateway
    openrouter_api_key: str = Field("", env="OPENROUTER_API_KEY")

    # Alpaca
    alpaca_api_key: str = Field("", env="ALPACA_API_KEY")
    alpaca_secret_key: str = Field("", env="ALPACA_SECRET_KEY")
    alpaca_base_url: str = Field("https://paper-api.alpaca.markets", env="ALPACA_BASE_URL")

    # Binance
    binance_api_key: str = Field("", env="BINANCE_API_KEY")
    binance_secret_key: str = Field("", env="BINANCE_SECRET_KEY")
    binance_testnet: bool = Field(True, env="BINANCE_TESTNET")

    # On-chain
    eth_rpc_url: str = Field("", env="ETH_RPC_URL")

    # Polygon.io — optional market data upgrade (replaces Alpaca bars when set)
    polygon_api_key: str = Field("", env="POLYGON_API_KEY")

    # Sentiment — Finnhub free tier fallback (optional; used when Yahoo RSS < 5 headlines)
    finnhub_api_key: str = Field("", env="FINNHUB_API_KEY")

    # Brain — Railway injects $PORT; fall back to BRAIN_PORT or 8000
    signal_confidence_threshold: float = Field(0.7, env="SIGNAL_CONFIDENCE_THRESHOLD")
    brain_port: int = Field(default_factory=lambda: int(os.environ.get("PORT") or os.environ.get("BRAIN_PORT") or 8000))

    # ── Position sizing ───────────────────────────────────────────────────────
    max_position_pct: float = Field(0.05, env="MAX_POSITION_PCT")          # WARM signal max, % of equity
    hot_position_pct: float = Field(0.08, env="HOT_POSITION_PCT")          # HOT signal max (overrides max_position_pct)
    max_crypto_allocation_pct: float = Field(0.30, env="MAX_CRYPTO_ALLOCATION_PCT")

    # ── Portfolio exposure ────────────────────────────────────────────────────
    max_exposure_pct: float = Field(0.50, env="MAX_EXPOSURE_PCT")          # max % of equity deployed at once
    max_concurrent_positions: int = Field(15, env="MAX_CONCURRENT_POSITIONS")

    # ── Entry / exit thresholds ───────────────────────────────────────────────
    stop_loss_pct: float = Field(0.02, env="STOP_LOSS_PCT")                # fallback when ATR data unavailable
    take_profit_pct: float = Field(0.05, env="TAKE_PROFIT_PCT")
    trailing_stop_pct: float = Field(0.015, env="TRAILING_STOP_PCT")       # trailing stop % for runners
    partial_exit_pct: float = Field(0.50, env="PARTIAL_EXIT_PCT")          # Layer 1 exit fraction
    runner_trail_pct: float = Field(0.10, env="RUNNER_TRAIL_PCT")          # default runner trailing %

    # ── ATR stop sizing ───────────────────────────────────────────────────────
    atr_multiplier: float = Field(1.5, env="ATR_MULTIPLIER")               # stop = atr_multiplier × ATR14
    atr_stop_floor: float = Field(0.005, env="ATR_STOP_FLOOR")             # minimum stop distance (0.5%)
    atr_stop_cap: float = Field(0.04, env="ATR_STOP_CAP")                  # maximum stop distance (4.0%)

    # ── Circuit breaker / drawdown ────────────────────────────────────────────
    circuit_breaker_drawdown: float = Field(0.10, env="CIRCUIT_BREAKER_DRAWDOWN")
    drawdown_scale_threshold: float = Field(0.08, env="DRAWDOWN_SCALE_THRESHOLD")  # reduce sizes above this
    drawdown_scale_factor: float = Field(0.80, env="DRAWDOWN_SCALE_FACTOR")        # scale factor when triggered

    # ── Correlation protection ────────────────────────────────────────────────
    correlation_halving_threshold: float = Field(0.70, env="CORRELATION_HALVING_THRESHOLD")

    # ── Signal analysis ───────────────────────────────────────────────────────
    lookback_days: int = Field(300, env="LOOKBACK_DAYS")                   # historical bars window

    # ── Loss cooldown ─────────────────────────────────────────────────────────
    loss_cooldown_hits: int = Field(2, env="LOSS_COOLDOWN_HITS")           # stop-loss hits to trigger cooldown
    loss_cooldown_window_days: int = Field(5, env="LOSS_COOLDOWN_WINDOW_DAYS")
    loss_cooldown_skip_cycles: int = Field(2, env="LOSS_COOLDOWN_SKIP_CYCLES")

    # ── Security ──────────────────────────────────────────────────────────────
    brain_api_key: str = Field("", env="BRAIN_API_KEY")  # required — set in Railway
    allowed_origins: str = Field("", env="ALLOWED_ORIGINS")  # comma-separated CORS origins

    # ── Supabase auth ─────────────────────────────────────────────────────────
    supabase_url: str = Field("", env="SUPABASE_URL")
    supabase_anon_key: str = Field("", env="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field("", env="SUPABASE_SERVICE_ROLE_KEY")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    telegram_allowed_ids: str = Field("", env="TELEGRAM_ALLOWED_IDS")  # comma-separated chat IDs
    max_telegram_order_usd: float = Field(1000.0, env="MAX_TELEGRAM_ORDER_USD")

    # ── Regime-adaptive risk overrides ───────────────────────────────────────────
    regime_trending_up_min_tp: float = Field(0.08, env="REGIME_TRENDING_UP_MIN_TP")
    regime_ranging_max_tp: float = Field(0.03, env="REGIME_RANGING_MAX_TP")
    regime_high_vol_min_sl: float = Field(0.03, env="REGIME_HIGH_VOL_MIN_SL")
    regime_high_vol_max_tp: float = Field(0.05, env="REGIME_HIGH_VOL_MAX_TP")

    # ── Credit / retrain triggers ─────────────────────────────────────────────
    retrain_trigger_loss_pct: float = Field(1.0, env="RETRAIN_TRIGGER_LOSS_PCT")
    credit_warning_threshold_usd: float = Field(5.0, env="CREDIT_WARNING_THRESHOLD_USD")
    credit_critical_threshold_usd: float = Field(2.0, env="CREDIT_CRITICAL_THRESHOLD_USD")
    credit_alert_cooldown_secs: int = Field(3600, env="CREDIT_ALERT_COOLDOWN_SECS")

    # ── COLD cooldown ─────────────────────────────────────────────────────────
    cold_skip_cycles: int = Field(2, env="COLD_SKIP_CYCLES")  # cycles a COLD symbol sits out

    # ── Crypto execution ──────────────────────────────────────────────────────
    crypto_cash_buffer: float = Field(0.99, env="CRYPTO_CASH_BUFFER")
    crypto_min_notional_usd: float = Field(1.0, env="CRYPTO_MIN_NOTIONAL_USD")
    crypto_fallback_equity_usd: float = Field(100_000.0, env="CRYPTO_FALLBACK_EQUITY_USD")

    # Monitoring
    prometheus_port: int = Field(9090, env="PROMETHEUS_PORT")
    grafana_port: int = Field(3000, env="GRAFANA_PORT")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
