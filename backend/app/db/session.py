"""Database engine, session factory, and schema bootstrap."""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _engine_kwargs(database_url: str) -> dict:
    """SQLite needs check_same_thread disabled for use across FastAPI threads."""
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


settings = get_settings()
engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that always closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after a table first shipped. create_all() never ALTERs existing tables and this
# project has no migration tool, so we additively backfill these on SQLite to keep an existing
# committed DB working. {table: {column: SQL type}}. Keep entries forever — it's idempotent.
_ADDED_COLUMNS = {
    "calls": {"vad_params": "JSON"},  # VAD-T3
}


def _backfill_columns(target_engine=None) -> None:
    """Add any missing additive columns to existing SQLite tables (no-op if already present)."""
    target_engine = target_engine or engine
    if not target_engine.url.get_backend_name().startswith("sqlite"):
        return
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    with target_engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all will make it fresh with all columns
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def init_db() -> None:
    """Create all tables. Safe to call repeatedly (no-op if they exist)."""
    # Import models so they register on Base.metadata before create_all.
    from app.db import models  # noqa: F401
    from app.db.models import Base

    Base.metadata.create_all(bind=engine)
    _backfill_columns()
