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
    detect_payment_intent,
    should_stop_selling,
)
from app.agent.recorder import CallRecorder
from app.db.models import Base, KPIEvent


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# --- payment intent + reconcile (PAY3-T3) ----------------------------------------------


def test_detect_payment_intent():
    assert detect_payment_intent("I'd like to pay now") == "link"
    assert detect_payment_intent("can you send me an invoice?") == "invoice"
    assert detect_payment_intent("what's the difference between SAT and ACT?") is None


def test_pay_intent_escalates_when_payments_disabled():
    # Default (flag off): pay-now still escalates exactly as before.
    assert detect_escalation("I'm ready to pay now").code == PAYMENT


def test_pay_intent_does_not_escalate_when_payments_enabled():
    # Flag on: the engine routes pay-intent to the payment flow, so it's not an escalation.
    assert detect_escalation("I'm ready to pay now", payments_enabled=True) is None


def test_card_data_always_escalates_even_when_payments_enabled():
    # PCI: we never take a card number in-call, regardless of the flag.
    assert detect_escalation("here's my card number", payments_enabled=True).code == PAYMENT
    card = detect_escalation("let me give you my credit card", payments_enabled=True)
    assert card.code == PAYMENT


# --- DE-4 escalation triggers ----------------------------------------------------------


def test_detects_each_escalation_trigger():
    assert detect_escalation("Can I just speak to a human?").code == HUMAN_REQUEST
    assert detect_escalation("I want a discount.").code == PRICE_CONCESSION
    assert detect_escalation("I'll talk to my lawyer about my privacy.").code == (
        LEGAL_SAFETY_PRIVACY
    )
    assert detect_escalation("Let me give you my credit card now.").code == PAYMENT
    assert detect_escalation("This is ridiculous, you're not listening.").code == ANGER_CONFUSION


def test_hostility_and_abuse_escalate_as_anger():
    # Real call 8b72f75c: "Shut the **** up." routed to PROGRESS and looped instead of
    # escalating. STT masks the profanity, so the surrounding phrase must trip the cue.
    assert detect_escalation("Shut the **** up.").code == ANGER_CONFUSION
    assert detect_escalation("Just shut up and answer me.").code == ANGER_CONFUSION
    assert detect_escalation("You're useless, stop talking.").code == ANGER_CONFUSION
    assert detect_escalation("This is bullshit.").code == ANGER_CONFUSION


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


# --- escalation record (DE-4 / observability) ------------------------------------------


def test_escalation_is_logged(session):
    rec = CallRecorder(session, channel="web")
    rec.record_escalation(HUMAN_REQUEST, reason="caller asked for a person")
    event = session.scalar(select(KPIEvent).where(KPIEvent.call_id == rec.call_id))
    assert event.event_type == "escalation"
    assert event.created_at is not None
    assert event.event_metadata["code"] == HUMAN_REQUEST
    assert event.event_metadata["reason"] == "caller asked for a person"
