"""ORM models for the PRD §15 data model.

Entities: Lead, Call, Turn, Decision, KPIEvent, Payment, Experiment, Variant.
IDs are UUID hex strings so they are stable across logs, dashboards, and exports.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _uuid() -> str:
    return uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Lead(Base):
    """A prospective customer and everything known about them across calls."""

    __tablename__ = "leads"

    lead_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    student_name: Mapped[str | None] = mapped_column(String, nullable=True)
    relationship_to_student: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    grade_level: Mapped[str | None] = mapped_column(String, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    urgency: Mapped[str | None] = mapped_column(String, nullable=True)
    schedule_constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_maker_status: Mapped[str | None] = mapped_column(String, nullable=True)
    budget_sensitivity: Mapped[str | None] = mapped_column(String, nullable=True)
    # Every discovery slot learned across calls, beyond the typed columns above (e.g. challenge,
    # readiness, motivation — see data/playbooks/discovery.yaml). Keeps the full slot object so the
    # next call can skip them instead of re-asking (P10-T3). Typed columns stay canonical.
    collected_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    prior_objections: Mapped[list] = mapped_column(JSON, default=list)
    prior_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="new")
    # Separates synthetic test/seed leads from real production leads (PRD §13.3).
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    calls: Mapped[list["Call"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class Call(Base):
    """A single conversation, with full version attribution (PRD §10.4)."""

    __tablename__ = "calls"

    call_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.lead_id"), nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    playbook_version: Mapped[str | None] = mapped_column(String, nullable=True)
    kb_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.experiment_id"), nullable=True
    )
    variant_id: Mapped[str | None] = mapped_column(ForeignKey("variants.variant_id"), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Turn-taking (VAD) endpointing dials this call ran under (VAD-T3): {stop_secs, start_secs,
    # confidence, min_volume}. Stamped at call start so the dashboard evaluator can show what a
    # given call used. Null for text/synthetic calls (no audio/VAD).
    vad_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Intent-router result (IR2-T3): the leaf the call resolved to and the price quoted, if any.
    reached_leaf: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True for simulated/self-play calls; keeps them out of real-call metrics (PRD §13.3).
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    lead: Mapped[Optional["Lead"]] = relationship(back_populates="calls")
    turns: Mapped[list["Turn"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    kpi_events: Mapped[list["KPIEvent"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class Turn(Base):
    """One utterance in a call (prospect, agent, or system)."""

    __tablename__ = "turns"

    turn_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    speaker: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    detected_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_objection: Mapped[str | None] = mapped_column(String, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Wall-clock ms to produce this (agent) turn. On voice calls this is the END-TO-END turnaround
    # (user-stopped-speaking → first agent audio); text mode records just the brain time (LAT-T1).
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-component split {stt_ms, brain_ms, tts_ms} on voice turns; null in text mode (LAT-T1).
    latency_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    call: Mapped["Call"] = relationship(back_populates="turns")


class Decision(Base):
    """The agent's per-turn decision trace (PRD DE-2)."""

    __tablename__ = "decisions"

    decision_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.turn_id"), nullable=True)
    stage: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_action: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    escalation_risk: Mapped[str | None] = mapped_column(String, nullable=True)
    kb_sources_used: Mapped[list] = mapped_column(JSON, default=list)
    # Intent-router trace (IR2-T3): cumulative slot state + the resolved leaf at this turn.
    slots: Mapped[dict] = mapped_column(JSON, default=dict)
    leaf: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    call: Mapped["Call"] = relationship(back_populates="decisions")


class KPIEvent(Base):
    """A single measurable event used to compute sales KPIs (PRD §16)."""

    __tablename__ = "kpi_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    event_type: Mapped[str] = mapped_column(String)
    event_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "metadata" is reserved on the Declarative base, so map it under another attr.
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    call: Mapped["Call"] = relationship(back_populates="kpi_events")


class Payment(Base):
    """A hosted-checkout charge for a call (BUILD_PLAN_PAYMENTS, PAY2-T1).

    The agent/server never touch card data — this row tracks a Stripe Payment Link or Invoice and
    its lifecycle. ``status`` moves created -> sent -> paid (or failed); the webhook is the source
    truth for ``paid`` and looks the row up by ``provider_ref`` (Stripe id), so it's indexed.
    """

    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.call_id"))
    leaf: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="usd")
    provider: Mapped[str] = mapped_column(String, default="stripe")
    kind: Mapped[str] = mapped_column(String)  # "link" (pay-now) | "invoice" (send-invoice)
    provider_ref: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="created")  # created|sent|paid|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    call: Mapped["Call"] = relationship(back_populates="payments")


class Experiment(Base):
    """A controlled experiment over one improvement dimension (PRD §11)."""

    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    dimension: Mapped[str | None] = mapped_column(String, nullable=True)
    # Logical reference to a Variant; kept as a plain string to avoid a circular FK.
    baseline_variant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    primary_kpi: Mapped[str | None] = mapped_column(String, nullable=True)
    guardrail_kpis: Mapped[list] = mapped_column(JSON, default=list)
    start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)

    variants: Mapped[list["Variant"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class Variant(Base):
    """A candidate change under an experiment (prompt/playbook delta)."""

    __tablename__ = "variants"

    variant_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.experiment_id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_delta: Mapped[str | None] = mapped_column(Text, nullable=True)
    playbook_delta: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    experiment: Mapped[Optional["Experiment"]] = relationship(back_populates="variants")


class KBEmbedding(Base):
    """A KB chunk's embedding, persisted in SQLite (IR3-T1, D-17).

    The vector lives next to the call data so the dev retriever ranks with Python cosine and the
    production GCP build can swap in a sqlite-vec index over the same rows. ``embedding`` is a
    little-endian float32 byte string (see ``kb/embeddings.py``).
    """

    __tablename__ = "kb_embeddings"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String)
    dim: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
