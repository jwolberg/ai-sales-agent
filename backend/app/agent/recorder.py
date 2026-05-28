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

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.agent.closing import CloseAttempt
from app.db.models import Call, Decision, KPIEvent, Turn

if TYPE_CHECKING:  # avoid a runtime import cycle (orchestrator imports CallRecorder)
    from app.agent.orchestrator import NextAction

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        )
        session.add(self._call)
        session.flush()  # assign call_id without ending the surrounding transaction

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
        )
        self._session.add(turn)
        self._session.commit()
        return turn

    def record_agent(self, text: str, **kwargs) -> Turn:
        """Record something the agent said."""
        return self.record_turn(SPEAKER_AGENT, text, **kwargs)

    def record_prospect(self, text: str, **kwargs) -> Turn:
        """Record something the caller said."""
        return self.record_turn(SPEAKER_PROSPECT, text, **kwargs)

    def record_decision(self, action: NextAction, *, turn_id: str | None = None) -> Decision:
        """Log the per-turn decision trace (PRD DE-2) from a NextAction."""
        decision = Decision(
            call_id=self._call.call_id,
            turn_id=turn_id,
            stage=action.stage.value if action.stage is not None else None,
            selected_action=action.action.value,
            reason=action.reason,
            confidence=action.confidence,
            missing_fields=list(action.missing_fields),
            escalation_risk=action.escalation_risk,
            kb_sources_used=list(action.kb_sources),
        )
        self._session.add(decision)
        self._session.commit()
        return decision

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
        return event

    def record_close_attempt(self, attempt: CloseAttempt) -> KPIEvent:
        """Log a close attempt (CF-3) as a KPIEvent; ``created_at`` captures the timing."""
        event = KPIEvent(
            call_id=self._call.call_id,
            event_type="close_attempt",
            event_metadata={
                "close_type": attempt.close_type,
                "next_step": attempt.next_step,
                "objection_state": attempt.objection_state,
                "user_response": attempt.user_response,
                "outcome": attempt.outcome,
            },
        )
        self._session.add(event)
        self._session.commit()
        return event

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
        return self._call
