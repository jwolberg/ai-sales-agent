"""Tests for fit summary, close criteria & close-attempt logging (P3-T4)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.closing import (
    CLOSE_DIRECT,
    CLOSE_SOFT,
    CLOSE_TRIAL,
    NEXT_STEP_CONSULTATION,
    NEXT_STEP_FOLLOWUP,
    NEXT_STEP_MATCH_TUTOR,
    OUTCOME_ACCEPTED,
    CloseAttempt,
    assess_close_criteria,
    build_fit_summary,
    choose_close,
    next_step_prompt,
)
from app.agent.decisioning import DiscoveryDecider
from app.agent.discovery import get_discovery_playbook
from app.agent.orchestrator import ConversationState
from app.agent.recorder import CallRecorder
from app.agent.stages import Action, Stage
from app.db.models import Base, KPIEvent

_PB = get_discovery_playbook()
_ALL_REQUIRED = {q.key for q in _PB.required}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# --- DE-3 close criteria ---------------------------------------------------------------

def test_close_criteria_ready_only_when_all_met():
    ready = assess_close_criteria(
        discovery_complete=True, buying_intent=True, high_risk_objection=False
    )
    assert ready.ready and ready.reasons == []


def test_close_criteria_reports_each_unmet_reason():
    r = assess_close_criteria(
        discovery_complete=False, buying_intent=False, high_risk_objection=True
    )
    assert not r.ready
    assert set(r.reasons) == {
        "required discovery incomplete",
        "no clear buying intent yet",
        "unresolved high-risk objection",
    }


# --- CF-1 fit summary & CF-2 next step -------------------------------------------------

def test_fit_summary_reflects_known_fields():
    summary = build_fit_summary(
        {"grade_level": "8th grade", "subject": "Algebra", "goal": "rebuild her confidence"}
    )
    assert "8th grade Algebra" in summary
    assert "rebuild her confidence" in summary
    assert "strong fit" in summary


def test_choose_close_matches_readiness():
    assert choose_close(buying_intent=True, high_risk_objection=False) == (
        CLOSE_DIRECT,
        NEXT_STEP_MATCH_TUTOR,
    )
    assert choose_close(buying_intent=False, high_risk_objection=False) == (
        CLOSE_TRIAL,
        NEXT_STEP_CONSULTATION,
    )
    assert choose_close(buying_intent=True, high_risk_objection=True) == (
        CLOSE_SOFT,
        NEXT_STEP_FOLLOWUP,
    )
    assert next_step_prompt(NEXT_STEP_MATCH_TUTOR)


# --- decider fit -> close flow ---------------------------------------------------------

def _ready_state(**overrides) -> ConversationState:
    base = dict(
        collected_fields={k: "x" for k in _ALL_REQUIRED},
        context_confirmed=True,
        buying_intent=True,
    )
    base.update(overrides)
    return ConversationState(**base)


def test_decider_summarizes_then_attempts_close_when_criteria_met():
    decider = DiscoveryDecider()
    state = _ready_state()

    first = decider.decide(state, "")
    assert first.stage is Stage.FIT_SUMMARY
    assert first.action is Action.SUMMARIZE_FIT
    assert first.prompt  # the CF-1 summary

    state.fit_summarized = True
    second = decider.decide(state, "")
    assert second.stage is Stage.CLOSE
    assert second.action is Action.ATTEMPT_CLOSE
    assert second.question_key == NEXT_STEP_MATCH_TUTOR


def test_decider_pivots_when_required_done_but_criteria_unmet():
    decider = DiscoveryDecider()
    # All discovery (required + leading) covered, fit summarized, but no buying intent.
    collected = {q.key: "x" for q in _PB.required + _PB.leading}
    state = ConversationState(
        collected_fields=collected, context_confirmed=True, fit_summarized=True
    )
    action = decider.decide(state, "")
    assert action.stage is Stage.CLOSE
    assert action.action is Action.PIVOT_TOWARD_CLOSE


# --- CF-3 close-attempt logging --------------------------------------------------------

def test_close_attempt_is_logged_with_required_fields(session):
    rec = CallRecorder(session, channel="web")
    rec.record_close_attempt(
        CloseAttempt(
            close_type=CLOSE_DIRECT,
            next_step=NEXT_STEP_MATCH_TUTOR,
            objection_state="none",
            user_response="Yes, let's do it.",
            outcome=OUTCOME_ACCEPTED,
        )
    )
    event = session.scalar(
        select(KPIEvent).where(KPIEvent.call_id == rec.call_id)
    )
    assert event.event_type == "close_attempt"
    assert event.created_at is not None  # CF-3 timing
    meta = event.event_metadata
    assert meta["close_type"] == CLOSE_DIRECT
    assert meta["next_step"] == NEXT_STEP_MATCH_TUTOR
    assert meta["objection_state"] == "none"
    assert meta["user_response"] == "Yes, let's do it."
    assert meta["outcome"] == OUTCOME_ACCEPTED
