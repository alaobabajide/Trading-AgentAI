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
import re
import time as _time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Kill switch ────────────────────────────────────────────────────────────────
_TRADING_PAUSED: bool = False

# ── Service singleton (rebuilt once per process, not per request) ─────────────
_services_cache: Any = None

# ── Bar data cache (5-min TTL — avoids re-fetching 300 days on every signal) ──
_bar_cache: dict[str, tuple[Any, float]] = {}
_BAR_CACHE_TTL = 300.0  # seconds

# ── Security helpers ───────────────────────────────────────────────────────────

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")


def _validate_symbol(symbol: str) -> str:
    upper = symbol.strip().upper()
    if not _SYMBOL_RE.match(upper):
        raise HTTPException(400, "Invalid symbol — uppercase alphanumeric, 1-20 characters")
    return upper


# Simple in-process rate limiter (per IP, sliding window)
class _RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = _time.monotonic()
        cutoff = now - window_seconds
        hits = [t for t in self._windows[key] if t > cutoff]
        self._windows[key] = hits
        if len(hits) >= max_requests:
            return False
        self._windows[key].append(now)
        return True


_rate_limiter = _RateLimiter()

# Audit log — append-only JSONL, one entry per order
_AUDIT_LOG = os.environ.get("AUDIT_LOG_FILE", "/tmp/ta_audit.log")


def _write_audit(
    symbol: str, action: str, qty: float, notional: float,
    source: str, order_id: str = "",
) -> None:
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol, "action": action,
        "qty": qty, "notional": round(notional, 2),
        "source": source, "order_id": order_id,
    }
    try:
        with open(_AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.warning("Audit log write failed: %s", exc)


# Hard bounds for risk config — enforced on both load and PATCH
_CONFIG_BOUNDS: dict[str, tuple[float, float]] = {
    "stop_loss_pct":            (0.005, 0.20),
    "take_profit_pct":          (0.01,  0.50),
    "max_position_pct":         (0.005, 0.10),
    "circuit_breaker_drawdown": (0.01,  0.20),
    "max_crypto_allocation_pct":(0.0,   0.50),
}

# ── Dynamic risk config (frontend-editable, persisted to file) ────────────────
# Overrides env-var defaults without a redeploy.
# Shape: {stop_loss_pct, take_profit_pct, max_position_pct, circuit_breaker_drawdown}
_CONFIG_FILE = os.environ.get("DYNAMIC_CONFIG_FILE", "/tmp/ta_dynamic_config.json")
_dynamic_config: dict = {}


def _load_dynamic_config() -> dict:
    try:
        with open(_CONFIG_FILE) as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        validated: dict = {}
        for key, (lo, hi) in _CONFIG_BOUNDS.items():
            if key in raw:
                try:
                    val = float(raw[key])
                except (TypeError, ValueError):
                    continue
                if lo <= val <= hi:
                    validated[key] = val
                else:
                    log.warning("Dynamic config %s=%.4f out of bounds [%.4f, %.4f] — rejected", key, val, lo, hi)
        return validated
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not load dynamic config from %s: %s", _CONFIG_FILE, exc)
        return {}


def _save_dynamic_config(data: dict) -> None:
    try:
        with open(_CONFIG_FILE, "w") as f:
            json.dump(data, f)
        os.chmod(_CONFIG_FILE, 0o600)
    except Exception as exc:
        log.warning("Could not persist dynamic config: %s", exc)


def _effective_config(cfg) -> dict:
    """Merge env-var defaults with any dynamic overrides."""
    return {
        "stop_loss_pct":            _dynamic_config.get("stop_loss_pct",            cfg.stop_loss_pct),
        "take_profit_pct":          _dynamic_config.get("take_profit_pct",          cfg.take_profit_pct),
        "max_position_pct":         _dynamic_config.get("max_position_pct",         cfg.max_position_pct),
        "circuit_breaker_drawdown": _dynamic_config.get("circuit_breaker_drawdown", cfg.circuit_breaker_drawdown),
        "max_crypto_allocation_pct": _dynamic_config.get("max_crypto_allocation_pct", cfg.max_crypto_allocation_pct),
    }


_dynamic_config = _load_dynamic_config()

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

# ── CORS: restrict to configured origins (no wildcard by default) ─────────────
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=bool(_allowed_origins),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["X-Api-Key", "Content-Type"],
)

# ── Rate limiting (outermost — runs first, cheapest check) ────────────────────
_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "/execute": (5,  60),
    "/signal":  (10, 60),
    "/kill":    (5,  60),
    "/resume":  (5,  60),
    "/config":  (20, 60),
}
_DEFAULT_RATE = (120, 60)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = (request.client.host if request.client else "unknown")
    max_req, window = _RATE_LIMITS.get(request.url.path, _DEFAULT_RATE)
    if not _rate_limiter.is_allowed(client_ip, max_req, window):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded — slow down"})
    return await call_next(request)


# ── Body size guard (64 KB max) ───────────────────────────────────────────────
@app.middleware("http")
async def body_size_limit(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and int(cl) > 65_536:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


# ── API key authentication (all routes except /health and /) ─────────────────
_PUBLIC_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    from config import get_settings
    cfg = get_settings()
    if not cfg.brain_api_key:
        log.critical("BRAIN_API_KEY is not set — API is UNAUTHENTICATED. Set it in Railway env vars.")
        return await call_next(request)   # fail-open during initial setup only
    if request.headers.get("X-Api-Key", "") != cfg.brain_api_key:
        return JSONResponse(status_code=403, content={"detail": "Forbidden — invalid or missing API key"})
    return await call_next(request)


# ── Safe exception handler — never expose stack traces externally ─────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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
    eff = _effective_config(cfg)
    orchestrator = DebateOrchestrator(
        anthropic_api_key=cfg.anthropic_api_key,
        confidence_threshold=cfg.signal_confidence_threshold,
        max_position_pct=eff["max_position_pct"],
        max_crypto_pct=eff["max_crypto_allocation_pct"],
        circuit_breaker_drawdown=eff["circuit_breaker_drawdown"],
        stop_loss_pct=eff["stop_loss_pct"],
        take_profit_pct=eff["take_profit_pct"],
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


# ── Dynamic risk config endpoints ─────────────────────────────────────────────

class RiskConfigUpdate(BaseModel):
    stop_loss_pct:             float | None = Field(None, ge=0.005, le=0.20)
    take_profit_pct:           float | None = Field(None, ge=0.01,  le=0.50)
    max_position_pct:          float | None = Field(None, ge=0.005, le=0.10)   # hard cap: 10% NAV
    circuit_breaker_drawdown:  float | None = Field(None, ge=0.01,  le=0.20)   # hard cap: 20% drawdown
    max_crypto_allocation_pct: float | None = Field(None, ge=0.0,   le=0.50)   # hard cap: 50% crypto


@app.get("/config")
def get_risk_config():
    """Return current effective risk config (env defaults merged with dynamic overrides)."""
    from config import get_settings
    cfg = get_settings()
    eff = _effective_config(cfg)
    return {
        **eff,
        "source": "dynamic" if _dynamic_config else "env",
        "overrides": dict(_dynamic_config),
        "defaults": {
            "stop_loss_pct":            cfg.stop_loss_pct,
            "take_profit_pct":          cfg.take_profit_pct,
            "max_position_pct":         cfg.max_position_pct,
            "circuit_breaker_drawdown": cfg.circuit_breaker_drawdown,
            "max_crypto_allocation_pct": cfg.max_crypto_allocation_pct,
        },
    }


@app.patch("/config")
def update_risk_config(body: RiskConfigUpdate):
    """Update risk config dynamically — no redeploy needed.

    Changes take effect on the next signal/monitor cycle.
    Values persist to disk and survive process restarts within the same container.
    On a full redeploy, Railway env vars re-seed the defaults.
    """
    global _dynamic_config, _services_cache
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    # Enforce hard server-side bounds regardless of Pydantic validation
    for key, val in list(updates.items()):
        if key in _CONFIG_BOUNDS:
            lo, hi = _CONFIG_BOUNDS[key]
            updates[key] = max(lo, min(hi, float(val)))
    _dynamic_config.update(updates)
    _save_dynamic_config(_dynamic_config)
    # Invalidate service singleton so DebateOrchestrator rebuilds with new values
    _services_cache = None
    log.info("Dynamic risk config updated: %s", updates)
    from config import get_settings
    return {"updated": updates, "current": _effective_config(get_settings())}


@app.delete("/config")
def reset_risk_config():
    """Reset all dynamic overrides — reverts to Railway env var defaults."""
    global _dynamic_config, _services_cache
    _dynamic_config = {}
    _save_dynamic_config({})
    _services_cache = None
    log.info("Dynamic risk config reset to env var defaults")
    from config import get_settings
    return {"reset": True, "current": _effective_config(get_settings())}


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
    req.symbol = _validate_symbol(req.symbol)
    if req.asset_class not in ("stock", "crypto"):
        raise HTTPException(400, "asset_class must be 'stock' or 'crypto'")
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
    """Place a bracket order (entry + stop-loss + take-profit) via the execution engines."""
    req.symbol = _validate_symbol(req.symbol)
    if req.asset_class not in ("stock", "crypto"):
        raise HTTPException(400, "asset_class must be 'stock' or 'crypto'")
    if req.action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="action must be BUY or SELL")
    if _TRADING_PAUSED:
        raise HTTPException(status_code=503, detail="Trading paused — POST /resume to restart")

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
            from alpaca.trading.client import TradingClient as _TC
            from data.market_data import AlpacaMarketData
            from execution.stock.engine import StockExecutionEngine

            is_paper = "paper" in cfg.alpaca_base_url.lower()

            # Pre-flight: check buying power before fetching bars or building engine
            if req.action == "BUY":
                _acct = _TC(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper).get_account()
                _bp   = float(_acct.buying_power or _acct.cash or 0)
                if _bp < 1:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Insufficient buying power (${_bp:,.2f}). "
                            "Close or take profit on existing positions to free capital."
                        ),
                    )

            # Fetch recent bars for ATR-based sizing; fall back to latest quote
            # if the bar fetch returns empty (e.g. data feed permission gap).
            market = AlpacaMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
            bars   = market.get_bars(req.symbol.upper(), days=30)
            bars_highs  = [b.high  for b in bars]
            bars_lows   = [b.low   for b in bars]
            bars_closes = [b.close for b in bars]

            if not bars_closes:
                # No historical bars — use latest quote for current price.
                # ATR sizing will fall back to fixed stop_loss_pct (correct behaviour).
                quote = market.get_latest_quote(req.symbol.upper())
                if quote and quote.mid > 0:
                    bars_closes = [quote.mid]
                    bars_highs  = [quote.ask or quote.mid]
                    bars_lows   = [quote.bid or quote.mid]
                else:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Could not fetch market price for {req.symbol.upper()} — data feed unavailable",
                    )

            eff = _effective_config(cfg)
            engine = StockExecutionEngine(
                alpaca_api_key=cfg.alpaca_api_key,
                alpaca_secret_key=cfg.alpaca_secret_key,
                alpaca_base_url=cfg.alpaca_base_url,
                max_position_pct=eff["max_position_pct"],
                circuit_breaker_drawdown=eff["circuit_breaker_drawdown"],
            )
            result = engine.execute(signal, bars_highs, bars_lows, bars_closes)

            if result is None:
                raise HTTPException(
                    status_code=409,
                    detail="Order blocked by risk controls (circuit breaker, sizing, or invalid price)",
                )

            exchange = "alpaca_paper" if is_paper else "alpaca_live"
            _write_audit(result.symbol, result.action, result.qty,
                         result.qty * result.submitted_price, "api", result.order_id)
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

            eff = _effective_config(cfg)
            engine = CryptoExecutionEngine(
                binance_api_key=cfg.binance_api_key,
                binance_secret_key=cfg.binance_secret_key,
                testnet=cfg.binance_testnet,
                max_position_pct=eff["max_position_pct"],
                max_crypto_allocation_pct=eff["max_crypto_allocation_pct"],
            )
            result = engine.execute(signal, portfolio_equity=portfolio_equity)

            if result is None:
                raise HTTPException(
                    status_code=409,
                    detail="Order blocked by risk controls (crypto cap, sizing, or invalid price)",
                )

            _write_audit(result.symbol, result.action, result.qty,
                         result.qty * result.submitted_price, "api", result.order_id)
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


@app.get("/audit")
def get_audit_log(limit: int = 50):
    """Return the last N trade audit log entries (newest first)."""
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be 1–1000")
    try:
        with open(_AUDIT_LOG) as f:
            lines = [l.strip() for l in f if l.strip()]
        entries = [json.loads(l) for l in lines]
        return list(reversed(entries[-limit:]))
    except FileNotFoundError:
        return []


if __name__ == "__main__":
    from config import get_settings
    cfg = get_settings()
    uvicorn.run("brain.api:app", host="0.0.0.0", port=cfg.brain_port, reload=False)
