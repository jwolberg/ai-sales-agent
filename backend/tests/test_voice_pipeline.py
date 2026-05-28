import pytest

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
