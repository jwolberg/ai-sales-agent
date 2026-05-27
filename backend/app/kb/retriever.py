"""Grounded retrieval over the knowledge base (PRD KB-1, KB-3).

A dependency-free lexical retriever: it scores KB chunks against a query with TF-IDF
and returns the top matches with their source ids and a score. Deterministic and cheap
(no embedding model or API), which suits a small approved-doc set and keeps tests stable;
swap in a vector store later if recall demands it. The score gates the "do we actually
have an answer?" decision in P4-T2 (KB-4 no-hallucination fallback).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from app.kb.ingest import KBChunk, load_documents

_TOKEN = re.compile(r"[a-z0-9]+")
# Very common words carry no retrieval signal; drop them so scores reflect content terms.
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how i in is it of on or our that the "
    "this to we what when where which who will with you your".split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclass(frozen=True)
class RetrievedChunk:
    """A KB chunk and its relevance score for a query."""

    chunk: KBChunk
    score: float

    @property
    def source(self) -> str:
        return self.chunk.source


class KBRetriever:
    """TF-IDF retrieval over a fixed set of KB chunks."""

    def __init__(self, chunks: list[KBChunk]) -> None:
        self._chunks = chunks
        self._chunk_tokens = [_tokenize(f"{c.title} {c.text}") for c in chunks]
        self._n = len(chunks)
        document_freq: Counter[str] = Counter()
        for tokens in self._chunk_tokens:
            document_freq.update(set(tokens))
        self._df = document_freq

    def _idf(self, term: str) -> float:
        # Smoothed idf; rarer terms across the corpus weigh more.
        return math.log(1 + self._n / (1 + self._df.get(term, 0)))

    def retrieve(self, query: str, *, k: int = 3, min_score: float = 0.0) -> list[RetrievedChunk]:
        """Return up to ``k`` chunks scoring above ``min_score``, best first."""
        query_terms = _tokenize(query)
        if not query_terms:
            return []
        results: list[RetrievedChunk] = []
        for chunk, tokens in zip(self._chunks, self._chunk_tokens, strict=True):
            if not tokens:
                continue
            term_freq = Counter(tokens)
            raw = sum(term_freq[t] * self._idf(t) for t in query_terms)
            # Length-normalize so long chunks don't dominate purely by size.
            score = raw / math.sqrt(len(tokens))
            if score > min_score:
                results.append(RetrievedChunk(chunk=chunk, score=score))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]


@lru_cache
def get_retriever() -> KBRetriever:
    """Return the process-wide retriever over the default KB directory (built once)."""
    return KBRetriever(load_documents())
