"""Pipecat realtime voice pipeline: Deepgram STT -> Claude -> Cartesia TTS.

This module imports Pipecat (the optional ``voice`` extra). Import it lazily from
request handlers / startup so the core app stays importable without the extra.

Scope (P2-T1): wire the streaming pipeline with VAD turn-taking over WebRTC. A minimal
placeholder persona lives here; the full persona + decisioning land in P2-T3/P2-T4.
Interruptions are enabled (``allow_interruptions``) as the foundation that P2-T2 tunes.
"""

import sys

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    LLMRunFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.anthropic.llm import AnthropicLLMContext, AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

# Persona lives in the agent layer (P2-T3) so the voice pipeline and the simulator
# share one source of truth. Re-exported here for backward-compatible imports.
from app.agent.persona import build_greeting_cue, build_system_prompt
from app.config import Settings, get_settings

__all__ = [
    "build_system_prompt",
    "build_greeting_cue",
    "build_services",
    "build_pipeline_task",
    "build_transport",
    "run_bot",
]

# Deepgram requires an explicit sample rate with linear16. The transport must declare it
# (its default is None, which Pipecat serializes to "None" -> Deepgram HTTP 400); the
# transport resamples the browser's 48 kHz WebRTC audio down to this.
AUDIO_IN_SAMPLE_RATE = 16000


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
        filter=lambda r: r["name"].startswith("app")
        or r["level"].no >= logger.level("WARNING").no,
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


def build_services(
    settings: Settings,
) -> tuple[DeepgramSTTService, AnthropicLLMService, CartesiaTTSService]:
    """Construct the STT, LLM, and TTS services from configured keys."""
    # Set sample_rate explicitly: relying on pipeline propagation left it None, which
    # Pipecat serializes to "None" and Deepgram rejects with HTTP 400.
    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key or "",
        sample_rate=AUDIO_IN_SAMPLE_RATE,
    )
    llm = AnthropicLLMService(
        api_key=settings.anthropic_api_key or "", model=settings.anthropic_model
    )
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key or "", voice_id=settings.cartesia_voice_id
    )
    if settings.voice_debug:
        logger.info(f"🔧 STT configured with sample_rate={AUDIO_IN_SAMPLE_RATE} (fix active)")
    return stt, llm, tts


def build_pipeline_task(
    transport: SmallWebRTCTransport,
    stt: DeepgramSTTService,
    llm: AnthropicLLMService,
    tts: CartesiaTTSService,
    system_prompt: str | None = None,
    greeting_cue: str | None = None,
) -> PipelineTask:
    """Assemble the streaming pipeline and return a runnable task.

    Frame order: mic in -> STT -> aggregate user turn -> Claude -> Cartesia TTS ->
    speaker out -> aggregate assistant turn (so context carries across turns).
    Prompt and greeting default to the configured persona when not provided.
    """
    settings = get_settings()
    system_prompt = system_prompt or build_system_prompt(settings)
    greeting_cue = greeting_cue or build_greeting_cue(settings)
    context = AnthropicLLMContext(
        messages=[{"role": "user", "content": greeting_cue}],
        system=system_prompt,
    )
    context_aggregator = llm.create_context_aggregator(context)

    processors = [transport.input()]
    if settings.voice_debug:
        processors.append(DebugTurnLogger("input"))  # audio arrival + VAD
    processors.append(stt)
    if settings.voice_debug:
        processors.append(DebugTurnLogger("stt"))  # transcriptions
    processors += [
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ]
    pipeline = Pipeline(processors)
    # allow_interruptions=True is the barge-in foundation (P2-T2 tunes it).
    return PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=AUDIO_IN_SAMPLE_RATE,
        ),
    )


def build_transport(connection: SmallWebRTCConnection) -> SmallWebRTCTransport:
    """Wrap a WebRTC connection in a transport with Silero VAD turn-taking."""
    params = TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_in_sample_rate=AUDIO_IN_SAMPLE_RATE,
        vad_analyzer=SileroVADAnalyzer(),
    )
    return SmallWebRTCTransport(webrtc_connection=connection, params=params)


async def run_bot(
    connection: SmallWebRTCConnection,
    settings: Settings,
) -> None:
    """Run one voice bot session for a connected WebRTC peer until it disconnects."""
    if settings.voice_debug:
        configure_debug_logging()
    stt, llm, tts = build_services(settings)
    transport = build_transport(connection)
    task = build_pipeline_task(
        transport,
        stt,
        llm,
        tts,
        system_prompt=build_system_prompt(settings),
        greeting_cue=build_greeting_cue(settings),
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        # Trigger the agent's opening line.
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
