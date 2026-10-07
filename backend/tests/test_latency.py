"""End-to-end turn-latency breakdown (LAT-T1): helper math + recorder + metrics rollup."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.latency import compose_turn_latency
from app.agent.recorder import CallRecorder
from app.db.models import Base
from app.kpis.metrics import compute_router_metrics


def test_compose_turn_latency_full():
    # user stops at t=10.0, STT final at 10.3, brain done at 11.1, audio out at 11.4.
    total, breakdown = compose_turn_latency(
        user_stopped_at=10.0, transcript_at=10.3, brain_done_at=11.1, bot_started_at=11.4
    )
    assert breakdown == {"stt_ms": 300.0, "brain_ms": 800.0, "tts_ms": 300.0}
    assert total == 1400.0  # user_stopped -> bot_started


def test_compose_turn_latency_without_vad_stop_falls_back_to_transcript():
    total, breakdown = compose_turn_latency(
        user_stopped_at=None, transcript_at=10.3, brain_done_at=11.1, bot_started_at=11.4
    )
    assert breakdown["stt_ms"] is None
    assert total == 1100.0  # transcript -> bot_started


def test_compose_turn_latency_missing_audio_is_none():
    total, breakdown = compose_turn_latency(
        user_stopped_at=10.0, transcript_at=10.3, brain_done_at=11.1, bot_started_at=None
    )
    assert total is None and breakdown["tts_ms"] is None


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_update_turn_latency_and_metrics_rollup(session):
    rec = CallRecorder(session, channel="web")
    turn = rec.record_agent("Hi there.", latency_ms=800.0)  # brain-only at first
    rec.update_turn_latency(
        turn.turn_id,
        latency_ms=1400.0,
        breakdown={"stt_ms": 300.0, "brain_ms": 800.0, "tts_ms": 300.0},
    )

    from app.db.models import Turn

    stored = session.get(Turn, turn.turn_id)
    assert stored.latency_ms == 1400.0  # overwritten with end-to-end
    assert stored.latency_breakdown["tts_ms"] == 300.0

    m = compute_router_metrics(session)
    assert m["turn_latency_ms_p50"] == 1400.0
    assert m["turn_latency_breakdown_ms"] == {"stt": 300.0, "brain": 800.0, "tts": 300.0}
