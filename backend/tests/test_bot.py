"""Tests for the decider-led live voice bot (P4.5-T5).

Pure logic + construction only — no audio, no real API. The full live loop is validated by a
browser/mic/keys run per the RUNBOOK.
"""

import pytest

pytest.importorskip("pipecat")  # the bot module imports pipecat at import time

from app.agent.guardrails import ESCALATION_MESSAGE  # noqa: E402
from app.config import Settings  # noqa: E402
from app.voice.bot import (  # noqa: E402
    EngineProcessor,
    _transcript_confidence,
    build_engine,
    build_engine_pipeline_task,
    guard_output,
    make_synthesizer,
)

# --- §18 output guard ------------------------------------------------------------------

def test_guard_blocks_human_claim_and_guarantee():
    assert guard_output("Don't worry, I'm a real person.") == ESCALATION_MESSAGE
    assert guard_output("We guarantee her grades will go up.") == ESCALATION_MESSAGE


def test_guard_allows_clean_lines_and_approved_prices():
    clean = "What grade is your daughter in?"
    assert guard_output(clean) == clean
    # Prices are approved KB content now — advisory flag only, not blocked.
    priced = "The annual plan is about $39.99 a year."
    assert guard_output(priced) == priced


# --- synthesizer (fake Anthropic client; no network) -----------------------------------

class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, *, text=None, error=None):
        self._text = text
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return _Response(self._text)


class _Client:
    def __init__(self, messages):
        self.messages = messages


def test_synthesizer_returns_text_and_uses_configured_model():
    settings = Settings(_env_file=None, anthropic_model="claude-sonnet-4-6")
    messages = _Messages(text="Sure — what subject are we focused on?")
    synth = make_synthesizer(settings, client=_Client(messages))
    assert synth("Rephrase: what subject?") == "Sure — what subject are we focused on?"
    assert messages.calls[0]["model"] == "claude-sonnet-4-6"
    assert messages.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_synthesizer_replays_transcript_history():
    # P10-T2: when given the running transcript, the synthesizer replays it as prior messages so
    # the model phrases with context. Must produce a valid Claude message list: first turn is the
    # user's, roles alternate (consecutive same-role turns coalesced), instruction is the last turn.
    settings = Settings(_env_file=None, anthropic_model="claude-sonnet-4-6")
    messages = _Messages(text="Sure.")
    synth = make_synthesizer(settings, client=_Client(messages))
    history = [
        ("agent", "Hi, how can I help?"),       # leading assistant turn -> must be dropped
        ("prospect", "It's for my son in 9th grade"),
        ("agent", "Great."),
    ]
    synth("Rephrase: what subject?", history)

    sent = messages.calls[0]["messages"]
    assert sent[0]["role"] == "user"           # Anthropic requires the first message be the user's
    assert sent[-1]["role"] == "user"
    assert "Rephrase: what subject?" in sent[-1]["content"]
    assert any("my son in 9th grade" in m["content"] for m in sent)
    roles = [m["role"] for m in sent]
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))  # alternating/coalesced


def test_synthesizer_without_history_sends_single_user_message():
    settings = Settings(_env_file=None)
    messages = _Messages(text="ok")
    synth = make_synthesizer(settings, client=_Client(messages))
    synth("just the instruction")  # 1-arg call path unchanged
    assert messages.calls[0]["messages"] == [{"role": "user", "content": "just the instruction"}]


def test_synthesizer_returns_none_on_error():
    settings = Settings(_env_file=None)
    synth = make_synthesizer(settings, client=_Client(_Messages(error=RuntimeError("boom"))))
    assert synth("anything") is None


# --- pipeline construction (no keys/audio) ---------------------------------------------

def test_engine_pipeline_constructs():
    from pipecat.pipeline.task import PipelineTask
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from app.voice.pipeline import build_services

    settings = Settings(
        _env_file=None, deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z"
    )
    stt, _llm, tts = build_services(settings)
    engine = build_engine(settings)  # no recorder; lazy clients, no API calls
    processor = EngineProcessor(engine)

    connection = SmallWebRTCConnection()
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    task = build_engine_pipeline_task(transport, stt, tts, processor)
    assert isinstance(task, PipelineTask)

    # The mic must be muted while the agent speaks so it never transcribes its own voice.
    from pipecat.pipeline.pipeline import Pipeline

    inner = next(p for p in task._pipeline._processors if isinstance(p, Pipeline))
    names = [type(p).__name__ for p in inner._processors]
    assert "STTMuteFilter" in names, names
    assert names.index("STTMuteFilter") < names.index("_DeepgramSTTService"), names


def test_build_engine_seeds_known_fields_and_lead_id():
    # P10-T1: cross-call memory must reach the live engine — known fields seed the state so the
    # agent skips/confirms instead of re-asking, and the lead id is tracked on the call state.
    settings = Settings(
        _env_file=None, deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z"
    )
    engine = build_engine(
        settings,
        known_fields={"subject": "SAT prep", "grade_level": "11th grade"},
        lead_id="seed-partial-002",
    )
    assert engine.state.lead_id == "seed-partial-002"
    assert engine.state.collected_fields["subject"] == "SAT prep"
    # subject + grade are known, so only "who" remains to ask (LM-3 skip-known).
    assert engine.orch.missing_required_fields() == ["relationship_to_student"]


def test_engine_processor_filler_flag():
    settings = Settings(
        _env_file=None, deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z"
    )
    engine = build_engine(settings)
    assert EngineProcessor(engine, fillers=True)._fillers is not None
    assert EngineProcessor(engine, fillers=False)._fillers is None


class _Alt:
    def __init__(self, confidence):
        self.confidence = confidence


class _Channel:
    def __init__(self, alternatives):
        self.alternatives = alternatives


class _DeepgramMsg:
    def __init__(self, confidence):
        self.channel = _Channel([_Alt(confidence)])


class _Frame:
    def __init__(self, result):
        self.result = result


def test_transcript_confidence_parsing():
    assert _transcript_confidence(_Frame(_DeepgramMsg(0.87))) == pytest.approx(0.87)
    # Unrecognized / missing shapes are treated as "trust it" (None).
    assert _transcript_confidence(_Frame(None)) is None
    assert _transcript_confidence(_Frame(object())) is None  # no .channel


def test_engine_processor_starts_not_ready():
    # Transcripts are dropped until greet() runs, so connect-time noise never becomes a turn.
    settings = Settings(
        _env_file=None, deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z"
    )
    assert EngineProcessor(build_engine(settings))._ready is False


def test_build_transport_ambient_off_constructs():
    # ambient_noise=False -> no SoundfileMixer, so no `soundfile` import needed.
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

    from app.voice.pipeline import build_transport

    settings = Settings(_env_file=None)  # ambient_noise defaults False
    transport = build_transport(SmallWebRTCConnection(), settings)
    assert transport is not None
