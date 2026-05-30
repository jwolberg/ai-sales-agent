"""Observability API endpoints — KPIs and per-call review (PRD §10.2, §10.3).

JSON the dashboard UI (static, served at /dashboard) reads: aggregate §16 KPIs (sliceable by
version/variant) and per-call transcript + decision trace + KPI events. Read-only.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import taxonomy as tx
from app.agent.pricing import quote_price
from app.agent.recorder import PAYMENT_SENT
from app.config import get_settings
from app.db.models import Call
from app.db.session import get_db
from app.events import Subscription, bus
from app.kpis.metrics import compute_metrics, compute_router_metrics
from app.payments.sms import SmsError, get_sms_sender
from app.simulator.live_feed import run_sim_call_paced
from app.simulator.personas import get_personas

# Short, operator-facing descriptions of the two top-level options the agent routes between.
_CATEGORY_DESC = {
    "test_prep": "Prep for a college-admissions test — pick the test the student is taking.",
    "tutoring": "One-on-one help in a specific school subject (math or science).",
}

# SSE keepalive cadence (seconds) so proxies don't drop an idle stream.
_SSE_KEEPALIVE = 15.0

router = APIRouter(prefix="/api", tags=["observability"])

Db = Annotated[Session, Depends(get_db)]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _payment_dict(payment) -> dict:
    return {
        "payment_id": payment.payment_id,
        "kind": payment.kind,
        "status": payment.status,
        "amount": payment.amount,
        "currency": payment.currency,
        "url": payment.url,
        "created_at": _iso(payment.created_at),
        "paid_at": _iso(payment.paid_at),
    }


def _latest_payment(call: Call) -> dict | None:
    """The most recent payment for the board (status badge); None if the call had no payment."""
    if not call.payments:
        return None
    return _payment_dict(max(call.payments, key=lambda p: p.created_at))


# stop_secs values the evaluator sweeps by default; the call's own value is merged in so the row
# for "what this call used" always appears.
_VAD_SWEEP_BASE = [0.2, 0.4, 0.6, 0.8, 1.0]
# Audio isn't stored per call (see docs/implementation-notes.md VAD-T2/T3), so the operator points
# the harness at a clip they record. This placeholder marks where that path goes in the command.
_VAD_CLIP_PLACEHOLDER = "<your-clip.wav>"


def _vad_eval(call: Call) -> dict:
    """Per-call turn-taking evaluator payload (VAD-T4).

    Exposes the VAD dials the call ran under (or the current config, flagged, for calls recorded
    before VAD-T3) and a ready-to-run ``vad_replay`` command + sweep prefilled with them. The
    operator records a clip with natural pauses and runs the command to see where the agent would
    have started talking — the way to tune "the agent jumps in too soon" without a live call.
    """
    params = call.vad_params
    from_call = params is not None
    if params is None:
        params = get_settings().vad_params()  # older call: show today's config, clearly flagged

    def _fmt(p: dict) -> str:
        return (
            f"--stop-secs {p['stop_secs']} --start-secs {p['start_secs']} "
            f"--confidence {p['confidence']} --min-volume {p['min_volume']}"
        )

    sweep = sorted({*_VAD_SWEEP_BASE, params["stop_secs"]})
    base = f"python -m app.simulator.vad_replay {_VAD_CLIP_PLACEHOLDER}"
    return {
        "params": params,
        "from_call": from_call,  # False → params are the current config, not this call's record
        # Replays a clip at the exact dials this call used.
        "command": f"{base} {_fmt(params)}",
        # Compares stop_secs around this call's value so you can pick a better one.
        "sweep_command": f"{base} --sweep {','.join(str(v) for v in sweep)}",
        "clip_placeholder": _VAD_CLIP_PLACEHOLDER,
    }


def _call_summary(call: Call) -> dict:
    return {
        "call_id": call.call_id,
        "lead_id": call.lead_id,
        "channel": call.channel,
        "started_at": _iso(call.started_at),
        "ended_at": _iso(call.ended_at),
        "outcome": call.outcome,
        "agent_version": call.agent_version,
        "model_version": call.model_version,
        "is_synthetic": call.is_synthetic,
        "num_turns": len(call.turns),
        # Intent-router result (IR6-T2): the leaf the call reached and the price quoted.
        "reached_leaf": call.reached_leaf,
        "quoted_price": call.quoted_price,
        # Payment state for the board badge (PAY5-T1): the latest payment, or null.
        "payment": _latest_payment(call),
    }


@router.get("/metrics")
def metrics(
    db: Db,
    agent_version: str | None = None,
    variant_id: str | None = None,
) -> dict:
    """Aggregate §16 KPIs across calls (optionally sliced by version/variant)."""
    return compute_metrics(db, agent_version=agent_version, variant_id=variant_id)


@router.get("/router-metrics")
def router_metrics(db: Db, include_synthetic: bool = True) -> dict:
    """Intent-router KPIs derivable from persisted calls (IR6-T2): leaf-reached / quote /
    escalation / mis-quote rates + avg clarifications. Classification accuracy needs ground
    truth and is reported by the benchmark, not here."""
    return compute_router_metrics(db, include_synthetic=include_synthetic)


async def _sse(sub: Subscription, request: Request):
    """Yield Server-Sent Events from a subscription until the client disconnects (IR7-T2)."""
    try:
        yield ": connected\n\n"
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=_SSE_KEEPALIVE)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        bus.unsubscribe(sub)


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Live event stream for all calls (call_started / turn / decision / kpi / call_ended)."""
    sub = bus.subscribe()
    return StreamingResponse(_sse(sub, request), media_type="text/event-stream")


@router.get("/calls/{call_id}/stream")
async def call_stream(call_id: str, request: Request) -> StreamingResponse:
    """Live event stream filtered to one call."""
    sub = bus.subscribe(call_id=call_id)
    return StreamingResponse(_sse(sub, request), media_type="text/event-stream")


def _leaf_entry(leaf: tx.Leaf) -> dict:
    rec = quote_price(leaf)
    return {
        "id": leaf.id,
        "label": leaf.label,
        "price": rec.amount if rec else None,
        "unit": rec.unit if rec else None,
        "display": rec.display if rec else None,
        "summary": rec.summary if rec else None,
        "approved": rec.approved if rec else None,
    }


@router.get("/catalog")
def catalog() -> dict:
    """The agent's offerings — the taxonomy the router classifies into, each leaf with its
    authoritative price and KB-sourced summary. Powers the dashboard's catalog/explainer panel."""
    test_leaves = [_leaf_entry(tx.Leaf(tx.Category.TEST_PREP, test=t)) for t in tx.TESTS]
    tutoring_groups = [
        {
            "label": area.title(),
            "leaves": [
                _leaf_entry(tx.Leaf(tx.Category.TUTORING, subject_area=area, subject=s))
                for s in subjects
            ],
        }
        for area, subjects in tx.SUBJECTS.items()
    ]
    return {
        "categories": [
            {
                "key": "test_prep",
                "label": "Test Prep",
                "description": _CATEGORY_DESC["test_prep"],
                "groups": [{"label": None, "leaves": test_leaves}],
            },
            {
                "key": "tutoring",
                "label": "Tutoring",
                "description": _CATEGORY_DESC["tutoring"],
                "groups": tutoring_groups,
            },
        ]
    }


@router.get("/sim/personas")
def sim_personas() -> list[dict]:
    """The ground-truth router personas available to drive a simulated live call (IR7-T3)."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "target_leaf": p.target_leaf,
            "opening_line": p.opening_line,
        }
        for p in get_personas().router_personas()
    ]


class SimStartRequest(BaseModel):
    persona: str | None = None


@router.post("/sim/start")
async def sim_start(payload: SimStartRequest | None = None) -> dict:
    """Kick off a paced simulated call in the background; it streams over /api/stream (IR7-T3)."""
    personas = get_personas().router_personas()
    key = payload.persona if payload else None
    persona = next((p for p in personas if p.key == key), personas[0])
    asyncio.create_task(run_sim_call_paced(persona))
    return {"started": True, "persona": persona.key, "target_leaf": persona.target_leaf}


@router.get("/calls")
def list_calls(db: Db) -> list[dict]:
    """All calls, newest first (summary rows for the dashboard table)."""
    calls = db.scalars(select(Call).order_by(Call.started_at.desc())).all()
    return [_call_summary(c) for c in calls]


@router.get("/calls/{call_id}")
def call_detail(call_id: str, db: Db) -> dict:
    """One call's transcript, decision trace, and KPI events (§10.3)."""
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="call not found")
    turns = sorted(call.turns, key=lambda t: t.timestamp)
    return {
        **_call_summary(call),
        "summary": call.summary,
        "turns": [
            {
                "speaker": t.speaker,
                "text": t.text,
                "timestamp": _iso(t.timestamp),
                "detected_intent": t.detected_intent,
                "detected_objection": t.detected_objection,
            }
            for t in turns
        ],
        "decisions": [
            {
                "stage": d.stage,
                "selected_action": d.selected_action,
                "reason": d.reason,
                "confidence": d.confidence,
                "missing_fields": d.missing_fields,
                "kb_sources_used": d.kb_sources_used,
                "escalation_risk": d.escalation_risk,
                # Intent-router trace (IR6-T2): cumulative slot state + resolved leaf this turn.
                "slots": d.slots,
                "leaf": d.leaf,
                "turn_id": d.turn_id,
                "created_at": _iso(d.created_at),
            }
            for d in sorted(call.decisions, key=lambda d: d.created_at)
        ],
        "kpi_events": [
            {
                "event_type": e.event_type,
                "metadata": e.event_metadata,
                "created_at": _iso(e.created_at),
            }
            for e in sorted(call.kpi_events, key=lambda e: e.created_at)
        ],
        # Payments for this call (PAY5-T1), oldest first.
        "payments": [
            _payment_dict(p) for p in sorted(call.payments, key=lambda p: p.created_at)
        ],
        # Turn-taking evaluator: the VAD dials this call ran under + a prefilled harness command.
        "vad_eval": _vad_eval(call),
    }


class SendPaymentSms(BaseModel):
    phone: str


@router.post("/calls/{call_id}/send-payment-sms")
def send_payment_sms(call_id: str, body: SendPaymentSms, db: Db) -> dict:
    """Text this call's latest payment link to a number the operator typed (PAY7-T2).

    A web Test Call has no caller ID, so the link is texted on demand. Uses the fake SMS sender in
    dev fake mode; otherwise real Twilio."""
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="call not found")
    if not call.payments:
        raise HTTPException(status_code=400, detail="no payment link for this call yet")
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="a phone number is required")
    payment = max(call.payments, key=lambda p: p.created_at)
    try:
        sender = get_sms_sender(get_settings())
    except SmsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    body_text = f"Here's your secure link to get started with Nerdy: {payment.url}"
    try:
        sid = sender.send(phone, body_text)
    except SmsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    payment.status = PAYMENT_SENT
    db.commit()
    bus.publish(
        call_id=call_id,
        type="payment_sent",
        payment_id=payment.payment_id,
        leaf=payment.leaf,
        amount=payment.amount,
        currency=payment.currency,
        kind=payment.kind,
        url=payment.url,
        status=PAYMENT_SENT,
    )
    return {"status": "sent", "message_sid": sid}
