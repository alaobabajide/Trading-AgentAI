"""Layer 4 — Orchestrator.

Runs the main event loop:
  1. Every N minutes: fetch data → call Brain API → execute signal.
  2. Continuously: update trailing stops.
  3. Daily: check retrain trigger (Sharpe < threshold).
  4. All state pushed to Prometheus.
"""
from __future__ import annotations

import json as _json
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import schedule

from config import get_settings
from data.portfolio import PortfolioFetcher, PortfolioState
from watchlist import STOCK_WATCHLIST, ETF_WATCHLIST, CRYPTO_WATCHLIST, CYCLE_INTERVAL_MINUTES
from monitoring.metrics import (
    brain_latency_histogram,
    cash_gauge,
    circuit_breaker_gauge,
    crypto_allocation_gauge,
    daily_pnl_gauge,
    daily_pnl_pct_gauge,
    equity_gauge,
    order_counter,
    retrain_counter,
    signal_confidence_histogram,
    signal_counter,
    start_metrics_server,
)

log = logging.getLogger(__name__)

# ── Persistent data directory ─────────────────────────────────────────────────
# Mirrors brain/api.py: auto-detects the best writable path without requiring a
# manually mounted Railway volume. /data (volume) → /app/data → /tmp.
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

# ── Peak-equity persistence ────────────────────────────────────────────────────
_PEAK_EQUITY_FILE = os.environ.get("PEAK_EQUITY_FILE", os.path.join(_DATA_DIR, "ta_peak_equity.json"))


def _load_peak_equity() -> float:
    try:
        with open(_PEAK_EQUITY_FILE) as _f:
            val = float(_json.load(_f).get("peak_equity", 0.0))
        log.info("Loaded persisted peak equity: $%.2f from %s", val, _PEAK_EQUITY_FILE)
        return max(val, 0.0)
    except FileNotFoundError:
        return 0.0
    except Exception as exc:
        log.warning("Could not load peak equity: %s — starting at 0", exc)
        return 0.0


def _save_peak_equity(value: float) -> None:
    try:
        _dir = os.path.dirname(_PEAK_EQUITY_FILE)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        with open(_PEAK_EQUITY_FILE, "w") as _f:
            _json.dump({"peak_equity": value}, _f)
    except Exception as exc:
        log.debug("Could not persist peak equity: %s", exc)


# ── Recent-entry persistence (for Gate 5e bracket stop-out detection) ─────────
_RECENT_ENTRIES_FILE = os.path.join(_DATA_DIR, "ta_recent_entries.json")
_RECENT_ENTRIES_TTL  = 4 * 30 * 60  # 4 cycles × 30 min = 120 min max age


def _load_recent_entries() -> dict[str, float]:
    """Load wall-clock entry timestamps from disk; prune stale ones."""
    try:
        with open(_RECENT_ENTRIES_FILE) as _f:
            raw: dict[str, float] = _json.load(_f)
        now = time.time()
        pruned = {sym: ts for sym, ts in raw.items() if now - ts < _RECENT_ENTRIES_TTL}
        log.info("Loaded %d recent entry record(s) from %s", len(pruned), _RECENT_ENTRIES_FILE)
        return pruned
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not load recent entries: %s", exc)
        return {}


def _save_recent_entries(entries: dict[str, float]) -> None:
    try:
        with open(_RECENT_ENTRIES_FILE, "w") as _f:
            _json.dump(entries, _f)
    except Exception as exc:
        log.debug("Could not persist recent entries: %s", exc)


# ── Loss cooldown persistence ──────────────────────────────────────────────────
# _loss_history and _loss_cooldown_end are wall-clock (time.time()) so they can
# be serialised to disk and correctly compared after a restart.
_LOSS_COOLDOWN_FILE  = os.path.join(_DATA_DIR, "ta_loss_cooldown.json")
_COLD_HISTORY_FILE   = os.path.join(_DATA_DIR, "ta_cold_history.json")


def _load_loss_cooldown() -> tuple[dict[str, list[float]], dict[str, float]]:
    """Load loss history and cooldown-end timestamps from disk; prune expired entries."""
    try:
        with open(_LOSS_COOLDOWN_FILE) as _f:
            data = _json.load(_f)
        now = time.time()
        raw_history: dict[str, list[float]] = data.get("history", {})
        raw_ends:    dict[str, float]        = data.get("ends", {})
        # Prune history entries older than 30 days (max window)
        history = {
            sym: [ts for ts in timestamps if now - ts < 30 * 86400]
            for sym, timestamps in raw_history.items()
            if any(now - ts < 30 * 86400 for ts in timestamps)
        }
        # Prune already-expired cooldown ends
        ends = {sym: end_ts for sym, end_ts in raw_ends.items() if end_ts > now}
        log.info(
            "Loaded loss cooldown state: %d symbol(s) in history, %d in active cooldown",
            len(history), len(ends),
        )
        return history, ends
    except FileNotFoundError:
        return {}, {}
    except Exception as exc:
        log.warning("Could not load loss cooldown state: %s", exc)
        return {}, {}


def _save_loss_cooldown(
    history: dict[str, list[float]], ends: dict[str, float]
) -> None:
    try:
        with open(_LOSS_COOLDOWN_FILE, "w") as _f:
            _json.dump({"history": history, "ends": ends}, _f)
    except Exception as exc:
        log.debug("Could not persist loss cooldown state: %s", exc)


def _load_cold_history(maxlen: int) -> deque:
    """Restore the cold-symbol deque from disk; prune any symbols whose cycles are stale."""
    try:
        with open(_COLD_HISTORY_FILE) as _f:
            raw: list[list[str]] = _json.load(_f)
        d: deque[set[str]] = deque(maxlen=maxlen)
        for bucket in raw[-maxlen:]:
            d.append(set(bucket))
        log.info("Loaded cold history: %d cycle bucket(s), %d unique symbol(s)",
                 len(d), len(set().union(*d) if d else set()))
        return d
    except FileNotFoundError:
        return deque(maxlen=maxlen)
    except Exception as exc:
        log.warning("Could not load cold history: %s — starting fresh", exc)
        return deque(maxlen=maxlen)


def _save_cold_history(history: deque) -> None:
    try:
        with open(_COLD_HISTORY_FILE, "w") as _f:
            _json.dump([list(bucket) for bucket in history], _f)
    except Exception as exc:
        log.debug("Could not persist cold history: %s", exc)


def _wait_for_brain(url: str, timeout_secs: int = 60) -> bool:
    """Poll /health until uvicorn is ready, up to timeout_secs."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/health", timeout=3)
            if r.status_code == 200:
                log.info("Brain API ready at %s", url)
                return True
        except Exception:
            pass
        time.sleep(2)
    log.error("Brain API did not become ready within %ds", timeout_secs)
    return False


class Orchestrator:
    def __init__(self) -> None:
        cfg = get_settings()
        self._cfg = cfg
        # Always talk to uvicorn directly on 8000 — cfg.brain_port resolves to
        # Railway's $PORT (nginx's public port) which returns 405 for POST requests.
        self._brain_url = "http://127.0.0.1:8000"
        # Use LLM debate when OpenRouter key is configured, rule-based otherwise
        self._paper_mode = not bool(cfg.openrouter_api_key)
        mode_label = "rule-based (paper)" if self._paper_mode else "LLM debate (live)"
        log.info("Orchestrator signal mode: %s", mode_label)

        from broker.adapters.alpaca import AlpacaBrokerAdapter
        self._portfolio_fetcher = PortfolioFetcher(
            AlpacaBrokerAdapter(cfg.alpaca_api_key, cfg.alpaca_secret_key, cfg.alpaca_base_url)
        )

        # Singleton Alpaca client — reused across all market-hour checks and position checks
        self._alpaca_client = None
        if cfg.alpaca_api_key and cfg.alpaca_secret_key:
            try:
                from alpaca.trading.client import TradingClient
                is_paper = "paper" in cfg.alpaca_base_url.lower()
                self._alpaca_client = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=is_paper)
            except Exception as exc:
                log.warning("Could not initialise Alpaca client: %s", exc)

        self._peak_equity: float = _load_peak_equity()
        # Per-symbol thresholds stored from last signal (keyed by symbol)
        # Lock guards concurrent writes from ThreadPoolExecutor workers.
        self._pos_thresholds: dict[str, tuple[float, float]] = {}  # symbol → (sl_pct, tp_pct)
        self._pos_thresholds_lock = threading.Lock()
        # COLD cooldown: symbols that returned HOLD/COLD are skipped for cold_skip_cycles cycles.
        # _cold_history is a deque of the last k cold-symbol sets (one per completed cycle).
        # A symbol in any set in the deque is still within its cooldown window.
        self._cold_history: deque[set[str]] = _load_cold_history(cfg.cold_skip_cycles)
        self._curr_cold_symbols: set[str] = set()
        self._cold_lock = threading.Lock()
        # Trailing stop: tracks highest observed price per open symbol (ratchets upward)
        self._trailing_peaks: dict[str, float] = {}
        self._trailing_pct: float = cfg.trailing_stop_pct
        # Per-symbol loss cooldown — wall-clock (time.time()) timestamps so state
        # can be persisted to disk and remains valid after a restart.
        _lc_history, _lc_ends = _load_loss_cooldown()
        self._loss_history: dict[str, list[float]] = _lc_history
        self._loss_cooldown_end: dict[str, float] = _lc_ends
        self._loss_lock = threading.Lock()
        self._loss_cooldown_hits: int = cfg.loss_cooldown_hits
        self._loss_cooldown_window_days: int = cfg.loss_cooldown_window_days
        self._loss_cooldown_skip_cycles: int = cfg.loss_cooldown_skip_cycles
        # Signal parameters — refreshed from brain API
        self._lookback_days: int = cfg.lookback_days
        self._correlation_threshold: float = cfg.correlation_halving_threshold
        # Live risk config — refreshed from brain API before every monitor run
        self._stop_loss_pct  = cfg.stop_loss_pct
        self._take_profit_pct = cfg.take_profit_pct
        # Credit alert — monotonic timestamp of last Telegram notification (avoids spam)
        self._last_credit_alert_ts: float = 0.0
        # SPY market trend cache — (monotonic_timestamp, is_uptrend); refreshed every 5 min
        self._spy_cache: tuple[float, bool] | None = None
        self._spy_cache_lock = threading.Lock()
        # Bracket stop-out tracker — records wall-clock timestamp when a BUY was submitted.
        # Used in Gate 5e: if a position disappears while an entry is still tracked, the
        # bracket stop-loss fired (Alpaca closed the position outside _monitor_positions),
        # so _monitor_positions never incremented loss_history. Gate 5e detects this and
        # records the loss hit so the loss-cooldown gate (3.6) can suppress re-entry.
        # Persisted to disk so stop-out history survives Railway restarts.
        self._recent_entries: dict[str, float] = _load_recent_entries()
        self._entry_lock = threading.Lock()
        # Gate 5 concurrency guard — prevents TOCTOU race where parallel workers
        # all read the same position count before any order fills, allowing
        # more than max_concurrent_positions to be submitted simultaneously.
        self._pending_buys: set[str] = set()
        self._gate5_lock = threading.Lock()

    # ── Portfolio refresh ──────────────────────────────────────────────────────

    def _refresh_portfolio_metrics(self) -> PortfolioState:
        portfolio = self._portfolio_fetcher.snapshot()
        equity_gauge.set(portfolio.equity)
        cash_gauge.set(portfolio.cash)
        daily_pnl_gauge.set(portfolio.daily_pnl)
        daily_pnl_pct_gauge.set(portfolio.daily_pnl_pct)
        crypto_allocation_gauge.set(portfolio.crypto_allocation_pct * 100)

        if portfolio.equity > self._peak_equity:
            self._peak_equity = portfolio.equity
            _save_peak_equity(self._peak_equity)
        drawdown = (
            (self._peak_equity - portfolio.equity) / self._peak_equity * 100
            if self._peak_equity > 0 else 0.0
        )

        from monitoring.metrics import drawdown_gauge
        drawdown_gauge.set(drawdown)

        cb_active = drawdown / 100 >= self._cfg.circuit_breaker_drawdown
        circuit_breaker_gauge.set(1.0 if cb_active else 0.0)

        log.info(
            "Portfolio: equity=%.2f pnl=%.2f (%.2f%%) cash=%.2f drawdown=%.2f%% cb=%s",
            portfolio.equity, portfolio.daily_pnl, portfolio.daily_pnl_pct,
            portfolio.cash, drawdown, "ACTIVE" if cb_active else "off",
        )

        if cb_active:
            log.warning(
                "CIRCUIT BREAKER ACTIVE — drawdown %.2f%% >= %.0f%% limit. "
                "All trades blocked until equity recovers.",
                drawdown, self._cfg.circuit_breaker_drawdown * 100,
            )

        return portfolio

    # ── Signal + execution ────────────────────────────────────────────────────

    def _spy_is_uptrend(self) -> bool:
        """True when SPY last daily close ≥ its 20-day SMA (broad market uptrend).

        Cached for 5 minutes so it doesn't hit yfinance on every symbol. Fails
        open (returns True) when data is unavailable so we never block all trades
        on a network hiccup.
        """
        now = time.monotonic()
        with self._spy_cache_lock:
            if self._spy_cache is not None:
                cached_ts, cached_val = self._spy_cache
                if now - cached_ts < 300:
                    return cached_val
        try:
            import yfinance as yf
            spy = yf.download("SPY", period="30d", progress=False, auto_adjust=True, threads=False)
            if spy.empty or len(spy) < 20:
                return True
            closes = spy["Close"].squeeze()
            sma20 = float(closes.rolling(20).mean().iloc[-1])
            last_close = float(closes.iloc[-1])
            result = last_close >= sma20
            log.info(
                "SPY trend filter: last=%.2f SMA20=%.2f → %s",
                last_close, sma20, "UPTREND" if result else "DOWNTREND/FLAT",
            )
        except Exception as exc:
            log.debug("SPY trend check failed: %s — failing open", exc)
            result = True
        with self._spy_cache_lock:
            self._spy_cache = (time.monotonic(), result)
        return result

    def _is_market_open(self) -> bool:
        """Return True only during regular US market hours (9:30–16:00 ET, Mon–Fri)."""
        try:
            if self._alpaca_client is None:
                return True  # no Alpaca credentials — assume open (crypto trades 24/7)
            clock = self._alpaca_client.get_clock()
            return bool(clock.is_open)
        except Exception as exc:
            log.warning("Could not check market clock: %s — assuming open", exc)
            return True  # fail-open: don't suppress orders if clock check fails

    @staticmethod
    def _is_stock_analysis_window() -> bool:
        """Return True only during the US equity analysis window: 5am–7pm ET, Mon–Fri.

        Covers pre-market (5am), regular session (9:30am–4pm), and post-market (to 7pm).
        Outside this window stock/ETF signals are meaningless — the LLM debate is skipped
        entirely so no OpenRouter credits are consumed on weekends or overnight.
        Crypto is always allowed through (separate check in _run_cycle).
        """
        _ET = ZoneInfo("America/New_York")
        now = datetime.now(_ET)
        if now.weekday() >= 5:          # Saturday=5, Sunday=6
            return False
        hour_min = now.hour * 60 + now.minute
        return 5 * 60 <= hour_min < 19 * 60   # 05:00–19:00 ET

    def _brain_headers(self) -> dict:
        key = self._cfg.brain_api_key
        return {"X-Api-Key": key} if key else {}

    def _is_trading_paused(self) -> bool:
        """Check the brain API kill switch before executing any order."""
        try:
            r = httpx.get(f"{self._brain_url}/kill", timeout=3, headers=self._brain_headers())
            return r.json().get("paused", False)
        except Exception:
            return False  # if we can't reach the kill switch, proceed

    def _has_open_position(self, symbol: str, asset_class: str) -> bool:
        """Return True if an open position for this symbol already exists."""
        try:
            if self._alpaca_client is None:
                return False
            positions = self._alpaca_client.get_all_positions()
            return any(p.symbol == symbol for p in positions)
        except Exception as exc:
            log.warning("Could not check open positions for %s: %s", symbol, exc)
            return False  # assume no position if check fails

    def _process_symbol(self, symbol: str, asset_class: str, portfolio: PortfolioState) -> None:
        # ── Gate 1: circuit breaker ───────────────────────────────────────────
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - portfolio.equity) / self._peak_equity
            if drawdown >= self._cfg.circuit_breaker_drawdown:
                log.info("SKIP %s — circuit breaker active (drawdown=%.1f%%)", symbol, drawdown * 100)
                return

        # ── Gate 2: kill switch ───────────────────────────────────────────────
        if self._is_trading_paused():
            log.info("SKIP %s — kill switch active (trading paused)", symbol)
            return

        # ── Gate 3.5: COLD cooldown — skip symbols quiet in recent cycles ──────
        with self._cold_lock:
            if any(symbol in past for past in self._cold_history):
                log.debug("SKIP %s — COLD cooldown (quiet within last %d cycle(s))",
                          symbol, self._cfg.cold_skip_cycles)
                return

        # ── Gate 3.6: Loss cooldown — 2 stop-loss hits in 5 days → skip 2 cycles ──
        with self._loss_lock:
            cooldown_end = self._loss_cooldown_end.get(symbol, 0)
        if time.time() < cooldown_end:
            log.info("SKIP %s — loss cooldown active (too many stop-loss hits recently)", symbol)
            return

        payload = {
            "symbol":        symbol,
            "asset_class":   asset_class,
            "lookback_days": self._lookback_days,
            "paper_mode":    self._paper_mode,
        }
        start = time.monotonic()
        try:
            resp = httpx.post(f"{self._brain_url}/signal", json=payload, timeout=180, headers=self._brain_headers())
            resp.raise_for_status()
            sig = resp.json()
        except Exception as exc:
            log.error("Brain API call failed for %s: %s", symbol, exc)
            return
        finally:
            elapsed = time.monotonic() - start
            brain_latency_histogram.observe(elapsed)

        action     = sig.get("action", "HOLD")
        confidence = sig.get("confidence", 0.0)
        tier       = sig.get("tier", "COLD")
        votes_for  = sig.get("votes_for_action", 0)
        conflict   = sig.get("panels_conflict", False)

        signal_counter.labels(symbol=symbol, action=action, asset_class=asset_class).inc()
        signal_confidence_histogram.observe(confidence)

        # Evaluate Category C watch rules for this symbol using the price from the signal.
        price = sig.get("current_price") or 0.0
        if price and price > 0:
            try:
                httpx.post(
                    f"{self._brain_url}/brain/rules/evaluate",
                    params={"symbol": symbol, "price": price},
                    timeout=5,
                    headers=self._brain_headers(),
                )
            except Exception as _wr_exc:
                log.debug("Watch rule evaluation for %s skipped: %s", symbol, _wr_exc)

        log.info(
            "Signal %-6s  %-6s  conf=%.2f  tier=%-4s  votes=%.1f/27  conflict=%s",
            symbol, action, confidence, tier, votes_for, conflict,
        )

        # Only write thresholds on BUY — HOLD/SELL/COLD must never overwrite the
        # ATR-calibrated stop that was set at entry, or positions get silently
        # tightened to the 2% config default on the very next HOLD cycle.
        if action == "BUY":
            sl_pct = sig.get("stop_loss_pct",  self._cfg.stop_loss_pct)
            tp_pct = sig.get("take_profit_pct", self._cfg.take_profit_pct)
            with self._pos_thresholds_lock:
                self._pos_thresholds[symbol] = (sl_pct, tp_pct)

        # ── Gate 4: only act on WARM or HOT signals ───────────────────────────
        if action == "HOLD" or tier == "COLD":
            log.info("  → %s for %s (tier=%s) — no order submitted", action, symbol, tier)
            with self._cold_lock:
                self._curr_cold_symbols.add(symbol)
            return

        # ── Gate 3 (order execution guard): market hours for stocks ──────────
        # Signal was already generated and cached above — only block order placement.
        if asset_class == "stock" and not self._is_market_open():
            log.info("  → %s signal for %s cached; order deferred — market closed", action, symbol)
            return

        # ── Gate 5: don't add to a position that already exists; enforce max concurrent + exposure ──
        # _gate5_lock prevents the TOCTOU race: all 16 workers can read the same position
        # count simultaneously and all pass the check, submitting 16 orders when only 1 slot
        # remains. The lock + _pending_buys set makes the check-and-reserve atomic.
        _added_to_pending = False
        if action == "BUY" and self._alpaca_client:
            try:
                with self._gate5_lock:
                    _all_pos = self._alpaca_client.get_all_positions()
                    if any(p.symbol == symbol for p in _all_pos) or symbol in self._pending_buys:
                        log.info("  → BUY skipped for %s — position already open or pending", symbol)
                        return
                    _n_active = len(_all_pos) + len(self._pending_buys)
                    if _n_active >= self._cfg.max_concurrent_positions:
                        log.info(
                            "  → BUY skipped for %s — at max concurrent positions (%d open + %d pending ≥ %d limit)",
                            symbol, len(_all_pos), len(self._pending_buys), self._cfg.max_concurrent_positions,
                        )
                        return
                    # Enforce max_exposure_pct — the field exists in config and backtest
                    # but was never checked in the live path, allowing margin-funded
                    # over-allocation (110% stocks + 64% ETFs = 174% of NAV observed).
                    try:
                        _acct_g5 = self._alpaca_client.get_account()
                        _equity_g5 = float(_acct_g5.equity or 1)
                        _deployed_g5 = sum(abs(float(p.market_value or 0)) for p in _all_pos)
                        if _equity_g5 > 0 and _deployed_g5 / _equity_g5 >= self._cfg.max_exposure_pct:
                            log.info(
                                "  → BUY skipped for %s — max exposure reached (%.0f%% deployed ≥ %.0f%% limit)",
                                symbol, _deployed_g5 / _equity_g5 * 100, self._cfg.max_exposure_pct * 100,
                            )
                            return
                    except Exception as _exc_exp:
                        log.debug("Exposure check failed for Gate 5: %s", _exc_exp)
                    self._pending_buys.add(symbol)
                    _added_to_pending = True
            except Exception as _exc5:
                log.warning("Could not check positions for Gate 5: %s", _exc5)
                if self._has_open_position(symbol, asset_class):
                    log.info("  → BUY skipped for %s — position already open (fallback check)", symbol)
                    return
        elif action == "BUY" and self._has_open_position(symbol, asset_class):
            log.info("  → BUY skipped for %s — position already open", symbol)
            return

        # ── Gate 5e: detect bracket stop-outs and enforce loss cooldown ────────
        # When Alpaca's bracket child stop-loss fires, the position closes
        # outside _monitor_positions → loss_history is NEVER incremented →
        # loss cooldown (Gate 3.6) never activates → system re-enters the
        # same failing symbol every 30 minutes indefinitely.
        # Fix: if we entered this symbol recently (tracked by _recent_entries)
        # and there is now no open position, infer a bracket stop-out and
        # record the loss hit so Gate 3.6 can suppress re-entry.
        if action == "BUY":
            _now5e = time.time()  # wall clock — survives restarts via _recent_entries persistence
            with self._entry_lock:
                _entry_ts = self._recent_entries.get(symbol, 0)
            if _entry_ts > 0 and _now5e - _entry_ts < _RECENT_ENTRIES_TTL:
                # Position was opened recently and is now gone → Alpaca bracket closed it
                with self._loss_lock:
                    _hist = self._loss_history.get(symbol, [])
                    # Guard: only record once per entry event (skip if already recorded
                    # within the last half-cycle to avoid double-counting)
                    if not _hist or _now5e - _hist[-1] > CYCLE_INTERVAL_MINUTES * 30:
                        _hist.append(_now5e)
                        _win = self._loss_cooldown_window_days * 86400
                        _hist = [t for t in _hist if _now5e - t < _win]
                        self._loss_history[symbol] = _hist
                        log.info(
                            "Bracket stop-out detected for %s — loss hit #%d in last %dd",
                            symbol, len(_hist), self._loss_cooldown_window_days,
                        )
                        if len(_hist) >= self._loss_cooldown_hits:
                            _cd = self._loss_cooldown_skip_cycles * CYCLE_INTERVAL_MINUTES * 60
                            self._loss_cooldown_end[symbol] = _now5e + _cd
                            log.info(
                                "Loss cooldown activated (bracket stop-out): %s → skip %d cycles",
                                symbol, self._loss_cooldown_skip_cycles,
                            )
                        _save_loss_cooldown(
                            dict(self._loss_history),
                            dict(self._loss_cooldown_end),
                        )
                with self._entry_lock:
                    self._recent_entries.pop(symbol, None)
                    _save_recent_entries(dict(self._recent_entries))
                # Re-check: cooldown may have just been activated above
                with self._loss_lock:
                    _cd_end = self._loss_cooldown_end.get(symbol, 0)
                if time.time() < _cd_end:
                    log.info("SKIP %s — loss cooldown active (bracket stop-out detected)", symbol)
                    if _added_to_pending:
                        with self._gate5_lock:
                            self._pending_buys.discard(symbol)
                    return

        # ── Gate 5b: can't short crypto — skip SELL with no open position ─────
        if action == "SELL" and asset_class == "crypto" and not self._has_open_position(symbol, asset_class):
            log.info("  → SELL skipped for %s — no open crypto position (shorting unsupported)", symbol)
            return

        # ── Gate 5c: crypto risk-off block (Phase 3-D) ────────────────────────
        # When the macro regime is HIGH_VOLATILITY or TRENDING_DOWN, don't open
        # new crypto longs — crypto amplifies drawdowns in risk-off conditions.
        regime = sig.get("regime_label", "UNKNOWN")
        if asset_class == "crypto" and action == "BUY":
            if "HIGH_VOLATILITY" in regime or ("TRENDING" in regime and "DOWN" in regime):
                log.info(
                    "  → SKIP crypto BUY for %s — risk-off regime (%s)",
                    symbol, regime,
                )
                if _added_to_pending:
                    with self._gate5_lock:
                        self._pending_buys.discard(symbol)
                return

        # ── Regime-adaptive risk parameters (Phase 3-B) ───────────────────────
        # Adjust stop/TP based on the macro regime from the signal.
        exec_sl_pct = float(sig.get("stop_loss_pct",  self._cfg.stop_loss_pct))
        exec_tp_pct = float(sig.get("take_profit_pct", self._cfg.take_profit_pct))
        if "TRENDING_UP" in regime:
            exec_tp_pct = max(exec_tp_pct, self._cfg.regime_trending_up_min_tp)
        elif "RANGING" in regime:
            exec_tp_pct = min(exec_tp_pct, self._cfg.regime_ranging_max_tp)
        elif "HIGH_VOLATILITY" in regime:
            exec_sl_pct = max(exec_sl_pct, self._cfg.regime_high_vol_min_sl)
            exec_tp_pct = min(exec_tp_pct, self._cfg.regime_high_vol_max_tp)

        # ── Correlation-aware position sizing (Phase 3-A) ─────────────────────
        # If the target correlates > 0.70 with any existing open position,
        # halve the size to avoid doubling concentrated risk.
        exec_pos_pct = float(sig.get("suggested_position_pct", self._cfg.max_position_pct))
        if action == "BUY" and self._alpaca_client:
            try:
                open_positions = self._alpaca_client.get_all_positions()
                open_syms = [p.symbol for p in open_positions if p.symbol != symbol]
                if open_syms:
                    import yfinance as yf
                    all_syms = [symbol] + open_syms[:6]   # cap at 6 to bound latency
                    hist = yf.download(
                        all_syms, period="60d", progress=False, auto_adjust=True, threads=False
                    )
                    close_df = hist["Close"] if "Close" in hist.columns.get_level_values(0) else hist
                    if symbol in close_df.columns:
                        corr = close_df.corr()
                        peer_corrs = corr[symbol].drop(symbol, errors="ignore").abs()
                        max_corr = float(peer_corrs.max()) if not peer_corrs.empty else 0.0
                        if max_corr > 0.85:
                            log.info(
                                "Correlation block: %s max_corr=%.2f > 0.85 → BUY skipped"
                                " (too correlated with open positions)",
                                symbol, max_corr,
                            )
                            if _added_to_pending:
                                with self._gate5_lock:
                                    self._pending_buys.discard(symbol)
                            return
                        elif max_corr > self._correlation_threshold:
                            exec_pos_pct *= 0.5
                            log.info(
                                "Correlation gate: %s max_corr=%.2f > threshold=%.2f → position halved to %.1f%%",
                                symbol, max_corr, self._correlation_threshold, exec_pos_pct * 100,
                            )
            except Exception as exc:
                log.debug("Correlation check failed for %s: %s", symbol, exc)

        # ── Gate 5d: market trend filter — only buy when SPY is in uptrend ──────
        # Prevents buying individual stocks while the broad market is in a
        # downtrend (SPY < 20-day SMA). SELL signals and crypto are unaffected.
        if action == "BUY" and asset_class == "stock":
            if not self._spy_is_uptrend():
                log.info(
                    "  → SKIP BUY for %s — SPY below 20-day SMA (broad market downtrend)",
                    symbol,
                )
                if _added_to_pending:
                    with self._gate5_lock:
                        self._pending_buys.discard(symbol)
                return

        log.info("  → Submitting %s %s order (tier=%s) via /execute …", action, symbol, tier)

        status = "skipped"
        _max_attempts = 3
        try:
            for _attempt in range(1, _max_attempts + 1):
                try:
                    exec_resp = httpx.post(
                        f"{self._brain_url}/execute",
                        json={
                            "symbol":                 symbol,
                            "asset_class":            asset_class,
                            "action":                 action,
                            "suggested_position_pct": exec_pos_pct,
                            "stop_loss_pct":          exec_sl_pct,
                            "take_profit_pct":        exec_tp_pct,
                        },
                        timeout=30,
                        headers=self._brain_headers(),
                    )
                    exec_resp.raise_for_status()
                    result = exec_resp.json()
                    log.info(
                        "  ✓ ORDER PLACED — %s %s  id=%s  status=%s  stop=%.2f%%  tp=%.2f%%",
                        action, symbol,
                        result.get("order_id", "?"),
                        result.get("status", "?"),
                        result.get("stop_pct", 0) * 100,
                        result.get("target_pct", 0) * 100,
                    )
                    status = "submitted"
                    # Track BUY entries for Gate 5e bracket stop-out detection (wall clock, persisted)
                    if action == "BUY":
                        with self._entry_lock:
                            self._recent_entries[symbol] = time.time()
                            _save_recent_entries(dict(self._recent_entries))
                    break  # success — exit retry loop
                except httpx.HTTPStatusError as exc:
                    _http_code = exc.response.status_code
                    _http_body = exc.response.text[:300]
                    if _http_code >= 500 and _attempt < _max_attempts:
                        _wait = 2 ** _attempt  # 2s, 4s
                        log.warning(
                            "  ✗ Execute attempt %d/%d for %s: HTTP %d — retrying in %ds",
                            _attempt, _max_attempts, symbol, _http_code, _wait,
                        )
                        time.sleep(_wait)
                        continue
                    # 4xx rejection or final 5xx — permanent failure for this cycle
                    log.error(
                        "  ✗ Execute rejected for %s after %d attempt(s): HTTP %d — %s",
                        symbol, _attempt, _http_code, _http_body,
                    )
                    self._send_trade_rejection_alert(symbol, action, _http_code, _http_body)
                    status = "skipped"
                    break
                except Exception as exc:
                    log.error("  ✗ Execute call failed for %s: %s", symbol, exc)
                    status = "skipped"
                    break
        finally:
            # Always release the Gate 5 pending-buy reservation so the slot
            # is freed whether the order succeeded, was rejected, or crashed.
            if _added_to_pending:
                with self._gate5_lock:
                    self._pending_buys.discard(symbol)

        exchange = "alpaca" if asset_class == "stock" else "alpaca_crypto"
        order_counter.labels(symbol=symbol, action=action, exchange=exchange, status=status).inc()

    # ── Live config sync ──────────────────────────────────────────────────────

    def _refresh_risk_config(self) -> None:
        """Pull effective risk config from brain API so UI changes take effect immediately."""
        try:
            r = httpx.get(f"{self._brain_url}/config", timeout=3, headers=self._brain_headers())
            if r.status_code == 200:
                data = r.json()
                self._stop_loss_pct             = float(data.get("stop_loss_pct",              self._stop_loss_pct))
                self._take_profit_pct           = float(data.get("take_profit_pct",            self._take_profit_pct))
                self._trailing_pct              = float(data.get("trailing_stop_pct",          self._trailing_pct))
                self._lookback_days             = int(data.get("lookback_days",                self._lookback_days))
                self._correlation_threshold     = float(data.get("correlation_halving_threshold", self._correlation_threshold))
                self._loss_cooldown_hits        = int(data.get("loss_cooldown_hits",            self._loss_cooldown_hits))
                self._loss_cooldown_window_days = int(data.get("loss_cooldown_window_days",     self._loss_cooldown_window_days))
                self._loss_cooldown_skip_cycles = int(data.get("loss_cooldown_skip_cycles",     self._loss_cooldown_skip_cycles))
                log.debug(
                    "Risk config refreshed: sl=%.1f%%  tp=%.1f%%  trail=%.1f%%  lookback=%dd  source=%s",
                    self._stop_loss_pct * 100, self._take_profit_pct * 100,
                    self._trailing_pct * 100, self._lookback_days,
                    data.get("source", "?"),
                )
        except Exception as exc:
            log.debug("Could not refresh risk config from brain API: %s", exc)

    # ── Position P&L monitor ──────────────────────────────────────────────────

    def _monitor_positions(self) -> None:
        """Close positions that hit take-profit or stop-loss thresholds.

        Runs every minute as a safety net for:
          • Positions opened before bracket orders were introduced (no child orders).
          • Cases where Alpaca's bracket child order was cancelled or expired.
        For positions with active bracket orders, Alpaca fires first; this loop
        is a second line of defence.
        """
        self._refresh_risk_config()   # pull latest thresholds before every check

        if not self._alpaca_client:
            return
        try:
            positions = self._alpaca_client.get_all_positions()
        except Exception as exc:
            log.warning("Position monitor: could not fetch positions: %s", exc)
            return

        for pos in positions:
            symbol = pos.symbol
            try:
                plpc = float(pos.unrealized_plpc or 0)  # fraction: 0.05 = +5%
            except (TypeError, ValueError):
                continue

            with self._pos_thresholds_lock:
                sl_pct, tp_pct = self._pos_thresholds.get(
                    symbol,
                    (self._stop_loss_pct, self._take_profit_pct),
                )

            reason = None
            if plpc >= tp_pct:
                reason = f"TAKE PROFIT (up {plpc*100:.2f}% >= {tp_pct*100:.1f}%)"
            elif plpc <= -sl_pct:
                reason = f"STOP LOSS (down {plpc*100:.2f}% <= -{sl_pct*100:.1f}%)"

            if reason:
                # Guard: skip manual close when Alpaca bracket child orders are still active.
                # Active stop/limit child orders already handle exit via OCO; a duplicate
                # close_position() call creates conflicting market orders and may cause
                # a rejected or partial fill.
                _has_child_orders = False
                try:
                    _open_orders = self._alpaca_client.get_orders()
                    _has_child_orders = any(
                        str(_o.symbol) == symbol
                        and str(_o.order_type) in ("stop", "stop_limit", "limit")
                        and str(_o.status) in (
                            "new", "held", "accepted",
                            "partially_filled", "pending_replace",
                        )
                        for _o in _open_orders
                    )
                except Exception as _oe:
                    log.debug("Could not check bracket child orders for %s: %s", symbol, _oe)

                if _has_child_orders:
                    log.debug(
                        "Position monitor: %s has active bracket child orders — "
                        "skipping manual close (Alpaca OCO will handle %s)",
                        symbol, reason,
                    )
                else:
                    log.info("Closing %s — %s", symbol, reason)
                    try:
                        order = self._alpaca_client.close_position(symbol)
                        order_counter.labels(
                            symbol=symbol, action="SELL", exchange="alpaca", status="submitted",
                        ).inc()
                        log.info("  ✓ Position closed: %s id=%s", symbol, order.id)
                        with self._pos_thresholds_lock:
                            self._pos_thresholds.pop(symbol, None)
                        self._trailing_peaks.pop(symbol, None)
                        # Record stop-loss hit for loss-cooldown gate (Phase 3-C)
                        if "STOP LOSS" in reason:
                            now = time.time()  # wall-clock so state persists across restarts
                            with self._loss_lock:
                                history = self._loss_history.get(symbol, [])
                                history.append(now)
                                window_secs = self._loss_cooldown_window_days * 86400
                                history = [t for t in history if now - t < window_secs]
                                self._loss_history[symbol] = history
                                if len(history) >= self._loss_cooldown_hits:
                                    cooldown_secs = self._loss_cooldown_skip_cycles * CYCLE_INTERVAL_MINUTES * 60
                                    self._loss_cooldown_end[symbol] = now + cooldown_secs
                                    log.info(
                                        "Loss cooldown activated: %s — %d stop-loss hits in %dd"
                                        " → skip next %d cycles",
                                        symbol, len(history),
                                        self._loss_cooldown_window_days,
                                        self._loss_cooldown_skip_cycles,
                                    )
                                _save_loss_cooldown(
                                    dict(self._loss_history),
                                    dict(self._loss_cooldown_end),
                                )
                    except Exception as exc:
                        log.error("  ✗ Failed to close %s: %s", symbol, exc)
            else:
                log.debug(
                    "Position monitor: %s plpc=%.2f%% (sl=%.1f%% tp=%.1f%%)",
                    symbol, plpc * 100, sl_pct * 100, tp_pct * 100,
                )
                # Trailing stop ratchet — update peak and replace open stop order if price climbs
                try:
                    current_price = float(pos.current_price or 0)
                except (TypeError, ValueError):
                    current_price = 0.0

                if current_price > 0:
                    peak = self._trailing_peaks.get(symbol, current_price)
                    if current_price > peak:
                        new_stop = round(current_price * (1 - self._trailing_pct), 2)
                        try:
                            orders = self._alpaca_client.get_orders()
                            for order in orders:
                                if (str(order.symbol) == symbol
                                        and str(order.order_type) in ("stop", "stop_limit")
                                        and str(order.status) in ("new", "held")):
                                    from alpaca.trading.requests import ReplaceOrderRequest
                                    self._alpaca_client.replace_order_by_id(
                                        order.id,
                                        ReplaceOrderRequest(stop_price=new_stop),
                                    )
                                    # Only advance the peak after the order is confirmed —
                                    # if replace_order_by_id throws, the old stop is still live
                                    # and the peak must stay at its prior value so the next
                                    # cycle retries the ratchet.
                                    self._trailing_peaks[symbol] = current_price
                                    log.info(
                                        "Trailing stop updated: %s peak=%.2f new_stop=%.2f",
                                        symbol, current_price, new_stop,
                                    )
                                    break
                        except Exception as exc:
                            log.debug("Trailing stop update failed for %s: %s", symbol, exc)
                    else:
                        self._trailing_peaks.setdefault(symbol, current_price)

    # ── Retrain trigger ───────────────────────────────────────────────────────

    def _check_retrain(self, portfolio: PortfolioState) -> None:
        if portfolio.daily_pnl_pct < -self._cfg.retrain_trigger_loss_pct:
            log.info("Retrain trigger: daily P&L = %.2f%%", portfolio.daily_pnl_pct)
            retrain_counter.inc()

    # ── API credit monitoring ─────────────────────────────────────────────────

    def _check_api_credits(self) -> None:
        """Poll /credits every 30 min; send Telegram alert if balance < $5."""
        if self._paper_mode:
            return  # paper mode uses no OpenRouter credits
        try:
            r = httpx.get(
                f"{self._brain_url}/credits",
                timeout=10,
                headers=self._brain_headers(),
            )
            if r.status_code != 200:
                return
            data = r.json()
            balance = data.get("balance_usd")
            if balance is not None and float(balance) < self._cfg.credit_warning_threshold_usd:
                self._send_credit_alert(float(balance))
        except Exception as exc:
            log.warning("Credit check failed: %s", exc)

    def _send_credit_alert(self, balance: float) -> None:
        """Send Telegram message about low credits (at most once per hour)."""
        now = time.monotonic()
        if now - self._last_credit_alert_ts < self._cfg.credit_alert_cooldown_secs:
            return
        self._last_credit_alert_ts = now
        cfg = self._cfg
        token      = getattr(cfg, "telegram_bot_token", "") or ""
        allowed_ids = getattr(cfg, "telegram_allowed_ids", []) or []
        if not token or not allowed_ids:
            log.warning("Credit alert: Telegram not configured, cannot send notification")
            return
        threshold = self._cfg.credit_warning_threshold_usd
        msg = (
            "⚠️ <b>OpenRouter API Credit Alert</b>\n\n"
            f"Remaining balance: <b>${balance:.2f}</b>\n"
            f"Balance is below the <b>${threshold:.2f}</b> warning threshold.\n\n"
            "Top up at openrouter.ai/settings/billing to keep live trading running."
        )
        for chat_id in allowed_ids:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
                log.info("Credit alert sent to Telegram chat %s (balance $%.2f)", chat_id, balance)
            except Exception as exc:
                log.warning("Telegram credit alert failed for %s: %s", chat_id, exc)

    def _send_trade_rejection_alert(
        self, symbol: str, action: str, http_code: int, body: str
    ) -> None:
        """Send Telegram alert when an order is permanently rejected by the broker."""
        cfg = self._cfg
        token       = getattr(cfg, "telegram_bot_token", "") or ""
        allowed_ids = getattr(cfg, "telegram_allowed_ids", []) or []
        if not token or not allowed_ids:
            log.warning("Trade rejection alert: Telegram not configured")
            return
        msg = (
            "🚨 <b>Order Rejected</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Action: <b>{action}</b>\n"
            f"HTTP {http_code}: {body[:200]}\n\n"
            "Check the orchestrator logs for full details."
        )
        for chat_id in allowed_ids:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
                log.info("Trade rejection alert sent to Telegram chat %s", chat_id)
            except Exception as exc:
                log.warning("Telegram trade rejection alert failed for %s: %s", chat_id, exc)

    def _send_heartbeat(self) -> None:
        """Send a periodic Telegram status message so operators know the system is alive."""
        cfg = self._cfg
        token       = getattr(cfg, "telegram_bot_token", "") or ""
        allowed_ids = getattr(cfg, "telegram_allowed_ids", []) or []
        if not token or not allowed_ids:
            return
        try:
            portfolio = self._portfolio_fetcher.snapshot()
            equity    = portfolio.equity
            daily_pnl = portfolio.daily_pnl
            n_pos     = len(portfolio.positions)
            mode      = "paper/rule-based" if self._paper_mode else "live/LLM"
            pnl_sign  = "🟢" if daily_pnl >= 0 else "🔴"
            msg = (
                "💓 <b>Trading Agent — Heartbeat</b>\n\n"
                f"Status: <b>Running</b>  ({mode})\n"
                f"Equity: <b>${equity:,.2f}</b>\n"
                f"Daily P&L: {pnl_sign} <b>${daily_pnl:+,.2f}</b>\n"
                f"Open positions: <b>{n_pos}</b>"
            )
        except Exception as exc:
            log.warning("Heartbeat: could not fetch portfolio — %s", exc)
            mode = "paper/rule-based" if self._paper_mode else "live/LLM"
            msg = (
                "💓 <b>Trading Agent — Heartbeat</b>\n\n"
                f"Status: <b>Running</b>  ({mode})\n"
                "(Portfolio data unavailable this cycle)"
            )
        for chat_id in allowed_ids:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
            except Exception as exc:
                log.warning("Heartbeat Telegram send failed for %s: %s", chat_id, exc)

    # ── Signal outcome resolution ─────────────────────────────────────────────

    def _resolve_signal_outcomes(self) -> None:
        """Hourly job: fill in price/outcome columns for pending signal history rows."""
        try:
            from brain import signal_history as _sh

            def _fetch_price(symbol: str, asset_class: str) -> float | None:
                try:
                    r = httpx.get(
                        f"{self._brain_url}/bars/{symbol}",
                        params={"days": 1, "asset_class": asset_class},
                        timeout=10,
                        headers=self._brain_headers(),
                    )
                    if r.status_code == 200:
                        d = r.json()
                        return d.get("current_price") or None
                except Exception as exc:
                    log.debug("Price fetch for outcome resolution failed %s: %s", symbol, exc)
                return None

            updated = _sh.resolve_pending_outcomes(_fetch_price)
            if updated:
                log.info("Signal outcome resolution: %d rows updated", updated)
        except Exception as exc:
            log.warning("Signal outcome resolution failed (non-fatal): %s", exc)

    def _refresh_congress_disclosures(self) -> None:
        """6-hourly job: pull latest STOCK Act trade disclosures from public APIs."""
        try:
            from brain.congress_fetcher import refresh as _refresh
            new_rows = _refresh()
            log.info("Congressional disclosure refresh: %d new trades", new_rows)
        except Exception as exc:
            log.warning("Congressional disclosure refresh failed (non-fatal): %s", exc)

    def _refresh_13f_holdings(self) -> None:
        """Daily job: fetch latest 13F filings from SEC EDGAR for tracked investors."""
        try:
            from brain.sec_fetcher import refresh_all as _refresh_all
            results = _refresh_all()
            success = sum(1 for v in results.values() if v)
            log.info("13F holdings refresh: %d/%d investors updated", success, len(results))
        except Exception as exc:
            log.warning("13F holdings refresh failed (non-fatal): %s", exc)

    def _resolve_snapshot_outcomes(self) -> None:
        """Hourly job: fill price checkpoints for Supabase signal_snapshots."""
        try:
            from brain import signal_snapshots as _ss

            def _fetch_price(symbol: str, asset_class: str) -> float | None:
                try:
                    r = httpx.get(
                        f"{self._brain_url}/bars/{symbol}",
                        params={"days": 1, "asset_class": asset_class},
                        timeout=10,
                        headers=self._brain_headers(),
                    )
                    if r.status_code == 200:
                        return r.json().get("current_price") or None
                except Exception as exc:
                    log.debug("Price fetch for snapshot outcome failed %s: %s", symbol, exc)
                return None

            updated = _ss.resolve_pending_outcomes(_fetch_price)
            if updated:
                log.info("Snapshot outcome resolution: %d rows updated", updated)
        except Exception as exc:
            log.warning("Snapshot outcome resolution failed (non-fatal): %s", exc)

    def _record_daily_portfolio_snapshot(self) -> None:
        """Daily job at 21:00 UTC: capture NAV + SPY/BTC closes to Supabase."""
        try:
            if not self._alpaca_client:
                log.debug("Daily portfolio snapshot: no Alpaca client — skipping")
                return
            acct = self._alpaca_client.get_account()
            nav      = float(acct.equity or 0)
            cash     = float(acct.cash or 0)
            invested = max(nav - cash, 0.0)
            daily_pnl = nav - float(acct.equity_previous_close or nav)
            positions = self._alpaca_client.get_all_positions()

            from brain import portfolio_snapshots as _ps
            _ps.record_daily_snapshot(
                nav=nav, cash=cash, invested=invested, daily_pnl=daily_pnl,
                positions_count=len(positions),
                peak_nav=self._peak_equity,
                initial_nav=100_000.0,
            )
        except Exception as exc:
            log.warning("Daily portfolio snapshot failed (non-fatal): %s", exc)

    # ── Scheduled jobs ────────────────────────────────────────────────────────

    def _run_cycle(self) -> None:
        log.info("=" * 60)
        log.info("=== Cycle start %s ===", datetime.now(timezone.utc).isoformat())
        log.info("=" * 60)
        # Rotate COLD cooldown: push curr into history, open a fresh set for this cycle.
        with self._cold_lock:
            self._cold_history.appendleft(self._curr_cold_symbols)
            self._curr_cold_symbols = set()
            cooled_count = len(set().union(*self._cold_history))
            _save_cold_history(self._cold_history)
        if cooled_count:
            log.info("COLD cooldown: %d symbol(s) on cooldown (window = %d cycle(s))",
                     cooled_count, self._cfg.cold_skip_cycles)

        try:
            portfolio = self._refresh_portfolio_metrics()
        except Exception as exc:
            log.error("Portfolio refresh failed: %s — using defaults", exc)
            portfolio = PortfolioState(
                timestamp=datetime.now(timezone.utc),
                equity=100_000.0, cash=100_000.0,
            )

        self._check_retrain(portfolio)

        # Stock/ETF analysis only runs 5am–7pm ET Mon–Fri.
        # Crypto runs 24/7 — those markets never close.
        stock_window_open = self._is_stock_analysis_window()
        if not stock_window_open:
            log.info(
                "Outside US equity analysis window (5am–7pm ET Mon–Fri) — "
                "skipping %d stock/ETF symbols; crypto-only cycle",
                len(STOCK_WATCHLIST) + len(ETF_WATCHLIST),
            )

        all_symbols = (
            ([(s, "stock") for s in STOCK_WATCHLIST] +
             [(s, "stock") for s in ETF_WATCHLIST]
             if stock_window_open else []) +
            [(s, "crypto") for s in CRYPTO_WATCHLIST]
        )

        if not all_symbols:
            log.info("No symbols to process this cycle — skipping.")
            return

        # Parallel symbol processing:
        # Paper mode (rule-based, no LLM): 16 workers — zero API calls, pure computation.
        # Live mode (LLM debate): 8 workers — I/O-bound LLM calls; parallelism pays.
        max_workers = 16 if self._paper_mode else 8
        log.info("Processing %d symbols  workers=%d  mode=%s",
                 len(all_symbols), max_workers, "paper" if self._paper_mode else "live")

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._process_symbol, sym, cls, portfolio): (sym, cls)
                for sym, cls in all_symbols
            }
            for fut in as_completed(futures):
                sym, cls = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    log.error("Unhandled error processing %s: %s", sym, exc)

        log.info("=== Cycle complete ===")

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        # Wait for Brain API — retry indefinitely in 30s windows rather than exiting
        while not _wait_for_brain(self._brain_url, timeout_secs=120):
            log.warning("Brain API not ready — retrying in 30s …")
            time.sleep(30)

        try:
            start_metrics_server(port=8001)
            log.info("Metrics server started on :8001")
        except Exception as exc:
            log.warning("Metrics server failed to start (non-fatal): %s", exc)

        schedule.every(CYCLE_INTERVAL_MINUTES).minutes.do(self._run_cycle)
        schedule.every(1).minutes.do(self._refresh_portfolio_metrics)
        schedule.every(1).minutes.do(self._monitor_positions)
        schedule.every(30).minutes.do(self._check_api_credits)
        schedule.every(1).hours.do(self._resolve_signal_outcomes)
        schedule.every(1).hours.do(self._resolve_snapshot_outcomes)
        schedule.every(6).hours.do(self._refresh_congress_disclosures)
        schedule.every(6).hours.do(self._send_heartbeat)
        schedule.every(1).days.do(self._refresh_13f_holdings)
        schedule.every(1).days.at("21:00").do(self._record_daily_portfolio_snapshot)

        total_symbols = len(STOCK_WATCHLIST) + len(ETF_WATCHLIST) + len(CRYPTO_WATCHLIST)
        log.info(
            "Orchestrator ready — scanning %d symbols every %d min "
            "(%d stocks, %d ETFs, %d crypto)  position monitor: 1 min  mode=%s",
            total_symbols, CYCLE_INTERVAL_MINUTES,
            len(STOCK_WATCHLIST), len(ETF_WATCHLIST), len(CRYPTO_WATCHLIST),
            "rule-based" if self._paper_mode else "LLM",
        )
        self._monitor_positions()  # check existing positions before first cycle
        self._run_cycle()          # run immediately on start
        self._send_heartbeat()     # notify operators the system has started

        while True:
            try:
                schedule.run_pending()
            except Exception as exc:
                log.error("Unhandled exception in scheduler loop (non-fatal, continuing): %s", exc, exc_info=True)
            time.sleep(10)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    Orchestrator().run()
