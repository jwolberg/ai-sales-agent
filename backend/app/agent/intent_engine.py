"""Intent-router conversation engine (IR2-T3, R1/R2/R3/R9).

The transport-agnostic per-turn loop for the narrowed agent. It drives the :class:`Brain` (which
owns the turn decision) and wires the deterministic rails around it:

    run_turn(text):
        record the prospect turn
        brain.decide(history, lead_fields, slots)   -> BrainDecision
        mis-quote guard on the composed reply        (IR1-T2 / R6)
        update slot state, reached leaf, quoted price
        emit KPI events + record the decision trace   (R9)
        record the agent turn

It deliberately does NOT use the legacy keyword router / discovery decider — the brain routes
(R2). The same engine drives live voice (STT-fed) and synthetic self-play (text-fed), so the
improvement loop tests the real path (R10).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent import taxonomy as tx
from app.agent.brain import Brain, get_brain
from app.agent.contract import BrainDecision, RouterAction
from app.agent.guardrails import ESCALATION_MESSAGE, check_mis_quote
from app.config import Settings, get_settings
from app.kpis import events as kpi

# Don't act on a likely-misheard low-confidence transcript; ask the caller to repeat.
STT_CONFIDENCE_THRESHOLD = 0.6

History = list[tuple[str, str]]


@dataclass
class RouterTurnResult:
    """The outcome of one engine turn."""

    decision: BrainDecision
    utterance: str

    @property
    def action(self) -> RouterAction:
        return self.decision.action

    @property
    def leaf(self) -> str | None:
        return self.decision.leaf


class IntentRouterEngine:
    """Drives a classify-and-quote call through the brain + deterministic rails."""

    def __init__(
        self,
        *,
        brain: Brain | None = None,
        recorder=None,
        lead_fields: dict | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.brain = brain or get_brain(self.settings)
        self.recorder = recorder
        self.lead_fields = dict(lead_fields or {})
        self.history: History = []
        self.slots: dict = {k: v for k, v in self.lead_fields.items() if k in tx.SLOT_FIELDS}
        self.reached_leaf: str | None = None
        self.quoted_price: float | None = None

    # --- turns -------------------------------------------------------------------------

    def open(self) -> str:
        greeting = (
            f"Hi, this is {self.settings.agent_name} with {self.settings.company_name}. "
            "Are you looking for test prep or tutoring help today?"
        )
        self._emit_agent(greeting)
        return greeting

    def run_turn(self, user_text: str, *, confidence: float | None = None) -> RouterTurnResult:
        # 1. Low-confidence STT: don't act on a probably-misheard turn (parity with old engine).
        if confidence is not None and confidence < STT_CONFIDENCE_THRESHOLD:
            return self._handle_low_confidence(user_text, confidence)

        # 2. Record the prospect turn.
        self.history.append(("prospect", user_text))
        turn = None
        if self.recorder is not None:
            turn = self.recorder.record_prospect(user_text, confidence=confidence)

        # 3. The brain decides the turn.
        decision = self.brain.decide(
            history=self.history, lead_fields=self.lead_fields, slots=self.slots
        )
        self.slots = decision.slots

        # 4. Mis-quote guard (R6): a price the brain wasn't authorized to state is a hard
        #    violation — substitute a safe handoff and record it.
        if check_mis_quote(decision.utterance, allowed_amount=decision.quoted_amount):
            self._emit_kpi(
                kpi.MIS_QUOTE_BLOCKED,
                metadata={"leaf": decision.leaf, "blocked_text": decision.utterance},
            )
            decision.utterance = ESCALATION_MESSAGE
            decision.action = RouterAction.ESCALATE
            decision.quoted_amount = None
            decision.reason = "mis-quote blocked; safe handoff substituted"

        # 5. Advance result state + emit KPI events.
        newly_reached = decision.leaf is not None and decision.leaf != self.reached_leaf
        if decision.leaf is not None:
            self.reached_leaf = decision.leaf
        if decision.quoted_amount is not None:
            self.quoted_price = decision.quoted_amount

        if newly_reached:
            self._emit_kpi(kpi.LEAF_REACHED, metadata={"leaf": decision.leaf})
        if decision.action is RouterAction.ASK:
            self._emit_kpi(kpi.CLARIFY_ASKED, metadata={"next": tx.next_unfilled(self.slots)})
        if decision.action is RouterAction.ESCALATE:
            self._emit_kpi(kpi.ESCALATION, metadata={"reason": decision.reason})

        # 6. Record the decision trace + the agent turn.
        if self.recorder is not None:
            missing = [tx.next_unfilled(self.slots)] if decision.leaf is None else []
            missing = [m for m in missing if m is not None]
            self.recorder.record_brain_decision(
                decision, turn_id=turn.turn_id if turn is not None else None, missing=missing
            )
        self._emit_agent(decision.utterance)

        return RouterTurnResult(decision=decision, utterance=decision.utterance)

    def end(self, *, outcome: str | None = None, summary: str | None = None) -> None:
        if self.recorder is not None:
            self._emit_kpi(kpi.CALL_COMPLETED, metadata={"outcome": outcome})
            self.recorder.record_result(
                reached_leaf=self.reached_leaf, quoted_price=self.quoted_price
            )
            self.recorder.end(outcome=outcome, summary=summary)

    # --- helpers -----------------------------------------------------------------------

    def _handle_low_confidence(self, user_text: str, confidence: float) -> RouterTurnResult:
        if self.recorder is not None:
            self.recorder.record_prospect(
                user_text, detected_intent="low_confidence", confidence=confidence
            )
        utterance = "Sorry, I didn't quite catch that — could you say that again?"
        decision = BrainDecision(
            action=RouterAction.ASK,
            utterance=utterance,
            reason=f"low STT confidence {confidence:.2f}; asked caller to repeat",
            confidence=confidence,
            slots=self.slots,
        )
        self._emit_agent(utterance)
        return RouterTurnResult(decision=decision, utterance=utterance)

    def _emit_agent(self, text: str) -> None:
        self.history.append(("agent", text))
        if self.recorder is not None:
            self.recorder.record_agent(text)

    def _emit_kpi(self, event_type: str, *, metadata: dict | None = None) -> None:
        if self.recorder is not None:
            self.recorder.record_event(event_type, metadata=metadata or None)
