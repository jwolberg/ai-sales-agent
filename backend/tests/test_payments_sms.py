"""Twilio SMS sender unit tests (PAY1-T2) — fake POST transport, no network."""

import pytest

from app.config import Settings
from app.payments.sms import SmsError, TwilioSmsSender, get_sms_sender


class FakePost:
    """Records the (url, data, auth) it was called with and returns a canned Twilio response."""

    def __init__(self, response=None):
        self.calls = []
        self._response = response if response is not None else {"sid": "SM123"}

    def __call__(self, url, data, auth):
        self.calls.append((url, data, auth))
        return self._response


def test_send_posts_to_from_body_and_basic_auth():
    post = FakePost()
    sender = TwilioSmsSender("AC_sid", "tok", "+15550000000", post=post)
    sid = sender.send("+15551234567", "Pay here: https://pay/x")
    assert sid == "SM123"
    url, data, auth = post.calls[0]
    assert "AC_sid/Messages.json" in url
    assert data == {"To": "+15551234567", "From": "+15550000000", "Body": "Pay here: https://pay/x"}
    assert auth == ("AC_sid", "tok")


def test_missing_destination_raises_without_calling_twilio():
    post = FakePost()
    sender = TwilioSmsSender("AC_sid", "tok", "+15550000000", post=post)
    with pytest.raises(SmsError, match="no destination"):
        sender.send("", "body")
    assert post.calls == []


def test_response_without_sid_raises():
    post = FakePost(response={"error_code": 21211})
    sender = TwilioSmsSender("AC_sid", "tok", "+15550000000", post=post)
    with pytest.raises(SmsError, match="missing message sid"):
        sender.send("+15551234567", "body")


def test_get_sms_sender_disabled_when_creds_missing():
    settings = Settings(_env_file=None)  # no Twilio creds
    assert settings.sms_enabled is False
    with pytest.raises(SmsError, match="SMS disabled"):
        get_sms_sender(settings)


def test_get_sms_sender_builds_when_configured():
    settings = Settings(
        _env_file=None,
        twilio_account_sid="AC_sid",
        twilio_auth_token="tok",
        twilio_from_number="+15550000000",
    )
    post = FakePost()
    sender = get_sms_sender(settings, post=post)
    assert sender.send("+15551234567", "hi") == "SM123"
