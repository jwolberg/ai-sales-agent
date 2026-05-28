"""Brain contract tests (IR2-T1)."""

from app.agent.contract import (
    TOOL_NAMES,
    TOOLS,
    BrainDecision,
    RouterAction,
)
from app.agent.taxonomy import SLOT_FIELDS


def test_tool_schemas_well_formed():
    names = set()
    for tool in TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        # required fields must be declared properties
        for req in params.get("required", []):
            assert req in params["properties"]
        names.add(fn["name"])
    assert names == set(TOOL_NAMES)
    assert names == {"slot_fill", "kb_lookup", "quote_price", "escalate"}


def test_slot_fill_enumerates_taxonomy_fields():
    slot_fill = next(t["function"] for t in TOOLS if t["function"]["name"] == "slot_fill")
    assert slot_fill["parameters"]["properties"]["field"]["enum"] == list(SLOT_FIELDS)


def test_brain_decision_trace_shape():
    d = BrainDecision(
        action=RouterAction.QUOTE,
        utterance="Chemistry tutoring is $80 an hour.",
        reason="leaf resolved",
        confidence=1.0,
        slots={"category": "tutoring", "subject_area": "science", "subject": "chemistry"},
        leaf="tutoring/science/chemistry",
        kb_sources=[],
        quoted_amount=80.0,
    )
    t = d.trace()
    assert t["selected_action"] == "quote"
    assert t["leaf"] == "tutoring/science/chemistry"
    assert t["quoted_amount"] == 80.0
    assert t["slots"]["subject"] == "chemistry"
