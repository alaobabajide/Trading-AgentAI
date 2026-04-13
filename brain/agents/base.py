"""Base class shared by all analyst agents."""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

log = logging.getLogger(__name__)

# Tactical agents (fundamental, technical, etc.) use Haiku — fast + cheap.
# Synthesis agents (risk manager, strategy coach) use Sonnet — better reasoning.
TACTICAL_MODEL  = "claude-haiku-4-5-20251001"
SYNTHESIS_MODEL = "claude-sonnet-4-6"


class BaseAnalyst:
    """Wraps a single Claude call with a specialist system prompt."""

    role: str    = "analyst"
    system_prompt: str = "You are a financial analyst."
    model: str   = TACTICAL_MODEL   # override in subclass for synthesis agents

    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    def analyse(self, context: dict[str, Any]) -> str:
        """Send context → Claude → return plain-text opinion."""
        user_msg = json.dumps(context, indent=2, default=str)
        response = self._client.messages.create(
            model=self.model,
            max_tokens=512,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        log.debug("[%s] opinion: %s", self.role, text[:120])
        return text
