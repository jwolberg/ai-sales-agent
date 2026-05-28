"""Tests for grounded answers & no-hallucination fallback (P4-T2)."""

from app.agent.knowledge import (
    FALLBACK_MESSAGE,
    answer_question,
    grounding_prompt,
    is_knowledge_question,
    is_social_pleasantry,
)
from app.agent.orchestrator import Orchestrator
from app.agent.stages import Action, Stage
from app.config import Settings


def test_grounded_answer_returns_snippets_and_sources():
    ans = answer_question("can I switch tutors if it's not a good fit?")
    assert ans.grounded
    assert ans.sources and all(s.endswith(".md") for s in ans.sources)
    assert ans.snippets and any("tutor" in s.lower() for s in ans.snippets)
    assert ans.fallback is None


def test_uncovered_question_falls_back_honestly():
    ans = answer_question("what's the weather like in Paris today?")
    assert not ans.grounded
    assert ans.sources == [] and ans.snippets == []
    assert ans.fallback == FALLBACK_MESSAGE


def test_grounding_prompt_includes_only_retrieved_material():
    ans = answer_question("do you offer a refund?")
    prompt = grounding_prompt(ans)
    assert "ONLY this approved information" in prompt
    assert any(snippet in prompt for snippet in ans.snippets)


def test_is_knowledge_question_heuristic():
    assert is_knowledge_question("How does tutor matching work?")
    assert is_knowledge_question("can we change tutors")
    assert not is_knowledge_question("It's for my son.")
    assert not is_knowledge_question("")


def test_social_pleasantries_are_not_knowledge_questions():
    # Real call ea6c68d9: "Hey. How's it going?" got a KB deferral on the opening turn.
    for greeting in (
        "Hey. How's it going?",
        "How are you doing today?",
        "Hi there!",
        "Hello?",
        "Thanks!",
        "Can you hear me?",
        "You still there?",
    ):
        assert is_social_pleasantry(greeting), greeting
        assert not is_knowledge_question(greeting), greeting


def test_real_questions_still_route_to_knowledge():
    # Tightening must not swallow genuine KB questions.
    for question in (
        "How much does tutoring cost?",
        "Do you offer SAT prep?",
        "Is it online or in person?",
        "How do I sign up?",
    ):
        assert not is_social_pleasantry(question), question
        assert is_knowledge_question(question), question


def test_orchestrator_answer_knowledge_grounded():
    orch = Orchestrator(settings=Settings(_env_file=None))
    action = orch.answer_knowledge("how do you match a student with a tutor?")
    assert action.stage is Stage.KNOWLEDGE_ANSWER
    assert action.action is Action.ANSWER_KNOWLEDGE
    assert "tutoring_formats_and_matching.md" in action.kb_sources
    assert action.prompt and "ONLY this approved information" in action.prompt
    assert action.confidence == 0.7


def test_orchestrator_answer_knowledge_fallback():
    orch = Orchestrator(settings=Settings(_env_file=None))
    action = orch.answer_knowledge("can my dog learn to drive a car?")
    assert action.stage is Stage.KNOWLEDGE_ANSWER
    assert action.action is Action.ANSWER_KNOWLEDGE
    assert action.kb_sources == []  # nothing grounded -> no sources claimed
    assert action.prompt == FALLBACK_MESSAGE
    assert action.confidence == 0.3
