"""Tests for KPI event capture & metric computation (P5-T3; PRD §16)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.decisioning import DiscoveryDecider
from app.agent.discovery import get_discovery_playbook
from app.agent.engine import ConversationEngine
from app.agent.orchestrator import Orchestrator
from app.agent.recorder import OUTCOME_COMPLETED, CallRecorder
from app.config import Settings
from app.db.models import Base, KPIEvent
from app.kpis import events as kpi
from app.kpis.metrics import compute_metrics

_REQUIRED = [q.key for q in get_discovery_playbook().required]


def _event_types(session, call_id) -> set[str]:
    return {
        e.event_type for e in session.scalars(select(KPIEvent).where(KPIEvent.call_id == call_id))
    }


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _engine(session, **kwargs):
    orch = Orchestrator(
        settings=Settings(_env_file=None),
        decider=DiscoveryDecider(),
        recorder=CallRecorder(session, channel="text", **kwargs),
    )
    return ConversationEngine(orch)


def test_engine_emits_objection_and_escalation_events(session):
    eng = _engine(session)
    eng.open()
    eng.run_turn("this is too expensive")       # objection
    eng.run_turn("can I talk to a human?")       # escalation
    eng.end(outcome=OUTCOME_COMPLETED)

    types = _event_types(session, eng.orch.recorder.call_id)
    assert kpi.OBJECTION_RAISED in types
    assert kpi.ESCALATION in types
    assert kpi.CALL_COMPLETED in types


def test_close_and_discovery_events_on_happy_path(session):
    eng = _engine(session)
    eng.open()
    eng.state.collected_fields.update({k: "known" for k in _REQUIRED})
    eng.state.context_confirmed = True
    eng.state.buying_intent = True
    eng.run_turn("yes")    # discovery complete -> fit summary (DISCOVERY_COMPLETE)
    eng.run_turn("great")  # -> attempt close (CLOSE_ATTEMPT)
    eng.end(outcome=OUTCOME_COMPLETED)

    types = _event_types(session, eng.orch.recorder.call_id)
    assert kpi.DISCOVERY_COMPLETE in types
    assert kpi.CLOSE_ATTEMPT in types


def test_metrics_rollup(session):
    # Call A: objection -> recovers to close, completes.
    a = _engine(session)
    a.open()
    a.state.collected_fields.update({k: "known" for k in _REQUIRED})
    a.state.context_confirmed = True
    a.state.buying_intent = True
    a.run_turn("too expensive")  # objection
    a.run_turn("okay")           # fit summary (discovery complete)
    a.run_turn("sounds good")    # attempt close
    a.end(outcome=OUTCOME_COMPLETED)

    # Call B: escalates, no completion.
    b = _engine(session)
    b.open()
    b.run_turn("can I talk to a human?")  # escalation
    b.end()

    m = compute_metrics(session)
    assert m["total_calls"] == 2
    assert m["escalation_rate"] == 0.5            # 1 of 2 calls escalated
    assert m["close_success_rate"] == 0.5         # 1 of 2 completed
    assert m["objection_recovery_rate"] == 1.0    # the 1 objection call progressed to close
    assert m["discovery_completion_rate"] == 0.5
    assert m["average_latency_seconds"] is None   # not captured yet
    assert m["frustration_rate"] is None


def test_metrics_empty_db_is_safe():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        m = compute_metrics(s)
    assert m["total_calls"] == 0
    assert m["escalation_rate"] is None  # no calls -> not-measured, not a div-by-zero


def test_metrics_slice_by_version(session):
    a = _engine(session, agent_version="persona-aaa")
    a.open()
    a.run_turn("talk to a human")  # escalation
    a.end()
    b = _engine(session, agent_version="persona-bbb")
    b.open()
    b.run_turn("she's in 8th grade")  # no escalation
    b.end()

    assert compute_metrics(session, agent_version="persona-aaa")["escalation_rate"] == 1.0
    assert compute_metrics(session, agent_version="persona-bbb")["escalation_rate"] == 0.0
