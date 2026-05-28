"""Tests for agent performance scoring (P6-T3). Deterministic + fake-judge; no real API."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.recorder import OUTCOME_COMPLETED, CallRecorder
from app.config import Settings
from app.db.models import Base
from app.kpis import events as kpi
from app.simulator.personas import get_personas
from app.simulator.scoring import JudgePayload, judge_transcript, score_call


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _call_with_events(session, *event_types, outcome=None):
    rec = CallRecorder(session, channel="sim:test", is_synthetic=True)
    rec.record_prospect("hi")
    for t in event_types:
        rec.record_event(t)
    rec.end(outcome=outcome)
    return rec.call_id


def test_objection_recovery_and_escalation_flags(session):
    cid = _call_with_events(
        session, kpi.OBJECTION_RAISED, kpi.CLOSE_ATTEMPT, outcome=OUTCOME_COMPLETED
    )
    score = score_call(session, cid, get_personas().get("price_sensitive_parent"), judge=False)
    assert score.objection_raised and score.objection_recovered
    assert score.close_attempted and not score.escalated
    assert score.appropriate_for_persona is True  # converts persona progressed to a close


def test_poor_fit_not_force_closed_is_appropriate(session):
    # poor-fit lead, no close attempted -> good handling.
    cid_ok = _call_with_events(session, kpi.DISCOVERY_COMPLETE)
    s_ok = score_call(session, cid_ok, get_personas().get("poor_fit"), judge=False)
    assert s_ok.appropriate_for_persona is True

    # poor-fit lead that WAS force-closed -> inappropriate.
    cid_bad = _call_with_events(session, kpi.CLOSE_ATTEMPT)
    s_bad = score_call(session, cid_bad, get_personas().get("poor_fit"), judge=False)
    assert s_bad.appropriate_for_persona is False


def test_converts_persona_without_progress_is_inappropriate(session):
    cid = _call_with_events(session, kpi.ESCALATION)  # bailed to escalation, no close/discovery
    score = score_call(session, cid, get_personas().get("motivated_parent"), judge=False)
    assert score.escalated is True
    assert score.appropriate_for_persona is False


# --- LLM judge (fake client) -----------------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self.parsed_output = payload


class _Messages:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self.payload)


class _Client:
    def __init__(self, payload):
        self.messages = _Messages(payload)


def test_judge_maps_structured_output(session):
    cid = _call_with_events(session, kpi.OBJECTION_RAISED)
    payload = JudgePayload(
        frustration=True, unsupported_claim=False, consultative_score=4, notes="solid"
    )
    score = score_call(
        session,
        cid,
        get_personas().get("skeptical_parent"),
        judge=True,
        judge_client=_Client(payload),
    )
    assert score.judge is not None
    assert score.judge.frustration is True
    assert score.judge.consultative_score == 4
    assert score.judge.unsupported_claim is False


def test_judge_transcript_sends_persona_and_transcript(session):
    cid = _call_with_events(session, kpi.OBJECTION_RAISED)
    from app.db.models import Call

    call = session.get(Call, cid)
    client = _Client(JudgePayload())
    judge_transcript(call, get_personas().get("price_sensitive_parent"), client=client,
                     settings=Settings(_env_file=None))
    sent = client.messages.calls[0]
    assert sent["output_format"] is JudgePayload
    assert "Price-Sensitive Parent" in sent["messages"][0]["content"]
