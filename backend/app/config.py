"""Application settings.

Secrets (API keys) come from the environment / ``backend/.env``. Non-secret tunables
(model, voice) come from the committed ``backend/config.toml``. An env var of the same
name overrides the TOML value.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict, TomlConfigSettingsSource

# Committed, non-secret tunables (resolved absolutely so cwd doesn't matter).
CONFIG_TOML = Path(__file__).resolve().parent.parent / "config.toml"


class Settings(BaseSettings):
    """Runtime configuration. Override any field via env var, .env, or config.toml."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        toml_file=CONFIG_TOML,
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # Precedence, high -> low: init args, env vars, .env, config.toml, defaults.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

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
    cartesia_voice_id: str = "a167e0f3-df7e-4d52-a9c3-f949145efdab"
    # jaqueline 9626c31c-bec5-4cca-baa8-f8ba9e84c8bc
    # ronald 5ee9feff-1265-424a-9d7f-8e4d431a12c7
    # caroline f9836c6e-a0bd-460e-9d3c-f7299fa60f94
    # blake  a167e0f3-df7e-4d52-a9c3-f949145efdab
    # brook e07c00bc-4134-4eae-9ea4-1a55fb45746b

    # Agent persona identity. Set the live values in config.toml (these are fallbacks).
    agent_name: str = "Jay"
    company_name: str = "Nerdy"
    # When true, log inbound audio / VAD / transcription to the server console (debug).
    voice_debug: bool = False

    # --- Latency / audio realism (P4.5-T6) ---
    # Transport output sample rate. The ambient bed (data/audio/ambient.wav) must match this —
    # SoundfileMixer does not resample.
    audio_out_sample_rate: int = 24000
    # Speak a short filler ("Sure," / "Let me check on that…") while the real reply is computed,
    # so the call never falls silent (AGENT_FLOW §5.10).
    fillers: bool = True
    # Mix a looping ambient room-tone bed under the agent's voice (output-only). Needs
    # data/audio/ambient.wav and the `soundfile` dep; off by default.
    ambient_noise: bool = False
    ambient_volume: float = 0.15  # 0.0-1.0; keep subtle

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
