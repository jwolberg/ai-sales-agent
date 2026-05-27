"""Application settings loaded from the environment (and an optional .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Override any field via env var or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Autonomous AI Sales Agent"
    environment: str = "development"
    # SQLite single-file DB by default; swap to a Postgres URL in production.
    database_url: str = "sqlite:///./nerdy_sales.db"
    log_level: str = "INFO"

    # --- Voice pipeline (Phase 2) ---
    # Provider API keys. Optional so the core app boots without them; the voice
    # endpoint returns a clear 503 until all three are set.
    deepgram_api_key: str | None = None   # STT
    anthropic_api_key: str | None = None  # LLM (Claude)
    cartesia_api_key: str | None = None   # TTS
    # Tunables (override via env). Default to a capable Claude model; switch to
    # claude-haiku-4-5 for lower latency if needed.
    anthropic_model: str = "claude-sonnet-4-6"
    cartesia_voice_id: str = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

    def missing_voice_keys(self) -> list[str]:
        """Return the env-var names of any unset voice provider keys."""
        required = {
            "DEEPGRAM_API_KEY": self.deepgram_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "CARTESIA_API_KEY": self.cartesia_api_key,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the env is read once per process."""
    return Settings()
