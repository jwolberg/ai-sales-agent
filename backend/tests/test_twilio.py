"""Twilio inbound bridge tests (IR7-T7).

Construction-level only — TwiML + URL derivation + webhook wiring. The live audio loop needs a real
inbound call to a configured Twilio number (see docs/RUNBOOK.md) and isn't exercised here.
"""

import pytest

pytest.importorskip("pipecat")  # twilio_bot imports pipecat at module load

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import app  # noqa: E402
from app.voice.twilio_bot import build_twiml, run_twilio_bot, stream_ws_url  # noqa: E402


def test_build_twiml_opens_a_stream():
    xml = build_twiml("wss://example.test/voice/twilio/ws")
    assert xml.startswith("<?xml")
    assert "<Connect><Stream" in xml
    assert 'url="wss://example.test/voice/twilio/ws"' in xml


def test_build_twiml_passes_caller_id_parameter():
    xml = build_twiml("wss://example.test/voice/twilio/ws", from_number="+15551234567")
    assert '<Parameter name="from" value="+15551234567" />' in xml
    # No caller id -> no Parameter element.
    assert "<Parameter" not in build_twiml("wss://example.test/voice/twilio/ws")


def test_stream_ws_url_from_request_host():
    s = Settings(_env_file=None)
    assert stream_ws_url(s, "abc.ngrok.app") == "wss://abc.ngrok.app/voice/twilio/ws"


def test_stream_ws_url_prefers_public_base_url_and_rewrites_scheme():
    s = Settings(_env_file=None, public_base_url="https://abc.ngrok.app/")
    assert stream_ws_url(s, "ignored") == "wss://abc.ngrok.app/voice/twilio/ws"
    s2 = Settings(_env_file=None, public_base_url="http://localhost:8000")
    assert stream_ws_url(s2, "ignored") == "ws://localhost:8000/voice/twilio/ws"


def test_webhook_returns_twiml_xml(monkeypatch):
    # No voice keys -> the "not configured" TwiML, still valid XML. Settings pinned so a local
    # backend/.env (e.g. a real TWILIO_AUTH_TOKEN, which turns on signature checks) can't leak in.
    from app.voice import server

    monkeypatch.setattr(server, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(app)
    r = client.post("/voice/twilio")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Response>" in r.text


def test_run_twilio_bot_is_callable():
    assert callable(run_twilio_bot)


def test_twilio_ws_route_rejects_when_voice_unconfigured(monkeypatch):
    """The Media Streams WebSocket is wired and reachable; with no voice keys it closes the stream
    before accepting (Starlette surfaces that as a handshake rejection). Proves the route is served
    without needing Deepgram/Cartesia. The same path runs on the voice-enabled container image.

    Stub the settings so the test is deterministic regardless of the dev env's configured keys."""
    from starlette.websockets import WebSocketDisconnect

    from app.voice import server

    class _Unconfigured:
        def missing_voice_keys(self):
            return ["DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "CARTESIA_API_KEY"]

    monkeypatch.setattr(server, "get_settings", lambda: _Unconfigured())
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/voice/twilio/ws"):
            pass


class _FakeTwilioSocket:
    """Just enough of a Starlette WebSocket for run_twilio_bot's pre-pipeline phase."""

    def __init__(self, custom_parameters: dict):
        import json

        self._frames = [
            json.dumps({"event": "connected"}),
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": "MZ1",
                        "callSid": "CA123",
                        "customParameters": custom_parameters,
                    },
                }
            ),
        ]
        self.accepted = False
        self.closed_code = None

    async def accept(self):
        self.accepted = True

    async def iter_text(self):
        for frame in self._frames:
            yield frame

    async def close(self, code=1000):
        self.closed_code = code


@pytest.mark.parametrize(
    "params",
    [
        {"from": "+15551234567"},  # no token at all
        {"from": "+15551234567", "token": "forged"},
        {"from": "+19998887777", "token": "__valid_for_other_caller__"},
    ],
)
def test_run_twilio_bot_rejects_bad_stream_token_before_spending(monkeypatch, params):
    import asyncio

    from app.voice import twilio_bot
    from app.voice.twilio_security import stream_token

    if params.get("token") == "__valid_for_other_caller__":
        params = {**params, "token": stream_token("tok", "CA123", "+15551234567")}

    def _boom(*_a, **_k):
        raise AssertionError("paid services must not be built for an unauthorized stream")

    monkeypatch.setattr(twilio_bot, "build_services", _boom)
    monkeypatch.setattr(twilio_bot, "init_db", _boom)
    ws = _FakeTwilioSocket(params)
    settings = Settings(_env_file=None, twilio_auth_token="tok", environment="production")
    asyncio.run(run_twilio_bot(ws, settings))
    assert ws.closed_code == 1008
