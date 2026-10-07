"""Twilio request-signature validation + Media Streams token (ticket 0002).

No pipecat needed: the security helpers and the webhook's reject paths run before any voice import.
Signatures in these tests are computed independently (HMAC-SHA1 over URL + sorted params, per
Twilio's spec) so the validator is checked against the algorithm, not against itself.
"""

import base64
import hashlib
import hmac
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.voice import server
from app.voice.twilio_security import (
    compute_signature,
    is_valid_request,
    stream_authorized,
    stream_token,
)

TOKEN = "test-auth-token"
CALL = {"CallSid": "CA123", "From": "+15551234567", "To": "+15557654321"}


def _reference_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


# --- signature algorithm -------------------------------------------------------------------------


def test_compute_signature_matches_reference_algorithm():
    url = "https://example.test/voice/twilio"
    expected = _reference_signature(TOKEN, url, CALL)
    assert compute_signature(TOKEN, url, {k: [v] for k, v in CALL.items()}) == expected


def test_is_valid_request_rejects_tampering():
    url = "https://example.test/voice/twilio"
    params = {k: [v] for k, v in CALL.items()}
    sig = compute_signature(TOKEN, url, params)
    assert is_valid_request(TOKEN, url, params, sig)
    assert not is_valid_request(TOKEN, url, {**params, "From": ["+19998887777"]}, sig)
    assert not is_valid_request(TOKEN, "https://evil.test/voice/twilio", params, sig)
    assert not is_valid_request("other-token", url, params, sig)
    assert not is_valid_request(TOKEN, url, params, None)
    assert not is_valid_request(TOKEN, url, params, "")


# --- webhook ------------------------------------------------------------------------------------


def _client(monkeypatch, **kwargs) -> TestClient:
    settings = Settings(_env_file=None, **kwargs)
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    return TestClient(app)


def _signed_post(
    client, params, *, url="http://testserver/voice/twilio", headers=None, token=TOKEN
):
    sig = _reference_signature(token, url, params)
    return client.post(
        "/voice/twilio",
        content=urlencode(params),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": sig,
            **(headers or {}),
        },
    )


def test_webhook_rejects_unsigned_request(monkeypatch):
    client = _client(monkeypatch, twilio_auth_token=TOKEN)
    resp = client.post("/voice/twilio", data=CALL)
    assert resp.status_code == 403


def test_webhook_rejects_forged_from(monkeypatch):
    client = _client(monkeypatch, twilio_auth_token=TOKEN)
    url = "http://testserver/voice/twilio"
    sig = _reference_signature(TOKEN, url, CALL)
    forged = {**CALL, "From": "+19998887777"}
    resp = client.post(
        "/voice/twilio",
        content=urlencode(forged),
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sig},
    )
    assert resp.status_code == 403


def test_webhook_accepts_signed_request(monkeypatch):
    client = _client(monkeypatch, twilio_auth_token=TOKEN)
    resp = _signed_post(client, CALL)
    assert resp.status_code == 200
    assert "<Response>" in resp.text


def test_webhook_validates_against_public_url_behind_proxy(monkeypatch):
    # Cloud Run terminates TLS: the app sees http, Twilio signed the https URL.
    client = _client(monkeypatch, twilio_auth_token=TOKEN)
    resp = _signed_post(
        client,
        CALL,
        url="https://testserver/voice/twilio",
        headers={"X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200


def test_webhook_validates_against_configured_public_base_url(monkeypatch):
    client = _client(monkeypatch, twilio_auth_token=TOKEN, public_base_url="https://abc.ngrok.app/")
    resp = _signed_post(client, CALL, url="https://abc.ngrok.app/voice/twilio")
    assert resp.status_code == 200


def test_webhook_fails_closed_without_auth_token_outside_development(monkeypatch):
    client = _client(monkeypatch, environment="production", twilio_auth_token=None)
    resp = client.post("/voice/twilio", data=CALL)
    assert resp.status_code == 503


def test_webhook_open_in_development_without_auth_token(monkeypatch):
    client = _client(monkeypatch, environment="development", twilio_auth_token=None)
    assert client.post("/voice/twilio", data=CALL).status_code == 200


# --- Media Streams token ------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_stream_token_binds_call_and_caller():
    s = _settings(twilio_auth_token=TOKEN)
    tok = stream_token(TOKEN, "CA123", "+15551234567")
    assert stream_authorized(s, "CA123", "+15551234567", tok)
    assert not stream_authorized(s, "CA999", "+15551234567", tok)  # replayed onto another call
    assert not stream_authorized(s, "CA123", "+19998887777", tok)  # swapped caller id
    assert not stream_authorized(s, "CA123", "+15551234567", None)
    assert not stream_authorized(s, "CA123", "+15551234567", "garbage")
    assert not stream_authorized(s, None, "+15551234567", tok)


def test_stream_token_without_caller_id():
    s = _settings(twilio_auth_token=TOKEN)
    tok = stream_token(TOKEN, "CA123", None)
    assert stream_authorized(s, "CA123", None, tok)
    assert not stream_authorized(s, "CA123", "+15551234567", tok)


def test_stream_unauthorized_without_auth_token_outside_development():
    assert not stream_authorized(_settings(environment="production"), "CA123", None, None)
    assert stream_authorized(_settings(environment="development"), "CA123", None, None)


@pytest.mark.parametrize("bad", ['+1" /><Hangup/><x a="', "<script>", "a&b"])
def test_twiml_escapes_caller_id(bad):
    pytest.importorskip("pipecat")
    from app.voice.twilio_bot import build_twiml

    xml = build_twiml("wss://example.test/voice/twilio/ws", from_number=bad, token="t")
    assert "<Hangup/>" not in xml and "<script>" not in xml
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)  # well-formed despite hostile input
    params = {p.get("name"): p.get("value") for p in root.iter("Parameter")}
    assert params == {"from": bad, "token": "t"}
