"""Turn-latency composition (LAT-T1).

Turns the monotonic timestamps the voice pipeline captures around one turn into an end-to-end
latency + an stt/brain/tts breakdown. Pure and side-effect-free so the math is unit-tested even
though the frame wiring that feeds it (``app/voice/bot.py``) needs a real call to exercise.

Boundaries (all monotonic seconds; any may be None if a frame wasn't observed):
- ``user_stopped_at``  — VAD said the caller stopped talking
- ``transcript_at``    — STT delivered the final transcript  (stt = transcript - user_stopped)
- ``brain_done_at``    — the engine finished deciding the reply (brain = brain_done - transcript)
- ``bot_started_at``   — the agent's first audio went out      (tts  = bot_started - brain_done)

The headline ``latency_ms`` is the caller-perceived turnaround: user_stopped → bot_started (or
transcript → bot_started when VAD's stop wasn't captured).
"""

from __future__ import annotations


def _ms(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start) * 1000, 1)


def compose_turn_latency(
    *,
    user_stopped_at: float | None,
    transcript_at: float | None,
    brain_done_at: float | None,
    bot_started_at: float | None,
) -> tuple[float | None, dict]:
    """Return ``(total_ms, {stt_ms, brain_ms, tts_ms})`` from the four turn boundaries."""
    breakdown = {
        "stt_ms": _ms(user_stopped_at, transcript_at),
        "brain_ms": _ms(transcript_at, brain_done_at),
        "tts_ms": _ms(brain_done_at, bot_started_at),
    }
    start = user_stopped_at if user_stopped_at is not None else transcript_at
    total = _ms(start, bot_started_at)
    return total, breakdown
