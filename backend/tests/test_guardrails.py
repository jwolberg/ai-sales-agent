"""Tests for guardrails & escalation criteria (P4-T4)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.guardrails import (
    ANGER_CONFUSION,
    CLAIMS_HUMAN,
    HUMAN_REQUEST,
    LEGAL_SAFETY_PRIVACY,
    LOW_CONFIDENCE,
    PAYMENT,
    PRICE_CONCESSION,
    PROMISES_GUARANTEE,
    QUOTES_PRICE,
    check_agent_output,
    detect_escalation,
    should_stop_selling,
)
from app.agent.orchestrator import Orchestrator
from app.agent.recorder import CallRecorder
from app.agent.stages import Action, Stage
from app.config import Settings
from app.db.models import Base, KPIEvent


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# --- DE-4 escalation triggers ----------------------------------------------------------

def test_detects_each_escalation_trigger():
    assert detect_escalation("Can I just speak to a human?").code == HUMAN_REQUEST
    assert detect_escalation("I want a discount.").code == PRICE_CONCESSION
    assert detect_escalation("I'll talk to my lawyer about my privacy.").code == (
        LEGAL_SAFETY_PRIVACY
    )
    assert detect_escalation("Let me give you my credit card now.").code == PAYMENT
    assert detect_escalation("This is ridiculous, you're not listening.").code == ANGER_CONFUSION


def test_low_confidence_triggers_escalation():
    assert detect_escalation("tell me more", confidence=0.2).code == LOW_CONFIDENCE
    assert detect_escalation("tell me more", confidence=0.9) is None
    assert detect_escalation("tell me more") is None  # no confidence given, no cue


def test_human_request_takes_priority_over_price_cue():
    # Both a human request and a discount mention -> human request wins (priority order).
    assert detect_escalation("I want a human, not a discount bot").code == HUMAN_REQUEST


# --- §18 stop-after-refusal & output guardrails ----------------------------------------

def test_should_stop_selling_on_clear_refusal():
    assert should_stop_selling("I'm really not interested, please stop calling.")
    assert not should_stop_selling("Tell me more about how it works.")


def test_check_agent_output_flags_prohibited_speech():
    assert CLAIMS_HUMAN in check_agent_output("Don't worry, I'm a real person.")
    assert QUOTES_PRICE in check_agent_output("It's just $40 per session.")
    assert PROMISES_GUARANTEE in check_agent_output("We guarantee her grades will improve.")
    assert check_agent_output("Happy to help you find the right tutor.") == []


# --- orchestrator wiring ---------------------------------------------------------------

def test_orchestrator_check_escalation_emits_escalate_action():
    orch = Orchestrator(settings=Settings(_env_file=None))
    assert orch.check_escalation("what grade is she in?") is None

    action = orch.check_escalation("Please connect me with a human.")
    assert action.stage is Stage.ESCALATION
    assert action.action is Action.ESCALATE
    assert action.escalation_risk == "high"
    assert action.question_key == HUMAN_REQUEST
    assert action.prompt  # the handoff line


def test_orchestrator_exposes_stop_selling():
    orch = Orchestrator(settings=Settings(_env_file=None))
    assert orch.should_stop_selling("no thanks, remove me from your list")


# --- escalation record (DE-4 / observability) ------------------------------------------

def test_escalation_is_logged(session):
    rec = CallRecorder(session, channel="web")
    rec.record_escalation(HUMAN_REQUEST, reason="caller asked for a person")
    event = session.scalar(select(KPIEvent).where(KPIEvent.call_id == rec.call_id))
    assert event.event_type == "escalation"
    assert event.created_at is not None
    assert event.event_metadata["code"] == HUMAN_REQUEST
    assert event.event_metadata["reason"] == "caller asked for a person"
