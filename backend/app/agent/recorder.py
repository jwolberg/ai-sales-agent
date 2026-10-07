"""Persist a call and its transcript (PRD §10.1, §15).

A :class:`CallRecorder` owns one ``Call`` row and appends ``Turn`` rows as the
conversation unfolds, then finalizes the call with an outcome. It is deliberately
separate from the (pure, DB-free) :class:`~app.agent.orchestrator.Orchestrator` so
the decision logic stays unit-testable without a database; the live voice pipeline
and the synthetic simulator both drive a recorder alongside an orchestrator.

Turns are committed as they happen so a transcript survives a mid-call crash —
observability is the whole point of capturing them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.models import Call, Decision, KPIEvent, Payment, Turn
from app.events import bus

if TYPE_CHECKING:
    from app.agent.contract import BrainDecision

# Turn.speaker values (PRD §15).
SPEAKER_AGENT = "agent"
SPEAKER_PROSPECT = "prospect"
SPEAKER_SYSTEM = "system"

# Call.outcome values used at finalization. Free-form on the column; these are the
# conventional set so KPI rollups (P5) can rely on them.
OUTCOME_COMPLETED = "completed"
OUTCOME_ESCALATED = "escalated"
OUTCOME_DISQUALIFIED = "disqualified"
OUTCOME_ABANDONED = "abandoned"

# Payment.status lifecycle (PAY2-T1). The webhook is the source of truth for PAID.
PAYMENT_CREATED = "created"  # link/invoice made, not yet texted
PAYMENT_SENT = "sent"  # hosted URL texted to the caller
PAYMENT_PAID = "paid"  # confirmed by the Stripe webhook
PAYMENT_FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CallRecorder:
    """Records one call's ``Call`` row and ``Turn`` transcript to the database."""

    def __init__(
        self,
        session: Session,
        *,
        lead_id: str | None = None,
        channel: str | None = None,
        is_synthetic: bool = False,
        agent_version: str | None = None,
        playbook_version: str | None = None,
        kb_version: str | None = None,
        model_version: str | None = None,
        experiment_id: str | None = None,
        variant_id: str | None = None,
        vad_params: dict | None = None,
    ) -> None:
        self._session = session
        self._call = Call(
            lead_id=lead_id,
            channel=channel,
            is_synthetic=is_synthetic,
            agent_version=agent_version,  # version attribution (PRD §10.4)
            playbook_version=playbook_version,
            kb_version=kb_version,
            model_version=model_version,
            experiment_id=experiment_id,  # variant attribution (P7)
            variant_id=variant_id,
            vad_params=vad_params,  # turn-taking dials this call ran under (VAD-T3)
        )
        session.add(self._call)
        session.flush()  # assign call_id without ending the surrounding transaction
        bus.publish(
            call_id=self._call.call_id,
            type="call_started",
            channel=channel,
            is_synthetic=is_synthetic,
            lead_id=lead_id,
        )

    @property
    def call(self) -> Call:
        return self._call

    @property
    def call_id(self) -> str:
        return self._call.call_id

    def record_turn(
        self,
        speaker: str,
        text: str,
        *,
        timestamp: datetime | None = None,
        detected_intent: str | None = None,
        detected_objection: str | None = None,
        sentiment: str | None = None,
        confidence: float | None = None,
        latency_ms: float | None = None,
    ) -> Turn:
        """Append one transcript turn and commit it."""
        turn = Turn(
            call_id=self._call.call_id,
            speaker=speaker,
            text=text,
            timestamp=timestamp or _utcnow(),
            detected_intent=detected_intent,
            detected_objection=detected_objection,
            sentiment=sentiment,
            confidence=confidence,
            latency_ms=latency_ms,
        )
        self._session.add(turn)
        self._session.commit()
        bus.publish(
            call_id=self._call.call_id,
            type="turn",
            speaker=speaker,
            text=text,
            latency_ms=latency_ms,
        )
        return turn

    def record_agent(self, text: str, **kwargs) -> Turn:
        """Record something the agent said."""
        return self.record_turn(SPEAKER_AGENT, text, **kwargs)

    def record_prospect(self, text: str, **kwargs) -> Turn:
        """Record something the caller said."""
        return self.record_turn(SPEAKER_PROSPECT, text, **kwargs)

    def update_turn_latency(
        self, turn_id: str, *, latency_ms: float | None, breakdown: dict | None = None
    ) -> None:
        """Attach the end-to-end latency + stt/brain/tts breakdown to an already-recorded agent turn
        (LAT-T1). The voice path calls this once the agent's audio actually goes out — after
        ``record_agent`` already committed the turn with the brain-only timing."""
        turn = self._session.get(Turn, turn_id)
        if turn is None:
            return
        if latency_ms is not None:
            turn.latency_ms = latency_ms
        if breakdown is not None:
            turn.latency_breakdown = breakdown
        self._session.commit()

    def record_brain_decision(
        self, decision: BrainDecision, *, turn_id: str | None = None, missing: list | None = None
    ) -> Decision:
        """Log the intent-router decision trace (IR2-T3) from a BrainDecision."""
        row = Decision(
            call_id=self._call.call_id,
            turn_id=turn_id,
            stage=decision.action.value,
            selected_action=decision.action.value,
            reason=decision.reason,
            confidence=decision.confidence,
            missing_fields=list(missing or []),
            kb_sources_used=list(decision.kb_sources),
            slots=dict(decision.slots),
            leaf=decision.leaf,
        )
        self._session.add(row)
        self._session.commit()
        bus.publish(
            call_id=self._call.call_id,
            type="decision",
            action=decision.action.value,
            reason=decision.reason,
            confidence=decision.confidence,
            slots=dict(decision.slots),
            leaf=decision.leaf,
        )
        return row

    def record_result(self, *, reached_leaf: str | None, quoted_price: float | None) -> Call:
        """Stamp the call-level intent-router result (IR2-T3)."""
        self._call.reached_leaf = reached_leaf
        self._call.quoted_price = quoted_price
        self._session.commit()
        return self._call

    def record_event(
        self, event_type: str, *, value: float | None = None, metadata: dict | None = None
    ) -> KPIEvent:
        """Emit a KPI event for this call (PRD §16). ``created_at`` is the timing."""
        event = KPIEvent(
            call_id=self._call.call_id,
            event_type=event_type,
            event_value=value,
            event_metadata=metadata or {},
        )
        self._session.add(event)
        self._session.commit()
        bus.publish(
            call_id=self._call.call_id, type="kpi", event_type=event_type, metadata=metadata or {}
        )
        return event

    def record_payment(
        self,
        *,
        leaf: str | None,
        amount: float,
        currency: str,
        kind: str,
        provider_ref: str | None,
        url: str | None,
        status: str = PAYMENT_SENT,
        provider: str = "stripe",
    ) -> Payment:
        """Persist a payment for this call and publish ``payment_sent`` for the dashboard (PAY2-T1).

        ``status`` is ``sent`` once the hosted URL was texted, or ``created`` when the link exists
        but SMS was unavailable (still surfaced on the board)."""
        payment = Payment(
            call_id=self._call.call_id,
            leaf=leaf,
            amount=amount,
            currency=currency,
            kind=kind,
            provider=provider,
            provider_ref=provider_ref,
            url=url,
            status=status,
        )
        self._session.add(payment)
        self._session.commit()
        bus.publish(
            call_id=self._call.call_id,
            type="payment_sent",
            payment_id=payment.payment_id,
            leaf=leaf,
            amount=amount,
            currency=currency,
            kind=kind,
            url=url,
            status=status,
        )
        return payment

    def record_escalation(self, code: str, reason: str | None = None) -> KPIEvent:
        """Log an escalation to a human (DE-4) as a KPIEvent; ``created_at`` is the timing."""
        event = KPIEvent(
            call_id=self._call.call_id,
            event_type="escalation",
            event_metadata={"code": code, "reason": reason},
        )
        self._session.add(event)
        self._session.commit()
        return event

    def end(
        self,
        *,
        outcome: str | None = None,
        summary: str | None = None,
        recording_url: str | None = None,
    ) -> Call:
        """Finalize the call: stamp ``ended_at`` and persist outcome/summary."""
        self._call.ended_at = _utcnow()
        if outcome is not None:
            self._call.outcome = outcome
        if summary is not None:
            self._call.summary = summary
        if recording_url is not None:
            self._call.recording_url = recording_url
        self._session.commit()
        bus.publish(
            call_id=self._call.call_id,
            type="call_ended",
            outcome=self._call.outcome,
            reached_leaf=self._call.reached_leaf,
            quoted_price=self._call.quoted_price,
        )
        return self._call


def mark_payment_paid(session: Session, provider_ref: str) -> Payment | None:
    """Mark the payment with this Stripe ``provider_ref`` paid; publish ``payment_paid`` (PAY2-T1).

    Module-level (not a recorder method) because the Stripe webhook (PAY-4) resolves payments
    globally by ``provider_ref`` with no call recorder in scope. Idempotent: a row already ``paid``
    is returned unchanged so a duplicate webhook can't re-fire the event. Returns None for an
    unknown ref (the webhook treats that as a no-op)."""
    payment = session.query(Payment).filter(Payment.provider_ref == provider_ref).one_or_none()
    if payment is None:
        return None
    if payment.status == PAYMENT_PAID:
        return payment  # already settled — don't double-publish
    payment.status = PAYMENT_PAID
    payment.paid_at = _utcnow()
    session.commit()
    bus.publish(
        call_id=payment.call_id,
        type="payment_paid",
        payment_id=payment.payment_id,
        leaf=payment.leaf,
        amount=payment.amount,
        currency=payment.currency,
    )
    return payment
