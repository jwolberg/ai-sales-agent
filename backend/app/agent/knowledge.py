"""Grounded Q&A with a no-hallucination fallback (PRD KB-1, KB-4).

Answers are built *only* from retrieved approved content. When retrieval doesn't clear a
confidence bar, the agent says so honestly and offers to clarify or escalate rather than
guessing (KB-4). This module decides grounded-vs-fallback and assembles the material the
phrasing layer answers from; it never invents facts itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.kb.retriever import KBRetriever, get_retriever

# Minimum retrieval score to treat the KB as actually covering the question. Tuned to the
# current placeholder corpus (relevant queries score ~0.5+, off-topic ~0.37/none); revisit
# when approved content lands.
DEFAULT_MIN_SCORE = 0.45
DEFAULT_K = 3

FALLBACK_MESSAGE = (
    "I want to make sure I give you accurate information on that, and I don't have it in "
    "front of me right now. I can connect you with a specialist who can confirm the details "
    "— would that help?"
)

_QUESTION_WORDS = frozenset(
    "how what when where which who whom whose why can could do does is are will would "
    "should".split()
)

# Social pleasantries and connectivity checks. These are grammatically questions ("how's it
# going?", "can you hear me?") but they ask nothing the KB answers — routing them to a KB lookup
# produces the §18 "let me connect you with a specialist" deferral on, e.g., the opening turn
# (real call ea6c68d9). They are *not* knowledge questions; the router lets them fall through to
# PROGRESS (acknowledge + advance discovery).
_PLEASANTRY_PHRASES = (
    "how's it going", "hows it going", "how is it going", "how are you", "how are ya",
    "how ya doing", "how you doing", "how're you", "how's your day", "hows your day",
    "how's everything", "hows everything", "what's up", "whats up", "how have you been",
    "nice to meet you", "good to meet you", "pleasure to meet you", "can you hear me",
    "are you there", "you there", "you still there", "still there", "good morning",
    "good afternoon", "good evening",
)
# Pure-greeting / acknowledgment tokens; a turn made only of these (plus a couple connectors) is
# small talk, not a question.
_GREETING_TOKENS = frozenset("hi hey hello yo hiya howdy thanks thank".split())
_GREETING_CONNECTORS = frozenset("there again you so and how doing".split())


def is_social_pleasantry(text: str) -> bool:
    """True for greetings, pleasantries, and connectivity checks — small talk that looks like a
    question but isn't one the KB can answer."""
    stripped = text.strip().lower()
    if not stripped:
        return False
    if any(phrase in stripped for phrase in _PLEASANTRY_PHRASES):
        return True
    words = re.findall(r"[a-z']+", stripped)
    return bool(words) and all(
        w in _GREETING_TOKENS or w in _GREETING_CONNECTORS for w in words
    )


def is_knowledge_question(text: str) -> bool:
    """Cheap heuristic for whether a turn is asking a question the KB might answer.

    A social pleasantry ("how's it going?") is never a knowledge question even though it's
    question-shaped — otherwise the opening turn gets a KB deferral (real call ea6c68d9)."""
    stripped = text.strip().lower()
    if not stripped:
        return False
    if is_social_pleasantry(text):
        return False
    if "?" in stripped:
        return True
    return stripped.split()[0] in _QUESTION_WORDS


@dataclass
class GroundedAnswer:
    """The result of a KB lookup: either grounded snippets+sources, or an honest fallback."""

    grounded: bool
    sources: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)
    fallback: str | None = None


def get_default_retriever():
    """Prefer the OpenAI-embedding vector retriever when it's available and populated; otherwise
    fall back to the dependency-free TF-IDF retriever (offline / no key / empty index)."""
    try:
        from app.db.session import SessionLocal
        from app.kb.embeddings import get_embedder
        from app.kb.vector_retriever import VectorRetriever

        embedder = get_embedder()
        if embedder is not None:
            with SessionLocal() as session:
                vr = VectorRetriever.from_session(session, embedder)
            if len(vr) > 0:
                return vr
    except Exception:
        # Any setup problem (no table, DB error, etc.) -> safe lexical fallback.
        pass
    return get_retriever()


def answer_question(
    question: str,
    *,
    retriever: KBRetriever | None = None,
    k: int = DEFAULT_K,
    min_score: float | None = None,
) -> GroundedAnswer:
    """Retrieve approved content for ``question``; ground in it or fall back honestly (KB-4)."""
    retriever = retriever or get_default_retriever()
    if min_score is None:
        min_score = getattr(retriever, "default_min_score", DEFAULT_MIN_SCORE)
    hits = retriever.retrieve(question, k=k, min_score=min_score)
    if not hits:
        return GroundedAnswer(grounded=False, fallback=FALLBACK_MESSAGE)

    sources: list[str] = []
    for hit in hits:  # unique sources, best-first order (KB-3)
        if hit.source not in sources:
            sources.append(hit.source)
    return GroundedAnswer(
        grounded=True,
        sources=sources,
        snippets=[hit.chunk.text for hit in hits],
    )


def grounding_prompt(answer: GroundedAnswer) -> str:
    """Instruction for the phrasing layer to answer from the retrieved material only."""
    material = "\n\n".join(answer.snippets)
    return (
        "Answer the caller's question using ONLY this approved information, briefly and in a "
        "natural spoken style. If it doesn't fully cover the question, say what you can and "
        f"offer to connect them with a specialist.\n\n{material}"
    )
