"""Directive + render — the single contract for turning a decision into words (P4.5-T3).

`NextAction.prompt` was overloaded: for most actions it holds the *final words* to say
(a discovery question, a confirmation, a rebuttal, the escalation line, the KB-4 fallback),
but for a grounded KB answer it holds an *LLM instruction* ("answer using ONLY this…"). A
:class:`Directive` makes that explicit with a `kind`:

- **SPEAK** — `text` is the final words. `render` returns them (deterministic).
- **GROUND** — `instruction` is fed to the LLM to synthesize from approved snippets; if no LLM
  is available, `render` degrades to the honest fallback (KB-4). Never guesses.

`render(directive, synthesize=…) → utterance` is the one place words are produced — so it's a
pure function of its inputs (deterministic for SPEAK; LLM-or-fallback for GROUND), which is what
lets the latency tiers (P4.5-T6) cache/precompute it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from app.agent.knowledge import FALLBACK_MESSAGE
from app.agent.orchestrator import NextAction
from app.agent.stages import Action, Modifier


class ContentKind(str, Enum):
    SPEAK = "speak"    # `text` is the final words to say
    GROUND = "ground"  # synthesize from KB material via the LLM, with a safe fallback


@dataclass
class Directive:
    """A structured render spec — what to say and how to produce it."""

    intent: Action
    kind: ContentKind
    text: str | None = None          # SPEAK: the words
    instruction: str | None = None   # GROUND: the LLM grounding instruction (snippets baked in)
    fallback: str | None = None      # GROUND: safe words if no LLM is available
    sources: list[str] = field(default_factory=list)  # KB-3 source ids (trace)
    style: Modifier | None = None    # human-layer modifier, if any


def to_directive(action: NextAction) -> Directive:
    """Map a capability's :class:`NextAction` to its render Directive."""
    # The only GROUND case: a KB answer that actually retrieved sources. A KB fallback
    # (no sources) already carries final words, so it's SPEAK like everything else.
    if action.action is Action.ANSWER_KNOWLEDGE and action.kb_sources:
        return Directive(
            intent=action.action,
            kind=ContentKind.GROUND,
            instruction=action.prompt,
            fallback=FALLBACK_MESSAGE,
            sources=list(action.kb_sources),
            style=action.modifier,
        )
    return Directive(
        intent=action.action,
        kind=ContentKind.SPEAK,
        text=action.prompt or "",
        style=action.modifier,
    )


# An LLM phrasing function: instruction -> spoken text. Injected live; omitted in tests.
Synthesize = Callable[[str], str]


def render(directive: Directive, *, synthesize: Synthesize | None = None) -> str:
    """Produce the final utterance for a directive.

    SPEAK returns its words directly. GROUND synthesizes from the instruction via ``synthesize``
    when available, otherwise degrades to the honest fallback rather than guessing (KB-4).
    """
    if directive.kind is ContentKind.GROUND:
        if synthesize is not None and directive.instruction:
            return synthesize(directive.instruction)
        return directive.fallback or FALLBACK_MESSAGE
    return directive.text or ""
