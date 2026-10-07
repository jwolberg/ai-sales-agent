"""Tests for the intent-router live voice bot (IR4-T1).

Pure logic + construction only — no audio, no real API. The full live loop is validated by a
browser/mic/keys run per the RUNBOOK.
"""

import pytest

pytest.importorskip("pipecat")  # the bot module imports pipecat at import time

from app.agent.guardrails import ESCALATION_MESSAGE  # noqa: E402
from app.agent.intent_engine import IntentRouterEngine  # noqa: E402
from app.config import Settings  # noqa: E402
from app.voice.bot import (  # noqa: E402
    EngineProcessor,
    _transcript_confidence,
    build_engine,
    build_engine_pipeline_task,
    guard_output,
)

_VOICE_KEYS = dict(deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z")


# --- §18 output guard ------------------------------------------------------------------


def test_guard_blocks_human_claim_and_guarantee():
    assert guard_output("Don't worry, I'm a real person.") == ESCALATION_MESSAGE
    assert guard_output("We guarantee her grades will go up.") == ESCALATION_MESSAGE


def test_guard_allows_clean_lines():
    clean = "Are you looking for test prep or subject tutoring?"
    assert guard_output(clean) == clean


# --- engine wiring ---------------------------------------------------------------------


def test_build_engine_returns_router_engine_seeded_with_slots():
    settings = Settings(_env_file=None, **_VOICE_KEYS)  # no OpenAI key -> offline RuleBrain
    engine = build_engine(
        settings, known_fields={"subject": "chemistry", "grade_level": "11th grade"}
    )
    assert isinstance(engine, IntentRouterEngine)
    # subject is a taxonomy slot and pre-fills classification state; grade_level is not.
    assert engine.slots.get("subject") == "chemistry"
    assert "grade_level" not in engine.slots


def test_engine_processor_filler_flag():
    settings = Settings(_env_file=None, **_VOICE_KEYS)
    engine = build_engine(settings)
    assert EngineProcessor(engine, fillers=True)._fillers is not None
    assert EngineProcessor(engine, fillers=False)._fillers is None


def test_engine_processor_starts_not_ready():
    # Transcripts are dropped until greet() runs, so connect-time noise never becomes a turn.
    settings = Settings(_env_file=None, **_VOICE_KEYS)
    assert EngineProcessor(build_engine(settings))._ready is False


# --- pipeline construction (no keys/audio) ---------------------------------------------


def test_engine_pipeline_constructs():
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from app.voice.pipeline import build_services

    settings = Settings(_env_file=None, **_VOICE_KEYS)
    stt, tts = build_services(settings)
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
    inner = next(p for p in task._pipeline._processors if isinstance(p, Pipeline))
    names = [type(p).__name__ for p in inner._processors]
    assert "BotSpeakingMute" in names, names
    assert names.index("BotSpeakingMute") < names.index("_DeepgramSTTService"), names


# --- STT confidence parsing ------------------------------------------------------------


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


def test_build_transport_ambient_off_constructs():
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

    from app.voice.pipeline import build_transport

    settings = Settings(_env_file=None)  # ambient_noise defaults False
    transport = build_transport(SmallWebRTCConnection(), settings)
    assert transport is not None
