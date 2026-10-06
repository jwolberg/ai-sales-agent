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
import time

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.filters.stt_mute_filter import (
    STTMuteConfig,
    STTMuteFilter,
    STTMuteStrategy,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from app.agent.brain import get_brain
from app.agent.guardrails import (
    CLAIMS_HUMAN,
    ESCALATION_MESSAGE,
    PROMISES_GUARANTEE,
    check_agent_output,
)
from app.agent.intent_engine import IntentRouterEngine
from app.agent.latency import compose_turn_latency
from app.agent.recorder import CallRecorder
from app.agent.versioning import compute_versions
from app.config import Settings
from app.db.session import SessionLocal, init_db
from app.memory.lead_store import LeadStore, all_known_fields
from app.voice.fillers import FillerBank
from app.voice.pipeline import (
    AUDIO_IN_SAMPLE_RATE,
    DebugTurnLogger,
    build_services,
    build_transport,
    configure_debug_logging,
)


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


def _transcript_confidence(frame: TranscriptionFrame) -> float | None:
    """Pull Deepgram's word confidence off a final transcript, if present.

    ``TranscriptionFrame.result`` carries the raw Deepgram message; the top alternative's
    ``confidence`` is what we use to gate acting on a possibly-misheard turn. Defensive: any
    shape we don't recognize returns None (treated as "trust it").
    """
    result = getattr(frame, "result", None)
    try:
        alternatives = result.channel.alternatives
        return float(alternatives[0].confidence) if alternatives else None
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


class EngineProcessor(FrameProcessor):
    """Drives the ConversationEngine from STT-final transcripts and speaks the result.

    The engine's per-turn work (the brain's tool-calling decision) is sync, so it runs in a
    worker thread to avoid blocking the pipeline's event loop.
    """

    def __init__(self, engine: IntentRouterEngine, *, fillers: bool = False) -> None:
        super().__init__()
        self._engine = engine
        self._fillers = FillerBank() if fillers else None
        # Transcripts before the greeting is dispatched are connect-time noise/echo, not a real
        # turn. Real call 8b72f75c recorded a phantom "Good early." turn *before* the greeting,
        # which drove a spurious discovery question. Drop transcripts until we've greeted.
        self._ready = False
        # End-to-end latency timing (LAT-T2). We stamp monotonic boundaries as frames flow and,
        # on the first agent-audio frame, attach the stt/brain/tts breakdown to the agent turn.
        self._user_stopped_at: float | None = None
        # {turn_id, user_stopped_at, transcript_at, brain_done_at}; closed by the first agent audio.
        self._pending: dict | None = None

    async def greet(self) -> None:
        greeting = await asyncio.to_thread(self._engine.open)
        spoken = guard_output(greeting)
        if spoken.strip():
            await self.push_frame(TTSSpeakFrame(spoken))
        self._ready = True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        # Latency boundaries (LAT-T2): VAD stop starts the clock; the first agent-audio frame ends
        # it. These frames pass straight through — we only read their arrival time.
        if isinstance(frame, UserStoppedSpeakingFrame):
            self._user_stopped_at = time.monotonic()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, BotStartedSpeakingFrame):
            await self._finalize_latency()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TranscriptionFrame) and not self._ready:
            logger.debug(f"dropping pre-greeting transcript: {frame.text!r}")
            return
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            transcript_at = time.monotonic()
            # Speak a filler immediately so the call doesn't fall silent while we compute.
            if self._fillers is not None:
                await self.push_frame(TTSSpeakFrame(self._fillers.pick(frame.text)))
            confidence = _transcript_confidence(frame)
            result = await asyncio.to_thread(
                self._engine.run_turn, frame.text, confidence=confidence
            )
            spoken = guard_output(result.utterance)
            if spoken.strip():
                await self.push_frame(TTSSpeakFrame(spoken))
            # Arm the latency finalizer for this turn; the next agent-audio frame closes it.
            if result.agent_turn_id is not None:
                self._pending = {
                    "turn_id": result.agent_turn_id,
                    "user_stopped_at": self._user_stopped_at,
                    "transcript_at": transcript_at,
                    "brain_done_at": time.monotonic(),
                }
            self._user_stopped_at = None
        else:
            await self.push_frame(frame, direction)

    async def _finalize_latency(self) -> None:
        """On the first agent-audio frame, stamp the end-to-end latency + breakdown on the turn.

        Best-effort telemetry — the exact frame timing needs a real call to validate. With fillers
        on, the first agent audio may be the filler, so this reflects perceived time-to-first-audio.
        """
        pending, self._pending = self._pending, None
        if pending is None:
            return
        total, breakdown = compose_turn_latency(
            user_stopped_at=pending["user_stopped_at"],
            transcript_at=pending["transcript_at"],
            brain_done_at=pending["brain_done_at"],
            bot_started_at=time.monotonic(),
        )
        recorder = getattr(self._engine, "recorder", None)
        if recorder is not None:
            await asyncio.to_thread(
                recorder.update_turn_latency,
                pending["turn_id"],
                latency_ms=total,
                breakdown=breakdown,
            )


def build_engine_pipeline_task(
    transport: SmallWebRTCTransport,
    stt: DeepgramSTTService,
    tts: CartesiaTTSService,
    engine_processor: EngineProcessor,
    *,
    voice_debug: bool = False,
) -> PipelineTask:
    """Assemble the decider-led pipeline: mic -> mute-while-speaking -> STT -> engine -> TTS ->
    speaker.

    The STTMuteFilter mutes the mic input whenever the *agent* is speaking (STTMuteStrategy.ALWAYS,
    driven by Bot{Started,Stopped}SpeakingFrame). This stops the agent from transcribing its own
    TTS output (and echo) and treating it as a new user turn — the root cause of the "agent talks
    to itself / keeps launching new prompts" failure. It must sit before STT so the agent's audio
    never reaches Deepgram.
    """
    processors: list = [transport.input()]
    processors.append(STTMuteFilter(config=STTMuteConfig(strategies={STTMuteStrategy.ALWAYS})))
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


def build_engine(
    settings: Settings,
    *,
    recorder: CallRecorder | None = None,
    known_fields: dict[str, str] | None = None,
    caller_number: str | None = None,
) -> IntentRouterEngine:
    """Wire the intent-router engine for the live path: the brain (OpenAI when keyed, else the
    offline RuleBrain) + an optional recorder for the transcript/decision trace.

    ``known_fields`` seeds the agent with what we already know about this lead (P10-T1) so it
    skips/confirms instead of re-asking (LM-1/LM-3); any that map to taxonomy slots pre-fill the
    classification state. ``caller_number`` is the phone call's caller ID, used to text a payment
    link without prompting (PAY3-T2).
    """
    return IntentRouterEngine(
        brain=get_brain(settings),
        recorder=recorder,
        lead_fields=known_fields,
        settings=settings,
        caller_number=caller_number,
    )


async def run_bot(connection: SmallWebRTCConnection, settings: Settings) -> None:
    """Run one decider-led voice session for a connected peer until it disconnects."""
    if settings.voice_debug:
        configure_debug_logging()
    init_db()  # idempotent; ensures Call/Turn/Decision tables exist
    stt, _llm, tts = build_services(settings)  # _llm unused: the engine owns reasoning now
    db = SessionLocal()
    # Continue from a known lead's prior-call memory when one is configured (P10-T1). Anonymous
    # web sessions (no demo_lead_id, or an unknown id) start cold, as before.
    lead_store = LeadStore(db)
    lead = lead_store.load(settings.demo_lead_id) if settings.demo_lead_id else None
    lead_id = lead.lead_id if lead is not None else None
    # Seed *all* prior slots (typed columns + extra discovery slots), not just the nine profile
    # columns, so nothing learned earlier gets re-asked (P10-T3).
    seeded = all_known_fields(lead) if lead is not None else None
    if lead is not None:
        logger.info(f"continuing lead {lead_id} with known fields: {sorted(seeded)}")
    recorder = CallRecorder(
        db,
        lead_id=lead_id,
        channel="web",
        vad_params=settings.vad_params(),  # record turn-taking dials for the dashboard evaluator
        **compute_versions(settings).as_dict(),
    )
    engine = build_engine(settings, recorder=recorder, known_fields=seeded)
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
        await asyncio.to_thread(engine.end)  # CALL_COMPLETED + stamp ended_at
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        db.close()
