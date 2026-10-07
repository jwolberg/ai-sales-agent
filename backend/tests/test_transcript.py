"""Tests for transcript & call-record capture (P2-T4)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.recorder import (
    OUTCOME_COMPLETED,
    SPEAKER_AGENT,
    SPEAKER_PROSPECT,
    CallRecorder,
)
from app.db.models import Base, Call, Lead, Turn


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _turns_in_order(session, call_id) -> list[Turn]:
    return list(
        session.scalars(select(Turn).where(Turn.call_id == call_id).order_by(Turn.timestamp))
    )


def test_recorder_persists_call_and_ordered_transcript(session):
    lead = Lead(contact_name="Sarah")
    session.add(lead)
    session.flush()

    rec = CallRecorder(session, lead_id=lead.lead_id, channel="web")
    call_id = rec.call_id
    assert call_id  # Call row created and flushed immediately

    base = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    rec.record_agent("Hi Sarah, this is Jay from Acme Tutoring.", timestamp=base)
    rec.record_prospect("I need math help for my daughter.", timestamp=base + timedelta(seconds=4))
    rec.record_agent("Got it — what grade is she in?", timestamp=base + timedelta(seconds=7))
    rec.end(outcome=OUTCOME_COMPLETED, summary="Parent seeking middle-school math help.")

    loaded = session.scalar(select(Call).where(Call.call_id == call_id))
    assert loaded.lead_id == lead.lead_id
    assert loaded.channel == "web"
    assert loaded.is_synthetic is False
    assert loaded.ended_at is not None and loaded.ended_at >= loaded.started_at
    assert loaded.outcome == OUTCOME_COMPLETED
    assert loaded.summary == "Parent seeking middle-school math help."

    turns = _turns_in_order(session, call_id)
    assert [(t.speaker, t.text) for t in turns] == [
        (SPEAKER_AGENT, "Hi Sarah, this is Jay from Acme Tutoring."),
        (SPEAKER_PROSPECT, "I need math help for my daughter."),
        (SPEAKER_AGENT, "Got it — what grade is she in?"),
    ]


def test_synthetic_flag_is_recorded(session):
    rec = CallRecorder(session, channel="simulator", is_synthetic=True)
    rec.record_agent("Hello.")
    rec.end()
    loaded = session.scalar(select(Call).where(Call.call_id == rec.call_id))
    assert loaded.is_synthetic is True
    assert loaded.ended_at is not None


def test_engine_drives_a_recorded_call(session):
    # The intent-router engine drives a recorded call end-to-end (replaces the old orchestrator
    # transcript test). Greeting + a classifying turn produce ordered turns + a decision trace.
    from app.agent.brain import RuleBrain
    from app.agent.intent_engine import IntentRouterEngine
    from app.config import Settings

    rec = CallRecorder(session, channel="web")
    eng = IntentRouterEngine(
        brain=RuleBrain(Settings(_env_file=None)), recorder=rec, settings=Settings(_env_file=None)
    )
    eng.open()
    eng.run_turn("I need help with chemistry.")
    eng.end(outcome=OUTCOME_COMPLETED)

    loaded = session.scalar(select(Call).where(Call.call_id == rec.call_id))
    assert loaded.outcome == OUTCOME_COMPLETED
    assert loaded.ended_at is not None
    assert loaded.reached_leaf == "tutoring/science/chemistry"

    turns = _turns_in_order(session, rec.call_id)
    # greeting + prospect + agent reply
    assert len(turns) == 3
    assert sum(t.speaker == SPEAKER_PROSPECT for t in turns) == 1
    assert sum(t.speaker == SPEAKER_AGENT for t in turns) == 2
