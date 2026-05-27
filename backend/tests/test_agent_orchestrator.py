"""Tests for the conversation orchestrator skeleton (P2-T3)."""

from app.agent.orchestrator import (
    ConversationState,
    NextAction,
    NextActionDecider,
    Orchestrator,
    StubDecider,
)
from app.agent.persona import stage_directive
from app.agent.stages import Action, Modifier, Stage
from app.config import Settings


def _settings() -> Settings:
    return Settings(_env_file=None, agent_name="Ava", company_name="Varsity Tutors")


def test_stage_action_modifier_vocab_matches_flow_doc():
    # PRD §17 (11 stages), §9.5 DE-1 (10 actions), AGENT_FLOW §4.4 (6 modifiers).
    assert len(Stage) == 11
    assert len(Action) == 10
    assert len(Modifier) == 6
    # str-valued so they drop straight into the Decision string columns.
    assert Stage.DISCOVERY.value == "discovery"
    assert Action.ATTEMPT_CLOSE.value == "attempt_close"
    assert Modifier.REASSURE.value == "reassure"
    assert isinstance(Stage.CLOSE, str) and isinstance(Action.END_CALL, str)


def test_open_returns_greeting_with_identity():
    orch = Orchestrator(settings=_settings())
    greeting = orch.open()
    assert "Ava" in greeting
    assert "Varsity Tutors" in greeting
    assert orch.state.stage is Stage.GREETING
    # Persona is fixed up front (consistent persona, VC-4).
    assert "consultative sales specialist" in orch.system_prompt


def test_stub_decider_walks_the_happy_path():
    orch = Orchestrator(settings=_settings())
    orch.open()

    seen = [orch.on_user_turn(f"reply {i}").stage for i in range(6)]
    assert seen == [
        Stage.DISCOVERY,       # turn 1
        Stage.DISCOVERY,       # turn 2
        Stage.FIT_SUMMARY,     # turn 3 (discovery assumed complete)
        Stage.CLOSE,           # turn 4
        Stage.WRAP_UP,         # turn 5
        Stage.WRAP_UP,         # turn 6 (stays wrapped up)
    ]
    # Orchestrator state tracks the latest stage.
    assert orch.state.stage is Stage.WRAP_UP
    assert orch.state.user_turns == 6


def test_first_discovery_turn_carries_a_rapport_modifier():
    orch = Orchestrator(settings=_settings())
    orch.open()
    first = orch.on_user_turn("hi there")
    assert first.action is Action.ASK_REQUIRED_DISCOVERY
    assert first.modifier is Modifier.RAPPORT
    # Modifier is independent of the logged stage.
    assert first.stage is Stage.DISCOVERY


def test_next_action_fields_map_to_decision_columns():
    action = StubDecider().decide(ConversationState(user_turns=4), "ok")
    # The values written to Decision.stage / Decision.selected_action are plain strings.
    assert action.stage.value == "close"
    assert action.action.value == "attempt_close"
    assert isinstance(action.missing_fields, list)
    assert action.confidence == 0.5


def test_decider_is_pluggable():
    class AlwaysEscalate:
        def decide(self, state: ConversationState, user_text: str) -> NextAction:
            return NextAction(stage=Stage.ESCALATION, action=Action.ESCALATE)

    assert isinstance(AlwaysEscalate(), NextActionDecider)  # structural Protocol check
    orch = Orchestrator(settings=_settings(), decider=AlwaysEscalate())
    orch.open()
    action = orch.on_user_turn("I want a human")
    assert action.action is Action.ESCALATE
    assert orch.state.stage is Stage.ESCALATION


def test_stage_directive_covers_every_stage():
    for stage in Stage:
        assert stage_directive(stage), f"missing directive for {stage}"
