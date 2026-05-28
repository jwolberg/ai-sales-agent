"""Tests for synthetic persona definitions (P6-T1; PRD §12.2, §12.3)."""

from app.simulator.personas import PersonaLibrary, get_personas, persona_system_prompt

_EXPECTED_KEYS = {
    "motivated_parent",
    "skeptical_parent",
    "price_sensitive_parent",
    "busy_parent",
    "competitive_shopper",
    "poor_fit",
}


def test_at_least_six_personas_covering_the_required_types():
    lib = get_personas()
    assert len(lib.personas) >= 6
    assert _EXPECTED_KEYS <= set(lib.keys())


def test_personas_carry_ground_truth_and_outcome_flags():
    lib = get_personas()
    motivated = lib.get("motivated_parent")
    assert motivated.converts is True and motivated.disqualifies is False
    assert motivated.facts["subject"] and motivated.facts["grade_level"]

    poor = lib.get("poor_fit")
    assert poor.disqualifies is True and poor.converts is False  # agent must not force a close


def test_objection_personas_carry_objections():
    lib = get_personas()
    assert lib.get("price_sensitive_parent").objections  # raises price/discount/comparison
    assert lib.get("skeptical_parent").objections        # tried-before / proof
    assert lib.get("motivated_parent").objections == ()  # smooth path


def test_persona_prompt_includes_facts_behavior_and_objections():
    persona = get_personas().get("price_sensitive_parent")
    prompt = persona_system_prompt(persona)
    assert persona.name in prompt
    assert "Geometry" in prompt                       # a ground-truth fact
    assert "too expensive" in prompt.lower()          # an objection
    assert "partial answers" in prompt.lower()        # §12.3 behavior rule
    assert "not an ai" not in prompt.lower()          # phrased as "never... AI", sanity not strict


def test_disqualified_persona_prompt_resists_close():
    prompt = persona_system_prompt(get_personas().get("poor_fit"))
    assert "not ready to buy" in prompt.lower() or "noncommittal" in prompt.lower()


def test_custom_load(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text(
        "personas:\n"
        "  - key: x\n    name: X\n    summary: s\n    converts: true\n    disqualifies: false\n"
    )
    lib = PersonaLibrary.load(path)
    assert lib.keys() == ["x"] and lib.get("x").facts == {}
