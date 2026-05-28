"""Tests for dynamic next-question selection (P3-T3)."""

from app.agent.decisioning import MAX_ASK_ATTEMPTS, DiscoveryDecider
from app.agent.discovery import get_discovery_playbook
from app.agent.orchestrator import ConversationState, Orchestrator
from app.agent.stages import Action, Modifier, Stage
from app.config import Settings

_PB = get_discovery_playbook()
_ALL_REQUIRED = {q.key for q in _PB.required}
_ALL_LEADING = {q.key for q in _PB.leading}


def _state(collected: dict | None = None, *, context_confirmed: bool = False) -> ConversationState:
    return ConversationState(
        collected_fields=dict(collected or {}), context_confirmed=context_confirmed
    )


def test_no_info_lead_starts_discovery_immediately():
    action = DiscoveryDecider().decide(_state(), "")
    assert action.stage is Stage.DISCOVERY
    assert action.action is Action.ASK_REQUIRED_DISCOVERY
    assert action.question_key == "relationship_to_student"
    assert action.prompt  # the spoken question to ask


def test_known_context_is_confirmed_before_probing():
    action = DiscoveryDecider().decide(
        _state({"subject": "SAT prep", "grade_level": "11th grade"}), ""
    )
    assert action.stage is Stage.CONTEXT_CONFIRMATION
    assert action.action is Action.ASK_REQUIRED_DISCOVERY
    assert action.question_key == "subject"  # first known required, in playbook order
    assert "SAT prep" in action.prompt  # confirms the known value (LM-3)
    assert "relationship_to_student" in action.missing_fields


def test_after_confirmation_asks_first_missing_required():
    action = DiscoveryDecider().decide(
        _state({"subject": "SAT prep", "grade_level": "11th grade"}, context_confirmed=True), ""
    )
    assert action.stage is Stage.DISCOVERY
    assert action.question_key == "relationship_to_student"


def test_skip_known_advances_as_fields_fill():
    decider = DiscoveryDecider()
    state = _state(
        {"subject": "Algebra", "grade_level": "8th", "relationship_to_student": "parent"},
        context_confirmed=True,
    )
    assert decider.decide(state, "").question_key == "challenge"
    state.collected_fields["challenge"] = "falling behind on homework"
    assert decider.decide(state, "").question_key == "goal"


def test_moves_to_leading_then_fit_summary():
    decider = DiscoveryDecider()
    required_known = {k: "x" for k in _ALL_REQUIRED}
    leading = decider.decide(_state(required_known, context_confirmed=True), "")
    assert leading.stage is Stage.NEED_DEVELOPMENT
    assert leading.action is Action.ASK_LEADING_DISCOVERY
    assert leading.question_key == "pain_severity"

    everything = {**required_known, **{k: "x" for k in _ALL_LEADING}}
    fit = decider.decide(_state(everything, context_confirmed=True), "")
    assert fit.stage is Stage.FIT_SUMMARY
    assert fit.action is Action.SUMMARIZE_FIT


def test_reasks_are_rephrased_then_field_is_abandoned():
    # Real call 8b72f75c looped on relationship_to_student. After MAX_ASK_ATTEMPTS the decider
    # must stop asking it and move to the next required field instead of re-asking forever.
    decider = DiscoveryDecider()
    state = _state()
    first = decider.decide(state, "")
    assert first.question_key == "relationship_to_student"
    assert first.modifier is None

    # Simulate the engine having asked once already: the next ask should be a rephrase.
    state.ask_attempts["relationship_to_student"] = 1
    retry = decider.decide(state, "")
    assert retry.question_key == "relationship_to_student"
    assert retry.modifier is Modifier.CLARIFY

    # Once capped, the field is abandoned and the decider advances to the next required field.
    state.ask_attempts["relationship_to_student"] = MAX_ASK_ATTEMPTS
    moved_on = decider.decide(state, "")
    assert moved_on.question_key != "relationship_to_student"


def test_orchestrator_confirms_known_context_once_then_progresses():
    orch = Orchestrator(
        settings=Settings(_env_file=None),
        decider=DiscoveryDecider(),
        known_fields={"subject": "SAT prep", "grade_level": "11th grade"},
    )
    orch.open()
    first = orch.on_user_turn("hi")
    assert first.stage is Stage.CONTEXT_CONFIRMATION
    assert orch.state.context_confirmed is True

    second = orch.on_user_turn("yes, that's right")
    assert second.stage is Stage.DISCOVERY
    assert second.question_key == "relationship_to_student"
