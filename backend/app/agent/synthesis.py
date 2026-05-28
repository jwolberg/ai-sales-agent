"""Claude phrasing for the render layer — GROUND synthesis + Hybrid SPEAK smoothing.

Pipecat-free so both the live voice bot and the text-mode simulator share one implementation.
`make_synthesizer` returns the `(instruction) -> text | None` callable that `render()` uses; it
returns ``None`` on any error so render falls back to the safe/verbatim text rather than failing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.agent.persona import build_system_prompt
from app.config import Settings

logger = logging.getLogger(__name__)


def make_synthesizer(
    settings: Settings, *, client: object | None = None
) -> Callable[[str], str | None]:
    """Build a Claude phrasing function. The persona is the (cached) system prompt so output
    stays in voice; the client is injected for tests and created lazily otherwise."""
    system = build_system_prompt(settings)

    def synthesize(instruction: str) -> str | None:
        nonlocal client
        try:
            if client is None:
                import anthropic  # lazy

                client = anthropic.Anthropic(api_key=settings.anthropic_api_key or "")
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=400,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": instruction}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text or None
        except Exception as exc:  # never let a phrasing error drop the conversation
            logger.warning("synthesize failed, falling back: %s", exc)
            return None

    return synthesize
