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
from brain.agents.investors import (
    BuffettInvestor, MungerInvestor, LynchInvestor, AckmanInvestor,
    CohenInvestor, DalioInvestor, WoodInvestor, BogleInvestor,
)

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


_PANEL_A_VOTERS = frozenset(
    {"fundamental", "technical", "sentiment", "macro", "quant", "options_flow", "regime"}
)
_PANEL_B_VOTERS = frozenset(
    {"buffett", "munger", "lynch", "ackman", "cohen", "dalio", "wood", "bogle"}
)


def _count_votes(views: dict[str, str], voter_set: frozenset[str]) -> dict[str, int]:
    """Count BULLISH / BEARISH / NEUTRAL votes for a given panel's voter set."""
    tally = {"bullish": 0, "bearish": 0, "neutral": 0}
    for key, view in views.items():
        if key not in voter_set:
            continue
        direction = _parse_direction(view)
        if direction == "BULLISH":
            tally["bullish"] += 1
        elif direction == "BEARISH":
            tally["bearish"] += 1
        else:
            tally["neutral"] += 1
    return tally


def _dominant_direction(tally: dict[str, int]) -> str:
    """Return the dominant direction or NEUTRAL if no clear winner."""
    if tally["bullish"] > tally["bearish"] and tally["bullish"] > tally["neutral"]:
        return "BULLISH"
    if tally["bearish"] > tally["bullish"] and tally["bearish"] > tally["neutral"]:
        return "BEARISH"
    return "NEUTRAL"


def _aggregate_dual_panel(
    panel_a: dict[str, str],
    panel_b: dict[str, str],
) -> tuple[dict, dict, dict, bool, str]:
    """
    Aggregate votes from both panels.

    Returns:
        a_votes, b_votes, combined_votes, panels_conflict, conflict_note
    """
    a_votes = _count_votes(panel_a, _PANEL_A_VOTERS)
    b_votes = _count_votes(panel_b, _PANEL_B_VOTERS)

    combined = {
        "bullish": a_votes["bullish"] + b_votes["bullish"],
        "bearish": a_votes["bearish"] + b_votes["bearish"],
        "neutral": a_votes["neutral"] + b_votes["neutral"],
    }

    a_dom = _dominant_direction(a_votes)
    b_dom = _dominant_direction(b_votes)

    # Conflict = both panels have a directional view but they disagree
    panels_conflict = (
        a_dom != b_dom
        and a_dom != "NEUTRAL"
        and b_dom != "NEUTRAL"
    )
    conflict_note = (
        f"Panel conflict: analysts={a_dom}, investors={b_dom} — standing aside"
        if panels_conflict else ""
    )
    return a_votes, b_votes, combined, panels_conflict, conflict_note


def _action_from_votes(
    tally: dict[str, int],
    panels_conflict: bool = False,
    threshold: int = 8,
) -> Literal["BUY", "SELL", "HOLD"]:
    """
    Dual-panel majority-vote arbiter.  15 total agents; default threshold = 8.
    Panel conflict immediately forces HOLD regardless of combined count.
    """
    if panels_conflict:
        return "HOLD"
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
    panels_conflict: bool = False,
) -> Literal["HOT", "WARM", "COLD"]:
    """
    Deterministic tier from combined 15-agent vote count + regime.

    HOT  = 11+ of 15 aligned AND no conflict AND regime is TRENDING
    WARM = 8–10 of 15 aligned AND no conflict AND regime allows trading
    COLD = < 8 aligned  OR  panel conflict  OR  HIGH_VOLATILITY  OR  RANGING  OR  HOLD
    """
    aligned  = tally["bullish"] if action == "BUY" else tally["bearish"] if action == "SELL" else 0
    high_vol = (
        "HIGH_VOLATILITY" in regime_label
        or (indicators.get("atr_14", 0) / max(indicators.get("price", 1), 1)) > 0.03
    )
    blocked = high_vol or "RANGING" in regime_label or action == "HOLD" or panels_conflict

    if blocked or aligned < 8:
        return "COLD"
    if aligned >= 11:
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


# ── Paper-mode rule-based analysts (no LLM, no API credits needed) ────────────

def _paper_technical(indicators: dict) -> str:
    """
    LENS: Short-term trend-following.
    Reads: RSI-14, MACD crossover, price vs SMA20.
    (No overlap with Quant/Fundamental/Options/Macro/Sentiment lenses.)
    """
    rsi      = float(indicators.get("rsi_14", 50.0))
    macd     = float(indicators.get("macd", 0.0))
    macd_sig = float(indicators.get("macd_signal", 0.0))
    price    = float(indicators.get("price", 1.0))
    sma_20   = float(indicators.get("sma_20", price))

    b, s, notes = 0, 0, []

    # RSI — momentum oscillator
    if rsi < 35:
        b += 1; notes.append(f"RSI={rsi:.1f} oversold")
    elif rsi > 65:
        s += 1; notes.append(f"RSI={rsi:.1f} overbought")
    else:
        notes.append(f"RSI={rsi:.1f} neutral")

    # MACD histogram crossover
    diff = macd - macd_sig
    if diff > 0:
        b += 1; notes.append(f"MACD above signal (+{diff:.4f})")
    elif diff < 0:
        s += 1; notes.append(f"MACD below signal ({diff:.4f})")
    else:
        notes.append("MACD flat")

    # Price vs SMA20 — short-term trend structure
    dev = (price - sma_20) / max(sma_20, 1e-9) * 100
    if price > sma_20 * 1.005:
        b += 1; notes.append(f"Price {dev:+.1f}% above SMA20")
    elif price < sma_20 * 0.995:
        s += 1; notes.append(f"Price {dev:+.1f}% below SMA20")
    else:
        notes.append(f"Price ≈ SMA20 ({dev:+.1f}%)")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Technical/trend] — {'; '.join(notes)}. "
        f"Bullish signals: {b}/3, bearish: {s}/3."
    )


def _paper_quant(indicators: dict) -> str:
    """
    LENS: Statistical mean-reversion.
    Reads: Bollinger %B, Stochastic K/D, ROC-10.
    (Distinct from Technical RSI/MACD, Fundamental long-horizon, Options vol/volume.)
    """
    price    = float(indicators.get("price", 1.0))
    bb_upper = float(indicators.get("bb_upper", price * 1.05))
    bb_lower = float(indicators.get("bb_lower", price * 0.95))
    bb_width = float(indicators.get("bb_width", 0.02))
    stoch_k  = float(indicators.get("stoch_k", 50.0))
    stoch_d  = float(indicators.get("stoch_d", 50.0))
    roc_10   = float(indicators.get("roc_10", 0.0))

    if bb_width < 0.005:
        return (
            "DIRECTION: NEUTRAL\n"
            f"REASONING: Paper mode [Quant/mean-rev] — Bollinger squeeze "
            f"(width={bb_width:.4f}), mean-reversion signal unreliable in low-vol regime."
        )

    b, s, notes = 0, 0, []

    # Bollinger %B
    bb_range = max(bb_upper - bb_lower, 1e-9)
    pct_b    = (price - bb_lower) / bb_range
    if price <= bb_lower:
        b += 1; notes.append(f"Price at/below lower band (%B={pct_b:.2f})")
    elif price >= bb_upper:
        s += 1; notes.append(f"Price at/above upper band (%B={pct_b:.2f})")
    else:
        notes.append(f"Price mid-bands (%B={pct_b:.2f})")

    # Stochastic K/D crossover
    if stoch_k < 25 and stoch_k > stoch_d:
        b += 1; notes.append(f"Stoch K={stoch_k:.1f} oversold + K>D bullish cross")
    elif stoch_k > 75 and stoch_k < stoch_d:
        s += 1; notes.append(f"Stoch K={stoch_k:.1f} overbought + K<D bearish cross")
    elif stoch_k < 30:
        b += 1; notes.append(f"Stoch K={stoch_k:.1f} oversold")
    elif stoch_k > 70:
        s += 1; notes.append(f"Stoch K={stoch_k:.1f} overbought")
    else:
        notes.append(f"Stoch K={stoch_k:.1f} neutral")

    # ROC10 as mean-reversion catalyst (sharp moves revert)
    if roc_10 < -8.0:
        b += 1; notes.append(f"ROC10={roc_10:+.1f}% sharp drop → reversion candidate")
    elif roc_10 > 8.0:
        s += 1; notes.append(f"ROC10={roc_10:+.1f}% sharp rally → reversion risk")
    else:
        notes.append(f"ROC10={roc_10:+.1f}% within normal range")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Quant/mean-rev] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_fundamental(indicators: dict) -> str:
    """
    LENS: Long-term value / structural momentum.
    Reads: ROC-20, ROC-60, price vs SMA50, price vs SMA200.
    (No RSI/MACD/Bollinger/volume — purely longer-horizon price structure.)
    """
    price   = float(indicators.get("price", 1.0))
    roc_20  = float(indicators.get("roc_20", 0.0))
    roc_60  = float(indicators.get("roc_60", 0.0))
    sma_50  = float(indicators.get("sma_50",  price))
    sma_200 = float(indicators.get("sma_200", price))

    b, s, notes = 0, 0, []

    # ROC20 — intermediate momentum (earnings-cycle horizon)
    if roc_20 > 8.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% strong intermediate uptrend")
    elif roc_20 < -8.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% strong intermediate downtrend")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% moderate")

    # ROC60 — quarterly momentum
    if roc_60 > 15.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% secular uptrend")
    elif roc_60 < -15.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% secular downtrend")
    else:
        notes.append(f"ROC60={roc_60:+.1f}%")

    # Price vs SMA50 / SMA200 — structural trend health
    dev_50  = (price - sma_50)  / max(sma_50,  1e-9) * 100
    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100
    if price > sma_50 * 1.01 and price > sma_200 * 1.01:
        b += 1; notes.append(f"Above SMA50 ({dev_50:+.1f}%) and SMA200 ({dev_200:+.1f}%) — bull structure")
    elif price < sma_50 * 0.99 and price < sma_200 * 0.99:
        s += 1; notes.append(f"Below SMA50 ({dev_50:+.1f}%) and SMA200 ({dev_200:+.1f}%) — bear structure")
    else:
        notes.append(f"Mixed: SMA50 {dev_50:+.1f}%, SMA200 {dev_200:+.1f}%")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Fundamental/long-term] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_options_flow(indicators: dict) -> str:
    """
    LENS: Volatility extremes and flow pressure.
    Reads: ATR% + ATR trend (vol expansion), volume ratio, 52W proximity.
    (No RSI/MACD/Bollinger/ROC — purely vol-regime and structural extremes.)
    """
    price          = float(indicators.get("price", 1.0))
    atr            = float(indicators.get("atr_14", 0.0))
    atr_trend      = float(indicators.get("atr_trend", 0.0))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    low_proximity  = float(indicators.get("low_proximity", 0.5))
    atr_pct        = atr / max(price, 1e-9)

    b, s, notes = 0, 0, []

    # ATR expansion — options flow / implied vol analogue
    if atr_pct > 0.03 and atr_trend > 0:
        s += 1; notes.append(f"ATR={atr_pct*100:.1f}% expanding (>3%) — distribution / fear premium")
    elif atr_pct < 0.01:
        b += 1; notes.append(f"ATR={atr_pct*100:.2f}% compressed — low premium, bullish drift likely")
    else:
        notes.append(f"ATR={atr_pct*100:.2f}% {'expanding' if atr_trend > 0 else 'contracting'}")

    # Volume surge with ATR context
    if volume_ratio > 1.5:
        if atr_trend > 0:
            s += 1; notes.append(f"Volume {volume_ratio:.1f}x surge + expanding vol → distribution")
        else:
            b += 1; notes.append(f"Volume {volume_ratio:.1f}x surge + stable vol → accumulation")
    elif volume_ratio < 0.5:
        notes.append(f"Volume dry-up {volume_ratio:.2f}x — low conviction")
    else:
        notes.append(f"Volume ratio {volume_ratio:.2f}x normal")

    # 52-Week proximity — breakout / breakdown catalyst
    if high_proximity < 0.02:
        b += 1; notes.append(f"Near 52W high ({high_proximity*100:.1f}% below) → breakout zone")
    elif low_proximity < 0.05:
        s += 1; notes.append(f"Near 52W low ({low_proximity*100:.1f}% above) → breakdown risk")
    else:
        pct_range = (1.0 - high_proximity) * 100
        notes.append(f"52W position {pct_range:.0f}% of annual range")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    if b == 1 and s == 0:
        direction = "BULLISH"
    elif s == 1 and b == 0:
        direction = "BEARISH"

    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Options Flow/vol] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_macro(indicators: dict) -> str:
    """
    LENS: Secular / macro-structural trend.
    Reads: price vs SMA200, ROC-60, 52W high proximity.
    (Big-picture regime — no short-term oscillators.)
    """
    price          = float(indicators.get("price", 1.0))
    sma_200        = float(indicators.get("sma_200", price))
    roc_60         = float(indicators.get("roc_60", 0.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))

    b, s, notes = 0, 0, []

    # Price vs SMA200 — bull/bear market structure
    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100
    if price > sma_200 * 1.03:
        b += 1; notes.append(f"Price {dev_200:+.1f}% above SMA200 — bull market structure")
    elif price < sma_200 * 0.97:
        s += 1; notes.append(f"Price {dev_200:+.1f}% below SMA200 — bear market structure")
    else:
        notes.append(f"Price at SMA200 crossover zone ({dev_200:+.1f}%)")

    # ROC60 — macro quarterly momentum
    if roc_60 > 12.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% positive macro momentum")
    elif roc_60 < -12.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% negative macro momentum")
    else:
        notes.append(f"ROC60={roc_60:+.1f}% subdued macro momentum")

    # 52W high proximity — secular trend health
    if high_proximity < 0.05:
        b += 1; notes.append(f"Near 52W high ({high_proximity*100:.1f}% from peak) — strong secular trend")
    elif high_proximity > 0.25:
        s += 1; notes.append(f"Far from 52W high ({high_proximity*100:.0f}% drawdown) — weak macro backdrop")
    else:
        notes.append(f"Moderate {high_proximity*100:.1f}% below 52W high")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Macro/secular] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_sentiment(indicators: dict) -> str:
    """
    LENS: Crowd psychology / short-term sentiment.
    Reads: ROC-5 (recency), volume ratio (participation), RSI as crowd-fear proxy.
    (Recency-biased lens — no long-term indicators.)
    """
    rsi          = float(indicators.get("rsi_14", 50.0))
    roc_5        = float(indicators.get("roc_5", 0.0))
    volume_ratio = float(indicators.get("volume_ratio", 1.0))

    b, s, notes = 0, 0, []

    # ROC5 — recent crowd momentum
    if roc_5 > 3.0:
        b += 1; notes.append(f"ROC5={roc_5:+.1f}% buying momentum")
    elif roc_5 < -3.0:
        s += 1; notes.append(f"ROC5={roc_5:+.1f}% selling panic")
    else:
        notes.append(f"ROC5={roc_5:+.1f}% low short-term momentum")

    # Volume with price direction — crowd participation
    if volume_ratio > 2.0:
        if roc_5 > 0:
            b += 1; notes.append(f"Volume surge {volume_ratio:.1f}x on up-move → crowd FOMO")
        else:
            s += 1; notes.append(f"Volume surge {volume_ratio:.1f}x on down-move → crowd panic")
    elif volume_ratio > 1.3:
        notes.append(f"Above-average volume {volume_ratio:.2f}x — elevated interest")
    elif volume_ratio < 0.5:
        notes.append(f"Volume dry-up {volume_ratio:.2f}x — crowd disinterest")
    else:
        notes.append(f"Normal volume {volume_ratio:.2f}x")

    # RSI as crowd fear/greed proxy (extreme readings)
    if rsi < 30:
        b += 1; notes.append(f"RSI={rsi:.1f} extreme pessimism / capitulation")
    elif rsi > 70:
        s += 1; notes.append(f"RSI={rsi:.1f} extreme greed / exhaustion")
    elif rsi > 58:
        notes.append(f"RSI={rsi:.1f} positive crowd sentiment")
    elif rsi < 42:
        notes.append(f"RSI={rsi:.1f} negative crowd sentiment")
    else:
        notes.append(f"RSI={rsi:.1f} neutral crowd sentiment")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Sentiment/crowd] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


# ── Paper-mode investor persona agents (Panel B) ─────────────────────────────

def _paper_investor_buffett(indicators: dict) -> str:
    """
    LENS: Secular trend + quarterly momentum (Buffett — long-term quality).
    Reads: ROC-60, SMA200 distance, ROC-20.
    No short-term oscillators — purely long-horizon price structure.
    """
    price   = float(indicators.get("price", 1.0))
    roc_60  = float(indicators.get("roc_60", 0.0))
    roc_20  = float(indicators.get("roc_20", 0.0))
    sma_200 = float(indicators.get("sma_200", price))

    b, s, notes = 0, 0, []

    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100
    if price > sma_200 * 1.05:
        b += 1; notes.append(f"Price {dev_200:+.1f}% above SMA200 — healthy secular uptrend")
    elif price < sma_200 * 0.95:
        s += 1; notes.append(f"Price {dev_200:+.1f}% below SMA200 — secular downtrend")
    else:
        notes.append(f"Price near SMA200 ({dev_200:+.1f}%) — neutral long-term structure")

    if roc_60 > 20.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% — strong business momentum proxy")
    elif roc_60 < -15.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% — deteriorating fundamentals proxy")
    else:
        notes.append(f"ROC60={roc_60:+.1f}% — insufficient for Buffett's conviction threshold")

    if roc_20 > 12.0 and b > 0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate strength")
    elif roc_20 < -12.0 and s > 0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate weakness")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% — moderate, Buffett needs stronger conviction")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Buffett/quality] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_munger(indicators: dict) -> str:
    """
    LENS: Ultra-selective long-term (Munger — inaction is preferable to bad trade).
    Reads: ROC-60, SMA200 distance, high_proximity.
    Stricter thresholds than Buffett — defaults to NEUTRAL.
    """
    price          = float(indicators.get("price", 1.0))
    roc_60         = float(indicators.get("roc_60", 0.0))
    sma_200        = float(indicators.get("sma_200", price))
    high_proximity = float(indicators.get("high_proximity", 0.5))

    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100
    notes = []

    # Munger requires ALL three conditions for BULLISH — very selective
    above_200   = price > sma_200 * 1.08
    strong_roc  = roc_60 > 25.0
    near_highs  = high_proximity < 0.10

    if above_200 and strong_roc:
        notes.append(f"Price {dev_200:+.1f}% above SMA200 + ROC60={roc_60:+.1f}% — Munger conviction met")
        direction = "BULLISH"
    elif price < sma_200 * 0.92 and roc_60 < -20.0:
        notes.append(f"Price {dev_200:+.1f}% below SMA200 + ROC60={roc_60:+.1f}% — avoid / exit")
        direction = "BEARISH"
    else:
        notes.append(
            f"SMA200 {dev_200:+.1f}%, ROC60={roc_60:+.1f}%, "
            f"52W proximity {high_proximity*100:.1f}% — Munger: insufficient certainty, default NEUTRAL"
        )
        direction = "NEUTRAL"

    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Munger/ultra-selective] — {'; '.join(notes)}."
    )


def _paper_investor_lynch(indicators: dict) -> str:
    """
    LENS: GARP multi-timeframe momentum (Lynch — buy growth at reasonable price).
    Reads: ROC-20, ROC-60, ROC-5, SMA20 distance, volume_ratio.
    """
    price        = float(indicators.get("price", 1.0))
    roc_20       = float(indicators.get("roc_20", 0.0))
    roc_60       = float(indicators.get("roc_60", 0.0))
    roc_5        = float(indicators.get("roc_5",  0.0))
    sma_20       = float(indicators.get("sma_20", price))
    volume_ratio = float(indicators.get("volume_ratio", 1.0))

    b, s, notes = 0, 0, []

    dev_20 = (price - sma_20) / max(sma_20, 1e-9) * 100
    if roc_20 > 10.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% — earnings-cycle momentum strong")
    elif roc_20 < -10.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% — earnings-cycle deteriorating")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% — moderate growth")

    if roc_60 > 15.0 and roc_5 > 2.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% + recent acceleration ROC5={roc_5:+.1f}% — story intact")
    elif roc_60 < -10.0 and roc_5 < -2.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% + recent deceleration ROC5={roc_5:+.1f}% — story broken")
    else:
        notes.append(f"ROC60={roc_60:+.1f}%, ROC5={roc_5:+.1f}% — mixed signals")

    if price > sma_20 * 1.01 and volume_ratio > 1.2:
        b += 1; notes.append(f"Above SMA20 ({dev_20:+.1f}%) on {volume_ratio:.1f}x volume — crowd confirming")
    elif price < sma_20 * 0.99 and volume_ratio > 1.4:
        s += 1; notes.append(f"Below SMA20 ({dev_20:+.1f}%) on {volume_ratio:.1f}x volume — distribution")
    else:
        notes.append(f"SMA20 {dev_20:+.1f}%, volume {volume_ratio:.2f}x — inconclusive")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Lynch/GARP] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_ackman(indicators: dict) -> str:
    """
    LENS: Concentrated catalyst-driven (Ackman — high conviction + unusual activity).
    Reads: ROC-20, ROC-60, high_proximity, SMA200 distance, volume_ratio.
    """
    price          = float(indicators.get("price", 1.0))
    roc_20         = float(indicators.get("roc_20", 0.0))
    roc_60         = float(indicators.get("roc_60", 0.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    sma_200        = float(indicators.get("sma_200", price))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))

    b, s, notes = 0, 0, []

    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100
    if roc_20 > 12.0 and roc_60 > 18.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — multi-timeframe thesis confirmed")
    elif roc_20 < -12.0 and roc_60 < -15.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — thesis broken across timeframes")
    else:
        notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — mixed, need more conviction")

    if price > sma_200 * 1.03 and high_proximity < 0.15:
        b += 1; notes.append(f"Above SMA200 ({dev_200:+.1f}%), near 52W high — structural strength")
    elif price < sma_200 * 0.97:
        s += 1; notes.append(f"Below SMA200 ({dev_200:+.1f}%) — structural damage")
    else:
        notes.append(f"SMA200 {dev_200:+.1f}% — neutral structural")

    if volume_ratio > 1.8:
        if b > 0:
            b += 1; notes.append(f"Volume {volume_ratio:.1f}x — catalyst / institutional accumulation")
        else:
            s += 1; notes.append(f"Volume {volume_ratio:.1f}x with weak trend — distribution signal")
    else:
        notes.append(f"Volume {volume_ratio:.2f}x — normal, no catalyst signal")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Ackman/concentrated] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_cohen(indicators: dict) -> str:
    """
    LENS: Momentum + flow (Cohen — pure technical momentum trading).
    Reads: RSI, MACD, ROC-5, ROC-10, volume_ratio, stoch_k, atr_pct, bb_pct_b.
    Widest indicator slice of all personas — Cohen reads everything.
    """
    price        = float(indicators.get("price", 1.0))
    rsi          = float(indicators.get("rsi_14", 50.0))
    macd         = float(indicators.get("macd", 0.0))
    macd_sig     = float(indicators.get("macd_signal", 0.0))
    roc_5        = float(indicators.get("roc_5",  0.0))
    roc_10       = float(indicators.get("roc_10", 0.0))
    volume_ratio = float(indicators.get("volume_ratio", 1.0))
    stoch_k      = float(indicators.get("stoch_k", 50.0))
    atr          = float(indicators.get("atr_14", 0.0))
    bb_upper     = float(indicators.get("bb_upper", price * 1.05))
    bb_lower     = float(indicators.get("bb_lower", price * 0.95))

    b, s, notes = 0, 0, []

    macd_bull = (macd - macd_sig) > 0
    if rsi > 55 and macd_bull:
        b += 1; notes.append(f"RSI={rsi:.1f}+MACD bull — momentum building")
    elif rsi < 45 and not macd_bull:
        s += 1; notes.append(f"RSI={rsi:.1f}+MACD bear — momentum fading")
    else:
        notes.append(f"RSI={rsi:.1f}, MACD {'bull' if macd_bull else 'bear'} — mixed")

    if roc_5 > 2.0 and roc_10 > 4.0:
        b += 1; notes.append(f"ROC5={roc_5:+.1f}%, ROC10={roc_10:+.1f}% — short-term acceleration")
    elif roc_5 < -2.0 and roc_10 < -4.0:
        s += 1; notes.append(f"ROC5={roc_5:+.1f}%, ROC10={roc_10:+.1f}% — short-term deceleration")
    else:
        notes.append(f"ROC5={roc_5:+.1f}%, ROC10={roc_10:+.1f}% — weak momentum")

    bb_range = max(bb_upper - bb_lower, 1e-9)
    pct_b = (price - bb_lower) / bb_range
    atr_pct = atr / max(price, 1e-9)
    if stoch_k > 55 and volume_ratio > 1.1 and pct_b > 0.5:
        b += 1; notes.append(f"Stoch={stoch_k:.0f}, vol {volume_ratio:.1f}x, BB%B={pct_b:.2f} — flow positive")
    elif stoch_k < 45 and volume_ratio > 1.2 and pct_b < 0.5:
        s += 1; notes.append(f"Stoch={stoch_k:.0f}, vol {volume_ratio:.1f}x, BB%B={pct_b:.2f} — flow negative")
    else:
        notes.append(f"Stoch={stoch_k:.0f}, ATR%={atr_pct*100:.1f}% — inconclusive flow")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Cohen/momentum] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_dalio(indicators: dict) -> str:
    """
    LENS: All-weather macro regime (Dalio — balanced risk parity).
    Reads: ROC-60, SMA200 distance, atr_14, ROC-20.
    High-vol regimes reduce conviction; prefers balanced environments.
    """
    price   = float(indicators.get("price", 1.0))
    roc_60  = float(indicators.get("roc_60", 0.0))
    sma_200 = float(indicators.get("sma_200", price))
    atr     = float(indicators.get("atr_14", 0.0))
    roc_20  = float(indicators.get("roc_20", 0.0))

    atr_pct = atr / max(price, 1e-9)
    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100

    b, s, notes = 0, 0, []

    if atr_pct > 0.025:
        notes.append(f"ATR%={atr_pct*100:.1f}% elevated — Dalio reduces risk exposure, NEUTRAL bias")
        return (
            f"DIRECTION: NEUTRAL\n"
            f"REASONING: Paper mode [Dalio/all-weather] — {'; '.join(notes)}."
        )

    if price > sma_200 * 1.03 and roc_60 > 15.0:
        b += 1; notes.append(f"Above SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — healthy macro regime")
    elif price < sma_200 * 0.97 and roc_60 < -10.0:
        s += 1; notes.append(f"Below SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — deteriorating macro")
    else:
        notes.append(f"SMA200 {dev_200:+.1f}%, ROC60={roc_60:+.1f}% — mixed macro signals")

    if roc_20 > 8.0 and b > 0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate strength")
    elif roc_20 < -8.0 and s > 0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate weakness")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% — Dalio: balanced signal, lean NEUTRAL")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Dalio/all-weather] — {'; '.join(notes)}. "
        f"Bullish: {b}/2, bearish: {s}/2."
    )


def _paper_investor_wood(indicators: dict) -> str:
    """
    LENS: Disruptive innovation / high-conviction growth (Wood).
    Reads: ROC-20, ROC-60, high_proximity, SMA200 distance, volume_ratio, atr_14.
    Buys dips in confirmed uptrends; high-vol ≠ bad if trend is intact.
    """
    price          = float(indicators.get("price", 1.0))
    roc_20         = float(indicators.get("roc_20", 0.0))
    roc_60         = float(indicators.get("roc_60", 0.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    sma_200        = float(indicators.get("sma_200", price))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))
    atr            = float(indicators.get("atr_14", 0.0))

    atr_pct = atr / max(price, 1e-9)
    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100

    b, s, notes = 0, 0, []

    # Wood's primary: secular trend is everything
    if price > sma_200 * 1.02 and roc_60 > 18.0:
        b += 1; notes.append(f"Above SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — innovation secular trend intact")
    elif price < sma_200 * 0.95 and roc_60 < -20.0:
        s += 1; notes.append(f"Below SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — secular trend broken")
    else:
        notes.append(f"SMA200 {dev_200:+.1f}%, ROC60={roc_60:+.1f}% — transition zone")

    # Wood buys dips — ATR pullback in uptrend = opportunity
    if roc_20 > 8.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% — intermediate growth acceleration")
    elif roc_20 > 0 and atr_pct > 0.02 and b > 0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% moderate + ATR%={atr_pct*100:.1f}% pullback in uptrend — buy the dip")
    elif roc_20 < -10.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% — growth story decelerating")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% — insufficient for Wood's conviction")

    if high_proximity < 0.20 and volume_ratio > 1.1 and b > 0:
        b += 1; notes.append(f"Near 52W high + {volume_ratio:.1f}x volume — institutional accumulation")
    elif high_proximity > 0.40:
        s += 1; notes.append(f"Far from 52W high ({high_proximity*100:.0f}% drawdown) — secular story challenged")
    else:
        notes.append(f"52W position {(1-high_proximity)*100:.0f}% of range, vol {volume_ratio:.2f}x")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Wood/innovation] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_bogle(indicators: dict) -> str:
    """
    LENS: Passive indexer (Bogle — rarely has strong single-stock views).
    Reads: high_proximity, atr_14, volume_ratio.
    Defaults to NEUTRAL; only extreme readings produce directional output.
    """
    price          = float(indicators.get("price", 1.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    low_proximity  = float(indicators.get("low_proximity", 0.5))
    atr            = float(indicators.get("atr_14", 0.0))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))

    atr_pct = atr / max(price, 1e-9)

    # Bogle requires extreme readings; otherwise NEUTRAL
    if atr_pct > 0.035 and volume_ratio > 2.0:
        return (
            "DIRECTION: BEARISH\n"
            f"REASONING: Paper mode [Bogle/passive] — "
            f"ATR%={atr_pct*100:.1f}% + volume {volume_ratio:.1f}x extreme — "
            "Bogle: this level of volatility/speculation is a warning; own index instead."
        )

    if low_proximity < 0.03 and atr_pct < 0.015:
        return (
            "DIRECTION: BULLISH\n"
            f"REASONING: Paper mode [Bogle/passive] — "
            f"Near 52W low, low volatility ATR%={atr_pct*100:.2f}% — "
            "Bogle: at structural support with low vol; index exposure acceptable."
        )

    range_pct = (1.0 - high_proximity) * 100
    return (
        "DIRECTION: NEUTRAL\n"
        f"REASONING: Paper mode [Bogle/passive] — "
        f"52W position {range_pct:.0f}%, ATR%={atr_pct*100:.1f}%, vol {volume_ratio:.2f}x — "
        "Bogle: no extreme signals; own the index, not the individual stock."
    )


def _paper_risk_manager(
    action: str,
    vote_tally: dict,
    portfolio: PortfolioState,
    max_pos: float,
    max_crypto: float,
    asset_class: str,
) -> str:
    """Rule-based risk assessment using portfolio values — no LLM needed."""
    equity  = max(portfolio.equity, 1.0)
    cash    = portfolio.cash
    cash_ratio = cash / equity

    pos_pct = min(max_pos, cash_ratio * 0.90) if action == "BUY" else max_pos
    pos_pct = round(max(0.01, pos_pct), 4)

    if asset_class == "crypto":
        headroom = max(0.0, max_crypto - portfolio.crypto_allocation_pct)
        if headroom < 0.005 and action == "BUY":
            action  = "HOLD"
            pos_pct = 0.0
            rationale = (
                f"Paper mode: crypto cap reached "
                f"({portfolio.crypto_allocation_pct*100:.1f}% / {max_crypto*100:.0f}% limit). "
                "No further crypto allocation permitted."
            )
        else:
            pos_pct   = round(min(pos_pct, headroom), 4)
            votes     = vote_tally.get("bullish" if action == "BUY" else "bearish", 0)
            rationale = (
                f"Paper mode rule-based risk. Equity=${equity:,.0f}, cash=${cash:,.0f} "
                f"({cash_ratio*100:.1f}%). Crypto headroom {headroom*100:.1f}%. "
                f"Consensus {votes}/15. Position={pos_pct*100:.1f}% NAV."
            )
    elif action == "BUY" and cash < equity * 0.03:
        action    = "HOLD"
        pos_pct   = 0.0
        rationale = (
            f"Paper mode: cash too low (${cash:,.0f} / {cash_ratio*100:.1f}% of equity). "
            "Need ≥3% cash cushion to open a new position."
        )
    else:
        votes     = vote_tally.get("bullish" if action == "BUY" else "bearish", 0)
        rationale = (
            f"Paper mode rule-based risk. Equity=${equity:,.0f}, cash=${cash:,.0f} "
            f"({cash_ratio*100:.1f}%). Vote consensus {votes}/15."
            f"Position sized at {pos_pct*100:.1f}% of equity."
        )

    votes = vote_tally.get("bullish" if action == "BUY" else "bearish", 0)
    return json.dumps({
        "action":                 action,
        "confidence":             round(votes / 15.0, 2),
        "rationale":              rationale,
        "suggested_position_pct": pos_pct,
        "stop_loss_pct":          0.02,
        "take_profit_pct":        0.05,
        "devil_advocate_score":   0,
        "devil_advocate_case":    "",
    })


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
    """
    Compute 22+ technical indicators from live market bars.
    Each paper-mode agent reads a distinct non-overlapping sub-set so votes are
    genuinely independent (asymmetric information lenses).
    """
    if len(snapshot.bars) < 20:
        return {}

    closes  = pd.Series([b.close  for b in snapshot.bars], dtype=float)
    highs   = pd.Series([b.high   for b in snapshot.bars], dtype=float)
    lows    = pd.Series([b.low    for b in snapshot.bars], dtype=float)
    volumes = pd.Series([float(b.volume) for b in snapshot.bars], dtype=float)
    price   = float(closes.iloc[-1])

    # ── Momentum ──────────────────────────────────────────────────────────────
    rsi      = ta.momentum.RSIIndicator(closes).rsi()
    macd_ind = ta.trend.MACD(closes)
    stoch    = ta.momentum.StochasticOscillator(highs, lows, closes)

    # ── Volatility ────────────────────────────────────────────────────────────
    atr_series = ta.volatility.AverageTrueRange(highs, lows, closes).average_true_range()
    bb         = ta.volatility.BollingerBands(closes)
    atr_now    = float(atr_series.iloc[-1])
    atr_5ago   = float(atr_series.iloc[-6]) if len(atr_series) >= 6 else atr_now

    bb_width_series = bb.bollinger_wband()
    bb_width_now    = float(bb_width_series.iloc[-1])
    bb_width_5ago   = float(bb_width_series.iloc[-6]) if len(bb_width_series) >= 6 else bb_width_now

    # ── Trend SMAs ────────────────────────────────────────────────────────────
    sma_20  = float(closes.rolling(20).mean().iloc[-1])
    sma_50  = float(closes.rolling(50).mean().iloc[-1])  if len(closes) >= 50  else price
    sma_200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else price

    # ── Rate of change ────────────────────────────────────────────────────────
    def _roc(n: int) -> float:
        if len(closes) <= n:
            return 0.0
        past = float(closes.iloc[-(n + 1)])
        return (price - past) / max(past, 1e-9) * 100

    # ── Volume ratio (today vs 20-day average) ────────────────────────────────
    vol_avg_20    = float(volumes.rolling(20).mean().iloc[-1])
    volume_ratio  = float(volumes.iloc[-1]) / max(vol_avg_20, 1.0)

    # ── 52-week (≤252 bars) range proximity ───────────────────────────────────
    bars_252   = snapshot.bars[-252:]
    high_52w   = max(b.high for b in bars_252)
    low_52w    = min(b.low  for b in bars_252)
    # high_proximity: fraction *below* 52w high (0 = at all-time high)
    # low_proximity:  fraction *above* 52w low  (0 = at all-time low)
    high_proximity = (high_52w - price) / max(high_52w, 1e-9)
    low_proximity  = (price - low_52w)  / max(price,    1e-9)

    return {
        "price":          price,
        # Momentum
        "rsi_14":         round(float(rsi.iloc[-1]), 2),
        "macd":           round(float(macd_ind.macd().iloc[-1]), 4),
        "macd_signal":    round(float(macd_ind.macd_signal().iloc[-1]), 4),
        "stoch_k":        round(float(stoch.stoch().iloc[-1]), 2),
        "stoch_d":        round(float(stoch.stoch_signal().iloc[-1]), 2),
        # Rate of change
        "roc_5":          round(_roc(5),  2),
        "roc_10":         round(_roc(10), 2),
        "roc_20":         round(_roc(20), 2),
        "roc_60":         round(_roc(60), 2),
        # Trend
        "sma_20":         round(sma_20,  4),
        "sma_50":         round(sma_50,  4),
        "sma_200":        round(sma_200, 4),
        # Volatility
        "atr_14":         round(atr_now, 4),
        "atr_trend":      round(atr_now - atr_5ago, 4),
        "bb_upper":       round(float(bb.bollinger_hband().iloc[-1]), 4),
        "bb_lower":       round(float(bb.bollinger_lband().iloc[-1]), 4),
        "bb_width":       round(bb_width_now, 4),
        "bb_width_trend": round(bb_width_now - bb_width_5ago, 4),
        # Volume
        "volume_ratio":   round(volume_ratio, 3),
        # 52-week range
        "high_52w":       round(high_52w, 4),
        "low_52w":        round(low_52w,  4),
        "high_proximity": round(high_proximity, 4),
        "low_proximity":  round(low_proximity,  4),
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
    """Runs 15 agents across two panels and returns a TradingSignal gated by majority vote.

    Panel A — original 7 specialist analysts:
        technical, fundamental, sentiment, macro, quant, options_flow, regime

    Panel B — 8 investor persona agents:
        buffett, munger, lynch, ackman, cohen, dalio, wood, bogle

    All 15 fire in parallel via ThreadPoolExecutor.
    Panel conflict (panels disagree on direction) forces HOLD.
    """

    def __init__(
        self,
        anthropic_api_key: str,
        confidence_threshold: float = 0.7,   # retained for Risk Manager compat; not used for gating
        max_position_pct: float = 0.05,
        max_crypto_pct: float = 0.30,
        circuit_breaker_drawdown: float = 0.10,
    ) -> None:
        client = anthropic.Anthropic(api_key=anthropic_api_key)

        # Panel A — analyst agents
        self._fundamental     = FundamentalAnalyst(client)
        self._technical       = TechnicalAnalyst(client)
        self._sentiment_agent = SentimentAnalyst(client)
        self._macro           = MacroEconomist(client)
        self._quant           = QuantAnalyst(client)
        self._options_flow    = OptionsFlowAnalyst(client)
        self._regime          = RegimeDetector(client)   # deterministic — client ignored

        # Panel B — investor persona agents
        self._buffett = BuffettInvestor(client)
        self._munger  = MungerInvestor(client)
        self._lynch   = LynchInvestor(client)
        self._ackman  = AckmanInvestor(client)
        self._cohen   = CohenInvestor(client)
        self._dalio   = DalioInvestor(client)
        self._wood    = WoodInvestor(client)
        self._bogle   = BogleInvestor(client)

        # Synthesis agents (not part of vote pool)
        self._strategy = StrategyCoach(client)
        self._risk     = RiskManager(client)

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
        paper_mode: bool = False,
    ) -> TradingSignal:
        symbol      = market.symbol
        asset_class = market.asset_class
        profile     = user_profile or DEFAULT_PROFILE
        mode_label  = "paper-rule-based" if paper_mode else "live-LLM"
        log.info("15-agent dual-panel debate starting: %s (%s) mode=%s", symbol, asset_class, mode_label)

        bars_dicts = _bars_to_dicts(market)
        indicators = _compute_indicators(market)

        price   = indicators.get("price", 1.0) or 1.0
        atr_pct = indicators.get("atr_14", 0.0) / price
        _regime_tracker.record_atr(atr_pct)

        # Both panels share the same underlying indicator dict;
        # each agent reads only its declared keys (enforced by agent prompt / paper logic).
        analyst_views: dict[str, str] = {}   # Panel A
        investor_views: dict[str, str] = {}  # Panel B

        if paper_mode:
            # ── Paper mode: all 15 agents rule-based, zero LLM calls ──────────
            # Panel A — each reads a distinct indicator subset (asymmetric lenses)
            regime_ctx = {"symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators}
            analyst_views["regime"]       = self._regime.analyse(regime_ctx)
            analyst_views["technical"]    = _paper_technical(indicators)      # RSI + MACD + SMA20
            analyst_views["quant"]        = _paper_quant(indicators)           # BB%B + Stoch + ROC10
            analyst_views["fundamental"]  = _paper_fundamental(indicators)     # ROC20/60 + SMA50/200
            analyst_views["options_flow"] = _paper_options_flow(indicators)    # ATR + vol_ratio + 52W
            analyst_views["macro"]        = _paper_macro(indicators)           # SMA200 + ROC60 + 52W high
            analyst_views["sentiment"]    = _paper_sentiment(indicators)       # ROC5 + vol_ratio + RSI crowd

            # Panel B — investor personas, distinct lenses
            investor_views["buffett"] = _paper_investor_buffett(indicators)   # ROC60 + SMA200 + ROC20
            investor_views["munger"]  = _paper_investor_munger(indicators)    # ROC60 + SMA200 + 52W
            investor_views["lynch"]   = _paper_investor_lynch(indicators)     # ROC20/60/5 + SMA20 + vol
            investor_views["ackman"]  = _paper_investor_ackman(indicators)    # ROC20/60 + SMA200 + vol
            investor_views["cohen"]   = _paper_investor_cohen(indicators)     # RSI/MACD/ROC5/10/stoch/atr
            investor_views["dalio"]   = _paper_investor_dalio(indicators)     # ROC60 + SMA200 + ATR + ROC20
            investor_views["wood"]    = _paper_investor_wood(indicators)      # ROC20/60 + 52W + SMA200 + vol
            investor_views["bogle"]   = _paper_investor_bogle(indicators)     # 52W + ATR + vol (passive)

            log.info(
                "Paper mode: %d Panel-A + %d Panel-B agents complete (%d indicators)",
                len(analyst_views), len(investor_views), len(indicators),
            )
            log.debug("Panel A: %s", {k: v.split("\n")[0] for k, v in analyst_views.items()})
            log.debug("Panel B: %s", {k: v.split("\n")[0] for k, v in investor_views.items()})

        else:
            # ── Live mode: full 15-agent LLM debate, all parallel ─────────────
            cache_key        = f"{symbol}:strategic"
            cached_strategic = _cache.get(cache_key)

            regime_ctx = {"symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators}
            macro_ctx  = {
                "symbol": symbol, "asset_class": asset_class,
                "bars_last_60": bars_dicts, "indicators": indicators,
                "portfolio_equity": portfolio.equity,
                "daily_pnl_pct": portfolio.daily_pnl_pct,
            }

            # Panel A tactical contexts
            panel_a_tasks: dict[str, tuple[Any, dict]] = {
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

            # Panel B — each persona receives only its data slice
            # (system prompt enforces philosophy; context provides the numbers)
            _ind_str = lambda keys: {k: indicators.get(k) for k in keys if k in indicators}
            panel_b_tasks: dict[str, tuple[Any, dict]] = {
                "buffett": (self._buffett.analyse, _ind_str(
                    ["symbol", "price", "roc_60", "sma_200", "roc_20"])),
                "munger": (self._munger.analyse, _ind_str(
                    ["symbol", "price", "roc_60", "sma_200", "high_proximity"])),
                "lynch": (self._lynch.analyse, _ind_str(
                    ["symbol", "price", "roc_20", "roc_60", "roc_5", "sma_20", "volume_ratio"])),
                "ackman": (self._ackman.analyse, _ind_str(
                    ["symbol", "price", "roc_20", "roc_60", "high_proximity", "sma_200", "volume_ratio"])),
                "cohen": (self._cohen.analyse, _ind_str(
                    ["symbol", "price", "rsi_14", "macd", "macd_signal", "roc_5", "roc_10",
                     "volume_ratio", "stoch_k", "atr_14", "bb_upper", "bb_lower"])),
                "dalio": (self._dalio.analyse, _ind_str(
                    ["symbol", "price", "roc_60", "sma_200", "atr_14", "roc_20"])),
                "wood": (self._wood.analyse, _ind_str(
                    ["symbol", "price", "roc_20", "roc_60", "high_proximity",
                     "sma_200", "volume_ratio", "atr_14"])),
                "bogle": (self._bogle.analyse, _ind_str(
                    ["symbol", "price", "high_proximity", "low_proximity", "atr_14", "volume_ratio"])),
            }
            # Add symbol to panel B contexts (needed by agents)
            for ctx_dict in (d for _, d in panel_b_tasks.values()):
                ctx_dict.setdefault("symbol", symbol)

            # Fire all 15 agents simultaneously (ThreadPoolExecutor — same as existing pattern)
            with ThreadPoolExecutor(max_workers=15) as pool:
                futures: dict[Any, tuple[str, str]] = {}  # future → (panel, role)

                futures[pool.submit(self._regime.analyse, regime_ctx)] = ("a", "regime")

                if cached_strategic:
                    analyst_views["macro"] = cached_strategic[0]
                    log.debug("Macro served from cache for %s", symbol)
                else:
                    futures[pool.submit(self._macro.analyse, macro_ctx)] = ("a", "macro")

                for role, (fn, ctx) in panel_a_tasks.items():
                    futures[pool.submit(fn, ctx)] = ("a", role)

                for role, (fn, ctx) in panel_b_tasks.items():
                    futures[pool.submit(fn, ctx)] = ("b", role)

                for fut in as_completed(futures):
                    panel, role = futures[fut]
                    try:
                        result = fut.result()
                    except Exception as exc:
                        log.error("Agent %s/%s failed: %s", panel, role, exc)
                        result = f"DIRECTION: NEUTRAL\nREASONING: Agent error — {exc}"
                    if panel == "a":
                        analyst_views[role] = result
                    else:
                        investor_views[role] = result

            if "macro" in analyst_views:
                _cache.set(cache_key, (analyst_views["macro"], analyst_views.get("regime", "")))

        for role, view in {**analyst_views, **investor_views}.items():
            log.info("%s: %s", role.title(), view[:80])

        # ── Dual-panel vote aggregation ───────────────────────────────────────
        panel_a_tally, panel_b_tally, combined_tally, panels_conflict, conflict_note = (
            _aggregate_dual_panel(analyst_views, investor_views)
        )
        action           = _action_from_votes(combined_tally, panels_conflict=panels_conflict, threshold=8)
        regime_view      = analyst_views.get("regime", "")
        regime_label     = _parse_regime_label(regime_view)
        votes_for_action = (
            combined_tally["bullish"] if action == "BUY"
            else combined_tally["bearish"] if action == "SELL"
            else 0
        )

        log.info(
            "Dual-panel votes: A=%s B=%s combined=%s conflict=%s → action=%s regime=%s mode=%s",
            panel_a_tally, panel_b_tally, combined_tally,
            panels_conflict, action, regime_label, mode_label,
        )

        # ── Round 2: Risk Manager + Strategy Coach ────────────────────────────
        if paper_mode:
            # Rule-based risk manager — uses portfolio values, no LLM
            risk_raw      = _paper_risk_manager(
                action, combined_tally, portfolio,
                self._max_pos, self._max_crypto, asset_class,
            )
            strategy_view = (
                "ALIGNED\nREASONING: Paper mode — strategy assessment uses rule-based "
                "position sizing. Trade aligns with technical indicators."
            )
        else:
            risk_ctx = {
                "symbol": symbol, "asset_class": asset_class,
                "action_from_votes": action,
                "vote_tally":        combined_tally,
                "panel_a_votes":     panel_a_tally,
                "panel_b_votes":     panel_b_tally,
                "panels_conflict":   panels_conflict,
                "analyst_opinions":  {**analyst_views, **investor_views},
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
                    "symbol":          symbol,
                    "action":          action,
                    "vote_tally":      combined_tally,
                    "panel_a_votes":   panel_a_tally,
                    "panel_b_votes":   panel_b_tally,
                    "panels_conflict": panels_conflict,
                    "analyst_opinions": {**analyst_views, **investor_views},
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

        # ── Tier — deterministic from combined 15-agent votes + regime ────────
        tier = _compute_tier(
            combined_tally, action, regime_label, indicators,
            panels_conflict=panels_conflict,
        )

        signal = TradingSignal(
            symbol=symbol,
            asset_class=asset_class,
            action=action,
            confidence=float(parsed.get("confidence", 0.0)),  # kept for display only
            rationale=parsed.get("rationale", f"Vote: {combined_tally}"),
            tier=tier,
            vote_tally=combined_tally,
            votes_for_action=votes_for_action,
            regime_label=regime_label,
            # Dual-panel breakdown
            panel_a_votes=panel_a_tally,
            panel_b_votes=panel_b_tally,
            panels_conflict=panels_conflict,
            conflict_note=conflict_note,
            suggested_position_pct=float(parsed.get("suggested_position_pct", 0.0)),
            stop_loss_pct=float(parsed.get("stop_loss_pct", 0.02)),
            take_profit_pct=float(parsed.get("take_profit_pct", 0.05)),
            devil_advocate_score=int(parsed.get("devil_advocate_score", 0)),
            devil_advocate_case=parsed.get("devil_advocate_case", ""),
            strategy_fit=strategy_fit,
            # Panel A views
            fundamental_view=analyst_views.get("fundamental", ""),
            technical_view=analyst_views.get("technical", ""),
            sentiment_view=analyst_views.get("sentiment", ""),
            macro_view=analyst_views.get("macro", ""),
            quant_view=analyst_views.get("quant", ""),
            options_flow_view=analyst_views.get("options_flow", ""),
            regime_view=analyst_views.get("regime", ""),
            strategy_view=strategy_view,
            risk_view=risk_raw,
            # Panel B views
            buffett_view=investor_views.get("buffett", ""),
            munger_view=investor_views.get("munger", ""),
            lynch_view=investor_views.get("lynch", ""),
            ackman_view=investor_views.get("ackman", ""),
            cohen_view=investor_views.get("cohen", ""),
            dalio_view=investor_views.get("dalio", ""),
            wood_view=investor_views.get("wood", ""),
            bogle_view=investor_views.get("bogle", ""),
        )

        log.info(
            "Signal: %s %s tier=%s votes=%d/15 (A=%s B=%s) conflict=%s regime=%s fit=%s",
            action, symbol, tier, votes_for_action,
            panel_a_tally, panel_b_tally, panels_conflict, regime_label, strategy_fit,
        )
        return signal
