"""WebRTC signaling endpoints for the voice demo.

Pipecat is imported lazily inside the handler so importing this router never requires
the optional ``voice`` extra. Missing keys or deps produce a clear 503.
"""

import asyncio

from fastapi import APIRouter, HTTPException
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

        from app.voice.pipeline import run_bot
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
