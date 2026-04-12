"""Centralised config — reads from environment / .env file."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")

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

    # Brain
    signal_confidence_threshold: float = Field(0.7, env="SIGNAL_CONFIDENCE_THRESHOLD")
    brain_port: int = Field(8000, env="BRAIN_PORT")

    # Risk
    max_position_pct: float = Field(0.05, env="MAX_POSITION_PCT")
    max_crypto_allocation_pct: float = Field(0.30, env="MAX_CRYPTO_ALLOCATION_PCT")
    circuit_breaker_drawdown: float = Field(0.10, env="CIRCUIT_BREAKER_DRAWDOWN")

    # Monitoring
    prometheus_port: int = Field(9090, env="PROMETHEUS_PORT")
    grafana_port: int = Field(3000, env="GRAFANA_PORT")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
