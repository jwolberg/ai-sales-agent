"""Spend/abuse limits (ticket 0003): payment-SMS budget + concurrent paid-session cap."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import limits
from app.agent.recorder import PAYMENT_CREATED, CallRecorder
from app.config import Settings
from app.db.models import Base
from app.db.session import get_db
from app.events import bus
from app.limits import SessionSlots, SmsBudget
from app.main import app

# --- SmsBudget unit ------------------------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sms_budget_caps_per_call():
    budget = SmsBudget(clock=_Clock())
    allowed = [
        budget.try_acquire("call-1", f"+1555000000{i}", per_call=3, per_number_per_hour=99)
        for i in range(4)
    ]
    assert allowed == [True, True, True, False]
    # Another call has its own budget.
    assert budget.try_acquire("call-2", "+15550000000", per_call=3, per_number_per_hour=99)


def test_sms_budget_caps_per_destination_across_calls_and_window_slides():
    clock = _Clock()
    budget = SmsBudget(clock=clock)
    to = "+15551234567"
    results = [
        budget.try_acquire(f"call-{i}", to, per_call=99, per_number_per_hour=2) for i in range(3)
    ]
    assert results == [True, True, False]
    clock.now += 3599
    assert not budget.try_acquire("call-x", to, per_call=99, per_number_per_hour=2)
    clock.now += 2  # first two sends are now > 1h old
    assert budget.try_acquire("call-y", to, per_call=99, per_number_per_hour=2)


def test_denied_attempts_do_not_consume_budget():
    budget = SmsBudget(clock=_Clock())
    assert budget.try_acquire("c", "+1", per_call=1, per_number_per_hour=99)
    for _ in range(5):
        assert not budget.try_acquire("c", "+2", per_call=1, per_number_per_hour=99)
    # +2 was never actually texted, so its per-number budget is untouched.
    assert budget.try_acquire("other", "+2", per_call=1, per_number_per_hour=1)


def test_sms_budget_without_call_id_still_caps_destination():
    budget = SmsBudget(clock=_Clock())
    assert budget.try_acquire(None, "+1", per_call=1, per_number_per_hour=1)
    assert not budget.try_acquire(None, "+1", per_call=1, per_number_per_hour=1)


# --- SessionSlots unit ---------------------------------------------------------------------------


def test_session_slots_cap_and_release():
    slots = SessionSlots()
    assert slots.try_acquire(limit=2)
    assert slots.try_acquire(limit=2)
    assert not slots.try_acquire(limit=2)
    slots.release()
    assert slots.try_acquire(limit=2)
    assert slots.active == 2


def test_session_slots_release_never_goes_negative():
    slots = SessionSlots()
    slots.release()
    assert slots.active == 0


# --- Dashboard SMS endpoint ---------------------------------------------------------------------


@pytest.fixture
def client():
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

    app.dependency_overrides[get_db] = _override
    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _call_with_payment(sessions) -> str:
    db = sessions()
    rec = CallRecorder(db, channel="web")
    rec.record_payment(
        leaf="test_prep/SAT",
        amount=85.0,
        currency="usd",
        kind="link",
        provider_ref="plink_1",
        url="https://pay/x",
        status=PAYMENT_CREATED,
    )
    db.close()
    return rec.call_id


def test_dashboard_sms_returns_429_over_per_call_cap_and_publishes_nothing(client, monkeypatch):
    from app.dashboard import router as dash

    tc, sessions = client
    settings = Settings(_env_file=None, payments_fake=True, sms_max_per_call=2)
    monkeypatch.setattr(dash, "get_settings", lambda: settings)
    published = []
    cid = _call_with_payment(sessions)  # seeding publishes its own payment_sent; count after it
    monkeypatch.setattr(bus, "publish", lambda **kw: published.append(kw))

    codes = [
        tc.post(f"/api/calls/{cid}/send-payment-sms", json={"phone": f"+1555000000{i}"}).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]
    sent_events = [e for e in published if e["type"] == "payment_sent"]
    assert len(sent_events) == 2  # the refused send emitted no payment_sent


def test_dashboard_sms_returns_429_over_per_number_cap(client, monkeypatch):
    from app.dashboard import router as dash

    tc, sessions = client
    settings = Settings(_env_file=None, payments_fake=True, sms_max_per_number_per_hour=1)
    monkeypatch.setattr(dash, "get_settings", lambda: settings)
    first, second = _call_with_payment(sessions), _call_with_payment(sessions)
    body = {"phone": "+15551234567"}
    assert tc.post(f"/api/calls/{first}/send-payment-sms", json=body).status_code == 200
    assert tc.post(f"/api/calls/{second}/send-payment-sms", json=body).status_code == 429


# --- Engine auto-text ---------------------------------------------------------------------------


def test_engine_auto_text_respects_destination_cap(monkeypatch):
    from app.agent.intent_engine import IntentRouterEngine

    class _Sms:
        def __init__(self):
            self.sent = []

        def send(self, to, body):
            self.sent.append(to)
            return "SM1"

    settings = Settings(_env_file=None, sms_max_per_number_per_hour=1)
    sms = _Sms()
    engine = IntentRouterEngine.__new__(IntentRouterEngine)  # only _try_text_link is exercised
    engine.settings, engine._sms_sender, engine.recorder = settings, sms, None

    class _Link:
        url = "https://pay/x"

    assert engine._try_text_link("+15551234567", _Link()) is True
    assert engine._try_text_link("+15551234567", _Link()) is False  # capped -> not texted
    assert sms.sent == ["+15551234567"]


# --- Concurrent paid sessions -------------------------------------------------------------------


def test_sim_start_returns_429_when_sessions_full(client, monkeypatch):
    from app.dashboard import router as dash

    tc, _ = client
    monkeypatch.setattr(
        dash, "get_settings", lambda: Settings(_env_file=None, max_concurrent_sessions=1)
    )
    assert limits.session_slots.try_acquire(limit=1)  # one call already live
    resp = tc.post("/api/sim/start", json={})
    assert resp.status_code == 429


def test_voice_offer_returns_429_when_sessions_full(monkeypatch):
    # Without the voice extra the endpoint 503s ("deps missing") before the session cap applies.
    pytest.importorskip("pipecat")
    from app.voice import server

    settings = Settings(
        _env_file=None,
        max_concurrent_sessions=1,
        deepgram_api_key="x",
        anthropic_api_key="x",
        cartesia_api_key="x",
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    assert limits.session_slots.try_acquire(limit=1)
    resp = TestClient(app).post("/voice/offer", json={"sdp": "v=0", "type": "offer"})
    assert resp.status_code == 429


def test_sim_start_releases_slot_when_call_finishes(monkeypatch):
    import asyncio

    from app.dashboard import router as dash

    monkeypatch.setattr(
        dash, "get_settings", lambda: Settings(_env_file=None, max_concurrent_sessions=1)
    )

    async def _instant(_persona):
        await asyncio.sleep(0)

    monkeypatch.setattr(dash, "run_sim_call_paced", _instant)

    async def _scenario():
        await dash.sim_start(dash.SimStartRequest())
        assert limits.session_slots.active == 1  # held while the call runs
        for _ in range(10):
            await asyncio.sleep(0)
        assert limits.session_slots.active == 0  # released on completion
        await dash.sim_start(dash.SimStartRequest())  # slot is reusable
        for _ in range(10):
            await asyncio.sleep(0)

    asyncio.run(_scenario())


# --- Review H3: one destination, many spellings ---------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    ["15551234567", "5551234567", "(555) 123-4567", "+1 555 123 4567", "+1-555-123-4567"],
)
def test_per_number_cap_ignores_formatting(spelling):
    budget = SmsBudget(clock=_Clock())
    assert budget.try_acquire("a", "+15551234567", per_call=99, per_number_per_hour=1)
    assert not budget.try_acquire("b", spelling, per_call=99, per_number_per_hour=1)


def test_global_hourly_cap_across_all_numbers_and_calls():
    clock = _Clock()
    budget = SmsBudget(clock=clock)
    allowed = [
        budget.try_acquire(
            f"c{i}", f"+1555000{i:04d}", per_call=99, per_number_per_hour=99, total_per_hour=3
        )
        for i in range(4)
    ]
    assert allowed == [True, True, True, False]
    clock.now += 3601
    assert budget.try_acquire(
        "later", "+15559999999", per_call=99, per_number_per_hour=99, total_per_hour=3
    )


def test_allow_sms_applies_configured_global_cap():
    settings = Settings(_env_file=None, sms_max_per_hour_total=1)
    assert limits.allow_sms(settings, "c1", "+15550000001")
    assert not limits.allow_sms(settings, "c2", "+15550000002")
