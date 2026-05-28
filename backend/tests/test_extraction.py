"""Tests for field & intent extraction (P4.5-T2)."""

from app.agent.extraction import (
    Extractor,
    RuleBasedExtractor,
    get_extractor,
)


def _x() -> RuleBasedExtractor:
    return RuleBasedExtractor()


def test_default_extractor_satisfies_protocol():
    assert isinstance(get_extractor(), Extractor)


def test_slot_fills_the_pending_question():
    # v1 is coarse: it stores the (lightly cleaned) utterance as the value, not a parsed token.
    e = _x().extract("She's in 8th grade", pending_field="grade_level")
    assert "8th grade" in e.fields["grade_level"]
    assert e.understood is True


def test_short_answer_fills_slot():
    e = _x().extract("Geometry.", pending_field="subject")
    assert e.fields["subject"] == "Geometry"


def test_non_answer_triggers_clarify_without_storing():
    e = _x().extract("Honestly I'm not sure", pending_field="grade_level")
    assert e.fields == {}
    assert e.understood is False


def test_question_back_is_not_an_answer():
    e = _x().extract("Well, how does that work?", pending_field="urgency")
    assert e.fields == {}
    assert e.understood is False


def test_no_pending_field_means_nothing_to_fill():
    e = _x().extract("Hi there")
    assert e.fields == {}
    assert e.understood is True


def test_buying_intent_detected():
    assert _x().extract("Yeah, let's get started!").buying_intent is True
    assert _x().extract("Sign me up.").buying_intent is True
    # A question about starting is not buying intent.
    assert _x().extract("How do I get started?").buying_intent is False


def test_disqualification_detected():
    assert _x().extract("We already found a tutor, not looking anymore.").disqualified is True
    assert _x().extract("I'm just looking for now.").disqualified is True


def test_answer_can_carry_buying_intent_too():
    e = _x().extract("8th grade, and yeah let's do it", pending_field="grade_level")
    assert e.fields["grade_level"]  # filled
    assert e.buying_intent is True
