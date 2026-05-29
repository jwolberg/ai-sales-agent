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

import time
from dataclasses import dataclass

from app.agent import taxonomy as tx
from app.agent.brain import Brain, get_brain
from app.agent.contract import BrainDecision, RouterAction
from app.agent.guardrails import ESCALATION_MESSAGE, check_mis_quote
from app.agent.pricing import quote_price
from app.agent.recorder import PAYMENT_CREATED, PAYMENT_SENT
from app.config import Settings, get_settings
from app.kpis import events as kpi
from app.payments.sms import SmsError, get_sms_sender
from app.payments.stripe_service import PaymentError, get_stripe_service

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
        caller_number: str | None = None,
        stripe_service=None,
        sms_sender=None,
    ) -> None:
        self.settings = settings or get_settings()
        self.brain = brain or get_brain(self.settings)
        self.recorder = recorder
        self.lead_fields = dict(lead_fields or {})
        # Payments (PAY3-T2): the caller's number to text (Twilio `From` on a phone call), and
        # optional injected fakes for tests. Real services are built lazily when first needed.
        self.caller_number = caller_number
        self._stripe_service = stripe_service
        self._sms_sender = sms_sender
        self.history: History = []
        self.slots: dict = {k: v for k, v in self.lead_fields.items() if k in tx.SLOT_FIELDS}
        self.reached_leaf: str | None = None
        self.quoted_price: float | None = None
        self.mis_quote_count = 0

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

        # 3. The brain decides the turn (timed — the brain decision + its tool calls, IR7-T1).
        _t0 = time.perf_counter()
        decision = self.brain.decide(
            history=self.history, lead_fields=self.lead_fields, slots=self.slots
        )
        latency_ms = round((time.perf_counter() - _t0) * 1000, 1)
        self.slots = decision.slots

        # 3b. Payment (PAY3-T2): if the brain asked to send a link/invoice, execute it now. On
        #     failure (e.g. an unapproved/placeholder price) this turns into a safe escalation.
        self._maybe_execute_payment(decision, turn)

        # 4. Mis-quote guard (R6): a price the brain wasn't authorized to state is a hard
        #    violation — substitute a safe handoff and record it.
        if check_mis_quote(decision.utterance, allowed_amount=decision.quoted_amount):
            self.mis_quote_count += 1
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
        self._emit_agent(decision.utterance, latency_ms=latency_ms)

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

    # --- payments (PAY3-T2) ------------------------------------------------------------

    def _maybe_execute_payment(self, decision: BrainDecision, turn) -> None:
        """Create the hosted link/invoice the brain asked for, text it, and record it. On a
        :class:`PaymentError` (unapproved price / Stripe off) the turn becomes a safe escalation —
        the agent never states a price it isn't authorized to charge."""
        req = decision.payment_request
        if (
            req is None
            or decision.action is not RouterAction.PAY
            or not self.settings.payments_enabled
        ):
            return
        leaf = decision.leaf
        try:
            service = self._stripe_service or get_stripe_service(self.settings)
            idem = self._payment_idem(turn)
            if req.kind == "invoice":
                link = service.create_invoice(
                    leaf, customer_phone=self._payment_phone(req), idempotency_key=idem
                )
            else:
                link = service.create_payment_link(leaf, idempotency_key=idem)
        except PaymentError as exc:
            decision.action = RouterAction.ESCALATE
            decision.utterance = ESCALATION_MESSAGE
            decision.reason = f"payment unavailable ({exc}); safe handoff"
            decision.payment_request = None
            return

        texted = self._try_text_link(self._payment_phone(req), link)
        record = quote_price(leaf)
        if self.recorder is not None:
            self.recorder.record_payment(
                leaf=leaf,
                amount=record.amount if record is not None else 0.0,
                currency=self.settings.payments_currency,
                kind=req.kind,
                provider_ref=link.id,
                url=link.url,
                status=PAYMENT_SENT if texted else PAYMENT_CREATED,
            )
        self._emit_kpi(
            kpi.PAYMENT_LINK_SENT,
            metadata={"leaf": leaf, "kind": req.kind, "texted": texted, "url": link.url},
        )
        decision.utterance = self._payment_confirmation(req.kind, texted)

    def _payment_phone(self, req) -> str | None:
        return req.phone or self.caller_number

    def _payment_idem(self, turn) -> str:
        """A stable idempotency key for this turn so a retry can't double-charge."""
        base = self.recorder.call_id if self.recorder is not None else "nocall"
        suffix = turn.turn_id if turn is not None else str(len(self.history))
        return f"{base}:pay:{suffix}"

    def _try_text_link(self, phone: str | None, link) -> bool:
        """Best-effort SMS. SMS failure is non-fatal: the link still exists + shows on the board."""
        if not phone:
            return False
        try:
            sender = self._sms_sender or (
                get_sms_sender(self.settings) if self.settings.sms_enabled else None
            )
            if sender is None:
                return False
            sender.send(phone, f"Here's your secure link to get started with Nerdy: {link.url}")
            return True
        except SmsError:
            return False

    @staticmethod
    def _payment_confirmation(kind: str, texted: bool) -> str:
        base = "I've created your invoice" if kind == "invoice" else (
            "I've set up a secure payment link for you"
        )
        if texted:
            return f"{base} and just texted you the link. Anything else I can help with?"
        return f"{base}. Anything else I can help with?"

    def _emit_agent(self, text: str, *, latency_ms: float | None = None) -> None:
        self.history.append(("agent", text))
        if self.recorder is not None:
            self.recorder.record_agent(text, latency_ms=latency_ms)

    def _emit_kpi(self, event_type: str, *, metadata: dict | None = None) -> None:
        if self.recorder is not None:
            self.recorder.record_event(event_type, metadata=metadata or None)
