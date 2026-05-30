"""Tests for the offline VAD replay harness (VAD-T2).

Segment/sweep logic is tested with a scripted fake VAD (no real audio needed); the WAV loader is
tested against generated clips so resample/mono/width conversion paths run. The real Silero path
is exercised only when a clip is provided — see docs/RUNBOOK.md.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

pytest.importorskip("pipecat")  # VADState lives in pipecat; the harness imports it lazily

from pipecat.audio.vad.vad_analyzer import VADState  # noqa: E402

from app.simulator.vad_replay import (  # noqa: E402
    FRAME_BYTES,
    FRAME_SECS,
    VAD_SAMPLE_RATE,
    analyze_clip,
    load_wav_frames,
)


class _ScriptedVAD:
    """Returns a pre-scripted VADState per frame, so turn extraction is tested deterministically."""

    def __init__(self, states: list[VADState]) -> None:
        self._states = states
        self._i = 0

    def set_sample_rate(self, _sr: int) -> None:
        pass

    async def analyze_audio(self, _buffer: bytes) -> VADState:
        state = self._states[self._i]
        self._i += 1
        return state


def _frames(n: int) -> list[bytes]:
    return [b"\x00" * FRAME_BYTES] * n


def test_single_turn_extracted_with_stop_silence():
    # quiet → speaking (a turn) → stopping → quiet (turn ends). One turn.
    Q, S, P = VADState.QUIET, VADState.SPEAKING, VADState.STOPPING
    states = [Q, S, S, S, P, P, Q, Q]
    segments = analyze_clip(frames=_frames(len(states)), analyzer=_ScriptedVAD(states))
    assert len(segments) == 1
    assert segments[0].start_s == pytest.approx(1 * FRAME_SECS)
    assert segments[0].end_s == pytest.approx(6 * FRAME_SECS)  # frame index of the QUIET return


def test_two_turns_when_pause_long_enough_to_reach_quiet():
    Q, S = VADState.QUIET, VADState.SPEAKING
    states = [S, S, Q, Q, S, S, Q]  # speak, end, speak again, end
    segments = analyze_clip(frames=_frames(len(states)), analyzer=_ScriptedVAD(states))
    assert len(segments) == 2


def test_unterminated_turn_closed_at_clip_end():
    Q, S = VADState.QUIET, VADState.SPEAKING
    states = [Q, S, S, S]  # never returns to QUIET
    segments = analyze_clip(frames=_frames(len(states)), analyzer=_ScriptedVAD(states))
    assert len(segments) == 1
    assert segments[0].end_s == pytest.approx(len(states) * FRAME_SECS)


def test_no_speech_yields_no_turns():
    states = [VADState.QUIET] * 5
    segments = analyze_clip(frames=_frames(len(states)), analyzer=_ScriptedVAD(states))
    assert segments == []


def _write_wav(path, *, framerate: int, n_channels: int, n_samples: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * n_samples * n_channels)


def test_load_wav_frames_native_rate(tmp_path):
    wav = tmp_path / "a.wav"
    _write_wav(wav, framerate=VAD_SAMPLE_RATE, n_channels=1, n_samples=512 * 3)
    assert len(load_wav_frames(wav)) == 3  # 3 full 512-sample frames, partial dropped


def test_load_wav_frames_resamples_and_downmixes(tmp_path):
    # 8 kHz stereo → resampled to 16 kHz mono. 512 samples @8k ≈ 1024 @16k = 2 frames; assert >0.
    wav = tmp_path / "b.wav"
    _write_wav(wav, framerate=8000, n_channels=2, n_samples=512 * 4)
    assert len(load_wav_frames(wav)) > 0


# --- Real Silero VAD against the committed fixtures (VAD-T5) -----------------------------------
# These exercise the full audio→VAD path end-to-end on canonical clips, so the harness can't
# silently rot. Assertions are on *relationships* (more splits when stricter, real turns preserved),
# not exact counts, so a Silero model bump won't make them brittle.
_FIXTURES = Path(__file__).resolve().parents[2] / "data" / "audio" / "vad_fixtures"
_has_fixtures = (_FIXTURES / "midsentence_pause.wav").exists()
real_vad = pytest.mark.skipif(
    not _has_fixtures, reason="VAD fixtures not generated (see generate.sh)"
)


@real_vad
def test_midsentence_pause_splits_when_too_aggressive_but_merges_when_relaxed():
    clip = _FIXTURES / "midsentence_pause.wav"
    aggressive = analyze_clip(clip, stop_secs=0.2)
    relaxed = analyze_clip(clip, stop_secs=1.0)
    # One utterance with a ~0.7s pause: the 0.2s default cuts it short (the agent jumps in),
    # while a relaxed stop_secs treats the pause as one turn — the whole point of the dial.
    assert len(aggressive) >= 2
    assert len(relaxed) == 1


@real_vad
def test_two_real_utterances_are_not_merged_by_a_relaxed_stop_secs():
    clip = _FIXTURES / "two_utterances.wav"
    # A genuine ~1.5s gap stays two turns even when relaxed — raising the dial must not swallow
    # real turn boundaries.
    assert len(analyze_clip(clip, stop_secs=1.0)) >= 2
