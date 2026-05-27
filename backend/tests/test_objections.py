"""Tests for objection handling via playbook + KB (P4-T3)."""

from app.agent.decisioning import DiscoveryDecider
from app.agent.discovery import get_discovery_playbook
from app.agent.objections import (
    ObjectionPlaybook,
    get_objection_playbook,
    respond_to_objection,
)
from app.agent.orchestrator import ConversationState, Orchestrator
from app.agent.stages import Action, Stage
from app.config import Settings

_REQUIRED = {q.key for q in get_discovery_playbook().required}


def test_playbook_covers_use_case_4_objections_with_a_baseline():
    pb = get_objection_playbook()
    keys = {o.key for o in pb.objections}
    # PRD Use Case 4 spread (well over the ">= 3 types" bar).
    assert {"price", "discount", "spouse", "comparison", "tried_before"} <= keys
    baseline = pb.baseline_price()
    assert baseline.key == "price" and baseline.baseline is True


def test_detection_maps_phrases_to_objections():
    pb = get_objection_playbook()
    assert pb.detect("Honestly it's too expensive for us right now.").key == "price"
    assert pb.detect("Can we get a discount?").key == "discount"
    assert pb.detect("I need to talk to my spouse first.").key == "spouse"
    assert pb.detect("We tried tutoring before and it didn't work.").key == "tried_before"
    assert pb.detect("She's in 8th grade.") is None  # not an objection


def test_discount_is_high_risk_and_price_is_not():
    pb = get_objection_playbook()
    assert pb.detect("can we get a discount").high_risk is True
    assert pb.detect("that's too expensive").high_risk is False


def test_respond_grounds_price_rebuttal_with_kb_sources():
    pb = get_objection_playbook()
    response = respond_to_objection(pb.detect("it's too expensive"))
    assert response.objection_key == "price"
    assert response.rebuttal and "cost" in response.rebuttal.lower()
    assert isinstance(response.kb_sources, list)  # grounded supporting detail when available


def test_orchestrator_handles_objection_and_flags_high_risk():
    orch = Orchestrator(settings=Settings(_env_file=None))
    assert orch.handle_objection("what grade is she in?") is None  # nothing to handle

    action = orch.handle_objection("can we get a discount?")
    assert action.stage is Stage.OBJECTION_HANDLING
    assert action.action is Action.HANDLE_OBJECTION
    assert action.question_key == "discount"
    assert action.prompt  # the rebuttal
    assert orch.state.open_high_risk_objection is True


def test_high_risk_objection_holds_the_close():
    # Discovery complete + buying intent would normally be close-ready...
    state = ConversationState(
        collected_fields={k: "x" for k in _REQUIRED},
        context_confirmed=True,
        fit_summarized=True,
        buying_intent=True,
        open_high_risk_objection=True,  # ...but an unresolved high-risk objection blocks it.
    )
    action = DiscoveryDecider().decide(state, "")
    assert action.action is not Action.ATTEMPT_CLOSE


def test_playbook_load_normalizes_folded_rebuttal_whitespace(tmp_path):
    path = tmp_path / "obj.yaml"
    path.write_text(
        "objections:\n"
        "  - key: price\n"
        "    baseline: true\n"
        "    cues: ['expensive']\n"
        "    rebuttal: >-\n"
        "      line one\n"
        "      line two\n"
    )
    pb = ObjectionPlaybook.load(path)
    assert pb.objections[0].rebuttal == "line one line two"
