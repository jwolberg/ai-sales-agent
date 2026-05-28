"""Decider-led live voice bot (P4.5-T5).

Replaces the raw-Claude pipeline path. STT-final transcripts drive the ConversationEngine,
which decides what to say (router -> extract -> decide -> render) and the result is spoken via
TTS. Rendering is Hybrid (see docs/AGENT_INTEGRATION.md): fixed lines (rebuttals, escalation,
KB-4 fallback) are spoken verbatim, discovery questions / fit summaries are LLM-smoothed, and KB
answers are LLM-synthesized from approved snippets. Every rendered line passes the §18 output
guard before it's spoken. Turns and the decision trace are persisted.

Pipecat is imported here (the optional ``voice`` extra); ``app.voice.server`` imports ``run_bot``
lazily so the core app stays importable without it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from app.agent.decisioning import DiscoveryDecider
from app.agent.engine import ConversationEngine
from app.agent.extraction import LLMExtractor
from app.agent.guardrails import (
    CLAIMS_HUMAN,
    ESCALATION_MESSAGE,
    PROMISES_GUARANTEE,
    check_agent_output,
)
from app.agent.orchestrator import Orchestrator
from app.agent.persona import build_system_prompt
from app.agent.recorder import CallRecorder
from app.config import Settings
from app.db.session import SessionLocal, init_db
from app.voice.fillers import FillerBank
from app.voice.pipeline import (
    AUDIO_IN_SAMPLE_RATE,
    DebugTurnLogger,
    build_services,
    build_transport,
    configure_debug_logging,
)


def make_synthesizer(
    settings: Settings, *, client: object | None = None
) -> Callable[[str], str | None]:
    """Return a function that turns a render instruction into a spoken line via Claude.

    Used for GROUND (synthesize from approved snippets) and Hybrid SPEAK smoothing. The persona
    is the (cached) system prompt so output stays in voice. Returns ``None`` on any error, so
    ``render()`` degrades to the safe fallback / verbatim text rather than crashing the call.
    """
    system = build_system_prompt(settings)

    def synthesize(instruction: str) -> str | None:
        nonlocal client
        try:
            if client is None:
                import anthropic  # lazy

                client = anthropic.Anthropic(api_key=settings.anthropic_api_key or "")
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=400,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": instruction}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text or None
        except Exception as exc:  # never let a phrasing error drop the call
            logger.warning(f"synthesize failed, falling back: {exc}")
            return None

    return synthesize


def guard_output(text: str) -> str:
    """Enforce §18 on a rendered line before it's spoken.

    Hard-block claims-to-be-human and guarantees (substitute a safe handoff). Price figures are
    now approved KB content, so the price flag is advisory only (logged, not blocked).
    """
    violations = check_agent_output(text)
    if CLAIMS_HUMAN in violations or PROMISES_GUARANTEE in violations:
        logger.warning(f"output guardrail blocked a line {violations}; substituting handoff")
        return ESCALATION_MESSAGE
    return text


class EngineProcessor(FrameProcessor):
    """Drives the ConversationEngine from STT-final transcripts and speaks the result.

    The engine's per-turn work (LLM extraction + render synthesis) is sync, so it runs in a
    worker thread to avoid blocking the pipeline's event loop.
    """

    def __init__(self, engine: ConversationEngine, *, fillers: bool = False) -> None:
        super().__init__()
        self._engine = engine
        self._fillers = FillerBank() if fillers else None

    async def greet(self) -> None:
        greeting = await asyncio.to_thread(self._engine.open)
        spoken = guard_output(greeting)
        if spoken.strip():
            await self.push_frame(TTSSpeakFrame(spoken))

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            # Speak a filler immediately so the call doesn't fall silent while we compute.
            if self._fillers is not None:
                await self.push_frame(TTSSpeakFrame(self._fillers.pick(frame.text)))
            result = await asyncio.to_thread(self._engine.run_turn, frame.text)
            spoken = guard_output(result.utterance)
            if spoken.strip():
                await self.push_frame(TTSSpeakFrame(spoken))
        else:
            await self.push_frame(frame, direction)


def build_engine_pipeline_task(
    transport: SmallWebRTCTransport,
    stt: DeepgramSTTService,
    tts: CartesiaTTSService,
    engine_processor: EngineProcessor,
    *,
    voice_debug: bool = False,
) -> PipelineTask:
    """Assemble the decider-led pipeline: mic -> STT -> engine -> TTS -> speaker."""
    processors: list = [transport.input()]
    if voice_debug:
        processors.append(DebugTurnLogger("input"))
    processors.append(stt)
    if voice_debug:
        processors.append(DebugTurnLogger("stt"))
    processors += [engine_processor, tts, transport.output()]
    pipeline = Pipeline(processors)
    return PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=AUDIO_IN_SAMPLE_RATE,
        ),
    )


def build_engine(settings: Settings, *, recorder: CallRecorder | None = None) -> ConversationEngine:
    """Wire the conversation engine for the live path: DiscoveryDecider + LLM extraction + Claude
    phrasing, with an optional recorder for the transcript/decision trace."""
    orchestrator = Orchestrator(
        settings=settings, decider=DiscoveryDecider(), recorder=recorder
    )
    return ConversationEngine(
        orchestrator,
        extractor=LLMExtractor(settings=settings),
        synthesize=make_synthesizer(settings),
    )


async def run_bot(connection: SmallWebRTCConnection, settings: Settings) -> None:
    """Run one decider-led voice session for a connected peer until it disconnects."""
    if settings.voice_debug:
        configure_debug_logging()
    init_db()  # idempotent; ensures Call/Turn/Decision tables exist
    stt, _llm, tts = build_services(settings)  # _llm unused: the engine owns reasoning now
    db = SessionLocal()
    recorder = CallRecorder(db, channel="web")
    engine = build_engine(settings, recorder=recorder)
    processor = EngineProcessor(engine, fillers=settings.fillers)
    transport = build_transport(connection, settings)
    task = build_engine_pipeline_task(
        transport, stt, tts, processor, voice_debug=settings.voice_debug
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        await processor.greet()  # agent speaks first

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        await asyncio.to_thread(engine.orch.end)  # stamp ended_at
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        db.close()
