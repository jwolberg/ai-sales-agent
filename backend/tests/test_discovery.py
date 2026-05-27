"""Tests for the discovery question set & skip-known logic (P3-T2)."""

from app.agent.discovery import (
    KIND_LEADING,
    KIND_REQUIRED,
    DiscoveryPlaybook,
    get_discovery_playbook,
)


def test_playbook_loads_df1_and_df2_question_sets():
    pb = get_discovery_playbook()
    # DF-1 lists 10 required questions; DF-2 lists 8 leading ones.
    assert len(pb.required) == 10
    assert len(pb.leading) == 8
    # Required questions lead with the DF-1 minimum (who / subject / grade).
    assert [q.key for q in pb.required[:3]] == [
        "relationship_to_student",
        "subject",
        "grade_level",
    ]
    assert all(q.kind == KIND_REQUIRED for q in pb.required)
    assert all(q.kind == KIND_LEADING for q in pb.leading)
    assert all(q.prompt for q in pb.required + pb.leading)


def test_next_question_starts_with_first_required_when_nothing_known():
    pb = get_discovery_playbook()
    q = pb.next_question({})
    assert q is not None and q.key == "relationship_to_student"


def test_next_question_skips_known_required_fields():
    pb = get_discovery_playbook()
    collected = {"relationship_to_student": "parent", "subject": "Algebra", "grade_level": "8th"}
    q = pb.next_question(collected)
    # First three required are known, so it moves to the 4th required field.
    assert q is not None and q.key == "challenge"
    assert {x.key for x in pb.missing_required(collected)}.isdisjoint(
        {"relationship_to_student", "subject", "grade_level"}
    )
    assert {x.key for x in pb.known_required(collected)} == {
        "relationship_to_student",
        "subject",
        "grade_level",
    }


def test_next_question_moves_to_leading_once_required_complete():
    pb = get_discovery_playbook()
    collected = {q.key: "known" for q in pb.required}
    q = pb.next_question(collected)
    assert q is not None and q.kind == KIND_LEADING
    assert q.key == "pain_severity"


def test_next_question_none_when_everything_collected():
    pb = get_discovery_playbook()
    collected = {q.key: "known" for q in pb.required + pb.leading}
    assert pb.next_question(collected) is None
    assert pb.missing_required(collected) == []


def test_confirm_prompt_uses_template_for_known_value():
    pb = get_discovery_playbook()
    subject_q = next(q for q in pb.required if q.key == "subject")
    assert "Algebra I" in subject_q.confirm_prompt("Algebra I")
    # A question without a custom confirm template still produces a sensible prompt.
    challenge_q = next(q for q in pb.required if q.key == "challenge")
    assert "8th" in challenge_q.confirm_prompt("8th")


def test_playbook_load_is_independent_of_default_cache(tmp_path):
    custom = tmp_path / "pb.yaml"
    custom.write_text(
        "required:\n  - key: subject\n    prompt: What subject?\nleading: []\n"
    )
    pb = DiscoveryPlaybook.load(custom)
    assert [q.key for q in pb.required] == ["subject"]
    assert pb.leading == []
