"""Authenticate Twilio's inbound voice webhook and its Media Streams WebSocket (ticket 0002).

Webhook: Twilio signs every request with ``X-Twilio-Signature`` = base64(HMAC-SHA1(auth_token,
url + sorted POST params)). We recompute it over the *public* URL Twilio called (TLS is terminated
upstream on Cloud Run, so the app itself sees http).

Media Streams: the WebSocket handshake carries nothing we can verify, so the signed webhook issues
a per-call token (HMAC over CallSid + caller id) as a TwiML ``<Parameter>``. Twilio echoes it in the
stream's ``start`` frame, and the bot checks it before spending anything on STT/LLM/TTS. Binding
the caller id means a valid token can't be replayed onto another call or another ``From`` number —
which matters because the engine auto-texts payment links to that number.

Implemented inline (stdlib hmac) rather than pulling in the ``twilio`` SDK for one function.
Without a ``TWILIO_AUTH_TOKEN`` there is nothing to verify against: open in ``development``, refused
everywhere else.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping, Sequence

from fastapi import Request

from app.config import Settings


def compute_signature(auth_token: str, url: str, params: Mapping[str, Sequence[str]]) -> str:
    """Twilio's request signature: HMAC-SHA1 over the URL plus each sorted param name+value."""
    payload = url
    for name in sorted(params):
        for value in sorted(params[name]):
            payload += name + value
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def is_valid_request(
    auth_token: str, url: str, params: Mapping[str, Sequence[str]], signature: str | None
) -> bool:
    if not signature:
        return False
    expected = compute_signature(auth_token, url, params)
    return hmac.compare_digest(expected.encode(), signature.encode())


def public_request_url(request: Request, settings: Settings) -> str:
    """The URL Twilio actually requested — what its signature covers."""
    query = f"?{request.url.query}" if request.url.query else ""
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}{request.url.path}{query}"
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    scheme = proto or request.url.scheme
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}{request.url.path}{query}"


def stream_token(auth_token: str, call_sid: str, from_number: str | None) -> str:
    message = f"media-stream|{call_sid}|{from_number or ''}".encode()
    return hmac.new(auth_token.encode(), message, hashlib.sha256).hexdigest()


def stream_authorized(
    settings: Settings, call_sid: str | None, from_number: str | None, token: str | None
) -> bool:
    """Whether a Media Streams ``start`` frame may run the (paid) voice pipeline."""
    if not settings.twilio_auth_token:
        return settings.environment == "development"
    if not call_sid or not token:
        return False
    expected = stream_token(settings.twilio_auth_token, call_sid, from_number)
    return hmac.compare_digest(expected.encode(), token.encode())
