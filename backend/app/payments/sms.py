"""Twilio SMS sender (PAY1-T2).

Texts the hosted payment URL to the caller via the Twilio **Messages** REST API with HTTP basic
auth — raw HTTP through the stdlib, no ``twilio`` SDK and no new dependency, matching the voice
bridge's "raw REST" choice. The HTTP call sits behind an injectable ``post`` seam so tests run with
no network.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class SmsError(RuntimeError):
    """Raised when an SMS can't be sent — missing creds/destination or a Twilio API error. The
    engine treats this as non-fatal: the payment link still exists (shown on the dashboard), the
    caller just wasn't texted."""


# A POST transport: (url, form-data, basic-auth) -> parsed JSON. Real impl is urllib; tests fake it.
PostFn = Callable[[str, dict, tuple[str, str]], dict]


def _urllib_post(url: str, data: dict, auth: tuple[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode()
    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (trusted Twilio URL)
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # 4xx/5xx carry a JSON error body
        detail = exc.read().decode(errors="replace")
        raise SmsError(f"Twilio API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SmsError(f"Twilio request failed: {exc.reason}") from exc


@dataclass
class TwilioSmsSender:
    """Sends one SMS via Twilio Messages. Build from settings with :func:`get_sms_sender`."""

    account_sid: str
    auth_token: str
    from_number: str
    post: PostFn = _urllib_post  # injectable for tests

    def send(self, to: str, body: str) -> str:
        """Send ``body`` to ``to`` (E.164). Returns the Twilio message SID. Raises on a missing
        destination or an API failure."""
        if not to:
            raise SmsError("no destination number to text")
        url = _MESSAGES_URL.format(sid=self.account_sid)
        data = {"To": to, "From": self.from_number, "Body": body}
        result = self.post(url, data, (self.account_sid, self.auth_token))
        sid = result.get("sid")
        if not sid:
            raise SmsError(f"Twilio response missing message sid: {result!r}")
        return sid


def get_sms_sender(settings, *, post: PostFn = _urllib_post) -> TwilioSmsSender:
    """Build the sender from settings. Raises :class:`SmsError` when SMS isn't configured (Twilio
    SID + auth token + from-number) — callers check ``settings.sms_enabled`` first."""
    if not settings.sms_enabled:
        raise SmsError(
            "SMS disabled (need TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER)"
        )
    return TwilioSmsSender(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_from_number,
        post=post,
    )
