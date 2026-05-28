"""Agent performance scoring for simulated calls (P6-T3; PRD §11.2 Step 1, §16).

Two layers per call:

- **Deterministic** — read straight off the recorded call: escalated? close attempted? discovery
  completed? objection raised and recovered? and `appropriate_for_persona` (a converts-persona
  should progress toward a close; a poor-fit persona should NOT be force-closed — §12.1).
- **LLM-as-judge** — qualitative signals the trace can't give: prospect frustration, unsupported
  (ungrounded) claims by the agent, and a 1–5 consultative-quality score.

The judge client is injected (tests use a fake; no API). Aggregating scores across personas into
an experiment comparison is Phase 7.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Call
from app.kpis import events as kpi
from app.simulator.personas import Persona


class JudgePayload(BaseModel):
    """Structured-output schema the judge fills in."""

    frustration: bool = Field(default=False, description="Prospect showed frustration")
    unsupported_claim: bool = Field(
        default=False, description="Agent stated an ungrounded price/guarantee/policy"
    )
    consultative_score: int = Field(
        default=3, ge=1, le=5, description="1 = pushy/scripted, 5 = genuinely consultative"
    )
    notes: str = Field(default="", description="One sentence of rationale")


@dataclass
class JudgeScores:
    frustration: bool
    unsupported_claim: bool
    consultative_score: int
    notes: str = ""


@dataclass
class CallScore:
    call_id: str
    persona_key: str
    outcome: str | None
    escalated: bool
    close_attempted: bool
    discovery_completed: bool
    objection_raised: bool
    objection_recovered: bool
    appropriate_for_persona: bool
    judge: JudgeScores | None = None


_JUDGE_SYSTEM = (
    "You are a strict, honest evaluator of tutoring sales-call transcripts. You are not trying to "
    "flatter the agent. Judge only what the transcript shows. Mark unsupported_claim=true if the "
    "AGENT stated a specific price, discount, guarantee, or policy as fact rather than deferring "
    "to a specialist. Mark frustration=true if the PROSPECT got frustrated, confused, or "
    "disengaged. Score consultative_score 1 (pushy/scripted/interrogating) to 5 (genuinely "
    "consultative: listens, adapts, develops need before closing)."
)


def _transcript_text(call: Call) -> str:
    turns = sorted(call.turns, key=lambda t: t.timestamp)
    return "\n".join(f"{t.speaker}: {t.text}" for t in turns)


def judge_transcript(
    call: Call,
    persona: Persona,
    *,
    client: object | None = None,
    settings: Settings | None = None,
) -> JudgeScores:
    """LLM-as-judge over the transcript. ``client`` is injected for tests."""
    settings = settings or get_settings()
    if client is None:
        import anthropic  # lazy

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or "")
    user = (
        f"Persona being role-played by the prospect: {persona.name} — {persona.summary}\n\n"
        f"Transcript:\n{_transcript_text(call)}"
    )
    response = client.messages.parse(
        model=settings.anthropic_model,
        max_tokens=512,
        system=[{"type": "text", "text": _JUDGE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=JudgePayload,
    )
    p: JudgePayload = response.parsed_output
    return JudgeScores(
        frustration=p.frustration,
        unsupported_claim=p.unsupported_claim,
        consultative_score=p.consultative_score,
        notes=p.notes,
    )


def score_call(
    session: Session,
    call_id: str,
    persona: Persona,
    *,
    judge: bool = True,
    judge_client: object | None = None,
    settings: Settings | None = None,
) -> CallScore:
    """Score one recorded (simulated) call deterministically, plus the LLM judge if enabled."""
    call = session.get(Call, call_id)
    if call is None:
        raise ValueError(f"call {call_id!r} not found")

    types = {e.event_type for e in call.kpi_events}
    escalated = kpi.ESCALATION in types
    close_attempted = kpi.CLOSE_ATTEMPT in types
    discovery_completed = kpi.DISCOVERY_COMPLETE in types
    objection_raised = kpi.OBJECTION_RAISED in types
    objection_recovered = objection_raised and (close_attempted or discovery_completed)

    if persona.disqualifies:
        # Good handling = the agent did NOT force a close on a poor-fit lead (§12.1).
        appropriate = not close_attempted
    elif persona.converts:
        # Good handling = the agent made real progress toward a close.
        appropriate = close_attempted or discovery_completed
    else:
        appropriate = True

    judge_scores = (
        judge_transcript(call, persona, client=judge_client, settings=settings) if judge else None
    )
    return CallScore(
        call_id=call_id,
        persona_key=persona.key,
        outcome=call.outcome,
        escalated=escalated,
        close_attempted=close_attempted,
        discovery_completed=discovery_completed,
        objection_raised=objection_raised,
        objection_recovered=objection_recovered,
        appropriate_for_persona=appropriate,
        judge=judge_scores,
    )
