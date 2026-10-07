"""Logging (ticket 0007): failures are visible, and phone numbers / secrets never hit the logs."""

import logging

import pytest

from app.config import Settings
from app.logs import configure_logging, mask_phone, scrub

PHONE = "+15551234567"


def test_mask_phone_keeps_only_last_four():
    assert mask_phone(PHONE) == "***4567"
    assert mask_phone("12") == "***"
    assert mask_phone(None) is None


def test_scrub_masks_phone_numbers_embedded_in_text():
    text = f"Twilio API error 400: The 'To' number {PHONE} is not valid; also (555) 987-6543"
    out = scrub(text)
    assert "5551234567" not in out and "987-6543" not in out
    assert "***4567" in out
    assert "Twilio API error 400" in out  # status codes / short numbers survive


def test_configure_logging_sets_app_level():
    configure_logging("DEBUG")
    assert logging.getLogger("app").level == logging.DEBUG
    configure_logging("WARNING")
    assert logging.getLogger("app").level == logging.WARNING
    configure_logging("INFO")


def test_retriever_fallback_logs_a_warning(monkeypatch, caplog):
    from app.agent import knowledge
    from app.kb import embeddings

    def _broken():
        raise RuntimeError("no such table: kb_chunks")

    monkeypatch.setattr(embeddings, "get_embedder", _broken)
    with caplog.at_level(logging.WARNING, logger="app"):
        retriever = knowledge.get_default_retriever()
    assert retriever is not None  # still falls back to TF-IDF
    records = [r for r in caplog.records if "TF-IDF" in r.getMessage()]
    assert records and records[0].levelno == logging.WARNING
    assert records[0].exc_info is not None  # the cause is attached, not swallowed


def test_sms_send_logs_masked_number_and_no_secrets(caplog):
    from app.payments.sms import TwilioSmsSender

    sender = TwilioSmsSender(
        account_sid="ACsecret-sid",
        auth_token="tok-very-secret",
        from_number="+15550000000",
        post=lambda url, data, auth: {"sid": "SM1"},
    )
    with caplog.at_level(logging.INFO, logger="app"):
        sender.send(PHONE, "Here's your link: https://pay/x")
    text = caplog.text
    assert "***4567" in text and "SM1" in text
    assert PHONE not in text and "5551234567" not in text
    assert "tok-very-secret" not in text


def test_sms_failure_in_engine_logged_masked(caplog):
    from app.agent.intent_engine import IntentRouterEngine
    from app.payments.sms import SmsError

    class _FailingSms:
        def send(self, to, body):
            raise SmsError(f"Twilio API error 400: The 'To' number {to} is not valid")

    engine = IntentRouterEngine.__new__(IntentRouterEngine)
    engine.settings, engine._sms_sender, engine.recorder = (
        Settings(_env_file=None),
        _FailingSms(),
        None,
    )

    class _Link:
        url = "https://pay/x"

    with caplog.at_level(logging.WARNING, logger="app"):
        assert engine._try_text_link(PHONE, _Link()) is False
    assert "SMS" in caplog.text and "***4567" in caplog.text
    assert "5551234567" not in caplog.text


def test_brain_failure_is_logged_and_reraised(caplog):
    from app.agent.intent_engine import IntentRouterEngine

    class _BrokenBrain:
        def decide(self, **_kw):
            raise TimeoutError("openai timed out")

    engine = IntentRouterEngine(brain=_BrokenBrain(), settings=Settings(_env_file=None))
    with caplog.at_level(logging.ERROR, logger="app"), pytest.raises(TimeoutError):
        engine.run_turn("I need SAT prep")
    assert any("brain" in r.getMessage().lower() for r in caplog.records)


def test_stripe_webhook_bad_signature_logged_generic_response(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.payments import webhook

    monkeypatch.setattr(
        webhook, "get_settings", lambda: Settings(_env_file=None, stripe_webhook_secret="whsec_x")
    )
    with caplog.at_level(logging.WARNING, logger="app"):
        resp = TestClient(app).post(
            "/payments/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=bad"}
        )
    assert resp.status_code == 400
    assert any("signature" in r.getMessage().lower() for r in caplog.records)


def test_rejected_twilio_get_does_not_log_caller_number(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.voice import server

    monkeypatch.setattr(
        server, "get_settings", lambda: Settings(_env_file=None, twilio_auth_token="tok")
    )
    with caplog.at_level(logging.WARNING, logger="app"):
        resp = TestClient(app).get("/voice/twilio", params={"From": PHONE, "CallSid": "CA1"})
    assert resp.status_code == 403
    assert "rejected Twilio webhook" in caplog.text
    assert "5551234567" not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("read timed out"), ValueError("Expecting value: line 1 column 1")],
)
def test_sms_transport_failures_become_sms_errors(monkeypatch, failure):
    from app.payments import sms

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            if isinstance(failure, TimeoutError):
                raise failure
            return b"not json"

    monkeypatch.setattr(sms.urllib.request, "urlopen", lambda *a, **k: _Resp())
    with pytest.raises(sms.SmsError):
        sms._urllib_post("https://api.twilio.test/x", {"To": PHONE}, ("AC", "tok"))


def test_missing_sid_error_does_not_embed_response_body():
    from app.payments.sms import SmsError, TwilioSmsSender

    sender = TwilioSmsSender(
        account_sid="AC1",
        auth_token="tok",
        from_number="+15550000000",
        post=lambda url, data, auth: {"to": PHONE, "status": "weird"},
    )
    with pytest.raises(SmsError) as err:
        sender.send(PHONE, "hi")
    assert "5551234567" not in str(err.value)
