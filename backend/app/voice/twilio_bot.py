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

import json

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.filters.stt_mute_filter import (
    STTMuteConfig,
    STTMuteFilter,
    STTMuteStrategy,
)
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from app.agent.recorder import CallRecorder
from app.agent.versioning import compute_versions
from app.config import Settings
from app.db.session import SessionLocal, init_db
from app.voice.bot import EngineProcessor, build_engine
from app.voice.pipeline import build_services, configure_debug_logging


def build_twiml(ws_url: str) -> str:
    """TwiML that connects the inbound call's audio to our Media Streams WebSocket."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Connect><Stream url=\"{ws_url}\" /></Connect>"
        "</Response>"
    )


def stream_ws_url(settings: Settings, host: str, *, scheme: str = "wss") -> str:
    """The wss URL Twilio should stream to. Prefers a configured public base URL."""
    if settings.public_base_url:
        base = settings.public_base_url.rstrip("/").replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        return f"{base}/voice/twilio/ws"
    return f"{scheme}://{host}/voice/twilio/ws"


async def _read_start(websocket) -> tuple[str, str | None]:
    """Consume Twilio's opening frames and return (stream_sid, call_sid)."""
    async for message in websocket.iter_text():
        data = json.loads(message)
        if data.get("event") == "start":
            start = data["start"]
            return start["streamSid"], start.get("callSid")
    raise RuntimeError("Twilio stream closed before a 'start' frame")


async def run_twilio_bot(websocket, settings: Settings) -> None:
    """Run one inbound Twilio call through the intent-router engine."""
    if settings.voice_debug:
        configure_debug_logging()
    await websocket.accept()
    stream_sid, call_sid = await _read_start(websocket)
    logger.info(f"twilio stream {stream_sid} (call {call_sid}) connected")

    init_db()
    stt, _llm, tts = build_services(settings)  # _llm unused: the engine owns reasoning
    db = SessionLocal()
    recorder = CallRecorder(
        db, channel="twilio", **compute_versions(settings).as_dict()
    )
    engine = build_engine(settings, recorder=recorder)
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
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            # Mute the mic while the agent speaks so it never transcribes its own audio.
            STTMuteFilter(config=STTMuteConfig(strategies={STTMuteStrategy.ALWAYS})),
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
