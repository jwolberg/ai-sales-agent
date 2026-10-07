"""Vector retrieval over the KB (IR3-T2, D-15/D-17).

A drop-in for :class:`~app.kb.retriever.KBRetriever`: same ``retrieve(query, *, k, min_score) ->
list[RetrievedChunk]`` shape, so :func:`app.agent.knowledge.answer_question` can use either. The
index is built from the markdown chunker (`kb/ingest.py`), embedded with OpenAI, and persisted to
SQLite (`KBEmbedding`). Dev ranks with Python cosine over the in-memory vectors; a production
sqlite-vec backend can replace the ranking over the same rows (D-17).
"""

from __future__ import annotations

from app.db.models import KBEmbedding
from app.kb.embeddings import Embedder, cosine, deserialize_floats, serialize_floats
from app.kb.ingest import KBChunk, load_documents
from app.kb.retriever import RetrievedChunk

# Cosine threshold for "we actually have an answer" — lower than the TF-IDF default since cosine
# and TF-IDF scores aren't comparable. Tuned conservatively; revisit with real content.
DEFAULT_VECTOR_MIN_SCORE = 0.30


def build_index(session, embedder: Embedder, *, chunks: list[KBChunk] | None = None) -> int:
    """Embed KB chunks and (re)persist them to the ``kb_embeddings`` table. Returns the count."""
    chunks = chunks if chunks is not None else load_documents()
    session.query(KBEmbedding).delete()
    if not chunks:
        session.commit()
        return 0
    vectors = embedder.embed([f"{c.title}\n{c.text}" for c in chunks])
    for chunk, vec in zip(chunks, vectors, strict=True):
        session.add(
            KBEmbedding(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                title=chunk.title,
                text=chunk.text,
                model=embedder.model,
                dim=len(vec),
                embedding=serialize_floats(vec),
            )
        )
    session.commit()
    return len(chunks)


class VectorRetriever:
    """Cosine retrieval over embeddings loaded from SQLite."""

    default_min_score = DEFAULT_VECTOR_MIN_SCORE

    def __init__(self, rows: list[tuple[KBChunk, list[float]]], embedder: Embedder) -> None:
        self._rows = rows
        self._embedder = embedder

    @classmethod
    def from_session(cls, session, embedder: Embedder) -> VectorRetriever:
        rows: list[tuple[KBChunk, list[float]]] = []
        for r in session.query(KBEmbedding).all():
            chunk = KBChunk(chunk_id=r.chunk_id, source=r.source, title=r.title, text=r.text)
            rows.append((chunk, deserialize_floats(r.embedding)))
        return cls(rows, embedder)

    def __len__(self) -> int:
        return len(self._rows)

    def retrieve(
        self, query: str, *, k: int = 3, min_score: float | None = None
    ) -> list[RetrievedChunk]:
        if not self._rows or not query.strip():
            return []
        threshold = self.default_min_score if min_score is None else min_score
        qv = self._embedder.embed([query])[0]
        scored = [RetrievedChunk(chunk=chunk, score=cosine(qv, vec)) for chunk, vec in self._rows]
        hits = [s for s in scored if s.score > threshold]
        hits.sort(key=lambda r: r.score, reverse=True)
        return hits[:k]
