"""Embedding helper tests (IR3-T1) — serialize roundtrip + cosine + factory."""

from app.config import Settings
from app.kb.embeddings import (
    OpenAIEmbedder,
    cosine,
    deserialize_floats,
    get_embedder,
    serialize_floats,
)


def test_serialize_roundtrip_float32():
    vec = [0.1, -0.5, 1.0, 0.0, 123.5]
    out = deserialize_floats(serialize_floats(vec))
    assert len(out) == len(vec)
    for a, b in zip(out, vec, strict=True):
        assert abs(a - b) < 1e-5


def test_cosine_identity_orthogonal_and_empty():
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine([], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_get_embedder_offline_returns_none():
    assert get_embedder(Settings(_env_file=None)) is None
    assert isinstance(get_embedder(Settings(_env_file=None, openai_api_key="sk-x")), OpenAIEmbedder)


class _FakeOpenAIClient:
    """Mimics client.embeddings.create -> resp.data[i].embedding."""

    class _Embeddings:
        def create(self, model, input):
            from types import SimpleNamespace

            data = [SimpleNamespace(embedding=[float(len(t)), 1.0]) for t in input]
            return SimpleNamespace(data=data)

    def __init__(self):
        self.embeddings = self._Embeddings()


def test_openai_embedder_batches_with_fake_client():
    emb = OpenAIEmbedder(
        Settings(_env_file=None, openai_api_key="sk-x"), client=_FakeOpenAIClient()
    )
    out = emb.embed(["ab", "cde"])
    assert out == [[2.0, 1.0], [3.0, 1.0]]
    assert emb.embed([]) == []
