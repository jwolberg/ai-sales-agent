"""Offline VAD endpointing replay harness (VAD-T2).

Feed a recorded WAV through the *real* Silero VAD and report where the caller's turn would be
declared over — i.e. the moment the live agent would start talking. This is the only layer that
can reproduce "the agent jumps in too soon": the text simulator (``app.simulator.benchmark``)
bypasses audio/VAD entirely, so it is blind to turn-taking timing.

The dominant dial is ``stop_secs`` — the trailing silence the VAD must observe before it ends the
turn. ``sweep_stop_secs`` runs one clip at several values so you can pick the smallest one that
stops cutting you off during natural mid-sentence pauses: on a clip that is *one* utterance with
pauses, the right ``stop_secs`` yields a single turn; too-low values split it into several.

No network, no Twilio — deterministic for a given clip. Usage:

    python -m app.simulator.vad_replay path/to/clip.wav --sweep 0.2,0.4,0.6,0.8,1.0
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

# Silero VAD runs at 16 kHz and consumes fixed 512-sample frames; one frame = 32 ms. We feed
# exactly one frame per step so every state reading maps to a precise timestamp.
VAD_SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
FRAME_BYTES = FRAME_SAMPLES * 2  # 16-bit mono PCM
FRAME_SECS = FRAME_SAMPLES / VAD_SAMPLE_RATE


@dataclass
class TurnSegment:
    """One detected caller turn: speech onset to the point VAD declared it over."""

    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class SweepRow:
    stop_secs: float
    num_turns: int
    segments: list[TurnSegment] = field(default_factory=list)


def load_wav_frames(path: str | Path) -> list[bytes]:
    """Read a WAV into a list of 512-sample (1024-byte) 16 kHz mono PCM frames.

    Converts width≠16-bit, stereo, and non-16 kHz clips with stdlib ``audioop`` so any recording
    works. The trailing partial frame (<32 ms) is dropped — irrelevant to endpointing.
    """
    import audioop
    import wave

    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        pcm = audioop.lin2lin(pcm, sampwidth, 2)
    if n_channels == 2:
        pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
    if framerate != VAD_SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, framerate, VAD_SAMPLE_RATE, None)

    n_frames = len(pcm) // FRAME_BYTES
    return [pcm[i * FRAME_BYTES : (i + 1) * FRAME_BYTES] for i in range(n_frames)]


def _build_analyzer(stop_secs: float, start_secs: float, confidence: float, min_volume: float):
    """Construct a real Silero VAD with the given dials (lazy import: optional ``voice`` extra)."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams

    return SileroVADAnalyzer(
        params=VADParams(
            stop_secs=stop_secs,
            start_secs=start_secs,
            confidence=confidence,
            min_volume=min_volume,
        )
    )


async def _run_states(frames: list[bytes], analyzer) -> list:
    """Feed frames one at a time and collect the VAD state after each."""
    analyzer.set_sample_rate(VAD_SAMPLE_RATE)
    states = []
    for frame in frames:
        states.append(await analyzer.analyze_audio(frame))
    return states


def _segments_from_states(states: list) -> list[TurnSegment]:
    """Collapse a per-frame VAD state stream into caller turns.

    A turn runs from the first ``SPEAKING`` frame (live "user started speaking") until VAD returns
    to ``QUIET`` — which only happens after ``stop_secs`` of trailing silence, the exact signal the
    live agent acts on. An unterminated final turn is closed at the clip's end.
    """
    from pipecat.audio.vad.vad_analyzer import VADState

    segments: list[TurnSegment] = []
    start: float | None = None
    for i, state in enumerate(states):
        t = i * FRAME_SECS
        if state == VADState.SPEAKING and start is None:
            start = t
        elif state == VADState.QUIET and start is not None:
            segments.append(TurnSegment(start, t))
            start = None
    if start is not None:
        segments.append(TurnSegment(start, len(states) * FRAME_SECS))
    return segments


def analyze_clip(
    path: str | Path | None = None,
    *,
    stop_secs: float = 0.6,
    start_secs: float = 0.2,
    confidence: float = 0.7,
    min_volume: float = 0.6,
    frames: list[bytes] | None = None,
    analyzer=None,
) -> list[TurnSegment]:
    """Return the caller turns Silero VAD would detect in ``path`` at the given dials.

    ``frames``/``analyzer`` are injection seams for tests and for reusing decoded audio across a
    sweep; normal callers pass only ``path``.
    """
    if frames is None:
        if path is None:
            raise ValueError("provide either path or frames")
        frames = load_wav_frames(path)
    analyzer = analyzer or _build_analyzer(stop_secs, start_secs, confidence, min_volume)
    states = asyncio.run(_run_states(frames, analyzer))
    return _segments_from_states(states)


def sweep_stop_secs(
    path: str | Path,
    values: list[float],
    *,
    start_secs: float = 0.2,
    confidence: float = 0.7,
    min_volume: float = 0.6,
) -> list[SweepRow]:
    """Run one clip at several ``stop_secs`` values; report how many turns each produces.

    On a clip that is one utterance with natural pauses, the smallest value yielding a single turn
    is the sweet spot — larger values only add latency, smaller ones split the utterance (the agent
    jumps in mid-thought).
    """
    frames = load_wav_frames(path)
    rows: list[SweepRow] = []
    for value in values:
        segments = analyze_clip(
            frames=frames,
            stop_secs=value,
            start_secs=start_secs,
            confidence=confidence,
            min_volume=min_volume,
        )
        rows.append(SweepRow(stop_secs=value, num_turns=len(segments), segments=segments))
    return rows


def _format_segments(segments: list[TurnSegment]) -> str:
    if not segments:
        return "  (no speech detected — check the clip is real speech at adequate volume)"
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(
            f"  turn {i}: speech {seg.start_s:5.2f}s → agent-go {seg.end_s:5.2f}s "
            f"(turn {seg.duration_s:4.2f}s)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", help="path to a WAV clip (any rate/width/channels)")
    parser.add_argument(
        "--sweep",
        help="comma-separated stop_secs values to compare, e.g. 0.2,0.4,0.6,0.8,1.0",
    )
    parser.add_argument("--stop-secs", type=float, default=0.6)
    parser.add_argument("--start-secs", type=float, default=0.2)
    parser.add_argument("--confidence", type=float, default=0.7)
    parser.add_argument("--min-volume", type=float, default=0.6)
    args = parser.parse_args(argv)

    if args.sweep:
        values = [float(v) for v in args.sweep.split(",") if v.strip()]
        print(f"Sweeping stop_secs over {values} on {args.clip}\n")
        for row in sweep_stop_secs(
            args.clip,
            values,
            start_secs=args.start_secs,
            confidence=args.confidence,
            min_volume=args.min_volume,
        ):
            print(f"stop_secs={row.stop_secs:.2f}  → {row.num_turns} turn(s)")
            print(_format_segments(row.segments))
            print()
        print(
            "Pick the smallest stop_secs that yields the turn count you expect for the clip "
            "(one utterance-with-pauses → 1 turn). Set it as vad_stop_secs in config.toml."
        )
    else:
        segments = analyze_clip(
            args.clip,
            stop_secs=args.stop_secs,
            start_secs=args.start_secs,
            confidence=args.confidence,
            min_volume=args.min_volume,
        )
        print(f"stop_secs={args.stop_secs:.2f} on {args.clip} → {len(segments)} turn(s)")
        print(_format_segments(segments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
