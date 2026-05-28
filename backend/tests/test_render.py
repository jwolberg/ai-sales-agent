"""Tests for the Directive + render step (P4.5-T3)."""

from app.agent.decisioning import DiscoveryDecider
from app.agent.knowledge import FALLBACK_MESSAGE
from app.agent.orchestrator import ConversationState, Orchestrator
from app.agent.render import ContentKind, Directive, render, to_directive
from app.agent.stages import Action
from app.config import Settings


def _orch() -> Orchestrator:
    return Orchestrator(settings=Settings(_env_file=None))


def test_discovery_question_is_a_speak_directive():
    action = DiscoveryDecider().decide(ConversationState(), "")  # asks first required question
    directive = to_directive(action)
    assert directive.kind is ContentKind.SPEAK
    assert directive.text == action.prompt
    assert render(directive) == action.prompt  # deterministic, no LLM


def test_grounded_answer_is_a_ground_directive_synthesized_by_the_llm():
    action = _orch().answer_knowledge("how do you match a student with a tutor?")
    directive = to_directive(action)
    assert directive.kind is ContentKind.GROUND
    assert directive.sources  # KB-3 attribution carried through
    assert directive.instruction and "ONLY this approved information" in directive.instruction

    # With an LLM, render synthesizes from the instruction...
    spoken = render(directive, synthesize=lambda instruction: "Here's how matching works…")
    assert spoken == "Here's how matching works…"
    # ...without one, it degrades to the honest fallback, never a guess.
    assert render(directive) == FALLBACK_MESSAGE


def test_kb_fallback_is_speak_not_ground():
    action = _orch().answer_knowledge("can my dog learn to drive a car?")
    directive = to_directive(action)
    assert directive.kind is ContentKind.SPEAK  # fallback already final words
    assert render(directive) == FALLBACK_MESSAGE
    assert directive.sources == []


def test_objection_and_escalation_render_their_words():
    orch = _orch()
    objection = to_directive(orch.handle_objection("it's too expensive"))
    assert objection.kind is ContentKind.SPEAK
    assert render(objection)  # the rebuttal text

    escalation = to_directive(orch.check_escalation("let me talk to a human"))
    assert escalation.intent is Action.ESCALATE
    assert render(escalation)  # the handoff line


def test_render_is_pure_for_speak():
    d = Directive(intent=Action.SUMMARIZE_FIT, kind=ContentKind.SPEAK, text="So, to confirm…")
    assert render(d) == "So, to confirm…"
    assert render(d) == render(d)  # same input -> same output


def test_smoothable_speak_is_llm_rephrased(monkeypatch=None):
    # A discovery question is smoothable: with an LLM it's rephrased, without it stays verbatim.
    action = DiscoveryDecider().decide(ConversationState(), "")
    directive = to_directive(action)
    assert directive.smoothable is True
    assert render(directive, synthesize=lambda instruction: "Smoothed line.") == "Smoothed line."
    assert render(directive) == action.prompt  # no LLM -> verbatim
    # Synthesize failure falls back to the verbatim authored text.
    assert render(directive, synthesize=lambda instruction: None) == action.prompt


def test_fixed_lines_are_not_smoothed():
    # An objection rebuttal is approved language — spoken verbatim even with an LLM available.
    action = _orch().handle_objection("it's too expensive")
    directive = to_directive(action)
    assert directive.smoothable is False
    assert render(directive, synthesize=lambda i: "should not be used") == action.prompt
