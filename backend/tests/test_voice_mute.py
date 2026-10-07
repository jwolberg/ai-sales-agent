"""BotSpeakingMute (ticket 0010): replaces Pipecat's deprecated STTMuteFilter(ALWAYS).

While the agent is speaking, the caller's audio / VAD / transcription frames are dropped before STT
so the agent never transcribes its own voice (echo) or gets barged in on by it; everything else
passes. Driven through Pipecat's own test pipeline, no audio or keys.
"""

import asyncio

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.tests.utils import SleepFrame, run_test  # noqa: E402

from app.voice.mute import BotSpeakingMute  # noqa: E402


def _audio() -> InputAudioRawFrame:
    return InputAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=16000, num_channels=1)


def _transcript(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="t")


def _down(frames):
    down, _up = asyncio.run(run_test(BotSpeakingMute(), frames_to_send=frames))
    return down


def test_user_frames_pass_while_bot_silent():
    down = _down([_audio(), VADUserStartedSpeakingFrame(), _transcript("hi")])
    assert [type(f) for f in down] == [
        InputAudioRawFrame,
        VADUserStartedSpeakingFrame,
        TranscriptionFrame,
    ]


def test_user_frames_dropped_while_bot_speaks_then_resume():
    down = _down(
        [
            BotStartedSpeakingFrame(),
            _audio(),
            VADUserStartedSpeakingFrame(),
            UserStartedSpeakingFrame(),
            InterimTranscriptionFrame(text="ech", user_id="caller", timestamp="t"),
            _transcript("echo of the agent"),
            TextFrame(text="non-user frames still flow"),
            # Pipecat runs system frames (Bot*Speaking, audio, VAD) ahead of queued data frames
            # (transcripts), so pace the script like real time — as Pipecat's own tests do.
            SleepFrame(sleep=0.05),
            BotStoppedSpeakingFrame(),
            SleepFrame(sleep=0.05),
            _transcript("real caller turn"),
        ]
    )
    texts = [f.text for f in down if isinstance(f, TranscriptionFrame)]
    assert texts == ["real caller turn"]
    assert not any(isinstance(f, (InputAudioRawFrame, VADUserStartedSpeakingFrame)) for f in down)
    assert any(isinstance(f, TextFrame) and "still flow" in f.text for f in down)
    # The bot-speaking markers themselves are never swallowed (downstream needs them).
    assert any(isinstance(f, BotStartedSpeakingFrame) for f in down)
    assert any(isinstance(f, BotStoppedSpeakingFrame) for f in down)


def test_cartesia_voice_comes_from_settings_without_deprecation(recwarn):
    from app.config import Settings
    from app.voice.pipeline import build_services

    settings = Settings(
        _env_file=None,
        deepgram_api_key="x",
        anthropic_api_key="y",
        cartesia_api_key="z",
        cartesia_voice_id="voice-123",
    )
    _stt, tts = build_services(settings)
    assert tts._settings.voice == "voice-123"
    ours = [w for w in recwarn.list if "app/voice" in str(w.filename)]
    assert not ours, [str(w.message) for w in ours]
