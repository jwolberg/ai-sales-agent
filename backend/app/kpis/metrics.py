"""Compute the strategy KPIs from recorded calls + KPI events (PRD §16, §10.2).

Metrics are computed across calls (optionally sliced by agent/playbook/kb/model version or
variant, for the experiment loop). Metrics whose inputs aren't captured yet — latency and
frustration — are returned as ``None`` rather than a misleading 0, so the dashboard can show
"not measured" honestly.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.recorder import OUTCOME_COMPLETED, PAYMENT_PAID
from app.db.models import Call
from app.kpis import events as kpi


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (pct in 0..100). None for an empty list.

    Nearest-rank: rank = ceil(pct/100 * N), 1-based, so the 0-based index is rank - 1. The earlier
    ``round(x + 0.5) - 1`` form was a broken ceil — Python's banker's rounding made it bias the
    index high (e.g. p95 of 20 returned the max, p50 of 2 returned the larger value), inflating p95.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil((pct / 100) * len(ordered))
    k = max(0, min(len(ordered) - 1, rank - 1))
    return round(ordered[k], 1)


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


def compute_router_metrics(session: Session, *, include_synthetic: bool = True) -> dict:
    """Intent-router KPIs derivable from persisted calls (IR5-T2).

    Classification *accuracy* needs the persona's ground-truth leaf and lives in the benchmark
    report (`simulator/benchmark.py`); these are the DB-only rates the dashboard can show for any
    call (live or synthetic), where no ground truth exists.
    """
    stmt = select(Call)
    if not include_synthetic:
        stmt = stmt.where(Call.is_synthetic.is_(False))
    calls = list(session.scalars(stmt))
    total = len(calls)

    def count(call: Call, event_type: str) -> int:
        return sum(e.event_type == event_type for e in call.kpi_events)

    n_leaf = sum(c.reached_leaf is not None for c in calls)
    n_quoted = sum(c.quoted_price is not None for c in calls)
    n_escalation = sum(count(c, kpi.ESCALATION) > 0 for c in calls)
    n_mis_quote = sum(count(c, kpi.MIS_QUOTE_BLOCKED) > 0 for c in calls)
    total_clarify = sum(count(c, kpi.CLARIFY_ASKED) for c in calls)

    # Turn latency over agent turns that recorded a timing (IR7-T1). On voice turns this is the
    # end-to-end turnaround; the per-component split lives in latency_breakdown (LAT-T1).
    latencies = [t.latency_ms for c in calls for t in c.turns if t.latency_ms is not None]
    breakdowns = [t.latency_breakdown for c in calls for t in c.turns if t.latency_breakdown]

    def _component_mean(key: str) -> float | None:
        vals = [b[key] for b in breakdowns if b.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    # Payments (PAY5-T1): links sent, how many were paid, and confirmed revenue.
    payments = [p for c in calls for p in c.payments]
    paid = [p for p in payments if p.status == PAYMENT_PAID]

    return {
        "total_calls": total,
        "leaf_reached_rate": _rate(n_leaf, total),
        "quote_rate": _rate(n_quoted, total),
        "escalation_rate": _rate(n_escalation, total),
        "mis_quote_rate": _rate(n_mis_quote, total),
        "avg_clarifications": round(total_clarify / total, 2) if total else None,
        "turn_latency_ms_p50": _percentile(latencies, 50),
        "turn_latency_ms_p95": _percentile(latencies, 95),
        # Mean stt/brain/tts split across voice turns that captured it (null in text-only data).
        "turn_latency_breakdown_ms": (
            {
                "stt": _component_mean("stt_ms"),
                "brain": _component_mean("brain_ms"),
                "tts": _component_mean("tts_ms"),
            }
            if breakdowns
            else None
        ),
        "payments_sent": len(payments),
        "payments_paid": len(paid),
        "paid_rate": _rate(len(paid), len(payments)),
        "revenue": round(sum(p.amount for p in paid), 2),
    }
