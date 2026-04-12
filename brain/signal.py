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
    confidence: float                     # 0.0 – 1.0
    rationale: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # HITL tier — drives confirmation UX
    tier: Literal["HOT", "WARM", "COLD"] = "WARM"

    # Optional sizing hints from Risk Manager
    suggested_position_pct: float = 0.0  # % of NAV to allocate
    stop_loss_pct: float = 0.02          # default 2 %
    take_profit_pct: float = 0.05        # default 5 %

    # Adversarial Devil's Advocate (from Risk Manager)
    devil_advocate_score: int = 0        # 0-100, strength of counter-case
    devil_advocate_case: str = ""        # strongest argument against the action

    # Strategy Coach fit assessment
    strategy_fit: Literal["ALIGNED", "MISALIGNED", "PARTIAL"] = "ALIGNED"

    # Per-agent opinions (for logging / explainability)
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
        return self.action != "HOLD" and self.confidence >= 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "generated_at": self.generated_at.isoformat(),
            "suggested_position_pct": self.suggested_position_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "tier": self.tier,
            "devil_advocate_score": self.devil_advocate_score,
            "devil_advocate_case": self.devil_advocate_case,
            "strategy_fit": self.strategy_fit,
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
