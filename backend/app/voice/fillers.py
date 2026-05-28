"""Filler phrases for latency masking (P4.5-T6; AGENT_FLOW §5.10).

A short spoken line played *immediately* while the real response is being computed, so the call
never falls into dead silence. Short neutral acknowledgments on most turns; a "working" filler
when the path is likely slow (a question that needs a KB lookup + synthesis). Phrases rotate so
they don't sound looped, and they're kept neutral so they can never contradict the reply that
follows.

Selection is pure/deterministic (rotation per instance). Actually *playing* the filler — and
ideally pre-synthesizing it to audio so it's instant — is the bot's job (P4.5-T6 wiring).
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from app.agent.knowledge import is_knowledge_question

# Neutral acknowledgments — safe before any reply (can't contradict what follows).
DEFAULT_ACKS: tuple[str, ...] = ("Sure.", "Got it.", "Okay.", "Mm-hmm.", "Right.")

# Longer "I'm working on it" fillers for slow paths (KB lookup + synthesis).
DEFAULT_WORKING: tuple[str, ...] = (
    "Good question — let me check on that.",
    "Let me look into that for you.",
    "Let me make sure I get that right.",
)


class FillerBank:
    """Picks a rotating filler for a turn."""

    def __init__(
        self,
        acks: Sequence[str] = DEFAULT_ACKS,
        working: Sequence[str] = DEFAULT_WORKING,
    ) -> None:
        self._acks = itertools.cycle(acks)
        self._working = itertools.cycle(working)

    def pick(self, text: str) -> str:
        """A 'working' filler if the turn is a question (slow path), else a short ack."""
        if is_knowledge_question(text):
            return next(self._working)
        return next(self._acks)
