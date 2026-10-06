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
from app.kpis.metrics import _percentile, compute_metrics, compute_router_metrics


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


def test_percentile_nearest_rank():
    assert _percentile([], 95) is None
    assert _percentile([42.0], 95) == 42.0
    # p50 of two values is the smaller (nearest-rank), not the larger — the old banker's-rounding
    # ceil returned 5000 here, which is what inflated p50/p95.
    assert _percentile([100.0, 5000.0], 50) == 100.0
    assert _percentile([100.0, 5000.0], 95) == 5000.0
    # 1..20: p50 -> 10th value, p95 -> 19th value (not the 20th/max).
    vals = [float(i) for i in range(1, 21)]
    assert _percentile(vals, 50) == 10.0
    assert _percentile(vals, 95) == 19.0


def test_turn_latency_recorded_and_rolled_up(session):
    eng = _engine(session)
    eng.open()
    eng.run_turn("I want SAT prep")
    eng.end(outcome=OUTCOME_COMPLETED)
    # the agent reply turn carries a latency measurement
    from app.db.models import Turn

    agent_turns = session.scalars(
        select(Turn).where(Turn.speaker == "agent", Turn.latency_ms.isnot(None))
    ).all()
    assert agent_turns, "expected a timed agent turn"
    m = compute_router_metrics(session)
    assert m["turn_latency_ms_p50"] is not None
    assert m["turn_latency_ms_p95"] is not None
