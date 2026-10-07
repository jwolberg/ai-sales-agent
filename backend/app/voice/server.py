"""WebRTC signaling endpoints for the voice demo.

Pipecat is imported lazily inside the handler so importing this router never requires
the optional ``voice`` extra. Missing keys or deps produce a clear 503.
"""

import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel

from app import limits, tasks
from app.config import get_settings
from app.voice.twilio_security import is_valid_request, public_request_url, stream_token

router = APIRouter(prefix="/voice", tags=["voice"])

logger = logging.getLogger(__name__)


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

    if not limits.session_slots.try_acquire(limit=settings.max_concurrent_sessions):
        logger.warning("voice offer refused: concurrent session limit reached")
        raise HTTPException(status_code=429, detail="Too many live calls; try again shortly")
    slots = limits.session_slots
    try:
        connection = SmallWebRTCConnection(ice_servers=["stun:stun.l.google.com:19302"])
        await connection.initialize(sdp=offer.sdp, type=offer.type)
        task = tasks.spawn(run_bot(connection, settings), name="voice-call")
    except BaseException:
        slots.release()
        raise
    task.add_done_callback(lambda _t: slots.release())

    return connection.get_answer()


# --- Twilio inbound (IR7-T7) -----------------------------------------------------------


@router.api_route("/twilio", methods=["GET", "POST"])
async def twilio_voice(request: Request) -> Response:
    """Twilio Voice webhook: return TwiML that streams the call's audio to our WebSocket.

    Point a Twilio number's Voice webhook at https://<public-host>/voice/twilio. The request must
    carry a valid ``X-Twilio-Signature`` (see app/voice/twilio_security.py) — otherwise anyone could
    forge a call and pick the ``From`` number the bot auto-texts payment links to.
    """
    settings = get_settings()
    # Parse the urlencoded body with the stdlib so we don't pull in python-multipart for this.
    raw = (await request.body()).decode("utf-8", "ignore") if request.method == "POST" else ""
    form = parse_qs(raw, keep_blank_values=True)
    if settings.twilio_auth_token:
        url = public_request_url(request, settings)
        signature = request.headers.get("x-twilio-signature")
        if not is_valid_request(settings.twilio_auth_token, url, form, signature):
            # Path only: the query string is attacker-controlled and can carry a phone number.
            logger.warning(
                "rejected Twilio webhook: bad or missing signature (%s)", request.url.path
            )
            return Response(status_code=403)
    elif settings.environment != "development":
        return Response("Twilio webhook not configured: set TWILIO_AUTH_TOKEN", status_code=503)

    if settings.missing_voice_keys():
        # Speak a clear message rather than failing silently on the call.
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?><Response><Say>'
            "Sorry, the assistant is not configured right now. Goodbye."
            "</Say><Hangup/></Response>"
        )
        return Response(content=twiml, media_type="application/xml")
    from app.voice.twilio_bot import build_twiml, stream_ws_url

    def _param(name: str) -> str | None:
        # GET webhooks carry params in the query string; POST in the (signed) body.
        return request.query_params.get(name) or (form.get(name) or [None])[0]

    # The caller's number is threaded through the TwiML so the bot can text the payment link
    # without asking for it (caller-ID auto-text); the stream token binds it to this call.
    from_number = _param("From")
    call_sid = _param("CallSid")
    token = (
        stream_token(settings.twilio_auth_token, call_sid, from_number)
        if settings.twilio_auth_token and call_sid
        else None
    )
    host = request.headers.get("host", request.url.netloc)
    return Response(
        content=build_twiml(stream_ws_url(settings, host), from_number=from_number, token=token),
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
    # Stream-token auth and the session-slot cap both happen inside, after the 'start' frame.
    await run_twilio_bot(websocket, settings)
