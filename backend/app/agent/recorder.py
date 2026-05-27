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

from sqlalchemy.orm import Session

from app.db.models import Call, Turn

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
    ) -> None:
        self._session = session
        self._call = Call(lead_id=lead_id, channel=channel, is_synthetic=is_synthetic)
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
