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
    """Return the default extractor — rule-based, deterministic, no API.

    The live pipeline opts into :class:`LLMExtractor` explicitly; the simulator and tests use
    this default so they stay offline and deterministic.
    """
    return RuleBasedExtractor()


# --- LLM-backed extractor (P4.5-T2 upgrade) ------------------------------------------------
#
# Captures the pending answer *and any fields the caller volunteers in the same turn* — the
# thing rule-based can't do. Uses the Claude Messages API with structured output. The Anthropic
# client is injected (tests pass a fake), and `anthropic` is imported lazily so importing this
# module never requires the voice extra.

from collections.abc import Iterable  # noqa: E402  (grouped with the LLM extractor)

from pydantic import BaseModel, Field  # noqa: E402

from app.agent.discovery import get_discovery_playbook  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.memory.lead_store import PROFILE_FIELDS  # noqa: E402


def allowed_fields() -> set[str]:
    """The field keys the extractor may emit: discovery playbook keys + lead profile fields."""
    playbook = get_discovery_playbook()
    keys = {q.key for q in playbook.required + playbook.leading}
    keys.update(PROFILE_FIELDS)
    return keys


class ExtractedField(BaseModel):
    """One field the caller revealed."""

    key: str
    value: str


class ExtractionPayload(BaseModel):
    """Structured-output schema Claude fills in for one turn."""

    answer: str | None = Field(
        default=None, description="Caller's answer to the pending question, if they answered it"
    )
    extra_fields: list[ExtractedField] = Field(
        default_factory=list, description="Other discovery fields the caller volunteered"
    )
    buying_intent: bool = Field(default=False, description="Caller signaled readiness to proceed")
    disqualified: bool = Field(default=False, description="Caller is not a fit / not interested")
    understood: bool = Field(
        default=True, description="False if no usable answer to the pending question"
    )


def _build_system_prompt(field_keys: Iterable[str]) -> str:
    keys = ", ".join(sorted(field_keys))
    return (
        "You extract structured facts from one turn of a spoken tutoring sales call. "
        "Return ONLY what the caller actually said — never infer or invent. "
        "If a pending field is named, put the caller's answer to it in `answer` (or leave null "
        "and set understood=false if they didn't actually answer it, e.g. a question or "
        '"I don\'t know"). Put any OTHER fields they volunteered in `extra_fields`, using only '
        f"these field keys: {keys}. Set buying_intent if they signal readiness to move forward, "
        "and disqualified if they say they're not interested or already sorted."
    )


class LLMExtractor:
    """Structured extraction via Claude. Drop-in for :class:`Extractor`.

    Model defaults to the configured ``anthropic_model`` (a latency-sensitive voice step, so we
    reuse the project's chosen model rather than the heavier default). The client is injected for
    testing; in production it's created lazily from the configured API key.
    """

    def __init__(
        self,
        *,
        client: object | None = None,
        model: str | None = None,
        settings: Settings | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._model = model or self._settings.anthropic_model
        self._max_tokens = max_tokens
        self._allowed = allowed_fields()
        self._system = _build_system_prompt(self._allowed)

    def _get_client(self):
        if self._client is None:
            import anthropic  # lazy: keeps core import-light

            self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key or "")
        return self._client

    def extract(self, utterance: str, *, pending_field: str | None = None) -> Extraction:
        pending = (
            f"The pending question is about the field '{pending_field}'.\n\n"
            if pending_field
            else "There is no pending question.\n\n"
        )
        response = self._get_client().messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f'{pending}Caller said: "{utterance}"'}],
            output_format=ExtractionPayload,
        )
        payload: ExtractionPayload = response.parsed_output

        fields: dict[str, str] = {}
        if pending_field and payload.answer:
            fields[pending_field] = payload.answer
        for item in payload.extra_fields:
            if item.key in self._allowed and item.value:
                fields[item.key] = item.value

        return Extraction(
            fields=fields,
            buying_intent=payload.buying_intent,
            disqualified=payload.disqualified,
            understood=payload.understood,
        )
