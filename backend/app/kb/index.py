"""Build the KB vector index (IR3-T2 CLI).

Embeds the approved markdown chunks (``data/kb/*.md``) with OpenAI and persists the vectors to the
``kb_embeddings`` table, so ``knowledge.answer_question`` uses semantic retrieval instead of the
TF-IDF fallback. Re-run after editing KB content.

    python -m app.kb.index

Requires ``OPENAI_API_KEY``. Without it the retriever stays on TF-IDF, so the index is optional.
"""

from __future__ import annotations

from app.db.session import SessionLocal, init_db
from app.kb.embeddings import get_embedder
from app.kb.vector_retriever import build_index


def main() -> None:
    embedder = get_embedder()
    if embedder is None:
        print("No OPENAI_API_KEY configured — skipping index (TF-IDF fallback stays active).")
        return
    init_db()
    with SessionLocal() as session:
        count = build_index(session, embedder)
    print(f"Indexed {count} KB chunks with {embedder.model} into kb_embeddings.")


if __name__ == "__main__":
    main()
