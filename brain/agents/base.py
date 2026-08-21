"""Base class shared by all analyst agents."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timezone
from typing import Any

from watchlist import TACTICAL_MODEL, SYNTHESIS_MODEL  # single source of truth for model IDs

log = logging.getLogger(__name__)

# ── Per-model pricing (USD per million tokens, mirroring watchlist.py comments) ──
_MODEL_PRICE: dict[str, tuple[float, float]] = {
    TACTICAL_MODEL:   (0.10, 0.40),   # (input $/M, output $/M)
    SYNTHESIS_MODEL:  (0.27, 1.12),
}

# ── Module-level daily usage accumulator (thread-safe) ────────────────────────
_usage_lock = threading.Lock()
# Keyed by ISO date string, e.g. "2026-08-13"
# Inner dict: {input_tokens, output_tokens, cost_usd, calls, by_model}
_daily_usage: dict[str, dict] = {}


def _record_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    today = date.today().isoformat()
    in_price, out_price = _MODEL_PRICE.get(model, (0.0, 0.0))
    cost = (prompt_tokens / 1_000_000) * in_price + (completion_tokens / 1_000_000) * out_price
    with _usage_lock:
        if today not in _daily_usage:
            _daily_usage[today] = {
                "date": today,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "calls": 0,
                "by_model": {},
            }
        day = _daily_usage[today]
        day["input_tokens"] += prompt_tokens
        day["output_tokens"] += completion_tokens
        day["cost_usd"] = round(day["cost_usd"] + cost, 6)
        day["calls"] += 1
        m = day["by_model"].setdefault(model, {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0,
        })
        m["input_tokens"] += prompt_tokens
        m["output_tokens"] += completion_tokens
        m["cost_usd"] = round(m["cost_usd"] + cost, 6)
        m["calls"] += 1


def get_usage_stats() -> dict:
    """Return a copy of the daily usage dict, newest day first."""
    with _usage_lock:
        history = sorted(_daily_usage.values(), key=lambda d: d["date"], reverse=True)
    today_str = date.today().isoformat()
    today = next((d for d in history if d["date"] == today_str), {
        "date": today_str, "input_tokens": 0, "output_tokens": 0,
        "cost_usd": 0.0, "calls": 0, "by_model": {},
    })
    return {"today": today, "history": history}


class BaseAnalyst:
    """Wraps a single LLM call with a specialist system prompt."""

    role: str    = "analyst"
    system_prompt: str = "You are a financial analyst."
    model: str   = TACTICAL_MODEL   # override in subclass for synthesis agents

    def __init__(self, client: Any, model: str | None = None) -> None:
        self._client = client
        if model is not None:
            self.model = model  # per-instance override from DebateOrchestrator

    def analyse(self, context: dict[str, Any]) -> str:
        """Send context → LLM → return plain-text opinion."""
        user_msg = json.dumps(context, indent=2, default=str)
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user",   "content": user_msg},
                ],
            )
        except Exception as exc:
            msg = str(exc)
            if "credit" in msg.lower() or "insufficient_quota" in msg or "billing" in msg.lower() or "402" in msg:
                raise RuntimeError(
                    "BILLING: LLM API credit balance is too low. "
                    "Check your provider's billing dashboard."
                ) from exc
            raise
        text = response.choices[0].message.content.strip()
        log.debug("[%s] opinion: %s", self.role, text[:120])

        # ── Record token usage for transparency dashboard ──────────────────────
        try:
            usage = response.usage
            if usage:
                _record_usage(
                    self.model,
                    int(getattr(usage, "prompt_tokens", 0) or 0),
                    int(getattr(usage, "completion_tokens", 0) or 0),
                )
        except Exception:
            pass  # never let tracking break a trade

        return text
