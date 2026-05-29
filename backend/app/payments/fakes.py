"""Dev-only fakes for the payment flow (PAY7-T1).

Let the Test Call exercise billing end-to-end with NO Stripe/Twilio keys and no real charge:
deterministic ``…example.test/fake/…`` links and a no-op SMS sender. Wired in only when
``settings.payments_fake`` is true (see ``get_stripe_service`` / ``get_sms_sender``) — not in prod.
"""

from __future__ import annotations

import re

from app.payments.stripe_service import PaymentLink

# Idempotency keys contain ':' (e.g. "{call_id}:pay:{turn_id}") — keep fake refs URL-safe.
_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def _ref(prefix: str, idempotency_key: str) -> str:
    return f"{prefix}_{_SAFE.sub('-', idempotency_key)}"


class FakeStripeGateway:
    """Returns deterministic fake links/ids without touching Stripe."""

    def payment_link(self, *, amount_cents, currency, product_name, idempotency_key) -> PaymentLink:
        ref = _ref("fakepl", idempotency_key)
        return PaymentLink(id=ref, url=f"https://pay.example.test/fake/{ref}")

    def invoice(
        self, *, amount_cents, currency, product_name, customer_phone, idempotency_key
    ) -> PaymentLink:
        ref = _ref("fakein", idempotency_key)
        return PaymentLink(id=ref, url=f"https://invoice.example.test/fake/{ref}")


class FakeSmsSender:
    """No-op SMS: records nothing, returns a fake message sid so the flow completes."""

    def send(self, to: str, body: str) -> str:
        return f"FAKESM_{_SAFE.sub('-', to or 'none')}"
