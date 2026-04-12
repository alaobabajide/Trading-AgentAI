"""Layer 2 — Brain FastAPI service on :8000.

POST /signal   → runs the full debate and returns a TradingSignal JSON.
GET  /health   → liveness check.
GET  /signal/{symbol}/latest → last cached signal.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import get_settings
from data.market_data import AlpacaMarketData, BinanceMarketData
from data.sentiment import SentimentFetcher
from data.onchain import OnChainFetcher
from data.portfolio import PortfolioFetcher
from brain.debate import DebateOrchestrator
from brain.signal import TradingSignal

log = logging.getLogger(__name__)

# ── In-memory signal cache ─────────────────────────────────────────────────────
_signal_cache: dict[str, dict] = {}


# ── Request / response models ──────────────────────────────────────────────────

class SignalRequest(BaseModel):
    symbol: str = Field(..., description="Ticker, e.g. AAPL or BTCUSDT")
    asset_class: str = Field(..., description="'stock' or 'crypto'")
    lookback_days: int = Field(60, ge=20, le=365)


class SignalResponse(BaseModel):
    symbol: str
    asset_class: str
    action: str
    confidence: float
    rationale: str
    generated_at: str
    suggested_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    agent_views: dict[str, str]
    passed_confidence_gate: bool


# ── App factory ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Brain API starting up…")
    yield
    log.info("Brain API shutting down.")


app = FastAPI(
    title="TradingAgent Brain",
    description="Multi-agent reasoning layer — Fundamental · Technical · Sentiment · Risk",
    version="0.1.0",
    lifespan=lifespan,
)


def _build_services(cfg):
    alpaca = AlpacaMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
    binance = BinanceMarketData(cfg.binance_api_key, cfg.binance_secret_key, cfg.binance_testnet)
    sentiment = SentimentFetcher()
    onchain = OnChainFetcher(eth_rpc_url=cfg.eth_rpc_url)
    portfolio = PortfolioFetcher(
        cfg.alpaca_api_key, cfg.alpaca_secret_key, cfg.alpaca_base_url,
        cfg.binance_api_key, cfg.binance_secret_key, cfg.binance_testnet,
    )
    orchestrator = DebateOrchestrator(
        anthropic_api_key=cfg.anthropic_api_key,
        confidence_threshold=cfg.signal_confidence_threshold,
        max_position_pct=cfg.max_position_pct,
        max_crypto_pct=cfg.max_crypto_allocation_pct,
        circuit_breaker_drawdown=cfg.circuit_breaker_drawdown,
    )
    return alpaca, binance, sentiment, onchain, portfolio, orchestrator


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/signal", response_model=SignalResponse)
def generate_signal(req: SignalRequest):
    cfg = get_settings()
    alpaca, binance, sentiment_fetcher, onchain_fetcher, portfolio_fetcher, orchestrator = (
        _build_services(cfg)
    )

    # ── Fetch data ──────────────────────────────────────────────────────────
    try:
        if req.asset_class == "stock":
            market = alpaca.snapshot(req.symbol, req.lookback_days)
            onchain_snap = None
        else:
            market = binance.snapshot(req.symbol, req.lookback_days)
            onchain_snap = onchain_fetcher.snapshot()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {exc}")

    sentiment_bundle = sentiment_fetcher.bundle(req.symbol)

    try:
        portfolio_state = portfolio_fetcher.snapshot()
    except Exception as exc:
        log.warning("Portfolio fetch failed, using defaults: %s", exc)
        from data.portfolio import PortfolioState
        from datetime import timezone
        portfolio_state = PortfolioState(
            timestamp=datetime.now(timezone.utc),
            equity=100_000.0,
            cash=100_000.0,
        )

    # ── Run debate ──────────────────────────────────────────────────────────
    signal: TradingSignal = orchestrator.run(market, sentiment_bundle, onchain_snap, portfolio_state)

    # Cache
    _signal_cache[req.symbol] = signal.to_dict()

    d = signal.to_dict()
    return SignalResponse(
        symbol=d["symbol"],
        asset_class=d["asset_class"],
        action=d["action"],
        confidence=d["confidence"],
        rationale=d["rationale"],
        generated_at=d["generated_at"],
        suggested_position_pct=d["suggested_position_pct"],
        stop_loss_pct=d["stop_loss_pct"],
        take_profit_pct=d["take_profit_pct"],
        agent_views=d["agent_views"],
        passed_confidence_gate=(d["action"] != "HOLD"),
    )


@app.get("/signal/{symbol}/latest", response_model=dict)
def get_latest_signal(symbol: str):
    cached = _signal_cache.get(symbol.upper())
    if not cached:
        raise HTTPException(status_code=404, detail=f"No cached signal for {symbol}")
    return cached


if __name__ == "__main__":
    cfg = get_settings()
    uvicorn.run("brain.api:app", host="0.0.0.0", port=cfg.brain_port, reload=False)
