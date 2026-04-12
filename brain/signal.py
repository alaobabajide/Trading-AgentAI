"""Shared signal contract — output of the Brain layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class TradingSignal:
    symbol: str
    asset_class: Literal["stock", "crypto"]
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float                     # retained for Risk Manager compat; NOT used for gating
    rationale: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # HITL tier — driven by vote count + deterministic regime, NOT LLM confidence
    tier: Literal["HOT", "WARM", "COLD"] = "WARM"

    # Vote tally from 7 specialist analysts
    vote_tally: dict = field(default_factory=dict)  # {bullish: N, bearish: N, neutral: N}
    votes_for_action: int = 0                        # count of agents that agree with action
    regime_label: str = "UNKNOWN"                    # TRENDING_UP / TRENDING_DOWN / RANGING / HIGH_VOLATILITY

    # Position sizing from Risk Manager
    suggested_position_pct: float = 0.0
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.05

    # Adversarial Devil's Advocate (text only — score removed from execution path)
    devil_advocate_score: int = 0        # retained for display context only
    devil_advocate_case: str = ""

    # Strategy Coach fit assessment
    strategy_fit: Literal["ALIGNED", "MISALIGNED", "PARTIAL"] = "ALIGNED"

    # Per-agent opinions
    fundamental_view: str = ""
    technical_view: str = ""
    sentiment_view: str = ""
    macro_view: str = ""
    quant_view: str = ""
    options_flow_view: str = ""
    regime_view: str = ""
    strategy_view: str = ""
    risk_view: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.action != "HOLD"

    def to_dict(self) -> dict:
        return {
            "symbol":               self.symbol,
            "asset_class":          self.asset_class,
            "action":               self.action,
            "confidence":           round(self.confidence, 4),
            "rationale":            self.rationale,
            "generated_at":         self.generated_at.isoformat(),
            "tier":                 self.tier,
            "vote_tally":           self.vote_tally,
            "votes_for_action":     self.votes_for_action,
            "regime_label":         self.regime_label,
            "suggested_position_pct": self.suggested_position_pct,
            "stop_loss_pct":        self.stop_loss_pct,
            "take_profit_pct":      self.take_profit_pct,
            "devil_advocate_score": self.devil_advocate_score,
            "devil_advocate_case":  self.devil_advocate_case,
            "strategy_fit":         self.strategy_fit,
            "passed_confidence_gate": self.action != "HOLD",
            "agent_views": {
                "fundamental":  self.fundamental_view,
                "technical":    self.technical_view,
                "sentiment":    self.sentiment_view,
                "macro":        self.macro_view,
                "quant":        self.quant_view,
                "options_flow": self.options_flow_view,
                "regime":       self.regime_view,
                "strategy":     self.strategy_view,
                "risk":         self.risk_view,
            },
        }
