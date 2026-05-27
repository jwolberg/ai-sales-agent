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

from app.agent.persona import build_greeting_cue, build_system_prompt
from app.agent.recorder import CallRecorder
from app.agent.stages import Action, Modifier, Stage
from app.config import Settings, get_settings


@dataclass
class NextAction:
    """One decision turn. Field-for-field the persistable shape of ``Decision`` (DE-2)."""

    stage: Stage
    action: Action
    modifier: Modifier | None = None
    reason: str | None = None
    confidence: float | None = None
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class ConversationState:
    """Mutable per-call state the decider reads to choose the next action.

    Lead context, collected fields, and detected signals are populated by later
    tickets (P3 memory/discovery, P4 KB/objections); for now the stub only needs the
    stage and the running user-turn count.
    """

    stage: Stage = Stage.GREETING
    user_turns: int = 0
    history: list[tuple[str, str]] = field(default_factory=list)  # (speaker, text)
    collected_fields: dict[str, str] = field(default_factory=dict)


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
    ) -> None:
        self.settings = settings or get_settings()
        self.decider = decider or StubDecider()
        # Optional: when set, prospect/agent turns are persisted as the call's
        # transcript (P2-T4). Left None for pure, DB-free decision testing.
        self.recorder = recorder
        # Built once and reused every turn — this is what keeps the persona consistent.
        self.system_prompt = build_system_prompt(self.settings)
        self.state = ConversationState()

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
        return action

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
