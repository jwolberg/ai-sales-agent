"""Fit summary, close criteria, and next-step recommendation (PRD §9.5 DE-3; §9.6 CF-1..3).

Pure logic (no DB, no LLM): given what's been collected and the current signal state,
decide whether the agent may pivot toward close (DE-3), build a fit summary (CF-1), and
recommend one concrete next step (CF-2). The :class:`CloseAttempt` record carries the
fields CF-3 says every close attempt must log; persistence lives in the recorder.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# CF-2: the concrete next steps the agent may recommend.
NEXT_STEP_CONSULTATION = "schedule_consultation"
NEXT_STEP_MATCH_TUTOR = "match_with_tutor"
NEXT_STEP_ENROLLMENT = "start_enrollment"
NEXT_STEP_TRANSFER = "transfer_to_specialist"
NEXT_STEP_FOLLOWUP = "send_followup_info"

_NEXT_STEP_PROMPTS = {
    NEXT_STEP_CONSULTATION: "Would it help to set up a quick consultation to map out a plan?",
    NEXT_STEP_MATCH_TUTOR: (
        "Based on everything you've shared, I'd love to match you with a tutor this "
        "week — want to get that started?"
    ),
    NEXT_STEP_ENROLLMENT: "Shall we go ahead and get enrollment started?",
    NEXT_STEP_TRANSFER: (
        "I can connect you with a specialist to finalize the details — would that help?"
    ),
    NEXT_STEP_FOLLOWUP: "How about I send over some info so you can review it on your own time?",
}

# Close type = the manner of the ask (AGENT_FLOW §5.13), matched to readiness.
CLOSE_DIRECT = "direct"
CLOSE_TRIAL = "trial"
CLOSE_SOFT = "soft"

# CloseAttempt.outcome values (CF-3).
OUTCOME_ACCEPTED = "accepted"
OUTCOME_DECLINED = "declined"
OUTCOME_DEFERRED = "deferred"


@dataclass
class CloseReadiness:
    """Result of the DE-3 check: whether to pivot toward close, and why not if not."""

    ready: bool
    reasons: list[str]  # unmet criteria; empty when ready


def assess_close_criteria(
    *,
    discovery_complete: bool,
    buying_intent: bool,
    high_risk_objection: bool,
) -> CloseReadiness:
    """Evaluate the DE-3 close criteria. (Confidence is approximated by discovery
    completeness for now; an explicit confidence signal arrives with later detection.)"""
    reasons: list[str] = []
    if not discovery_complete:
        reasons.append("required discovery incomplete")
    if not buying_intent:
        reasons.append("no clear buying intent yet")
    if high_risk_objection:
        reasons.append("unresolved high-risk objection")
    return CloseReadiness(ready=not reasons, reasons=reasons)


def build_fit_summary(collected: Mapping[str, object]) -> str:
    """Summarize the prospect's situation before closing (CF-1), from known fields."""
    subject_grade = " ".join(
        str(collected[k]) for k in ("grade_level", "subject") if collected.get(k)
    )
    bits: list[str] = []
    if subject_grade:
        bits.append(f"this is about {subject_grade}")
    if collected.get("challenge"):
        bits.append(f"the main challenge has been {collected['challenge']}")
    if collected.get("goal"):
        bits.append(f"you're hoping to {collected['goal']}")
    body = "; ".join(bits) if bits else "I've got the basics of what you're looking for"
    return (
        f"So, to make sure I've got it: {body}. "
        "Based on that, personalized tutoring sounds like a strong fit."
    )


def choose_close(
    *, buying_intent: bool, high_risk_objection: bool
) -> tuple[str, str]:
    """Pick the close type and one next step (CF-2), matched to readiness."""
    if high_risk_objection:
        return CLOSE_SOFT, NEXT_STEP_FOLLOWUP
    if buying_intent:
        return CLOSE_DIRECT, NEXT_STEP_MATCH_TUTOR
    return CLOSE_TRIAL, NEXT_STEP_CONSULTATION


def next_step_prompt(next_step: str) -> str:
    """The spoken phrasing for a recommended next step."""
    return _NEXT_STEP_PROMPTS.get(next_step, "What would you like the next step to be?")


@dataclass
class CloseAttempt:
    """Everything CF-3 requires logging for a close attempt (timing is the log time)."""

    close_type: str
    next_step: str
    objection_state: str | None = None  # preceding objection state
    user_response: str | None = None
    outcome: str | None = None
