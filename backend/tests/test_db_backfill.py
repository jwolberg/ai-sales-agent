"""The additive-column self-heal (VAD-T3, generalized): create_all never ALTERs existing tables and
this project has no migration tool, so init_db backfills any column the models define but an old
table is missing (e.g. turns.latency_breakdown, calls.vad_params).
"""

from sqlalchemy import create_engine, inspect, text

from app.db.session import _backfill_columns


def test_backfill_adds_missing_columns_to_existing_sqlite_table():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Simulate an older DB: a calls table that predates several columns.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE calls (call_id TEXT PRIMARY KEY)"))

    _backfill_columns(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("calls")}
    assert {"vad_params", "channel", "reached_leaf"} <= cols  # all model columns are healed


def test_backfill_heals_turns_latency_breakdown_drift():
    """Regression: the committed dev DB lacked turns.latency_breakdown (added in LAT-T1 with no
    migration), which 500'd /api/calls until the self-heal covered it generically."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        # A turns table from before latency_breakdown existed.
        conn.execute(text("CREATE TABLE turns (turn_id TEXT PRIMARY KEY, call_id TEXT, text TEXT)"))

    _backfill_columns(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("turns")}
    assert "latency_breakdown" in cols


def test_backfill_is_idempotent_and_skips_absent_tables():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # No tables at all → must not raise (create_all will make them fresh).
    _backfill_columns(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE calls (call_id TEXT PRIMARY KEY, vad_params JSON)"))
    # Already-present columns → second run is a no-op (no error).
    _backfill_columns(engine)
    _backfill_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("calls")}
    assert "vad_params" in cols
