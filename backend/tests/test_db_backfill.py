"""The additive-column self-heal (VAD-T3): create_all never ALTERs existing tables and this
project has no migration tool, so init_db backfills columns added after a table first shipped.
"""

from sqlalchemy import create_engine, inspect, text

from app.db.session import _backfill_columns


def test_backfill_adds_missing_column_to_existing_sqlite_table():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Simulate an older DB: a calls table that predates the vad_params column.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE calls (call_id TEXT PRIMARY KEY)"))

    _backfill_columns(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("calls")}
    assert "vad_params" in cols


def test_backfill_is_idempotent_and_skips_absent_tables():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # No tables at all → must not raise.
    _backfill_columns(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE calls (call_id TEXT PRIMARY KEY, vad_params JSON)"))
    # Column already present → second run is a no-op.
    _backfill_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("calls")}
    assert "vad_params" in cols
