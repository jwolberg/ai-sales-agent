"""Tests for the observability API (P5-T4; PRD §10.2, §10.3)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.brain import RuleBrain
from app.agent.intent_engine import IntentRouterEngine
from app.agent.recorder import OUTCOME_COMPLETED, CallRecorder
from app.config import Settings
from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def client():
    # StaticPool keeps one in-memory connection so the seed session and the API's get_db
    # session share the same data.
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


def _seed_call(session_factory) -> str:
    db = session_factory()
    rec = CallRecorder(db, channel="web", agent_version="persona-x")
    eng = IntentRouterEngine(
        brain=RuleBrain(Settings(_env_file=None)), recorder=rec, settings=Settings(_env_file=None)
    )
    eng.open()
    eng.run_turn("I need chemistry tutoring")  # classify -> quote
    eng.run_turn("can I talk to a human?")     # escalation
    eng.end(outcome=OUTCOME_COMPLETED)
    call_id = rec.call_id
    db.close()
    return call_id


def test_metrics_endpoint(client):
    tc, sessions = client
    _seed_call(sessions)
    m = tc.get("/api/metrics").json()
    assert m["total_calls"] == 1
    assert m["escalation_rate"] == 1.0
    assert m["close_success_rate"] == 1.0
    assert m["average_latency_seconds"] is None  # not-measured surfaces as null


def test_metrics_slice_by_version(client):
    tc, sessions = client
    _seed_call(sessions)
    assert tc.get("/api/metrics", params={"agent_version": "persona-x"}).json()["total_calls"] == 1
    assert tc.get("/api/metrics", params={"agent_version": "other"}).json()["total_calls"] == 0


def test_calls_list_and_detail(client):
    tc, sessions = client
    call_id = _seed_call(sessions)

    calls = tc.get("/api/calls").json()
    assert len(calls) == 1 and calls[0]["call_id"] == call_id
    assert calls[0]["num_turns"] > 0

    # Call-level router result is surfaced (IR6-T2).
    assert calls[0]["reached_leaf"] == "tutoring/science/chemistry"
    assert calls[0]["quoted_price"] == 80.0

    detail = tc.get(f"/api/calls/{call_id}").json()
    assert any(t["speaker"] == "prospect" for t in detail["turns"])
    assert any(t["speaker"] == "agent" for t in detail["turns"])
    assert detail["decisions"] and detail["decisions"][0]["selected_action"]
    # Decision trace carries the slot state + reached leaf (IR6-T2).
    quote = next(d for d in detail["decisions"] if d["selected_action"] == "quote")
    assert quote["leaf"] == "tutoring/science/chemistry"
    assert quote["slots"]["subject"] == "chemistry"
    assert any(e["event_type"] == "escalation" for e in detail["kpi_events"])


def test_vad_eval_uses_recorded_params(client):
    tc, sessions = client
    db = sessions()
    rec = CallRecorder(
        db, channel="web", vad_params={"stop_secs": 0.8, "start_secs": 0.2,
                                       "confidence": 0.7, "min_volume": 0.6}
    )
    call_id = rec.call_id
    db.commit()
    db.close()

    ev = tc.get(f"/api/calls/{call_id}").json()["vad_eval"]
    assert ev["from_call"] is True
    assert ev["params"]["stop_secs"] == 0.8
    assert "--stop-secs 0.8" in ev["command"]
    assert ev["clip_placeholder"] in ev["command"]
    # The sweep includes the call's own stop_secs so its row always shows up.
    assert "0.8" in ev["sweep_command"]


def test_vad_eval_falls_back_to_current_config(client):
    tc, sessions = client
    call_id = _seed_call(sessions)  # seeded without vad_params (pre-VAD-T3 style)
    ev = tc.get(f"/api/calls/{call_id}").json()["vad_eval"]
    assert ev["from_call"] is False  # flagged: params are today's config, not the call's record
    assert set(ev["params"]) == {"stop_secs", "start_secs", "confidence", "min_volume"}


def test_router_metrics_endpoint(client):
    tc, sessions = client
    _seed_call(sessions)
    m = tc.get("/api/router-metrics").json()
    assert m["total_calls"] == 1
    assert m["leaf_reached_rate"] == 1.0
    assert m["escalation_rate"] == 1.0
    assert m["mis_quote_rate"] == 0.0


def test_call_not_found(client):
    tc, _ = client
    assert tc.get("/api/calls/does-not-exist").status_code == 404


def test_sim_personas_endpoint(client):
    tc, _ = client
    personas = tc.get("/api/sim/personas").json()
    assert len(personas) == 10
    assert all(p["target_leaf"] and p["opening_line"] for p in personas)


def test_payment_surfaces_on_calls_api_and_metrics(client):
    tc, sessions = client
    db = sessions()
    rec = CallRecorder(db, channel="web")
    rec.record_payment(
        leaf="test_prep/SAT", amount=85.0, currency="usd", kind="link",
        provider_ref="plink_1", url="https://pay/x",
    )
    from app.agent.recorder import mark_payment_paid
    mark_payment_paid(db, "plink_1")
    cid = rec.call_id
    db.close()

    row = next(c for c in tc.get("/api/calls").json() if c["call_id"] == cid)
    assert row["payment"]["status"] == "paid"
    detail = tc.get(f"/api/calls/{cid}").json()
    assert detail["payments"][0]["url"] == "https://pay/x"
    m = tc.get("/api/router-metrics").json()
    assert m["payments_paid"] == 1 and m["paid_rate"] == 1.0 and m["revenue"] == 85.0


def test_send_payment_sms_endpoint(client, monkeypatch):
    tc, sessions = client
    db = sessions()
    rec = CallRecorder(db, channel="web")
    rec.record_payment(
        leaf="test_prep/SAT", amount=85.0, currency="usd", kind="link",
        provider_ref="plink_1", url="https://pay/x",
    )
    cid = rec.call_id
    db.close()

    # Fake SMS via fake mode so no Twilio creds are needed.
    from app.dashboard import router as dash
    monkeypatch.setattr(dash, "get_settings", lambda: Settings(_env_file=None, payments_fake=True))

    ok = tc.post(f"/api/calls/{cid}/send-payment-sms", json={"phone": "+15551234567"})
    assert ok.status_code == 200 and ok.json()["status"] == "sent"
    # detail now reflects the sent status
    detail = tc.get(f"/api/calls/{cid}").json()
    assert detail["payments"][-1]["status"] == "sent"

    # No payment on a fresh call -> 400.
    db = sessions()
    empty = CallRecorder(db, channel="web").call_id
    db.commit()
    db.close()
    assert tc.post(f"/api/calls/{empty}/send-payment-sms", json={"phone": "+1"}).status_code == 400


def test_catalog_endpoint(client):
    tc, _ = client
    cat = tc.get("/api/catalog").json()
    cats = {c["key"]: c for c in cat["categories"]}
    assert set(cats) == {"test_prep", "tutoring"}
    # all 8 leaves present with prices + summaries
    leaves = [lf for c in cat["categories"] for g in c["groups"] for lf in g["leaves"]]
    assert len(leaves) == 8
    assert all(lf["display"] and lf["summary"] for lf in leaves)
    # tutoring is grouped by subject area
    assert {g["label"] for g in cats["tutoring"]["groups"]} == {"Math", "Science"}
