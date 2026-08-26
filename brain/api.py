"""Layer 2 — Brain FastAPI service on :8000.

POST /signal   → runs the full debate and returns a TradingSignal JSON.
GET  /health   → liveness check.
GET  /signal/{symbol}/latest → last cached signal.

Heavy dependencies (pandas, ta, etc.) are imported lazily inside
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
from dataclasses import replace as _dc_replace
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

# ── Kill switch ────────────────────────────────────────────────────────────────
_TRADING_PAUSED: bool = False

# ── Service singletons ────────────────────────────────────────────────────────
# Shared data-layer services (Alpaca market data, sentiment, etc.) — one per process.
_shared_services_cache: Any = None
# Per-LLM-config DebateOrchestrators — keyed by hash of (t_provider, t_model, s_provider, s_model).
_debate_cache: dict[str, Any] = {}

# ── Encryption key (derived at startup from BRAIN_API_KEY via HKDF) ───────────
_enc_key: bytes | None = None

# ── Bar data cache (5-min TTL — avoids re-fetching 300 days on every signal) ──
_bar_cache: dict[str, tuple[Any, float]] = {}
_BAR_CACHE_TTL = 300.0  # seconds

# ── Schwab OAuth state nonces — in-memory CSRF protection ─────────────────────
# Maps state_string → (user_id, expiry_monotonic). Pruned on each new auth request.
_SCHWAB_OAUTH_STATES: dict[str, tuple[str, float]] = {}
_SCHWAB_STATE_TTL = 600.0  # 10-minute window to complete OAuth flow

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
# Float fields
_CONFIG_BOUNDS: dict[str, tuple[float, float]] = {
    # Entry / exit
    "stop_loss_pct":                (0.005, 0.20),
    "take_profit_pct":              (0.01,  0.50),
    "trailing_stop_pct":            (0.005, 0.15),
    "partial_exit_pct":             (0.10,  1.0),
    "runner_trail_pct":             (0.01,  0.30),
    # Position sizing
    "max_position_pct":             (0.005, 0.20),
    "hot_position_pct":             (0.01,  0.20),
    "max_crypto_allocation_pct":    (0.0,   0.50),
    # Portfolio exposure
    "max_exposure_pct":             (0.10,  1.0),
    # Circuit breaker / drawdown
    "circuit_breaker_drawdown":     (0.01,  0.50),
    "drawdown_scale_threshold":     (0.01,  0.30),
    "drawdown_scale_factor":        (0.50,  1.0),
    # Correlation
    "correlation_halving_threshold":(0.20,  1.0),
    # Signal quality
    "signal_confidence_threshold":  (0.30,  1.0),
    # ATR
    "atr_multiplier":               (0.5,   5.0),
    "atr_stop_floor":               (0.001, 0.05),
    "atr_stop_cap":                 (0.01,  0.20),
    # Telegram
    "max_telegram_order_usd":       (10.0,  100_000.0),
}
# Integer fields stored as float in the JSON config, cast to int when read
_CONFIG_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "max_concurrent_positions":  (1,   50),
    "lookback_days":             (30,  730),
    "loss_cooldown_hits":        (1,   10),
    "loss_cooldown_window_days": (1,   30),
    "loss_cooldown_skip_cycles": (1,   20),
}

# ── Persistent data directory ─────────────────────────────────────────────────
# Auto-detects the best writable path at import time — no manual Railway volume
# setup required. Priority: DATA_DIR env var → /data (Railway volume, if mounted)
# → /app/data (app dir, survives process restarts within same deployment) → /tmp.
def _find_data_dir() -> str:
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")),
        "/tmp",
    ]
    for _p in (p for p in candidates if p):
        try:
            os.makedirs(_p, exist_ok=True)
            _probe = os.path.join(_p, ".write_probe")
            with open(_probe, "w") as _f:
                _f.write("ok")
            os.remove(_probe)
            return _p
        except Exception:
            continue
    return "/tmp"

_DATA_DIR = _find_data_dir()
_AUDIT_LOG = os.environ.get("AUDIT_LOG_FILE", os.path.join(_DATA_DIR, "ta_audit.log"))

# ── Dynamic risk config (frontend-editable, persisted to file) ────────────────
# Overrides env-var defaults without a redeploy.
# Shape: {stop_loss_pct, take_profit_pct, max_position_pct, circuit_breaker_drawdown}
_CONFIG_FILE = os.environ.get("DYNAMIC_CONFIG_FILE", os.path.join(_DATA_DIR, "ta_dynamic_config.json"))
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
        for key, (lo, hi) in _CONFIG_INT_BOUNDS.items():
            if key in raw:
                try:
                    val = int(float(raw[key]))
                except (TypeError, ValueError):
                    continue
                if lo <= val <= hi:
                    validated[key] = val
                else:
                    log.warning("Dynamic config %s=%d out of bounds [%d, %d] — rejected", key, val, lo, hi)
        return validated
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not load dynamic config from %s: %s", _CONFIG_FILE, exc)
        return {}


def _save_dynamic_config(data: dict) -> None:
    try:
        config_dir = os.path.dirname(_CONFIG_FILE)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)
        with open(_CONFIG_FILE, "w") as f:
            json.dump(data, f)
        os.chmod(_CONFIG_FILE, 0o600)
    except Exception as exc:
        log.warning("Could not persist dynamic config: %s", exc)


def _effective_config(cfg) -> dict:
    """Merge env-var defaults with any dynamic overrides."""
    def _f(key: str, default: float) -> float:
        return float(_dynamic_config.get(key, default))
    def _i(key: str, default: int) -> int:
        return int(_dynamic_config.get(key, default))
    return {
        # Entry / exit
        "stop_loss_pct":                _f("stop_loss_pct",                cfg.stop_loss_pct),
        "take_profit_pct":              _f("take_profit_pct",              cfg.take_profit_pct),
        "trailing_stop_pct":            _f("trailing_stop_pct",            cfg.trailing_stop_pct),
        "partial_exit_pct":             _f("partial_exit_pct",             cfg.partial_exit_pct),
        "runner_trail_pct":             _f("runner_trail_pct",             cfg.runner_trail_pct),
        # Position sizing
        "max_position_pct":             _f("max_position_pct",             cfg.max_position_pct),
        "hot_position_pct":             _f("hot_position_pct",             cfg.hot_position_pct),
        "max_crypto_allocation_pct":    _f("max_crypto_allocation_pct",    cfg.max_crypto_allocation_pct),
        # Portfolio exposure
        "max_exposure_pct":             _f("max_exposure_pct",             cfg.max_exposure_pct),
        "max_concurrent_positions":     _i("max_concurrent_positions",     cfg.max_concurrent_positions),
        # Circuit breaker / drawdown
        "circuit_breaker_drawdown":     _f("circuit_breaker_drawdown",     cfg.circuit_breaker_drawdown),
        "drawdown_scale_threshold":     _f("drawdown_scale_threshold",     cfg.drawdown_scale_threshold),
        "drawdown_scale_factor":        _f("drawdown_scale_factor",        cfg.drawdown_scale_factor),
        # Correlation
        "correlation_halving_threshold":_f("correlation_halving_threshold",cfg.correlation_halving_threshold),
        # Signal quality
        "signal_confidence_threshold":  _f("signal_confidence_threshold",  cfg.signal_confidence_threshold),
        "lookback_days":                _i("lookback_days",                cfg.lookback_days),
        # ATR stop sizing
        "atr_multiplier":               _f("atr_multiplier",               cfg.atr_multiplier),
        "atr_stop_floor":               _f("atr_stop_floor",               cfg.atr_stop_floor),
        "atr_stop_cap":                 _f("atr_stop_cap",                 cfg.atr_stop_cap),
        # Loss cooldown
        "loss_cooldown_hits":           _i("loss_cooldown_hits",           cfg.loss_cooldown_hits),
        "loss_cooldown_window_days":    _i("loss_cooldown_window_days",    cfg.loss_cooldown_window_days),
        "loss_cooldown_skip_cycles":    _i("loss_cooldown_skip_cycles",    cfg.loss_cooldown_skip_cycles),
        # Telegram
        "max_telegram_order_usd":       _f("max_telegram_order_usd",       cfg.max_telegram_order_usd),
    }


_dynamic_config = _load_dynamic_config()

# ── Rationale sanitiser ───────────────────────────────────────────────────────

def _clean_rationale(text: str) -> str:
    """Strip markdown formatting from a rationale string, return one clean sentence.
    Mirrors brain/debate.py — applied here so old cached entries are cleaned on read."""
    if not text or not text.strip():
        return "Signal generated."
    t = text.strip()
    t = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", t)
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*\d+[.)]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"[\r\n]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(
        r"^(given (the|this|my) analysis[,.]?\s*"
        r"|the recommendation is \w+(\s+for \w+)?[,.]\s*"
        r"|here.?s (the|my) (trade |trading )?(decision|recommendation|signal|decision-making process)[^.]*[,.]\s*"
        r"|based on (the|this|my|our) analysis[,.]?\s*"
        r"|let.?s analyze[^.]*[,.]\s*)",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    m = re.search(r"^(.+?[.!?])(?:\s+[A-Z]|$)", t)
    first = m.group(1).strip() if m else t
    if len(first) > 180:
        first = first[:177] + "..."
    return first or "Signal generated."


# ── Persistent signal cache ────────────────────────────────────────────────────
# Survives uvicorn/process restarts AND Railway redeploys when a persistent
# volume is mounted at /data or DATA_DIR.  Falls back silently to /tmp.
_MAX_CACHE = 100   # keep the 100 most-recent unique symbols

# Optional: set OWNER_USER_ID in Railway env vars to the owner's Supabase user ID.
# When set, orchestrator signals (tagged _uid="system") are visible ONLY to the owner
# and to X-Api-Key callers. Other JWT users see only their own generated signals.
# When unset (default), all authenticated users see system signals (legacy behaviour).
_OWNER_USER_ID: str = os.environ.get("OWNER_USER_ID", "")
# Optional: set DEMO_USER_ID to a Supabase user whose session should serve
# pre-recorded snapshot data rather than live broker data.
_DEMO_USER_ID: str = os.environ.get("DEMO_USER_ID", "")


def _signal_cache_file() -> str:
    """Return the best writable path for the signal cache JSON file.

    Priority: SIGNAL_CACHE_FILE env var → DATA_DIR env var → /data → /tmp.
    Matching order_history._store_path() so both files land in the same volume.
    """
    explicit = os.environ.get("SIGNAL_CACHE_FILE", "")
    if explicit:
        return explicit
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")),
    ]
    for d in (c for c in candidates if c):
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".write_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return os.path.join(d, "ta_signal_cache.json")
        except Exception:
            continue
    return "/tmp/ta_signal_cache.json"


_CACHE_FILE = _signal_cache_file()


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
    tmp = _CACHE_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE) or ".", exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.replace(tmp, _CACHE_FILE)
        try:
            os.chmod(_CACHE_FILE, 0o600)
        except Exception:
            pass
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
    # Vote-based fields — combined 27-agent weighted pool
    vote_tally: dict = {}
    votes_for_action: float = 0.0
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
    import sys
    log.info("Brain API starting up — Python %s  cwd=%s", sys.version.split()[0], os.getcwd())

    # _DATA_DIR was resolved at import time by _find_data_dir() — log the result so it's
    # visible in Railway logs immediately and the user knows what durability level they have.
    _durability = (
        "Railway persistent volume — survives redeploys" if _DATA_DIR == "/data"
        else "app directory — survives process restarts, not redeploys" if "app" in _DATA_DIR
        else "ephemeral — data lost on any restart"
    )
    log.info("Data directory: %s (%s)", _DATA_DIR, _durability)
    log.info("Config file:    %s", _CONFIG_FILE)

    # Load dynamic config from disk at startup (picks up any pre-existing overrides)
    global _dynamic_config, _enc_key
    disk_cfg = _load_dynamic_config()
    if disk_cfg:
        _dynamic_config = disk_cfg
        log.info("Dynamic config loaded at startup: %s", list(disk_cfg.keys()))

    # Derive AES-256 encryption key for LLM credentials from BRAIN_API_KEY.
    # This is idempotent and fast — no external calls needed.
    from config import get_settings as _startup_gs
    _startup_cfg = _startup_gs()
    if _startup_cfg.brain_api_key:
        try:
            from brain.llm_creds import _derive_enc_key
            _enc_key = _derive_enc_key(_startup_cfg.brain_api_key)
            log.info("LLM credential encryption key derived (AES-256).")
        except Exception as _kexc:
            log.warning("Could not derive LLM encryption key: %s", _kexc)
    else:
        log.warning("BRAIN_API_KEY not set — LLM credential encryption unavailable.")

    # Bootstrap disclosure DB and trigger initial data fetch in background
    def _bootstrap_disclosures():
        import time
        time.sleep(5)  # let uvicorn finish binding before heavy I/O
        try:
            from brain.copy_trading import init_db
            init_db()
        except Exception as exc:
            log.warning("Disclosure DB init failed: %s", exc)
        try:
            from brain.sec_fetcher import refresh_all
            refresh_all()
            log.info("Startup 13F bootstrap complete")
        except Exception as exc:
            log.warning("Startup 13F bootstrap failed: %s", exc)
        try:
            from brain.congress_fetcher import refresh as _cr
            _cr()
            log.info("Startup congress bootstrap complete")
        except Exception as exc:
            log.warning("Startup congress bootstrap failed: %s", exc)
        try:
            from brain.track_record import ensure_track_record_config
            ensure_track_record_config()
        except Exception as exc:
            log.warning("Track record config lock failed (non-fatal): %s", exc)

    import threading as _threading
    _threading.Thread(target=_bootstrap_disclosures, daemon=True, name="disclosure-bootstrap").start()

    # On every server start, any backtest_runs row with status="running" in Supabase
    # is orphaned — its thread died in the previous container. Mark them failed now
    # so the UI stops showing them as running indefinitely.
    def _cleanup_stale_backtests():
        import time as _t
        _t.sleep(3)
        try:
            from brain.signal_snapshots import _get_sb
            sb = _get_sb()
            if sb is None:
                return
            resp = sb.table("backtest_runs").select("id,name,created_at").eq("status", "running").execute()
            stale = resp.data or []
            if stale:
                ids = [r["id"] for r in stale]
                names = [r["name"] for r in stale]
                sb.table("backtest_runs").update({
                    "status":        "failed",
                    "error_message": "Server restarted — run was interrupted and must be re-triggered",
                }).in_("id", ids).execute()
                log.warning("Startup: marked %d orphaned backtest run(s) as failed: %s", len(ids), names)
        except Exception as exc:
            log.warning("Startup backtest cleanup failed (non-fatal): %s", exc)

    _threading.Thread(target=_cleanup_stale_backtests, daemon=True, name="backtest-cleanup").start()

    yield
    log.info("Brain API shutting down.")


app = FastAPI(
    title="TradingAgent Brain",
    description="Multi-agent reasoning layer — Fundamental · Technical · Sentiment · Risk",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ── CORS: restrict to configured origins (no wildcard by default) ─────────────
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=bool(_allowed_origins),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["X-Api-Key", "Content-Type", "Authorization"],
)

# ── Rate limiting (outermost — runs first, cheapest check) ────────────────────
_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "/execute":          (5,  60),
    "/signal":           (10, 60),
    "/kill":             (5,  60),
    "/resume":           (5,  60),
    "/config":           (20, 60),
    "/llm-settings":     (20, 60),
    "/alpaca-settings":  (20, 60),
    "/risk-settings":    (20, 60),
    "/webhook-settings": (10, 60),
    "/broker-settings":       (20, 60),
    "/broker-assets":         (30, 60),
    "/tastytrade-settings":   (20, 60),
    "/polygon-settings":      (20, 60),
    "/ngx-settings":          (20, 60),
    "/fmp-settings":          (20, 60),
    "/demo/snapshot":         (5,  60),
    "/demo/snapshot-info":    (20, 60),
    "/schwab-settings":       (20, 60),
    "/schwab-auth/url":       (10, 60),
    "/ibkr-settings":         (20, 60),
    "/orders/history":        (30, 60),
    "/orders/history/export": (5,  60),
    "/orders/history/years":      (20, 60),
    "/kraken-settings":           (20, 60),
    "/coinbase-settings":         (20, 60),
    "/tradestation-settings":     (20, 60),
    "/tradestation-auth/url":     (10, 60),
}
_DEFAULT_RATE = (120, 60)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = (request.client.host if request.client else "unknown")
    # Orchestrator calls /signal and /execute from localhost — never throttle internal traffic
    if client_ip in ("127.0.0.1", "::1"):
        return await call_next(request)
    max_req, window = _RATE_LIMITS.get(request.url.path, _DEFAULT_RATE)
    # Key includes the path so each endpoint has its own per-IP counter
    rl_key = f"{client_ip}:{request.url.path}"
    if not _rate_limiter.is_allowed(rl_key, max_req, window):
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
_PUBLIC_PATHS = {"/health", "/", "/schwab-auth/callback", "/tradestation-auth/callback"}

# ── Supabase JWT validation (lazy init, cached results) ───────────────────────
_supabase_admin = None
_supabase_admin_lock = __import__("threading").Lock()
_jwt_cache: dict[str, tuple[str | None, float]] = {}   # sha256[:32] hex → (user_id, monotonic_expiry)
_JWT_CACHE_TTL = 300  # 5 min — tokens live 1 h so this is a safe cache window


def _get_supabase_admin():
    global _supabase_admin
    if _supabase_admin is None:
        with _supabase_admin_lock:
            if _supabase_admin is None:
                from config import get_settings as _gs
                _c = _gs()
                if _c.supabase_url and _c.supabase_service_role_key:
                    from supabase import create_client as _cc
                    _supabase_admin = _cc(_c.supabase_url, _c.supabase_service_role_key)
    return _supabase_admin


def _verify_supabase_jwt(token: str) -> str | None:
    """Return user_id if the Supabase JWT is valid, else None. Results cached 5 min."""
    import hashlib as _hl
    cache_key = _hl.sha256(token.encode()).hexdigest()[:32]  # collision-safe; never stores the raw token
    cached = _jwt_cache.get(cache_key)
    if cached:
        user_id, expires = cached
        if _time.monotonic() < expires:
            return user_id
    try:
        sb = _get_supabase_admin()
        if sb is None:
            return None
        resp = sb.auth.get_user(token)
        uid = resp.user.id if resp and resp.user else None
        _jwt_cache[cache_key] = (uid, _time.monotonic() + _JWT_CACHE_TTL)
        return uid
    except Exception as exc:
        log.debug("JWT validation failed: %s", exc)
        _jwt_cache[cache_key] = (None, _time.monotonic() + 60)   # cache failures 1 min to avoid hammering Supabase
        return None


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/webhook/tradingview/"):
        return await call_next(request)

    from config import get_settings
    cfg = get_settings()

    # Fail-closed: if no auth credentials are configured, reject every request.
    # A misconfigured deployment must not silently become an open API.
    if not cfg.brain_api_key and not cfg.supabase_service_role_key:
        log.critical(
            "AUTH MISCONFIGURATION: BRAIN_API_KEY and SUPABASE_SERVICE_ROLE_KEY are both unset. "
            "All non-public requests are blocked. Set BRAIN_API_KEY in Railway env vars."
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Service misconfigured — authentication credentials not set. Contact the administrator."},
        )

    # Path 1: X-Api-Key — machine-to-machine (orchestrator, Telegram bot)
    if cfg.brain_api_key and request.headers.get("X-Api-Key", "") == cfg.brain_api_key:
        return await call_next(request)

    # Path 2: Supabase Bearer token — browser users
    if cfg.supabase_service_role_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            user_id = _verify_supabase_jwt(auth_header[7:])
            if user_id:
                request.state.user_id = user_id
                return await call_next(request)

    return JSONResponse(status_code=403, content={"detail": "Forbidden — invalid or missing credentials"})


# ── Safe exception handler — never expose stack traces externally ─────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _build_shared_services(cfg):
    """Build the shared data-layer services. Called once per process."""
    from data.market_data import AlpacaMarketData, AlpacaCryptoMarketData
    from data.sentiment import SentimentFetcher
    from data.onchain import OnChainFetcher
    from data.portfolio import PortfolioFetcher
    from broker.adapters.alpaca import AlpacaBrokerAdapter

    alpaca        = AlpacaMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
    alpaca_crypto = AlpacaCryptoMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
    sentiment     = SentimentFetcher(finnhub_api_key=cfg.finnhub_api_key)
    onchain       = OnChainFetcher(eth_rpc_url=cfg.eth_rpc_url)
    sys_broker    = AlpacaBrokerAdapter(cfg.alpaca_api_key, cfg.alpaca_secret_key, cfg.alpaca_base_url)
    portfolio     = PortfolioFetcher(sys_broker)
    return alpaca, alpaca_crypto, sentiment, onchain, portfolio


def _get_shared_services(cfg):
    """Return (or lazily build) the shared data-layer service singleton."""
    global _shared_services_cache
    if _shared_services_cache is None:
        log.info("Building shared service singleton (first request this process)")
        _shared_services_cache = _build_shared_services(cfg)
    return _shared_services_cache


def _build_debate(cfg, tactical_client, synthesis_client,
                  tactical_model, synthesis_model) -> Any:
    """Build a DebateOrchestrator for the given LLM clients and models."""
    from brain.debate import DebateOrchestrator
    eff = _effective_config(cfg)
    return DebateOrchestrator(
        confidence_threshold=cfg.signal_confidence_threshold,
        max_position_pct=eff["max_position_pct"],
        max_crypto_pct=eff["max_crypto_allocation_pct"],
        circuit_breaker_drawdown=eff["circuit_breaker_drawdown"],
        stop_loss_pct=eff["stop_loss_pct"],
        take_profit_pct=eff["take_profit_pct"],
        tactical_client=tactical_client,
        synthesis_client=synthesis_client,
        tactical_model=tactical_model,
        synthesis_model=synthesis_model,
    )


def _build_debate_with_risk(cfg, effective_llm, risk_eff: dict) -> Any:
    """Build a fresh DebateOrchestrator using an already-resolved risk dict.

    Used for per-user signal requests where risk params may differ from the
    global config — these orchestrators are never cached.
    """
    from brain.debate import DebateOrchestrator
    return DebateOrchestrator(
        confidence_threshold=risk_eff.get("signal_confidence_threshold", cfg.signal_confidence_threshold),
        max_position_pct=risk_eff["max_position_pct"],
        max_crypto_pct=risk_eff["max_crypto_allocation_pct"],
        circuit_breaker_drawdown=risk_eff["circuit_breaker_drawdown"],
        stop_loss_pct=risk_eff["stop_loss_pct"],
        take_profit_pct=risk_eff["take_profit_pct"],
        tactical_client=effective_llm.tactical_client,
        synthesis_client=effective_llm.synthesis_client,
        tactical_model=effective_llm.tactical_model,
        synthesis_model=effective_llm.synthesis_model,
    )


def _debate_cache_key(t_prov: str, t_model: str, s_prov: str, s_model: str) -> str:
    import hashlib
    raw = f"{t_prov}|{t_model}|{s_prov}|{s_model}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_debate(cfg, effective_llm) -> Any:
    """Return (or lazily build) a DebateOrchestrator for the given LLM config."""
    key = _debate_cache_key(
        effective_llm.tactical_provider, effective_llm.tactical_model,
        effective_llm.synthesis_provider, effective_llm.synthesis_model,
    )
    if key not in _debate_cache:
        log.info("Building DebateOrchestrator for config %s (%s/%s + %s/%s)",
                 key, effective_llm.tactical_provider, effective_llm.tactical_model,
                 effective_llm.synthesis_provider, effective_llm.synthesis_model)
        _debate_cache[key] = _build_debate(
            cfg,
            effective_llm.tactical_client,
            effective_llm.synthesis_client,
            effective_llm.tactical_model,
            effective_llm.synthesis_model,
        )
    return _debate_cache[key]


# ── Encryption key accessor ───────────────────────────────────────────────────

def _get_enc_key() -> bytes:
    """Return the AES-256 encryption key, deriving it lazily if needed."""
    global _enc_key
    if _enc_key is not None:
        return _enc_key
    from config import get_settings as _gs
    _secret = _gs().brain_api_key
    if not _secret:
        raise HTTPException(
            status_code=503,
            detail="LLM credential encryption not available — BRAIN_API_KEY is not set.",
        )
    from brain.llm_creds import _derive_enc_key
    _enc_key = _derive_enc_key(_secret)
    return _enc_key


def _resolve_alpaca_creds(user_id: str | None, cfg) -> tuple[str, str, str, bool]:
    """Return (api_key, secret_key, base_url, is_paper) for the given user.

    user_id = None  (orchestrator / X-Api-Key) → always system credentials.
    user_id = str   (JWT browser user)          → per-user if configured, else system.
    """
    if user_id:
        try:
            enc_key = _get_enc_key()
            from brain.alpaca_creds import get_effective_alpaca_creds
            creds = get_effective_alpaca_creds(user_id, enc_key, cfg)
            return creds.api_key, creds.secret_key, creds.alpaca_base_url, creds.is_paper
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("Could not resolve per-user Alpaca creds for %s: %s", user_id, exc)
    return (
        cfg.alpaca_api_key or "",
        cfg.alpaca_secret_key or "",
        cfg.alpaca_base_url or "https://paper-api.alpaca.markets",
        "paper" in (cfg.alpaca_base_url or "").lower(),
    )


def _jwt_user_has_own_alpaca(user_id: str, cfg) -> bool:
    """Return True only if this JWT user has their own Alpaca API key stored.

    Used to prevent JWT users from silently falling through to the system
    account (the owner's Alpaca) when they have no personal credentials.
    """
    try:
        enc_key = _get_enc_key()
        from brain.alpaca_creds import get_effective_alpaca_creds
        return not get_effective_alpaca_creds(user_id, enc_key, cfg).using_system_keys
    except Exception:
        return False


def _resolve_broker(user_id: str | None, cfg):
    """Return a BrokerAdapter for the given user.

    Orchestrator (user_id=None) always receives system Alpaca creds.
    JWT users get the broker they selected in /broker-settings, defaulting to Alpaca.
    Raises HTTPException 503 for unimplemented brokers, 400 if tastytrade creds missing.
    """
    broker_type = "alpaca"
    if user_id:
        from brain.broker_creds import load_user_broker_type, LIVE_BROKERS
        broker_type = load_user_broker_type(user_id) or "alpaca"
        if broker_type not in LIVE_BROKERS:
            raise HTTPException(503, f"Broker '{broker_type}' is not yet supported — switch to Alpaca")

    if broker_type == "tastytrade":
        enc_key = _get_enc_key()
        from brain.tastytrade_creds import get_effective_tastytrade_creds
        creds = get_effective_tastytrade_creds(user_id, enc_key)
        if not creds.keys_configured:
            raise HTTPException(400, "tastytrade credentials not configured — save them in Settings → tastytrade Account")
        from broker.adapters.tastytrade import TastytradeBrokerAdapter
        return TastytradeBrokerAdapter(
            username=creds.username,
            password=creds.password,
            account_number=creds.account_number,
            paper=creds.paper_mode,
        )

    if broker_type == "schwab":
        enc_key = _get_enc_key()
        from brain.schwab_creds import load_schwab_tokens, update_schwab_access_token
        tokens = load_schwab_tokens(user_id, enc_key)
        if tokens is None or not tokens.configured:
            raise HTTPException(400, "Schwab account not connected — go to Settings → Charles Schwab and click Connect")
        if tokens.refresh_expired:
            raise HTTPException(401, "Schwab refresh token expired — reconnect your account in Settings → Charles Schwab")

        # Pre-flight: refresh access token if it expires within the next 2 minutes
        if tokens.access_expired or (_time.time() + 120 >= tokens.access_token_exp):
            tokens = _schwab_refresh_access_token(user_id, cfg, enc_key, tokens.refresh_token)

        from broker.adapters.schwab import SchwabBrokerAdapter
        return SchwabBrokerAdapter(
            access_token=tokens.access_token,
            account_hash=tokens.account_hash or None,
        )

    if broker_type == "ibkr":
        from brain.ibkr_creds import load_ibkr_settings
        s = load_ibkr_settings(user_id)
        if not s.configured:
            raise HTTPException(400, "IB Gateway not configured — enter your IB Gateway host and port in Settings → Interactive Brokers")
        from broker.adapters.ibkr import IBKRBrokerAdapter
        return IBKRBrokerAdapter(
            host=s.host,
            port=s.port,
            client_id=s.client_id,
            account_id=s.account_id,
            paper=s.paper_mode,
        )

    if broker_type == "kraken":
        enc_key = _get_enc_key()
        from brain.kraken_creds import get_effective_kraken_creds
        creds = get_effective_kraken_creds(user_id, enc_key)
        if not creds.configured:
            raise HTTPException(400, "Kraken API credentials not configured — save them in Settings → Kraken")
        from broker.adapters.kraken import KrakenBrokerAdapter
        return KrakenBrokerAdapter(creds.api_key, creds.api_secret)

    if broker_type == "coinbase":
        enc_key = _get_enc_key()
        from brain.coinbase_creds import get_effective_coinbase_creds
        creds = get_effective_coinbase_creds(user_id, enc_key)
        if not creds.configured:
            raise HTTPException(400, "Coinbase credentials not configured — save them in Settings → Coinbase Advanced Trade")
        from broker.adapters.coinbase import CoinbaseBrokerAdapter
        return CoinbaseBrokerAdapter(creds.api_key_name, creds.private_key)

    if broker_type == "tradestation":
        enc_key = _get_enc_key()
        from brain.tradestation_creds import load_ts_tokens
        tokens = load_ts_tokens(user_id, enc_key)
        if tokens is None or not tokens.configured:
            raise HTTPException(400, "TradeStation not connected — go to Settings → TradeStation and click Connect")
        if tokens.refresh_expired:
            raise HTTPException(401, "TradeStation refresh token expired — reconnect in Settings → TradeStation")
        if tokens.access_expired or (_time.time() + 120 >= tokens.access_token_exp):
            tokens = _ts_refresh_access_token(user_id, cfg, enc_key, tokens.refresh_token)
        from broker.adapters.tradestation import TradeStationBrokerAdapter
        return TradeStationBrokerAdapter(tokens.access_token, tokens.account_number, tokens.paper_mode)

    # Default path: Alpaca
    ak, sk, base_url, _ = _resolve_alpaca_creds(user_id, cfg)
    from broker.adapters.alpaca import AlpacaBrokerAdapter
    return AlpacaBrokerAdapter(ak, sk, base_url)


def _schwab_refresh_access_token(user_id: str, cfg, enc_key: bytes, refresh_token: str):
    """Exchange a refresh token for a new Schwab access token.

    Persists the new token to the cred store and returns an updated
    EffectiveSchwabTokens. Raises HTTPException 401 if the refresh fails.
    """
    import base64
    import httpx as _httpx
    from brain.schwab_creds import update_schwab_access_token, load_schwab_tokens

    app_key    = getattr(cfg, "schwab_app_key",    "") or os.environ.get("SCHWAB_APP_KEY",    "")
    app_secret = getattr(cfg, "schwab_app_secret", "") or os.environ.get("SCHWAB_APP_SECRET", "")
    if not app_key or not app_secret:
        raise HTTPException(503, "Schwab app credentials not configured — set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in Railway")

    credentials = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    try:
        resp = _httpx.post(
            "https://api.schwabapi.com/v1/oauth/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        log.warning("Schwab token refresh failed for user %s: %s", user_id[:8], exc)
        raise HTTPException(401, "Schwab session expired — reconnect your account in Settings → Charles Schwab")

    new_access  = token_data.get("access_token", "")
    expires_in  = int(token_data.get("expires_in", 1800))
    new_exp     = _time.time() + expires_in

    # Also update refresh token if Schwab rotated it
    new_refresh = token_data.get("refresh_token", "")
    if new_refresh and new_refresh != refresh_token:
        from brain.schwab_creds import save_schwab_tokens, load_schwab_tokens as _lst
        existing = _lst(user_id, enc_key)
        refresh_exp = existing.refresh_token_exp if existing else (_time.time() + 7 * 86400)
        save_schwab_tokens(
            user_id, enc_key,
            access_token=new_access,
            refresh_token=new_refresh,
            access_token_exp=new_exp,
            refresh_token_exp=refresh_exp,
            account_hash=existing.account_hash if existing else "",
        )
    else:
        update_schwab_access_token(user_id, enc_key, new_access, new_exp)

    return load_schwab_tokens(user_id, enc_key)


def _ts_refresh_access_token(user_id: str, cfg, enc_key: bytes, refresh_token: str):
    """Exchange a TradeStation refresh token for a new access token."""
    import httpx as _httpx
    from brain.tradestation_creds import update_ts_access_token, load_ts_tokens

    client_id     = getattr(cfg, "tradestation_client_id",     "") or os.environ.get("TRADESTATION_CLIENT_ID",     "")
    client_secret = getattr(cfg, "tradestation_client_secret", "") or os.environ.get("TRADESTATION_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(503, "TradeStation app credentials not configured — set TRADESTATION_CLIENT_ID and TRADESTATION_CLIENT_SECRET in Railway")

    try:
        resp = _httpx.post(
            "https://signin.tradestation.com/oauth/token",
            data={
                "grant_type":    "refresh_token",
                "client_id":     client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        log.warning("TradeStation token refresh failed for %s: %s", user_id[:8], exc)
        raise HTTPException(401, "TradeStation session expired — reconnect your account in Settings → TradeStation")

    new_access = token_data.get("access_token", "")
    expires_in = int(token_data.get("expires_in", 1200))  # TS access tokens = 20 min
    new_exp    = _time.time() + expires_in
    update_ts_access_token(user_id, enc_key, new_access, new_exp)
    return load_ts_tokens(user_id, enc_key)


# ── TradeStation OAuth state nonces (in-memory, TTL 10 min) ──────────────────
_TS_OAUTH_STATES: dict[str, tuple[str, float]] = {}  # state → (user_id, exp)
_TS_STATE_TTL = 600.0


class AlpacaSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_mode:  bool = True
    api_key:     str  = ""    # plaintext; empty = "don't change stored key"
    secret_key:  str  = ""    # plaintext; empty = "don't change stored key"


class BrokerSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    broker_type: str


class TastytradeSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username:       str  = ""   # plaintext; empty = "don't change"
    password:       str  = ""   # plaintext; empty = "don't change stored password"
    account_number: str  = ""   # optional; empty = "use first account"
    paper_mode:     bool = True


class PolygonSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = ""   # plaintext; empty = "don't change stored key"


class NgxSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str   # plaintext NGX Pulse API key


class IBKRSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host:       str  = "127.0.0.1"
    port:       int  = 4002          # 4001 = live, 4002 = paper
    client_id:  int  = 1             # unique per simultaneous connection to the same gateway
    account_id: str  = ""            # IBKR account ID; empty = auto-detected
    paper_mode: bool = True


def _get_market_snapshot(fetcher, symbol: str, days: int):
    """Return a cached bar snapshot (TTL %ds) to avoid re-fetching on every signal.

    Cache key includes the fetcher type so Alpaca and Polygon snapshots are stored
    separately — prevents stale Alpaca bars from being served when a user switches
    to Polygon mid-session.
    """
    source = type(fetcher).__name__
    key = f"{source}:{symbol}:{days}"
    now = _time.monotonic()
    if key in _bar_cache:
        snap, ts = _bar_cache[key]
        if now - ts < _BAR_CACHE_TTL:
            log.debug("Bar cache hit [%s] for %s (%ds)", source, symbol, days)
            return snap
    snap = fetcher.snapshot(symbol, days)
    _bar_cache[key] = (snap, now)
    return snap


def _resolve_stock_data(user_id: str | None, cfg, fallback):
    """Return the best stock market data client for this request.

    Priority:
      1. Per-user Polygon key (JWT user with key stored)
      2. System POLYGON_API_KEY env var / config
      3. fallback (the system AlpacaMarketData passed in from shared services)
    """
    polygon_key = None
    if user_id:
        try:
            enc_key = _get_enc_key()
            from brain.polygon_creds import get_effective_polygon_key
            polygon_key = get_effective_polygon_key(user_id, enc_key, cfg)
        except Exception as exc:
            log.debug("Polygon key resolution failed for user %s: %s", user_id, exc)
    if not polygon_key:
        polygon_key = getattr(cfg, "polygon_api_key", "") or None
    if polygon_key:
        from data.polygon_data import PolygonMarketData
        log.debug("Using Polygon.io for %s market data", "per-user" if user_id else "system")
        return PolygonMarketData(polygon_key)
    return fallback


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
def kill_switch(request: Request):
    """Emergency halt — stops all new trade execution immediately. Owner or M2M (X-Api-Key) only."""
    uid = getattr(request.state, "user_id", None)
    if _OWNER_USER_ID and uid and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Owner access required to activate kill switch")
    global _TRADING_PAUSED
    _TRADING_PAUSED = True
    log.critical("KILL SWITCH ACTIVATED — auto-trading paused by uid=%s", uid or "M2M")
    return {"status": "paused", "message": "Auto-trading halted. POST /resume to restart."}


@app.post("/resume")
def resume_trading(request: Request):
    """Resume trading after a kill switch. Owner or M2M (X-Api-Key) only."""
    uid = getattr(request.state, "user_id", None)
    if _OWNER_USER_ID and uid and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Owner access required to resume trading")
    global _TRADING_PAUSED
    _TRADING_PAUSED = False
    log.info("Auto-trading resumed via /resume by uid=%s", uid or "M2M")
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
    model_config = ConfigDict(extra="ignore")  # silently drop source/overrides/defaults sent by frontend
    # Entry / exit
    stop_loss_pct:                  float | None = Field(None, ge=0.005, le=0.20)
    take_profit_pct:                float | None = Field(None, ge=0.01,  le=0.50)
    trailing_stop_pct:              float | None = Field(None, ge=0.005, le=0.15)
    partial_exit_pct:               float | None = Field(None, ge=0.10,  le=1.0)
    runner_trail_pct:               float | None = Field(None, ge=0.01,  le=0.30)
    # Position sizing
    max_position_pct:               float | None = Field(None, ge=0.005, le=0.20)
    hot_position_pct:               float | None = Field(None, ge=0.01,  le=0.20)
    max_crypto_allocation_pct:      float | None = Field(None, ge=0.0,   le=0.50)
    # Portfolio exposure
    max_exposure_pct:               float | None = Field(None, ge=0.10,  le=1.0)
    max_concurrent_positions:       int   | None = Field(None, ge=1,     le=50)
    # Circuit breaker / drawdown
    circuit_breaker_drawdown:       float | None = Field(None, ge=0.01,  le=0.50)
    drawdown_scale_threshold:       float | None = Field(None, ge=0.01,  le=0.30)
    drawdown_scale_factor:          float | None = Field(None, ge=0.50,  le=1.0)
    # Correlation
    correlation_halving_threshold:  float | None = Field(None, ge=0.20,  le=1.0)
    # Signal quality
    signal_confidence_threshold:    float | None = Field(None, ge=0.30,  le=1.0)
    lookback_days:                  int   | None = Field(None, ge=30,    le=730)
    # ATR stop sizing
    atr_multiplier:                 float | None = Field(None, ge=0.5,   le=5.0)
    atr_stop_floor:                 float | None = Field(None, ge=0.001, le=0.05)
    atr_stop_cap:                   float | None = Field(None, ge=0.01,  le=0.20)
    # Loss cooldown
    loss_cooldown_hits:             int   | None = Field(None, ge=1,     le=10)
    loss_cooldown_window_days:      int   | None = Field(None, ge=1,     le=30)
    loss_cooldown_skip_cycles:      int   | None = Field(None, ge=1,     le=20)
    # Telegram
    max_telegram_order_usd:         float | None = Field(None, ge=10.0,  le=100_000.0)
    # Brain watch rules
    max_watch_rules:                int   | None = Field(None, ge=1,     le=50)


@app.get("/config")
def get_risk_config(request: Request):
    """Return current effective risk config (env defaults merged with dynamic overrides).

    Orchestrator (X-Api-Key, user_id=None): always returns the global config — unchanged.
    Browser user (JWT, user_id=str): returns global config merged with per-user overrides.
    """
    from config import get_settings
    global _dynamic_config
    cfg = get_settings()
    # Always reload from disk so a PATCH to any worker is immediately visible here.
    disk = _load_dynamic_config()
    if disk:
        _dynamic_config = disk
    base_eff = _effective_config(cfg)

    defaults = {
        "stop_loss_pct":                cfg.stop_loss_pct,
        "take_profit_pct":              cfg.take_profit_pct,
        "trailing_stop_pct":            cfg.trailing_stop_pct,
        "partial_exit_pct":             cfg.partial_exit_pct,
        "runner_trail_pct":             cfg.runner_trail_pct,
        "max_position_pct":             cfg.max_position_pct,
        "hot_position_pct":             cfg.hot_position_pct,
        "max_crypto_allocation_pct":    cfg.max_crypto_allocation_pct,
        "max_exposure_pct":             cfg.max_exposure_pct,
        "max_concurrent_positions":     cfg.max_concurrent_positions,
        "circuit_breaker_drawdown":     cfg.circuit_breaker_drawdown,
        "drawdown_scale_threshold":     cfg.drawdown_scale_threshold,
        "drawdown_scale_factor":        cfg.drawdown_scale_factor,
        "correlation_halving_threshold":cfg.correlation_halving_threshold,
        "signal_confidence_threshold":  cfg.signal_confidence_threshold,
        "lookback_days":                cfg.lookback_days,
        "atr_multiplier":               cfg.atr_multiplier,
        "atr_stop_floor":               cfg.atr_stop_floor,
        "atr_stop_cap":                 cfg.atr_stop_cap,
        "loss_cooldown_hits":           cfg.loss_cooldown_hits,
        "loss_cooldown_window_days":    cfg.loss_cooldown_window_days,
        "loss_cooldown_skip_cycles":    cfg.loss_cooldown_skip_cycles,
        "max_telegram_order_usd":       cfg.max_telegram_order_usd,
        "max_watch_rules":              _dynamic_config.get("max_watch_rules", 10),
    }

    user_id: str | None = getattr(request.state, "user_id", None)
    if user_id:
        from brain.risk_config import get_effective_risk_for_user, load_user_risk_config
        eff = get_effective_risk_for_user(user_id, base_eff)
        user_overrides = load_user_risk_config(user_id)
        _cfg_is_owner = (not _OWNER_USER_ID) or (_OWNER_USER_ID and user_id == _OWNER_USER_ID)
        return {
            **eff,
            "source": "user" if user_overrides else ("dynamic" if _dynamic_config else "env"),
            "overrides": dict(_dynamic_config) if _cfg_is_owner else {},
            "user_overrides": user_overrides,
            "defaults": defaults,
        }

    return {
        **base_eff,
        "source": "dynamic" if _dynamic_config else "env",
        "overrides": dict(_dynamic_config),
        "defaults": defaults,
    }


@app.patch("/config")
def update_risk_config(body: RiskConfigUpdate, request: Request):
    """Update risk config dynamically — no redeploy needed.

    Orchestrator (X-Api-Key, user_id=None): updates global config + clears caches.
    Browser user (JWT, user_id=str): updates only the user's per-user overrides.
      Per-user PATCH never touches _dynamic_config and never clears caches.
    """
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    # Enforce hard server-side bounds regardless of Pydantic validation
    for key, val in list(updates.items()):
        if key in _CONFIG_BOUNDS:
            lo, hi = _CONFIG_BOUNDS[key]
            updates[key] = max(lo, min(hi, float(val)))
        elif key in _CONFIG_INT_BOUNDS:
            lo, hi = _CONFIG_INT_BOUNDS[key]
            updates[key] = max(lo, min(hi, int(val)))

    user_id: str | None = getattr(request.state, "user_id", None)
    from config import get_settings
    cfg = get_settings()

    if user_id:
        # Per-user: write to user_risk_config.json only — never touch global state or caches
        from brain.risk_config import save_user_risk_config, get_effective_risk_for_user
        save_user_risk_config(user_id, updates)
        log.info("Per-user risk config updated for %s: %s", user_id, updates)
        base_eff = _effective_config(cfg)
        user_eff = get_effective_risk_for_user(user_id, base_eff)
        return {"updated": updates, "current": user_eff}

    # Global: identical to pre-Phase-3 behaviour
    global _dynamic_config, _shared_services_cache, _debate_cache
    _dynamic_config.update(updates)
    _save_dynamic_config(_dynamic_config)
    _shared_services_cache = None
    _debate_cache.clear()
    log.info("Dynamic risk config updated: %s", updates)
    return {"updated": updates, "current": _effective_config(cfg)}


@app.delete("/config")
def reset_risk_config(request: Request):
    """Reset dynamic overrides.

    Orchestrator (X-Api-Key, user_id=None): resets global config + clears caches.
    Browser user (JWT, user_id=str): removes only the user's per-user overrides.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    from config import get_settings

    if user_id:
        from brain.risk_config import delete_user_risk_config
        delete_user_risk_config(user_id)
        log.info("Per-user risk config reset for %s", user_id)
        return {"reset": True, "current": _effective_config(get_settings())}

    global _dynamic_config, _shared_services_cache, _debate_cache
    _dynamic_config = {}
    _save_dynamic_config({})
    _shared_services_cache = None
    _debate_cache.clear()
    log.info("Dynamic risk config reset to env var defaults")
    return {"reset": True, "current": _effective_config(get_settings())}


@app.get("/config-status")
def config_status(request: Request):
    """Returns which API keys are configured (true/false only — never exposes values)
    plus runtime metadata so the frontend never needs to hardcode facts about the engine."""
    from config import get_settings
    from watchlist import (
        STOCK_WATCHLIST, ETF_WATCHLIST, CRYPTO_WATCHLIST,
        HOT_MIN_VOTES, WARM_MIN_VOTES, AGENT_COUNT,
        CYCLE_INTERVAL_MINUTES, LLM_PROVIDER_NAME, LLM_PROVIDER_URL,
        PROVIDER_DISPLAY, PROVIDER_BILLING_URLS,
    )
    cfg = get_settings()
    system_llm_ok = bool(cfg.openrouter_api_key)
    alpaca_ok = bool(cfg.alpaca_api_key and cfg.alpaca_secret_key)

    # Check if this browser user has their own LLM config
    user_id: str | None = getattr(request.state, "user_id", None)
    user_llm_provider = "openrouter"
    user_llm_name = LLM_PROVIDER_NAME
    user_llm_url  = LLM_PROVIDER_URL
    user_llm_ok   = system_llm_ok
    if user_id:
        try:
            from brain.llm_creds import load_user_settings, get_keys_configured
            _us = load_user_settings(user_id)
            _configured = get_keys_configured(user_id)
            if _configured:
                user_llm_provider = _us.tactical_provider
                user_llm_name = PROVIDER_DISPLAY.get(_us.tactical_provider, _us.tactical_provider)
                user_llm_url  = PROVIDER_BILLING_URLS.get(_us.tactical_provider, "")
                user_llm_ok   = _us.tactical_provider in _configured
        except Exception:
            pass

    return {
        # Key presence (boolean only — values never exposed)
        "llm_provider":    user_llm_ok,
        "llm_provider_name": user_llm_name,
        "llm_provider_url":  user_llm_url,
        "llm_env_var":     "OPENROUTER_API_KEY",
        "alpaca":          alpaca_ok,
        "binance":         bool(cfg.binance_api_key and cfg.binance_secret_key),
        "telegram":        bool(cfg.telegram_bot_token),
        "alpaca_base_url": cfg.alpaca_base_url,
        "binance_testnet": cfg.binance_testnet,
        "auto_trade":      os.environ.get("AUTO_TRADE", "true").lower() != "false",
        "ready_for_signals":  user_llm_ok,
        "ready_for_trading":  user_llm_ok and alpaca_ok,
        # Engine metadata — used by the dashboard instead of hardcoded values
        "agent_count":            AGENT_COUNT,
        "hot_min_votes":          HOT_MIN_VOTES,
        "warm_min_votes":         WARM_MIN_VOTES,
        "cycle_interval_minutes": CYCLE_INTERVAL_MINUTES,
        "watchlist_stocks":       STOCK_WATCHLIST,
        "watchlist_etfs":         ETF_WATCHLIST,
        "watchlist_crypto":       CRYPTO_WATCHLIST,
        "total_symbols":          len(STOCK_WATCHLIST) + len(ETF_WATCHLIST) + len(CRYPTO_WATCHLIST),
    }


# ── LLM provider / model catalogue ────────────────────────────────────────────

@app.get("/models")
def list_models():
    """Return the curated model list for each provider.
    Also returns provider display names and confidence notes for Kimi and Qwen."""
    from watchlist import PROVIDER_MODELS, PROVIDER_DISPLAY
    return {
        "providers": PROVIDER_DISPLAY,
        "models": PROVIDER_MODELS,
        "confidence_notes": {
            "qwen": "Endpoint confidence 92% — verify the base URL before use.",
            "kimi": "Endpoint confidence 90% — verify the base URL before use.",
        },
    }


# ── Per-user LLM settings ──────────────────────────────────────────────────────

class _LLMSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tactical_provider:  str = "openrouter"
    tactical_model:     str = "google/gemini-2.5-flash-lite"
    synthesis_provider: str = "openrouter"
    synthesis_model:    str = "deepseek/deepseek-chat-v3-0324"
    # API keys — only sent when the user is updating a key.
    # Empty string = "don't change the stored key for this provider."
    openrouter_key: str = ""
    anthropic_key:  str = ""
    openai_key:     str = ""
    deepseek_key:   str = ""
    xai_key:        str = ""
    qwen_key:       str = ""
    kimi_key:       str = ""


@app.get("/llm-settings")
def get_llm_settings(request: Request):
    """Return the user's LLM settings (key presence only — values never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for LLM settings.")
    from brain.llm_creds import load_user_settings, get_keys_configured
    settings = load_user_settings(user_id)
    keys_configured = get_keys_configured(user_id)
    return {
        "tactical_provider":  settings.tactical_provider,
        "tactical_model":     settings.tactical_model,
        "synthesis_provider": settings.synthesis_provider,
        "synthesis_model":    settings.synthesis_model,
        "keys_configured":    keys_configured,
    }


@app.post("/llm-settings")
def save_llm_settings(req: _LLMSettingsWrite, request: Request):
    """Save the user's LLM provider, model, and API key selections.

    Keys are write-only: once saved they are encrypted at rest and never returned.
    Only send a key field when the user is explicitly updating it.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for LLM settings.")

    from watchlist import PROVIDER_BASE_URLS
    if req.tactical_provider not in PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail=f"Unknown tactical provider: {req.tactical_provider}")
    if req.synthesis_provider not in PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail=f"Unknown synthesis provider: {req.synthesis_provider}")

    enc_key = _get_enc_key()

    new_keys = {
        "openrouter": req.openrouter_key,
        "anthropic":  req.anthropic_key,
        "openai":     req.openai_key,
        "deepseek":   req.deepseek_key,
        "xai":        req.xai_key,
        "qwen":       req.qwen_key,
        "kimi":       req.kimi_key,
    }

    from brain.llm_creds import save_user_settings, get_keys_configured
    save_user_settings(
        user_id=user_id,
        tactical_provider=req.tactical_provider,
        tactical_model=req.tactical_model,
        synthesis_provider=req.synthesis_provider,
        synthesis_model=req.synthesis_model,
        new_api_keys={k: v for k, v in new_keys.items() if v},
        enc_key=enc_key,
    )
    # Invalidate any cached DebateOrchestrator for this LLM config so the next
    # signal request builds a fresh one with the new key/model.
    _debate_cache.clear()
    log.info("LLM settings saved for user %s (providers: %s / %s)",
             user_id, req.tactical_provider, req.synthesis_provider)
    return {
        "saved": True,
        "keys_configured": get_keys_configured(user_id),
    }


@app.get("/alpaca-settings")
def get_alpaca_settings(request: Request):
    """Return the current user's Alpaca configuration (presence only — keys never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Alpaca settings")
    from brain.alpaca_creds import load_user_alpaca_settings
    settings = load_user_alpaca_settings(user_id)
    return {
        "paper_mode":     settings.paper_mode,
        "keys_configured": bool(settings.api_key_enc and settings.secret_key_enc),
    }


@app.post("/alpaca-settings")
def save_alpaca_settings_endpoint(req: AlpacaSettingsPayload, request: Request):
    """Save the current user's Alpaca credentials (encrypted at rest, never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Alpaca settings")
    enc_key = _get_enc_key()
    from brain.alpaca_creds import save_user_alpaca_settings, load_user_alpaca_settings
    save_user_alpaca_settings(
        user_id=user_id,
        paper_mode=req.paper_mode,
        new_api_key=req.api_key,
        new_secret_key=req.secret_key,
        enc_key=enc_key,
    )
    settings = load_user_alpaca_settings(user_id)
    log.info("Alpaca settings saved for user %s (paper=%s)", user_id, req.paper_mode)
    return {
        "saved": True,
        "keys_configured": bool(settings.api_key_enc and settings.secret_key_enc),
    }


@app.get("/broker-settings")
def get_broker_settings(request: Request):
    """Return the broker catalog and the user's current broker selection."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for broker settings")
    from brain.broker_creds import BROKER_CATALOG, DEFAULT_BROKER, load_user_broker_type
    current = load_user_broker_type(user_id) or DEFAULT_BROKER
    return {
        "current_broker":    current,
        "available_brokers": BROKER_CATALOG,
    }


@app.post("/broker-settings")
def save_broker_settings(req: BrokerSettingsPayload, request: Request):
    """Save the user's broker selection. Only brokers with status='live' are accepted."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for broker settings")
    from brain.broker_creds import BROKER_CATALOG, LIVE_BROKERS, save_user_broker_type
    valid_ids = {b["id"] for b in BROKER_CATALOG}
    if req.broker_type not in valid_ids:
        raise HTTPException(400, f"Unknown broker '{req.broker_type}'")
    if req.broker_type not in LIVE_BROKERS:
        raise HTTPException(400, f"Broker '{req.broker_type}' is not yet available — stay tuned")
    save_user_broker_type(user_id, req.broker_type)
    log.info("Broker preference updated for user %s: %s", user_id[:8], req.broker_type)
    return {"saved": True, "broker_type": req.broker_type}


@app.delete("/broker-settings")
def reset_broker_settings(request: Request):
    """Reset the user's broker selection to the system default (Alpaca)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for broker settings")
    from brain.broker_creds import DEFAULT_BROKER, delete_user_broker_type
    existed = delete_user_broker_type(user_id)
    return {"reset": True, "broker_type": DEFAULT_BROKER, "had_preference": existed}


@app.get("/broker-assets")
def get_broker_assets(request: Request):
    """Return which asset-class tabs are available for the authenticated user's broker.

    Unauthenticated callers receive the default (Alpaca) tab set.
    """
    uid: str | None = getattr(request.state, "user_id", None)
    from brain.broker_creds import DEFAULT_BROKER, load_user_broker_type, get_broker_asset_tabs
    broker = (load_user_broker_type(uid) or DEFAULT_BROKER) if uid else DEFAULT_BROKER
    return {"broker": broker, "tabs": get_broker_asset_tabs(broker)}


@app.get("/tastytrade-settings")
def get_tastytrade_settings(request: Request):
    """Return the current user's tastytrade configuration (password never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for tastytrade settings")
    from brain.tastytrade_creds import load_user_tastytrade_settings
    s = load_user_tastytrade_settings(user_id)
    return {
        "username":         s.username or "",
        "account_number":   s.account_number or "",
        "paper_mode":       s.paper_mode,
        "keys_configured":  bool(s.username and s.password_enc),
    }


@app.post("/tastytrade-settings")
def save_tastytrade_settings(req: TastytradeSettingsPayload, request: Request):
    """Save the current user's tastytrade credentials (password encrypted at rest, never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for tastytrade settings")
    enc_key = _get_enc_key()
    from brain.tastytrade_creds import save_user_tastytrade_settings, load_user_tastytrade_settings
    save_user_tastytrade_settings(
        user_id=user_id,
        username=req.username,
        new_password=req.password,
        account_number=req.account_number,
        paper_mode=req.paper_mode,
        enc_key=enc_key,
    )
    s = load_user_tastytrade_settings(user_id)
    log.info("tastytrade settings saved for user %s (paper=%s)", user_id[:8], req.paper_mode)
    return {
        "saved":           True,
        "keys_configured": bool(s.username and s.password_enc),
    }


@app.get("/polygon-settings")
def get_polygon_settings(request: Request):
    """Return the user's Polygon.io configuration (key presence only — value never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Polygon settings")
    from brain.polygon_creds import load_user_polygon_settings
    from config import get_settings
    s   = load_user_polygon_settings(user_id)
    cfg = get_settings()
    return {
        "user_key_configured":   bool(s.api_key_enc),
        "system_key_configured": bool(getattr(cfg, "polygon_api_key", "")),
        "effective_source":      (
            "user"   if s.api_key_enc
            else "system" if getattr(cfg, "polygon_api_key", "")
            else "none"
        ),
    }


@app.post("/polygon-settings")
def save_polygon_settings(req: PolygonSettingsPayload, request: Request):
    """Save the user's Polygon API key (encrypted at rest, never returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Polygon settings")
    if not req.api_key:
        raise HTTPException(400, "api_key is required")
    enc_key = _get_enc_key()
    from brain.polygon_creds import save_user_polygon_key
    save_user_polygon_key(user_id, req.api_key, enc_key)
    log.info("Polygon API key saved for user %s", user_id[:8])
    return {"saved": True, "user_key_configured": True}


@app.delete("/polygon-settings")
def delete_polygon_settings(request: Request):
    """Remove the user's Polygon API key (reverts to system key or Alpaca fallback)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Polygon settings")
    from brain.polygon_creds import delete_user_polygon_key
    existed = delete_user_polygon_key(user_id)
    return {"deleted": True, "had_key": existed}


# ── NGX Pulse market data endpoints ───────────────────────────────────────────

@app.get("/ngx-settings")
def get_ngx_settings(request: Request):
    """Return NGX Pulse API key configuration (no key values)."""
    enc_key = None
    try:
        enc_key = _get_enc_key()
    except Exception:
        pass
    from brain.ngx_creds import get_ngx_pulse_settings_info
    return get_ngx_pulse_settings_info(enc_key)


@app.post("/ngx-settings")
def save_ngx_settings(req: NgxSettingsPayload, request: Request):
    """Store the NGX Pulse API key (encrypted). Owner-only."""
    uid: str | None = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(403, "Authentication required")
    if _OWNER_USER_ID and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Only the account owner can configure market data keys")
    if not req.api_key.strip():
        raise HTTPException(400, "api_key must not be blank")
    enc_key = _get_enc_key()
    from brain.ngx_creds import save_ngx_pulse_key
    save_ngx_pulse_key(req.api_key.strip(), enc_key)
    return {"saved": True}


@app.delete("/ngx-settings")
def delete_ngx_settings(request: Request):
    """Remove the stored NGX Pulse API key (falls back to env var or unconfigured)."""
    uid: str | None = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(403, "Authentication required")
    if _OWNER_USER_ID and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Only the account owner can remove market data keys")
    from brain.ngx_creds import delete_ngx_pulse_key
    existed = delete_ngx_pulse_key()
    return {"deleted": existed}


# ── Financial Modeling Prep (FMP) settings + data proxy ──────────────────────

class FmpSettingsPayload(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=512)


# Whitelisted FMP endpoints — prevents arbitrary FMP API access via our proxy
_FMP_ALLOWED_ENDPOINTS = frozenset({
    "profile",
    "key-metrics",
    "income-statement",
    "balance-sheet-statement",
    "cash-flow-statement",
    "analyst-stock-recommendations",
    "price-target-consensus",
})

# Endpoints that don't accept period/limit params
_FMP_SIMPLE_ENDPOINTS = frozenset({
    "profile",
    "analyst-stock-recommendations",
    "price-target-consensus",
})


def _resolve_fmp_key(user_id: str | None) -> str | None:
    """Return the best FMP API key for this user (never logged or returned to callers)."""
    if user_id:
        try:
            enc_key = _get_enc_key()
            from brain.fmp_creds import get_effective_fmp_key
            key = get_effective_fmp_key(user_id, enc_key)
            if key:
                return key
        except Exception as exc:
            log.warning("FMP key resolution failed for user %s: %s", user_id[:8], exc)
    return os.environ.get("FMP_API_KEY") or None


@app.get("/fmp-settings")
def get_fmp_settings(request: Request):
    """Return this user's FMP key status — value is never returned."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for FMP settings")
    from brain.fmp_creds import load_user_fmp_settings
    s = load_user_fmp_settings(user_id)
    system_key = bool(os.environ.get("FMP_API_KEY"))
    return {
        "user_key_configured":   bool(s.api_key_enc),
        "system_key_configured": system_key,
        "effective_source":      (
            "user"   if s.api_key_enc
            else "system" if system_key
            else "none"
        ),
    }


@app.post("/fmp-settings")
def save_fmp_settings(req: FmpSettingsPayload, request: Request):
    """Encrypt and persist this user's FMP API key — stored per-user, never shared."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for FMP settings")
    enc_key = _get_enc_key()
    from brain.fmp_creds import save_user_fmp_key
    save_user_fmp_key(user_id, req.api_key, enc_key)
    log.info("FMP API key saved for user %s", user_id[:8])
    return {"saved": True, "user_key_configured": True}


@app.delete("/fmp-settings")
def delete_fmp_settings(request: Request):
    """Remove this user's FMP API key — reverts to system key or free tier."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for FMP settings")
    from brain.fmp_creds import delete_user_fmp_key
    existed = delete_user_fmp_key(user_id)
    return {"deleted": True, "had_key": existed}


@app.get("/fmp/{data_type}")
def fmp_proxy(data_type: str, symbol: str, request: Request,
              period: str = "annual", limit: int = 5):
    """Proxy requests to Financial Modeling Prep — key is resolved server-side.

    data_type: one of profile | key-metrics | income-statement |
               balance-sheet-statement | cash-flow-statement |
               analyst-stock-recommendations | price-target-consensus
    symbol: uppercase ticker (e.g. AAPL)
    period: annual (default) or quarter
    limit:  number of periods to return (1-10, default 5)
    """
    if data_type not in _FMP_ALLOWED_ENDPOINTS:
        raise HTTPException(400, f"data_type must be one of: {', '.join(sorted(_FMP_ALLOWED_ENDPOINTS))}")
    if period not in ("annual", "quarter"):
        raise HTTPException(400, "period must be 'annual' or 'quarter'")
    limit = max(1, min(limit, 10))

    sym = _validate_symbol(symbol)
    user_id: str | None = getattr(request.state, "user_id", None)

    # Demo account — return empty rather than fetching live FMP data
    if _DEMO_USER_ID and user_id == _DEMO_USER_ID:
        return []

    api_key = _resolve_fmp_key(user_id)

    # No FMP key — fall back to Yahoo Finance (same response schema, no key required)
    if not api_key:
        from brain.yf_research import yf_fetch
        result = yf_fetch(data_type, sym, limit)
        if result is not None:
            return result
        # Financial statements not in yfinance fallback — return empty list gracefully
        return []

    url = f"https://financialmodelingprep.com/api/v3/{data_type}/{sym}"
    params: dict = {"apikey": api_key}
    if data_type not in _FMP_SIMPLE_ENDPOINTS:
        params["period"] = period
        params["limit"]  = str(limit)

    try:
        import httpx
        resp = httpx.get(url, params=params, timeout=12.0)
        if resp.status_code == 401:
            raise HTTPException(401, "FMP API key invalid — check Settings → Research Data")
        if resp.status_code == 403:
            raise HTTPException(403, "FMP access denied — your key may lack permissions")
        if resp.status_code == 429:
            raise HTTPException(429, "FMP rate limit reached — add your own key in Settings → Research Data")
        if not resp.is_success:
            raise HTTPException(502, f"FMP returned HTTP {resp.status_code}")
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise HTTPException(503, data["Error Message"])
        return data
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("FMP proxy error for %s/%s: %s", data_type, sym, exc)
        raise HTTPException(502, "FMP data temporarily unavailable")


# ── Demo account snapshot ─────────────────────────────────────────────────────

@app.get("/demo/snapshot-info")
def demo_snapshot_info_endpoint(request: Request):
    """Return metadata about the saved demo snapshot (owner-only)."""
    uid = getattr(request.state, "user_id", None)
    if _OWNER_USER_ID and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Owner access required")
    from brain.demo_store import demo_snapshot_info
    return demo_snapshot_info()


@app.post("/demo/snapshot")
def take_demo_snapshot(request: Request):
    """Capture the owner's current live state as the demo account's snapshot.

    Captures: portfolio state, equity curve (1D/1M/1Y), cached signals, and
    the last 50 orders.  The demo user (DEMO_USER_ID) will see this data
    instead of live broker data.  Owner-only.
    """
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(403, "JWT authentication required")
    if _OWNER_USER_ID and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Only the account owner can update the demo snapshot")

    from config import get_settings
    from datetime import timezone
    cfg = get_settings()

    # ── Portfolio state ───────────────────────────────────────────────────────
    portfolio_data: dict = {}
    try:
        from data.portfolio import PortfolioFetcher
        from broker.adapters.alpaca import AlpacaBrokerAdapter
        ak, sk, base_url, _ = _resolve_alpaca_creds(uid, cfg)
        if ak:
            fetcher = PortfolioFetcher(AlpacaBrokerAdapter(ak, sk, base_url))
            state = fetcher.snapshot()
            portfolio_data = {
                "timestamp":             state.timestamp.isoformat(),
                "equity":                state.equity,
                "cash":                  state.cash,
                "buying_power":          state.buying_power,
                "daily_pnl":             state.daily_pnl,
                "daily_pnl_pct":         state.daily_pnl_pct,
                "open_pnl_today":        state.open_pnl_today,
                "realized_pnl_today":    state.realized_pnl_today,
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
                    for p in (state.positions or [])
                ],
                "fetch_error": None,
            }
    except Exception as exc:
        log.warning("Demo snapshot: portfolio fetch failed: %s", exc)

    # ── Equity history ────────────────────────────────────────────────────────
    history_data: dict[str, list] = {}
    try:
        ak, sk, base_url, _ = _resolve_alpaca_creds(uid, cfg)
        if ak:
            from broker.adapters.alpaca import AlpacaBrokerAdapter
            broker = AlpacaBrokerAdapter(ak, sk, base_url)
            for period in ("1D", "1M", "1Y"):
                try:
                    tf = "5Min" if period == "1D" else "1D"
                    history_data[period] = broker.get_portfolio_history(period, tf)
                except Exception as exc:
                    log.warning("Demo snapshot: history %s fetch failed: %s", period, exc)
                    history_data[period] = []
    except Exception as exc:
        log.warning("Demo snapshot: history fetch failed: %s", exc)

    # ── Cached signals ────────────────────────────────────────────────────────
    signals_data = sorted(
        list(_signal_cache.values()),
        key=lambda s: s.get("generated_at", ""),
        reverse=True,
    )

    # ── Recent orders ─────────────────────────────────────────────────────────
    orders_data: dict = {"orders": []}
    try:
        ak, sk, base_url, _ = _resolve_alpaca_creds(uid, cfg)
        if ak:
            from broker.adapters.alpaca import AlpacaBrokerAdapter
            broker = AlpacaBrokerAdapter(ak, sk, base_url)
            raw_orders = broker.get_orders(status="all", limit=50)
            orders_data = {
                "orders": [
                    {
                        "order_id":         o.order_id,
                        "client_order_id":  o.client_order_id,
                        "symbol":           o.symbol,
                        "side":             o.side,
                        "order_type":       o.order_type,
                        "qty":              o.qty,
                        "filled_qty":       o.filled_qty,
                        "status":           o.status,
                        "submitted_at":     o.submitted_at.isoformat() if o.submitted_at else None,
                        "filled_at":        o.filled_at.isoformat() if o.filled_at else None,
                        "limit_price":      o.limit_price,
                        "stop_price":       o.stop_price,
                        "filled_avg_price": o.filled_avg_price,
                    }
                    for o in raw_orders
                ]
            }
    except Exception as exc:
        log.warning("Demo snapshot: orders fetch failed: %s", exc)

    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "portfolio":   portfolio_data,
        "history":     history_data,
        "signals":     signals_data,
        "orders":      orders_data,
    }

    from brain.demo_store import save_demo_snapshot
    path = save_demo_snapshot(snapshot)
    return {
        "status":       "ok",
        "captured_at":  snapshot["captured_at"],
        "path":         path,
        "signal_count": len(signals_data),
        "order_count":  len(orders_data["orders"]),
    }


# ── Charles Schwab OAuth 2.0 endpoints ────────────────────────────────────────

@app.get("/schwab-auth/url")
def schwab_auth_url(request: Request):
    """Generate a Schwab OAuth authorization URL for this user.

    Returns: { url: string } — the user should open this in a new tab.
    Requires JWT auth. Rate-limited.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required")

    cfg = _get_settings()
    app_key      = getattr(cfg, "schwab_app_key",      "") or os.environ.get("SCHWAB_APP_KEY",      "")
    redirect_uri = getattr(cfg, "schwab_redirect_uri", "") or os.environ.get("SCHWAB_REDIRECT_URI", "")
    if not app_key:
        raise HTTPException(503, "Schwab integration not configured — contact the administrator")
    if not redirect_uri:
        raise HTTPException(503, "SCHWAB_REDIRECT_URI not configured")

    import secrets
    import urllib.parse

    # Prune expired states
    now = _time.monotonic()
    expired = [k for k, (_, exp) in _SCHWAB_OAUTH_STATES.items() if now >= exp]
    for k in expired:
        del _SCHWAB_OAUTH_STATES[k]

    nonce        = secrets.token_urlsafe(24)
    state        = f"{user_id}:{nonce}"
    _SCHWAB_OAUTH_STATES[state] = (user_id, now + _SCHWAB_STATE_TTL)

    params = {
        "response_type": "code",
        "client_id":     app_key,
        "redirect_uri":  redirect_uri,
        "state":         state,
        "scope":         "readonly",
    }
    url = "https://api.schwabapi.com/v1/oauth/authorize?" + urllib.parse.urlencode(params)
    return {"url": url}


@app.get("/schwab-auth/callback")
async def schwab_auth_callback(request: Request):
    """Browser redirect target after Schwab OAuth.

    Schwab redirects here with ?code=...&state=...
    We exchange the code for tokens, persist them, then redirect the user to the dashboard.
    This endpoint is NOT JWT-authenticated — it is called by Schwab's servers on behalf
    of the browser. CSRF protection is via the state nonce.
    """
    from fastapi.responses import RedirectResponse

    params = dict(request.query_params)
    code   = params.get("code",  "")
    state  = params.get("state", "")
    error  = params.get("error", "")

    cfg             = _get_settings()
    redirect_target = getattr(cfg, "schwab_redirect_target", "") or os.environ.get("SCHWAB_REDIRECT_TARGET", "/")

    def _fail(reason: str):
        import urllib.parse
        dest = redirect_target + ("&" if "?" in redirect_target else "?") + urllib.parse.urlencode({"schwab_error": reason})
        return RedirectResponse(dest)

    if error:
        return _fail(f"OAuth denied: {error}")
    if not code or not state:
        return _fail("Missing code or state parameter")

    # CSRF validation
    now = _time.monotonic()
    if state not in _SCHWAB_OAUTH_STATES:
        return _fail("Invalid or expired state — please try connecting again")
    user_id, expiry = _SCHWAB_OAUTH_STATES.pop(state)
    if now >= expiry:
        return _fail("OAuth session timed out — please try connecting again")

    # Exchange code for tokens
    import base64
    import httpx as _httpx

    app_key      = getattr(cfg, "schwab_app_key",      "") or os.environ.get("SCHWAB_APP_KEY",      "")
    app_secret   = getattr(cfg, "schwab_app_secret",   "") or os.environ.get("SCHWAB_APP_SECRET",   "")
    redirect_uri = getattr(cfg, "schwab_redirect_uri", "") or os.environ.get("SCHWAB_REDIRECT_URI", "")
    credentials  = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()

    try:
        token_resp = _httpx.post(
            "https://api.schwabapi.com/v1/oauth/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": redirect_uri,
            },
            timeout=15.0,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except Exception as exc:
        log.error("Schwab token exchange failed for user %s: %s", user_id[:8], exc)
        return _fail("Token exchange failed — please try again")

    access_token  = token_data.get("access_token",  "")
    refresh_token = token_data.get("refresh_token", "")
    access_exp    = _time.time() + int(token_data.get("expires_in", 1800))
    refresh_exp   = _time.time() + int(token_data.get("refresh_token_expires_in", 7 * 86400))

    if not access_token or not refresh_token:
        return _fail("Incomplete token response from Schwab")

    # Fetch account hash from the accounts endpoint
    account_hash = ""
    try:
        acct_resp = _httpx.get(
            "https://api.schwabapi.com/trader/v1/accounts",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        acct_resp.raise_for_status()
        accounts = acct_resp.json() if isinstance(acct_resp.json(), list) else []
        if accounts:
            account_hash = accounts[0].get("hashValue") or accounts[0].get("encryptedId") or ""
    except Exception as exc:
        log.warning("Schwab account hash fetch failed for user %s: %s", user_id[:8], exc)

    enc_key = _get_enc_key()
    from brain.schwab_creds import save_schwab_tokens
    save_schwab_tokens(
        user_id, enc_key,
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_exp=access_exp,
        refresh_token_exp=refresh_exp,
        account_hash=account_hash,
    )
    log.info("Schwab OAuth complete for user %s — account hash: %s", user_id[:8], account_hash[:8] if account_hash else "none")

    dest = redirect_target + ("&" if "?" in redirect_target else "?") + "schwab_connected=1"
    return RedirectResponse(dest)


@app.get("/schwab-settings")
def get_schwab_settings(request: Request):
    """Return Schwab connection status for this user (no token values ever returned)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Schwab settings")

    enc_key = _get_enc_key()
    from brain.schwab_creds import load_schwab_tokens
    tokens = load_schwab_tokens(user_id, enc_key)
    if tokens is None or not tokens.configured:
        return {"connected": False, "access_expired": False, "refresh_expired": False, "account_hash": ""}

    return {
        "connected":      True,
        "access_expired": tokens.access_expired,
        "refresh_expired": tokens.refresh_expired,
        "account_hash":   tokens.account_hash,  # not sensitive — it's Schwab's own obfuscated ID
    }


@app.delete("/schwab-settings")
def delete_schwab_settings(request: Request):
    """Disconnect Schwab account — removes stored tokens for this user."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for Schwab settings")
    from brain.schwab_creds import delete_schwab_tokens
    existed = delete_schwab_tokens(user_id)
    return {"disconnected": True, "had_tokens": existed}


# ── Interactive Brokers IB Gateway endpoints ──────────────────────────────────

@app.get("/ibkr-settings")
def get_ibkr_settings(request: Request):
    """Return the user's IB Gateway connection settings.

    Connection parameters are not secret (no passwords stored), so values
    are returned for display. Returns defaults if not configured.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for IBKR settings")
    from brain.ibkr_creds import load_ibkr_settings
    s = load_ibkr_settings(user_id)
    return {
        "host":       s.host,
        "port":       s.port,
        "client_id":  s.client_id,
        "account_id": s.account_id,
        "paper_mode": s.paper_mode,
        "configured": s.configured,
    }


@app.post("/ibkr-settings")
def save_ibkr_settings(req: IBKRSettingsPayload, request: Request):
    """Save the user's IB Gateway connection settings."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for IBKR settings")
    if not req.host:
        raise HTTPException(400, "host is required")
    if not (1 <= req.port <= 65535):
        raise HTTPException(400, "port must be between 1 and 65535")
    if not (0 <= req.client_id <= 32):
        raise HTTPException(400, "client_id must be between 0 and 32")
    from brain.ibkr_creds import save_ibkr_settings as _save
    _save(
        user_id=user_id,
        host=req.host,
        port=req.port,
        client_id=req.client_id,
        account_id=req.account_id,
        paper_mode=req.paper_mode,
    )
    return {"saved": True, "configured": True}


@app.delete("/ibkr-settings")
def delete_ibkr_settings(request: Request):
    """Remove the user's IB Gateway settings (reverts to unconfigured)."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for IBKR settings")
    from brain.ibkr_creds import delete_ibkr_settings as _delete
    existed = _delete(user_id)
    return {"deleted": True, "had_settings": existed}


@app.get("/risk-settings")
def get_risk_settings(request: Request):
    """Return the user's per-user risk overrides alongside the effective merged config.

    Response includes:
      effective      — merged result (env defaults + global dynamic + per-user)
      user_overrides — only the fields the user has explicitly set
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for risk settings.")
    from config import get_settings
    from brain.risk_config import load_user_risk_config, get_effective_risk_for_user
    cfg = get_settings()
    base_eff = _effective_config(cfg)
    user_overrides = load_user_risk_config(user_id)
    effective = get_effective_risk_for_user(user_id, base_eff)
    return {
        "effective": effective,
        "user_overrides": user_overrides,
    }


@app.post("/risk-settings")
def save_risk_settings(body: RiskConfigUpdate, request: Request):
    """Save per-user risk overrides (partial update — only send fields you want to change).

    Never affects the global config or other users. Returns the merged effective config.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for risk settings.")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")
    for key, val in list(updates.items()):
        if key in _CONFIG_BOUNDS:
            lo, hi = _CONFIG_BOUNDS[key]
            updates[key] = max(lo, min(hi, float(val)))
        elif key in _CONFIG_INT_BOUNDS:
            lo, hi = _CONFIG_INT_BOUNDS[key]
            updates[key] = max(lo, min(hi, int(val)))
    from brain.risk_config import save_user_risk_config, get_effective_risk_for_user, load_user_risk_config
    save_user_risk_config(user_id, updates)
    log.info("Per-user risk settings saved for %s: %s", user_id, updates)
    from config import get_settings
    cfg = get_settings()
    base_eff = _effective_config(cfg)
    user_overrides = load_user_risk_config(user_id)
    effective = get_effective_risk_for_user(user_id, base_eff)
    return {
        "saved": True,
        "updated": updates,
        "effective": effective,
        "user_overrides": user_overrides,
    }


@app.delete("/risk-settings")
def reset_risk_settings(request: Request):
    """Remove all per-user risk overrides — reverts the user to global config."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for risk settings.")
    from brain.risk_config import delete_user_risk_config
    delete_user_risk_config(user_id)
    log.info("Per-user risk settings reset for %s", user_id)
    from config import get_settings
    return {"reset": True, "current": _effective_config(get_settings())}


@app.post("/signal", response_model=SignalResponse)
def generate_signal(req: SignalRequest, request: Request):
    req.symbol = _validate_symbol(req.symbol)
    if req.asset_class not in ("stock", "crypto"):
        raise HTTPException(400, "asset_class must be 'stock' or 'crypto'")
    from config import get_settings
    cfg = get_settings()

    # Resolve the LLM configuration for this request.
    # Browser users (JWT) → their per-user settings (falls back to system defaults if none set).
    # Orchestrator (X-Api-Key) → always system defaults (no user_id in state).
    user_id: str | None = getattr(request.state, "user_id", None)
    effective_llm = None
    if not req.paper_mode:
        try:
            from brain.llm_creds import get_effective_llm_config
            effective_llm = get_effective_llm_config(
                user_id, cfg.openrouter_api_key, _get_enc_key() if cfg.brain_api_key else b"",
            )
        except Exception as _llm_exc:
            log.warning("LLM config resolution failed (%s) — falling back to system OpenRouter key", _llm_exc)

        if effective_llm is None or (effective_llm.using_system_keys and not cfg.openrouter_api_key):
            raise HTTPException(
                status_code=503,
                detail=(
                    "No LLM provider configured. Enter your API key in Settings → Brain / LLM, "
                    "or ask the admin to set OPENROUTER_API_KEY in Railway env vars."
                ),
            )

    try:
        alpaca, alpaca_crypto, sentiment_fetcher, onchain_fetcher, portfolio_fetcher = (
            _get_shared_services(cfg)
        )
        if effective_llm is not None:
            if user_id:
                # Per-user: build fresh DebateOrchestrator with per-user risk — never cached
                from brain.risk_config import get_effective_risk_for_user
                _user_risk_eff = get_effective_risk_for_user(user_id, _effective_config(cfg))
                orchestrator = _build_debate_with_risk(cfg, effective_llm, _user_risk_eff)
            else:
                # Orchestrator / system path: use cached debate (unchanged behaviour)
                orchestrator = _get_debate(cfg, effective_llm)
        else:
            orchestrator = None  # paper mode — orchestrator not used
    except Exception as exc:
        log.error("Service initialisation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Service init failed: {exc}")

    # ── Resolve market data source (Polygon if configured, else Alpaca) ────────
    stock_md = _resolve_stock_data(user_id, cfg, alpaca)

    # ── Fetch market data (bar cache reduces network round-trip to ~0 ms after first call) ──
    try:
        if req.asset_class == "stock":
            market = _get_market_snapshot(stock_md, req.symbol, req.lookback_days)
            onchain_snap = None
        else:
            market = _get_market_snapshot(alpaca_crypto, req.symbol, req.lookback_days)
            onchain_snap = onchain_fetcher.snapshot()
    except Exception as exc:
        log.error("Market data fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {exc}")

    # ── Refresh latest_quote outside bar cache (bar cache TTL=5min retains yesterday's close;
    # indicators must reflect the live intraday price to avoid acting on stale signals) ──
    try:
        fetcher = stock_md if req.asset_class == "stock" else alpaca_crypto
        live_quote = fetcher.get_latest_quote(req.symbol)
        if live_quote and float(getattr(live_quote, "mid", 0) or 0) > 0:
            market = _dc_replace(market, latest_quote=live_quote)
            log.debug("Live quote refreshed: %s mid=%.4f", req.symbol, live_quote.mid)
    except Exception as _qexc:
        log.debug("Live quote refresh skipped for %s: %s", req.symbol, _qexc)

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

    # ── Billing probe: verify LLM credits before spawning 27 agents ──────────
    # If billing fails, fall back to rule-based paper mode so signals are still
    # useful rather than returning 27×NEUTRAL and a HOLD/COLD result.
    effective_paper_mode = req.paper_mode
    billing_fallback = False
    if not req.paper_mode and effective_llm is not None:
        try:
            _probe_response = effective_llm.tactical_client.chat.completions.create(
                model=effective_llm.tactical_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "x"}],
            )
        except Exception as _probe_exc:
            _msg = str(_probe_exc)
            if "credit" in _msg.lower() or "insufficient_quota" in _msg or "billing" in _msg.lower() or "402" in _msg:
                from watchlist import PROVIDER_BILLING_URLS as _PBURL
                _billing_url = _PBURL.get(effective_llm.tactical_provider, "your provider dashboard")
                log.warning(
                    "%s billing insufficient — falling back to rule-based (paper) mode for %s. "
                    "Top up credits at %s to restore full LLM debate.",
                    effective_llm.tactical_provider, req.symbol, _billing_url,
                )
                effective_paper_mode = True
                billing_fallback = True

    # ── Run debate (paper mode = rule-based; live mode = full LLM) ────────
    # Paper mode doesn't need an LLM client — build a default orchestrator if
    # none was resolved (e.g. paper_mode=True request with no LLM config).
    # Browser users (user_id=str) get their per-user risk params even in paper mode.
    if orchestrator is None:
        from brain.debate import DebateOrchestrator
        if user_id:
            from brain.risk_config import get_effective_risk_for_user as _paper_risk_fn
            _paper_eff = _paper_risk_fn(user_id, _effective_config(cfg))
            orchestrator = DebateOrchestrator(
                openrouter_api_key="",
                confidence_threshold=_paper_eff.get("signal_confidence_threshold", cfg.signal_confidence_threshold),
                max_position_pct=_paper_eff["max_position_pct"],
                max_crypto_pct=_paper_eff["max_crypto_allocation_pct"],
                circuit_breaker_drawdown=_paper_eff["circuit_breaker_drawdown"],
                stop_loss_pct=_paper_eff["stop_loss_pct"],
                take_profit_pct=_paper_eff["take_profit_pct"],
            )
        else:
            orchestrator = DebateOrchestrator(openrouter_api_key="")
    try:
        signal = orchestrator.run(
            market, sentiment_bundle, onchain_snap, portfolio_state,
            paper_mode=effective_paper_mode,
        )
    except Exception as exc:
        log.error("Debate failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent debate failed: {exc}")

    if billing_fallback:
        _prov = effective_llm.tactical_provider if effective_llm else "LLM"
        signal.rationale = (
            f"[Rule-based fallback — {_prov} credits exhausted, LLM debate unavailable] "
            + signal.rationale
        )

    d = signal.to_dict()

    # Cache — persist to disk so signals survive process restarts.
    # Skip caching if majority of LLM agents errored (e.g. bad model ID, quota, network).
    # A broken signal would sit in cache and be shown on every refresh until the next cycle.
    agent_views = d.get("agent_views", {})
    all_views   = [v for v in agent_views.values() if isinstance(v, str)]
    error_views = [v for v in all_views if "Agent error" in v]
    too_many_errors = not effective_paper_mode and len(all_views) > 0 and len(error_views) > len(all_views) * 0.5
    if too_many_errors:
        log.warning(
            "NOT caching %s — %d/%d agents errored (likely LLM API / model ID issue). "
            "Signal will not be stored until agents recover.",
            req.symbol, len(error_views), len(all_views),
        )
    else:
        _cache_key = f"{user_id or 'system'}::{req.symbol}"
        _signal_cache[_cache_key] = {**d, "_uid": user_id or "system"}
        _save_cache(_signal_cache)

        # Persist to SQLite history log (non-fatal)
        try:
            from brain import signal_history as _sh
            _cp = (
                market.latest_quote.mid
                if market.latest_quote and getattr(market.latest_quote, "mid", None)
                else (market.bars[-1].close if market.bars else None)
            )
            _sh.record(user_id or "system", d, _cp)
        except Exception as _sh_exc:
            log.debug("signal_history.record skipped: %s", _sh_exc)

        # Persist to Supabase track record (Approaches 1+3) — non-fatal, background thread
        try:
            from brain.debate import _compute_indicators as _ci
            _inds = _ci(market)
        except Exception:
            _inds = {}

        def _record_snapshot_bg():
            try:
                from brain import signal_snapshots as _ss
                _source = "live_llm" if not effective_paper_mode else "live_rule"
                _model  = ""
                _prov   = ""
                if effective_llm is not None:
                    _model = getattr(effective_llm, "tactical_model", "")
                    _prov  = getattr(effective_llm, "tactical_provider", "")
                _ss.record_snapshot(
                    d, _inds,
                    source=_source,
                    paper_mode=effective_paper_mode,
                    model_used=_model,
                    provider=_prov,
                )
            except Exception as _ss_exc:
                log.debug("signal_snapshots.record_snapshot skipped: %s", _ss_exc)

        import threading as _thr
        _thr.Thread(target=_record_snapshot_bg, daemon=True, name="snapshot-write").start()

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
def get_latest_signal(symbol: str, request: Request):
    uid = getattr(request.state, "user_id", None) or "system"
    sym = symbol.upper()
    # Try user-scoped key first; fall back to legacy plain-symbol key for backward compat.
    cached = _signal_cache.get(f"{uid}::{sym}") or _signal_cache.get(sym)
    if not cached:
        raise HTTPException(status_code=404, detail=f"No cached signal for {symbol}")
    return cached


@app.get("/signals/cached", response_model=list)
def get_all_cached_signals(request: Request):
    """Return all signals in the in-memory cache for the current user, newest first.
    Rationale fields are sanitised on the way out."""
    uid = getattr(request.state, "user_id", None) or "system"

    # ── Demo account intercept ────────────────────────────────────────────────
    if _DEMO_USER_ID and uid == _DEMO_USER_ID:
        from brain.demo_store import load_demo_snapshot
        snap = load_demo_snapshot()
        if snap:
            return snap.get("signals", [])
        return []

    def _clean(s: dict) -> dict:
        rat = s.get("rationale", "")
        if rat and any(c in rat for c in ("**", "##", "\n")):
            s = {**s, "rationale": _clean_rationale(rat)}
        return s

    # Determine whether this user can see orchestrator ("system") signals.
    # X-Api-Key callers (uid="system") always see them.
    # If OWNER_USER_ID is configured, only the designated owner sees system signals;
    # all other JWT users see only their own signals.
    # If OWNER_USER_ID is not configured (legacy / single-user mode), all authenticated
    # users see system signals — preserves original behaviour for existing deployments.
    _see_system = (
        uid == "system"
        or (not _OWNER_USER_ID)
        or (_OWNER_USER_ID and uid == _OWNER_USER_ID)
    )

    # Show:
    #  • Entries tagged with this user's own id (signals they generated manually)
    #  • Entries tagged "system" (orchestrator) when _see_system is True
    #  • Entries with no _uid tag (generated before per-user scoping) — treated as system
    user_signals = [
        v for v in _signal_cache.values()
        if v.get("_uid", "system") == uid
        or (_see_system and v.get("_uid", "system") == "system")
    ]
    return sorted(
        (_clean(s) for s in user_signals),
        key=lambda s: s.get("generated_at", ""),
        reverse=True,
    )


@app.delete("/signals/cached")
def clear_all_cached_signals(request: Request):
    """Wipe the current user's own signals from the cache.
    System/orchestrator signals are shared and are not cleared by individual users."""
    uid = getattr(request.state, "user_id", None) or "system"
    keys_to_del = [
        k for k, v in _signal_cache.items()
        if v.get("_uid") == uid  # exact match only — never wipe system signals
    ]
    for k in keys_to_del:
        del _signal_cache[k]
    _save_cache(_signal_cache)
    return {"cleared": True}


# ── Signal history endpoints ───────────────────────────────────────────────────

@app.get("/signal/history")
def get_signal_history(
    request: Request,
    symbol:  str | None = None,
    action:  str | None = None,
    tier:    str | None = None,
    outcome: str | None = None,
    limit:   int = 100,
    offset:  int = 0,
):
    uid = getattr(request.state, "user_id", None) or "system"
    from brain import signal_history as _sh
    return _sh.list_history(uid, symbol=symbol, action=action,
                             tier=tier, outcome=outcome, limit=limit, offset=offset)


@app.get("/signal/leaderboard")
def get_signal_leaderboard(request: Request, group_by: str = "tier"):
    uid = getattr(request.state, "user_id", None) or "system"
    from brain import signal_history as _sh
    return {"group_by": group_by, "rows": _sh.get_leaderboard(uid, group_by=group_by)}


@app.get("/signal/stats")
def get_signal_stats(request: Request):
    uid = getattr(request.state, "user_id", None) or "system"
    from brain import signal_history as _sh
    return _sh.get_stats(uid)


# ── Track Record API (Supabase-backed) ───────────────────────────────────────

@app.get("/track-record/stats")
def get_track_record_stats(request: Request):
    """7d and 30d signal performance from Supabase signal_snapshots."""
    from brain import signal_snapshots as _ss
    return _ss.get_stats()


@app.get("/track-record/leaderboard")
def get_track_record_leaderboard(request: Request, group_by: str = "tier"):
    """Aggregate win/loss/neutral from Supabase, grouped by tier/asset_class/regime."""
    from brain import signal_snapshots as _ss
    return {"group_by": group_by, "rows": _ss.get_leaderboard(group_by=group_by)}


@app.get("/track-record/config")
def get_track_record_config(request: Request):
    """Return the locked track record configuration."""
    from brain.track_record import get_config
    return get_config()


@app.get("/track-record/equity-curve")
def get_equity_curve(
    request: Request,
    days: int = 90,
    backtest_id: str | None = None,
):
    """Return daily portfolio NAV snapshots for the equity curve chart."""
    from brain import portfolio_snapshots as _ps
    source = "backtest" if backtest_id else "paper_live"
    return {
        "source":     source,
        "backtest_id": backtest_id,
        "rows":       _ps.get_equity_curve(source=source, backtest_id=backtest_id, days=days),
    }


@app.get("/track-record/benchmarks")
def get_benchmark_comparison(request: Request, days: int = 30):
    """Return portfolio vs SPY vs BTC performance for a given period.

    When Supabase has fewer than 2 historical snapshots, supplements with
    the live portfolio equity so the tile shows data from day one.
    """
    from brain import portfolio_snapshots as _ps
    result = _ps.get_benchmark_comparison(days=days)
    if result.get("insufficient_data"):
        # Try to provide a real-time reading using live equity
        try:
            uid = getattr(request.state, "user_id", None) or "system"
            from config import get_settings
            from brain.api import _resolve_alpaca_creds
            from broker.adapters.alpaca import AlpacaBrokerAdapter
            from data.portfolio import PortfolioFetcher
            cfg = get_settings()
            ak, sk, base_url, _ = _resolve_alpaca_creds(uid, cfg)
            if ak:
                fetcher = PortfolioFetcher(AlpacaBrokerAdapter(ak, sk, base_url))
                snap = fetcher.snapshot()
                result = _ps.get_benchmark_comparison(days=days, current_nav=snap.equity)
        except Exception:
            pass
    return result


# ── Backtest API ──────────────────────────────────────────────────────────────

# In-memory cache — survives without the Supabase migration being applied.
# Keyed by run name; holds the latest status for each run this process has seen.
_BACKTEST_CACHE: dict[str, dict] = {}


@app.get("/backtest/runs")
def list_backtest_runs(request: Request, limit: int = 20):
    """List backtest runs — merges in-memory cache with Supabase (if available)."""
    sb_runs: list[dict] = []
    try:
        from brain.signal_snapshots import _get_sb
        sb = _get_sb()
        if sb is not None:
            resp = (
                sb.table("backtest_runs")
                .select("id,name,engine,start_date,end_date,status,total_return,"
                        "annualized_return,sharpe_ratio,max_drawdown,win_rate,"
                        "total_trades,symbol_universe,created_at,spy_return,btc_return,"
                        "final_nav,profit_factor,engine_version")
                .order("created_at", desc=True)
                .limit(min(limit, 50))
                .execute()
            )
            sb_runs = resp.data or []
    except Exception as exc:
        log.debug("backtest list from Supabase failed (non-fatal): %s", exc)

    # Mark any Supabase "running" row older than 20 minutes as stale in the response.
    # These are orphaned threads from a previous container that will never complete.
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _stale_cutoff = _dt.now(_tz.utc) - _td(minutes=20)
    for row in sb_runs:
        if row.get("status") == "running":
            try:
                created = _dt.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                if created < _stale_cutoff:
                    row["status"] = "failed"
                    row["error"]  = "Run timed out — server was restarted. Please re-run."
            except Exception:
                pass

    # Merge: Supabase rows take precedence; fall back to cache for runs not yet persisted
    sb_names = {r["name"] for r in sb_runs}
    cache_only = [v for v in _BACKTEST_CACHE.values() if v.get("name") not in sb_names]
    merged = sb_runs + sorted(cache_only, key=lambda r: r.get("created_at", ""), reverse=True)
    return {"runs": merged[:limit]}


@app.get("/backtest/runs/{run_id}")
def get_backtest_run(run_id: str, request: Request):
    """Return full detail for one backtest run."""
    # Check cache first
    for entry in _BACKTEST_CACHE.values():
        if entry.get("id") == run_id:
            return entry
    try:
        from brain.signal_snapshots import _get_sb
        sb = _get_sb()
        if sb is None:
            raise HTTPException(503, "Supabase not configured")
        resp = sb.table("backtest_runs").select("*").eq("id", run_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(404, "Backtest run not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/backtest/run")
async def trigger_backtest(request: Request):
    """Trigger a new rule-based backtest run in a background thread.

    Body: {"name": str, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD",
           "symbols": ["AAPL", ...] | "all"}
    """
    import threading as _thr
    from datetime import datetime as _dt, timezone as _tz
    import uuid as _uuid
    try:
        body = await request.json()
    except Exception:
        body = {}
    name           = body.get("name", "")
    start_date     = body.get("start_date", "2024-01-01")
    end_date       = body.get("end_date", "")
    symbols        = body.get("symbols", "all")
    engine_version = body.get("engine_version", "v1")

    if not name:
        raise HTTPException(400, "name is required")

    # Validate engine version
    from backtest.engine_profiles import ENGINE_PROFILES
    if engine_version not in ENGINE_PROFILES:
        engine_version = "v1"

    run_id = str(_uuid.uuid4())
    created_at = _dt.now(_tz.utc).isoformat()

    # Write optimistic "running" entry to cache immediately
    _BACKTEST_CACHE[name] = {
        "id":             run_id,
        "name":           name,
        "status":         "running",
        "engine":         "rule_based",
        "engine_version": engine_version,
        "start_date":     start_date,
        "end_date":       end_date or "",
        "created_at":     created_at,
        "started_at":     created_at,   # ISO timestamp so frontend can show elapsed time
        "symbol_universe": [],
    }

    BACKTEST_TIMEOUT_S = 300  # 5 minutes — fail fast so the user can retry

    def _run():
        import time as _time
        import concurrent.futures as _cf
        t0 = _time.monotonic()
        try:
            from backtest.supabase_engine import run_backtest

            # Do NOT use ThreadPoolExecutor as a context manager — __exit__ calls
            # shutdown(wait=True) which blocks until the thread finishes, making
            # the timeout completely ineffective.
            _ex  = _cf.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(run_backtest, name=name, start_date=start_date,
                              end_date=end_date or None, symbols=symbols,
                              engine_version=engine_version)
            try:
                result = _fut.result(timeout=BACKTEST_TIMEOUT_S)
            except _cf.TimeoutError:
                _ex.shutdown(wait=False)   # abandon — don't block waiting for the thread
                elapsed = int(_time.monotonic() - t0)
                raise RuntimeError(
                    f"Backtest timed out after {elapsed}s — server may be under load"
                )
            _ex.shutdown(wait=False)

            _BACKTEST_CACHE[name] = {
                "id":                run_id,
                "name":              name,
                "status":            result.get("status", "completed"),
                "engine":            "rule_based",
                "engine_version":    engine_version,
                "start_date":        start_date,
                "end_date":          end_date or "",
                "created_at":        created_at,
                "final_nav":         result.get("final_equity"),
                "total_return":      result.get("total_return_pct", 0) / 100,
                "annualized_return": result.get("annualized_return_pct", 0) / 100,
                "sharpe_ratio":      result.get("sharpe_ratio"),
                "max_drawdown":      result.get("max_drawdown_pct", 0) / 100,
                "win_rate":          result.get("win_rate_pct"),
                "total_trades":      result.get("total_trades"),
                "profit_factor":     result.get("profit_factor"),
                "symbol_universe":   [],
            }
            log.info("Backtest %s completed in %.0fs", name, _time.monotonic() - t0)
        except Exception as exc:
            log.error("Backtest %s failed: %s", name, exc, exc_info=True)
            _BACKTEST_CACHE[name] = {**_BACKTEST_CACHE.get(name, {}), "status": "failed", "error": str(exc)}

    _thr.Thread(target=_run, daemon=True, name=f"backtest-{name}").start()
    return {"status": "started", "name": name, "start_date": start_date, "end_date": end_date, "run_id": run_id}


# ── Brain NLP query endpoint ───────────────────────────────────────────────────

_CLASSIFY_SYSTEM = """You are an intent classifier for a trading AI assistant. Analyze the user's query and return ONLY valid JSON — no markdown, no explanation.

Category A — user wants to trigger a new multi-agent analysis for a specific ticker symbol:
{"category": "A", "symbol": "AAPL", "asset_class": "stock"}

Category B — user wants to query existing signal data, compare signals, or asks a general question:
{"category": "B"}

Category C — user wants to set a price alert / watch condition on a specific ticker:
{"category": "C", "symbol": "AAPL", "asset_class": "stock", "condition_type": "price_below", "threshold": 180.0}
Supported condition_type values: "price_above", "price_below".

Rules:
- Category A: the query names a specific ticker to analyze NOW (AAPL, NVDA, BTCUSD, ETHUSD, SPY, TSLA, etc.).
  Extract the ticker in UPPERCASE letters/digits only.
  asset_class is "crypto" if the ticker ends in USD/USDT or is a known crypto name (BTC, ETH, SOL, DOGE, XRP, ADA, etc.).
  Otherwise asset_class is "stock".
  If the query is just a bare ticker symbol, treat as Category A.
- Category B: comparative questions, leaderboard questions, questions about existing cached signals, or anything not naming one specific ticker to analyze.
  Examples: "which signal is strongest", "show HOT signals", "compare signals", "any sell signals?".
- Category C: the query uses alert/watch/notify language with a price condition.
  Examples: "alert me if AAPL drops below 180", "tell me when NVDA hits 200", "watch BTC above 100000".
  Extract symbol, asset_class, condition_type (price_above or price_below), and threshold (numeric).
  If no threshold can be determined, fall back to Category B.
- When ambiguous between A and C: if the query mentions a future condition, prefer C; if it asks for an immediate analysis, prefer A.
- Return ONLY the JSON object."""

_SYNTHESIZE_SYSTEM = """You are an AI assistant for a trading platform. Answer the user's question using the provided recent signal data.
Be concise (under 120 words). Reference specific symbols, tiers (HOT/WARM/COLD), and actions (BUY/SELL/HOLD) from the data.
If the data does not contain enough information to answer, say so clearly.
Do not fabricate signals or make trading recommendations beyond what the data shows.
Plain text only — no markdown."""


class BrainQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    conversation_history: list[dict] = Field(default_factory=list)
    asset_class_hint: str = Field("stock", description="User's current default asset class context")


class BrainQueryResponse(BaseModel):
    category: str                   # "A", "B", or "C"
    symbol: str | None = None
    asset_class: str | None = None
    text: str | None = None         # Category B synthesized answer
    condition_type: str | None = None  # Category C
    threshold: float | None = None     # Category C
    rule_id: str | None = None         # Category C — set by frontend after POST /brain/rule
    error: str | None = None


def _or_client_for_query(cfg):
    """Build a minimal OpenAI client pointed at OpenRouter, using system key."""
    from openai import OpenAI
    from config import get_settings
    settings = get_settings()
    api_key = settings.openrouter_api_key or cfg.get("openrouter_api_key", "")
    if not api_key:
        return None
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def _fallback_classify(query: str, asset_class_hint: str) -> dict:
    """Regex fallback when LLM classification fails — detects bare tickers and watch conditions."""
    import re as _re
    q = query.strip()

    # ── Category C: price alert keywords + a number ───────────────────────────
    _alert_kw = _re.compile(
        r'\b(alert|watch|notify|tell me when|warn me|ping me|trigger)\b', _re.I
    )
    _price_pattern = _re.compile(r'\$?([\d,]+(?:\.\d+)?)')
    _above_kw = _re.compile(r'\b(above|over|crosses above|breaks? (above|out|through)|hits?)\b', _re.I)
    _below_kw = _re.compile(r'\b(below|under|drops? (below|to)|falls? (to|below))\b', _re.I)

    if _alert_kw.search(q):
        price_match = _price_pattern.search(q)
        tickers_c = _re.findall(r'\b([A-Z]{2,6}(?:USD|USDT)?)\b', q.upper())
        common_words = {"AND", "THE", "FOR", "BUY", "SELL", "HOLD", "HOT", "WARM", "COLD",
                        "RUN", "ANY", "ME", "ALERT", "WHEN", "HITS", "ABOVE", "BELOW"}
        tickers_c = [t for t in tickers_c if t not in common_words]
        if tickers_c and price_match:
            sym   = tickers_c[0]
            price = float(price_match.group(1).replace(",", ""))
            is_crypto = any(sym.endswith(sfx) for sfx in ("USD", "USDT")) or len(sym) >= 6
            ctype = "price_above" if _above_kw.search(q) else "price_below"
            return {
                "category":       "C",
                "symbol":         sym,
                "asset_class":    "crypto" if is_crypto else asset_class_hint,
                "condition_type": ctype,
                "threshold":      price,
            }

    # ── Category A: bare ticker or ticker in sentence ─────────────────────────
    if _re.match(r'^[A-Z0-9]{1,8}$', q.upper()):
        sym = q.upper()
        is_crypto = any(sym.endswith(sfx) for sfx in ("USD", "USDT", "BTC", "ETH")) or len(sym) >= 6
        return {"category": "A", "symbol": sym, "asset_class": "crypto" if is_crypto else asset_class_hint}
    tickers = _re.findall(r'\b([A-Z]{2,6}(?:USD|USDT)?)\b', q.upper())
    common_words = {"AND", "THE", "FOR", "BUY", "SELL", "HOLD", "HOT", "WARM", "COLD", "RUN", "ANY"}
    tickers = [t for t in tickers if t not in common_words]
    if tickers:
        sym = tickers[0]
        is_crypto = any(sym.endswith(sfx) for sfx in ("USD", "USDT")) or len(sym) >= 6
        return {"category": "A", "symbol": sym, "asset_class": "crypto" if is_crypto else asset_class_hint}
    return {"category": "B"}


@app.post("/brain/query", response_model=BrainQueryResponse)
def brain_query(req: BrainQueryRequest, request: Request):
    """Classify a natural language trading query and return intent metadata or a synthesized answer.

    Category A: returns symbol + asset_class so the frontend can call /signal.
    Category B: synthesizes an answer from the user's cached signal feed.
    """
    user_id: str | None = getattr(request.state, "user_id", None)

    cfg = _effective_config(_dynamic_config)
    client = _or_client_for_query(cfg)

    if client is None:
        # No OpenRouter key — try regex classification only
        classification = _fallback_classify(req.query, req.asset_class_hint)
        if classification["category"] == "C":
            return BrainQueryResponse(
                category="C",
                symbol=classification.get("symbol"),
                asset_class=classification.get("asset_class", req.asset_class_hint),
                condition_type=classification.get("condition_type"),
                threshold=classification.get("threshold"),
            )
        if classification["category"] == "B":
            return BrainQueryResponse(
                category="B",
                text="OpenRouter API key is not configured. Cannot answer data queries without it.",
            )
        return BrainQueryResponse(
            category="A",
            symbol=classification.get("symbol"),
            asset_class=classification.get("asset_class", req.asset_class_hint),
        )

    # ── Step 1: Intent classification ─────────────────────────────────────────
    classify_messages = [
        {"role": "system", "content": _CLASSIFY_SYSTEM},
    ]
    # Include last 2 user/assistant turns for context-aware disambiguation
    for h in req.conversation_history[-4:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            classify_messages.append({"role": h["role"], "content": str(h.get("content", ""))[:400]})

    classify_messages.append({
        "role": "user",
        "content": f'Query: "{req.query}"\nDefault asset class context: {req.asset_class_hint}',
    })

    classification: dict = {}
    try:
        resp = client.chat.completions.create(
            model="google/gemini-2.5-flash-lite",
            max_tokens=80,
            temperature=0.0,
            messages=classify_messages,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if the model adds them despite instructions
        raw = raw.strip("`").lstrip("json").strip()
        classification = json.loads(raw)
    except Exception as exc:
        log.warning("brain/query classification failed (%s) — using regex fallback", exc)
        classification = _fallback_classify(req.query, req.asset_class_hint)

    category = classification.get("category", "B")

    if category == "A":
        symbol = str(classification.get("symbol", "")).upper().strip()
        asset_class = str(classification.get("asset_class", req.asset_class_hint))
        if not symbol or not any(c.isalpha() for c in symbol):
            return BrainQueryResponse(
                category="B",
                text="I couldn't identify a specific ticker symbol in your query. Try typing the symbol directly, e.g. \"Analyse AAPL\" or \"BTCUSD\".",
            )
        return BrainQueryResponse(category="A", symbol=symbol, asset_class=asset_class)

    if category == "C":
        symbol     = str(classification.get("symbol", "")).upper().strip()
        asset_class = str(classification.get("asset_class", req.asset_class_hint))
        ctype      = classification.get("condition_type")
        threshold  = classification.get("threshold")
        if not symbol or ctype not in ("price_above", "price_below") or threshold is None:
            return BrainQueryResponse(
                category="B",
                text="I understood you want a price alert, but couldn't extract the ticker, condition, and threshold. Try: \"Alert me when AAPL drops below 180\" or \"Notify me if NVDA goes above 200\".",
            )
        return BrainQueryResponse(
            category="C",
            symbol=symbol,
            asset_class=asset_class,
            condition_type=ctype,
            threshold=float(threshold),
        )

    # ── Step 2: Category B — synthesize answer from signal cache ──────────────
    uid = user_id or "system"
    _see_system = (
        uid == "system"
        or (not _OWNER_USER_ID)
        or (_OWNER_USER_ID and uid == _OWNER_USER_ID)
    )
    cached = [
        v for v in _signal_cache.values()
        if v.get("_uid", "system") == uid
        or (_see_system and v.get("_uid", "system") == "system")
    ]
    # Sort newest first, cap at 20 signals to control token cost
    cached_sorted = sorted(cached, key=lambda s: s.get("generated_at", ""), reverse=True)[:20]

    if not cached_sorted:
        return BrainQueryResponse(
            category="B",
            text="No signals in the cache yet. Generate some signals from the Signals page or Brain Console first, then ask again.",
        )

    # Slim down each signal record for the LLM context (keep only key fields)
    def _slim(s: dict) -> dict:
        return {k: s[k] for k in ("symbol", "asset_class", "action", "tier", "confidence",
                                   "rationale", "generated_at", "regime_label")
                if k in s}

    signals_json = json.dumps([_slim(s) for s in cached_sorted], indent=None)

    synth_messages = [{"role": "system", "content": _SYNTHESIZE_SYSTEM}]
    for h in req.conversation_history[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            synth_messages.append({"role": h["role"], "content": str(h.get("content", ""))[:600]})
    synth_messages.append({
        "role": "user",
        "content": f"Recent signals:\n{signals_json}\n\nQuestion: {req.query}",
    })

    try:
        synth_resp = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324",
            max_tokens=200,
            temperature=0.3,
            messages=synth_messages,
        )
        text = synth_resp.choices[0].message.content.strip()
    except Exception as exc:
        log.error("brain/query synthesis failed: %s", exc)
        text = f"Could not synthesize an answer: {exc}"

    return BrainQueryResponse(category="B", text=text)


# ── Category C: watch rule management endpoints ────────────────────────────────

class WatchRuleRequest(BaseModel):
    symbol: str         = Field(..., min_length=1, max_length=20)
    asset_class: str    = Field("stock")
    condition_type: str = Field(...)
    threshold: float    = Field(...)
    trigger_debate: bool = Field(True)


@app.post("/brain/rule")
def create_watch_rule(body: WatchRuleRequest, request: Request):
    """Register a price-watch rule for the authenticated user."""
    from brain.watch_rules import add_rule as _add_rule, CONDITION_TYPES as _CT
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "Authentication required to create watch rules")
    if body.condition_type not in _CT:
        raise HTTPException(400, f"condition_type must be one of: {sorted(_CT)}")

    max_rules = int(_dynamic_config.get("max_watch_rules", 10))
    try:
        rule = _add_rule(
            uid=user_id,
            symbol=body.symbol,
            asset_class=body.asset_class,
            condition_type=body.condition_type,
            threshold=body.threshold,
            trigger_debate=body.trigger_debate,
            max_rules=max_rules,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return rule


@app.get("/brain/rules")
def list_watch_rules(request: Request):
    """List active (non-triggered) watch rules for the authenticated user."""
    from brain.watch_rules import list_rules as _list_rules
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "Authentication required")
    return {"rules": _list_rules(user_id)}


@app.delete("/brain/rule/{rule_id}")
def delete_watch_rule(rule_id: str, request: Request):
    """Delete a watch rule by ID."""
    from brain.watch_rules import delete_rule as _delete_rule
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "Authentication required")
    ok = _delete_rule(user_id, rule_id)
    if not ok:
        raise HTTPException(404, "Rule not found or does not belong to this user")
    return {"deleted": True}


@app.get("/brain/alerts")
def list_watch_alerts(request: Request, include_delivered: bool = False):
    """List pending (or all) alerts for the authenticated user."""
    from brain.watch_rules import list_alerts as _list_alerts
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "Authentication required")
    return {"alerts": _list_alerts(user_id, include_delivered=include_delivered)}


@app.post("/brain/rules/evaluate")
def evaluate_watch_rules_endpoint(request: Request, symbol: str, price: float):
    """Orchestrator-facing endpoint: evaluate watch rules for symbol at price.

    Called after each signal cycle with the symbol's current price.
    Auth: X-Api-Key (machine-to-machine) only — browser JWT callers are rejected
    to prevent forged prices from firing other users' alerts.
    """
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        raise HTTPException(403, "This endpoint is reserved for internal orchestrator use (X-Api-Key required)")
    from brain.watch_rules import evaluate_rules as _evaluate
    triggered = _evaluate(symbol=symbol, price=price)
    return {"evaluated": symbol, "price": price, "triggered": len(triggered)}


@app.get("/brain/alerts/stream")
async def watch_alerts_stream(request: Request):
    """SSE stream: pushes new watch alerts to the browser as they fire.

    Uses fetch + ReadableStream on the client (not EventSource) to support
    the X-Session-Id authentication header.

    Each event is a JSON-encoded alert object.  Alerts are marked delivered
    after transmission so they are not re-sent on reconnect.
    The stream sends a keep-alive comment every 15 seconds.
    """
    import asyncio
    from fastapi.responses import StreamingResponse
    from brain.watch_rules import list_alerts as _list_alerts, mark_delivered as _mark_delivered

    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "Authentication required for alert stream")

    async def _event_generator():
        try:
            heartbeat = 0
            while True:
                if await request.is_disconnected():
                    break

                pending = _list_alerts(user_id, include_delivered=False)
                if pending:
                    ids = []
                    for alert in pending:
                        payload = json.dumps(alert, default=str)
                        yield f"data: {payload}\n\n"
                        ids.append(alert["alert_id"])
                    _mark_delivered(user_id, ids)

                heartbeat += 5
                if heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    heartbeat = 0

                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class ExecuteRequest(BaseModel):
    symbol: str
    asset_class: str = Field(..., description="'stock' or 'crypto'")
    action: str = Field(..., description="'BUY' or 'SELL'")
    suggested_position_pct: float = Field(0.05, ge=0.001, le=0.20)
    stop_loss_pct: float = Field(0.02, ge=0.005, le=0.20)
    take_profit_pct: float = Field(0.05, ge=0.01, le=0.50)
    qty: float = Field(0.0, ge=0.0, description="Fixed share/unit count. 0 = use notional (equity × position_pct)")


def _execute_order(
    broker,
    exec_eff: dict, cfg, signal, sl_pct: float, tp_pct: float,
    source: str = "api",
    user_id: str | None = None,
) -> dict:
    """Run the execution engine for a resolved TradingSignal. Raises HTTPException on failure.

    Shared by /execute and /webhook/tradingview so both routes use identical execution
    logic — no drift risk from duplicated code paths.
    broker is a BrokerAdapter (currently always AlpacaBrokerAdapter).
    """
    try:
        if signal.asset_class == "stock":
            from execution.stock.engine import StockExecutionEngine

            # Pre-flight: block BUY if already at max_exposure_pct or if an open
            # order already exists for this symbol (idempotency guard against restarts).
            if signal.action == "BUY":
                _acct      = broker.get_account()
                _equity_pf = _acct.equity
                if _equity_pf <= 0:
                    raise HTTPException(status_code=409, detail="Account has no equity.")
                try:
                    # Idempotency: reject if a same-symbol BUY order is already pending at Alpaca.
                    _open_orders = broker.get_orders(status="open", limit=100)
                    for _ord in _open_orders:
                        if _ord.symbol == signal.symbol and _ord.side.upper() == "BUY":
                            raise HTTPException(
                                status_code=409,
                                detail=f"Duplicate order blocked: a BUY order for {signal.symbol} is already open (id={_ord.order_id}). Restart-safe deduplication.",
                            )
                    _positions_pf = broker.get_all_positions()
                    _deployed_pf  = sum(abs(p.market_value) for p in _positions_pf)
                    # Use buying_power (reflects pending orders and margin correctly) for the
                    # exposure check. Fall back to equity-minus-deployed if unavailable.
                    _buying_power = _acct.buying_power if _acct.buying_power > 0 else max(0.0, _equity_pf - _deployed_pf)
                    if _deployed_pf / _equity_pf >= exec_eff["max_exposure_pct"]:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                f"Max exposure reached: {_deployed_pf/_equity_pf*100:.0f}% of equity "
                                f"is deployed (limit {exec_eff['max_exposure_pct']*100:.0f}%). "
                                "Close or take profit on existing positions to free capital."
                            ),
                        )
                except HTTPException:
                    raise
                except Exception:
                    pass  # fall through if positions fetch fails

            market = broker.get_market_data_client("stock")
            bars   = market.get_bars(signal.symbol, days=30)
            bars_highs  = [b.high  for b in bars]
            bars_lows   = [b.low   for b in bars]
            bars_closes = [b.close for b in bars]

            if not bars_closes:
                quote = market.get_latest_quote(signal.symbol)
                if quote and quote.mid > 0:
                    bars_closes = [quote.mid]
                    bars_highs  = [quote.ask or quote.mid]
                    bars_lows   = [quote.bid or quote.mid]
                else:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Could not fetch market price for {signal.symbol} — data feed unavailable",
                    )
            else:
                _exec_quote = market.get_latest_quote(signal.symbol)
                if _exec_quote and _exec_quote.mid > 0:
                    bars_closes[-1] = _exec_quote.mid
                    bars_highs[-1]  = max(bars_highs[-1], _exec_quote.mid)
                    bars_lows[-1]   = min(bars_lows[-1],  _exec_quote.mid)
                    log.debug(
                        "Execute live price inject: %s mid=%.4f (bar close was %.4f)",
                        signal.symbol, _exec_quote.mid, bars[-1].close if bars else 0,
                    )

            engine = StockExecutionEngine(
                broker=broker,
                max_position_pct=exec_eff["max_position_pct"],
                circuit_breaker_drawdown=exec_eff["circuit_breaker_drawdown"],
                trailing_stop_pct=exec_eff["trailing_stop_pct"],
                atr_multiplier=exec_eff["atr_multiplier"],
                atr_stop_floor=exec_eff["atr_stop_floor"],
                atr_stop_cap=exec_eff["atr_stop_cap"],
            )
            result = engine.execute(signal, bars_highs, bars_lows, bars_closes)

            if result is None:
                raise HTTPException(
                    status_code=409,
                    detail="Order blocked by risk controls (circuit breaker, sizing, or invalid price)",
                )

            _write_audit(result.symbol, result.action, result.qty,
                         result.qty * result.submitted_price, source, result.order_id)
            try:
                from brain.order_history import record_from_broker_result
                record_from_broker_result(
                    order_id=result.order_id,
                    symbol=result.symbol,
                    side=result.action,
                    order_type="bracket",
                    qty=result.qty,
                    submitted_at=result.timestamp.isoformat() if result.timestamp else None,
                    broker=getattr(broker, "broker_name", result.exchange or "unknown"),
                    stop_price=result.stop_price or None,
                    take_profit_price=result.take_profit_price or None,
                    source=source,
                    user_id=user_id or "system",
                )
            except Exception as _rec_exc:
                log.debug("Order history record failed (non-fatal): %s", _rec_exc)
            return {
                "order_id":          result.order_id,
                "status":            "submitted",
                "symbol":            result.symbol,
                "action":            result.action,
                "qty":               result.qty,
                "submitted_price":   result.submitted_price,
                "stop_price":        result.stop_price,
                "take_profit_price": result.take_profit_price,
                "exchange":          result.exchange,
                "stop_pct":          sl_pct,
                "target_pct":        tp_pct,
            }

        else:  # crypto
            from execution.crypto.engine import CryptoExecutionEngine

            engine = CryptoExecutionEngine(
                broker=broker,
                max_position_pct=exec_eff["max_position_pct"],
                max_crypto_allocation_pct=exec_eff["max_crypto_allocation_pct"],
                cash_buffer=cfg.crypto_cash_buffer,
                min_notional_usd=cfg.crypto_min_notional_usd,
                fallback_equity_usd=cfg.crypto_fallback_equity_usd,
            )
            result = engine.execute(signal)

            if result is None:
                raise HTTPException(
                    status_code=409,
                    detail="Order blocked by risk controls (crypto cap, sizing, or invalid price)",
                )

            _write_audit(result.symbol, result.action, result.qty,
                         result.qty * result.submitted_price, source, result.order_id)
            try:
                from brain.order_history import record_from_broker_result
                record_from_broker_result(
                    order_id=result.order_id,
                    symbol=result.symbol,
                    side=result.action,
                    order_type="market",
                    qty=result.qty,
                    submitted_at=result.timestamp.isoformat() if result.timestamp else None,
                    broker=getattr(broker, "broker_name", result.exchange or "unknown"),
                    stop_price=result.stop_price or None,
                    take_profit_price=result.take_profit_price or None,
                    source=source,
                    user_id=user_id or "system",
                )
            except Exception as _rec_exc:
                log.debug("Order history record failed (non-fatal): %s", _rec_exc)
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
        log.error("Trade execution failed for %s: %s", signal.symbol, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Execution failed: {exc}")


@app.post("/execute")
def execute_trade(req: ExecuteRequest, request: Request):
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
    _exec_user_id = getattr(request.state, "user_id", None)

    # ── Demo account block ────────────────────────────────────────────────────
    if _DEMO_USER_ID and _exec_user_id == _DEMO_USER_ID:
        raise HTTPException(403, "Trade execution is disabled for the demo account")

    # ── Ownership guard ───────────────────────────────────────────────────────
    _exec_is_owner = (not _OWNER_USER_ID) or (_OWNER_USER_ID and _exec_user_id == _OWNER_USER_ID)
    if _exec_user_id and not _exec_is_owner and not _jwt_user_has_own_alpaca(_exec_user_id, cfg):
        raise HTTPException(403, "No broker configured — add your API key in Settings → Broker")

    from brain.risk_config import get_effective_risk_for_user as _exec_risk_fn
    _exec_eff = _exec_risk_fn(_exec_user_id, _effective_config(cfg))

    # The orchestrator already applies all risk adjustments before sending this request.
    # Always use request values; fall back to cache only for the rationale (informational).
    _exec_uid = _exec_user_id or "system"
    cached  = _signal_cache.get(f"{_exec_uid}::{req.symbol.upper()}", {})
    sl_pct  = req.stop_loss_pct
    tp_pct  = req.take_profit_pct

    signal = TradingSignal(
        symbol=req.symbol.upper(),
        asset_class=req.asset_class,  # type: ignore[arg-type]
        action=req.action,            # type: ignore[arg-type]
        confidence=1.0,
        rationale=cached.get("rationale", "Manual execute via API"),
        suggested_position_pct=req.suggested_position_pct,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
    )

    broker = _resolve_broker(_exec_user_id, cfg)
    return _execute_order(broker, _exec_eff, cfg, signal, sl_pct, tp_pct, user_id=_exec_user_id)


@app.get("/portfolio")
def get_portfolio(request: Request):
    """Return current portfolio state (positions, equity, P&L).

    Returns a zeroed default with fetch_error set if credentials are missing or
    the exchange API call fails — the dashboard surfaces this as an error banner
    instead of silently showing $0 / 0 positions.
    """
    from config import get_settings
    from data.portfolio import PortfolioFetcher, PortfolioState
    from datetime import timezone

    cfg = get_settings()
    _pf_user_id = getattr(request.state, "user_id", None)
    fetch_error: str | None = None

    # ── Demo account intercept ────────────────────────────────────────────────
    if _DEMO_USER_ID and _pf_user_id == _DEMO_USER_ID:
        from brain.demo_store import load_demo_snapshot
        snap = load_demo_snapshot()
        if snap and snap.get("portfolio"):
            return snap["portfolio"]
        from datetime import timezone
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": 0.0, "cash": 0.0, "buying_power": 0.0,
            "daily_pnl": 0.0, "daily_pnl_pct": 0.0,
            "crypto_allocation_pct": 0.0, "positions": [],
            "fetch_error": "Demo snapshot not yet taken — ask the owner to generate one.",
        }

    # Non-owner JWT users who have not configured their own Alpaca credentials must
    # not fall through to the system account (the owner's live trading account).
    # The owner is identified by OWNER_USER_ID. When unset, legacy behaviour applies
    # (all JWT users can use system creds — single-user deployment mode).
    _pf_is_owner = (not _OWNER_USER_ID) or (_OWNER_USER_ID and _pf_user_id == _OWNER_USER_ID)
    if _pf_user_id and not _pf_is_owner and not _jwt_user_has_own_alpaca(_pf_user_id, cfg):
        state = PortfolioState(timestamp=datetime.now(timezone.utc), equity=0.0, cash=0.0)
        return {
            "timestamp":             state.timestamp.isoformat(),
            "equity":                0.0, "cash": 0.0, "buying_power": 0.0,
            "daily_pnl":             0.0, "daily_pnl_pct": 0.0,
            "crypto_allocation_pct": 0.0, "positions": [],
            "fetch_error": "No broker configured — add your Alpaca API key in Settings → Broker",
        }

    _pf_ak, _pf_sk, _pf_base_url, _ = _resolve_alpaca_creds(_pf_user_id, cfg)

    if not _pf_ak:
        fetch_error = "ALPACA_API_KEY is not configured — check Settings"
        log.warning("/portfolio: no Alpaca API key — returning empty state")
        state = PortfolioState(timestamp=datetime.now(timezone.utc), equity=0.0, cash=0.0)
    else:
        from broker.adapters.alpaca import AlpacaBrokerAdapter
        portfolio_fetcher = PortfolioFetcher(AlpacaBrokerAdapter(_pf_ak, _pf_sk, _pf_base_url))
        try:
            state = portfolio_fetcher.snapshot()
        except Exception as exc:
            log.error("Portfolio fetch failed: %s", exc, exc_info=True)
            fetch_error = f"Portfolio fetch failed: {exc}"
            state = PortfolioState(timestamp=datetime.now(timezone.utc), equity=0.0, cash=0.0)

    return {
        "timestamp":             state.timestamp.isoformat(),
        "equity":                state.equity,
        "cash":                  state.cash,
        "buying_power":          state.buying_power,
        "daily_pnl":             state.daily_pnl,
        "daily_pnl_pct":         state.daily_pnl_pct,
        "open_pnl_today":        state.open_pnl_today,
        "realized_pnl_today":    state.realized_pnl_today,
        "crypto_allocation_pct": state.crypto_allocation_pct,
        "fetch_error":           fetch_error,
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


@app.get("/orders")
def get_orders(request: Request, status: str = "open"):
    """Return open or recent orders from Alpaca.

    status=open   — pending / partially-filled / new (default)
    status=all    — last 50 orders regardless of fill state
    status=closed — filled, cancelled, expired

    Positions only appear after an order is FULLY FILLED. This endpoint
    exposes the order queue so the dashboard can show submitted-but-unfilled
    trades that would otherwise be invisible to the user.
    """
    if status not in ("open", "all", "closed"):
        raise HTTPException(400, "status must be open, all, or closed")

    from config import get_settings
    cfg = get_settings()
    _ord_user_id = getattr(request.state, "user_id", None)

    # ── Demo account intercept ────────────────────────────────────────────────
    if _DEMO_USER_ID and _ord_user_id == _DEMO_USER_ID:
        from brain.demo_store import load_demo_snapshot
        snap = load_demo_snapshot()
        if snap:
            return snap.get("orders", {"orders": []})
        return {"orders": []}

    # Non-owner JWT users with no personal broker credentials must not see system account orders.
    _ord_is_owner = (not _OWNER_USER_ID) or (_OWNER_USER_ID and _ord_user_id == _OWNER_USER_ID)
    if _ord_user_id and not _ord_is_owner and not _jwt_user_has_own_alpaca(_ord_user_id, cfg):
        return {"orders": [], "fetch_error": "No broker configured — add your Alpaca API key in Settings → Broker"}

    _ord_ak, _ord_sk, _ord_base_url, _ = _resolve_alpaca_creds(_ord_user_id, cfg)

    if not _ord_ak:
        return {"orders": [], "fetch_error": "ALPACA_API_KEY is not configured"}

    try:
        from broker.adapters.alpaca import AlpacaBrokerAdapter
        broker = AlpacaBrokerAdapter(_ord_ak, _ord_sk, _ord_base_url)
        orders = broker.get_orders(status=status, limit=50)
        result = [
            {
                "order_id":         o.order_id,
                "client_order_id":  o.client_order_id,
                "symbol":           o.symbol,
                "side":             o.side,
                "order_type":       o.order_type,
                "qty":              o.qty,
                "filled_qty":       o.filled_qty,
                "status":           o.status,
                "submitted_at":     o.submitted_at.isoformat() if o.submitted_at else None,
                "filled_at":        o.filled_at.isoformat() if o.filled_at else None,
                "limit_price":      o.limit_price,
                "stop_price":       o.stop_price,
                "filled_avg_price": o.filled_avg_price,
            }
            for o in orders
        ]
        # Passive backfill: record fetched orders into the audit store (non-blocking)
        try:
            from brain.order_history import record_from_broker_result
            _passive_uid = _ord_user_id or "system"
            for o in orders:
                if o.order_id:
                    record_from_broker_result(
                        order_id=o.order_id,
                        symbol=o.symbol,
                        side=o.side,
                        order_type=o.order_type or "market",
                        qty=float(o.qty or 0),
                        filled_qty=float(o.filled_qty or 0),
                        status=o.status or "unknown",
                        submitted_at=o.submitted_at.isoformat() if o.submitted_at else None,
                        filled_at=o.filled_at.isoformat() if o.filled_at else None,
                        broker="alpaca",
                        stop_price=o.stop_price,
                        filled_avg_price=o.filled_avg_price,
                        source="broker_sync",
                        user_id=_passive_uid,
                    )
        except Exception as _bp_exc:
            log.debug("Passive order backfill failed (non-fatal): %s", _bp_exc)
        return {"orders": result, "fetch_error": None}
    except Exception as exc:
        log.error("Orders fetch failed: %s", exc, exc_info=True)
        return {"orders": [], "fetch_error": f"Orders fetch failed: {exc}"}


# ── Order history (persistent audit store) ────────────────────────────────────

# ── Kraken endpoints ─────────────────────────────────────────────────────────

class KrakenSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key:    str = ""
    api_secret: str = ""


@app.get("/kraken-settings")
def get_kraken_settings(request: Request):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    from brain.kraken_creds import load_kraken_settings
    row = load_kraken_settings(user_id)
    configured = bool(row.get("api_key_enc") and row.get("api_secret_enc"))
    # Return a non-secret prefix of the key name for display
    raw_key = row.get("api_key_enc", "")
    return {"configured": configured, "key_prefix": raw_key[:4] + "…" if configured else ""}


@app.post("/kraken-settings")
def save_kraken_settings_endpoint(request: Request, payload: KrakenSettingsPayload):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    if not payload.api_key and not payload.api_secret:
        raise HTTPException(400, "Provide at least one of api_key or api_secret")
    enc_key = _get_enc_key()
    from brain.kraken_creds import save_kraken_settings
    save_kraken_settings(user_id, payload.api_key, payload.api_secret, enc_key)
    return {"ok": True}


@app.delete("/kraken-settings")
def delete_kraken_settings_endpoint(request: Request):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    from brain.kraken_creds import delete_kraken_settings
    delete_kraken_settings(user_id)
    return {"ok": True}


# ── Coinbase endpoints ────────────────────────────────────────────────────────

class CoinbaseSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key_name: str = ""
    private_key:  str = ""


@app.get("/coinbase-settings")
def get_coinbase_settings(request: Request):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    from brain.coinbase_creds import load_coinbase_settings
    row = load_coinbase_settings(user_id)
    configured = bool(row.get("api_key_name") and row.get("private_key_enc"))
    key_name   = row.get("api_key_name", "")
    return {"configured": configured, "api_key_name": key_name if configured else ""}


@app.post("/coinbase-settings")
def save_coinbase_settings_endpoint(request: Request, payload: CoinbaseSettingsPayload):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    if not payload.api_key_name and not payload.private_key:
        raise HTTPException(400, "Provide api_key_name and private_key")
    enc_key = _get_enc_key()
    from brain.coinbase_creds import save_coinbase_settings
    save_coinbase_settings(user_id, payload.api_key_name, payload.private_key, enc_key)
    return {"ok": True}


@app.delete("/coinbase-settings")
def delete_coinbase_settings_endpoint(request: Request):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    from brain.coinbase_creds import delete_coinbase_settings
    delete_coinbase_settings(user_id)
    return {"ok": True}


# ── TradeStation OAuth + settings endpoints ──────────────────────────────────

@app.get("/tradestation-auth/url")
def get_tradestation_auth_url(request: Request):
    """Return a one-time OAuth URL for the user to authorise TradeStation."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    import secrets
    cfg = get_settings()
    client_id    = getattr(cfg, "tradestation_client_id",   "") or os.environ.get("TRADESTATION_CLIENT_ID",   "")
    redirect_uri = getattr(cfg, "tradestation_redirect_uri","") or os.environ.get("TRADESTATION_REDIRECT_URI","")
    if not client_id or not redirect_uri:
        raise HTTPException(503, "TradeStation app not configured — set TRADESTATION_CLIENT_ID and TRADESTATION_REDIRECT_URI in Railway")

    state = secrets.token_urlsafe(32)
    _TS_OAUTH_STATES[state] = (user_id, _time.time() + _TS_STATE_TTL)

    import urllib.parse as _up
    params = _up.urlencode({
        "response_type": "code",
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "audience":      "https://api.tradestation.com",
        "scope":         "openid profile offline_access MarketData ReadAccount Trade",
        "state":         state,
    })
    return {"url": f"https://signin.tradestation.com/authorize?{params}"}


@app.get("/tradestation-auth/callback")
def tradestation_auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """OAuth callback — exchanges code for tokens and redirects to the dashboard."""
    from fastapi.responses import RedirectResponse
    cfg = get_settings()
    redirect_target = (
        getattr(cfg, "tradestation_redirect_target", "")
        or os.environ.get("TRADESTATION_REDIRECT_TARGET", "/")
    )
    if error:
        return RedirectResponse(url=f"{redirect_target}?ts_error={error}")

    entry = _TS_OAUTH_STATES.pop(state, None)
    if not entry:
        return RedirectResponse(url=f"{redirect_target}?ts_error=invalid_state")
    user_id, exp = entry
    if _time.time() > exp:
        return RedirectResponse(url=f"{redirect_target}?ts_error=state_expired")

    client_id     = getattr(cfg, "tradestation_client_id",     "") or os.environ.get("TRADESTATION_CLIENT_ID",     "")
    client_secret = getattr(cfg, "tradestation_client_secret", "") or os.environ.get("TRADESTATION_CLIENT_SECRET", "")
    redirect_uri  = getattr(cfg, "tradestation_redirect_uri",  "") or os.environ.get("TRADESTATION_REDIRECT_URI",  "")

    import httpx as _hx
    try:
        resp = _hx.post(
            "https://signin.tradestation.com/oauth/token",
            data={
                "grant_type":    "authorization_code",
                "client_id":     client_id,
                "client_secret": client_secret,
                "code":          code,
                "redirect_uri":  redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        resp.raise_for_status()
        td = resp.json()
    except Exception as exc:
        log.warning("TradeStation OAuth callback failed: %s", exc)
        return RedirectResponse(url=f"{redirect_target}?ts_error=token_exchange_failed")

    enc_key    = _get_enc_key()
    expires_in = int(td.get("expires_in", 1200))
    from brain.tradestation_creds import save_ts_tokens
    save_ts_tokens(
        user_id, enc_key,
        access_token=td.get("access_token", ""),
        refresh_token=td.get("refresh_token", ""),
        access_token_exp=_time.time() + expires_in,
        refresh_token_exp=_time.time() + 365 * 86400,  # TS refresh tokens don't expire by default
    )
    return RedirectResponse(url=f"{redirect_target}?ts_connected=1")


@app.get("/tradestation-settings")
def get_tradestation_settings(request: Request):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    enc_key = _get_enc_key()
    from brain.tradestation_creds import load_ts_tokens
    tokens = load_ts_tokens(user_id, enc_key)
    if tokens is None:
        return {"connected": False, "account_number": "", "paper_mode": False}
    return {
        "connected":      tokens.configured,
        "account_number": tokens.account_number,
        "paper_mode":     tokens.paper_mode,
        "access_expires": tokens.access_token_exp,
    }


class TSAccountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_number: str


@app.post("/tradestation-settings/account")
def set_tradestation_account(request: Request, payload: TSAccountPayload):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    if not payload.account_number.strip():
        raise HTTPException(400, "account_number is required")
    from brain.tradestation_creds import save_ts_account
    save_ts_account(user_id, payload.account_number.strip())
    return {"ok": True}


@app.delete("/tradestation-settings")
def delete_tradestation_settings(request: Request):
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT required")
    from brain.tradestation_creds import delete_ts_tokens
    delete_ts_tokens(user_id)
    return {"ok": True}


@app.get("/orders/history")
def get_order_history(request: Request, days: int = 365):
    """Return stored order history (up to 1 year) from the persistent audit store.

    Unlike GET /orders, this is not limited to 50 and covers all brokers and sources.
    Requires JWT authentication.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for order history")
    if not (1 <= days <= 365):
        raise HTTPException(400, "days must be between 1 and 365")
    from brain.order_history import get_all_orders
    orders = get_all_orders(days=days, user_id=user_id)
    return {"orders": orders, "total": len(orders), "days": days}


@app.get("/orders/history/export")
def export_order_history(request: Request, format: str = "csv", days: int = 365):
    """Export order history as CSV or PDF attachment.

    ?format=csv  — returns a UTF-8 CSV file
    ?format=pdf  — returns a PDF file (requires fpdf2)
    ?days=N      — limit to last N days (max 365)
    Requires JWT authentication.
    """
    from fastapi.responses import Response, StreamingResponse
    import io

    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required for order history export")
    if format not in ("csv", "pdf"):
        raise HTTPException(400, "format must be csv or pdf")
    if not (1 <= days <= 365):
        raise HTTPException(400, "days must be between 1 and 365")

    from brain.order_history import get_all_orders
    orders = get_all_orders(days=days, user_id=user_id)

    if format == "csv":
        import csv
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[
            "submitted_at", "symbol", "side", "order_type", "qty", "filled_qty",
            "status", "filled_at", "broker", "stop_price", "take_profit_price",
            "filled_avg_price", "notional", "source", "order_id",
        ], extrasaction="ignore")
        writer.writeheader()
        for o in orders:
            writer.writerow(o)
        content = buf.getvalue().encode("utf-8")
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=\"order_history_{days}d.csv\""},
        )

    # PDF
    try:
        from fpdf import FPDF
    except ImportError:
        raise HTTPException(503, "PDF export requires fpdf2 — install it with: pip install fpdf2")

    from datetime import date as _date

    COLS = [
        ("Date",    38),
        ("Symbol",  18),
        ("Side",    12),
        ("Type",    16),
        ("Qty",     14),
        ("Filled",  14),
        ("Status",  20),
        ("Broker",  18),
        ("Source",  20),
        ("Avg $",   20),
        ("Stop $",  20),
        ("TP $",    20),
    ]

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(10, 10, 10)

    def _header_page():
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(255, 255, 255)
        pdf.set_fill_color(30, 41, 59)   # slate-800
        pdf.cell(0, 9, "TradeAgent — Order Audit History", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(148, 163, 184)  # slate-400
        pdf.cell(0, 5, f"Exported {_date.today().isoformat()} · Last {days} days · {len(orders)} orders", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        # Column headers
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(200, 210, 220)
        pdf.set_fill_color(15, 23, 42)   # slate-900
        for col, w in COLS:
            pdf.cell(w, 6, col, border=0, fill=True, align="C")
        pdf.ln()
        pdf.set_text_color(226, 232, 240)  # slate-200

    pdf.add_page()
    _header_page()

    def _fmt(val, prefix="") -> str:
        if val is None:
            return "—"
        if isinstance(val, float):
            return f"{prefix}{val:,.4f}".rstrip("0").rstrip(".")
        return str(val)

    def _short_date(iso: str | None) -> str:
        if not iso:
            return "—"
        try:
            return iso[:16].replace("T", " ")
        except Exception:
            return str(iso)

    row_even = (30, 41, 59)    # slate-700 tint
    row_odd  = (15, 23, 42)    # slate-900 tint

    for i, o in enumerate(orders):
        if pdf.get_y() > 185:
            pdf.add_page()
            _header_page()
        fill_color = row_even if i % 2 == 0 else row_odd
        pdf.set_fill_color(*fill_color)
        side = str(o.get("side", "")).upper()
        pdf.set_text_color(52, 211, 153) if side == "BUY" else pdf.set_text_color(248, 113, 113)
        pdf.set_font("Helvetica", "B", 7)
        # Side column
        pdf.cell(COLS[0][1], 5, _short_date(o.get("submitted_at")), fill=True, align="L")
        pdf.cell(COLS[1][1], 5, str(o.get("symbol", "")), fill=True, align="C")
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(COLS[2][1], 5, side, fill=True, align="C")
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(226, 232, 240)
        pdf.cell(COLS[3][1], 5, str(o.get("order_type", "")),       fill=True, align="C")
        pdf.cell(COLS[4][1], 5, _fmt(o.get("qty")),                  fill=True, align="R")
        pdf.cell(COLS[5][1], 5, _fmt(o.get("filled_qty")),           fill=True, align="R")
        status = str(o.get("status", ""))
        if status in ("filled",):
            pdf.set_text_color(52, 211, 153)
        elif status in ("canceled", "cancelled", "expired"):
            pdf.set_text_color(148, 163, 184)
        elif status in ("rejected",):
            pdf.set_text_color(248, 113, 113)
        else:
            pdf.set_text_color(251, 191, 36)
        pdf.cell(COLS[6][1], 5, status.capitalize(),              fill=True, align="C")
        pdf.set_text_color(226, 232, 240)
        pdf.cell(COLS[7][1], 5, str(o.get("broker", "")),            fill=True, align="C")
        pdf.cell(COLS[8][1], 5, str(o.get("source", "")),            fill=True, align="C")
        pdf.cell(COLS[9][1], 5,  _fmt(o.get("filled_avg_price"), "$"), fill=True, align="R")
        pdf.cell(COLS[10][1], 5, _fmt(o.get("stop_price"),      "$"), fill=True, align="R")
        pdf.cell(COLS[11][1], 5, _fmt(o.get("take_profit_price"), "$"), fill=True, align="R")
        pdf.ln()

    pdf.set_y(-10)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, f"Page {pdf.page_no()} — TradeAgent Audit Export — Retention: 1 year", align="C")

    pdf_bytes = pdf.output()
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"order_history_{days}d.pdf\""},
    )


@app.get("/orders/history/years")
def get_order_history_years(request: Request):
    """Return list of past complete calendar years that have stored orders.

    Used by the dashboard Archive panel to show which years have downloadable data.
    Requires JWT authentication.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required")
    from brain.order_history import get_available_years
    years = get_available_years(user_id=user_id)
    return {"years": years}


@app.get("/orders/archive/{year}")
def download_archive_zip(request: Request, year: int):
    """Download a ZIP archive of all orders for the given past calendar year.

    The ZIP contains two files:
      orders_{year}.csv — machine-readable data
      orders_{year}.pdf — formatted audit report

    Only past complete years are allowed (not the current year).
    Requires JWT authentication.
    """
    from fastapi.responses import Response as _Response
    import io, csv, zipfile
    from datetime import datetime as _dt, timezone as _tz, date as _date

    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(403, "JWT authentication required")

    current_year = _dt.now(_tz.utc).year
    if year >= current_year:
        raise HTTPException(400, "Only past calendar years can be archived")
    if year < 2020:
        raise HTTPException(400, "Year out of supported range")

    from brain.order_history import get_orders_for_year
    orders = get_orders_for_year(year, user_id=user_id)

    # ── CSV ───────────────────────────────────────────────────────────────────
    csv_buf = io.StringIO()
    csv_writer = csv.DictWriter(csv_buf, fieldnames=[
        "submitted_at", "symbol", "side", "order_type", "qty", "filled_qty",
        "status", "filled_at", "broker", "stop_price", "take_profit_price",
        "filled_avg_price", "notional", "source", "order_id",
    ], extrasaction="ignore")
    csv_writer.writeheader()
    for o in orders:
        csv_writer.writerow(o)
    csv_bytes = csv_buf.getvalue().encode("utf-8")

    # ── PDF ───────────────────────────────────────────────────────────────────
    pdf_bytes: bytes = b""
    try:
        from fpdf import FPDF

        COLS = [
            ("Date",    38), ("Symbol",  18), ("Side",    12), ("Type",    16),
            ("Qty",     14), ("Filled",  14), ("Status",  20), ("Broker",  18),
            ("Source",  20), ("Avg $",   20), ("Stop $",  20), ("TP $",    20),
        ]

        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=12)
        pdf.set_margins(10, 10, 10)

        def _arch_header():
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(255, 255, 255)
            pdf.set_fill_color(30, 41, 59)
            pdf.cell(0, 9, f"TradeAgent — Order Archive {year}", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(148, 163, 184)
            pdf.cell(0, 5, f"Generated {_date.today().isoformat()} · {year} full year · {len(orders)} orders", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(200, 210, 220)
            pdf.set_fill_color(15, 23, 42)
            for col, w in COLS:
                pdf.cell(w, 6, col, border=0, fill=True, align="C")
            pdf.ln()
            pdf.set_text_color(226, 232, 240)

        pdf.add_page()
        _arch_header()

        def _fmt(val, prefix="") -> str:
            if val is None:
                return "—"
            if isinstance(val, float):
                return f"{prefix}{val:,.4f}".rstrip("0").rstrip(".")
            return str(val)

        def _short_date(iso) -> str:
            if not iso:
                return "—"
            try:
                return str(iso)[:16].replace("T", " ")
            except Exception:
                return str(iso)

        for i, o in enumerate(orders):
            if pdf.get_y() > 185:
                pdf.add_page()
                _arch_header()
            fill_color = (30, 41, 59) if i % 2 == 0 else (15, 23, 42)
            pdf.set_fill_color(*fill_color)
            side = str(o.get("side", "")).upper()
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(52, 211, 153) if side == "BUY" else pdf.set_text_color(248, 113, 113)
            pdf.cell(COLS[0][1], 5, _short_date(o.get("submitted_at")), fill=True, align="L")
            pdf.cell(COLS[1][1], 5, str(o.get("symbol", "")),           fill=True, align="C")
            pdf.set_font("Helvetica", "B", 7)
            pdf.cell(COLS[2][1], 5, side,                                fill=True, align="C")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(226, 232, 240)
            pdf.cell(COLS[3][1], 5, str(o.get("order_type", "")),        fill=True, align="C")
            pdf.cell(COLS[4][1], 5, _fmt(o.get("qty")),                  fill=True, align="R")
            pdf.cell(COLS[5][1], 5, _fmt(o.get("filled_qty")),           fill=True, align="R")
            status = str(o.get("status", ""))
            if status == "filled":
                pdf.set_text_color(52, 211, 153)
            elif status in ("canceled", "cancelled", "expired"):
                pdf.set_text_color(148, 163, 184)
            elif status == "rejected":
                pdf.set_text_color(248, 113, 113)
            else:
                pdf.set_text_color(251, 191, 36)
            pdf.cell(COLS[6][1], 5, status.capitalize(),                 fill=True, align="C")
            pdf.set_text_color(226, 232, 240)
            pdf.cell(COLS[7][1], 5, str(o.get("broker", "")),            fill=True, align="C")
            pdf.cell(COLS[8][1], 5, str(o.get("source", "")),            fill=True, align="C")
            pdf.cell(COLS[9][1],  5, _fmt(o.get("filled_avg_price"), "$"), fill=True, align="R")
            pdf.cell(COLS[10][1], 5, _fmt(o.get("stop_price"),      "$"), fill=True, align="R")
            pdf.cell(COLS[11][1], 5, _fmt(o.get("take_profit_price"), "$"), fill=True, align="R")
            pdf.ln()

        pdf.set_y(-10)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(0, 5, f"Page {pdf.page_no()} — TradeAgent Archive {year} — 1-year retention policy", align="C")
        pdf_bytes = bytes(pdf.output())

    except ImportError:
        pass  # PDF missing — ZIP will only contain CSV

    # ── Pack ZIP ──────────────────────────────────────────────────────────────
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"orders_{year}.csv", csv_bytes)
        if pdf_bytes:
            zf.writestr(f"orders_{year}.pdf", pdf_bytes)
    zip_buf.seek(0)

    return _Response(
        content=zip_buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=\"orders_archive_{year}.zip\""},
    )


def _alpaca_portfolio_history(broker, period: str, timeframe: str) -> list:
    """Fetch equity curve via the broker's native portfolio history API.

    This is the authoritative source — it captures realized P&L from closed
    trades, whereas the reconstruction approach can only see currently-open
    positions and produces a flat line when all trades are closed.

    Null equity values (pre-market / post-market gaps) are forward-filled
    so the chart never shows gaps.
    """
    return broker.get_portfolio_history(period, timeframe)


@app.get("/portfolio/history")
def get_portfolio_history(period: str = "1D", request: Request = None):
    """Return the equity curve for the requested period.

    Primary: Alpaca's native portfolio history API — captures realized P&L
    from closed trades, so the curve reflects what Alpaca actually shows.

    Fallback: position-reconstruction (cash + Σ qty×price) — used only if
    the Alpaca API fails or returns fewer than 2 points.

    1D  → 5-min bars during market hours (up to ~78 pts)
    1M  → daily bars, last 30 calendar days
    1Y  → daily bars, last 365 calendar days
    """
    if period not in ("1D", "1M", "1Y"):
        raise HTTPException(400, "period must be 1D, 1M, or 1Y")

    from config import get_settings
    cfg = get_settings()

    _hist_user_id = getattr(request.state, "user_id", None) if request else None

    # ── Demo account intercept ────────────────────────────────────────────────
    if _DEMO_USER_ID and _hist_user_id == _DEMO_USER_ID:
        from brain.demo_store import load_demo_snapshot
        snap = load_demo_snapshot()
        if snap:
            return snap.get("history", {}).get(period, [])
        return []

    # ── Ownership guard (mirrors /portfolio) ──────────────────────────────────
    _hist_is_owner = (not _OWNER_USER_ID) or (_OWNER_USER_ID and _hist_user_id == _OWNER_USER_ID)
    if _hist_user_id and not _hist_is_owner and not _jwt_user_has_own_alpaca(_hist_user_id, cfg):
        return []  # non-owner without personal broker → empty curve

    _hist_ak, _hist_sk, _hist_base_url, _hist_is_paper = _resolve_alpaca_creds(_hist_user_id, cfg)

    if not _hist_ak:
        return []

    # Alpaca API period/timeframe map
    alpaca_params = {
        "1D": ("1D",  "5Min"),
        "1M": ("1M",  "1D"),
        "1Y": ("1A",  "1D"),
    }
    alpaca_period, alpaca_tf = alpaca_params[period]

    # ── Try native broker portfolio history first ──────────────────────────────
    try:
        from broker.adapters.alpaca import AlpacaBrokerAdapter
        hist_broker = AlpacaBrokerAdapter(_hist_ak, _hist_sk, _hist_base_url)
        pts = _alpaca_portfolio_history(hist_broker, alpaca_period, alpaca_tf)
        if len(pts) >= 2:
            # 1D: Alpaca only returns today's market session (9:30am ET onward).
            # Bracket stop-losses that fire at the open are invisible because the
            # chart starts at 9:30am ET. Prepend yesterday's closing NAV so the
            # full day-over-day move is visible.
            #
            # Source priority for yesterday's close:
            #   1. Supabase portfolio_snapshots (recorded at EOD, immutable) — best
            #   2. acct.last_equity as fallback (sometimes stale after session end)
            if period == "1D":
                try:
                    from datetime import timezone, timedelta
                    today_str = datetime.now(timezone.utc).date().isoformat()
                    anchor_eq: float | None = None

                    # Primary: Supabase EOD snapshot (immutable, recorded after market close)
                    try:
                        from brain.portfolio_snapshots import get_equity_curve
                        snaps = get_equity_curve(days=3)
                        prev_snaps = [s for s in snaps if s.get("snapshot_date", "") < today_str]
                        if prev_snaps:
                            anchor_eq = float(prev_snaps[-1]["nav"])
                            log.info(
                                "portfolio/history(1D): anchor %.2f from Supabase snap %s",
                                anchor_eq, prev_snaps[-1]["snapshot_date"],
                            )
                    except Exception as _se:
                        log.debug("portfolio/history(1D): Supabase anchor lookup failed: %s", _se)

                    # Fallback: acct.last_equity — use only when it meaningfully
                    # differs from the first 1D bar (i.e. there was a pre-open gap)
                    if anchor_eq is None:
                        acct = hist_broker.get_account()
                        last_eq = float(acct.last_equity or 0)
                        first_bar_eq = pts[0]["equity"] if pts else 0.0
                        gap_pct = abs(last_eq - first_bar_eq) / max(first_bar_eq, 1)
                        if last_eq > 0 and gap_pct > 0.005:
                            anchor_eq = last_eq
                            log.info(
                                "portfolio/history(1D): anchor %.2f from last_equity (gap %.1f%%)",
                                anchor_eq, gap_pct * 100,
                            )

                    if anchor_eq:
                        first_dt = datetime.fromisoformat(pts[0]["time"])
                        prev_day = (first_dt - timedelta(days=1)).date()
                        # 20:00 UTC = 4pm ET = NYSE regular-hours close
                        prev_close_dt = datetime(
                            prev_day.year, prev_day.month, prev_day.day,
                            20, 0, 0, tzinfo=timezone.utc,
                        )
                        pts = [{"time": prev_close_dt.isoformat(), "equity": anchor_eq, "pnl": 0.0}] + pts
                except Exception as _exc:
                    log.warning("portfolio/history(1D): could not prepend yesterday close: %s", _exc)

            # 1M/1Y: problems with Alpaca's native daily bars:
            #   • Today's bar may not exist yet (market still open) → append live equity
            #   • Today's bar may be timestamped as "tomorrow" in UTC+x zones
            #     (Alpaca uses end-of-day ET timestamps = early UTC next calendar day)
            #   • 1Y chart shows $0 for all periods before the account was opened
            # Fix: use datetime-aware comparison; always end the series at live equity;
            # strip leading zero-equity bars from 1Y.
            elif period in ("1M", "1Y"):
                try:
                    from datetime import timezone, timedelta
                    acct = hist_broker.get_account()
                    live_eq = float(acct.equity or 0)
                    if live_eq > 0:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        today_utc = datetime.now(timezone.utc).date()
                        # Parse the last bar's date properly (handles tz-aware strings)
                        last_bar_dt = datetime.fromisoformat(pts[-1]["time"])
                        last_bar_date = last_bar_dt.astimezone(timezone.utc).date()
                        if last_bar_date >= today_utc:
                            # Replace stale/future-labelled Alpaca bar with live data
                            pts[-1] = {"time": now_iso, "equity": live_eq, "pnl": 0.0}
                        else:
                            # No today bar yet — append one
                            pts.append({"time": now_iso, "equity": live_eq, "pnl": 0.0})
                        log.info(
                            "portfolio/history(%s): appended/replaced live equity %.2f",
                            period, live_eq,
                        )

                    # 1Y: strip leading bars where equity == 0 (account not open yet)
                    if period == "1Y":
                        first_nonzero = next(
                            (i for i, p in enumerate(pts) if p["equity"] > 0), 0
                        )
                        if first_nonzero > 0:
                            pts = pts[first_nonzero:]
                            log.info(
                                "portfolio/history(1Y): clipped %d leading zero-equity bars",
                                first_nonzero,
                            )
                except Exception as _exc:
                    log.warning("portfolio/history(%s): could not update today's bar: %s", period, _exc)

            log.info("portfolio/history(%s): %d pts from broker native API", period, len(pts))
            return pts
        log.warning(
            "portfolio/history(%s): broker native returned %d pts — falling back to reconstruction",
            period, len(pts),
        )
    except Exception as exc:
        log.warning("portfolio/history(%s): broker native API failed (%s) — falling back", period, exc)

    # ── Fallback: reconstruct from live positions + price bars ─────────────────
    lookback = {"1D": 1, "1M": 30, "1Y": 365}[period]
    daily    = period != "1D"
    pts = _build_equity(_hist_ak, _hist_sk, _hist_is_paper, lookback_days=lookback, use_daily=daily)
    log.info("portfolio/history(%s): fallback reconstruction returned %d pts", period, len(pts))
    return pts


def _build_equity(ak: str, sk: str, is_paper: bool, lookback_days: int, use_daily: bool) -> list:
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
        client  = TradingClient(ak, sk, paper=is_paper)
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
        sc = StockHistoricalDataClient(ak, sk)
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
            cc  = CryptoHistoricalDataClient(ak, sk)
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
    """Diagnostic: shows point counts for 1D/1M/1Y equity builds (system creds)."""
    from config import get_settings
    cfg = get_settings()
    if not cfg.alpaca_api_key:
        return {"error": "no ALPACA_API_KEY"}
    is_paper = "paper" in cfg.alpaca_base_url.lower()
    out = {}
    for period, days, daily in [("1D", 1, False), ("1M", 30, True), ("1Y", 365, True)]:
        pts = _build_equity(cfg.alpaca_api_key, cfg.alpaca_secret_key, is_paper, lookback_days=days, use_daily=daily)
        out[period] = {"pts": len(pts), "first": pts[:1], "last": pts[-1:]}
    return out


@app.get("/indices")
def get_indices():
    """Return market indices and their tradable ETF proxies.

    Indices themselves are not directly tradable via Alpaca.
    Their ETF proxies are fully supported by Alpaca's market data and trading APIs.
    Use POST /signal with the etf_proxy symbol and asset_class='stock' to analyse any index.
    """
    return {
        "us_broad": [
            {"name": "S&P 500",           "tv_symbol": "TVC:SPX",    "etf_proxy": "SPY",  "description": "500 largest US companies by market cap"},
            {"name": "NASDAQ 100",        "tv_symbol": "TVC:NDX",    "etf_proxy": "QQQ",  "description": "100 largest non-financial NASDAQ companies"},
            {"name": "Dow Jones",         "tv_symbol": "TVC:DJI",    "etf_proxy": "DIA",  "description": "30 blue-chip US industrial companies"},
            {"name": "Russell 2000",      "tv_symbol": "TVC:RUT",    "etf_proxy": "IWM",  "description": "2000 small-cap US companies"},
            {"name": "S&P 500 Eq Weight", "tv_symbol": "TVC:SPX",    "etf_proxy": "RSP",  "description": "Equal-weighted S&P 500 (less mega-cap bias)"},
            {"name": "Total US Market",   "tv_symbol": "TVC:WILLR",  "etf_proxy": "VTI",  "description": "Entire US stock market — ~4000 companies"},
            {"name": "S&P MidCap 400",    "tv_symbol": "TVC:SPX",    "etf_proxy": "MDY",  "description": "Mid-cap US companies ($2B–$10B market cap)"},
            {"name": "S&P SmallCap 600",  "tv_symbol": "TVC:RUT",    "etf_proxy": "IJR",  "description": "Small-cap US companies with quality screen"},
        ],
        "volatility": [
            {"name": "VIX (Fear Index)",   "tv_symbol": "CBOE:VIX",   "etf_proxy": "UVXY", "description": "CBOE Volatility Index — 30-day implied vol on S&P 500"},
            {"name": "VIX Short-Term",     "tv_symbol": "CBOE:VIX",   "etf_proxy": "VIXY", "description": "Short-term VIX futures — pure volatility exposure"},
            {"name": "NASDAQ Volatility",  "tv_symbol": "CBOE:VXN",   "etf_proxy": "QQQ",  "description": "NASDAQ 100 implied volatility index"},
            {"name": "Inv. VIX (calm)",    "tv_symbol": "CBOE:VIX",   "etf_proxy": "SVXY", "description": "Short VIX — profits when markets are calm"},
        ],
        "macro": [
            {"name": "US 10-Year Yield",   "tv_symbol": "TVC:US10Y",  "etf_proxy": "TLT",  "description": "10-yr US Treasury yield — long bond benchmark"},
            {"name": "US 2-Year Yield",    "tv_symbol": "TVC:US02Y",  "etf_proxy": "SHY",  "description": "2-yr US Treasury yield — Fed policy sensitive"},
            {"name": "US 7-10 Year",       "tv_symbol": "TVC:US10Y",  "etf_proxy": "IEF",  "description": "Intermediate Treasury ETF — yield curve proxy"},
            {"name": "US Dollar Index",    "tv_symbol": "TVC:DXY",    "etf_proxy": "UUP",  "description": "USD strength vs EUR, JPY, GBP, CAD, SEK, CHF"},
            {"name": "Agg Bond Market",    "tv_symbol": "TVC:US10Y",  "etf_proxy": "AGG",  "description": "US investment-grade bond market aggregate"},
            {"name": "High Yield Bonds",   "tv_symbol": "TVC:US10Y",  "etf_proxy": "HYG",  "description": "High-yield (junk) bonds — credit risk barometer"},
            {"name": "TIPS (Inflation)",   "tv_symbol": "TVC:US10Y",  "etf_proxy": "TIP",  "description": "Treasury inflation-protected securities"},
        ],
        "us_sector": [
            {"name": "Technology",         "tv_symbol": "AMEX:XLK",   "etf_proxy": "XLK",  "description": "S&P Technology sector"},
            {"name": "Financials",         "tv_symbol": "AMEX:XLF",   "etf_proxy": "XLF",  "description": "S&P Financials sector"},
            {"name": "Healthcare",         "tv_symbol": "AMEX:XLV",   "etf_proxy": "XLV",  "description": "S&P Healthcare sector"},
            {"name": "Energy",             "tv_symbol": "AMEX:XLE",   "etf_proxy": "XLE",  "description": "S&P Energy sector"},
            {"name": "Industrials",        "tv_symbol": "AMEX:XLI",   "etf_proxy": "XLI",  "description": "S&P Industrials sector"},
            {"name": "Consumer Discr.",    "tv_symbol": "AMEX:XLY",   "etf_proxy": "XLY",  "description": "S&P Consumer Discretionary sector"},
            {"name": "Consumer Staples",   "tv_symbol": "AMEX:XLP",   "etf_proxy": "XLP",  "description": "S&P Consumer Staples sector"},
            {"name": "Utilities",          "tv_symbol": "AMEX:XLU",   "etf_proxy": "XLU",  "description": "S&P Utilities sector"},
            {"name": "Real Estate",        "tv_symbol": "AMEX:XLRE",  "etf_proxy": "XLRE", "description": "S&P Real Estate sector (REITs)"},
            {"name": "Materials",          "tv_symbol": "AMEX:XLB",   "etf_proxy": "XLB",  "description": "S&P Materials sector"},
            {"name": "Comm Services",      "tv_symbol": "AMEX:XLC",   "etf_proxy": "XLC",  "description": "S&P Communication Services sector"},
            {"name": "Semiconductors",     "tv_symbol": "NASDAQ:SOXX","etf_proxy": "SOXX", "description": "Philadelphia Semiconductor Index ETF"},
        ],
        "international": [
            {"name": "FTSE 100",           "tv_symbol": "TVC:UKX",    "etf_proxy": "EWU",  "description": "UK top 100 large-cap companies"},
            {"name": "DAX 40",             "tv_symbol": "TVC:DAX",    "etf_proxy": "EWG",  "description": "German top 40 companies"},
            {"name": "Nikkei 225",         "tv_symbol": "TVC:NI225",  "etf_proxy": "EWJ",  "description": "Japan top 225 blue-chip companies"},
            {"name": "Hang Seng",          "tv_symbol": "TVC:HSI",    "etf_proxy": "EWH",  "description": "Hong Kong top companies"},
            {"name": "CAC 40",             "tv_symbol": "TVC:CAC40",  "etf_proxy": "EWQ",  "description": "French top 40 companies"},
            {"name": "Euro Stoxx 50",      "tv_symbol": "TVC:SX5E",   "etf_proxy": "FEZ",  "description": "50 largest Eurozone blue-chips"},
            {"name": "Dev. Markets ex-US", "tv_symbol": "NASDAQ:VEA", "etf_proxy": "VEA",  "description": "Developed markets — Europe, Asia-Pacific, Canada"},
            {"name": "Emerging Markets",   "tv_symbol": "AMEX:EEM",   "etf_proxy": "EEM",  "description": "Emerging markets — China, India, Brazil, etc."},
            {"name": "China Large Cap",    "tv_symbol": "AMEX:MCHI",  "etf_proxy": "MCHI", "description": "iShares MSCI China ETF"},
            {"name": "India (Nifty 50)",   "tv_symbol": "NSE:NIFTY",  "etf_proxy": "INDA", "description": "iShares MSCI India ETF"},
        ],
        "commodities": [
            {"name": "Gold",               "tv_symbol": "TVC:GOLD",   "etf_proxy": "GLD",  "description": "Gold spot price (SPDR Gold Shares)"},
            {"name": "Silver",             "tv_symbol": "TVC:SILVER", "etf_proxy": "SLV",  "description": "Silver spot price (iShares Silver Trust)"},
            {"name": "Crude Oil (WTI)",    "tv_symbol": "NYMEX:CL1!", "etf_proxy": "USO",  "description": "West Texas Intermediate crude oil futures"},
            {"name": "Natural Gas",        "tv_symbol": "NYMEX:NG1!", "etf_proxy": "UNG",  "description": "Henry Hub natural gas futures"},
            {"name": "Broad Commodities",  "tv_symbol": "TVC:BCOM",   "etf_proxy": "PDBC", "description": "Bloomberg Commodity Index — diversified exposure"},
            {"name": "Copper",             "tv_symbol": "COMEX:HG1!", "etf_proxy": "CPER", "description": "Copper — leading economic indicator"},
        ],
    }


@app.get("/bars/{symbol}")
def get_bars(symbol: str, days: int = 60, asset_class: str = "stock"):
    """Real OHLCV bars + per-bar indicators from Alpaca (stocks and crypto).

    Used by the dashboard Technical and Fundamental pages for live charting.
    Indicators computed: RSI-14, MACD, Bollinger Bands (20), ATR-14.
    """
    sym = _validate_symbol(symbol)
    if days < 1 or days > 730:
        raise HTTPException(400, "days must be 1–730")

    try:
        from config import get_settings
        cfg = get_settings()
        import pandas as pd
        import ta as _ta

        if asset_class == "ngx":
            # ── NGX Pulse market data ──────────────────────────────────────────
            enc_key = None
            try:
                enc_key = _get_enc_key()
            except Exception:
                pass
            from brain.ngx_creds import get_ngx_pulse_key
            api_key = get_ngx_pulse_key(enc_key)
            if not api_key:
                raise HTTPException(503, "NGX Pulse API key not configured — add it in Settings → Market Data")

            import httpx
            ngx_resp = httpx.get(
                f"https://www.ngxpulse.ng/api/ngxdata/prices/{sym}",
                params={"days": max(days, 14)},
                headers={"X-API-Key": api_key},
                timeout=15.0,
                follow_redirects=True,
            )
            if ngx_resp.status_code == 401:
                raise HTTPException(503, "Invalid NGX Pulse API key — update it in Settings → Market Data")
            if ngx_resp.status_code == 404:
                raise HTTPException(503, f"Symbol {sym} not found on NGX Pulse")
            if ngx_resp.status_code == 429:
                raise HTTPException(503, "NGX Pulse rate limit reached — upgrade your plan or wait a minute")
            ngx_resp.raise_for_status()
            data = ngx_resp.json()

            # Parse multiple possible response shapes defensively
            raw_bars: list[dict] = []
            if isinstance(data, list):
                raw_bars = data
            elif isinstance(data, dict):
                for _k in ("history", "data", "bars", "prices", "ohlcv"):
                    if _k in data and isinstance(data[_k], list):
                        raw_bars = data[_k]
                        break
                if not raw_bars:
                    # Single-price snapshot — synthesise a placeholder bar
                    from datetime import date
                    cp = float(data.get("current_price") or data.get("close") or 0)
                    raw_bars = [{"time": date.today().isoformat(), "open": cp, "high": cp, "low": cp, "close": cp, "volume": data.get("volume", 0)}]

            def _ngx_bar(b: dict) -> dict | None:
                dt    = b.get("date") or b.get("time") or b.get("timestamp") or b.get("trading_date") or ""
                close = float(b.get("close") or b.get("current_price") or b.get("price") or 0)
                if not close:
                    return None
                return {
                    "time":   str(dt)[:10],
                    "open":   float(b.get("open") or close),
                    "high":   float(b.get("high") or close),
                    "low":    float(b.get("low") or close),
                    "close":  close,
                    "volume": int(b.get("volume") or 0),
                }

            bars_clean = [r for b in raw_bars if (r := _ngx_bar(b))]
            if not bars_clean:
                raise HTTPException(503, f"No usable bar data returned for {sym} from NGX Pulse")

            df = pd.DataFrame(bars_clean)

        elif asset_class == "crypto":
            from data.market_data import AlpacaCryptoMarketData
            md = AlpacaCryptoMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
            snap = _get_market_snapshot(md, sym, max(days, 210))
            if not snap.bars:
                raise HTTPException(503, f"No bar data available for {sym}")
            df = pd.DataFrame([
                {"time": b.timestamp.strftime("%Y-%m-%d"), "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in snap.bars
            ])
        else:
            from data.market_data import AlpacaMarketData
            md = AlpacaMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
            snap = _get_market_snapshot(md, sym, max(days, 210))
            if not snap.bars:
                raise HTTPException(503, f"No bar data available for {sym}")
            df = pd.DataFrame([
                {"time": b.timestamp.strftime("%Y-%m-%d"), "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in snap.bars
            ])

        if len(df) >= 14:
            df["rsi"]         = _ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            _macd             = _ta.trend.MACD(df["close"])
            df["macd"]        = _macd.macd()
            df["macd_signal"] = _macd.macd_signal()
            df["macd_hist"]   = _macd.macd_diff()
            df["atr"]         = _ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            ).average_true_range()
        if len(df) >= 20:
            _bb            = _ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
            df["bb_upper"] = _bb.bollinger_hband()
            df["bb_mid"]   = _bb.bollinger_mavg()
            df["bb_lower"] = _bb.bollinger_lband()

        # Use to_json → json.loads to guarantee NaN → null conversion.
        # df.where(notna, other=None) cannot replace NaN in float64 columns
        # (pandas stores NaN back), so warmup rows at the start of a long
        # series would contain float NaN which Python's json module rejects.
        import json as _json
        bars_out = _json.loads(df.tail(days).to_json(orient="records"))

        if asset_class == "ngx":
            current_price = bars_clean[-1]["close"] if bars_clean else None
        else:
            current_price = (
                snap.latest_quote.mid
                if snap.latest_quote and snap.latest_quote.mid
                else (snap.bars[-1].close if snap.bars else None)
            )

        return {"symbol": sym, "asset_class": asset_class, "bars": bars_out, "current_price": current_price}

    except HTTPException:
        raise
    except Exception as exc:
        log.error("bars endpoint error for %s: %s", sym, exc)
        raise HTTPException(503, "Market data temporarily unavailable")


_FUND_CACHE: dict[str, tuple[float, dict]] = {}
_FUND_TTL = 3600  # 1 hour — fundamentals change slowly


@app.get("/fundamentals/{symbol}")
def get_fundamentals(symbol: str, asset_class: str = "stock"):
    """Real fundamental data from Yahoo Finance: key metrics, analyst consensus,
    quarterly earnings history. Cached 1 h per symbol to avoid hammering Yahoo.
    """
    sym = _validate_symbol(symbol)
    cache_key = f"{sym}:{asset_class}"

    import time as _time
    cached = _FUND_CACHE.get(cache_key)
    if cached and _time.time() - cached[0] < _FUND_TTL:
        return cached[1]

    try:
        import yfinance as yf
        import pandas as pd

        yf_sym = sym.replace("USDT", "-USD").replace("USD", "-USD") if asset_class == "crypto" else sym
        ticker = yf.Ticker(yf_sym)
        try:
            info = ticker.info or {}
        except Exception as _info_exc:
            log.warning("ticker.info failed for %s, falling back to fast_info: %s", yf_sym, _info_exc)
            try:
                fi = ticker.fast_info
                info = {
                    "currentPrice":      getattr(fi, "last_price", None),
                    "regularMarketPrice": getattr(fi, "last_price", None),
                    "marketCap":         getattr(fi, "market_cap", None),
                    "fiftyTwoWeekHigh":  getattr(fi, "year_high", None),
                    "fiftyTwoWeekLow":   getattr(fi, "year_low", None),
                }
            except Exception:
                info = {}

        def _sf(v, scale=1.0, decimals=2):
            try:
                return round(float(v or 0) * scale, decimals)
            except Exception:
                return 0.0

        def _fmt_cap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"${v / 1e12:.2f}T"
                if v >= 1e9:  return f"${v / 1e9:.2f}B"
                if v >= 1e6:  return f"${v / 1e6:.2f}M"
            except Exception:
                pass
            return "N/A"

        # ── ETF early path — return ETF-specific metrics and skip stock fields ──
        if asset_class == "etf":
            avg_vol = info.get("averageVolume") or info.get("averageDailyVolume3Month") or 0
            def _fmt_vol(v: int) -> str:
                if v >= 1_000_000: return f"{v / 1_000_000:.1f}M"
                if v >= 1_000:    return f"{v / 1_000:.0f}K"
                return str(v) if v else "N/A"
            etf_result = {
                "symbol":             sym,
                "asset_class":        "etf",
                "name":               info.get("longName") or info.get("shortName") or sym,
                "current_price":      _sf(info.get("regularMarketPrice") or info.get("navPrice"), decimals=2),
                "week52_high":        _sf(info.get("fiftyTwoWeekHigh"), decimals=2),
                "week52_low":         _sf(info.get("fiftyTwoWeekLow"), decimals=2),
                # ETF-specific live fields
                "aum":                _fmt_cap(info.get("totalAssets")),
                "nav":                _sf(info.get("navPrice") or info.get("regularMarketPrice"), decimals=2),
                "distribution_yield": round(float(info.get("yield") or 0) * 100, 2),
                "beta":               _sf(info.get("beta") or info.get("beta3Year"), decimals=2),
                "pe_underlying":      _sf(info.get("trailingPE"), decimals=1),
                "expense_ratio":      round(float(info.get("expenseRatio") or 0), 4),
                "avg_volume":         _fmt_vol(int(avg_vol)),
                # Stock fields empty — required by frontend interface shape
                "market_cap": "N/A", "pe": 0.0, "forward_pe": 0.0, "eps": 0.0,
                "revenue_growth_yoy": 0.0, "gross_margin": 0.0,
                "debt_to_equity": 0.0, "roe": 0.0,
                "analyst_target": 0.0, "analyst_rating": "N/A",
                "buy_count": 0, "hold_count": 0, "sell_count": 0,
                "earnings": [],
            }
            _FUND_CACHE[cache_key] = (_time.time(), etf_result)
            return etf_result

        # ── Analyst consensus ─────────────────────────────────────────────────
        buy_ct = hold_ct = sell_ct = 0
        try:
            rs = ticker.recommendations_summary
            if rs is not None and not rs.empty:
                row = rs.iloc[0]
                buy_ct  = int((row.get("strongBuy") or 0) + (row.get("buy") or 0))
                hold_ct = int(row.get("hold") or 0)
                sell_ct = int((row.get("sell") or 0) + (row.get("strongSell") or 0))
        except Exception:
            n    = int(info.get("numberOfAnalystOpinions") or 0)
            mean = _sf(info.get("recommendationMean"))
            if n and mean:
                bf = max(0.0, (3 - mean) / 2)
                sf = max(0.0, (mean - 3) / 2)
                hf = max(0.0, 1 - bf - sf)
                buy_ct  = round(n * bf)
                sell_ct = round(n * sf)
                hold_ct = n - buy_ct - sell_ct

        mean_rec = _sf(info.get("recommendationMean"))
        if mean_rec > 0:
            if mean_rec <= 1.5:   rating = "Strong Buy"
            elif mean_rec <= 2.5: rating = "Buy"
            elif mean_rec <= 3.5: rating = "Hold"
            else:                 rating = "Sell"
        else:
            rk = (info.get("recommendationKey") or "").lower()
            if "strong" in rk and "buy" in rk: rating = "Strong Buy"
            elif "buy"  in rk:                  rating = "Buy"
            elif "hold" in rk or "neutral" in rk: rating = "Hold"
            elif "sell" in rk:                  rating = "Sell"
            else:                               rating = "N/A"

        # ── Quarterly earnings (last 4 reported quarters) ─────────────────────
        earnings = []
        if asset_class != "crypto":
            try:
                stmt = ticker.quarterly_income_stmt
                if stmt is not None and not stmt.empty:
                    rev_row = eps_row = None
                    for k in ("Total Revenue", "Operating Revenue"):
                        if k in stmt.index:
                            rev_row = stmt.loc[k]; break
                    for k in ("Diluted EPS", "Basic EPS"):
                        if k in stmt.index:
                            eps_row = stmt.loc[k]; break

                    cols = sorted(stmt.columns)[-4:]
                    for col in cols:
                        dt  = pd.Timestamp(col)
                        qtr = f"Q{((dt.month - 1) // 3) + 1} '{str(dt.year)[-2:]}"
                        rev = 0.0
                        eps = 0.0
                        if rev_row is not None and col in rev_row.index:
                            v = rev_row[col]
                            if pd.notna(v): rev = round(float(v) / 1e9, 2)
                        if eps_row is not None and col in eps_row.index:
                            v = eps_row[col]
                            if pd.notna(v): eps = round(float(v), 2)
                        earnings.append({
                            "quarter": qtr,
                            "eps_est": 0.0,
                            "eps_actual": eps,
                            "revenue_est": 0.0,
                            "revenue_actual": rev,
                        })
            except Exception as e:
                log.warning("earnings fetch failed for %s: %s", sym, e)

        result = {
            "symbol":             sym,
            "asset_class":        asset_class,
            "name":               info.get("longName") or info.get("shortName") or sym,
            "market_cap":         _fmt_cap(info.get("marketCap")),
            "pe":                 _sf(info.get("trailingPE"), decimals=1),
            "forward_pe":         _sf(info.get("forwardPE"), decimals=1),
            "eps":                _sf(info.get("trailingEps"), decimals=2),
            "revenue_growth_yoy": _sf(info.get("revenueGrowth"), scale=100, decimals=1),
            "gross_margin":       _sf(info.get("grossMargins"), scale=100, decimals=1),
            "debt_to_equity":     _sf(info.get("debtToEquity"), decimals=2),
            "roe":                _sf(info.get("returnOnEquity"), scale=100, decimals=1),
            "beta":               _sf(info.get("beta"), decimals=2),
            "week52_high":        _sf(info.get("fiftyTwoWeekHigh"), decimals=2),
            "week52_low":         _sf(info.get("fiftyTwoWeekLow"), decimals=2),
            "current_price":      _sf(info.get("currentPrice") or info.get("regularMarketPrice"), decimals=2),
            "analyst_target":     _sf(info.get("targetMeanPrice"), decimals=2),
            "analyst_rating":     rating,
            "buy_count":          buy_ct,
            "hold_count":         hold_ct,
            "sell_count":         sell_ct,
            "earnings":           earnings,
        }
        _FUND_CACHE[cache_key] = (_time.time(), result)
        return result

    except HTTPException:
        raise
    except Exception as exc:
        log.error("fundamentals error for %s: %s", sym, exc)
        # Serve stale cache rather than hard-erroring — yfinance is intermittently flaky
        stale = _FUND_CACHE.get(cache_key)
        if stale:
            log.info("fundamentals: serving stale cache for %s", sym)
            return stale[1]
        raise HTTPException(503, "Fundamental data temporarily unavailable")


@app.get("/usage")
def get_api_usage():
    """Return daily LLM token usage and cost statistics.
    Usage is persisted to disk so it survives container restarts within the same day.
    All costs are estimates based on published provider pricing.
    """
    from brain.agents.base import get_usage_stats
    return get_usage_stats()


_CREDITS_CACHE: dict = {}
_CREDITS_TTL   = 120  # seconds — check balance every 2 minutes max


@app.get("/credits")
def get_credit_status():
    """Query OpenRouter for remaining API credit balance.
    Returns current balance, used amount, and whether balance is below the configured warning threshold.
    """
    import time as _time
    from config import get_settings
    cached = _CREDITS_CACHE.get("last")
    if cached and _time.time() - cached["ts"] < _CREDITS_TTL:
        return cached["data"]

    cfg = get_settings()
    api_key = cfg.openrouter_api_key or ""

    warn_thresh = cfg.credit_warning_threshold_usd
    crit_thresh = cfg.credit_critical_threshold_usd

    if not api_key:
        result = {
            "provider": "openrouter",
            "configured": False,
            "balance_usd": None,
            "used_usd": None,
            "limit_usd": None,
            "warning": False,
            "warning_threshold": warn_thresh,
            "critical_threshold": crit_thresh,
            "error": "OPENROUTER_API_KEY not configured — running in paper mode",
        }
        return result

    try:
        import httpx as _httpx
        r = _httpx.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.status_code != 200:
            raise ValueError(f"OpenRouter returned HTTP {r.status_code}")
        body = r.json().get("data") or r.json()
        used_usd   = float(body.get("usage", 0) or 0)
        limit_usd  = body.get("limit")
        limit_usd  = float(limit_usd) if limit_usd is not None else None
        balance_usd = round((limit_usd - used_usd), 4) if limit_usd is not None else None
        result = {
            "provider": "openrouter",
            "configured": True,
            "balance_usd": balance_usd,
            "used_usd": round(used_usd, 4),
            "limit_usd": limit_usd,
            "warning": balance_usd is not None and balance_usd < warn_thresh,
            "warning_threshold": warn_thresh,
            "critical_threshold": crit_thresh,
            "error": None,
        }
    except Exception as exc:
        log.warning("credits check failed: %s", exc)
        result = {
            "provider": "openrouter",
            "configured": True,
            "balance_usd": None,
            "used_usd": None,
            "limit_usd": None,
            "warning": False,
            "warning_threshold": warn_thresh,
            "critical_threshold": crit_thresh,
            "error": str(exc),
        }

    _CREDITS_CACHE["last"] = {"ts": _time.time(), "data": result}
    return result


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


# ── TradingView webhook settings (JWT-required) ───────────────────────────────

@app.get("/webhook-settings")
def get_webhook_settings(request: Request):
    """Return whether this user has a webhook secret configured.

    The frontend constructs the full webhook URL as:
      window.location.origin + webhook_path
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for webhook settings.")
    from brain.webhook_store import has_secret
    configured = has_secret(user_id)
    # /api/ prefix is needed for nginx to proxy to uvicorn; FastAPI sees the path without it.
    webhook_path = f"/api/webhook/tradingview/{user_id}/<your-secret>" if configured else None
    return {"configured": configured, "user_id": user_id, "webhook_path": webhook_path}


@app.post("/webhook-settings")
def generate_webhook_secret(request: Request):
    """Generate a new webhook secret for this user (replaces any existing one).

    The plaintext secret is returned ONCE in this response — it is never stored
    and cannot be retrieved again. Store it somewhere safe before navigating away.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for webhook settings.")
    from brain.webhook_store import generate_secret
    plaintext = generate_secret(user_id)
    # /api/ prefix required for nginx → uvicorn proxy; FastAPI registers without it.
    webhook_path = f"/api/webhook/tradingview/{user_id}/{plaintext}"
    log.info("Webhook secret generated for user %s", user_id[:8])
    return {
        "generated": True,
        "secret": plaintext,
        "webhook_path": webhook_path,
        "warning": "Save this secret now — it will not be shown again.",
    }


@app.delete("/webhook-settings")
def revoke_webhook_secret(request: Request):
    """Revoke this user's webhook secret. Subsequent webhook calls will return 401."""
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=403, detail="JWT authentication required for webhook settings.")
    from brain.webhook_store import revoke_secret
    existed = revoke_secret(user_id)
    log.info("Webhook secret revoked for user %s (existed=%s)", user_id[:8], existed)
    return {"revoked": existed}


# ── TradingView public webhook (authenticated by per-user secret in URL) ───────

@app.post("/webhook/tradingview/{user_id}/{secret}")
async def tradingview_webhook(user_id: str, secret: str, request: Request):
    """Receive TradingView alerts and execute trades for the matching user.

    This endpoint is public (no X-Api-Key / JWT) — the per-user secret in the
    URL path is the sole authentication token. It is validated with a timing-safe
    comparison against the stored SHA-256 hash.

    Expected JSON body (paste as TradingView alert message):
      {
        "symbol":     "{{ticker}}",
        "action":     "{{strategy.order.action}}",
        "asset_class": "stock",
        "qty":         0
      }

    Fields:
      symbol      — uppercase ticker (e.g. "AAPL"). {{ticker}} fills it automatically.
      action      — "buy" or "sell" (case-insensitive). {{strategy.order.action}} fills it.
      asset_class — "stock" (default) or "crypto"
      qty         — fixed share/unit count; 0 = size by equity × position_pct (recommended)
    """
    from brain.webhook_store import validate_secret

    # Per-user-id rate limit (TradingView IPs vary — keying on IP would throttle all users)
    if not _rate_limiter.is_allowed(f"webhook:{user_id}", 10, 60):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    # Timing-safe secret check — 401 reveals nothing about whether the user_id exists
    if not validate_secret(user_id, secret):
        log.warning("Webhook: invalid secret attempt for user prefix %s", user_id[:8])
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")

    # Parse body — TradingView sends application/json or text/plain
    try:
        raw = await request.body()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("expected JSON object")
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be a valid JSON object")

    # Extract and validate fields
    symbol = _validate_symbol(str(payload.get("symbol") or payload.get("ticker") or ""))

    action_raw = str(payload.get("action") or payload.get("side") or "").strip().upper()
    if action_raw not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="action must be 'buy' or 'sell'")

    asset_class = str(payload.get("asset_class") or "stock").strip().lower()
    if asset_class not in ("stock", "crypto"):
        raise HTTPException(status_code=400, detail="asset_class must be 'stock' or 'crypto'")

    try:
        qty = float(payload.get("qty") or 0)
        if qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="qty must be a non-negative number")

    if _TRADING_PAUSED:
        raise HTTPException(status_code=503, detail="Trading paused — POST /resume to restart")

    # ── Demo account block ────────────────────────────────────────────────────
    if _DEMO_USER_ID and user_id == _DEMO_USER_ID:
        log.info("TradingView webhook: demo account %s — skipping execution", user_id[:8])
        return {"status": "ok", "detail": "Demo account — no trade executed"}

    from config import get_settings
    from brain.signal import TradingSignal
    from brain.risk_config import get_effective_risk_for_user as _wh_risk_fn

    cfg = get_settings()

    # ── Ownership guard: non-owner users must have personal broker credentials ─
    _wh_is_owner = (not _OWNER_USER_ID) or (_OWNER_USER_ID and user_id == _OWNER_USER_ID)
    if not _wh_is_owner and not _jwt_user_has_own_alpaca(user_id, cfg):
        log.warning("Webhook: non-owner %s has no personal broker creds — rejecting", user_id[:8])
        raise HTTPException(403, "No broker configured — add your API key in Settings → Broker")

    _wh_eff = _wh_risk_fn(user_id, _effective_config(cfg))

    sl_pct  = _wh_eff.get("stop_loss_pct",  cfg.stop_loss_pct)
    tp_pct  = _wh_eff.get("take_profit_pct", cfg.take_profit_pct)
    pos_pct = _wh_eff.get("max_position_pct", cfg.max_position_pct)

    signal = TradingSignal(
        symbol=symbol,
        asset_class=asset_class,  # type: ignore[arg-type]
        action=action_raw,        # type: ignore[arg-type]
        confidence=1.0,
        rationale="TradingView alert",
        suggested_position_pct=pos_pct,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
    )

    log.info("TradingView webhook: user=%s symbol=%s action=%s asset=%s",
             user_id[:8], symbol, action_raw, asset_class)

    broker = _resolve_broker(user_id, cfg)
    return _execute_order(broker, _wh_eff, cfg, signal, sl_pct, tp_pct, source="tradingview", user_id=user_id)


# ── Disclosure Tracker — settings endpoints ──────────────────────────────────

class DisclosureSettingsPayload(BaseModel):
    edgar_user_agent:              str | None = None
    edgar_request_timeout_secs:    int | None = None
    edgar_rate_limit_sleep_secs:   int | None = None
    house_feed_url:                str | None = None
    senate_feed_url:               str | None = None
    congress_request_timeout_secs: int | None = None
    congress_refresh_hours:        int | None = None
    holdings_refresh_hours:        int | None = None
    min_confidence_pct:            int | None = None
    quiver_api_key:                str | None = None


@app.get("/disclosure-settings")
def get_disclosure_settings(request: Request):
    from brain.disclosure_settings import as_dict
    d = as_dict()
    # Never return the raw API key — replace with a presence indicator
    d["quiver_api_key_configured"] = bool(d.get("quiver_api_key", ""))
    d["quiver_api_key"] = ""
    return d


@app.post("/disclosure-settings")
def save_disclosure_settings(payload: DisclosureSettingsPayload, request: Request):
    uid = getattr(request.state, "user_id", None)
    if _OWNER_USER_ID and uid and uid != _OWNER_USER_ID:
        raise HTTPException(403, "Owner access required to modify disclosure settings")
    from brain.disclosure_settings import save
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    cfg = save(updates)
    from dataclasses import asdict
    return {"saved": True, "settings": asdict(cfg)}


# ── Public Disclosure Tracker endpoints ──────────────────────────────────────
# Read-only: returns 13F institutional holdings and STOCK Act congressional
# trade disclosures. No order placement occurs in these endpoints.

@app.get("/disclosures/status")
def get_disclosures_status(request: Request):
    """Return data availability state for the Disclosure Tracker UI."""
    from brain.disclosure_settings import load as _ds_load
    from brain.copy_trading import init_db, get_investors, get_congress_members
    init_db()
    cfg = _ds_load()
    investors = get_investors()
    members = get_congress_members()
    last_13f = max((i.get("last_fetched_at") or "" for i in investors), default="") or None
    return {
        "quiver_key_configured":   bool(cfg.quiver_api_key),
        "investors_count":         len(investors),
        "congress_members_count":  len(members),
        "last_13f_fetch":          last_13f,
        "min_confidence_pct":      cfg.min_confidence_pct,
    }


@app.get("/disclosures/investors")
def get_disclosure_investors(request: Request):
    """List tracked institutional investors with metadata and confidence scores."""
    from brain.copy_trading import get_investors
    return get_investors()


@app.get("/disclosures/investors/{investor_id}/holdings")
def get_investor_holdings(investor_id: str, period: str = "", request: Request = None):
    """Return 13F holdings for an investor. Omit period for the latest filing."""
    from brain.copy_trading import get_holdings, get_holdings_periods
    periods = get_holdings_periods(investor_id)
    if not periods:
        return {"investor_id": investor_id, "period": None, "periods_available": [], "holdings": []}
    target = period if period in periods else periods[0]
    holdings = get_holdings(investor_id, target)
    return {
        "investor_id":       investor_id,
        "period":            target,
        "periods_available": periods,
        "holdings":          holdings,
        "lag_warning":       "13F filings reflect holdings up to 45 days before the filing date. Positions may have changed.",
    }


@app.get("/disclosures/investors/{investor_id}/periods")
def get_investor_periods(investor_id: str, request: Request = None):
    """Return all available filing periods for an investor."""
    from brain.copy_trading import get_holdings_periods
    return {"investor_id": investor_id, "periods": get_holdings_periods(investor_id)}


@app.get("/disclosures/congress/feed")
def get_congress_feed(
    limit: int = 100,
    member: str = "",
    symbol: str = "",
    request: Request = None,
):
    """Return congressional STOCK Act trade disclosures, newest first."""
    from brain.copy_trading import get_congress_feed
    trades = get_congress_feed(
        limit=min(limit, 500),
        member=member or None,
        symbol=symbol or None,
    )
    return {
        "count":       len(trades),
        "lag_warning": "STOCK Act disclosures may be up to 45 days after the actual transaction date.",
        "trades":      trades,
    }


@app.get("/disclosures/congress/members")
def get_congress_members_list(request: Request = None):
    """Return members who have disclosed trades, with trade counts."""
    from brain.copy_trading import get_congress_members
    return get_congress_members()


@app.post("/disclosures/refresh")
def trigger_disclosure_refresh(request: Request):
    """Manually trigger a disclosure data refresh. M2M (X-Api-Key) only."""
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        raise HTTPException(403, "This endpoint requires machine-to-machine authentication (X-Api-Key) — not accessible to browser users")
    import threading
    def _run():
        try:
            from brain.congress_fetcher import refresh as refresh_congress
            refresh_congress()
        except Exception as exc:
            log.error("Manual congress refresh error: %s", exc)
        try:
            from brain.sec_fetcher import refresh_all
            refresh_all()
        except Exception as exc:
            log.error("Manual 13F refresh error: %s", exc)
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "refresh started in background"}


if __name__ == "__main__":
    from config import get_settings
    cfg = get_settings()
    uvicorn.run("brain.api:app", host="0.0.0.0", port=cfg.brain_port, reload=False)
