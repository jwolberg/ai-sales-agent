"""Stripe hosted-payment service (PAY1-T1).

Creates a **Payment Link** (pay-now) or **Invoice** (send-invoice) for a classification leaf and
returns the hosted URL. Two correctness anchors live here:

- **Approved-price gate** — the amount is derived from the leaf's :class:`PriceRecord` in
  ``pricing.yaml`` and we refuse unless that record is ``approved``. Deviation from the build-plan
  signature (which passed ``amount``/``currency`` in): deriving the amount from the price table
  rather than trusting a caller means no code path can request an arbitrary charge — the price table
  stays the single source of truth the mis-quote guard already enforces.
- **Idempotency** — every Stripe write takes an idempotency key so a retried turn can't
  double-charge.

The Stripe calls sit behind a small :class:`StripeGateway` seam so tests inject a fake (no net).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agent.pricing import PriceBook, PriceRecord, get_pricebook, quote_price


class PaymentError(RuntimeError):
    """Raised when a charge can't be created — unknown leaf, unapproved (placeholder) price, or a
    missing Stripe key. The engine turns this into a safe escalation rather than a spoken price."""


@dataclass(frozen=True)
class PaymentLink:
    """The hosted-checkout handle we persist + text to the caller."""

    id: str  # Stripe object id (PaymentLink or Invoice) — our provider_ref
    url: str  # hosted URL the caller opens to pay


class StripeGateway(Protocol):
    """The minimal Stripe surface the service needs. The real impl wraps the ``stripe`` SDK; tests
    pass a fake that records calls and returns canned handles."""

    def payment_link(
        self, *, amount_cents: int, currency: str, product_name: str, idempotency_key: str
    ) -> PaymentLink: ...

    def invoice(
        self,
        *,
        amount_cents: int,
        currency: str,
        product_name: str,
        customer_phone: str | None,
        idempotency_key: str,
    ) -> PaymentLink: ...


def _to_cents(amount: float) -> int:
    """Dollars -> Stripe's smallest currency unit. round() avoids float drift (85.0 -> 8500)."""
    return int(round(amount * 100))


def _product_name(record: PriceRecord) -> str:
    """A human label for the Stripe line item, e.g. 'SAT prep (per hour)'."""
    leaf = record.leaf_id.split("/")[-1]
    return f"{leaf} ({record.unit})"


class StripeService:
    """Create hosted payment links / invoices for an approved leaf price."""

    def __init__(
        self,
        gateway: StripeGateway,
        *,
        pricebook: PriceBook | None = None,
        currency: str = "usd",
        allow_unapproved: bool = False,
    ) -> None:
        self._gateway = gateway
        self._pricebook = pricebook or get_pricebook()
        # Stripe wants a lowercase ISO code; the pricebook stores 'USD'.
        self._currency = currency.lower()
        # Dev fake mode only: charge placeholder (unapproved) prices since the fake never bills.
        # The real path leaves this False — the approved-price gate stays strict (PAY-6).
        self._allow_unapproved = allow_unapproved

    def create_payment_link(self, leaf_id: str, *, idempotency_key: str) -> PaymentLink:
        """Pay-now link for ``leaf_id``. Raises :class:`PaymentError` if not approved/priced."""
        record = self._approved_record(leaf_id)
        return self._gateway.payment_link(
            amount_cents=_to_cents(record.amount),
            currency=self._currency,
            product_name=_product_name(record),
            idempotency_key=idempotency_key,
        )

    def create_invoice(
        self, leaf_id: str, *, customer_phone: str | None = None, idempotency_key: str
    ) -> PaymentLink:
        """Send-invoice (hosted invoice URL) for ``leaf_id``. Same approved-price gate."""
        record = self._approved_record(leaf_id)
        return self._gateway.invoice(
            amount_cents=_to_cents(record.amount),
            currency=self._currency,
            product_name=_product_name(record),
            customer_phone=customer_phone,
            idempotency_key=idempotency_key,
        )

    def _approved_record(self, leaf_id: str) -> PriceRecord:
        record = quote_price(leaf_id, pricebook=self._pricebook)
        if record is None:
            raise PaymentError(f"no priced record for leaf {leaf_id!r}; cannot charge")
        if not record.approved and not self._allow_unapproved:
            raise PaymentError(
                f"price for {leaf_id!r} is not approved (placeholder); refusing to charge"
            )
        return record


class _StripeApiGateway:
    """Real gateway backed by the ``stripe`` SDK. A Payment Link needs a Price object, so we create
    an ad-hoc one-off Price (with inline product data) then the link; the invoice path creates an
    anonymous customer (phone optional), an invoice item, and a finalized invoice."""

    def __init__(self, api_key: str) -> None:
        import stripe  # local import: only the live path needs the SDK loaded

        self._stripe = stripe
        self._stripe.api_key = api_key

    def payment_link(
        self, *, amount_cents: int, currency: str, product_name: str, idempotency_key: str
    ) -> PaymentLink:
        price = self._stripe.Price.create(
            unit_amount=amount_cents,
            currency=currency,
            product_data={"name": product_name},
            idempotency_key=f"{idempotency_key}:price",
        )
        link = self._stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            idempotency_key=f"{idempotency_key}:link",
        )
        return PaymentLink(id=link.id, url=link.url)

    def invoice(
        self,
        *,
        amount_cents: int,
        currency: str,
        product_name: str,
        customer_phone: str | None,
        idempotency_key: str,
    ) -> PaymentLink:
        customer = self._stripe.Customer.create(
            phone=customer_phone or None, idempotency_key=f"{idempotency_key}:customer"
        )
        self._stripe.InvoiceItem.create(
            customer=customer.id,
            amount=amount_cents,
            currency=currency,
            description=product_name,
            idempotency_key=f"{idempotency_key}:item",
        )
        invoice = self._stripe.Invoice.create(
            customer=customer.id,
            collection_method="send_invoice",
            days_until_due=7,
            idempotency_key=f"{idempotency_key}:invoice",
        )
        invoice = self._stripe.Invoice.finalize_invoice(invoice.id)
        return PaymentLink(id=invoice.id, url=invoice.hosted_invoice_url)


def get_stripe_service(settings, *, pricebook: PriceBook | None = None) -> StripeService:
    """Build the service from settings. In dev fake mode (PAY7-T1) returns a no-network fake that
    can charge placeholder prices; otherwise the real Stripe-backed service with the strict
    approved-price gate. Raises :class:`PaymentError` if payments aren't enabled at all."""
    if settings.payments_fake:
        from app.payments.fakes import FakeStripeGateway

        return StripeService(
            FakeStripeGateway(),
            pricebook=pricebook,
            currency=settings.payments_currency,
            allow_unapproved=True,
        )
    if not settings.payments_enabled:
        raise PaymentError("payments are disabled (no STRIPE_API_KEY)")
    gateway = _StripeApiGateway(settings.stripe_api_key)
    return StripeService(gateway, pricebook=pricebook, currency=settings.payments_currency)
