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


# Intents whose SPEAK text should be LLM-smoothed into natural phrasing (Hybrid rendering):
# discovery questions, confirmations, fit summaries, and pivots. Fixed lines (rebuttals,
# escalation, KB-4 fallback, the wrap-up close) are spoken verbatim — they're approved language.
_SMOOTHABLE_INTENTS = frozenset(
    {
        Action.ASK_REQUIRED_DISCOVERY,
        Action.ASK_LEADING_DISCOVERY,
        Action.SUMMARIZE_FIT,
        Action.PIVOT_TOWARD_CLOSE,
    }
)


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
    smoothable: bool = False         # SPEAK: may be LLM-rephrased for natural delivery (DF-4)


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
        smoothable=action.action in _SMOOTHABLE_INTENTS,
    )


# An LLM phrasing function: (instruction, history?) -> spoken text (or None on failure). Injected
# live. ``history`` (the running transcript) is optional so 1-arg callables still satisfy it.
Synthesize = Callable[..., "str | None"]


def _smoothing_instruction(text: str) -> str:
    return (
        "Rephrase the following into a natural, warm, spoken-style line. Keep it to one or two "
        "sentences, add no new information, and output only the words to say:\n\n"
        f"{text}"
    )


def _synthesize(synthesize: Synthesize, instruction: str, history) -> str | None:
    """Call the phrasing fn, passing the transcript only when we have one — so a plain
    ``(instruction)`` callable (tests, text-mode) keeps working unchanged."""
    return synthesize(instruction, history) if history else synthesize(instruction)


def render(directive: Directive, *, synthesize: Synthesize | None = None, history=None) -> str:
    """Produce the final utterance for a directive (Hybrid rendering).

    - GROUND: synthesize from the instruction via ``synthesize``; degrade to the honest KB-4
      fallback if there's no LLM or it fails (never guesses).
    - SPEAK + smoothable: LLM-rephrase the authored text for natural delivery, falling back to
      the verbatim text if there's no LLM or it fails.
    - SPEAK otherwise: the words verbatim (approved fixed language).

    ``history`` (the running transcript) is forwarded to ``synthesize`` so the LLM phrases with
    conversational context (P10-T2); it never affects the deterministic SPEAK paths.
    """
    if directive.kind is ContentKind.GROUND:
        if synthesize is not None and directive.instruction:
            return _synthesize(synthesize, directive.instruction, history) or (
                directive.fallback or FALLBACK_MESSAGE
            )
        return directive.fallback or FALLBACK_MESSAGE

    text = directive.text or ""
    if text and directive.smoothable and synthesize is not None:
        return _synthesize(synthesize, _smoothing_instruction(text), history) or text
    return text
