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

import time as _time

log = logging.getLogger(__name__)

# ── Kill switch ────────────────────────────────────────────────────────────────
_TRADING_PAUSED: bool = False

# ── Service singleton (rebuilt once per process, not per request) ─────────────
_services_cache: Any = None

# ── Bar data cache (5-min TTL — avoids re-fetching 300 days on every signal) ──
_bar_cache: dict[str, tuple[Any, float]] = {}
_BAR_CACHE_TTL = 300.0  # seconds

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
    lookback_days: int = Field(300, ge=61, le=400)
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


def _get_services(cfg):
    """Return the service singleton, building it once per process."""
    global _services_cache
    if _services_cache is None:
        log.info("Building service singleton (first request this process)")
        _services_cache = _build_services(cfg)
    return _services_cache


def _get_market_snapshot(fetcher, symbol: str, days: int):
    """Return a cached bar snapshot (TTL %ds) to avoid re-fetching on every signal."""
    key = f"{symbol}:{days}"
    now = _time.monotonic()
    if key in _bar_cache:
        snap, ts = _bar_cache[key]
        if now - ts < _BAR_CACHE_TTL:
            log.debug("Bar cache hit for %s (%ds)", symbol, days)
            return snap
    snap = fetcher.snapshot(symbol, days)
    _bar_cache[key] = (snap, now)
    return snap


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

@app.post("/kill")
def kill_switch():
    """Emergency halt — stops all new trade execution immediately."""
    global _TRADING_PAUSED
    _TRADING_PAUSED = True
    log.critical("KILL SWITCH ACTIVATED — auto-trading paused")
    return {"status": "paused", "message": "Auto-trading halted. POST /resume to restart."}


@app.post("/resume")
def resume_trading():
    """Resume trading after a kill switch."""
    global _TRADING_PAUSED
    _TRADING_PAUSED = False
    log.info("Auto-trading resumed via /resume")
    return {"status": "active", "message": "Auto-trading resumed."}


@app.get("/kill")
def kill_status():
    """Check whether trading is currently paused."""
    return {"paused": _TRADING_PAUSED}


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
            _get_services(cfg)
        )
    except Exception as exc:
        log.error("Service initialisation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Service init failed: {exc}")

    # ── Fetch market data (bar cache reduces Alpaca round-trip to ~0 ms after first call) ──
    try:
        if req.asset_class == "stock":
            market = _get_market_snapshot(alpaca, req.symbol, req.lookback_days)
            onchain_snap = None
        else:
            market = _get_market_snapshot(binance, req.symbol, req.lookback_days)
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
    """Place a bracket order (entry + stop-loss + take-profit) via the execution engines.

    Routes to StockExecutionEngine (Alpaca bracket orders) or CryptoExecutionEngine
    (Binance market + OCO), which enforce all risk controls:
      • ATR-based position sizing capped at max_position_pct (5% NAV)
      • Stop-loss and take-profit on every entry
      • Circuit breaker (10% daily drawdown)
      • Crypto cap (30% of portfolio)

    Uses cached signal sizing if available; falls back to request params.
    """
    if _TRADING_PAUSED:
        raise HTTPException(status_code=503, detail="Trading paused — POST /resume to restart")
    if req.action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="action must be BUY or SELL")

    from config import get_settings
    from brain.signal import TradingSignal

    cfg = get_settings()

    # Merge with cached signal sizing if present
    cached   = _signal_cache.get(req.symbol.upper(), {})
    pos_pct  = float(cached.get("suggested_position_pct", req.suggested_position_pct))
    sl_pct   = float(cached.get("stop_loss_pct",          req.stop_loss_pct))
    tp_pct   = float(cached.get("take_profit_pct",        req.take_profit_pct))

    # Build a TradingSignal from the request so the execution engines can use it
    signal = TradingSignal(
        symbol=req.symbol.upper(),
        asset_class=req.asset_class,  # type: ignore[arg-type]
        action=req.action,            # type: ignore[arg-type]
        confidence=1.0,
        rationale=cached.get("rationale", "Manual execute via API"),
        suggested_position_pct=pos_pct,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
    )

    try:
        if req.asset_class == "stock":
            from data.market_data import AlpacaMarketData
            from execution.stock.engine import StockExecutionEngine

            is_paper = "paper" in cfg.alpaca_base_url.lower()

            # Fetch recent bars for ATR-based sizing (14-day minimum)
            market = AlpacaMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
            bars   = market.get_bars(req.symbol.upper(), days=30)
            bars_highs  = [b.high  for b in bars]
            bars_lows   = [b.low   for b in bars]
            bars_closes = [b.close for b in bars]

            engine = StockExecutionEngine(
                alpaca_api_key=cfg.alpaca_api_key,
                alpaca_secret_key=cfg.alpaca_secret_key,
                alpaca_base_url=cfg.alpaca_base_url,
                max_position_pct=cfg.max_position_pct,
                circuit_breaker_drawdown=cfg.circuit_breaker_drawdown,
            )
            result = engine.execute(signal, bars_highs, bars_lows, bars_closes)

            if result is None:
                raise HTTPException(
                    status_code=409,
                    detail="Order blocked by risk controls (circuit breaker, sizing, or invalid price)",
                )

            exchange = "alpaca_paper" if is_paper else "alpaca_live"
            return {
                "order_id":        result.order_id,
                "status":          "submitted",
                "symbol":          result.symbol,
                "action":          result.action,
                "qty":             result.qty,
                "submitted_price": result.submitted_price,
                "stop_price":      result.stop_price,
                "take_profit_price": result.take_profit_price,
                "exchange":        exchange,
                "stop_pct":        sl_pct,
                "target_pct":      tp_pct,
            }

        else:  # crypto — Binance
            from alpaca.trading.client import TradingClient
            from execution.crypto.engine import CryptoExecutionEngine

            # Get portfolio equity from Alpaca so crypto cap is evaluated correctly
            is_paper = "paper" in cfg.alpaca_base_url.lower()
            trading_client = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper)
            acct           = trading_client.get_account()
            portfolio_equity = float(acct.equity)

            engine = CryptoExecutionEngine(
                binance_api_key=cfg.binance_api_key,
                binance_secret_key=cfg.binance_secret_key,
                testnet=cfg.binance_testnet,
                max_position_pct=cfg.max_position_pct,
                max_crypto_allocation_pct=cfg.max_crypto_allocation_pct,
            )
            result = engine.execute(signal, portfolio_equity=portfolio_equity)

            if result is None:
                raise HTTPException(
                    status_code=409,
                    detail="Order blocked by risk controls (crypto cap, sizing, or invalid price)",
                )

            return {
                "order_id":          result.order_id,
                "status":            "submitted",
                "symbol":            result.symbol,
                "action":            result.action,
                "qty":               result.qty,
                "avg_price":         result.submitted_price,
                "stop_price":        result.stop_price,
                "take_profit_price": result.take_profit_price,
                "exchange":          result.exchange,
                "stop_pct":          sl_pct,
                "target_pct":        tp_pct,
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

    All periods use the same approach: reconstruct equity from live
    positions + historical price bars via Alpaca's market data API.

        equity[t] = cash + Σ(qty_i × close_price_i[t])

    1D  → 5-minute bars, last 24 h  (up to 288 pts)
    1M  → daily bars,    last 30 d  (up to 30 pts)
    1Y  → daily bars,    last 365 d (up to 365 pts)

    This is reliable for all periods because it uses the market data API
    (StockHistoricalDataClient / CryptoHistoricalDataClient) which always
    has data, unlike the portfolio history API which returns null-heavy
    results for paper accounts outside market hours.
    """
    from config import get_settings
    cfg = get_settings()
    if not cfg.alpaca_api_key:
        return []

    is_paper = "paper" in cfg.alpaca_base_url.lower()

    lookback = {"1D": 1, "1M": 30, "1Y": 365}.get(period, 1)
    daily    = period != "1D"
    return _build_equity(cfg, is_paper, lookback_days=lookback, use_daily=daily)


def _build_1d_equity(cfg, is_paper: bool) -> list:
    return _build_equity(cfg, is_paper, lookback_days=1, use_daily=False)


def _build_equity(cfg, is_paper: bool, lookback_days: int, use_daily: bool) -> list:
    """
    Reconstruct an equity curve from live positions + historical price bars.

        equity[t] = cash + Σ(qty_i × close_price_i[t])

    use_daily=False → 5-minute bars (for 1D)
    use_daily=True  → daily bars    (for 1M / 1Y)

    Stock bars: market hours only; prices carried forward between sessions.
    Crypto bars: 24/7, fills overnight gaps.
    """
    import pandas as pd
    from datetime import timezone, timedelta
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    tf    = TimeFrame.Day if use_daily else TimeFrame(5, TimeFrameUnit.Minute)
    label = f"{'daily' if use_daily else '5min'}/{lookback_days}d"

    try:
        client  = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper)
        acct    = client.get_account()
        cash    = float(acct.cash)
        raw_pos = client.get_all_positions()
    except Exception as exc:
        log.error("equity(%s): account/positions failed: %s", label, exc)
        return []

    if not raw_pos:
        log.info("equity(%s): no positions — flat cash line", label)
        pts, t = [], start
        step = timedelta(days=1) if use_daily else timedelta(minutes=5)
        while t <= now:
            pts.append({"time": t.isoformat(), "equity": cash, "pnl": 0.0})
            t += step
        return pts

    stock_pos: dict  = {}
    crypto_pos: dict = {}
    for p in raw_pos:
        qty       = float(p.qty)
        sym       = p.symbol
        asset_cls = str(getattr(p, "asset_class", "")).lower()
        if "crypto" in asset_cls:
            slash = sym[:-3] + "/" + sym[-3:] if "/" not in sym else sym
            crypto_pos[slash] = qty
        else:
            stock_pos[sym] = qty

    log.info("equity(%s): %d stock + %d crypto pos, cash=%.2f",
             label, len(stock_pos), len(crypto_pos), cash)

    price_series: dict = {}   # {datetime_utc: {symbol: close_price}}

    def _load_df(df, sym_map: dict) -> None:
        """Parse a bars DataFrame (possibly MultiIndex) into price_series."""
        if df is None or df.empty:
            return
        if isinstance(df.index, pd.MultiIndex):
            for sym in sym_map:
                lvl0 = df.index.get_level_values(0)
                if sym not in lvl0:
                    continue
                for ts, row in df.loc[sym].iterrows():
                    t = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                    t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
                    price_series.setdefault(t, {})[sym] = float(row["close"])
        else:
            sym = next(iter(sym_map))
            for ts, row in df.iterrows():
                t = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
                price_series.setdefault(t, {})[sym] = float(row["close"])

    # ── Stock bars ────────────────────────────────────────────────────────────
    if stock_pos:
        sc = StockHistoricalDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        for feed in (DataFeed.SIP, DataFeed.IEX):
            try:
                req = StockBarsRequest(
                    symbol_or_symbols=list(stock_pos.keys()),
                    timeframe=tf, start=start, end=now, feed=feed,
                )
                df = sc.get_stock_bars(req).df
                if not df.empty:
                    _load_df(df, stock_pos)
                    log.info("equity(%s): %d stock bar ts via %s", label, len(price_series), feed)
                    break
            except Exception as exc:
                log.warning("equity(%s): stock bars %s: %s", label, feed, exc)

    # ── Crypto bars (24/7) ────────────────────────────────────────────────────
    if crypto_pos:
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            cc  = CryptoHistoricalDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
            req = CryptoBarsRequest(
                symbol_or_symbols=list(crypto_pos.keys()),
                timeframe=tf, start=start, end=now,
            )
            df = cc.get_crypto_bars(req).df
            _load_df(df, crypto_pos)
            log.info("equity(%s): crypto bars added, total ts=%d", label, len(price_series))
        except Exception as exc:
            log.warning("equity(%s): crypto bars: %s", label, exc)

    if not price_series:
        log.warning("equity(%s): no price bars — empty", label)
        return []

    # ── Build time series with carry-forward pricing ──────────────────────────
    sorted_ts  = sorted(price_series.keys())
    last_price: dict = {}
    pts        = []

    for t in sorted_ts:
        last_price.update(price_series[t])
        equity = cash
        for sym, qty in stock_pos.items():
            px = last_price.get(sym)
            if px:
                equity += qty * px
        for sym, qty in crypto_pos.items():
            px = last_price.get(sym)
            if px:
                equity += qty * px
        pts.append({"time": t.isoformat(), "equity": equity, "pnl": 0.0})

    log.info("equity(%s): %d pts from %d positions", label, len(pts), len(raw_pos))
    return pts


@app.get("/portfolio/history/debug")
def portfolio_history_debug():
    """Diagnostic: shows point counts for 1D/1M/1Y equity builds."""
    from config import get_settings
    cfg = get_settings()
    if not cfg.alpaca_api_key:
        return {"error": "no ALPACA_API_KEY"}
    is_paper = "paper" in cfg.alpaca_base_url.lower()
    out = {}
    for period, days, daily in [("1D", 1, False), ("1M", 30, True), ("1Y", 365, True)]:
        pts = _build_equity(cfg, is_paper, lookback_days=days, use_daily=daily)
        out[period] = {"pts": len(pts), "first": pts[:1], "last": pts[-1:]}
    return out


if __name__ == "__main__":
    from config import get_settings
    cfg = get_settings()
    uvicorn.run("brain.api:app", host="0.0.0.0", port=cfg.brain_port, reload=False)
