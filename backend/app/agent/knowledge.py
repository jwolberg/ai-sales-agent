"""Grounded Q&A with a no-hallucination fallback (PRD KB-1, KB-4).

Answers are built *only* from retrieved approved content. When retrieval doesn't clear a
confidence bar, the agent says so honestly and offers to clarify or escalate rather than
guessing (KB-4). This module decides grounded-vs-fallback and assembles the material the
phrasing layer answers from; it never invents facts itself.
"""

from __future__ import annotations

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


def is_knowledge_question(text: str) -> bool:
    """Cheap heuristic for whether a turn is asking a question the KB might answer."""
    stripped = text.strip().lower()
    if not stripped:
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


def answer_question(
    question: str,
    *,
    retriever: KBRetriever | None = None,
    k: int = DEFAULT_K,
    min_score: float = DEFAULT_MIN_SCORE,
) -> GroundedAnswer:
    """Retrieve approved content for ``question``; ground in it or fall back honestly (KB-4)."""
    retriever = retriever or get_retriever()
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
