"""Observability API endpoints — KPIs and per-call review (PRD §10.2, §10.3).

JSON the dashboard UI (static, served at /dashboard) reads: aggregate §16 KPIs (sliceable by
version/variant) and per-call transcript + decision trace + KPI events. Read-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Call
from app.db.session import get_db
from app.kpis.metrics import compute_metrics

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
    }


@router.get("/metrics")
def metrics(
    db: Db,
    agent_version: str | None = None,
    variant_id: str | None = None,
) -> dict:
    """Aggregate §16 KPIs across calls (optionally sliced by version/variant)."""
    return compute_metrics(db, agent_version=agent_version, variant_id=variant_id)


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
