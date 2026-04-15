"""Layer 2 — Brain FastAPI service on :8000.

POST /signal   → runs the full debate and returns a TradingSignal JSON.
GET  /health   → liveness check.
GET  /signal/{symbol}/latest → last cached signal.

Heavy dependencies (anthropic, pandas, ta, etc.) are imported lazily inside
request handlers so that a missing package or OOM during import does NOT
prevent the /health endpoint from responding.
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Persistent signal cache ────────────────────────────────────────────────────
# Survives uvicorn/process restarts within the same container.
# Falls back silently if the filesystem is read-only.
_CACHE_FILE = os.environ.get("SIGNAL_CACHE_FILE", "/tmp/ta_signal_cache.json")
_MAX_CACHE  = 100   # keep the 100 most-recent unique symbols


def _load_cache() -> dict[str, dict]:
    try:
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            log.info("Loaded %d cached signals from %s", len(data), _CACHE_FILE)
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("Could not load signal cache from disk: %s", exc)
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as exc:
        log.warning("Could not persist signal cache: %s", exc)


_signal_cache: dict[str, dict] = _load_cache()


# ── Request / response models ──────────────────────────────────────────────────

class SignalRequest(BaseModel):
    symbol: str = Field(..., description="Ticker, e.g. AAPL or BTCUSDT")
    asset_class: str = Field(..., description="'stock' or 'crypto'")
    lookback_days: int = Field(60, ge=20, le=365)
    paper_mode: bool = Field(True, description="True = rule-based analysis (no API credits); False = full LLM debate")


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
    # Vote-based fields — combined 15-agent pool
    vote_tally: dict = {}
    votes_for_action: int = 0
    regime_label: str = "UNKNOWN"
    tier: str = "WARM"
    devil_advocate_score: int = 0
    devil_advocate_case: str = ""
    strategy_fit: str = "ALIGNED"
    # Dual-panel breakdown
    panel_a_votes: dict = {}
    panel_b_votes: dict = {}
    panels_conflict: bool = False
    conflict_note: str = ""


# ── App factory ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    import sys, os
    log.info("Brain API starting up — Python %s  cwd=%s", sys.version.split()[0], os.getcwd())
    yield
    log.info("Brain API shutting down.")


app = FastAPI(
    title="TradingAgent Brain",
    description="Multi-agent reasoning layer — Fundamental · Technical · Sentiment · Risk",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Return the actual error message instead of a blank 500."""
    import traceback
    from fastapi.responses import JSONResponse
    log.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}",
                 "traceback": traceback.format_exc()[-2000:]},
    )


def _build_services(cfg):
    # Heavy imports done here (inside a request handler) so a bad import never
    # prevents the health endpoint from starting.
    from config import get_settings  # noqa: F401 (already passed as cfg)
    from data.market_data import AlpacaMarketData, BinanceMarketData
    from data.sentiment import SentimentFetcher
    from data.onchain import OnChainFetcher
    from data.portfolio import PortfolioFetcher
    from brain.debate import DebateOrchestrator

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


@app.get("/")
def root():
    return {
        "name": "TradingAgent Brain API",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "POST /signal": "Run 9-agent debate for a symbol",
            "GET /signal/{symbol}/latest": "Fetch last cached signal",
            "GET /health": "Liveness check",
        },
    }

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/config-status")
def config_status():
    """Returns which API keys are configured (true/false only — never exposes values)."""
    import os
    from config import get_settings
    cfg = get_settings()
    return {
        "anthropic":       bool(cfg.anthropic_api_key),
        "alpaca":          bool(cfg.alpaca_api_key and cfg.alpaca_secret_key),
        "binance":         bool(cfg.binance_api_key and cfg.binance_secret_key),
        "telegram":        bool(cfg.telegram_bot_token),
        "alpaca_base_url": cfg.alpaca_base_url,
        "binance_testnet": cfg.binance_testnet,
        "auto_trade":      os.environ.get("AUTO_TRADE", "").lower() == "true",
        "ready_for_signals":  bool(cfg.anthropic_api_key),
        "ready_for_trading":  bool(cfg.anthropic_api_key and cfg.alpaca_api_key),
    }


@app.post("/signal", response_model=SignalResponse)
def generate_signal(req: SignalRequest):
    from config import get_settings
    cfg = get_settings()
    if not cfg.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured. Set it in Railway environment variables.",
        )
    try:
        alpaca, binance, sentiment_fetcher, onchain_fetcher, portfolio_fetcher, orchestrator = (
            _build_services(cfg)
        )
    except Exception as exc:
        log.error("Service initialisation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Service init failed: {exc}")

    # ── Fetch market data ───────────────────────────────────────────────────
    try:
        if req.asset_class == "stock":
            market = alpaca.snapshot(req.symbol, req.lookback_days)
            onchain_snap = None
        else:
            market = binance.snapshot(req.symbol, req.lookback_days)
            onchain_snap = onchain_fetcher.snapshot()
    except Exception as exc:
        log.error("Market data fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {exc}")

    # ── Fetch sentiment (non-fatal) ─────────────────────────────────────────
    try:
        sentiment_bundle = sentiment_fetcher.bundle(req.symbol)
    except Exception as exc:
        log.warning("Sentiment fetch failed, using empty bundle: %s", exc)
        from data.sentiment import SentimentBundle
        sentiment_bundle = SentimentBundle(symbol=req.symbol, items=[])

    # ── Fetch portfolio (non-fatal) ─────────────────────────────────────────
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

    # ── Run debate (paper mode = rule-based; live mode = full LLM) ────────
    try:
        signal = orchestrator.run(
            market, sentiment_bundle, onchain_snap, portfolio_state,
            paper_mode=req.paper_mode,
        )
    except Exception as exc:
        log.error("Debate failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent debate failed: {exc}")

    # Cache — persist to disk so signals survive process restarts
    _signal_cache[req.symbol] = signal.to_dict()
    _save_cache(_signal_cache)

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
        vote_tally=d.get("vote_tally", {}),
        votes_for_action=d.get("votes_for_action", 0),
        regime_label=d.get("regime_label", "UNKNOWN"),
        tier=d.get("tier", "WARM"),
        devil_advocate_score=d.get("devil_advocate_score", 0),
        devil_advocate_case=d.get("devil_advocate_case", ""),
        strategy_fit=d.get("strategy_fit", "ALIGNED"),
        panel_a_votes=d.get("panel_a_votes", {}),
        panel_b_votes=d.get("panel_b_votes", {}),
        panels_conflict=d.get("panels_conflict", False),
        conflict_note=d.get("conflict_note", ""),
    )


@app.get("/signal/{symbol}/latest", response_model=dict)
def get_latest_signal(symbol: str):
    cached = _signal_cache.get(symbol.upper())
    if not cached:
        raise HTTPException(status_code=404, detail=f"No cached signal for {symbol}")
    return cached


@app.get("/signals/cached", response_model=list)
def get_all_cached_signals():
    """Return all signals currently in the in-memory cache, newest first."""
    return sorted(
        _signal_cache.values(),
        key=lambda s: s.get("generated_at", ""),
        reverse=True,
    )


class ExecuteRequest(BaseModel):
    symbol: str
    asset_class: str = Field(..., description="'stock' or 'crypto'")
    action: str = Field(..., description="'BUY' or 'SELL'")
    suggested_position_pct: float = Field(0.05, ge=0.001, le=0.20)
    stop_loss_pct: float = Field(0.02, ge=0.005, le=0.20)
    take_profit_pct: float = Field(0.05, ge=0.01, le=0.50)
    qty: float = Field(0.0, ge=0.0, description="Fixed share/unit count. 0 = use notional (equity × position_pct)")


@app.post("/execute")
def execute_trade(req: ExecuteRequest):
    """Place a market order on Alpaca (stocks) or Binance (crypto).

    Uses the cached signal's sizing if available; falls back to request params.
    Returns order_id, status, notional, and exchange.
    """
    if req.action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="action must be BUY or SELL")

    from config import get_settings
    cfg = get_settings()

    # Merge with cached signal sizing if present
    cached = _signal_cache.get(req.symbol.upper(), {})
    pos_pct  = cached.get("suggested_position_pct", req.suggested_position_pct)
    sl_pct   = cached.get("stop_loss_pct",          req.stop_loss_pct)
    tp_pct   = cached.get("take_profit_pct",         req.take_profit_pct)

    try:
        if req.asset_class == "stock":
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            is_paper = "paper" in cfg.alpaca_base_url.lower()
            client   = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper)
            side     = OrderSide.BUY if req.action == "BUY" else OrderSide.SELL
            exchange = "alpaca_paper" if is_paper else "alpaca_live"

            if req.qty > 0:
                # Fixed share-count order
                order = client.submit_order(MarketOrderRequest(
                    symbol=req.symbol.upper(),
                    qty=req.qty,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                ))
                return {
                    "order_id":   str(order.id),
                    "status":     str(order.status),
                    "symbol":     req.symbol.upper(),
                    "action":     req.action,
                    "qty":        req.qty,
                    "exchange":   exchange,
                    "stop_pct":   sl_pct,
                    "target_pct": tp_pct,
                }
            else:
                # Notional (equity × position %) order
                acct     = client.get_account()
                equity   = float(acct.equity)
                notional = round(equity * pos_pct, 2)
                if notional < 1:
                    raise HTTPException(status_code=400, detail="Computed notional < $1 — check position sizing")
                order = client.submit_order(MarketOrderRequest(
                    symbol=req.symbol.upper(),
                    notional=notional,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                ))
                return {
                    "order_id":   str(order.id),
                    "status":     str(order.status),
                    "symbol":     req.symbol.upper(),
                    "action":     req.action,
                    "notional":   notional,
                    "exchange":   exchange,
                    "stop_pct":   sl_pct,
                    "target_pct": tp_pct,
                }

        else:  # crypto — Binance
            from binance.client import Client as BinanceClient

            client = BinanceClient(
                cfg.binance_api_key, cfg.binance_secret_key,
                testnet=cfg.binance_testnet,
            )
            ticker  = client.get_symbol_ticker(symbol=req.symbol.upper())
            price   = float(ticker["price"])

            # Approximate equity from USDT balance
            balances  = client.get_account()["balances"]
            usdt_free = next((float(b["free"]) for b in balances if b["asset"] == "USDT"), 1000.0)
            notional  = min(usdt_free * pos_pct, usdt_free * 0.99)
            qty       = round(notional / price, 6)

            if qty <= 0:
                raise HTTPException(status_code=400, detail="Computed qty = 0")

            if req.action == "BUY":
                order = client.order_market_buy(symbol=req.symbol.upper(), quantity=qty)
            else:
                order = client.order_market_sell(symbol=req.symbol.upper(), quantity=qty)

            fills   = order.get("fills", [])
            avg_px  = (
                sum(float(f["price"]) * float(f["qty"]) for f in fills)
                / max(sum(float(f["qty"]) for f in fills), 1e-12)
                if fills else price
            )
            return {
                "order_id":  str(order.get("orderId", "?")),
                "status":    order.get("status", "FILLED"),
                "symbol":    req.symbol.upper(),
                "action":    req.action,
                "qty":       qty,
                "avg_price": avg_px,
                "exchange":  "binance_testnet" if cfg.binance_testnet else "binance",
                "stop_pct":  sl_pct,
                "target_pct": tp_pct,
            }

    except HTTPException:
        raise
    except Exception as exc:
        log.error("Trade execution failed for %s: %s", req.symbol, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Execution failed: {exc}")


@app.get("/portfolio")
def get_portfolio():
    """Return current portfolio state (positions, equity, P&L).

    Returns a zeroed default if no exchange credentials are configured so the
    dashboard always renders rather than showing a 500 error.
    """
    from config import get_settings
    from data.portfolio import PortfolioFetcher, PortfolioState
    from datetime import timezone

    cfg = get_settings()

    # If no Alpaca credentials are set at all, return a safe empty state
    # rather than attempting a call that will fail.
    if not cfg.alpaca_api_key:
        log.warning("/portfolio called with no ALPACA_API_KEY configured — returning empty state")
        state = PortfolioState(
            timestamp=datetime.now(timezone.utc),
            equity=0.0,
            cash=0.0,
        )
    else:
        portfolio_fetcher = PortfolioFetcher(
            cfg.alpaca_api_key, cfg.alpaca_secret_key, cfg.alpaca_base_url,
            cfg.binance_api_key, cfg.binance_secret_key, cfg.binance_testnet,
        )
        try:
            state = portfolio_fetcher.snapshot()
        except Exception as exc:
            log.error("Portfolio fetch failed: %s", exc, exc_info=True)
            # Return empty state so the dashboard degrades gracefully
            state = PortfolioState(
                timestamp=datetime.now(timezone.utc),
                equity=0.0,
                cash=0.0,
            )

    return {
        "timestamp":             state.timestamp.isoformat(),
        "equity":                state.equity,
        "cash":                  state.cash,
        "buying_power":          state.buying_power,
        "daily_pnl":             state.daily_pnl,
        "daily_pnl_pct":         state.daily_pnl_pct,
        "crypto_allocation_pct": state.crypto_allocation_pct,
        "positions": [
            {
                "symbol":             p.symbol,
                "asset_class":        p.asset_class,
                "qty":                p.qty,
                "avg_entry_price":    p.avg_entry_price,
                "current_price":      p.current_price,
                "market_value":       p.market_value,
                "unrealized_pnl":     p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
            }
            for p in state.positions
        ],
    }


@app.get("/portfolio/history")
def get_portfolio_history(period: str = "1D"):
    """Return the equity curve for the requested period.

    period (query param):
        1D  → today's intraday data, 5-min bars
        1M  → last month, daily bars
        1Y  → last year,  daily bars
        all → all available history, daily bars

    Uses the same alpaca-py TradingClient that already works for
    positions/equity — no raw httpx, no parameter format guessing.
    """
    from datetime import timezone
    from config import get_settings
    cfg = get_settings()

    if not cfg.alpaca_api_key:
        log.warning("/portfolio/history: no ALPACA_API_KEY configured")
        return []

    from alpaca.trading.client import TradingClient
    is_paper = "paper" in cfg.alpaca_base_url.lower()
    client   = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper)

    # Map UI period → (Alpaca period, Alpaca timeframe)
    # Fallback chains: if the primary request returns < 2 pts, widen the window.
    PERIOD_CHAINS: dict[str, list[tuple[str, str]]] = {
        "1D":  [("1D", "5Min"), ("1W", "1D"), ("1M", "1D")],
        "1M":  [("1M", "1D"),   ("3M", "1D")],
        "1Y":  [("1A", "1D"),   ("6M", "1D"), ("3M", "1D")],
        "all": [("all", "1D"),  ("1A", "1D"), ("6M", "1D")],
    }
    chain = PERIOD_CHAINS.get(period, PERIOD_CHAINS["1D"])

    def _to_points(hist) -> list:
        timestamps = list(getattr(hist, "timestamp",   None) or [])
        equities   = list(getattr(hist, "equity",      None) or [])
        pnls       = list(getattr(hist, "profit_loss", None) or [])
        nulls = sum(1 for e in equities if e is None)
        log.info("  raw: %d pts, %d null", len(equities), nulls)

        return [
            {
                "time":   datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "equity": float(eq),
                "pnl":    float(pnl) if pnl is not None else 0.0,
            }
            for ts, eq, pnl in zip(timestamps, equities, pnls)
            if eq is not None
        ]

    def _fetch(alp_period: str, alp_tf: str) -> list:
        log.info("Portfolio history: period=%s tf=%s", alp_period, alp_tf)
        # For intraday timeframes include pre/post-market so we get the full
        # 24-hour window (7 PM → 6 PM) that Alpaca's own app shows.
        intraday = alp_tf in ("1Min", "5Min", "15Min", "1H")
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest
            kwargs: dict = dict(period=alp_period, timeframe=alp_tf)
            if intraday:
                kwargs["extended_hours"] = True
            req  = GetPortfolioHistoryRequest(**kwargs)
            hist = client.get_portfolio_history(filter=req)
        except Exception as e1:
            log.warning("  SDK request failed (%s), trying direct kwargs", e1)
            try:
                kw: dict = dict(period=alp_period, timeframe=alp_tf)
                if intraday:
                    kw["extended_hours"] = True
                hist = client.get_portfolio_history(**kw)
            except Exception as e2:
                log.warning("  kwargs also failed: %s", e2)
                return []
        return _to_points(hist)

    for alp_period, alp_tf in chain:
        pts = _fetch(alp_period, alp_tf)
        if len(pts) >= 2:
            log.info("Portfolio history: returning %d pts", len(pts))
            return pts

    # Last resort: 2-point line from account snapshot
    log.warning("Portfolio history: all attempts returned <2 pts — using account snapshot")
    try:
        acct        = client.get_account()
        equity      = float(acct.equity)
        last_equity = float(acct.last_equity)
        now         = datetime.now(timezone.utc)
        day_start   = now.replace(hour=13, minute=30, second=0, microsecond=0)
        if day_start > now:
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [
            {"time": day_start.isoformat(), "equity": last_equity, "pnl": 0.0},
            {"time": now.isoformat(),        "equity": equity,      "pnl": equity - last_equity},
        ]
    except Exception as exc:
        log.error("Account snapshot fallback failed: %s", exc)
        return []


@app.get("/portfolio/history/debug")
def portfolio_history_debug():
    """Returns raw Alpaca portfolio history response for debugging.
    Shows exactly what the SDK returns so we can diagnose null-value issues.
    """
    from datetime import timezone
    from config import get_settings
    cfg = get_settings()
    if not cfg.alpaca_api_key:
        return {"error": "no ALPACA_API_KEY"}

    from alpaca.trading.client import TradingClient
    is_paper = "paper" in cfg.alpaca_base_url.lower()
    client   = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper)

    results = {}
    for period, timeframe in [("1D", "5Min"), ("1W", "1D"), ("1M", "1D")]:
        key = f"{period}/{timeframe}"
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest
            req  = GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
            hist = client.get_portfolio_history(filter=req)
            equities = list(getattr(hist, "equity", None) or [])
            non_null = [e for e in equities if e is not None]
            results[key] = {
                "total_pts":    len(equities),
                "non_null_pts": len(non_null),
                "first_3":      equities[:3],
                "last_3":       equities[-3:],
                "timeframe":    getattr(hist, "timeframe", None),
                "base_value":   getattr(hist, "base_value", None),
            }
        except Exception as exc:
            results[key] = {"error": str(exc)}

    return results


if __name__ == "__main__":
    from config import get_settings
    cfg = get_settings()
    uvicorn.run("brain.api:app", host="0.0.0.0", port=cfg.brain_port, reload=False)
