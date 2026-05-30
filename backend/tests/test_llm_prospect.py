"""LLMProspect + prospect_factory forwarding tests (IR5-T4) — offline via a stub client."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.config import Settings
from app.db.models import Base
from app.simulator.improvement import run_improvement
from app.simulator.llm_prospect import LLMProspect
from app.simulator.personas import get_personas


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class _StubClient:
    """Mimics the OpenAI client surface LLMProspect uses; records the messages it was sent."""

    def __init__(self, reply: str = "It's the ACT.") -> None:
        self.reply = reply
        self.calls: list[list[dict]] = []
        self.chat = self  # client.chat.completions.create(...)
        self.completions = self

    def create(self, *, model, messages, **kwargs):
        self.calls.append(list(messages))

        class _Msg:
            content = self.reply

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


def _persona(key: str):
    return next(p for p in get_personas().router_personas() if p.key == key)


def test_opening_is_scripted_and_recorded():
    client = _StubClient()
    persona = _persona("router_act_ambiguous")
    prospect = LLMProspect(persona, Settings(_env_file=None), client=client)
    opening = prospect.opening()
    assert opening == "We need to start getting ready for college entrance exams."
    assert client.calls == []  # opening makes no API call


def test_next_feeds_agent_reply_and_returns_model_text():
    client = _StubClient(reply="It's the ACT, actually.")
    persona = _persona("router_act_ambiguous")
    prospect = LLMProspect(persona, Settings(_env_file=None), client=client)
    prospect.opening()
    reply = prospect.next("Which test are you preparing for — the SAT, ACT, or PSAT?")
    assert reply == "It's the ACT, actually."
    # The agent's line was handed to the model as a user turn, after the system + opening turns.
    sent = client.calls[-1]
    assert sent[0]["role"] == "system"
    assert sent[-1]["role"] == "user"
    assert "Which test" in sent[-1]["content"]


def test_run_improvement_forwards_prospect_factory(session):
    """A factory that forces the wrong leaf should drag accuracy to 0 — proving it was used."""

    class _WrongProspect:
        def opening(self):
            return "I need physics help."

        def next(self, agent_text=""):
            return "physics"

    settings = Settings(_env_file=None)
    chem = [_persona("router_chemistry")]
    report = run_improvement(
        session,
        baseline_brain=RuleBrain(settings),
        candidate_brains={"same": RuleBrain(settings)},
        personas=chem,
        settings=settings,
        prospect_factory=lambda _p: _WrongProspect(),
    )
    # The forced-physics prospect never reaches chemistry, so accuracy is 0 for both variants.
    assert report.baseline.metrics["classification_accuracy"] == 0.0
    assert report.candidates[0].metrics["classification_accuracy"] == 0.0
