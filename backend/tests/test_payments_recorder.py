"""Payment persistence tests (PAY2-T1): record_payment + mark_payment_paid."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.recorder import (
    PAYMENT_PAID,
    PAYMENT_SENT,
    CallRecorder,
    mark_payment_paid,
)
from app.db.models import Base, Payment


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _recorder(session) -> CallRecorder:
    return CallRecorder(session, channel="web")


def test_record_payment_persists_row(session):
    rec = _recorder(session)
    payment = rec.record_payment(
        leaf="test_prep/SAT",
        amount=85.0,
        currency="usd",
        kind="link",
        provider_ref="plink_123",
        url="https://pay/x",
    )
    assert payment.status == PAYMENT_SENT
    stored = session.get(Payment, payment.payment_id)
    assert stored.call_id == rec.call_id
    assert stored.provider == "stripe"
    assert stored.provider_ref == "plink_123"
    assert stored.paid_at is None


def test_mark_payment_paid_transitions_and_stamps(session):
    rec = _recorder(session)
    rec.record_payment(
        leaf="test_prep/SAT",
        amount=85.0,
        currency="usd",
        kind="link",
        provider_ref="plink_123",
        url="https://pay/x",
    )
    paid = mark_payment_paid(session, "plink_123")
    assert paid is not None
    assert paid.status == PAYMENT_PAID
    assert paid.paid_at is not None


def test_mark_payment_paid_is_idempotent(session):
    rec = _recorder(session)
    rec.record_payment(
        leaf="test_prep/SAT",
        amount=85.0,
        currency="usd",
        kind="link",
        provider_ref="plink_123",
        url="https://pay/x",
    )
    first = mark_payment_paid(session, "plink_123")
    stamp = first.paid_at
    again = mark_payment_paid(session, "plink_123")  # duplicate webhook
    assert again.paid_at == stamp  # unchanged — not re-settled


def test_mark_payment_paid_unknown_ref_is_noop(session):
    assert mark_payment_paid(session, "nope_999") is None
