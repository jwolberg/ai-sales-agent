"""Config tests — OpenAI brain/embedding settings (IR0-T2)."""

from app.config import Settings


def test_openai_defaults_present():
    s = Settings(_env_file=None)
    assert s.openai_embedding_model == "text-embedding-3-small"
    assert s.openai_chat_model  # a non-empty default chat model
    # App must boot without an OpenAI key (offline fallback path).
    assert s.openai_api_key is None
    assert s.openai_enabled is False


def test_openai_enabled_when_key_set():
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.openai_enabled is True


def test_missing_voice_keys_unaffected():
    s = Settings(_env_file=None)
    # OpenAI is not a *voice* key; the voice readiness check is unchanged.
    assert set(s.missing_voice_keys()) == {
        "DEEPGRAM_API_KEY",
        "ANTHROPIC_API_KEY",
        "CARTESIA_API_KEY",
    }
