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


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the env is read once per process."""
    return Settings()
