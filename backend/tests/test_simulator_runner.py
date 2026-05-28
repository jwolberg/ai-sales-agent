"""Tests for the simulated call runner (P6-T2). Offline: scripted prospect, no-LLM engine."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.decisioning import DiscoveryDecider
from app.agent.engine import ConversationEngine
from app.agent.orchestrator import Orchestrator
from app.agent.recorder import OUTCOME_ESCALATED, CallRecorder
from app.agent.stages import Stage
from app.config import Settings
from app.db.models import Base, Call, Decision, Turn
from app.simulator.personas import get_personas
from app.simulator.runner import make_prospect, run_call


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _engine(session) -> ConversationEngine:
    orch = Orchestrator(
        settings=Settings(_env_file=None),
        decider=DiscoveryDecider(),
        recorder=CallRecorder(session, channel="sim:test", is_synthetic=True),
    )
    return ConversationEngine(orch)  # rule-based extractor, no synthesize -> deterministic


def _scripted(replies):
    it = iter(replies)

    def respond(_agent_line):
        return next(it, "okay, that's all, bye")

    return respond


def test_run_call_records_a_synthetic_call(session):
    eng = _engine(session)
    prospect = _scripted(["it's for my son", "8th grade", "algebra", "i'm the parent"])
    result = run_call(eng, prospect, "motivated_parent", max_turns=6)

    assert result.call_id and result.persona_key == "motivated_parent"
    assert result.num_turns >= 2
    assert ("agent", result.transcript[0][1]) == result.transcript[0]  # greeting first

    call = session.scalar(select(Call).where(Call.call_id == result.call_id))
    assert call.is_synthetic is True
    assert call.channel == "sim:test"
    assert call.ended_at is not None and call.outcome is not None
    assert session.scalars(select(Turn).where(Turn.call_id == result.call_id)).all()
    assert session.scalars(select(Decision).where(Decision.call_id == result.call_id)).all()


def test_goodbye_ends_the_call(session):
    eng = _engine(session)
    result = run_call(eng, _scripted(["thanks, that's all, bye"]), "busy_parent", max_turns=10)
    # Loop should stop on the goodbye, not run all 10 turns.
    assert result.num_turns <= 3


def test_escalation_ends_with_escalated_outcome(session):
    eng = _engine(session)
    result = run_call(eng, _scripted(["can I talk to a human?"]), "skeptical_parent", max_turns=6)
    assert result.final_stage is Stage.ESCALATION
    assert result.outcome == OUTCOME_ESCALATED


# --- prospect responder (fake Anthropic client) ----------------------------------------

class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, reply):
        self._reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._reply)


class _Client:
    def __init__(self, reply):
        self.messages = _Messages(reply)


def test_make_prospect_uses_persona_and_tracks_history():
    persona = get_personas().get("price_sensitive_parent")
    client = _Client("It's for my son, 9th grade geometry.")
    prospect = make_prospect(persona, Settings(_env_file=None), client=client)

    reply = prospect("Hi, this is Jay. How can I help?")
    assert reply == "It's for my son, 9th grade geometry."
    # Persona drives the system prompt; the agent line is the user turn.
    call = client.messages.calls[0]
    assert "Price-Sensitive Parent" in call["system"]
    assert call["messages"][0] == {"role": "user", "content": "Hi, this is Jay. How can I help?"}
