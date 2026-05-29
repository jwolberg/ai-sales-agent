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


def test_stream_ws_url_from_request_host():
    s = Settings(_env_file=None)
    assert stream_ws_url(s, "abc.ngrok.app") == "wss://abc.ngrok.app/voice/twilio/ws"


def test_stream_ws_url_prefers_public_base_url_and_rewrites_scheme():
    s = Settings(_env_file=None, public_base_url="https://abc.ngrok.app/")
    assert stream_ws_url(s, "ignored") == "wss://abc.ngrok.app/voice/twilio/ws"
    s2 = Settings(_env_file=None, public_base_url="http://localhost:8000")
    assert stream_ws_url(s2, "ignored") == "ws://localhost:8000/voice/twilio/ws"


def test_webhook_returns_twiml_xml():
    # No voice keys configured in tests -> the "not configured" TwiML, still valid XML.
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
