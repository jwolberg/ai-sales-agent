"""Vector retriever tests (IR3-T2) — build index + cosine ranking with a fake embedder."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.knowledge import get_default_retriever
from app.kb.ingest import KBChunk
from app.kb.retriever import KBRetriever
from app.kb.vector_retriever import VectorRetriever, build_index


class _FakeEmbedder:
    """Deterministic bag-of-vocab embedding so cosine ranking is testable offline."""

    model = "fake-embed"
    VOCAB = ("sat", "act", "chemistry", "tutoring", "price")

    def embed(self, texts):
        return [[float(t.lower().count(w)) for w in self.VOCAB] for t in texts]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.db.models import Base

    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


_CHUNKS = [
    KBChunk(chunk_id="sat#0", source="sat.md", title="SAT", text="The SAT is a college test."),
    KBChunk(
        chunk_id="chem#0",
        source="chem.md",
        title="Chemistry",
        text="Chemistry tutoring covers reactions and bonding.",
    ),
]


def test_build_index_persists_rows(session):
    n = build_index(session, _FakeEmbedder(), chunks=_CHUNKS)
    assert n == 2
    # rebuild replaces rather than duplicates
    assert build_index(session, _FakeEmbedder(), chunks=_CHUNKS) == 2


def test_build_index_empty(session):
    assert build_index(session, _FakeEmbedder(), chunks=[]) == 0


def test_vector_retriever_ranks_relevant_chunk_first(session):
    build_index(session, _FakeEmbedder(), chunks=_CHUNKS)
    vr = VectorRetriever.from_session(session, _FakeEmbedder())
    assert len(vr) == 2
    hits = vr.retrieve("tell me about the SAT", k=1)
    assert hits and hits[0].source == "sat.md"


def test_vector_retriever_returns_nothing_for_offtopic(session):
    build_index(session, _FakeEmbedder(), chunks=_CHUNKS)
    vr = VectorRetriever.from_session(session, _FakeEmbedder())
    # "price" is in the vocab but neither chunk mentions it -> cosine 0 -> below threshold
    assert vr.retrieve("what is the price of pizza", k=3) == []


def test_get_default_retriever_falls_back_to_tfidf_without_embedder(monkeypatch):
    # With no embedder available, retrieval must fall back to TF-IDF — regardless of whether the
    # dev env happens to have an OpenAI key + a built index.
    import app.kb.embeddings as emb

    monkeypatch.setattr(emb, "get_embedder", lambda *a, **k: None)
    assert isinstance(get_default_retriever(), KBRetriever)
