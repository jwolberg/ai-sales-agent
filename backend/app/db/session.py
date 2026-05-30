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


def _backfill_columns(target_engine=None) -> None:
    """Add any column the models define but an existing SQLite table is missing.

    create_all() never ALTERs existing tables and this project has no migration tool, so a DB
    created before a column was added (e.g. turns.latency_breakdown, calls.vad_params) raises
    "no such column" at query time. This additively heals such drift: for every model table that
    already exists, ADD COLUMN each missing column as a plain nullable, typed column. We emit only
    the type (no FK/PK/constraints) — that's all SQLite's ALTER ADD COLUMN reliably supports, and
    it's enough to keep an old dev DB queryable. Fresh DBs get full schemas from create_all.
    Idempotent and self-maintaining (no hardcoded column list to keep in sync).
    """
    target_engine = target_engine or engine
    if not target_engine.url.get_backend_name().startswith("sqlite"):
        return
    from app.db.models import Base

    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    with target_engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if table.name not in existing_tables:
                continue  # create_all will make it fresh with all columns
            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in present:
                    col_type = column.type.compile(dialect=target_engine.dialect)
                    conn.execute(
                        text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}")
                    )


def init_db() -> None:
    """Create all tables. Safe to call repeatedly (no-op if they exist)."""
    # Import models so they register on Base.metadata before create_all.
    from app.db import models  # noqa: F401
    from app.db.models import Base

    Base.metadata.create_all(bind=engine)
    _backfill_columns()
