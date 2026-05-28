"""Tests for the LLM-backed extractor (P4.5-T2 upgrade). No real API calls — fake client."""

from app.agent.extraction import (
    ExtractedField,
    ExtractionPayload,
    Extractor,
    LLMExtractor,
    allowed_fields,
)
from app.config import Settings


class _FakeResponse:
    def __init__(self, payload: ExtractionPayload):
        self.parsed_output = payload


class _FakeMessages:
    def __init__(self, payload: ExtractionPayload):
        self._payload = payload
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._payload)


class FakeClient:
    def __init__(self, payload: ExtractionPayload):
        self.messages = _FakeMessages(payload)


def _extractor(payload: ExtractionPayload) -> tuple[LLMExtractor, FakeClient]:
    client = FakeClient(payload)
    settings = Settings(_env_file=None, anthropic_model="claude-sonnet-4-6")
    return LLMExtractor(client=client, settings=settings), client


def test_is_an_extractor():
    extractor, _ = _extractor(ExtractionPayload())
    assert isinstance(extractor, Extractor)


def test_pending_answer_and_volunteered_fields_are_captured():
    payload = ExtractionPayload(
        answer="8th grade",
        extra_fields=[
            ExtractedField(key="subject", value="Algebra"),
            ExtractedField(key="relationship_to_student", value="parent"),
        ],
    )
    extractor, _ = _extractor(payload)
    result = extractor.extract(
        "She's in 8th grade, I'm her mom, it's algebra", pending_field="grade_level"
    )
    assert result.fields == {
        "grade_level": "8th grade",
        "subject": "Algebra",
        "relationship_to_student": "parent",
    }
    assert result.understood is True


def test_unknown_field_keys_are_dropped():
    payload = ExtractionPayload(
        extra_fields=[
            ExtractedField(key="subject", value="Math"),
            ExtractedField(key="favorite_color", value="blue"),  # not an allowed field
        ]
    )
    extractor, _ = _extractor(payload)
    result = extractor.extract("math, and her favorite color is blue")
    assert result.fields == {"subject": "Math"}


def test_signals_pass_through():
    payload = ExtractionPayload(buying_intent=True, disqualified=False, understood=True)
    extractor, _ = _extractor(payload)
    result = extractor.extract("yes, let's get started")
    assert result.buying_intent is True


def test_non_answer_sets_understood_false():
    payload = ExtractionPayload(answer=None, understood=False)
    extractor, _ = _extractor(payload)
    result = extractor.extract("hmm, I'm not sure", pending_field="urgency")
    assert result.fields == {}
    assert result.understood is False


def test_request_uses_configured_model_cached_system_and_field_keys():
    extractor, client = _extractor(ExtractionPayload())
    extractor.extract("hi", pending_field="subject")
    call = client.messages.calls[0]
    assert call["model"] == "claude-sonnet-4-6"  # configured model, not a hardcoded default
    # System prompt is a cached block listing the allowed field keys.
    system_block = call["system"][0]
    assert system_block["cache_control"] == {"type": "ephemeral"}
    assert "subject" in system_block["text"] and "relationship_to_student" in system_block["text"]
    assert call["output_format"] is ExtractionPayload


def test_allowed_fields_cover_discovery_and_profile():
    keys = allowed_fields()
    expected = {"subject", "grade_level", "relationship_to_student", "challenge", "pain_severity"}
    assert expected <= keys
