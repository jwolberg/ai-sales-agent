"""Twilio inbound voice bridge (IR7-T7).

Routes a phone call into the same intent-router brain as the web demo. Twilio Media Streams sends
the caller's audio over a WebSocket (μ-law 8kHz); Pipecat's ``TwilioFrameSerializer`` +
``FastAPIWebsocketTransport`` decode it into the existing STT → engine → TTS pipeline, and the call
surfaces on the dashboard tagged ``channel="twilio"`` (no dashboard changes needed).

Flow:
  1. Twilio hits the voice webhook -> we return TwiML opening a bidirectional <Stream> to /…/ws.
  2. Twilio connects the WebSocket and sends a "connected" then a "start" frame (streamSid/callSid).
  3. We build the serializer/transport from those ids and run the pipeline until the call ends.

Pipecat is imported lazily by the caller (the optional ``voice`` extra); this module is only
imported once the voice deps are present.

NOTE: the live audio loop (and telephony sample-rate/echo tuning) can only be validated with a real
inbound call to a configured Twilio number pointed at a public URL — see docs/RUNBOOK.md.
"""

from __future__ import annotations

import asyncio
import json
from xml.sax.saxutils import quoteattr

from loguru import logger
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from app import limits
from app.agent.recorder import CallRecorder
from app.agent.versioning import compute_versions
from app.config import Settings
from app.db.session import SessionLocal, init_db
from app.voice.bot import EngineProcessor, build_engine
from app.voice.mute import BotSpeakingMute
from app.voice.pipeline import build_services, build_vad_analyzer, configure_debug_logging
from app.voice.twilio_security import stream_authorized


def build_twiml(ws_url: str, *, from_number: str | None = None, token: str | None = None) -> str:
    """TwiML that connects the inbound call's audio to our Media Streams WebSocket.

    The caller's number (``From``) and the per-call stream token are passed as Stream
    ``<Parameter>``s so they arrive in the Media Streams ``start`` frame's ``customParameters`` —
    the engine uses ``from`` to text the payment link without prompting (caller-ID auto-text), and
    the bot checks ``token`` before running the pipeline. Values are XML-attribute-escaped: ``From``
    is caller-controlled input."""
    params = "".join(
        f"<Parameter name={quoteattr(name)} value={quoteattr(value)} />"
        for name, value in (("from", from_number), ("token", token))
        if value
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Connect><Stream url={quoteattr(ws_url)}>{params}</Stream></Connect>"
        "</Response>"
    )


def stream_ws_url(settings: Settings, host: str, *, scheme: str = "wss") -> str:
    """The wss URL Twilio should stream to. Prefers a configured public base URL."""
    if settings.public_base_url:
        base = (
            settings.public_base_url.rstrip("/")
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        return f"{base}/voice/twilio/ws"
    return f"{scheme}://{host}/voice/twilio/ws"


# An unauthenticated client can open this public socket; it gets this long to send a valid 'start'.
START_TIMEOUT_SECS = 10.0


async def _read_start(websocket) -> tuple[str, str | None, str | None, str | None] | None:
    """Consume Twilio's opening frames; return (stream_sid, call_sid, caller_number, token).

    ``caller_number`` and ``token`` are the ``from`` / ``token`` Stream parameters set in the
    TwiML (caller ID and the per-call stream token), or None. Returns None (never raises) if the
    socket closes first or sends anything malformed — the client is still unauthenticated here.
    """
    async for message in websocket.iter_text():
        try:
            data = json.loads(message)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        if data.get("event") == "start":
            start = data.get("start")
            if not isinstance(start, dict) or not start.get("streamSid"):
                return None
            params = start.get("customParameters") or {}
            if not isinstance(params, dict):
                return None
            return start["streamSid"], start.get("callSid"), params.get("from"), params.get("token")
    return None


async def _refuse(websocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except (RuntimeError, OSError):
        pass  # the client is already gone (Starlette: RuntimeError; uvicorn: ClientDisconnected)


async def run_twilio_bot(websocket, settings: Settings) -> None:
    """Run one inbound Twilio call through the intent-router engine."""
    if settings.voice_debug:
        configure_debug_logging()
    await websocket.accept()
    try:
        start = await asyncio.wait_for(_read_start(websocket), timeout=START_TIMEOUT_SECS)
    except TimeoutError:
        start = None
    if start is None:
        logger.warning("twilio stream: no valid 'start' frame, closing")
        await _refuse(websocket, 1008)
        return
    stream_sid, call_sid, caller_number, token = start
    # Reject before any session slot, DB row, or paid STT/TTS session exists (tickets 0002/0003).
    if not stream_authorized(settings, call_sid, caller_number, token):
        logger.warning(f"twilio stream {stream_sid}: missing/invalid stream token, closing")
        await _refuse(websocket, 1008)
        return
    # Only an authenticated call may take a paid-session slot, so idle or forged sockets can't
    # starve real callers.
    if not limits.session_slots.try_acquire(limit=settings.max_concurrent_sessions):
        logger.warning(f"twilio stream {stream_sid}: concurrent session limit reached, closing")
        await _refuse(websocket, 1013)  # "try again later"
        return
    slots = limits.session_slots
    try:
        await _run_authorized(websocket, settings, stream_sid, call_sid, caller_number)
    finally:
        slots.release()


async def _run_authorized(websocket, settings, stream_sid, call_sid, caller_number) -> None:
    logger.info(f"twilio stream {stream_sid} (call {call_sid}) connected")

    init_db()
    stt, tts = build_services(settings)
    db = SessionLocal()
    recorder = CallRecorder(
        db,
        channel="twilio",
        vad_params=settings.vad_params(),  # record turn-taking dials for the dashboard evaluator
        **compute_versions(settings).as_dict(),
    )
    # caller_number = Twilio `From` -> the engine texts the payment link to it without prompting.
    engine = build_engine(settings, recorder=recorder, caller_number=caller_number)
    processor = EngineProcessor(engine, fillers=settings.fillers)

    # auto_hang_up=False keeps us off the Twilio REST SDK (an extra dep): the call ends naturally
    # when the caller hangs up (Twilio closes the stream -> on_client_disconnected -> engine.end).
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=build_vad_analyzer(settings),
            serializer=serializer,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            # Mute the mic while the agent speaks so it never transcribes its own audio.
            BotSpeakingMute(),
            stt,
            processor,
            tts,
            transport.output(),
        ]
    )
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

    @transport.event_handler("on_client_connected")
    async def _on_connected(_t, _c):
        await processor.greet()  # the agent answers first

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_t, _c):
        import asyncio

        await asyncio.to_thread(engine.end)
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        db.close()
