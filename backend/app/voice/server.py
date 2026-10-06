"""WebRTC signaling endpoints for the voice demo.

Pipecat is imported lazily inside the handler so importing this router never requires
the optional ``voice`` extra. Missing keys or deps produce a clear 503.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/voice", tags=["voice"])

# Keep references to running bot tasks so they aren't garbage-collected mid-call.
_active_tasks: set[asyncio.Task] = set()


class Offer(BaseModel):
    sdp: str
    type: str
    pc_id: str | None = None


@router.get("/status")
def voice_status() -> dict:
    """Report whether the voice pipeline is configured (used by the demo client)."""
    settings = get_settings()
    missing = settings.missing_voice_keys()
    return {
        "ready": not missing,
        "missing_keys": missing,
        "model": settings.anthropic_model,
    }


@router.post("/offer")
async def voice_offer(offer: Offer) -> dict:
    """Accept a browser SDP offer, start a bot session, and return the SDP answer."""
    settings = get_settings()
    missing = settings.missing_voice_keys()
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Voice not configured. Set: {', '.join(missing)} in backend/.env",
        )

    try:
        from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

        from app.voice.bot import run_bot
    except ImportError as exc:  # voice extra not installed
        raise HTTPException(
            status_code=503,
            detail=f"Voice dependencies missing — run: pip install -e '.[voice]' ({exc})",
        ) from exc

    connection = SmallWebRTCConnection(ice_servers=["stun:stun.l.google.com:19302"])
    await connection.initialize(sdp=offer.sdp, type=offer.type)

    task = asyncio.create_task(run_bot(connection, settings))
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return connection.get_answer()


# --- Twilio inbound (IR7-T7) -----------------------------------------------------------


@router.api_route("/twilio", methods=["GET", "POST"])
async def twilio_voice(request: Request) -> Response:
    """Twilio Voice webhook: return TwiML that streams the call's audio to our WebSocket.

    Point a Twilio number's Voice webhook at https://<public-host>/voice/twilio.
    """
    settings = get_settings()
    if settings.missing_voice_keys():
        # Speak a clear message rather than failing silently on the call.
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?><Response><Say>'
            "Sorry, the assistant is not configured right now. Goodbye."
            "</Say><Hangup/></Response>"
        )
        return Response(content=twiml, media_type="application/xml")
    from app.voice.twilio_bot import build_twiml, stream_ws_url

    # The caller's number (Twilio posts `From`) is threaded through the TwiML so the bot can text
    # the payment link without asking for it (caller-ID auto-text). Parse the urlencoded body with
    # the stdlib so we don't pull in python-multipart just for this.
    from_number = request.query_params.get("From")
    if from_number is None:
        from urllib.parse import parse_qs

        raw = (await request.body()).decode("utf-8", "ignore")
        from_number = (parse_qs(raw).get("From") or [None])[0]
    host = request.headers.get("host", request.url.netloc)
    return Response(
        content=build_twiml(stream_ws_url(settings, host), from_number=from_number),
        media_type="application/xml",
    )


@router.websocket("/twilio/ws")
async def twilio_ws(websocket: WebSocket) -> None:
    """Media Streams WebSocket: bridge Twilio audio into the intent-router engine."""
    settings = get_settings()
    if settings.missing_voice_keys():
        await websocket.close(code=1011)
        return
    try:
        from app.voice.twilio_bot import run_twilio_bot
    except ImportError:
        await websocket.close(code=1011)
        return
    await run_twilio_bot(websocket, settings)
