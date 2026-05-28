"""KB embeddings — OpenAI vectors + cosine helpers (IR3-T1, D-15/D-17).

The embedding *generation* is OpenAI `text-embedding-3-small`; the *store* is the existing SQLite
DB (`KBEmbedding`), and dev ranking is Python cosine (the corpus is tiny). Vectors serialize to a
little-endian float32 byte string so a production sqlite-vec index can read the same bytes.

`get_embedder` returns ``None`` when no OpenAI key is configured, so callers fall back to the
TF-IDF retriever offline.
"""

from __future__ import annotations

import math
import struct
from typing import Protocol

from app.config import Settings, get_settings


def serialize_floats(vec: list[float]) -> bytes:
    """Pack a vector to little-endian float32 bytes (sqlite-vec compatible)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def deserialize_floats(blob: bytes) -> list[float]:
    """Unpack a little-endian float32 byte string to a list of floats."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 if either vector is zero-length/empty."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """OpenAI embeddings (batched)."""

    def __init__(self, settings: Settings | None = None, *, client=None) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.openai_embedding_model
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


def get_embedder(settings: Settings | None = None) -> Embedder | None:
    """Return an embedder when OpenAI is configured, else None (offline -> TF-IDF fallback)."""
    settings = settings or get_settings()
    if settings.openai_enabled:
        return OpenAIEmbedder(settings)
    return None
