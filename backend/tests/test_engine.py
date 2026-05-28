"""Tests for the conversation engine — the decider-led runtime (P4.5-T4)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.decisioning import DiscoveryDecider
from app.agent.discovery import get_discovery_playbook
from app.agent.engine import ConversationEngine
from app.agent.orchestrator import Orchestrator
from app.agent.recorder import CallRecorder
from app.agent.router import Route
from app.agent.stages import Action, Modifier, Stage
from app.config import Settings
from app.db.models import Base, Decision, Turn

_REQUIRED = [q.key for q in get_discovery_playbook().required]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _engine(session, **orch_kwargs):
    orch = Orchestrator(
        settings=Settings(_env_file=None, agent_name="Jay", company_name="Nerdy"),
        decider=DiscoveryDecider(),
        recorder=CallRecorder(session, channel="text"),
        **orch_kwargs,
    )
    return ConversationEngine(orch)


def test_open_greets_and_records(session):
    eng = _engine(session)
    greeting = eng.open()
    assert "Jay" in greeting and "Nerdy" in greeting
    assert eng.state.stage is Stage.GREETING


def test_progress_turn_extracts_and_asks_next(session):
    eng = _engine(session)
    eng.open()
    # No pending question after the greeting, so the first turn just makes the agent ask
    # the first required question (rule-based extraction only fills a *pending* slot).
    eng.run_turn("Hi there")
    assert eng.state.pending_field == "relationship_to_student"
    # Answering the pending question gets captured.
    result = eng.run_turn("I'm the parent")
    assert "relationship_to_student" in eng.state.collected_fields
    assert result.route is Route.PROGRESS
    assert result.action.action in {Action.ASK_REQUIRED_DISCOVERY, Action.ASK_LEADING_DISCOVERY}
    assert result.utterance  # a rendered question


def test_unclear_answer_triggers_clarify(session):
    eng = _engine(session)
    eng.open()
    eng.run_turn("It's for my son")          # fills relationship; agent asks subject
    result = eng.run_turn("I'm not sure")    # non-answer to the pending question
    assert result.action.modifier is Modifier.CLARIFY
    assert "make sure" in result.utterance.lower()


def test_objection_turn_is_handled(session):
    eng = _engine(session)
    eng.open()
    result = eng.run_turn("Honestly this sounds too expensive.")
    assert result.route is Route.OBJECTION
    assert result.action.action is Action.HANDLE_OBJECTION
    assert result.utterance


def test_escalation_turn_routes_to_human(session):
    eng = _engine(session)
    eng.open()
    result = eng.run_turn("Can I just talk to a human?")
    assert result.route is Route.ESCALATE
    assert result.action.action is Action.ESCALATE
    assert result.action.escalation_risk == "high"


def test_knowledge_turn_grounds_or_falls_back(session):
    # With a synthesize fn, a grounded question is answered from KB material.
    orch = Orchestrator(
        settings=Settings(_env_file=None),
        decider=DiscoveryDecider(),
        recorder=CallRecorder(session, channel="text"),
    )
    eng = ConversationEngine(orch, synthesize=lambda instruction: "SYNTHESIZED")
    eng.open()
    result = eng.run_turn("How does tutor matching work?")
    assert result.route is Route.KNOWLEDGE
    assert result.utterance == "SYNTHESIZED"
    assert result.action.kb_sources  # source attribution recorded


def test_full_discovery_to_close_runs_and_is_traced(session):
    eng = _engine(session)
    eng.open()
    # Pre-fill all but one required field, mark context confirmed, so we reach close quickly.
    eng.state.collected_fields.update({k: "known" for k in _REQUIRED if k != "readiness"})
    eng.state.context_confirmed = True

    eng.run_turn("I'm ready to find a tutor, let's do it")  # fills 'readiness' + buying intent
    # Discovery now complete + buying intent -> fit summary, then close.
    assert eng.state.buying_intent is True
    r_summary = eng.run_turn("yes that's right")
    r_close = eng.run_turn("sounds good")
    stages = {r_summary.action.stage, r_close.action.stage}
    assert Stage.FIT_SUMMARY in stages or Stage.CLOSE in stages
    assert eng.state.stage in {Stage.FIT_SUMMARY, Stage.CLOSE}

    # Transcript + decision trace persisted.
    call_id = eng.orch.recorder.call_id
    turns = session.scalars(select(Turn).where(Turn.call_id == call_id)).all()
    decisions = session.scalars(select(Decision).where(Decision.call_id == call_id)).all()
    assert any(t.speaker == "agent" for t in turns) and any(t.speaker == "prospect" for t in turns)
    assert decisions  # at least one decision logged
    assert all(d.selected_action for d in decisions)


def test_decision_trace_is_enriched_and_linked(session):
    """P5-T1: prospect turns carry detected intent/objection; decisions link to them (DE-2)."""
    eng = _engine(session)
    eng.open()
    eng.run_turn("Honestly this is too expensive.")  # objection
    eng.run_turn("Can I speak to a human?")           # escalation

    call_id = eng.orch.recorder.call_id
    prospect_turns = session.scalars(
        select(Turn).where(Turn.call_id == call_id, Turn.speaker == "prospect")
    ).all()
    by_intent = {t.detected_intent for t in prospect_turns}
    assert "objection" in by_intent and "escalate" in by_intent
    objection_turn = next(t for t in prospect_turns if t.detected_intent == "objection")
    assert objection_turn.detected_objection == "price"

    decisions = session.scalars(select(Decision).where(Decision.call_id == call_id)).all()
    # Each decision links back to a recorded turn (DE-2 trace ↔ transcript).
    turn_ids = {t.turn_id for t in session.scalars(select(Turn).where(Turn.call_id == call_id))}
    assert decisions and all(d.turn_id in turn_ids for d in decisions)
    # The escalation decision carries its risk.
    assert any(d.escalation_risk == "high" for d in decisions)
