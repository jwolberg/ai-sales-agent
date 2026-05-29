"""Dev fake payments mode (PAY7-T1) — flow works with no Stripe/Twilio keys."""

from app.config import Settings
from app.payments.sms import get_sms_sender
from app.payments.stripe_service import get_stripe_service


def _fake_settings() -> Settings:
    return Settings(_env_file=None, payments_fake=True)


def test_fake_mode_enables_payments_without_keys():
    s = _fake_settings()
    assert s.payments_enabled is True
    assert s.stripe_api_key is None and s.sms_enabled is False


def test_fake_stripe_charges_placeholder_price_with_fake_link():
    # Placeholder pricing.yaml (approved: false) would be refused on the real path; fake mode allows
    # it because nothing is actually billed.
    svc = get_stripe_service(_fake_settings())
    link = svc.create_payment_link("test_prep/SAT", idempotency_key="call1:pay:turn2")
    assert link.url.startswith("https://pay.example.test/fake/")
    assert link.id.startswith("fakepl_")


def test_fake_sms_is_noop_when_no_twilio_creds():
    sender = get_sms_sender(_fake_settings())
    assert sender.send("+15551234567", "pay here").startswith("FAKESM_")
