"""Tests for KB ingestion & retrieval (P4-T1)."""

from app.kb.ingest import KBChunk, load_documents
from app.kb.retriever import KBRetriever, get_retriever


def test_documents_load_and_chunk_with_sources():
    chunks = load_documents()
    assert chunks, "expected KB docs under data/kb/"
    # Every chunk is attributed to a source file and a section title (KB-3).
    assert all(c.source.endswith(".md") for c in chunks)
    assert all(c.title and c.text for c in chunks)
    # PLACEHOLDER HTML comments are stripped from chunk text.
    assert all("<!--" not in c.text for c in chunks)
    # Pricing doc is split into sections (e.g. "How pricing works", "Discounts").
    pricing_titles = [c.title for c in chunks if c.source == "pricing.md"]
    assert any("Discounts" in t for t in pricing_titles)


def test_retrieval_finds_the_relevant_source():
    r = get_retriever()
    top = r.retrieve("how much does it cost and can I get a discount?", k=3)
    assert top, "expected at least one match"
    assert top[0].source == "pricing.md"
    assert top[0].score > 0


def test_retrieval_ranks_matching_topic_first():
    r = get_retriever()
    assert r.retrieve("how do you match my child with a tutor?")[0].source == (
        "tutoring_formats_and_matching.md"
    )
    assert r.retrieve("what times can we schedule sessions?")[0].source == "scheduling.md"


def test_retrieval_is_empty_for_no_query_signal():
    r = get_retriever()
    assert r.retrieve("the and of to") == []  # all stopwords
    assert r.retrieve("") == []


def test_min_score_filters_weak_matches():
    chunks = [
        KBChunk("a#0", "a.md", "Pricing", "pricing depends on the plan and frequency"),
        KBChunk("b#0", "b.md", "Scheduling", "weekday evenings and weekends work well"),
    ]
    retriever = KBRetriever(chunks)
    assert retriever.retrieve("pricing plan", min_score=0.0)
    assert retriever.retrieve("pricing plan", min_score=10_000) == []
