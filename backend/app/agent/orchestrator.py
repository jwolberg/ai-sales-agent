"""Conversation orchestrator skeleton (P2-T3).

A transport-agnostic conversation loop: the agent greets, then on each user turn it
asks a *pluggable* decider what to do next. The decider returns a :class:`NextAction`
whose fields map 1:1 onto the decision trace (PRD DE-2) — stage, action, modifier,
reason, confidence, missing_fields — so persisting a turn (P2-T4 / P5-T1) is a direct
write.

Real decisioning (intent/objection/KB-aware next-best-action) lands in P3-T3. This
ticket ships the interface plus a deliberately trivial :class:`StubDecider` that walks
the happy path, so the loop runs and is unit-testable today. The persona is built once
and reused for the whole call, which is what keeps it consistent (PRD VC-4).

See docs/AGENT_FLOW.md for the stage / action / modifier model this implements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.agent.knowledge import answer_question, grounding_prompt
from app.agent.objections import get_objection_playbook, respond_to_objection
from app.agent.persona import build_greeting_cue, build_system_prompt
from app.agent.recorder import CallRecorder
from app.agent.stages import Action, Modifier, Stage
from app.config import Settings, get_settings
from app.kb.retriever import KBRetriever
from app.memory.lead_store import missing_required


@dataclass
class NextAction:
    """One decision turn. Field-for-field the persistable shape of ``Decision`` (DE-2),
    plus the discovery question chosen (P3-T3) so the phrasing layer knows what to ask."""

    stage: Stage
    action: Action
    modifier: Modifier | None = None
    reason: str | None = None
    confidence: float | None = None
    missing_fields: list[str] = field(default_factory=list)
    question_key: str | None = None
    prompt: str | None = None
    kb_sources: list[str] = field(default_factory=list)  # KB-3 source attribution


@dataclass
class ConversationState:
    """Mutable per-call state the decider reads to choose the next action.

    ``collected_fields`` starts from the lead's known profile (P3-T1) and grows as the
    agent learns more; detected signals are populated by later tickets (P4 KB/objections).
    """

    stage: Stage = Stage.GREETING
    user_turns: int = 0
    history: list[tuple[str, str]] = field(default_factory=list)  # (speaker, text)
    collected_fields: dict[str, str] = field(default_factory=dict)
    lead_id: str | None = None
    # Set once the agent has confirmed the lead's already-known context (LM-3 / P3-T3),
    # so it doesn't re-confirm on every turn.
    context_confirmed: bool = False
    # Set once a fit summary has been given, so the agent moves on to the close (P3-T4).
    fit_summarized: bool = False
    # Close-criteria signals (DE-3). Real detection lands in Phase 4; until then a driver
    # or test sets these. buying_intent = prospect has shown interest; the objection flag =
    # an unresolved high-risk objection is on the table.
    buying_intent: bool = False
    open_high_risk_objection: bool = False


@runtime_checkable
class NextActionDecider(Protocol):
    """Pluggable policy: given the conversation so far, choose the next action.

    Implementations: :class:`StubDecider` (this ticket) and the real intent/objection/
    KB-aware decisioning in P3-T3. Swapping the decider is how the orchestrator's
    behavior is replaced without touching the loop.
    """

    def decide(self, state: ConversationState, user_text: str) -> NextAction: ...


# Placeholder threshold: how many user turns the stub spends in discovery before
# moving on. Real "required fields complete?" logic (DF-1 / DE-3) arrives in P3.
_STUB_DISCOVERY_TURNS = 3


class StubDecider:
    """Linear happy-path placeholder — no real intent, objection, or KB detection.

    Walks discovery → fit summary → close → wrap-up purely off the turn count so the
    orchestrator and its decision trace are demonstrable now. Replaced wholesale by
    P3-T3; do not build real logic on top of it.
    """

    def decide(self, state: ConversationState, user_text: str) -> NextAction:
        # The orchestrator has already counted this turn before calling us.
        turn = state.user_turns

        if turn < _STUB_DISCOVERY_TURNS:
            # Open the first discovery turn with a warm opener (demonstrates the
            # modifier channel; see AGENT_FLOW §4.5 "Warm Opener / Pleasantry").
            modifier = Modifier.RAPPORT if turn == 1 else None
            return NextAction(
                stage=Stage.DISCOVERY,
                action=Action.ASK_REQUIRED_DISCOVERY,
                modifier=modifier,
                reason="stub: gathering required discovery fields",
                confidence=0.5,
            )
        if turn == _STUB_DISCOVERY_TURNS:
            return NextAction(
                stage=Stage.FIT_SUMMARY,
                action=Action.SUMMARIZE_FIT,
                reason="stub: required discovery assumed complete",
                confidence=0.5,
            )
        if turn == _STUB_DISCOVERY_TURNS + 1:
            return NextAction(
                stage=Stage.CLOSE,
                action=Action.ATTEMPT_CLOSE,
                reason="stub: attempt close after fit summary",
                confidence=0.5,
            )
        return NextAction(
            stage=Stage.WRAP_UP,
            action=Action.END_CALL,
            reason="stub: wrap up",
            confidence=0.5,
        )


class Orchestrator:
    """Drives one call: holds the consistent persona and state, delegating the
    next-action choice to a pluggable decider. Voice/transcript wiring is P2-T4.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        decider: NextActionDecider | None = None,
        recorder: CallRecorder | None = None,
        known_fields: dict[str, str] | None = None,
        lead_id: str | None = None,
        retriever: KBRetriever | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.decider = decider or StubDecider()
        # Optional: when set, prospect/agent turns are persisted as the call's
        # transcript (P2-T4). Left None for pure, DB-free decision testing.
        self.recorder = recorder
        # KB retriever for grounded answers (P4-T2); defaults to the shared one on demand.
        self._retriever = retriever
        # Built once and reused every turn — this is what keeps the persona consistent.
        self.system_prompt = build_system_prompt(self.settings)
        self.state = ConversationState(lead_id=lead_id)
        # Seed known lead context so the agent can skip-known and ask only for gaps (P3-T1).
        if known_fields:
            self.state.collected_fields.update(known_fields)

    def missing_required_fields(self) -> list[str]:
        """Required discovery fields still unknown given what we've collected (LM-2)."""
        return missing_required(self.state.collected_fields)

    def open(self) -> str:
        """Return the greeting cue for the agent's opening line.

        Greeting precedes the first user turn, so it produces no decision row
        (AGENT_FLOW §4.5); it only sets the stage. The greeting's spoken words are
        captured later via :meth:`record_agent_turn` once the LLM produces them.
        """
        self.state.stage = Stage.GREETING
        return build_greeting_cue(self.settings)

    def on_user_turn(self, user_text: str) -> NextAction:
        """Record a user turn, ask the decider for the next action, advance the stage."""
        self.state.user_turns += 1
        self.state.history.append(("user", user_text))
        if self.recorder is not None:
            self.recorder.record_prospect(user_text)
        action = self.decider.decide(self.state, user_text)
        self.state.stage = action.stage
        # Once we've entered context confirmation, don't keep re-confirming (LM-3).
        if action.stage is Stage.CONTEXT_CONFIRMATION:
            self.state.context_confirmed = True
        # Once a fit summary is given, the next discovery-complete turn moves to close.
        if action.stage is Stage.FIT_SUMMARY:
            self.state.fit_summarized = True
        return action

    def answer_knowledge(self, question: str) -> NextAction:
        """Answer a caller's question from the KB, or fall back honestly (KB-1, KB-4).

        Grounded answers carry the retrieved material in ``prompt`` (the phrasing layer must
        use only that) and their `kb_sources` for the trace; an uncovered question yields the
        honest deferral instead of a guess.
        """
        answer = answer_question(question, retriever=self._retriever)
        if answer.grounded:
            return NextAction(
                stage=Stage.KNOWLEDGE_ANSWER,
                action=Action.ANSWER_KNOWLEDGE,
                reason="answering from approved KB content (KB-1)",
                confidence=0.7,
                kb_sources=answer.sources,
                prompt=grounding_prompt(answer),
            )
        return NextAction(
            stage=Stage.KNOWLEDGE_ANSWER,
            action=Action.ANSWER_KNOWLEDGE,
            reason="KB does not cover this; honest fallback (KB-4)",
            confidence=0.3,
            prompt=answer.fallback,
        )

    def handle_objection(self, text: str) -> NextAction | None:
        """If the turn raises a known objection, respond from the approved playbook + KB
        (Use Case 4); ``None`` if no objection is detected. A high-risk objection (e.g. a
        discount request) flags the call so the close gate holds and escalation can follow."""
        objection = get_objection_playbook().detect(text)
        if objection is None:
            return None
        response = respond_to_objection(objection, retriever=self._retriever)
        if response.high_risk:
            self.state.open_high_risk_objection = True
        risk = " (high-risk)" if response.high_risk else ""
        return NextAction(
            stage=Stage.OBJECTION_HANDLING,
            action=Action.HANDLE_OBJECTION,
            reason=f"detected objection '{objection.key}'{risk}",
            confidence=0.6,
            question_key=objection.key,
            prompt=response.rebuttal,
            kb_sources=response.kb_sources,
        )

    def record_agent_turn(self, text: str) -> None:
        """Record the agent's spoken words for the transcript (the decider chooses the
        action; the words come from the LLM / TTS layer that calls this)."""
        self.state.history.append(("agent", text))
        if self.recorder is not None:
            self.recorder.record_agent(text)

    def end(self, *, outcome: str | None = None, summary: str | None = None) -> None:
        """Finalize the call record, if one is being kept."""
        if self.recorder is not None:
            self.recorder.end(outcome=outcome, summary=summary)
