"""IntentRouterEngine tests (IR2-T3) — brain-driven turn loop + persistence."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.agent.contract import BrainDecision, RouterAction
from app.agent.intent_engine import IntentRouterEngine
from app.agent.recorder import CallRecorder
from app.config import Settings
from app.db.models import Base, Call, Decision, KPIEvent, Turn
from app.kpis import events as kpi


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _engine(session, brain=None):
    return IntentRouterEngine(
        brain=brain or RuleBrain(Settings(_env_file=None)),
        recorder=CallRecorder(session, channel="sim:test", is_synthetic=True),
        settings=Settings(_env_file=None),
    )


def test_classify_then_quote_persists_trace_and_result(session):
    eng = _engine(session)
    eng.open()
    result = eng.run_turn("I need help with chemistry")
    assert result.action is RouterAction.QUOTE
    assert result.leaf == "tutoring/science/chemistry"
    eng.end(outcome="completed")

    call = session.scalar(select(Call))
    assert call.reached_leaf == "tutoring/science/chemistry"
    assert call.quoted_price == 80.0

    decisions = session.scalars(select(Decision).where(Decision.call_id == call.call_id)).all()
    quote_decision = [d for d in decisions if d.selected_action == "quote"]
    assert quote_decision and quote_decision[0].leaf == "tutoring/science/chemistry"
    assert quote_decision[0].slots.get("subject") == "chemistry"

    # transcript captured (greeting + prospect + agent reply)
    turns = session.scalars(select(Turn).where(Turn.call_id == call.call_id)).all()
    assert len(turns) >= 3


def test_leaf_reached_kpi_emitted_once(session):
    eng = _engine(session)
    eng.run_turn("I want to prep for the SAT")
    events = session.scalars(select(KPIEvent).where(KPIEvent.event_type == kpi.LEAF_REACHED)).all()
    assert len(events) == 1
    assert events[0].event_metadata["leaf"] == "test_prep/SAT"


def test_low_confidence_asks_to_repeat_without_brain(session):
    eng = _engine(session)
    result = eng.run_turn("garbled", confidence=0.2)
    assert result.action is RouterAction.ASK
    assert "say that again" in result.utterance.lower()
    # no decision row written for a non-acted turn
    assert not session.scalars(select(Decision)).all()


class _MisQuoteBrain:
    """A brain that illegally states a price it never authorized (quoted_amount=None)."""

    def decide(self, *, history, lead_fields=None, slots=None):
        return BrainDecision(
            action=RouterAction.QUOTE,
            utterance="Sure, I can do $40 an hour for you.",
            reason="oops",
            slots={"category": "tutoring", "subject_area": "math", "subject": "algebra"},
            leaf="tutoring/math/algebra",
            quoted_amount=None,  # NOT authorized
        )


def test_mis_quote_is_blocked_and_substituted(session):
    eng = _engine(session, brain=_MisQuoteBrain())
    result = eng.run_turn("how much for algebra?")
    assert result.action is RouterAction.ESCALATE
    assert "$40" not in result.utterance
    blocked = session.scalars(
        select(KPIEvent).where(KPIEvent.event_type == kpi.MIS_QUOTE_BLOCKED)
    ).all()
    assert len(blocked) == 1
