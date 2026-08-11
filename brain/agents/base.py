"""Base class shared by all analyst agents."""
from __future__ import annotations

import json
import logging
from typing import Any

from watchlist import TACTICAL_MODEL, SYNTHESIS_MODEL  # single source of truth for model IDs

log = logging.getLogger(__name__)


class BaseAnalyst:
    """Wraps a single OpenRouter call with a specialist system prompt."""

    role: str    = "analyst"
    system_prompt: str = "You are a financial analyst."
    model: str   = TACTICAL_MODEL   # override in subclass for synthesis agents

    def __init__(self, client: Any) -> None:
        self._client = client

    def analyse(self, context: dict[str, Any]) -> str:
        """Send context → OpenRouter → return plain-text opinion."""
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
                    "BILLING: OpenRouter API credit balance is too low. "
                    "Add credits at openrouter.ai/settings/billing"
                ) from exc
            raise
        text = response.choices[0].message.content.strip()
        log.debug("[%s] opinion: %s", self.role, text[:120])
        return text
