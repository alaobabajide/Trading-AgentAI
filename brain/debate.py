"""Brain orchestration — 9-agent debate with deterministic vote-count tier classification."""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal

import anthropic
import ta
import pandas as pd

from data.market_data import MarketSnapshot
from data.sentiment import SentimentBundle
from data.onchain import OnChainSnapshot
from data.portfolio import PortfolioState
from brain.signal import TradingSignal
from brain.agents.fundamental import FundamentalAnalyst
from brain.agents.technical import TechnicalAnalyst
from brain.agents.sentiment import SentimentAnalyst
from brain.agents.macro import MacroEconomist
from brain.agents.quant import QuantAnalyst
from brain.agents.options_flow import OptionsFlowAnalyst
from brain.agents.regime import RegimeDetector
from brain.agents.strategy import StrategyCoach
from brain.agents.risk_manager import RiskManager

log = logging.getLogger(__name__)


# ── Strategic-layer cache (60s TTL for slow/stable macro + regime) ────────────

class _StrategicCache:
    TTL = 60

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry and (time.monotonic() - entry[0]) < self.TTL:
            return entry[1]
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)


_cache = _StrategicCache()


# ── Regime weight tracker (purges on >20% ATR shift) ─────────────────────────

class _RegimeWeightTracker:
    PURGE_THRESHOLD = 0.20
    PURGE_LOCKOUT   = 7 * 86400

    def __init__(self) -> None:
        self._weights: dict[str, float] = {}
        self._atr_baseline: float | None = None
        self._last_purge: float = 0.0

    def record_atr(self, atr_pct: float) -> bool:
        if self._atr_baseline is None:
            self._atr_baseline = atr_pct
            return False
        shift = abs(atr_pct - self._atr_baseline) / max(self._atr_baseline, 1e-9)
        if shift > self.PURGE_THRESHOLD:
            now = time.monotonic()
            if (now - self._last_purge) > self.PURGE_LOCKOUT:
                log.warning("Regime shift %.1f%% — purging agent weights", shift * 100)
                self._weights.clear()
                self._atr_baseline = atr_pct
                self._last_purge = now
                return True
        return False

    def weight(self, agent: str) -> float:
        return self._weights.get(agent, 1.0)


_regime_tracker = _RegimeWeightTracker()


# ── Vote-counting helpers ─────────────────────────────────────────────────────

def _parse_direction(view: str) -> Literal["BULLISH", "BEARISH", "NEUTRAL"]:
    """Extract DIRECTION: from agent output text."""
    m = re.search(r"DIRECTION:\s*(BULLISH|BEARISH|NEUTRAL)", view, re.IGNORECASE)
    if m:
        return m.group(1).upper()  # type: ignore[return-value]
    return "NEUTRAL"


def _parse_regime_label(regime_view: str) -> str:
    """Extract REGIME: label from deterministic regime output."""
    m = re.search(r"REGIME:\s*(\w+)", regime_view, re.IGNORECASE)
    return m.group(1).upper() if m else "UNKNOWN"


def _count_votes(analyst_views: dict[str, str]) -> dict[str, int]:
    """
    Count BULLISH / BEARISH / NEUTRAL across the 7 specialist analysts.
    Excludes the strategy coach and risk manager (they don't cast direction votes).
    """
    VOTERS = {"fundamental", "technical", "sentiment", "macro", "quant", "options_flow", "regime"}
    tally = {"bullish": 0, "bearish": 0, "neutral": 0}
    for key, view in analyst_views.items():
        if key not in VOTERS:
            continue
        direction = _parse_direction(view)
        if direction == "BULLISH":
            tally["bullish"] += 1
        elif direction == "BEARISH":
            tally["bearish"] += 1
        else:
            tally["neutral"] += 1
    return tally


def _action_from_votes(
    tally: dict[str, int],
    threshold: int = 4,
) -> Literal["BUY", "SELL", "HOLD"]:
    """
    Majority-vote arbiter.  Requires threshold/7 agents to agree.
    Default threshold = 4 (simple majority).
    """
    if tally["bullish"] >= threshold:
        return "BUY"
    if tally["bearish"] >= threshold:
        return "SELL"
    return "HOLD"


def _compute_tier(
    tally: dict[str, int],
    action: str,
    regime_label: str,
    indicators: dict[str, Any],
) -> Literal["HOT", "WARM", "COLD"]:
    """
    Deterministic tier from vote count + regime — no LLM confidence involved.

    HOT  = 6 or 7 analysts aligned AND regime is TRENDING (not HIGH_VOL / RANGING)
    WARM = 4 or 5 analysts aligned AND regime allows trading
    COLD = 3 or fewer aligned  OR  HIGH_VOLATILITY  OR  RANGING regime
    """
    aligned  = tally["bullish"] if action == "BUY" else tally["bearish"] if action == "SELL" else 0
    high_vol = (
        "HIGH_VOLATILITY" in regime_label
        or (indicators.get("atr_14", 0) / max(indicators.get("price", 1), 1)) > 0.03
    )
    blocked  = high_vol or "RANGING" in regime_label or action == "HOLD"

    if blocked or aligned <= 3:
        return "COLD"
    if aligned >= 6:
        return "HOT"
    return "WARM"


def _parse_strategy_fit(
    strategy_raw: str,
) -> Literal["ALIGNED", "MISALIGNED", "PARTIAL"]:
    m = strategy_raw.upper()
    if "MISALIGNED" in m:
        return "MISALIGNED"
    if "PARTIAL" in m:
        return "PARTIAL"
    return "ALIGNED"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bars_to_dicts(snapshot: MarketSnapshot) -> list[dict]:
    return [
        {
            "date":   b.timestamp.date().isoformat(),
            "open":   b.open, "high": b.high,
            "low":    b.low,  "close": b.close,
            "volume": b.volume,
        }
        for b in snapshot.bars[-60:]
    ]


def _compute_indicators(snapshot: MarketSnapshot) -> dict[str, Any]:
    if len(snapshot.bars) < 20:
        return {}
    closes = pd.Series([b.close for b in snapshot.bars])
    highs  = pd.Series([b.high  for b in snapshot.bars])
    lows   = pd.Series([b.low   for b in snapshot.bars])

    rsi         = ta.momentum.RSIIndicator(closes).rsi().iloc[-1]
    macd_ind    = ta.trend.MACD(closes)
    atr         = ta.volatility.AverageTrueRange(highs, lows, closes).average_true_range().iloc[-1]
    bb          = ta.volatility.BollingerBands(closes)

    return {
        "rsi_14":      round(float(rsi), 2),
        "macd":        round(float(macd_ind.macd().iloc[-1]), 4),
        "macd_signal": round(float(macd_ind.macd_signal().iloc[-1]), 4),
        "atr_14":      round(float(atr), 4),
        "bb_upper":    round(float(bb.bollinger_hband().iloc[-1]), 4),
        "bb_lower":    round(float(bb.bollinger_lband().iloc[-1]), 4),
        "bb_width":    round(float(bb.bollinger_wband().iloc[-1]), 4),
        "price":       snapshot.bars[-1].close,
    }


# ── Default user profile ──────────────────────────────────────────────────────

DEFAULT_PROFILE = {
    "mode":             "assisted",
    "time_horizon":     "swing",
    "max_drawdown_pct": 10,
    "max_position_pct": 5,
}


# ── Main orchestrator ─────────────────────────────────────────────────────────

class DebateOrchestrator:
    """Runs all nine agents and returns a TradingSignal gated by majority vote."""

    def __init__(
        self,
        anthropic_api_key: str,
        confidence_threshold: float = 0.7,   # retained for Risk Manager compat; not used for gating
        max_position_pct: float = 0.05,
        max_crypto_pct: float = 0.30,
        circuit_breaker_drawdown: float = 0.10,
    ) -> None:
        client = anthropic.Anthropic(api_key=anthropic_api_key)

        self._fundamental     = FundamentalAnalyst(client)
        self._technical       = TechnicalAnalyst(client)
        self._sentiment_agent = SentimentAnalyst(client)
        self._macro           = MacroEconomist(client)
        self._quant           = QuantAnalyst(client)
        self._options_flow    = OptionsFlowAnalyst(client)
        self._regime          = RegimeDetector(client)   # deterministic — client ignored
        self._strategy        = StrategyCoach(client)
        self._risk            = RiskManager(client)

        self._threshold   = confidence_threshold
        self._max_pos     = max_position_pct
        self._max_crypto  = max_crypto_pct
        self._cb_drawdown = circuit_breaker_drawdown

    def run(
        self,
        market: MarketSnapshot,
        sentiment: SentimentBundle,
        onchain: OnChainSnapshot | None,
        portfolio: PortfolioState,
        user_profile: dict | None = None,
    ) -> TradingSignal:
        symbol      = market.symbol
        asset_class = market.asset_class
        profile     = user_profile or DEFAULT_PROFILE
        log.info("9-agent debate starting: %s (%s)", symbol, asset_class)

        bars_dicts = _bars_to_dicts(market)
        indicators = _compute_indicators(market)

        price   = indicators.get("price", 1.0) or 1.0
        atr_pct = indicators.get("atr_14", 0.0) / price
        _regime_tracker.record_atr(atr_pct)

        # ── Round 1: all 7 analysts in parallel ──────────────────────────────
        # Regime is deterministic (no LLM call) so it completes instantly.
        # Macro is cache-backed; on a cache hit it also returns instantly.
        cache_key = f"{symbol}:strategic"
        cached_strategic = _cache.get(cache_key)

        regime_ctx = {"symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators}
        macro_ctx  = {
            "symbol": symbol, "asset_class": asset_class,
            "bars_last_60": bars_dicts, "indicators": indicators,
            "portfolio_equity": portfolio.equity,
            "daily_pnl_pct": portfolio.daily_pnl_pct,
        }
        tactical_tasks = {
            "fundamental": (self._fundamental.analyse, {
                "symbol": symbol, "asset_class": asset_class,
                "bars_last_60": bars_dicts,
                "onchain": onchain.__dict__ if onchain else {},
                "portfolio_equity": portfolio.equity,
            }),
            "technical": (self._technical.analyse, {
                "symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators,
            }),
            "sentiment": (self._sentiment_agent.analyse, {
                "symbol": symbol,
                "news_items": [
                    {"source": n.source, "headline": n.headline, "published": n.published.isoformat()}
                    for n in sentiment.items[:30]
                ],
            }),
            "quant": (self._quant.analyse, {
                "symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators,
            }),
            "options_flow": (self._options_flow.analyse, {
                "symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators,
            }),
        }

        analyst_views: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=7) as pool:
            futures: dict[Any, str] = {}

            # Regime always runs (deterministic, microseconds)
            futures[pool.submit(self._regime.analyse, regime_ctx)] = "regime"

            # Macro: use cache if available, otherwise run in parallel
            if cached_strategic:
                macro_view, regime_view_cached = cached_strategic
                analyst_views["macro"] = macro_view
                log.debug("Macro served from cache for %s", symbol)
            else:
                futures[pool.submit(self._macro.analyse, macro_ctx)] = "macro"

            # All 5 tactical agents in parallel
            for role, (fn, ctx) in tactical_tasks.items():
                futures[pool.submit(fn, ctx)] = role

            for fut in as_completed(futures):
                role = futures[fut]
                try:
                    analyst_views[role] = fut.result()
                except Exception as exc:
                    log.error("Agent %s failed: %s", role, exc)
                    analyst_views[role] = f"DIRECTION: NEUTRAL\nREASONING: Agent error — {exc}"

        # Persist macro+regime to strategic cache if freshly computed
        if "macro" in analyst_views:
            _cache.set(cache_key, (analyst_views["macro"], analyst_views.get("regime", "")))

        for role, view in analyst_views.items():
            log.info("%s: %s", role.title(), view[:80])

        # ── Vote counting — determines action (replaces LLM confidence gate) ──
        vote_tally       = _count_votes(analyst_views)
        action           = _action_from_votes(vote_tally, threshold=4)
        regime_view      = analyst_views.get("regime", "")
        regime_label     = _parse_regime_label(regime_view)
        votes_for_action = vote_tally["bullish"] if action == "BUY" else vote_tally["bearish"] if action == "SELL" else 0

        log.info(
            "Vote tally: %s → action=%s regime=%s",
            vote_tally, action, regime_label,
        )

        # ── Round 2: Risk Manager + Strategy Coach in parallel ────────────────
        risk_ctx = {
            "symbol": symbol, "asset_class": asset_class,
            "action_from_votes": action,
            "vote_tally": vote_tally,
            "analyst_opinions": analyst_views,
            "portfolio": {
                "equity":                portfolio.equity,
                "daily_pnl_pct":         portfolio.daily_pnl_pct,
                "crypto_allocation_pct": portfolio.crypto_allocation_pct,
            },
            "risk_limits": {
                "max_position_pct":         self._max_pos,
                "max_crypto_pct":           self._max_crypto,
                "circuit_breaker_drawdown": self._cb_drawdown,
            },
        }
        strategy_ctx = {
            "market_analysis": {
                "symbol": symbol, "action": action,
                "vote_tally": vote_tally, "analyst_opinions": analyst_views,
            },
            "trader_profile": profile,
            "portfolio": {
                "equity": portfolio.equity, "daily_pnl_pct": portfolio.daily_pnl_pct,
            },
        }

        with ThreadPoolExecutor(max_workers=2) as pool:
            risk_future     = pool.submit(self._risk.analyse, risk_ctx)
            strategy_future = pool.submit(self._strategy.analyse, strategy_ctx)
            try:
                risk_raw = risk_future.result()
            except Exception as exc:
                log.error("Risk manager failed: %s", exc)
                risk_raw = json.dumps({
                    "action": action, "confidence": 0.0,
                    "rationale": f"Risk manager error: {exc}",
                    "suggested_position_pct": 0.02,
                    "stop_loss_pct": 0.02, "take_profit_pct": 0.05,
                    "devil_advocate_score": 0, "devil_advocate_case": "",
                })
            try:
                strategy_view = strategy_future.result()
            except Exception as exc:
                log.error("Strategy coach failed: %s", exc)
                strategy_view = "ALIGNED"

        try:
            parsed = json.loads(risk_raw)
        except json.JSONDecodeError:
            log.warning("Risk manager non-JSON — using defaults: %s", risk_raw[:120])
            parsed = {
                "action": action, "confidence": 0.0, "rationale": risk_raw,
                "devil_advocate_score": 0, "devil_advocate_case": "",
            }

        strategy_fit = _parse_strategy_fit(strategy_view)

        # ── Tier — deterministic from votes + regime ──────────────────────────
        tier = _compute_tier(vote_tally, action, regime_label, indicators)

        signal = TradingSignal(
            symbol=symbol,
            asset_class=asset_class,
            action=action,
            confidence=float(parsed.get("confidence", 0.0)),  # kept for display only
            rationale=parsed.get("rationale", f"Vote: {vote_tally}"),
            tier=tier,
            vote_tally=vote_tally,
            votes_for_action=votes_for_action,
            regime_label=regime_label,
            suggested_position_pct=float(parsed.get("suggested_position_pct", 0.0)),
            stop_loss_pct=float(parsed.get("stop_loss_pct", 0.02)),
            take_profit_pct=float(parsed.get("take_profit_pct", 0.05)),
            devil_advocate_score=int(parsed.get("devil_advocate_score", 0)),
            devil_advocate_case=parsed.get("devil_advocate_case", ""),
            strategy_fit=strategy_fit,
            fundamental_view=fundamental_view,
            technical_view=technical_view,
            sentiment_view=sentiment_view,
            macro_view=macro_view,
            quant_view=quant_view,
            options_flow_view=options_flow_view,
            regime_view=regime_view,
            strategy_view=strategy_view,
            risk_view=risk_raw,
        )

        log.info(
            "Signal: %s %s tier=%s votes=%d/7 regime=%s fit=%s",
            action, symbol, tier, votes_for_action, regime_label, strategy_fit,
        )
        return signal
