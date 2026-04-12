"""Brain orchestration — 9-agent HITL debate with tier classification and regime weight decay."""
from __future__ import annotations

import json
import logging
import time
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


# ── Strategic-layer cache (Solution 7: edge-cached inference) ─────────────────

class _StrategicCache:
    """
    Caches the outputs of slow/stable agents (macro, regime) for 60 s so that
    intraday price ticks only need to re-run the fast tactical agents.
    """
    TTL = 60  # seconds

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


# ── Regime-aware weight tracker (Solution 4) ─────────────────────────────────

class _RegimeWeightTracker:
    """
    Tracks per-agent override win rates but purges learned weights when
    the volatility regime changes significantly (>20% shift in ATR z-score),
    preventing the overfitting trap.
    """
    PURGE_THRESHOLD = 0.20   # 20% regime shift triggers purge
    PURGE_LOCKOUT = 7 * 86400  # 1 week in seconds

    def __init__(self) -> None:
        self._weights: dict[str, float] = {}
        self._atr_baseline: float | None = None
        self._last_purge: float = 0.0

    def record_atr(self, atr_pct: float) -> bool:
        """Returns True if regime has shifted and weights were purged."""
        if self._atr_baseline is None:
            self._atr_baseline = atr_pct
            return False

        shift = abs(atr_pct - self._atr_baseline) / max(self._atr_baseline, 1e-9)
        if shift > self.PURGE_THRESHOLD:
            now = time.monotonic()
            if (now - self._last_purge) > self.PURGE_LOCKOUT:
                log.warning(
                    "Regime shift detected (ATR Δ=%.1f%%) — purging learned agent weights",
                    shift * 100,
                )
                self._weights.clear()
                self._atr_baseline = atr_pct
                self._last_purge = now
                return True
        return False

    def weight(self, agent: str) -> float:
        return self._weights.get(agent, 1.0)


_regime_tracker = _RegimeWeightTracker()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bars_to_dicts(snapshot: MarketSnapshot) -> list[dict]:
    return [
        {
            "date":   b.timestamp.date().isoformat(),
            "open":   b.open,
            "high":   b.high,
            "low":    b.low,
            "close":  b.close,
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
    macd_line   = ta.trend.MACD(closes).macd().iloc[-1]
    macd_signal = ta.trend.MACD(closes).macd_signal().iloc[-1]
    atr         = ta.volatility.AverageTrueRange(highs, lows, closes).average_true_range().iloc[-1]
    bb          = ta.volatility.BollingerBands(closes)
    bb_width    = float(bb.bollinger_wband().iloc[-1])

    return {
        "rsi_14":      round(float(rsi), 2),
        "macd":        round(float(macd_line), 4),
        "macd_signal": round(float(macd_signal), 4),
        "atr_14":      round(float(atr), 4),
        "bb_upper":    round(float(bb.bollinger_hband().iloc[-1]), 4),
        "bb_lower":    round(float(bb.bollinger_lband().iloc[-1]), 4),
        "bb_width":    round(bb_width, 4),
        "price":       snapshot.bars[-1].close,
    }


def _compute_tier(
    confidence: float,
    indicators: dict[str, Any],
) -> Literal["HOT", "WARM", "COLD"]:
    """
    Solution 1 — Tiered Confirmation.
    HOT  (confidence ≥ 0.85, low volatility)  → auto-execute in Auto mode
    WARM (confidence 0.70–0.85)               → 10-second veto window in Assisted mode
    COLD (confidence < 0.70 OR high vol)      → requires explicit click in all modes
    """
    price   = indicators.get("price", 1.0) or 1.0
    atr     = indicators.get("atr_14", 0.0)
    atr_pct = atr / price

    if confidence < 0.70 or atr_pct > 0.03:
        return "COLD"
    if confidence >= 0.85 and atr_pct < 0.02:
        return "HOT"
    return "WARM"


def _parse_strategy_fit(strategy_raw: str) -> Literal["ALIGNED", "MISALIGNED", "PARTIAL"]:
    m = strategy_raw.upper()
    if "MISALIGNED" in m:
        return "MISALIGNED"
    if "PARTIAL" in m:
        return "PARTIAL"
    return "ALIGNED"


# ── Default user profile (overridden when profile is passed in) ───────────────

DEFAULT_PROFILE = {
    "mode":            "assisted",
    "time_horizon":    "swing",
    "max_drawdown_pct": 10,
    "max_position_pct": 5,
}


# ── Main orchestrator ─────────────────────────────────────────────────────────

class DebateOrchestrator:
    """Runs all nine agents and returns a final TradingSignal with HITL metadata."""

    def __init__(
        self,
        anthropic_api_key: str,
        confidence_threshold: float = 0.7,
        max_position_pct: float = 0.05,
        max_crypto_pct: float = 0.30,
        circuit_breaker_drawdown: float = 0.10,
    ) -> None:
        client = anthropic.Anthropic(api_key=anthropic_api_key)

        # Seven specialist market analysts
        self._fundamental     = FundamentalAnalyst(client)
        self._technical       = TechnicalAnalyst(client)
        self._sentiment_agent = SentimentAnalyst(client)
        self._macro           = MacroEconomist(client)
        self._quant           = QuantAnalyst(client)
        self._options_flow    = OptionsFlowAnalyst(client)
        self._regime          = RegimeDetector(client)

        # Ninth agent: Strategy Coach (profile-decoupled)
        self._strategy = StrategyCoach(client)

        # Final arbitrator with adversarial DA scoring
        self._risk = RiskManager(client)

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
        log.info("9-agent debate starting for %s (%s)", symbol, asset_class)

        bars_dicts = _bars_to_dicts(market)
        indicators = _compute_indicators(market)

        # Regime weight tracking (Solution 4)
        price   = indicators.get("price", 1.0) or 1.0
        atr_pct = indicators.get("atr_14", 0.0) / price
        regime_purged = _regime_tracker.record_atr(atr_pct)
        if regime_purged:
            log.info("Agent weights reset to equal — regime shift detected")

        # ── Strategic layer (cache-backed, Solution 7) ────────────────────────
        cache_key = f"{symbol}:strategic"
        cached = _cache.get(cache_key)
        if cached:
            macro_view, regime_view = cached
            log.debug("Strategic layer served from cache for %s", symbol)
        else:
            macro_ctx = {
                "symbol": symbol,
                "asset_class": asset_class,
                "bars_last_60": bars_dicts,
                "indicators": indicators,
                "portfolio_equity": portfolio.equity,
                "daily_pnl_pct": portfolio.daily_pnl_pct,
            }
            regime_ctx = {"symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators}
            macro_view  = self._macro.analyse(macro_ctx)
            regime_view = self._regime.analyse(regime_ctx)
            _cache.set(cache_key, (macro_view, regime_view))

        # ── Tactical layer (always fresh) ─────────────────────────────────────
        fundamental_view  = self._fundamental.analyse({
            "symbol": symbol, "asset_class": asset_class,
            "bars_last_60": bars_dicts, "onchain": onchain.__dict__ if onchain else {},
            "portfolio_equity": portfolio.equity,
        })
        technical_view    = self._technical.analyse({
            "symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators,
        })
        sentiment_view    = self._sentiment_agent.analyse({
            "symbol": symbol,
            "news_items": [
                {"source": n.source, "headline": n.headline, "published": n.published.isoformat()}
                for n in sentiment.items[:30]
            ],
        })
        quant_view        = self._quant.analyse({
            "symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators,
        })
        options_flow_view = self._options_flow.analyse({
            "symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators,
        })

        for role, view in [
            ("Fundamental",  fundamental_view),
            ("Technical",    technical_view),
            ("Sentiment",    sentiment_view),
            ("Macro",        macro_view),
            ("Quant",        quant_view),
            ("OptionsFlow",  options_flow_view),
            ("Regime",       regime_view),
        ]:
            log.info("%s: %s", role, view[:80])

        # ── Risk Manager — synthesises all 7 analysts with DA scoring ─────────
        daily_drawdown = abs(portfolio.daily_pnl_pct) / 100
        risk_ctx = {
            "symbol": symbol,
            "asset_class": asset_class,
            "analyst_opinions": {
                "fundamental":  fundamental_view,
                "technical":    technical_view,
                "sentiment":    sentiment_view,
                "macro":        macro_view,
                "quant":        quant_view,
                "options_flow": options_flow_view,
                "regime":       regime_view,
            },
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
        risk_raw = self._risk.analyse(risk_ctx)

        try:
            parsed = json.loads(risk_raw)
        except json.JSONDecodeError:
            log.warning("Risk manager returned non-JSON — defaulting to HOLD: %s", risk_raw)
            parsed = {
                "action": "HOLD", "confidence": 0.0, "rationale": risk_raw,
                "devil_advocate_score": 0, "devil_advocate_case": "",
            }

        confidence = float(parsed.get("confidence", 0.0))
        action     = parsed.get("action", "HOLD")

        # ── Strategy Coach — profile-decoupled coaching (Solution 3) ──────────
        strategy_ctx = {
            "market_analysis": {
                "symbol": symbol, "action": action, "confidence": confidence,
                "rationale": parsed.get("rationale", ""),
            },
            "trader_profile": profile,
            "portfolio": {"equity": portfolio.equity, "daily_pnl_pct": portfolio.daily_pnl_pct},
        }
        strategy_view = self._strategy.analyse(strategy_ctx)
        strategy_fit  = _parse_strategy_fit(strategy_view)

        # ── Tier classification — drives HITL confirmation UX ─────────────────
        tier = _compute_tier(confidence, indicators)

        # ── Confidence gate ───────────────────────────────────────────────────
        if confidence < self._threshold and action != "HOLD":
            log.info(
                "Signal for %s below threshold (%.2f < %.2f) — downgrading to HOLD",
                symbol, confidence, self._threshold,
            )
            action = "HOLD"

        signal = TradingSignal(
            symbol=symbol,
            asset_class=asset_class,
            action=action,
            confidence=confidence,
            rationale=parsed.get("rationale", ""),
            tier=tier,
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
            "Final signal: %s %s tier=%s confidence=%.2f da_score=%d fit=%s",
            signal.action, symbol, signal.tier,
            signal.confidence, signal.devil_advocate_score, signal.strategy_fit,
        )
        return signal
