import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings


def test_missing_voice_keys_detected():
    none_set = Settings(
        _env_file=None, deepgram_api_key=None, anthropic_api_key=None, cartesia_api_key=None
    )
    assert set(none_set.missing_voice_keys()) == {
        "DEEPGRAM_API_KEY",
        "ANTHROPIC_API_KEY",
        "CARTESIA_API_KEY",
    }

    all_set = Settings(
        _env_file=None, deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z"
    )
    assert all_set.missing_voice_keys() == []


def test_latency_config_defaults():
    s = Settings(_env_file=None)
    assert s.fillers is True  # latency mask on by default
    assert s.ambient_noise is False  # opt-in (needs the asset + soundfile)
    assert s.audio_out_sample_rate == 24000  # matches data/audio/ambient.wav


def test_vad_config_defaults():
    s = Settings(_env_file=None)
    # Defaults match pipecat's own, so live turn-taking is unchanged until deliberately tuned.
    assert s.vad_stop_secs == 0.2
    assert s.vad_start_secs == 0.2
    assert s.vad_confidence == 0.7
    assert s.vad_min_volume == 0.6


def test_vad_params_shape():
    s = Settings(_env_file=None, vad_stop_secs=0.8)
    assert s.vad_params() == {
        "stop_secs": 0.8,
        "start_secs": 0.2,
        "confidence": 0.7,
        "min_volume": 0.6,
    }


def test_recorder_stamps_vad_params():
    """A call records the VAD dials it ran under so the dashboard evaluator can show them."""
    from app.agent.recorder import CallRecorder
    from app.db.models import Base, Call

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Settings(_env_file=None, vad_stop_secs=0.7)
    with Session(engine) as session:
        recorder = CallRecorder(session, channel="web", vad_params=s.vad_params())
        session.commit()
        stored = session.get(Call, recorder.call.call_id)
        assert stored.vad_params == {
            "stop_secs": 0.7,
            "start_secs": 0.2,
            "confidence": 0.7,
            "min_volume": 0.6,
        }


def test_build_vad_analyzer_applies_settings():
    """The VAD dials flow from Settings into the Silero analyzer's params."""
    pytest.importorskip("pipecat")
    from app.voice.pipeline import build_vad_analyzer

    s = Settings(_env_file=None, vad_stop_secs=1.1, vad_start_secs=0.3)
    analyzer = build_vad_analyzer(s)
    assert analyzer.params.stop_secs == 1.1
    assert analyzer.params.start_secs == 0.3
    assert analyzer.params.confidence == 0.7  # untouched default


def test_pipeline_builds_with_dummy_keys():
    """The pipeline wires together without network/keys (construction only)."""
    pytest.importorskip("pipecat")
    from pipecat.pipeline.task import PipelineTask
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from app.voice.pipeline import build_pipeline_task, build_services

    settings = Settings(
        _env_file=None, deepgram_api_key="x", anthropic_api_key="y", cartesia_api_key="z"
    )
    stt, llm, tts = build_services(settings)

    connection = SmallWebRTCConnection()
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    task = build_pipeline_task(transport, stt, llm, tts)
    assert isinstance(task, PipelineTask)
