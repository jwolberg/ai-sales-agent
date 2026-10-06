"""Stripe service unit tests (PAY1-T1) — fake gateway, no network.

Asserts the approved-price gate refuses placeholder/unpriced leaves and that idempotency keys and
the price-table amount are passed through to Stripe.
"""

import pytest

from app.agent.pricing import PriceBook, PriceRecord, get_pricebook
from app.payments.stripe_service import PaymentError, PaymentLink, StripeService


class FakeGateway:
    """Records the kwargs the service hands Stripe and returns canned handles."""

    def __init__(self):
        self.calls = []

    def payment_link(self, **kw):
        self.calls.append(("payment_link", kw))
        return PaymentLink(id="plink_123", url="https://pay.stripe.test/plink_123")

    def invoice(self, **kw):
        self.calls.append(("invoice", kw))
        return PaymentLink(id="inv_123", url="https://invoice.stripe.test/inv_123")


def _book(*, approved: bool) -> PriceBook:
    rec = PriceRecord(
        leaf_id="test_prep/SAT",
        amount=85.0,
        unit="per hour",
        currency="USD",
        summary="",
        approved=approved,
    )
    return PriceBook({"test_prep/SAT": rec})


def test_payment_link_approved_passes_amount_and_idempotency_key():
    gw = FakeGateway()
    svc = StripeService(gw, pricebook=_book(approved=True), currency="usd")
    link = svc.create_payment_link("test_prep/SAT", idempotency_key="call42:turn3")
    assert link.url == "https://pay.stripe.test/plink_123"
    name, kw = gw.calls[0]
    assert name == "payment_link"
    assert kw["amount_cents"] == 8500  # $85.00 from the price table, in cents
    assert kw["currency"] == "usd"
    assert kw["idempotency_key"] == "call42:turn3"


def test_invoice_approved_passes_phone():
    gw = FakeGateway()
    svc = StripeService(gw, pricebook=_book(approved=True))
    link = svc.create_invoice("test_prep/SAT", customer_phone="+15551234567", idempotency_key="k1")
    assert link.id == "inv_123"
    _, kw = gw.calls[0]
    assert kw["customer_phone"] == "+15551234567"


def test_unapproved_price_is_refused():
    gw = FakeGateway()
    svc = StripeService(gw, pricebook=_book(approved=False))
    with pytest.raises(PaymentError, match="not approved"):
        svc.create_payment_link("test_prep/SAT", idempotency_key="k1")
    assert gw.calls == []  # never reached Stripe


def test_unknown_leaf_is_refused():
    gw = FakeGateway()
    svc = StripeService(gw, pricebook=_book(approved=True))
    with pytest.raises(PaymentError, match="no priced record"):
        svc.create_payment_link("tutoring/math/algebra", idempotency_key="k1")
    assert gw.calls == []


def test_currency_is_lowercased_for_stripe():
    gw = FakeGateway()
    svc = StripeService(gw, pricebook=_book(approved=True), currency="USD")
    svc.create_payment_link("test_prep/SAT", idempotency_key="k1")
    assert gw.calls[0][1]["currency"] == "usd"


def test_shipped_pricebook_blocks_every_leaf_until_prices_are_approved():
    """PAY6-T1 safety anchor: the committed pricing.yaml is `approved: false` (placeholders), so the
    gate must refuse a charge for EVERY real leaf — no accidental charges on placeholder prices."""
    gw = FakeGateway()
    book = get_pricebook()
    svc = StripeService(gw, pricebook=book)
    assert book.leaf_ids(), "expected priced leaves to exist in pricing.yaml"
    for leaf_id in book.leaf_ids():
        with pytest.raises(PaymentError, match="not approved"):
            svc.create_payment_link(leaf_id, idempotency_key="k")
    assert gw.calls == []  # never reached Stripe for any leaf
