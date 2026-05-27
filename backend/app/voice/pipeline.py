"""Pipecat realtime voice pipeline: Deepgram STT -> Claude -> Cartesia TTS.

This module imports Pipecat (the optional ``voice`` extra). Import it lazily from
request handlers / startup so the core app stays importable without the extra.

Scope (P2-T1): wire the streaming pipeline with VAD turn-taking over WebRTC. A minimal
placeholder persona lives here; the full persona + decisioning land in P2-T3/P2-T4.
Interruptions are enabled (``allow_interruptions``) as the foundation that P2-T2 tunes.
"""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.services.anthropic.llm import AnthropicLLMContext, AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from app.config import Settings

# Placeholder persona — replaced by the full persona/playbook in P2-T3.
DEFAULT_SYSTEM_PROMPT = (
    "You are a warm, consultative sales specialist for Varsity Tutors (Nerdy). "
    "Your goal is to understand the caller's tutoring needs and help them take a "
    "sensible next step. Be concise and natural — this is a spoken phone call, so "
    "keep replies short and ask one question at a time. Never invent prices, "
    "guarantees, or policies; if you are unsure, say so. Do not claim to be human."
)

# First-turn cue so the agent speaks first (Anthropic needs a user turn to respond to).
_GREETING_CUE = (
    "The call has just connected. Greet the caller warmly, introduce yourself as a "
    "Varsity Tutors specialist, and ask how you can help today."
)


def build_services(
    settings: Settings,
) -> tuple[DeepgramSTTService, AnthropicLLMService, CartesiaTTSService]:
    """Construct the STT, LLM, and TTS services from configured keys."""
    stt = DeepgramSTTService(api_key=settings.deepgram_api_key or "")
    llm = AnthropicLLMService(
        api_key=settings.anthropic_api_key or "", model=settings.anthropic_model
    )
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key or "", voice_id=settings.cartesia_voice_id
    )
    return stt, llm, tts


def build_pipeline_task(
    transport: SmallWebRTCTransport,
    stt: DeepgramSTTService,
    llm: AnthropicLLMService,
    tts: CartesiaTTSService,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> PipelineTask:
    """Assemble the streaming pipeline and return a runnable task.

    Frame order: mic in -> STT -> aggregate user turn -> Claude -> Cartesia TTS ->
    speaker out -> aggregate assistant turn (so context carries across turns).
    """
    context = AnthropicLLMContext(
        messages=[{"role": "user", "content": _GREETING_CUE}],
        system=system_prompt,
    )
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )
    # allow_interruptions=True is the barge-in foundation (P2-T2 tunes it).
    return PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))


def build_transport(connection: SmallWebRTCConnection) -> SmallWebRTCTransport:
    """Wrap a WebRTC connection in a transport with Silero VAD turn-taking."""
    params = TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(),
    )
    return SmallWebRTCTransport(webrtc_connection=connection, params=params)


async def run_bot(
    connection: SmallWebRTCConnection,
    settings: Settings,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> None:
    """Run one voice bot session for a connected WebRTC peer until it disconnects."""
    stt, llm, tts = build_services(settings)
    transport = build_transport(connection)
    task = build_pipeline_task(transport, stt, llm, tts, system_prompt)

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        # Trigger the agent's opening line.
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
