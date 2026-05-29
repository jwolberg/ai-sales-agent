"""Engine payment executor end-to-end, offline (PAY3-T2).

RuleBrain + fake Stripe + fake SMS. Asserts a paid-intent turn after a quote creates a Payment row,
emits PAYMENT_LINK_SENT, texts the link, and that the approved-price gate escalates placeholders.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.agent.contract import RouterAction
from app.agent.intent_engine import IntentRouterEngine
from app.agent.pricing import PriceBook, PriceRecord
from app.agent.recorder import PAYMENT_SENT, CallRecorder
from app.config import Settings
from app.db.models import Base, KPIEvent, Payment
from app.payments.stripe_service import PaymentLink, StripeService


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class FakeGateway:
    def payment_link(self, **kw):
        return PaymentLink(id="plink_1", url="https://pay/x")

    def invoice(self, **kw):
        return PaymentLink(id="inv_1", url="https://inv/x")


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, to, body):
        self.sent.append((to, body))
        return "SM1"


def _book(approved: bool) -> PriceBook:
    rec = PriceRecord(
        leaf_id="test_prep/SAT", amount=85.0, unit="per hour",
        currency="USD", summary="SAT prep is $85/hr.", approved=approved,
    )
    return PriceBook({"test_prep/SAT": rec})


def _engine(session, *, approved: bool, sms: FakeSms | None = None) -> IntentRouterEngine:
    settings = Settings(_env_file=None, stripe_api_key="sk_test_x", payments_currency="usd")
    assert settings.payments_enabled
    recorder = CallRecorder(session, channel="web")
    service = StripeService(FakeGateway(), pricebook=_book(approved), currency="usd")
    return IntentRouterEngine(
        brain=RuleBrain(settings),
        recorder=recorder,
        settings=settings,
        caller_number="+15551234567",
        stripe_service=service,
        sms_sender=sms,
    )


def test_pay_after_quote_creates_payment_and_texts_link(session):
    sms = FakeSms()
    eng = _engine(session, approved=True, sms=sms)
    eng.open()
    eng.run_turn("I need SAT prep")          # resolves the leaf + quotes
    result = eng.run_turn("Great, I'll pay now")  # pay intent
    assert result.action is RouterAction.PAY
    assert "texted" in result.utterance.lower()

    payment = session.scalars(select(Payment)).one()
    assert payment.leaf == "test_prep/SAT"
    assert payment.amount == 85.0
    assert payment.provider_ref == "plink_1"
    assert payment.status == PAYMENT_SENT
    assert sms.sent and sms.sent[0][0] == "+15551234567"

    kpis = session.scalars(select(KPIEvent).where(KPIEvent.event_type == "payment_link_sent")).all()
    assert len(kpis) == 1


def test_unapproved_price_escalates_instead_of_charging(session):
    eng = _engine(session, approved=False, sms=FakeSms())
    eng.open()
    eng.run_turn("I need SAT prep")
    result = eng.run_turn("I'll pay now")
    assert result.action is RouterAction.ESCALATE  # approved-price gate -> safe handoff
    assert session.scalars(select(Payment)).all() == []  # nothing charged
