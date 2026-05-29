"""KPI event capture & metric computation for the intent router (IR6-T1; PRD §16)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.agent.intent_engine import IntentRouterEngine
from app.agent.recorder import OUTCOME_COMPLETED, CallRecorder
from app.config import Settings
from app.db.models import Base, KPIEvent
from app.kpis import events as kpi
from app.kpis.metrics import compute_metrics, compute_router_metrics


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _engine(session, **kwargs):
    return IntentRouterEngine(
        brain=RuleBrain(Settings(_env_file=None)),
        recorder=CallRecorder(session, channel="text", **kwargs),
        settings=Settings(_env_file=None),
    )


def _event_types(session, call_id) -> set[str]:
    return {
        e.event_type for e in session.scalars(select(KPIEvent).where(KPIEvent.call_id == call_id))
    }


def test_classify_quote_emits_leaf_and_completion(session):
    eng = _engine(session)
    eng.open()
    eng.run_turn("I need chemistry tutoring")  # resolves a leaf -> quote
    eng.end(outcome=OUTCOME_COMPLETED)
    types = _event_types(session, eng.recorder.call_id)
    assert kpi.LEAF_REACHED in types
    assert kpi.CALL_COMPLETED in types


def test_escalation_emits_event(session):
    eng = _engine(session)
    eng.open()
    eng.run_turn("can I get a discount?")  # escalation
    eng.end()
    assert kpi.ESCALATION in _event_types(session, eng.recorder.call_id)


def test_router_metrics_rollup(session):
    a = _engine(session)
    a.open()
    a.run_turn("I want SAT prep")
    a.end(outcome=OUTCOME_COMPLETED)

    b = _engine(session)
    b.open()
    b.run_turn("can I talk to a human?")  # escalation, no leaf
    b.end()

    m = compute_router_metrics(session)
    assert m["total_calls"] == 2
    assert m["leaf_reached_rate"] == 0.5
    assert m["escalation_rate"] == 0.5
    assert m["mis_quote_rate"] == 0.0


def test_compute_metrics_empty_db_is_safe():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        assert compute_metrics(s)["total_calls"] == 0
        assert compute_router_metrics(s)["total_calls"] == 0
