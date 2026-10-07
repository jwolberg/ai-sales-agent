"""Shared Pipecat builders for the realtime voice path: Deepgram STT, Cartesia TTS, Silero VAD, and
the WebRTC transport. The turn logic itself is the intent-router engine (app.voice.bot).

This module imports Pipecat (the optional ``voice`` extra). Import it lazily from
request handlers / startup so the core app stays importable without the extra.

Scope (P2-T1): wire the streaming pipeline with VAD turn-taking over WebRTC. A minimal
placeholder persona lives here; the full persona + decisioning land in P2-T3/P2-T4.
Interruptions are enabled (``allow_interruptions``) as the foundation that P2-T2 tunes.
"""

import sys
from pathlib import Path

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

# Persona lives in the agent layer (P2-T3) so the voice pipeline and the simulator
# share one source of truth. Re-exported here for backward-compatible imports.
from app.agent.persona import build_greeting_cue, build_system_prompt
from app.config import Settings, get_settings

# NOTE: the live bot lives in app.voice.bot (decider-led runtime, P4.5-T5). The legacy raw-Claude
# `build_pipeline_task` was removed in ticket 0010: nothing ran it, and it was the only user of
# Pipecat's deprecated OpenAILLMContext/aggregator APIs.
__all__ = [
    "build_system_prompt",
    "build_greeting_cue",
    "build_services",
    "build_transport",
    "build_vad_analyzer",
]

# Deepgram requires an explicit sample rate with linear16. The transport must declare it
# (its default is None, which Pipecat serializes to "None" -> Deepgram HTTP 400); the
# transport resamples the browser's 48 kHz WebRTC audio down to this.
AUDIO_IN_SAMPLE_RATE = 16000

# backend/app/voice/pipeline.py -> repo root is four levels up (for the ambient asset).
REPO_ROOT = Path(__file__).resolve().parents[3]
AMBIENT_WAV = REPO_ROOT / "data" / "audio" / "ambient.wav"


def _build_ambient_mixer(settings: Settings):
    """Looping room-tone bed mixed under the agent's voice (output-only). Lazy-imports
    SoundfileMixer so `soundfile` is only required when ambient noise is enabled."""
    from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer

    return SoundfileMixer(
        sound_files={"ambient": str(AMBIENT_WAV)},
        default_sound="ambient",
        volume=settings.ambient_volume,
        loop=True,
    )


class _DeepgramSTTService(DeepgramSTTService):
    """Work around two pipecat-0.0.108 serialization bugs that make Deepgram reject the
    streaming WebSocket with HTTP 400 (silently masked by the SDK as "Unexpected error
    when initializing websocket connection"):

    1. ``language`` is sent as ``str(Language.EN)`` -> "Language.EN" instead of the
       BCP-47 value "en". Settings coerces any string back to the enum, so the only
       reliable fix is to re-serialize the enum's ``.value`` here.
    2. ``sample_rate`` can still be 0/None at connect time if the pipeline hasn't
       propagated it yet; pin it to our known input rate so the query param is valid.

    Verified against Deepgram live: with these two corrected, the handshake is accepted.
    """

    def _build_connect_kwargs(self) -> dict:
        kwargs = super()._build_connect_kwargs()
        language = self._settings.language
        if language is not None and hasattr(language, "value"):
            kwargs["language"] = str(language.value)
        if kwargs.get("sample_rate") in (None, "0", "None"):
            kwargs["sample_rate"] = str(AUDIO_IN_SAMPLE_RATE)
        return kwargs


def configure_debug_logging() -> None:
    """Quiet Pipecat's INFO chatter to warnings-only while keeping our app markers.

    Idempotent. Without this the console floods with framework logs and the inbound-audio
    markers are impossible to find.
    """
    if getattr(configure_debug_logging, "_done", False):
        return
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        filter=lambda r: r["name"].startswith("app") or r["level"].no >= logger.level("WARNING").no,
    )
    configure_debug_logging._done = True


class DebugTurnLogger(FrameProcessor):
    """Logs the inbound audio path (audio arrival, VAD, transcripts) for diagnosis.

    Placed at two points: just after the transport (sees audio + VAD) and just after STT
    (sees transcripts). A silent log here tells us exactly which link is broken.
    """

    def __init__(self, label: str):
        super().__init__()
        self._label = label
        self._audio_seen = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            if not self._audio_seen:
                self._audio_seen = True
                logger.info(f"[{self._label}] 🎤 inbound audio arriving (first frame from browser)")
        elif isinstance(frame, UserStartedSpeakingFrame):
            logger.info(f"[{self._label}] 🗣️  VAD: user started speaking")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.info(f"[{self._label}] 🤫 VAD: user stopped speaking")
        elif isinstance(frame, InterimTranscriptionFrame):
            logger.info(f"[{self._label}] 📝 STT interim: {frame.text!r}")
        elif isinstance(frame, TranscriptionFrame):
            logger.info(f"[{self._label}] ✅ STT final: {frame.text!r}")
        await self.push_frame(frame, direction)


def build_services(settings: Settings) -> tuple[DeepgramSTTService, CartesiaTTSService]:
    """Construct the STT and TTS services from configured keys. (No LLM service: the
    intent-router engine owns reasoning.)"""
    # Use the patched STT: pins sample_rate and fixes Deepgram language serialization
    # (both otherwise cause a masked HTTP 400 on the streaming WebSocket).
    stt = _DeepgramSTTService(
        api_key=settings.deepgram_api_key or "",
        sample_rate=AUDIO_IN_SAMPLE_RATE,
    )
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key or "",
        settings=CartesiaTTSService.Settings(voice=settings.cartesia_voice_id),
    )
    if settings.voice_debug:
        logger.info(f"🔧 STT configured with sample_rate={AUDIO_IN_SAMPLE_RATE} (fix active)")
    return stt, tts


def build_vad_analyzer(settings: Settings) -> SileroVADAnalyzer:
    """Build the Silero VAD with the configured endpointing dials (VAD-T1).

    Centralizing this keeps the WebRTC and Twilio paths on identical turn-taking behavior.
    ``vad_stop_secs`` is the dominant lever for "agent jumps in too soon" — see config.py.
    """
    return SileroVADAnalyzer(
        params=VADParams(
            stop_secs=settings.vad_stop_secs,
            start_secs=settings.vad_start_secs,
            confidence=settings.vad_confidence,
            min_volume=settings.vad_min_volume,
        )
    )


def build_transport(
    connection: SmallWebRTCConnection, settings: Settings | None = None
) -> SmallWebRTCTransport:
    """Wrap a WebRTC connection in a transport with Silero VAD turn-taking.

    When ``ambient_noise`` is on, mixes a looping room-tone bed into the output (P4.5-T6).
    """
    settings = settings or get_settings()
    params_kwargs = dict(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_in_sample_rate=AUDIO_IN_SAMPLE_RATE,
        audio_out_sample_rate=settings.audio_out_sample_rate,
        vad_analyzer=build_vad_analyzer(settings),
    )
    if settings.ambient_noise:
        params_kwargs["audio_out_mixer"] = _build_ambient_mixer(settings)
    return SmallWebRTCTransport(
        webrtc_connection=connection, params=TransportParams(**params_kwargs)
    )
