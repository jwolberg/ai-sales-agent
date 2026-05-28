"""Tests for the turn router (P4.5-T1)."""

from app.agent.router import Route, classify_turn


def test_escalation_wins_over_everything():
    d = classify_turn("Can I just speak to a human?")
    assert d.route is Route.ESCALATE
    assert d.detail == "human_request"


def test_discount_demand_escalates_but_too_expensive_is_an_objection():
    # Deliberate split (DE-4 vs §8 baseline):
    assert classify_turn("Can we get a discount?").route is Route.ESCALATE
    expensive = classify_turn("Honestly it's too expensive for us.")
    assert expensive.route is Route.OBJECTION
    assert expensive.detail == "price"


def test_clear_refusal_stops_selling():
    d = classify_turn("I'm really not interested, please stop calling.")
    assert d.route is Route.STOP_SELLING


def test_objection_is_routed_with_its_key():
    assert classify_turn("I need to talk to my spouse first.").detail == "spouse"
    assert classify_turn("We tried tutoring before and it didn't work.").detail == "tried_before"


def test_objection_takes_priority_over_a_question_phrasing():
    # "How do I know the tutor will be good?" is both a question and the tutor_quality
    # objection -> handled as the objection.
    d = classify_turn("How do I know the tutor will be good?")
    assert d.route is Route.OBJECTION
    assert d.detail == "tutor_quality"


def test_plain_question_routes_to_knowledge():
    assert classify_turn("How much does tutoring cost?").route is Route.KNOWLEDGE
    assert classify_turn("Is it online or in person?").route is Route.KNOWLEDGE


def test_discovery_answer_routes_to_progress():
    assert classify_turn("She's in 8th grade.").route is Route.PROGRESS
    assert classify_turn("It's for my daughter, math.").route is Route.PROGRESS


def test_social_pleasantry_routes_to_progress_not_knowledge():
    # Real call ea6c68d9: a greeting was sent to KNOWLEDGE -> §18 specialist deferral on turn one.
    assert classify_turn("Hey. How's it going?").route is Route.PROGRESS
    assert classify_turn("How are you doing?").route is Route.PROGRESS
    assert classify_turn("Hi there!").route is Route.PROGRESS
    assert classify_turn("Can you hear me?").route is Route.PROGRESS


def test_hostility_routes_to_escalate():
    assert classify_turn("Shut the **** up.").route is Route.ESCALATE
    assert classify_turn("Just shut up.").route is Route.ESCALATE


def test_priority_order_is_strict():
    # A turn that mentions a human AND an objection still escalates first.
    assert classify_turn("I'd rather talk to a human, this is too expensive").route is (
        Route.ESCALATE
    )
