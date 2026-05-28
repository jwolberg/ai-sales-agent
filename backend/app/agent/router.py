"""Per-turn routing: decide which capability handles the caller's turn (P4.5-T1).

The router is the first step of the decider-led runtime (docs/AGENT_INTEGRATION.md). Each turn
it classifies the caller's utterance and picks the handler, in strict priority order:

    escalate (DE-4) > stop-selling (refusal, §18) > objection > knowledge question > progress

It is a **pure, deterministic classifier** — it does not run the capability or touch the DB; the
conversation engine (P4.5-T4) dispatches on the result. It reuses the existing detectors
(`detect_escalation`, `should_stop_selling`, the objection playbook, `is_knowledge_question`),
so behavior stays consistent with the capabilities themselves.

Confidence-based escalation (escalate rather than guess) is intentionally *not* handled here —
it's a post-decision check the engine applies, so a clear turn never escalates just because a
prior step was uncertain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.agent.guardrails import detect_escalation, should_stop_selling
from app.agent.knowledge import is_knowledge_question
from app.agent.objections import ObjectionPlaybook, get_objection_playbook


class Route(str, Enum):
    """Which capability should handle this turn."""

    ESCALATE = "escalate"          # DE-4 trigger -> hand off to a human
    STOP_SELLING = "stop_selling"  # clear refusal -> stop pushing (§18)
    OBJECTION = "objection"        # recognized objection -> rebuttal from the playbook
    KNOWLEDGE = "knowledge"        # a question -> grounded KB answer
    PROGRESS = "progress"          # default -> advance discovery / close via the decider


@dataclass(frozen=True)
class RouteDecision:
    """The chosen route plus why, and the detected detail the engine will need."""

    route: Route
    reason: str
    detail: str | None = None  # escalation trigger code or objection key, when applicable


def classify_turn(
    text: str, *, objection_playbook: ObjectionPlaybook | None = None
) -> RouteDecision:
    """Classify a caller turn into a :class:`Route`, applying strict priority.

    Note the deliberate split that falls out of the detectors: a hard concession demand
    ("discount", "lower the price") trips the DE-4 escalation trigger and routes to ESCALATE,
    while a value objection ("it's too expensive") routes to OBJECTION and gets the consultative
    price rebuttal. That matches DE-4 + the §8 baseline.
    """
    playbook = objection_playbook or get_objection_playbook()

    trigger = detect_escalation(text)  # cue-based only; confidence handled downstream
    if trigger is not None:
        return RouteDecision(Route.ESCALATE, trigger.reason, detail=trigger.code)

    if should_stop_selling(text):
        return RouteDecision(Route.STOP_SELLING, "caller clearly refused (§18 stop-selling)")

    objection = playbook.detect(text)
    if objection is not None:
        return RouteDecision(Route.OBJECTION, f"objection '{objection.key}'", detail=objection.key)

    if is_knowledge_question(text):
        return RouteDecision(Route.KNOWLEDGE, "caller asked a question")

    return RouteDecision(Route.PROGRESS, "advance discovery / close")
