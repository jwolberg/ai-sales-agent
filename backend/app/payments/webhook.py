"""Stripe webhook — the source of truth for "paid" (PAY4-T1).

Stripe POSTs here when a hosted checkout completes. We verify the signature with
``STRIPE_WEBHOOK_SECRET`` (the client-side `url` only proves a link was *sent*, never *paid*), then
flip the matching :class:`Payment` to paid via :func:`mark_payment_paid` (which publishes
``payment_paid`` to the bus).

Idempotency: ``mark_payment_paid`` no-ops a row that's already ``paid``, so a duplicate webhook
can't re-fire the event — we lean on the payment's status rather than tracking event ids in a table.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent.recorder import mark_payment_paid
from app.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/payments", tags=["payments"])

Db = Annotated[Session, Depends(get_db)]

# Stripe event types that mean "the caller paid".
_PAID_EVENTS = {"checkout.session.completed", "invoice.paid"}

logger = logging.getLogger(__name__)


def _verify_event(payload: bytes, signature: str | None, secret: str) -> dict:
    """Verify the Stripe signature and return the event. Raises 400 on a bad/forged signature.

    Split out as a module function so tests can monkeypatch it with a constructed event instead of
    signing payloads."""
    import stripe

    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:  # SignatureVerificationError / ValueError
        # The specific reason goes to the log only; the caller gets a generic 400.
        logger.warning("rejected Stripe webhook: invalid signature (%s)", exc)
        raise HTTPException(status_code=400, detail="invalid Stripe signature") from exc


def _paid_provider_ref(event: dict) -> str | None:
    """The provider_ref of the paid object, or None for an event we don't act on.

    A Payment Link checkout reports the link id under ``payment_link``; an invoice reports its own
    ``id`` — both are what we stored as ``Payment.provider_ref``."""
    if event.get("type") not in _PAID_EVENTS:
        return None
    obj = event.get("data", {}).get("object", {})
    if event["type"] == "invoice.paid":
        return obj.get("id")
    return obj.get("payment_link")  # checkout.session.completed


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Db,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook not configured")
    payload = await request.body()
    event = _verify_event(payload, stripe_signature, settings.stripe_webhook_secret)

    ref = _paid_provider_ref(event)
    if ref is None:
        logger.info("stripe webhook %s ignored", event.get("type"))
        return {"status": "ignored"}  # an event type we don't act on
    payment = mark_payment_paid(db, ref)
    status = "ok" if payment is not None else "unknown_ref"
    log = logger.info if payment is not None else logger.warning
    log("stripe webhook %s for %s: %s", event.get("type"), ref, status)
    return {"status": status}
