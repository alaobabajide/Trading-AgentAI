"""Market Regime Detector — deterministic rules, no LLM call.

Rules (evaluated in priority order):
  HIGH_VOLATILITY  ATR% > 3.0 %
  TRENDING_DOWN    MACD < signal AND RSI < 50
  TRENDING_UP      MACD > signal AND RSI > 50
  RANGING          all other cases (mixed/low-momentum signals)
"""
from __future__ import annotations

from typing import Any


class RegimeDetector:
    """Classifies regime from technical indicators without an LLM call.

    The client argument is accepted for API compatibility with other agents
    (which do need it) but is never used here.
    """
    role = "regime"

    def __init__(self, client=None) -> None:  # noqa: ARG002
        pass

    def analyse(self, ctx: dict[str, Any]) -> str:
        ind      = ctx.get("indicators", {})
        price    = float(ind.get("price",       1.0) or 1.0)
        atr      = float(ind.get("atr_14",      0.0))
        rsi      = float(ind.get("rsi_14",     50.0))
        macd     = float(ind.get("macd",        0.0))
        macd_sig = float(ind.get("macd_signal", 0.0))
        bb_width = float(ind.get("bb_width",    0.05))

        atr_pct = atr / price

        if atr_pct > 0.030:
            label, direction = "HIGH_VOLATILITY", "NEUTRAL"
            reasoning = (
                f"ATR is {atr_pct * 100:.1f}% of price (threshold 3.0%). "
                "Elevated volatility degrades both trend-following and mean-reversion strategies. "
                "Recommend standing aside or cutting position sizes ≥ 50%."
            )
        elif macd < macd_sig and rsi < 50:
            label, direction = "TRENDING_DOWN", "BEARISH"
            reasoning = (
                f"MACD {macd:.4f} below signal {macd_sig:.4f}; RSI {rsi:.1f} < 50. "
                "Confirmed downtrend with bearish momentum alignment. "
                "Trend-following SHORT entries favoured; avoid counter-trend longs."
            )
        elif macd > macd_sig and rsi > 50:
            label, direction = "TRENDING_UP", "BULLISH"
            reasoning = (
                f"MACD {macd:.4f} above signal {macd_sig:.4f}; RSI {rsi:.1f} > 50. "
                "Confirmed uptrend with bullish momentum alignment. "
                "Trend-following LONG entries favoured with ATR-based trailing stop."
            )
        else:
            label, direction = "RANGING", "NEUTRAL"
            reasoning = (
                f"MACD/RSI signals mixed (RSI {rsi:.1f}, BB width {bb_width:.4f}). "
                "No confirmed trending regime — mean-reversion probability elevated. "
                "Wait for regime confirmation before entering directional positions."
            )

        return (
            f"DIRECTION: {direction}\n"
            f"REGIME: {label}\n"
            f"REASONING: {reasoning}"
        )
