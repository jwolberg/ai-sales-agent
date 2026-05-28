"""Conversation engine — the decider-led runtime loop (P4.5-T4).

Ties the pieces into one transport-agnostic turn: extract → route → dispatch to the right
capability → render → record (transcript + decision trace). The live voice pipeline (P4.5-T5)
and the synthetic simulator (Phase 6) both drive this same engine; only the transport differs.

It wraps an :class:`Orchestrator` (which holds the call state, persona, recorder, and the
capability methods) and owns the per-turn control flow:

    run_turn(text):
        record prospect turn
        extract fields/signals      (P4.5-T2) -> merge into state
        classify the turn           (P4.5-T1)
        dispatch -> NextAction       (escalate / stop / objection / knowledge / clarify / progress)
        advance state, render words  (P4.5-T3)
        record decision + agent turn

`synthesize` is the LLM phrasing function used for GROUND directives (present live, omitted in
text-mode/tests, where GROUND degrades to the honest KB-4 fallback).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.agent.discovery import get_discovery_playbook
from app.agent.extraction import Extractor, get_extractor
from app.agent.orchestrator import NextAction, Orchestrator
from app.agent.persona import build_greeting_cue
from app.agent.render import Directive, render, to_directive
from app.agent.router import Route, RouteDecision, classify_turn
from app.agent.stages import Action, Modifier, Stage
from app.kpis import events as kpi

# Stages where the agent has just asked for a discovery value the next turn should fill.
_PENDING_STAGES = (Stage.DISCOVERY, Stage.NEED_DEVELOPMENT)


@dataclass
class TurnResult:
    """The outcome of one engine turn."""

    route: Route
    action: NextAction
    directive: Directive
    utterance: str
    understood: bool


class ConversationEngine:
    """Drives a call through the decider-led runtime."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        extractor: Extractor | None = None,
        synthesize: Callable[[str], str] | None = None,
        classify: Callable[[str], RouteDecision] = classify_turn,
    ) -> None:
        self.orch = orchestrator
        self.extractor = extractor or get_extractor()
        self.synthesize = synthesize
        self._classify = classify

    @property
    def state(self):
        return self.orch.state

    def open(self) -> str:
        """Greet first and record it (the greeting precedes any decision; AGENT_FLOW §4.5)."""
        self.orch.open()  # sets stage = GREETING
        greeting = self._greeting()
        self._emit_agent(greeting)
        return greeting

    def run_turn(self, user_text: str) -> TurnResult:
        state = self.state

        # 1. Classify the turn, then record the prospect turn tagged with the detected intent
        #    (the route) and objection (DE-2 trace).
        decision = self._classify(user_text)
        objection_key = decision.detail if decision.route is Route.OBJECTION else None
        prospect_turn = self._record_prospect(
            user_text, detected_intent=decision.route.value, detected_objection=objection_key
        )

        # 2. Extract fields + signals and fold them into state.
        extraction = self.extractor.extract(user_text, pending_field=state.pending_field)
        state.collected_fields.update(extraction.fields)
        if extraction.buying_intent:
            state.buying_intent = True
        if extraction.disqualified:
            state.disqualified = True

        # 3. Dispatch to a capability (or clarify a non-answer to the pending question).
        if (
            decision.route is Route.PROGRESS
            and state.pending_field
            and not extraction.understood
        ):
            action = self._clarify(state.pending_field)
        else:
            action = self._dispatch(decision, user_text)

        # 4. Advance state.
        was_summarized = state.fit_summarized
        state.user_turns += 1
        state.stage = action.stage
        if action.stage is Stage.CONTEXT_CONFIRMATION:
            state.context_confirmed = True
        if action.stage is Stage.FIT_SUMMARY:
            state.fit_summarized = True
        state.pending_field = (
            action.question_key if action.stage in _PENDING_STAGES else None
        )

        # 4b. Emit KPI events for this turn (PRD §16).
        if decision.route is Route.OBJECTION:
            self._emit_kpi(kpi.OBJECTION_RAISED, objection=objection_key)
        if action.action is Action.ESCALATE:
            self._emit_kpi(kpi.ESCALATION, code=action.question_key)
        if action.action is Action.ATTEMPT_CLOSE:
            self._emit_kpi(kpi.CLOSE_ATTEMPT, next_step=action.question_key)
        if action.stage is Stage.FIT_SUMMARY and not was_summarized:
            self._emit_kpi(kpi.DISCOVERY_COMPLETE)

        # 5. Render words, 6. record the decision (linked to the prospect turn) + agent turn.
        directive = to_directive(action)
        utterance = render(directive, synthesize=self.synthesize)
        turn_id = prospect_turn.turn_id if prospect_turn is not None else None
        self._record_decision(action, turn_id=turn_id)
        self._emit_agent(utterance)

        return TurnResult(
            route=decision.route,
            action=action,
            directive=directive,
            utterance=utterance,
            understood=extraction.understood,
        )

    # --- dispatch ----------------------------------------------------------------------

    def _dispatch(self, decision: RouteDecision, user_text: str) -> NextAction:
        if decision.route is Route.ESCALATE:
            return self.orch.check_escalation(user_text) or self._stop()
        if decision.route is Route.STOP_SELLING:
            return self._stop()
        if decision.route is Route.OBJECTION:
            return self.orch.handle_objection(user_text) or self._progress(user_text)
        if decision.route is Route.KNOWLEDGE:
            return self.orch.answer_knowledge(user_text)
        return self._progress(user_text)

    def _progress(self, user_text: str) -> NextAction:
        return self.orch.decider.decide(self.state, user_text)

    def _stop(self) -> NextAction:
        return NextAction(
            stage=Stage.WRAP_UP,
            action=Action.END_CALL,
            reason="caller declined; stopping per §18",
            confidence=0.9,
            prompt=(
                "Totally understand — I won't take more of your time. If anything changes, "
                "we're here to help. Take care!"
            ),
        )

    def _clarify(self, field: str) -> NextAction:
        playbook = get_discovery_playbook()
        question = next(
            (q for q in playbook.required + playbook.leading if q.key == field), None
        )
        ask = question.prompt if question else "could you tell me a bit more about that?"
        return NextAction(
            stage=self.state.stage,  # stay where we are
            action=Action.ASK_REQUIRED_DISCOVERY,
            modifier=Modifier.CLARIFY,
            reason=f"unclear answer for '{field}'; clarifying (LM-2)",
            confidence=0.5,
            question_key=field,
            prompt=f"Sorry, I want to make sure I get this right — {ask}",
        )

    # --- helpers -----------------------------------------------------------------------

    def _greeting(self) -> str:
        settings = self.orch.settings
        if self.synthesize is not None:
            return self.synthesize(build_greeting_cue(settings))
        return (
            f"Hi, this is {settings.agent_name} with {settings.company_name}. "
            "How can I help today?"
        )

    def _record_prospect(
        self,
        text: str,
        *,
        detected_intent: str | None = None,
        detected_objection: str | None = None,
    ):
        """Record the prospect turn (tagged with detected intent/objection); returns the Turn,
        or None when there's no recorder."""
        self.state.history.append(("prospect", text))
        if self.orch.recorder is not None:
            return self.orch.recorder.record_prospect(
                text, detected_intent=detected_intent, detected_objection=detected_objection
            )
        return None

    def _emit_agent(self, text: str) -> None:
        self.state.history.append(("agent", text))
        if self.orch.recorder is not None:
            self.orch.recorder.record_agent(text)

    def _record_decision(self, action: NextAction, *, turn_id: str | None = None) -> None:
        if self.orch.recorder is not None:
            self.orch.recorder.record_decision(action, turn_id=turn_id)

    def _emit_kpi(self, event_type: str, **metadata) -> None:
        if self.orch.recorder is not None:
            self.orch.recorder.record_event(event_type, metadata=metadata or None)

    def end(self, *, outcome: str | None = None, summary: str | None = None) -> None:
        """Finalize the call: emit a CALL_COMPLETED KPI event and stamp the Call (ended/outcome)."""
        self._emit_kpi(kpi.CALL_COMPLETED, outcome=outcome)
        self.orch.end(outcome=outcome, summary=summary)
