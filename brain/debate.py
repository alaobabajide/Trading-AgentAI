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


# ── Paper-mode rule-based analysts (no LLM, no API credits needed) ────────────

def _paper_technical(indicators: dict) -> str:
    """RSI + MACD crossover rule — replaces LLM Technical Analyst in paper mode."""
    rsi      = float(indicators.get("rsi_14", 50.0))
    macd     = float(indicators.get("macd", 0.0))
    macd_sig = float(indicators.get("macd_signal", 0.0))

    bullish = (rsi < 35) or (macd > macd_sig and rsi < 62)
    bearish = (rsi > 65) or (macd < macd_sig and rsi > 38)

    if bullish and not bearish:
        direction = "BULLISH"
    elif bearish and not bullish:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    cross = "↑ bullish" if macd > macd_sig else "↓ bearish" if macd < macd_sig else "flat"
    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode — RSI={rsi:.1f}, MACD {cross} ({macd:.4f} vs signal {macd_sig:.4f})."
    )


def _paper_quant(indicators: dict) -> str:
    """Bollinger Bands position — replaces LLM Quant Analyst in paper mode."""
    price    = float(indicators.get("price", 0.0))
    bb_upper = float(indicators.get("bb_upper", price * 1.05))
    bb_lower = float(indicators.get("bb_lower", price * 0.95))
    bb_width = float(indicators.get("bb_width", 0.02))
    atr      = float(indicators.get("atr_14", 0.0))

    if bb_width < 0.005:
        return (
            "DIRECTION: NEUTRAL\n"
            f"REASONING: Paper mode — Bollinger squeeze (width={bb_width:.4f}), no directional edge."
        )
    if price <= bb_lower:
        direction, note = "BULLISH", f"price ${price:.2f} at/below lower band ${bb_lower:.2f}"
    elif price >= bb_upper:
        direction, note = "BEARISH", f"price ${price:.2f} at/above upper band ${bb_upper:.2f}"
    else:
        direction, note = "NEUTRAL", f"price ${price:.2f} mid-bands (${bb_lower:.2f}–${bb_upper:.2f})"

    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode — Bollinger Bands: {note}, ATR={atr:.2f}."
    )


def _paper_fundamental(bars: list[dict]) -> str:
    """20-day price momentum — replaces LLM Fundamental Analyst in paper mode."""
    if len(bars) < 20:
        return "DIRECTION: NEUTRAL\nREASONING: Paper mode — insufficient history for momentum."
    close_now = float(bars[-1]["close"])
    close_20d = float(bars[-21]["close"] if len(bars) >= 21 else bars[0]["close"])
    momentum  = (close_now - close_20d) / max(close_20d, 1e-9) * 100

    if momentum > 5.0:
        direction = "BULLISH"
    elif momentum < -5.0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode — 20-day momentum {momentum:+.1f}% "
        f"(${close_20d:.2f} → ${close_now:.2f})."
    )


def _paper_options_flow(indicators: dict) -> str:
    """Vol-adjusted directional bias — replaces LLM Options Flow Analyst in paper mode."""
    price    = float(indicators.get("price", 1.0))
    atr      = float(indicators.get("atr_14", 0.0))
    macd     = float(indicators.get("macd", 0.0))
    macd_sig = float(indicators.get("macd_signal", 0.0))
    atr_pct  = atr / max(price, 1e-9)

    if atr_pct > 0.025:
        return (
            "DIRECTION: NEUTRAL\n"
            f"REASONING: Paper mode — elevated ATR {atr_pct*100:.1f}% (>2.5%), "
            "implied volatility analogue high, no directional edge."
        )
    if macd > macd_sig:
        direction, note = "BULLISH", "low-vol uptrend — premium compressed, bullish flow"
    elif macd < macd_sig:
        direction, note = "BEARISH", "low-vol downtrend — bearish momentum"
    else:
        direction, note = "NEUTRAL", "no directional flow signal"

    return (
        f"DIRECTION: {direction}\n"
        f"REASONING: Paper mode — vol-adjusted flow ({note}). ATR={atr_pct*100:.2f}%."
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
                f"Consensus {votes}/7. Position={pos_pct*100:.1f}% NAV."
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
            f"({cash_ratio*100:.1f}%). Vote consensus {votes}/7. "
            f"Position sized at {pos_pct*100:.1f}% of equity."
        )

    votes = vote_tally.get("bullish" if action == "BUY" else "bearish", 0)
    return json.dumps({
        "action":                 action,
        "confidence":             round(votes / 7.0, 2),
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
        paper_mode: bool = False,
    ) -> TradingSignal:
        symbol      = market.symbol
        asset_class = market.asset_class
        profile     = user_profile or DEFAULT_PROFILE
        mode_label  = "paper-rule-based" if paper_mode else "live-LLM"
        log.info("9-agent debate starting: %s (%s) mode=%s", symbol, asset_class, mode_label)

        bars_dicts = _bars_to_dicts(market)
        indicators = _compute_indicators(market)

        price   = indicators.get("price", 1.0) or 1.0
        atr_pct = indicators.get("atr_14", 0.0) / price
        _regime_tracker.record_atr(atr_pct)

        analyst_views: dict[str, str] = {}

        if paper_mode:
            # ── Paper mode: all rule-based, zero LLM calls ────────────────────
            # Regime is already deterministic — run as normal.
            regime_ctx = {"symbol": symbol, "bars_last_60": bars_dicts, "indicators": indicators}
            analyst_views["regime"] = self._regime.analyse(regime_ctx)

            analyst_views["technical"]    = _paper_technical(indicators)
            analyst_views["quant"]        = _paper_quant(indicators)
            analyst_views["fundamental"]  = _paper_fundamental(bars_dicts)
            analyst_views["options_flow"] = _paper_options_flow(indicators)
            analyst_views["macro"]     = (
                "DIRECTION: NEUTRAL\n"
                "REASONING: Paper mode — macro analysis uses live economic data feed "
                "(not available without live API). Defaulting to neutral."
            )
            analyst_views["sentiment"] = (
                "DIRECTION: NEUTRAL\n"
                "REASONING: Paper mode — sentiment requires live news/social feed "
                "(not available without live API). Defaulting to neutral."
            )
            log.info("Paper mode analysts complete: %s", {k: v[:60] for k, v in analyst_views.items()})

        else:
            # ── Live mode: full 9-agent LLM debate ────────────────────────────
            cache_key        = f"{symbol}:strategic"
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

            with ThreadPoolExecutor(max_workers=7) as pool:
                futures: dict[Any, str] = {}

                futures[pool.submit(self._regime.analyse, regime_ctx)] = "regime"

                if cached_strategic:
                    macro_view, _ = cached_strategic
                    analyst_views["macro"] = macro_view
                    log.debug("Macro served from cache for %s", symbol)
                else:
                    futures[pool.submit(self._macro.analyse, macro_ctx)] = "macro"

                for role, (fn, ctx) in tactical_tasks.items():
                    futures[pool.submit(fn, ctx)] = role

                for fut in as_completed(futures):
                    role = futures[fut]
                    try:
                        analyst_views[role] = fut.result()
                    except Exception as exc:
                        log.error("Agent %s failed: %s", role, exc)
                        analyst_views[role] = f"DIRECTION: NEUTRAL\nREASONING: Agent error — {exc}"

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
            "Vote tally: %s → action=%s regime=%s mode=%s",
            vote_tally, action, regime_label, mode_label,
        )

        # ── Round 2: Risk Manager + Strategy Coach ────────────────────────────
        if paper_mode:
            # Rule-based risk manager — uses portfolio values, no LLM
            risk_raw      = _paper_risk_manager(
                action, vote_tally, portfolio,
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
            fundamental_view=analyst_views.get("fundamental", ""),
            technical_view=analyst_views.get("technical", ""),
            sentiment_view=analyst_views.get("sentiment", ""),
            macro_view=analyst_views.get("macro", ""),
            quant_view=analyst_views.get("quant", ""),
            options_flow_view=analyst_views.get("options_flow", ""),
            regime_view=analyst_views.get("regime", ""),
            strategy_view=strategy_view,
            risk_view=risk_raw,
        )

        log.info(
            "Signal: %s %s tier=%s votes=%d/7 regime=%s fit=%s",
            action, symbol, tier, votes_for_action, regime_label, strategy_fit,
        )
        return signal
