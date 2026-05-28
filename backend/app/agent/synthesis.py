"""Claude phrasing for the render layer — GROUND synthesis + Hybrid SPEAK smoothing.

Pipecat-free so both the live voice bot and the text-mode simulator share one implementation.
`make_synthesizer` returns the `(instruction) -> text | None` callable that `render()` uses; it
returns ``None`` on any error so render falls back to the safe/verbatim text rather than failing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from app.agent.persona import build_system_prompt
from app.config import Settings

logger = logging.getLogger(__name__)

# Cap how much transcript we replay into a phrasing call — recent turns carry the context that
# prevents repetition/contradiction; older turns add latency and tokens for little gain (P10-T2).
MAX_HISTORY_TURNS = 20

# (speaker, text) pairs as produced by ConversationState.history. Speakers are "prospect"/"user"
# (the caller) and "agent"/"assistant" (us).
History = Sequence[tuple[str, str]]

_ROLE_OF = {"prospect": "user", "user": "user", "agent": "assistant", "assistant": "assistant"}


def _history_messages(history: History, instruction: str) -> list[dict]:
    """Turn the running transcript + the phrasing instruction into Claude `messages`.

    Maps each turn to a user/assistant message, coalesces consecutive same-role turns, drops any
    leading assistant turn (Anthropic requires the first message to be the user's), and appends the
    phrasing instruction as the final user turn so the model phrases the *next* line with the whole
    conversation in view.
    """
    messages: list[dict] = []
    for speaker, text in list(history)[-MAX_HISTORY_TURNS:]:
        role = _ROLE_OF.get(speaker, "user")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": role, "content": text})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    if messages and messages[-1]["role"] == "user":
        messages[-1] = {"role": "user", "content": f"{messages[-1]['content']}\n\n{instruction}"}
    else:
        messages.append({"role": "user", "content": instruction})
    return messages


def make_synthesizer(
    settings: Settings, *, client: object | None = None
) -> Callable[..., str | None]:
    """Build a Claude phrasing function. The persona is the (cached) system prompt so output
    stays in voice; the client is injected for tests and created lazily otherwise.

    The returned callable takes ``(instruction, history=None)``. When ``history`` (the running
    transcript) is supplied, it's replayed as prior messages so the LLM phrases with conversational
    context — it won't re-ask what was answered and can smooth over a caller's correction (P10-T2).
    """
    system = build_system_prompt(settings)

    def synthesize(instruction: str, history: History | None = None) -> str | None:
        nonlocal client
        try:
            if client is None:
                import anthropic  # lazy

                client = anthropic.Anthropic(api_key=settings.anthropic_api_key or "")
            messages = (
                _history_messages(history, instruction)
                if history
                else [{"role": "user", "content": instruction}]
            )
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=400,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text or None
        except Exception as exc:  # never let a phrasing error drop the conversation
            logger.warning("synthesize failed, falling back: %s", exc)
            return None

    return synthesize
