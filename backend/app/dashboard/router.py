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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Call
from app.db.session import get_db
from app.events import Subscription, bus
from app.kpis.metrics import compute_metrics, compute_router_metrics

# SSE keepalive cadence (seconds) so proxies don't drop an idle stream.
_SSE_KEEPALIVE = 15.0

router = APIRouter(prefix="/api", tags=["observability"])

Db = Annotated[Session, Depends(get_db)]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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
    }
