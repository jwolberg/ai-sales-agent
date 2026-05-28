"""Field & intent extraction — turning a caller's words into state (P4.5-T2).

This is the NLU step the decider-led runtime needs: given the caller's utterance and the
question we just asked, produce field updates for `collected_fields`, detect buying /
disqualification signals, and flag when we didn't get a usable answer ("didn't catch that →
clarify", LM-2).

v1 is **rule-based and deterministic** (no LLM, so it's cheap and unit-testable). It hides
behind the :class:`Extractor` protocol so an LLM-backed structured extractor can be dropped in
later without touching the engine. The rule-based slot-fill is coarse — it stores the cleaned
utterance as the field value rather than parsing out the exact token (the LLM version refines
that) — which is fine for skip-known logic and for weaving into confirmations/summaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.agent.knowledge import is_knowledge_question

# Utterances that don't actually answer the question -> trigger a clarify rather than storing.
_NON_ANSWERS = ("i don't know", "i dont know", "not sure", "no idea", "idk", "dunno", "no clue")

# Committal phrases that signal buying intent (kept specific so questions like "how do I get
# started?" don't trip them).
_BUYING_CUES = (
    "let's do it", "lets do it", "let's get started", "lets get started", "sign me up",
    "sounds good", "i'm ready", "im ready", "ready to start", "ready to go", "book it",
    "let's go", "lets go", "where do i sign", "yes let's", "yes lets", "i'm in", "im in",
    "count me in", "set it up", "let's set it up",
)

_DISQUALIFY_CUES = (
    "just looking", "just browsing", "not for me", "no longer need", "already found",
    "found a tutor", "found someone", "not looking anymore", "changed my mind",
)

_LEADING_FILLER = re.compile(
    r"^(?:well|um|uh|so|like|okay|ok|yeah|yes|i mean|it's|its)[,\s]+", re.I
)


@dataclass
class Extraction:
    """What we learned from one caller turn."""

    fields: dict[str, str] = field(default_factory=dict)  # updates to merge into collected_fields
    buying_intent: bool = False
    disqualified: bool = False
    understood: bool = True  # False -> answer wasn't usable; the agent should clarify (LM-2)


@runtime_checkable
class Extractor(Protocol):
    """Turns an utterance (and the pending question) into an :class:`Extraction`."""

    def extract(self, utterance: str, *, pending_field: str | None = None) -> Extraction: ...


def _is_non_answer(lowered: str) -> bool:
    return any(na in lowered for na in _NON_ANSWERS)


def _is_substantive_answer(utterance: str) -> bool:
    lowered = utterance.strip().lower()
    if not lowered:
        return False
    if is_knowledge_question(utterance):  # a question back isn't an answer
        return False
    if _is_non_answer(lowered):
        return False
    return any(ch.isalnum() for ch in lowered)


def _clean_value(utterance: str) -> str:
    """Light cleanup: strip a leading filler/affirmation and trailing punctuation."""
    value = _LEADING_FILLER.sub("", utterance.strip())
    return value.strip().rstrip(".!?,")


class RuleBasedExtractor:
    """Deterministic v1 extractor: slot-fill the pending question + cue-based signals."""

    def extract(self, utterance: str, *, pending_field: str | None = None) -> Extraction:
        lowered = utterance.lower()
        result = Extraction(
            buying_intent=any(cue in lowered for cue in _BUYING_CUES),
            disqualified=any(cue in lowered for cue in _DISQUALIFY_CUES),
        )
        if pending_field is not None:
            if _is_substantive_answer(utterance):
                value = _clean_value(utterance)
                if value:
                    result.fields[pending_field] = value
                else:
                    result.understood = False
            else:
                # We asked something and didn't get a usable answer -> clarify.
                result.understood = False
        return result


def get_extractor() -> Extractor:
    """Return the default extractor (rule-based for now; LLM-backed later)."""
    return RuleBasedExtractor()
