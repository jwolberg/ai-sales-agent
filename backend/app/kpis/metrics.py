"""Compute the strategy KPIs from recorded calls + KPI events (PRD §16, §10.2).

Metrics are computed across calls (optionally sliced by agent/playbook/kb/model version or
variant, for the experiment loop). Metrics whose inputs aren't captured yet — latency and
frustration — are returned as ``None`` rather than a misleading 0, so the dashboard can show
"not measured" honestly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.recorder import OUTCOME_COMPLETED
from app.db.models import Call
from app.kpis import events as kpi


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def compute_metrics(
    session: Session,
    *,
    agent_version: str | None = None,
    variant_id: str | None = None,
    include_synthetic: bool = True,
) -> dict:
    """Roll up §16 KPIs over the matching calls."""
    stmt = select(Call)
    if agent_version is not None:
        stmt = stmt.where(Call.agent_version == agent_version)
    if variant_id is not None:
        stmt = stmt.where(Call.variant_id == variant_id)
    if not include_synthetic:
        stmt = stmt.where(Call.is_synthetic.is_(False))
    calls = list(session.scalars(stmt))
    total = len(calls)

    def has(call: Call, event_type: str) -> bool:
        return any(e.event_type == event_type for e in call.kpi_events)

    objection_calls = [c for c in calls if has(c, kpi.OBJECTION_RAISED)]
    recovered = sum(
        has(c, kpi.CLOSE_ATTEMPT) or has(c, kpi.DISCOVERY_COMPLETE) for c in objection_calls
    )
    n_close = sum(has(c, kpi.CLOSE_ATTEMPT) for c in calls)
    n_completed = sum(c.outcome == OUTCOME_COMPLETED for c in calls)
    n_escalation = sum(has(c, kpi.ESCALATION) for c in calls)
    n_discovery = sum(has(c, kpi.DISCOVERY_COMPLETE) for c in calls)
    n_unsupported = sum(has(c, kpi.UNSUPPORTED_CLAIM) for c in calls)

    return {
        "total_calls": total,
        # Close: attempts made vs. calls that actually completed.
        "close_attempt_rate": _rate(n_close, total),
        "close_success_rate": _rate(n_completed, total),
        # Of calls where an objection was raised, the share that kept progressing toward a close.
        "objection_recovery_rate": _rate(recovered, len(objection_calls)),
        "escalation_rate": _rate(n_escalation, total),
        "discovery_completion_rate": _rate(n_discovery, total),
        "unsupported_claim_rate": _rate(n_unsupported, total),
        # Not captured yet (need per-turn timing / sentiment) — reported as not-measured.
        "average_latency_seconds": None,
        "frustration_rate": None,
    }
