"""Router improvement-loop tests (IR5-T3) — promote only on accuracy gain, no regression."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.agent.contract import BrainDecision, RouterAction
from app.config import Settings
from app.db.models import Base
from app.simulator.improvement import decide_promotion, run_improvement


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class _AlwaysAskBrain:
    """A weak brain that never resolves a leaf -> 0% accuracy."""

    def decide(self, *, history, lead_fields=None, slots=None):
        return BrainDecision(
            action=RouterAction.ASK, utterance="Can you tell me more?", slots=dict(slots or {})
        )


def test_decide_promotion_rules():
    base = {"classification_accuracy": 0.5, "mis_quote_rate": 0.0, "price_correct_rate": 0.5}
    better = {"classification_accuracy": 0.9, "mis_quote_rate": 0.0, "price_correct_rate": 0.9}
    assert decide_promotion(base, better).promote is True
    # no gain
    assert decide_promotion(base, base).promote is False
    # accuracy up but mis-quote regressed
    regressed = {"classification_accuracy": 0.9, "mis_quote_rate": 0.1, "price_correct_rate": 0.9}
    assert decide_promotion(base, regressed).promote is False


def test_run_improvement_promotes_better_candidate(session):
    settings = Settings(_env_file=None)
    report = run_improvement(
        session,
        baseline_brain=_AlwaysAskBrain(),  # 0% accuracy baseline
        candidate_brains={"rule": RuleBrain(settings)},  # 100% accuracy candidate
        settings=settings,
    )
    assert report.promoted_key == "rule"
    assert report.candidates[0].metrics["classification_accuracy"] == 1.0


def test_run_improvement_keeps_baseline_when_no_gain(session):
    settings = Settings(_env_file=None)
    report = run_improvement(
        session,
        baseline_brain=RuleBrain(settings),
        candidate_brains={"weak": _AlwaysAskBrain()},
        settings=settings,
    )
    assert report.promoted_key is None
    assert "PROMOTE" not in report.render()
