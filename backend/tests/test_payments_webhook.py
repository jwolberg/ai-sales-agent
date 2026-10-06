"""Stripe webhook tests (PAY4-T1) — verifier monkeypatched, no signing/network."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.recorder import PAYMENT_PAID, CallRecorder
from app.config import Settings, get_settings
from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.payments import webhook


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # A webhook secret must be set for the endpoint to run; override the cached settings.
    get_settings.cache_clear()
    monkeypatch.setattr(
        webhook, "get_settings", lambda: Settings(_env_file=None, stripe_webhook_secret="whsec_x")
    )
    app.dependency_overrides[get_db] = _override
    yield TestClient(app), TestSession
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _seed_payment(session_factory, *, provider_ref: str, kind: str = "link") -> str:
    db = session_factory()
    rec = CallRecorder(db, channel="web")
    rec.record_payment(
        leaf="test_prep/SAT",
        amount=85.0,
        currency="usd",
        kind=kind,
        provider_ref=provider_ref,
        url="https://pay/x",
    )
    db.close()
    return provider_ref


def _fake_event(monkeypatch, event: dict):
    monkeypatch.setattr(webhook, "_verify_event", lambda payload, sig, secret: event)


def test_checkout_completed_marks_paid(client, monkeypatch):
    tc, sessions = client
    _seed_payment(sessions, provider_ref="plink_1")
    _fake_event(
        monkeypatch,
        {
            "type": "checkout.session.completed",
            "data": {"object": {"payment_link": "plink_1"}},
        },
    )
    resp = tc.post("/payments/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.json() == {"status": "ok"}

    db = sessions()
    from app.db.models import Payment

    paid = db.query(Payment).filter(Payment.provider_ref == "plink_1").one()
    assert paid.status == PAYMENT_PAID and paid.paid_at is not None
    db.close()


def test_invoice_paid_marks_paid(client, monkeypatch):
    tc, sessions = client
    _seed_payment(sessions, provider_ref="in_1", kind="invoice")
    _fake_event(
        monkeypatch,
        {
            "type": "invoice.paid",
            "data": {"object": {"id": "in_1"}},
        },
    )
    resp = tc.post("/payments/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.json() == {"status": "ok"}


def test_unknown_ref_is_reported(client, monkeypatch):
    tc, _ = client
    _fake_event(
        monkeypatch,
        {
            "type": "checkout.session.completed",
            "data": {"object": {"payment_link": "nope"}},
        },
    )
    resp = tc.post("/payments/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.json() == {"status": "unknown_ref"}


def test_unhandled_event_type_ignored(client, monkeypatch):
    tc, _ = client
    _fake_event(monkeypatch, {"type": "customer.created", "data": {"object": {}}})
    resp = tc.post("/payments/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.json() == {"status": "ignored"}
