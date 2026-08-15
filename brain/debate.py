"""Brain orchestration — 9-agent debate with deterministic vote-count tier classification."""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal

import ta
import pandas as pd

from data.market_data import MarketSnapshot
from data.sentiment import SentimentBundle
from data.onchain import OnChainSnapshot
from data.portfolio import PortfolioState
from data.macro_data import fetch_macro_context
from brain.signal import TradingSignal
from watchlist import HOT_MIN_VOTES, WARM_MIN_VOTES, AGENT_COUNT
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
    SorosInvestor, DruckenmillerInvestor, SimonsInvestor, TempletonInvestor,
)
from brain.agents.breakout import BreakoutAnalyst
from brain.agents.trend_strength import TrendStrengthAnalyst
from brain.agents.sector_rotation import SectorRotationAnalyst
from brain.agents.earnings_event import EarningsEventAnalyst
from brain.agents.momentum_scorer import MomentumScorerAnalyst
from brain.agents.supply_demand import SupplyDemandAnalyst
from brain.agents.volume_analyst import VolumeAnalyst
from brain.agents.risk_reward import RiskRewardAnalyst

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


# ── Real-data helpers for Phase 2 agents ────────────────────────────────────

# Options flow cache: symbol → (fetch_time, {put_call_ratio, iv_estimate})
_OPTIONS_CACHE: dict[str, tuple[float, dict]] = {}
_OPTIONS_CACHE_TTL = 1800  # 30-minute TTL — options data changes during trading day

def _fetch_options_data(symbol: str) -> dict:
    """Fetch put/call ratio and ATM IV from yfinance options chain.
    Returns empty dict on failure — agent treats missing data as unavailable."""
    cached = _OPTIONS_CACHE.get(symbol)
    if cached and (time.monotonic() - cached[0]) < _OPTIONS_CACHE_TTL:
        return cached[1]
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        dates = ticker.options
        if not dates:
            _OPTIONS_CACHE[symbol] = (time.monotonic(), {})
            return {}
        chain = ticker.option_chain(dates[0])
        calls = chain.calls
        puts  = chain.puts
        call_vol = max(float(calls["volume"].fillna(0).sum()), 1.0)
        put_vol  = float(puts["volume"].fillna(0).sum())
        pc_ratio = round(put_vol / call_vol, 3)

        # ATM IV: average impliedVolatility of calls within 5% of current price
        info = ticker.info
        price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0)
        atm_iv = 0.0
        if price > 0:
            atm_calls = calls[(calls["strike"] - price).abs() < price * 0.05]
            if not atm_calls.empty:
                atm_iv = round(float(atm_calls["impliedVolatility"].mean()), 4)

        result = {
            "put_call_ratio":   pc_ratio,
            "atm_iv_est":       atm_iv,
            "options_available": True,
        }
        _OPTIONS_CACHE[symbol] = (time.monotonic(), result)
        log.debug("Options %s: pc=%.3f atm_iv=%.3f", symbol, pc_ratio, atm_iv)
        return result
    except Exception as exc:
        log.debug("Options fetch failed for %s: %s", symbol, exc)
        _OPTIONS_CACHE[symbol] = (time.monotonic(), {})
        return {}


# Sector ETF momentum cache: (fetch_time, {ETF → 20d ROC%})
_SECTOR_CACHE: tuple[float, dict] | None = None
_SECTOR_CACHE_TTL = 3600  # 1 hour — sector leadership shifts slowly

_SECTOR_ETFS = ["XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"]

def _fetch_sector_momentum() -> dict:
    """Return 20-day ROC% for all 11 SPDR sector ETFs plus the ranked top-3 and bottom-3."""
    global _SECTOR_CACHE
    if _SECTOR_CACHE and (time.monotonic() - _SECTOR_CACHE[0]) < _SECTOR_CACHE_TTL:
        return _SECTOR_CACHE[1]
    try:
        import yfinance as yf
        raw = yf.download(_SECTOR_ETFS, period="35d", progress=False, auto_adjust=True)
        close = raw["Close"] if "Close" in raw else raw
        rocs: dict[str, float] = {}
        for etf in _SECTOR_ETFS:
            if etf in close.columns:
                series = close[etf].dropna()
                n = min(21, len(series))
                if n >= 2:
                    rocs[etf] = round((float(series.iloc[-1]) / float(series.iloc[-n]) - 1) * 100, 2)
        sorted_etfs = sorted(rocs.items(), key=lambda x: x[1], reverse=True)
        result = {
            "sector_roc_20d": rocs,
            "leading_sectors":  [e for e, _ in sorted_etfs[:3]],
            "lagging_sectors":  [e for e, _ in sorted_etfs[-3:]],
            "sector_data_available": len(rocs) >= 6,
        }
        _SECTOR_CACHE = (time.monotonic(), result)
        log.debug("Sector momentum fetched: %d ETFs", len(rocs))
        return result
    except Exception as exc:
        log.debug("Sector momentum fetch failed: %s", exc)
        return {}


# ── LLM output helpers ───────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """Remove markdown code fences that some LLMs add despite instructions not to.
    Handles ```json ... ``` and ``` ... ``` variants."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop opening fence line (```json or ```)
    lines = lines[1:]
    # Drop closing fence line if present
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _clean_rationale(text: str) -> str:
    """Strip markdown formatting from a rationale string and return one clean sentence.

    DeepSeek V3 ignores the 'no markdown' instruction ~30% of the time, producing
    **bold**, ### headers, and numbered lists inside the rationale field.  This
    sanitiser is applied both when JSON parsing succeeds and in the non-JSON fallback.
    """
    if not text or not text.strip():
        return "Signal generated."
    t = text.strip()
    # Strip bold / italic markers  (**text** → text, *text* → text)
    t = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", t)
    # Strip markdown headers (## Key Reasons: → Key Reasons:)
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.MULTILINE)
    # Strip bullet / numbered-list markers at line starts
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*\d+[.)]\s+", "", t, flags=re.MULTILINE)
    # Collapse newlines and extra spaces into a single line
    t = re.sub(r"[\r\n]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # Drop common LLM preamble that adds no information
    t = re.sub(
        r"^(given (the|this|my) analysis[,.]?\s*"
        r"|the recommendation is \w+(\s+for \w+)?[,.]\s*"
        r"|here.?s (the|my) (trade |trading )?(decision|recommendation|signal)[^.]*[,.]\s*"
        r"|based on (the|this|my|our) analysis[,.]?\s*)",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    # Extract only the first sentence
    m = re.search(r"^(.+?[.!?])(?:\s+[A-Z]|$)", t)
    first = m.group(1).strip() if m else t
    # Hard cap at 180 chars
    if len(first) > 180:
        first = first[:177] + "..."
    return first or "Signal generated."


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


_PANEL_A_VOTERS = frozenset({
    # Original 7 specialists
    "fundamental", "technical", "sentiment", "macro", "quant", "options_flow", "regime",
    # Wave 2 specialists (19-agent pool)
    "breakout", "trend_strength", "sector_rotation", "earnings_event",
    # Wave 3 specialists (27-agent pool)
    "momentum_scorer", "supply_demand", "volume_analyst", "risk_reward",
})
_PANEL_B_VOTERS = frozenset({
    "buffett", "munger", "lynch", "ackman", "cohen", "dalio", "wood", "bogle",
    # Wave 3 investor personas (27-agent pool)
    "soros", "druckenmiller", "simons", "templeton",
})

# ── Panel B preference weights per asset class ────────────────────────────────
# Panel A analysts are always 1.0 — they are technical/quant domain-agnostic.
# For Panel B, each persona's vote is scaled by how relevant their real-world
# track record and philosophy is to the asset class being traded.
# Weight > 1.0 → domain expert, amplified.  Weight < 1.0 → outside domain,
# reduced.  Weight = 0.0 → excluded entirely (Bogle on crypto).
# ETFs are received as asset_class="stock" by the backend, so only two keys:
_PERSONA_WEIGHTS: dict[str, dict[str, float]] = {
    #                            stock   crypto
    "buffett":       {"stock": 1.5, "crypto": 0.1},  # legendary stock investor; "rat poison"
    "munger":        {"stock": 1.5, "crypto": 0.1},  # "rat poison squared"
    "lynch":         {"stock": 1.5, "crypto": 0.5},  # GARP stocks; crypto not his domain
    "ackman":        {"stock": 1.2, "crypto": 0.3},  # activist stocks; minimal crypto conviction
    "cohen":         {"stock": 1.0, "crypto": 1.2},  # pure momentum — works on any liquid asset
    "dalio":         {"stock": 1.2, "crypto": 0.8},  # macro all-weather; small crypto as hedge
    "wood":          {"stock": 1.0, "crypto": 1.8},  # strongest crypto/innovation conviction
    "bogle":         {"stock": 1.0, "crypto": 0.0},  # passive index only; zero crypto
    "soros":         {"stock": 1.0, "crypto": 1.5},  # reflexivity fits crypto boom/bust cycles
    "druckenmiller": {"stock": 1.0, "crypto": 1.5},  # concentrated macro; publicly owns BTC
    "simons":        {"stock": 1.0, "crypto": 1.3},  # pure quant; statistical patterns ideal for crypto
    "templeton":     {"stock": 1.2, "crypto": 0.5},  # global contrarian value; stocks his domain
}
# Stock total Panel B weight: 14.1   Crypto total Panel B weight: 9.6
# Total system weight (15 Panel A + Panel B): stock=29.1  crypto=24.6

# ── yfinance TTL cache (30 min) — prevents rate-limiting with 40+ symbols ────
_YF_CACHE: dict[str, tuple[float, dict]] = {}
_YF_CACHE_TTL = 1800  # seconds


def _count_votes(views: dict[str, str], voter_set: frozenset[str]) -> dict[str, int]:
    """Count BULLISH / BEARISH / NEUTRAL votes for Panel A (always weight = 1)."""
    tally: dict[str, int] = {"bullish": 0, "bearish": 0, "neutral": 0}
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


def _count_votes_weighted(
    views: dict[str, str],
    voter_set: frozenset[str],
    asset_class: str,
) -> dict[str, float]:
    """
    Weighted vote tally for Panel B personas.

    Each persona's vote is multiplied by its asset-class preference weight from
    _PERSONA_WEIGHTS.  A weight of 0.0 (Bogle on crypto) excludes the agent
    entirely.  Panel A always uses _count_votes() with weight = 1.0.
    """
    tally: dict[str, float] = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    for key, view in views.items():
        if key not in voter_set:
            continue
        weight = _PERSONA_WEIGHTS.get(key, {}).get(asset_class, 1.0)
        if weight == 0.0:
            continue  # excluded from this asset class entirely
        direction = _parse_direction(view)
        if direction == "BULLISH":
            tally["bullish"] += weight
        elif direction == "BEARISH":
            tally["bearish"] += weight
        else:
            tally["neutral"] += weight
    return tally


def _total_b_weight(asset_class: str) -> float:
    """Sum of all Panel B preference weights for the given asset class."""
    return round(sum(
        _PERSONA_WEIGHTS.get(p, {}).get(asset_class, 1.0)
        for p in _PANEL_B_VOTERS
    ), 1)


def _total_system_weight(asset_class: str) -> float:
    """Total weighted vote pool: Panel A (always 15 × 1.0) + weighted Panel B."""
    return round(15.0 + _total_b_weight(asset_class), 1)


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
    asset_class: str = "stock",
) -> tuple[dict, dict, dict, bool, str, bool]:
    """
    Aggregate votes from both panels with asset-class-weighted Panel B.

    Panel A: all 15 analysts weighted = 1.0 (domain-agnostic technical specialists).
    Panel B: each of the 12 investor personas weighted by _PERSONA_WEIGHTS[name][asset_class].
             e.g. Buffett crypto=0.1, Wood crypto=1.8, Bogle crypto=0.0 (excluded).

    b_abstaining threshold: proportional to total Panel B weight so the bar stays
    at the same 83.3% (10/12) ratio regardless of asset class.

    Returns:
        a_votes, b_votes, combined_votes, panels_conflict, conflict_note, b_abstaining
    """
    a_votes = _count_votes(panel_a, _PANEL_A_VOTERS)                             # int dict
    b_votes = _count_votes_weighted(panel_b, _PANEL_B_VOTERS, asset_class)       # float dict

    combined = {
        "bullish": round(a_votes["bullish"] + b_votes["bullish"], 1),
        "bearish": round(a_votes["bearish"] + b_votes["bearish"], 1),
        "neutral": round(a_votes["neutral"] + b_votes["neutral"], 1),
    }

    a_dom = _dominant_direction(a_votes)
    b_dom = _dominant_direction(b_votes)

    # Hard conflict: both panels directional but in opposing directions
    panels_conflict = (
        a_dom != b_dom
        and a_dom != "NEUTRAL"
        and b_dom != "NEUTRAL"
    )

    # Soft conflict: analysts directional but investors near-unanimously abstain.
    # Threshold = 83.3% of total Panel B weight (same ratio as the original 10/12).
    # On crypto, stock-specialist neutrals (Buffett 0.1, Munger 0.1, Bogle 0.0)
    # barely contribute, so this only fires when the crypto-relevant personas
    # (Wood, Soros, Druckenmiller, Simons, Cohen) are themselves neutral.
    b_total_w  = _total_b_weight(asset_class)
    b_abstain_threshold = (10.0 / 12.0) * b_total_w
    b_abstaining = b_votes["neutral"] >= b_abstain_threshold and a_dom != "NEUTRAL"

    if panels_conflict:
        conflict_note = f"Panel conflict: analysts={a_dom}, investors={b_dom} — standing aside"
    elif b_abstaining:
        conflict_note = (
            f"Investor panel near-unanimous abstention "
            f"(weighted neutral={b_votes['neutral']:.1f}/{b_total_w:.1f}) "
            f"while analysts={a_dom} — downgraded to COLD"
        )
    else:
        conflict_note = ""

    return a_votes, b_votes, combined, panels_conflict, conflict_note, b_abstaining


def _action_from_votes(
    tally: dict[str, int],
    panels_conflict: bool = False,
    threshold: int = WARM_MIN_VOTES,
) -> Literal["BUY", "SELL", "HOLD"]:
    """
    Dual-panel majority-vote arbiter.  27 total agents (15 Panel A + 12 Panel B).
    Default threshold = WARM_MIN_VOTES (11, ≈41% of pool — same ratio as old 8/19).
    Panel conflict only forces HOLD when BOTH panels are strongly directional
    and opposing (≥4 votes each).  Weak/neutral panel conflict is advisory only.
    """
    a_bullish = tally.get("bullish", 0)
    a_bearish = tally.get("bearish", 0)
    # Only block on conflict when it's a strong disagreement
    strong_conflict = panels_conflict and a_bullish >= 4 and a_bearish >= 4
    if strong_conflict:
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
    b_abstaining: bool = False,
) -> Literal["HOT", "WARM", "COLD"]:
    """
    Deterministic tier from combined 27-agent vote count + regime.

    HOT  = 17+ of 27 aligned AND no strong conflict  (≈63% — consistent with prior ratio)
    WARM = 11–16 of 27 aligned AND no strong conflict
    COLD = < 11 aligned  OR  strong panel conflict  OR  near-unanimous investor abstention  OR  HOLD

    RANGING and HIGH_VOLATILITY no longer force COLD — they prevent HOT (cap at WARM).
    ATR% threshold raised from 4% → 7% since 4% is normal for tech/crypto.
    """
    aligned  = tally["bullish"] if action == "BUY" else tally["bearish"] if action == "SELL" else 0
    strong_conflict = panels_conflict and tally.get("bullish", 0) >= 4 and tally.get("bearish", 0) >= 4
    # Hard blockers: not enough votes, action is HOLD, strong bi-directional conflict, or unanimous abstention
    hard_blocked = action == "HOLD" or strong_conflict or b_abstaining or aligned < WARM_MIN_VOTES

    if hard_blocked:
        return "COLD"

    # Regime / vol conditions cap at WARM but don't force COLD
    high_vol = (
        "HIGH_VOLATILITY" in regime_label
        or (indicators.get("atr_14", 0) / max(indicators.get("price", 1), 1)) > 0.07
    )
    soft_cap = high_vol or "RANGING" in regime_label

    if aligned >= HOT_MIN_VOTES and not soft_cap:
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
    if roc_10 < -4.0:
        b += 1; notes.append(f"ROC10={roc_10:+.1f}% pullback → reversion candidate")
    elif roc_10 > 4.0:
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
    if roc_20 > 5.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% intermediate uptrend")
    elif roc_20 < -5.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% intermediate downtrend")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% moderate")

    # ROC60 — quarterly momentum
    if roc_60 > 8.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% quarterly uptrend")
    elif roc_60 < -8.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% quarterly downtrend")
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
    if price > sma_200 * 1.015:
        b += 1; notes.append(f"Price {dev_200:+.1f}% above SMA200 — bull market structure")
    elif price < sma_200 * 0.985:
        s += 1; notes.append(f"Price {dev_200:+.1f}% below SMA200 — bear market structure")
    else:
        notes.append(f"Price at SMA200 crossover zone ({dev_200:+.1f}%)")

    # ROC60 — macro quarterly momentum
    if roc_60 > 7.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% positive macro momentum")
    elif roc_60 < -7.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% negative macro momentum")
    else:
        notes.append(f"ROC60={roc_60:+.1f}% subdued macro momentum")

    # 52W high proximity — secular trend health
    if high_proximity < 0.08:
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
    if roc_5 > 1.5:
        b += 1; notes.append(f"ROC5={roc_5:+.1f}% buying momentum")
    elif roc_5 < -1.5:
        s += 1; notes.append(f"ROC5={roc_5:+.1f}% selling panic")
    else:
        notes.append(f"ROC5={roc_5:+.1f}% low short-term momentum")

    # Volume with price direction — crowd participation
    if volume_ratio > 1.5:
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
    if price > sma_200 * 1.03:
        b += 1; notes.append(f"Price {dev_200:+.1f}% above SMA200 — healthy secular uptrend")
    elif price < sma_200 * 0.97:
        s += 1; notes.append(f"Price {dev_200:+.1f}% below SMA200 — secular downtrend")
    else:
        notes.append(f"Price near SMA200 ({dev_200:+.1f}%) — neutral long-term structure")

    if roc_60 > 10.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% — strong business momentum proxy")
    elif roc_60 < -10.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% — deteriorating fundamentals proxy")
    else:
        notes.append(f"ROC60={roc_60:+.1f}% — moderate momentum")

    if roc_20 > 6.0 and b > 0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate strength")
    elif roc_20 < -6.0 and s > 0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate weakness")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% — moderate")

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

    # Munger requires strong conditions for BULLISH — selective but not impossible
    above_200   = price > sma_200 * 1.06
    strong_roc  = roc_60 > 15.0
    near_highs  = high_proximity < 0.10

    if above_200 and strong_roc:
        notes.append(f"Price {dev_200:+.1f}% above SMA200 + ROC60={roc_60:+.1f}% — Munger conviction met")
        direction = "BULLISH"
    elif price < sma_200 * 0.94 and roc_60 < -15.0:
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
    if roc_20 > 5.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% — earnings-cycle momentum positive")
    elif roc_20 < -5.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}% — earnings-cycle deteriorating")
    else:
        notes.append(f"ROC20={roc_20:+.1f}% — moderate growth")

    if roc_60 > 8.0 and roc_5 > 1.0:
        b += 1; notes.append(f"ROC60={roc_60:+.1f}% + recent momentum ROC5={roc_5:+.1f}% — story intact")
    elif roc_60 < -8.0 and roc_5 < -1.0:
        s += 1; notes.append(f"ROC60={roc_60:+.1f}% + recent weakness ROC5={roc_5:+.1f}% — story broken")
    else:
        notes.append(f"ROC60={roc_60:+.1f}%, ROC5={roc_5:+.1f}% — mixed signals")

    if price > sma_20 * 1.005 and volume_ratio > 1.1:
        b += 1; notes.append(f"Above SMA20 ({dev_20:+.1f}%) on {volume_ratio:.1f}x volume — crowd confirming")
    elif price < sma_20 * 0.995 and volume_ratio > 1.3:
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
    if roc_20 > 6.0 and roc_60 > 10.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — multi-timeframe thesis confirmed")
    elif roc_20 < -6.0 and roc_60 < -10.0:
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

    if atr_pct > 0.035:
        notes.append(f"ATR%={atr_pct*100:.1f}% elevated — Dalio reduces risk exposure, NEUTRAL bias")
        return (
            f"DIRECTION: NEUTRAL\n"
            f"REASONING: Paper mode [Dalio/all-weather] — {'; '.join(notes)}."
        )

    if price > sma_200 * 1.015 and roc_60 > 8.0:
        b += 1; notes.append(f"Above SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — healthy macro regime")
    elif price < sma_200 * 0.985 and roc_60 < -8.0:
        s += 1; notes.append(f"Below SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — deteriorating macro")
    else:
        notes.append(f"SMA200 {dev_200:+.1f}%, ROC60={roc_60:+.1f}% — mixed macro signals")

    if roc_20 > 4.0 and b > 0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% confirms intermediate strength")
    elif roc_20 < -4.0 and s > 0:
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
    if price > sma_200 * 1.01 and roc_60 > 10.0:
        b += 1; notes.append(f"Above SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — innovation secular trend intact")
    elif price < sma_200 * 0.97 and roc_60 < -12.0:
        s += 1; notes.append(f"Below SMA200 ({dev_200:+.1f}%) + ROC60={roc_60:+.1f}% — secular trend broken")
    else:
        notes.append(f"SMA200 {dev_200:+.1f}%, ROC60={roc_60:+.1f}% — transition zone")

    # Wood buys dips — ATR pullback in uptrend = opportunity
    if roc_20 > 5.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}% — intermediate growth acceleration")
    elif roc_20 > 0 and atr_pct > 0.015 and b > 0:
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


def _paper_breakout(indicators: dict) -> str:
    """
    LENS: Breakout / breakdown detection with volume confirmation.
    Reads: high_proximity, low_proximity, volume_ratio, atr_14, roc_5.
    """
    price          = float(indicators.get("price", 1.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    low_proximity  = float(indicators.get("low_proximity", 0.5))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))
    atr            = float(indicators.get("atr_14", 0.0))
    atr_trend      = float(indicators.get("atr_trend", 0.0))
    roc_5          = float(indicators.get("roc_5", 0.0))
    atr_pct        = atr / max(price, 1e-9)

    b, s, notes = 0, 0, []

    # Near 52W high with volume — breakout setup
    if high_proximity < 0.02:
        b += 1; notes.append(f"Price {high_proximity*100:.1f}% from 52W high — breakout zone")
    elif high_proximity < 0.05 and volume_ratio > 1.2:
        b += 1; notes.append(f"Approaching 52W high ({high_proximity*100:.1f}%) + vol {volume_ratio:.1f}x")
    elif low_proximity < 0.05:
        s += 1; notes.append(f"Near 52W low ({low_proximity*100:.1f}%) — breakdown risk")
    else:
        notes.append(f"52W position mid-range (h={high_proximity*100:.1f}%, l={low_proximity*100:.1f}%)")

    # Volume + ATR expansion (institutional breakout)
    if volume_ratio > 1.5 and atr_trend > 0:
        if roc_5 > 0:
            b += 1; notes.append(f"Vol {volume_ratio:.1f}x + expanding ATR on up-move — breakout buying")
        else:
            s += 1; notes.append(f"Vol {volume_ratio:.1f}x + expanding ATR on down-move — breakdown selling")
    elif volume_ratio > 1.3:
        notes.append(f"Vol {volume_ratio:.1f}x above normal")
    else:
        notes.append(f"Vol {volume_ratio:.2f}x — no breakout volume signal")

    # Immediate momentum confirmation
    if roc_5 > 2.0 and b > 0:
        b += 1; notes.append(f"ROC5={roc_5:+.1f}% confirms breakout momentum")
    elif roc_5 < -2.0 and s > 0:
        s += 1; notes.append(f"ROC5={roc_5:+.1f}% confirms breakdown momentum")
    else:
        notes.append(f"ROC5={roc_5:+.1f}%")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Breakout] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_trend_strength(indicators: dict) -> str:
    """
    LENS: Multi-timeframe trend alignment (all timeframes must agree).
    Reads: rsi_14, macd, macd_signal, sma_20, sma_50, sma_200, roc_20, roc_60.
    """
    price   = float(indicators.get("price", 1.0))
    rsi     = float(indicators.get("rsi_14", 50.0))
    macd    = float(indicators.get("macd", 0.0))
    macd_s  = float(indicators.get("macd_signal", 0.0))
    sma_20  = float(indicators.get("sma_20",  price))
    sma_50  = float(indicators.get("sma_50",  price))
    sma_200 = float(indicators.get("sma_200", price))
    roc_20  = float(indicators.get("roc_20", 0.0))
    roc_60  = float(indicators.get("roc_60", 0.0))

    # Bullish SMA stack: price > SMA20 > SMA50 > SMA200
    bull_stack = price > sma_20 and sma_20 > sma_50 and sma_50 > sma_200
    bear_stack = price < sma_20 and sma_20 < sma_50 and sma_50 < sma_200

    b, s, notes = 0, 0, []

    if bull_stack:
        b += 1; notes.append("Full bullish SMA stack (price>SMA20>SMA50>SMA200)")
    elif bear_stack:
        s += 1; notes.append("Full bearish SMA stack (price<SMA20<SMA50<SMA200)")
    else:
        notes.append("Mixed SMA alignment — trend not confirmed")

    macd_bull = (macd - macd_s) > 0
    if rsi > 52 and macd_bull:
        b += 1; notes.append(f"RSI={rsi:.1f} + MACD bullish — momentum aligned")
    elif rsi < 48 and not macd_bull:
        s += 1; notes.append(f"RSI={rsi:.1f} + MACD bearish — momentum aligned")
    else:
        notes.append(f"RSI={rsi:.1f}, MACD {'bull' if macd_bull else 'bear'} — mixed momentum")

    if roc_20 > 4.0 and roc_60 > 6.0 and b > 0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — all timeframes bullish")
    elif roc_20 < -4.0 and roc_60 < -6.0 and s > 0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — all timeframes bearish")
    else:
        notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — timeframe conflict")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [TrendStrength] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_sector_rotation(indicators: dict) -> str:
    """
    LENS: Sector / capital rotation momentum.
    Reads: roc_20, roc_60, volume_ratio, sma_50, high_proximity.
    """
    price          = float(indicators.get("price", 1.0))
    roc_20         = float(indicators.get("roc_20", 0.0))
    roc_60         = float(indicators.get("roc_60", 0.0))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))
    sma_50         = float(indicators.get("sma_50", price))
    high_proximity = float(indicators.get("high_proximity", 0.5))

    b, s, notes = 0, 0, []
    dev_50 = (price - sma_50) / max(sma_50, 1e-9) * 100

    # Multi-timeframe relative strength
    if roc_20 > 5.0 and roc_60 > 8.0:
        b += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — strong relative momentum in")
    elif roc_20 < -5.0 and roc_60 < -8.0:
        s += 1; notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — capital rotating out")
    else:
        notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — rotation signal unclear")

    # Institutional flow proxy
    if volume_ratio > 1.2 and roc_20 > 0:
        b += 1; notes.append(f"Vol {volume_ratio:.1f}x on uptrend — institutional inflow")
    elif volume_ratio > 1.3 and roc_20 < 0:
        s += 1; notes.append(f"Vol {volume_ratio:.1f}x on downtrend — institutional outflow")
    else:
        notes.append(f"Vol {volume_ratio:.2f}x — normal flow")

    # Trend + structural position
    if price > sma_50 * 1.01 and high_proximity < 0.15:
        b += 1; notes.append(f"Above SMA50 ({dev_50:+.1f}%), near 52W high — sector leadership confirmed")
    elif price < sma_50 * 0.99 and high_proximity > 0.25:
        s += 1; notes.append(f"Below SMA50 ({dev_50:+.1f}%), far from 52W high — sector laggard")
    else:
        notes.append(f"SMA50 {dev_50:+.1f}%, 52W {high_proximity*100:.1f}% below peak — neutral rotation")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [SectorRotation] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_earnings_event(indicators: dict) -> str:
    """
    LENS: Volatility regime + event-driven positioning.
    Reads: atr_14, atr_trend, bb_width, bb_width_trend, roc_5, roc_10, volume_ratio.
    """
    price         = float(indicators.get("price", 1.0))
    atr           = float(indicators.get("atr_14", 0.0))
    atr_trend     = float(indicators.get("atr_trend", 0.0))
    bb_width      = float(indicators.get("bb_width", 0.02))
    bb_width_t    = float(indicators.get("bb_width_trend", 0.0))
    roc_5         = float(indicators.get("roc_5", 0.0))
    roc_10        = float(indicators.get("roc_10", 0.0))
    volume_ratio  = float(indicators.get("volume_ratio", 1.0))
    atr_pct       = atr / max(price, 1e-9)

    b, s, notes = 0, 0, []

    # Volatility squeeze — coiled spring before catalyst
    if bb_width < 0.015 and bb_width_t < 0:
        b += 1; notes.append(f"BB squeeze (width={bb_width:.3f}, contracting) — pre-event compression")
    elif atr_pct > 0.03 and atr_trend > 0 and roc_5 < -1.5:
        s += 1; notes.append(f"ATR%={atr_pct*100:.1f}% expanding + negative ROC5 — post-event distribution")
    else:
        notes.append(f"ATR%={atr_pct*100:.1f}%, BB-width={bb_width:.3f} — normal volatility regime")

    # Volume surge context
    if volume_ratio > 1.8 and atr_trend > 0:
        if roc_5 > 1.0:
            b += 1; notes.append(f"Vol {volume_ratio:.1f}x + expanding vol + positive ROC — bullish catalyst")
        else:
            s += 1; notes.append(f"Vol {volume_ratio:.1f}x + expanding vol + negative ROC — bearish catalyst")
    elif volume_ratio > 1.3:
        notes.append(f"Vol {volume_ratio:.1f}x elevated — event awareness building")
    else:
        notes.append(f"Vol {volume_ratio:.2f}x — quiet, no event signal")

    # Short-term reaction momentum
    if roc_5 > 2.5 and roc_10 > 4.0:
        b += 1; notes.append(f"ROC5={roc_5:+.1f}%, ROC10={roc_10:+.1f}% — strong post-event momentum")
    elif roc_5 < -2.5 and roc_10 < -4.0:
        s += 1; notes.append(f"ROC5={roc_5:+.1f}%, ROC10={roc_10:+.1f}% — post-event selling")
    else:
        notes.append(f"ROC5={roc_5:+.1f}%, ROC10={roc_10:+.1f}% — sub-threshold momentum")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [EarningsEvent] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_momentum_scorer(indicators: dict) -> str:
    """
    LENS: Cross-timeframe momentum scoring (roc_5/10/20/60 + stochastic cross).
    Distinct from technical (RSI/MACD/SMA20) and trend_strength (SMA stack alignment).
    """
    roc_5  = float(indicators.get("roc_5",  0.0))
    roc_10 = float(indicators.get("roc_10", 0.0))
    roc_20 = float(indicators.get("roc_20", 0.0))
    roc_60 = float(indicators.get("roc_60", 0.0))
    stoch_k = float(indicators.get("stoch_k", 50.0))
    stoch_d = float(indicators.get("stoch_d", 50.0))

    score = 0
    notes = []

    # Score each ROC window independently
    for name, val in [("ROC5", roc_5), ("ROC10", roc_10), ("ROC20", roc_20), ("ROC60", roc_60)]:
        if val > 0:
            score += 1; notes.append(f"{name}={val:+.1f}%▲")
        else:
            score -= 1; notes.append(f"{name}={val:+.1f}%▼")

    # Stochastic K/D cross as confirmation
    if stoch_k > stoch_d:
        score += 1; notes.append(f"Stoch K>{stoch_d:.0f} (bull cross)")
    else:
        score -= 1; notes.append(f"Stoch K<{stoch_d:.0f} (bear cross)")

    direction = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [MomentumScorer] — score={score:+d}/±5 — {', '.join(notes)}."
    )


def _paper_supply_demand(indicators: dict) -> str:
    """
    LENS: Supply/demand zone detection via Bollinger bands + 52W levels.
    Distinct from options_flow (ATR/vol) and quant (BB mean-rev / stoch).
    """
    price          = float(indicators.get("price", 1.0))
    bb_upper       = float(indicators.get("bb_upper", price * 1.05))
    bb_lower       = float(indicators.get("bb_lower", price * 0.95))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    low_proximity  = float(indicators.get("low_proximity", 0.5))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))

    bb_range = max(bb_upper - bb_lower, 1e-9)
    pct_b    = (price - bb_lower) / bb_range   # 0=at lower, 1=at upper

    b, s, notes = 0, 0, []

    # Demand zone: near BB lower AND near 52W low
    if pct_b <= 0.15 and low_proximity < 0.10:
        b += 2; notes.append(f"Demand zone: pct_B={pct_b:.2f} + near 52W low ({low_proximity*100:.1f}%)")
    elif pct_b <= 0.25:
        b += 1; notes.append(f"Near BB lower (pct_B={pct_b:.2f})")
    elif pct_b >= 0.75:
        s += 1; notes.append(f"Near BB upper (pct_B={pct_b:.2f})")

    # Supply zone: near BB upper AND near 52W high
    if pct_b >= 0.85 and high_proximity < 0.10:
        s += 2; notes.append(f"Supply zone: pct_B={pct_b:.2f} + near 52W high ({high_proximity*100:.1f}%)")
    elif high_proximity < 0.05:
        s += 1; notes.append(f"Near 52W high ({high_proximity*100:.1f}%) — supply overhead")
    elif low_proximity < 0.05:
        b += 1; notes.append(f"Near 52W low ({low_proximity*100:.1f}%) — demand support")
    else:
        notes.append(f"52W: high={high_proximity*100:.0f}% low={low_proximity*100:.0f}% — mid-zone")

    # Volume confirmation at zones
    if volume_ratio > 1.3:
        if b > s:
            b += 1; notes.append(f"Vol {volume_ratio:.1f}x confirms demand zone activity")
        elif s > b:
            s += 1; notes.append(f"Vol {volume_ratio:.1f}x confirms supply zone activity")

    direction = "BULLISH" if b > s + 1 else "BEARISH" if s > b + 1 else (
        "BULLISH" if b > s else "BEARISH" if s > b else "NEUTRAL"
    )
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [SupplyDemand] — {'; '.join(notes)}. "
        f"Demand score: {b}, supply score: {s}."
    )


def _paper_volume_analyst(indicators: dict) -> str:
    """
    LENS: Volume-price relationship (accumulation vs distribution).
    Distinct from options_flow (ATR/52W) and breakout (52W high/low focus).
    """
    volume_ratio = float(indicators.get("volume_ratio", 1.0))
    roc_5        = float(indicators.get("roc_5",  0.0))
    roc_10       = float(indicators.get("roc_10", 0.0))
    atr_trend    = float(indicators.get("atr_trend", 0.0))

    b, s, notes = 0, 0, []

    # Primary signal: volume direction vs price direction
    if volume_ratio > 1.3:
        if roc_5 > 0 and roc_10 > 0:
            b += 2; notes.append(f"Vol {volume_ratio:.1f}x + ROC5={roc_5:+.1f}% + ROC10={roc_10:+.1f}% — accumulation")
        elif roc_5 < 0 and roc_10 < 0:
            s += 2; notes.append(f"Vol {volume_ratio:.1f}x + ROC5={roc_5:+.1f}% + ROC10={roc_10:+.1f}% — distribution")
        elif roc_5 > 0 or roc_10 > 0:
            b += 1; notes.append(f"Vol {volume_ratio:.1f}x on mixed/slight up-move — mild accumulation")
        else:
            s += 1; notes.append(f"Vol {volume_ratio:.1f}x on mixed/slight down-move — mild distribution")
    elif volume_ratio < 0.7:
        notes.append(f"Vol dry-up {volume_ratio:.2f}x — low conviction, no accumulation/distribution")
    else:
        notes.append(f"Vol {volume_ratio:.2f}x — normal flow")

    # ATR trend as confirmation
    if atr_trend > 0 and roc_5 < -1.0:
        s += 1; notes.append("ATR expanding on down-move — panic selling / distribution pressure")
    elif atr_trend < 0 and roc_5 > 0:
        b += 1; notes.append("ATR contracting on up-move — controlled accumulation / stealth buying")
    else:
        notes.append(f"ATR trend {'expanding' if atr_trend > 0 else 'contracting'} — neutral vol context")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [VolumeAnalyst] — {'; '.join(notes)}. "
        f"Accumulation: {b}, distribution: {s}."
    )


def _paper_risk_reward(indicators: dict) -> str:
    """
    LENS: Trade setup quality / risk-reward ratio assessment.
    Reads: atr_14, bb_width, bb_upper, bb_lower, high_proximity, low_proximity, stoch_k.
    Distinct: assesses WHETHER to trade, not direction (complementary asymmetric lens).
    """
    price          = float(indicators.get("price", 1.0))
    atr            = float(indicators.get("atr_14", 0.0))
    bb_width       = float(indicators.get("bb_width", 0.02))
    bb_upper       = float(indicators.get("bb_upper", price * 1.02))
    bb_lower       = float(indicators.get("bb_lower", price * 0.98))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    low_proximity  = float(indicators.get("low_proximity", 0.5))
    stoch_k        = float(indicators.get("stoch_k", 50.0))
    atr_pct        = atr / max(price, 1e-9)

    bb_range = max(bb_upper - bb_lower, 1e-9)
    pct_b    = (price - bb_lower) / bb_range

    b, s, notes = 0, 0, []

    # ATR regime — low ATR = tight stops, good R/R for buys; high ATR = wide stops, poor R/R
    if atr_pct < 0.015:
        b += 1; notes.append(f"ATR%={atr_pct*100:.2f}% — compressed vol, tight stops possible, good R/R for BUY")
    elif atr_pct > 0.035:
        s += 1; notes.append(f"ATR%={atr_pct*100:.1f}% — wide vol, choppy, poor R/R for BUY")
    else:
        notes.append(f"ATR%={atr_pct*100:.2f}% — moderate vol regime")

    # BB width — squeeze before expansion (low width = upcoming move, bias long at support)
    if bb_width < 0.015 and pct_b < 0.4:
        b += 1; notes.append(f"BB squeeze (w={bb_width:.3f}) near lower band — coiled, buy setup")
    elif bb_width > 0.04 and pct_b > 0.8:
        s += 1; notes.append(f"BB wide (w={bb_width:.3f}) near upper — overextended, sell setup")
    else:
        notes.append(f"BB width={bb_width:.3f}, pct_B={pct_b:.2f} — neutral setup")

    # Stoch extremes — entry timing
    if stoch_k < 25 and low_proximity < 0.12:
        b += 1; notes.append(f"Stoch K={stoch_k:.0f} oversold + near support — buy entry quality HIGH")
    elif stoch_k > 75 and high_proximity < 0.12:
        s += 1; notes.append(f"Stoch K={stoch_k:.0f} overbought + near resistance — sell entry quality HIGH")
    else:
        notes.append(f"Stoch K={stoch_k:.0f} — entry timing neutral")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [RiskReward] — {'; '.join(notes)}. "
        f"Buy setup score: {b}/3, sell setup score: {s}/3."
    )


def _paper_investor_soros(indicators: dict) -> str:
    """
    LENS: Macro reflexivity — rides self-reinforcing trends until clearly broken.
    Reads: roc_60, sma_200, roc_20, atr_14, high_proximity.
    """
    price          = float(indicators.get("price", 1.0))
    roc_60         = float(indicators.get("roc_60", 0.0))
    sma_200        = float(indicators.get("sma_200", price))
    roc_20         = float(indicators.get("roc_20", 0.0))
    atr            = float(indicators.get("atr_14", 0.0))
    high_proximity = float(indicators.get("high_proximity", 0.5))
    atr_pct        = atr / max(price, 1e-9)

    b, s, notes = 0, 0, []
    dev_200 = (price - sma_200) / max(sma_200, 1e-9) * 100

    # Reflexivity: strong uptrend above SMA200 + near highs = self-reinforcing
    if price > sma_200 * 1.02 and roc_60 > 8.0:
        b += 1; notes.append(f"Reflexive uptrend: +{dev_200:.1f}% above SMA200, ROC60={roc_60:+.1f}%")
    elif price < sma_200 * 0.98 and roc_60 < -8.0:
        s += 1; notes.append(f"Reflexive downtrend: {dev_200:.1f}% below SMA200, ROC60={roc_60:+.1f}%")
    else:
        notes.append(f"SMA200 {dev_200:+.1f}%, ROC60={roc_60:+.1f}% — no reflexive trend")

    if roc_20 > 5.0 and b > 0:
        b += 1; notes.append(f"Intermediate momentum ROC20={roc_20:+.1f}% confirms uptrend")
    elif roc_20 < -5.0 and s > 0:
        s += 1; notes.append(f"Intermediate momentum ROC20={roc_20:+.1f}% confirms downtrend")
    else:
        notes.append(f"ROC20={roc_20:+.1f}%")

    if high_proximity < 0.08 and b > 0:
        b += 1; notes.append("Near 52W high — trend is running, Soros rides it")
    elif high_proximity > 0.30 and s > 0:
        s += 1; notes.append(f"Far from 52W high ({high_proximity*100:.0f}% off) — downtrend accelerating")
    else:
        notes.append(f"52W proximity {high_proximity*100:.0f}% below peak")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Soros/reflexivity] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_druckenmiller(indicators: dict) -> str:
    """
    LENS: Concentrated momentum + institutional confirmation.
    Reads: roc_20, roc_60, roc_5, sma_50, volume_ratio.
    """
    price        = float(indicators.get("price", 1.0))
    roc_20       = float(indicators.get("roc_20", 0.0))
    roc_60       = float(indicators.get("roc_60", 0.0))
    roc_5        = float(indicators.get("roc_5",  0.0))
    sma_50       = float(indicators.get("sma_50", price))
    volume_ratio = float(indicators.get("volume_ratio", 1.0))
    dev_50       = (price - sma_50) / max(sma_50, 1e-9) * 100

    b, s, notes = 0, 0, []

    # Strong multi-timeframe momentum
    if roc_20 > 7.0 and roc_60 > 12.0:
        b += 1; notes.append(f"Strong momentum: ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}%")
    elif roc_20 < -7.0 and roc_60 < -12.0:
        s += 1; notes.append(f"Strong negative momentum: ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}%")
    else:
        notes.append(f"ROC20={roc_20:+.1f}%, ROC60={roc_60:+.1f}% — not strong enough for Druckenmiller")

    # Institutional volume confirmation
    if volume_ratio > 1.3 and b > 0:
        b += 1; notes.append(f"Vol {volume_ratio:.1f}x — institutional participation confirms momentum")
    elif volume_ratio > 1.3 and s > 0:
        s += 1; notes.append(f"Vol {volume_ratio:.1f}x — institutions selling into weakness")
    else:
        notes.append(f"Vol {volume_ratio:.2f}x — insufficient institutional conviction")

    # Trend structure (SMA50)
    if price > sma_50 * 1.01 and b > 0:
        b += 1; notes.append(f"Price {dev_50:+.1f}% above SMA50 — trend structure intact")
    elif price < sma_50 * 0.99 and s > 0:
        s += 1; notes.append(f"Price {dev_50:+.1f}% below SMA50 — breakdown confirmed")
    else:
        notes.append(f"SMA50 {dev_50:+.1f}%")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Druckenmiller/concentrated] — {'; '.join(notes)}. "
        f"Bullish: {b}/3, bearish: {s}/3."
    )


def _paper_investor_simons(indicators: dict) -> str:
    """
    LENS: Quantitative statistical patterns (pure mechanical signals, no macro/fundamental).
    Reads: stoch_k, stoch_d, roc_10, bb_upper, bb_lower, volume_ratio, price.
    """
    price        = float(indicators.get("price", 1.0))
    stoch_k      = float(indicators.get("stoch_k", 50.0))
    stoch_d      = float(indicators.get("stoch_d", 50.0))
    roc_10       = float(indicators.get("roc_10", 0.0))
    bb_upper     = float(indicators.get("bb_upper", price * 1.02))
    bb_lower     = float(indicators.get("bb_lower", price * 0.98))
    volume_ratio = float(indicators.get("volume_ratio", 1.0))

    bb_range = max(bb_upper - bb_lower, 1e-9)
    pct_b    = (price - bb_lower) / bb_range

    b, s, notes = 0, 0, []

    # Stochastic K/D cross from extremes
    if stoch_k < 25 and stoch_k > stoch_d:
        b += 2; notes.append(f"Stoch K={stoch_k:.1f} (<25) crossing above D={stoch_d:.1f} — oversold recovery signal")
    elif stoch_k > 75 and stoch_k < stoch_d:
        s += 2; notes.append(f"Stoch K={stoch_k:.1f} (>75) crossing below D={stoch_d:.1f} — overbought reversal signal")
    elif stoch_k < 30:
        b += 1; notes.append(f"Stoch K={stoch_k:.1f} oversold zone")
    elif stoch_k > 70:
        s += 1; notes.append(f"Stoch K={stoch_k:.1f} overbought zone")
    else:
        notes.append(f"Stoch K={stoch_k:.1f} — mid-range, no statistical edge")

    # BB band extension (statistical overextension)
    if pct_b < 0.05:
        b += 1; notes.append(f"Price at BB lower extreme (pct_B={pct_b:.2f}) — statistical mean-reversion BUY")
    elif pct_b > 0.95:
        s += 1; notes.append(f"Price at BB upper extreme (pct_B={pct_b:.2f}) — statistical mean-reversion SELL")
    else:
        notes.append(f"BB pct_B={pct_b:.2f} — within normal range")

    # ROC10 early confirmation of turn
    if roc_10 > 0 and b > 0:
        notes.append(f"ROC10={roc_10:+.1f}% early upturn confirms signal")
    elif roc_10 < 0 and s > 0:
        notes.append(f"ROC10={roc_10:+.1f}% early downturn confirms signal")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Simons/quant] — {'; '.join(notes)}. "
        f"Bullish stat edge: {b}, bearish stat edge: {s}."
    )


def _paper_investor_templeton(indicators: dict) -> str:
    """
    LENS: Contrarian — buy maximum pessimism, sell maximum optimism.
    Reads: high_proximity, low_proximity, roc_60, volume_ratio.
    """
    high_proximity = float(indicators.get("high_proximity", 0.5))
    low_proximity  = float(indicators.get("low_proximity", 0.5))
    roc_60         = float(indicators.get("roc_60", 0.0))
    volume_ratio   = float(indicators.get("volume_ratio", 1.0))

    b, s, notes = 0, 0, []

    # Maximum pessimism: near 52W low + negative ROC + low volume (no one cares)
    if low_proximity < 0.08 and roc_60 < -10.0:
        b += 2; notes.append(
            f"Max pessimism: near 52W low ({low_proximity*100:.1f}% above), ROC60={roc_60:+.1f}% — Templeton BUY"
        )
    elif low_proximity < 0.15 and roc_60 < -5.0:
        b += 1; notes.append(f"Moderate pessimism: near 52W low ({low_proximity*100:.1f}%), ROC60={roc_60:+.1f}%")
    else:
        notes.append(f"52W low proximity {low_proximity*100:.1f}% — not at pessimism extreme")

    # Maximum optimism/euphoria: near 52W high + positive ROC + high volume (everyone's buying)
    if high_proximity < 0.05 and roc_60 > 10.0 and volume_ratio > 1.4:
        s += 2; notes.append(
            f"Max euphoria: near 52W high ({high_proximity*100:.1f}%), ROC60={roc_60:+.1f}%, vol {volume_ratio:.1f}x — Templeton SELL"
        )
    elif high_proximity < 0.10 and roc_60 > 5.0:
        s += 1; notes.append(f"Moderate optimism: near 52W high ({high_proximity*100:.1f}%), ROC60={roc_60:+.1f}%")
    else:
        notes.append(f"52W high proximity {high_proximity*100:.1f}% — not at euphoria extreme")

    # Low volume + pessimism = Templeton's ideal (ignored by market)
    if volume_ratio < 0.8 and b > 0:
        b += 1; notes.append(f"Vol {volume_ratio:.2f}x dry — market ignoring it (Templeton ideal)")
    elif volume_ratio > 1.3 and s > 0:
        s += 1; notes.append(f"Vol {volume_ratio:.1f}x high at highs — crowd chasing (Templeton warning)")
    else:
        notes.append(f"Vol {volume_ratio:.2f}x — normal participation")

    direction = "BULLISH" if b >= 2 else "BEARISH" if s >= 2 else "NEUTRAL"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode [Templeton/contrarian] — {'; '.join(notes)}. "
        f"Pessimism score: {b}/3, euphoria score: {s}/3."
    )


def _paper_risk_manager(
    action: str,
    vote_tally: dict,
    portfolio: PortfolioState,
    max_pos: float,
    max_crypto: float,
    asset_class: str,
    stop_loss_pct: float = 0.02,
    take_profit_pct: float = 0.05,
) -> str:
    """Rule-based risk assessment using portfolio values — no LLM needed."""
    original_action = action   # capture before any branch may mutate it to HOLD
    equity  = max(portfolio.equity, 1.0)
    cash    = portfolio.cash
    cash_ratio = cash / equity

    pos_pct = min(max_pos, cash_ratio * 0.90) if action == "BUY" else max_pos
    pos_pct = round(max(0.01, pos_pct), 4)

    total_w = _total_system_weight(asset_class)

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
                f"Weighted consensus {votes:.1f}/{total_w:.1f}. Position={pos_pct*100:.1f}% NAV."
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
            f"({cash_ratio*100:.1f}%). Weighted consensus {votes:.1f}/{total_w:.1f}. "
            f"Position sized at {pos_pct*100:.1f}% of equity."
        )

    vote_key = "bullish" if original_action == "BUY" else "bearish"
    votes = vote_tally.get(vote_key, 0)
    return json.dumps({
        "action":                 action,
        "confidence":             round(float(votes) / total_w, 2),
        "rationale":              rationale,
        "suggested_position_pct": pos_pct,
        "stop_loss_pct":          stop_loss_pct,
        "take_profit_pct":        take_profit_pct,
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
    if len(snapshot.bars) < 35:
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
        if len(closes) < n + 1:
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

    All 27 fire in parallel via ThreadPoolExecutor.
    Panel conflict (panels disagree on direction) forces HOLD.
    """

    def __init__(
        self,
        openrouter_api_key: str,
        confidence_threshold: float = 0.7,   # retained for Risk Manager compat; not used for gating
        max_position_pct: float = 0.05,
        max_crypto_pct: float = 0.30,
        circuit_breaker_drawdown: float = 0.10,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.05,
    ) -> None:
        from openai import OpenAI  # lazy: paper mode works without the package
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_api_key,
        )

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

        # Panel A — Wave 2 specialist agents
        self._breakout        = BreakoutAnalyst(client)
        self._trend_strength  = TrendStrengthAnalyst(client)
        self._sector_rotation = SectorRotationAnalyst(client)
        self._earnings_event  = EarningsEventAnalyst(client)

        # Panel A — Wave 3 specialist agents (27-agent pool)
        self._momentum_scorer = MomentumScorerAnalyst(client)
        self._supply_demand   = SupplyDemandAnalyst(client)
        self._volume_analyst  = VolumeAnalyst(client)
        self._risk_reward     = RiskRewardAnalyst(client)

        # Panel B — Wave 3 investor personas (27-agent pool)
        self._soros           = SorosInvestor(client)
        self._druckenmiller   = DruckenmillerInvestor(client)
        self._simons          = SimonsInvestor(client)
        self._templeton       = TempletonInvestor(client)

        # Synthesis agents (not part of vote pool)
        self._strategy = StrategyCoach(client)
        self._risk     = RiskManager(client)

        self._threshold      = confidence_threshold
        self._max_pos        = max_position_pct
        self._max_crypto     = max_crypto_pct
        self._cb_drawdown    = circuit_breaker_drawdown
        self._stop_loss_pct  = stop_loss_pct
        self._take_profit_pct = take_profit_pct

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
        log.info("27-agent dual-panel debate starting: %s (%s) mode=%s", symbol, asset_class, mode_label)

        bars_dicts = _bars_to_dicts(market)
        indicators = _compute_indicators(market)

        # Guard: refuse to run debate on empty/insufficient data — produces garbage signals
        if not indicators:
            log.warning(
                "Insufficient bar data for %s (%d bars, need 35+) — returning HOLD/COLD",
                symbol, len(market.bars),
            )
            return TradingSignal(
                symbol=symbol, asset_class=asset_class,
                action="HOLD", confidence=0.0,
                rationale=f"Insufficient data: {len(market.bars)} bars (35+ required for indicator computation)",
                tier="COLD",
            )

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
            analyst_views["regime"]          = self._regime.analyse(regime_ctx)
            analyst_views["technical"]       = _paper_technical(indicators)       # RSI + MACD + SMA20
            analyst_views["quant"]           = _paper_quant(indicators)            # BB%B + Stoch + ROC10
            analyst_views["fundamental"]     = _paper_fundamental(indicators)      # ROC20/60 + SMA50/200
            analyst_views["options_flow"]    = _paper_options_flow(indicators)     # ATR + vol_ratio + 52W
            analyst_views["macro"]           = _paper_macro(indicators)            # SMA200 + ROC60 + 52W high
            analyst_views["sentiment"]       = _paper_sentiment(indicators)        # ROC5 + vol_ratio + RSI crowd
            # Panel A — Wave 2 specialists
            analyst_views["breakout"]        = _paper_breakout(indicators)         # 52W high/low + vol + ATR + ROC5
            analyst_views["trend_strength"]  = _paper_trend_strength(indicators)   # SMA stack + RSI/MACD + ROC20/60
            analyst_views["sector_rotation"] = _paper_sector_rotation(indicators)  # ROC20/60 + vol + SMA50 + 52W
            analyst_views["earnings_event"]  = _paper_earnings_event(indicators)   # ATR + BB-width + ROC5/10 + vol
            # Panel A — Wave 3 specialists (27-agent pool)
            analyst_views["momentum_scorer"] = _paper_momentum_scorer(indicators)  # roc_5/10/20/60 + stoch cross
            analyst_views["supply_demand"]   = _paper_supply_demand(indicators)    # BB bands + 52W levels + vol
            analyst_views["volume_analyst"]  = _paper_volume_analyst(indicators)   # vol-price relationship
            analyst_views["risk_reward"]     = _paper_risk_reward(indicators)      # ATR + BB-width + stoch setup

            # Panel B — original 8 investor personas
            investor_views["buffett"] = _paper_investor_buffett(indicators)   # ROC60 + SMA200 + ROC20
            investor_views["munger"]  = _paper_investor_munger(indicators)    # ROC60 + SMA200 + 52W
            investor_views["lynch"]   = _paper_investor_lynch(indicators)     # ROC20/60/5 + SMA20 + vol
            investor_views["ackman"]  = _paper_investor_ackman(indicators)    # ROC20/60 + SMA200 + vol
            investor_views["cohen"]   = _paper_investor_cohen(indicators)     # RSI/MACD/ROC5/10/stoch/atr
            investor_views["dalio"]   = _paper_investor_dalio(indicators)     # ROC60 + SMA200 + ATR + ROC20
            investor_views["wood"]    = _paper_investor_wood(indicators)      # ROC20/60 + 52W + SMA200 + vol
            investor_views["bogle"]   = _paper_investor_bogle(indicators)     # 52W + ATR + vol (passive)
            # Panel B — Wave 3 investor personas (27-agent pool)
            investor_views["soros"]          = _paper_investor_soros(indicators)          # reflexivity
            investor_views["druckenmiller"]  = _paper_investor_druckenmiller(indicators)  # concentrated momentum
            investor_views["simons"]         = _paper_investor_simons(indicators)         # statistical quant
            investor_views["templeton"]      = _paper_investor_templeton(indicators)      # contrarian

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

            # Quick deterministic regime estimate for Dalio context (before agents fire)
            _roc20 = indicators.get("roc_20", 0) or 0
            _atr14 = indicators.get("atr_14", 0) or 0
            _price = max(indicators.get("price", 1) or 1, 1e-9)
            _quick_regime = (
                "HIGH_VOLATILITY" if (_atr14 / _price) > 0.04
                else "TRENDING_UP"   if _roc20 > 3
                else "TRENDING_DOWN" if _roc20 < -3
                else "RANGING"
            )

            # FRED macro indicators (cached 1h — shared across all parallel workers)
            _fred_ctx = fetch_macro_context()

            macro_ctx  = {
                "symbol": symbol, "asset_class": asset_class,
                "bars_last_60": bars_dicts, "indicators": indicators,
                "portfolio_equity": portfolio.equity,
                "daily_pnl_pct": portfolio.daily_pnl_pct,
                # Real macro data from FRED
                **_fred_ctx,
            }

            # Helper: extract only declared keys from indicators (asymmetric information partition)
            _ind_str = lambda keys: {k: indicators.get(k) for k in keys if k in indicators}

            # Fetch yfinance fundamentals — TTL-cached 30 min to avoid rate limiting
            # with 40+ stock symbols running in parallel workers.
            yf_fundamentals: dict = {}
            if asset_class == "stock":
                cached_entry = _YF_CACHE.get(symbol)
                if cached_entry and (time.monotonic() - cached_entry[0]) < _YF_CACHE_TTL:
                    yf_fundamentals = cached_entry[1]
                    log.debug("yfinance cache hit for %s (%d fields)", symbol, len(yf_fundamentals))
                else:
                    import yfinance as yf
                    _info: dict = {}
                    for _attempt in range(3):
                        try:
                            _info = yf.Ticker(symbol).info
                            break
                        except Exception as exc:
                            if _attempt == 2:
                                log.debug("yfinance fetch failed after 3 attempts for %s: %s", symbol, exc)
                            else:
                                time.sleep(0.5 * (_attempt + 1))
                    yf_fundamentals = {
                        "pe_ratio":       _info.get("trailingPE"),
                        "forward_pe":     _info.get("forwardPE"),
                        "eps_ttm":        _info.get("trailingEps"),
                        "revenue_growth": _info.get("revenueGrowth"),
                        "profit_margin":  _info.get("profitMargins"),
                        "debt_to_equity": _info.get("debtToEquity"),
                        "market_cap":     _info.get("marketCap"),
                        "sector":         _info.get("sector"),
                        "industry":       _info.get("industry"),
                        "52w_high":       _info.get("fiftyTwoWeekHigh"),
                        "52w_low":        _info.get("fiftyTwoWeekLow"),
                    }
                    yf_fundamentals = {k: v for k, v in yf_fundamentals.items() if v is not None}
                    # Flag for the fundamental agent: if < 3 real fields, data quality is low
                    yf_fundamentals["data_available"] = len(yf_fundamentals) >= 3
                    _YF_CACHE[symbol] = (time.monotonic(), yf_fundamentals)
                    log.debug("yfinance fundamentals for %s: %d fields (fetched)", symbol, len(yf_fundamentals))

            # Panel A tactical contexts
            panel_a_tasks: dict[str, tuple[Any, dict]] = {
                "fundamental": (self._fundamental.analyse, {
                    "symbol": symbol, "asset_class": asset_class,
                    "bars_last_60": bars_dicts,
                    "fundamentals": yf_fundamentals,    # real P/E, EPS, margins etc.
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
                    # Real options chain data: put/call ratio + ATM IV (cached 30 min)
                    **_fetch_options_data(symbol),
                }),
                # New Panel A specialists — each receives only its declared indicator slice
                "breakout": (self._breakout.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "high_proximity", "low_proximity",
                                "volume_ratio", "atr_14", "atr_trend", "roc_5"])}),
                "trend_strength": (self._trend_strength.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "rsi_14", "macd", "macd_signal",
                                "sma_20", "sma_50", "sma_200", "roc_20", "roc_60"])}),
                "sector_rotation": (self._sector_rotation.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "roc_20", "roc_60", "volume_ratio",
                                "sma_50", "high_proximity"]),
                    # Real cross-sector ETF momentum (11 SPDR ETFs, cached 1h)
                    **_fetch_sector_momentum(),
                }),
                "earnings_event": (self._earnings_event.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "atr_14", "atr_trend", "bb_width",
                                "bb_width_trend", "roc_5", "roc_10", "volume_ratio"])}),
                # Wave 3 Panel A specialists
                "momentum_scorer": (self._momentum_scorer.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "roc_5", "roc_10", "roc_20", "roc_60",
                                "stoch_k", "stoch_d"])}),
                "supply_demand": (self._supply_demand.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "bb_upper", "bb_lower", "high_proximity",
                                "low_proximity", "volume_ratio"])}),
                "volume_analyst": (self._volume_analyst.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "volume_ratio", "roc_5", "roc_10", "atr_trend"])}),
                "risk_reward": (self._risk_reward.analyse, {
                    "symbol": symbol,
                    **_ind_str(["price", "atr_14", "bb_width", "bb_upper", "bb_lower",
                                "high_proximity", "low_proximity", "stoch_k"])}),
            }

            # Panel B — each persona receives only its data slice
            # (system prompt enforces philosophy; context provides the numbers)
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
                "dalio": (self._dalio.analyse, {
                    **_ind_str(["symbol", "price", "roc_60", "sma_200", "atr_14", "roc_20"]),
                    "regime_label": _quick_regime,  # deterministic estimate — replaced by regime agent after
                }),
                "wood": (self._wood.analyse, _ind_str(
                    ["symbol", "price", "roc_20", "roc_60", "high_proximity",
                     "sma_200", "volume_ratio", "atr_14"])),
                "bogle": (self._bogle.analyse, _ind_str(
                    ["symbol", "price", "high_proximity", "low_proximity", "atr_14", "volume_ratio"])),
                # Wave 3 investor personas
                "soros": (self._soros.analyse, _ind_str(
                    ["symbol", "price", "roc_60", "sma_200", "roc_20", "atr_14", "high_proximity"])),
                "druckenmiller": (self._druckenmiller.analyse, _ind_str(
                    ["symbol", "price", "roc_20", "roc_60", "roc_5", "sma_50", "volume_ratio"])),
                "simons": (self._simons.analyse, _ind_str(
                    ["symbol", "price", "stoch_k", "stoch_d", "roc_10",
                     "bb_upper", "bb_lower", "volume_ratio"])),
                "templeton": (self._templeton.analyse, _ind_str(
                    ["symbol", "price", "high_proximity", "low_proximity", "roc_60", "volume_ratio"])),
            }
            # Add symbol to panel B contexts (needed by agents)
            for ctx_dict in (d for _, d in panel_b_tasks.values()):
                ctx_dict.setdefault("symbol", symbol)

            with ThreadPoolExecutor(max_workers=AGENT_COUNT) as pool:
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

        # ── Dual-panel vote aggregation (weighted by asset-class preference) ────
        panel_a_tally, panel_b_tally, combined_tally, panels_conflict, conflict_note, b_abstaining = (
            _aggregate_dual_panel(analyst_views, investor_views, asset_class)
        )
        action           = _action_from_votes(combined_tally, panels_conflict=panels_conflict, threshold=WARM_MIN_VOTES)
        regime_view      = analyst_views.get("regime", "")
        regime_label     = _parse_regime_label(regime_view)
        votes_for_action = (
            combined_tally["bullish"] if action == "BUY"
            else combined_tally["bearish"] if action == "SELL"
            else 0
        )

        log.info(
            "Dual-panel votes (27 agents): A=%s B=%s combined=%s conflict=%s → action=%s regime=%s mode=%s",
            panel_a_tally, panel_b_tally, combined_tally,
            panels_conflict, action, regime_label, mode_label,
        )

        # ── Round 2: Risk Manager + Strategy Coach ────────────────────────────
        if paper_mode:
            # Rule-based risk manager — uses portfolio values, no LLM
            risk_raw      = _paper_risk_manager(
                action, combined_tally, portfolio,
                self._max_pos, self._max_crypto, asset_class,
                stop_loss_pct=self._stop_loss_pct,
                take_profit_pct=self._take_profit_pct,
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
                        "suggested_position_pct": self._max_pos,
                        "stop_loss_pct": self._stop_loss_pct,
                        "take_profit_pct": self._take_profit_pct,
                        "devil_advocate_score": 0, "devil_advocate_case": "",
                    })
                try:
                    strategy_view = strategy_future.result()
                except Exception as exc:
                    log.error("Strategy coach failed: %s", exc)
                    strategy_view = "ALIGNED"

        try:
            parsed = json.loads(_strip_fences(risk_raw))
            # Sanitise rationale — model sometimes adds markdown despite instructions
            if "rationale" in parsed:
                parsed["rationale"] = _clean_rationale(parsed["rationale"])
        except json.JSONDecodeError:
            log.warning("Risk manager non-JSON — using defaults: %s", risk_raw[:120])
            # Generate a clean rationale from vote data instead of storing raw markdown
            bulls   = combined_tally.get("bullish",  0)
            bears   = combined_tally.get("bearish",  0)
            neutral = combined_tally.get("neutral", 0)
            mood    = "Bullish" if action == "BUY" else "Bearish" if action == "SELL" else "Mixed"
            parsed = {
                "action": action, "confidence": 0.0,
                "rationale": (
                    f"{mood} consensus: {bulls:.1f} bullish, {bears:.1f} bearish, "
                    f"{neutral:.1f} neutral agent votes."
                ),
                "devil_advocate_score": 0, "devil_advocate_case": "",
            }

        strategy_fit = _parse_strategy_fit(strategy_view)

        # ── Risk manager veto: if risk says HOLD, honour it ──────────────────
        risk_action = parsed.get("action", action)
        if risk_action == "HOLD" and action in ("BUY", "SELL"):
            log.warning(
                "Risk manager vetoed %s for %s → HOLD: %s",
                action, symbol, parsed.get("rationale", ""),
            )
            action = "HOLD"
            votes_for_action = 0

        # ── Tier — deterministic from combined 15-agent votes + regime ────────
        tier = _compute_tier(
            combined_tally, action, regime_label, indicators,
            panels_conflict=panels_conflict,
            b_abstaining=b_abstaining,
        )

        # ── Strategy Coach veto: MISALIGNED on a WARM signal → COLD ─────────
        # HOT signals survive MISALIGNED (consensus too strong to override).
        # COLD signals are already blocked and need no further downgrade.
        if strategy_fit == "MISALIGNED" and tier == "WARM":
            log.info(
                "Strategy coach veto: %s MISALIGNED — WARM downgraded to COLD for %s",
                action, symbol,
            )
            tier = "COLD"

        # ── Confidence-scaled position sizing (Phase 1-F) ────────────────────
        # Linear scale: conf=0.60→60% of base size, conf≥0.85→100%.
        # Prevents the system from going full-size on low-confidence signals.
        _conf = float(parsed.get("confidence", 0.0))
        _base_pos_pct = float(parsed.get("suggested_position_pct", 0.0))
        if _base_pos_pct > 0 and _conf > 0:
            _scale = (_conf - 0.60) / (0.85 - 0.60)         # 0.0 at conf=0.60, 1.0 at conf=0.85
            _scale = max(0.0, min(1.0, _scale))               # clamp to [0, 1]
            _size_factor = 0.60 + _scale * 0.40              # maps to [0.60, 1.00]
            _base_pos_pct = _base_pos_pct * _size_factor
            log.debug("Confidence sizing: conf=%.2f scale=%.2f pos_pct=%.3f",
                      _conf, _size_factor, _base_pos_pct)

        signal = TradingSignal(
            symbol=symbol,
            asset_class=asset_class,
            action=action,
            confidence=_conf,
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
            suggested_position_pct=_base_pos_pct,
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
            # Panel A — Wave 2 specialists
            breakout_view=analyst_views.get("breakout", ""),
            trend_strength_view=analyst_views.get("trend_strength", ""),
            sector_rotation_view=analyst_views.get("sector_rotation", ""),
            earnings_event_view=analyst_views.get("earnings_event", ""),
            # Panel A — Wave 3 specialists
            momentum_scorer_view=analyst_views.get("momentum_scorer", ""),
            supply_demand_view=analyst_views.get("supply_demand", ""),
            volume_analyst_view=analyst_views.get("volume_analyst", ""),
            risk_reward_view=analyst_views.get("risk_reward", ""),
            # Panel B — Wave 3 investor personas
            soros_view=investor_views.get("soros", ""),
            druckenmiller_view=investor_views.get("druckenmiller", ""),
            simons_view=investor_views.get("simons", ""),
            templeton_view=investor_views.get("templeton", ""),
        )

        log.info(
            "Signal: %s %s tier=%s votes=%.1f/%.1f (A=%s B=%s) conflict=%s regime=%s fit=%s",
            action, symbol, tier, votes_for_action, _total_system_weight(asset_class),
            panel_a_tally, panel_b_tally, panels_conflict, regime_label, strategy_fit,
        )
        return signal
