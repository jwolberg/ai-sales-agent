"""HTTP Basic auth gate for the operator surfaces (dashboard, API, voice demo).

Secure by default: every HTTP/WebSocket path requires credentials except ``PUBLIC_PATHS`` — the
liveness probe and the provider webhooks, which authenticate by signature instead. A new route is
therefore protected without anyone remembering to opt it in.

Implemented as plain ASGI middleware (not a FastAPI dependency) so it also covers the StaticFiles
mounts (/dashboard, /demo) and doesn't buffer the SSE stream. Browsers cache Basic credentials per
origin, so once the operator logs in at /dashboard the page's own fetch/EventSource calls carry
them automatically — no frontend changes needed.

With no ``DASHBOARD_PASSWORD`` set, ``environment == "development"`` stays open (local dev, tests);
any other environment fails closed with a 503.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets

from app.config import get_settings

# Exact paths that skip Basic auth. Exact-match (not prefix) so lookalikes stay protected.
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/voice/twilio",  # Twilio webhook — X-Twilio-Signature
        "/voice/twilio/ws",  # Twilio Media Streams — per-call stream token
        "/payments/webhook",  # Stripe webhook — Stripe-Signature
    }
)

_REALM = 'Basic realm="operator", charset="UTF-8"'


def _credentials_ok(header: str | None, username: str, password: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    user, sep, pw = decoded.partition(":")
    if not sep:
        return False
    # Compare both halves in constant time; `&` (not `and`) so both comparisons always run.
    return secrets.compare_digest(user.encode(), username.encode()) & secrets.compare_digest(
        pw.encode(), password.encode()
    )


class BasicAuthMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket") or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.dashboard_password:
            if settings.environment == "development":
                await self.app(scope, receive, send)
            else:
                await _reject(scope, send, 503, "Auth not configured: set DASHBOARD_PASSWORD")
            return

        headers = dict(scope.get("headers") or [])
        raw = headers.get(b"authorization")
        header = raw.decode("latin-1") if raw is not None else None
        if _credentials_ok(header, settings.dashboard_username, settings.dashboard_password):
            await self.app(scope, receive, send)
            return
        await _reject(scope, send, 401, "Authentication required")


async def _reject(scope, send, status: int, detail: str) -> None:
    if scope["type"] == "websocket":
        # Close before accept -> the handshake is refused (HTTP 403 to the client).
        await send({"type": "websocket.close", "code": 1008})
        return
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", _REALM.encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
