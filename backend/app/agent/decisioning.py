"""Dynamic next-question selection (PRD §9.3: DF-3, DF-4; DE-1 discovery actions).

`DiscoveryDecider` is a deterministic `NextActionDecider` that turns the lead's
known/missing fields plus the discovery playbook into the next action:

1. confirm the lead's already-known context once, before probing (LM-3, Use Case 1),
2. fill missing required fields one at a time (DF-1),
3. explore leading questions when required fields are done (DF-2),
4. move to a fit summary once discovery is exhausted.

DF-3 also lists emotional state, buying signals, and objections as inputs; those
depend on detection that lands in Phase 4, so they're accepted via state but not yet
weighted. DF-4 (conversational, non-checklist phrasing) is handled by the LLM phrasing
layer using the persona + the chosen question's prompt — this module picks *what* to
ask, not the exact words.
"""

from __future__ import annotations

from app.agent.discovery import DiscoveryPlaybook, get_discovery_playbook
from app.agent.orchestrator import ConversationState, NextAction
from app.agent.stages import Action, Stage


class DiscoveryDecider:
    """Chooses the next action from lead state and the discovery playbook."""

    def __init__(self, playbook: DiscoveryPlaybook | None = None) -> None:
        self._playbook = playbook or get_discovery_playbook()

    def decide(self, state: ConversationState, user_text: str) -> NextAction:
        collected = state.collected_fields
        known_required = self._playbook.known_required(collected)
        missing_required = self._playbook.missing_required(collected)
        missing_keys = [q.key for q in missing_required]

        # 1. Confirm known context first (LM-3): if we already know required fields and
        #    haven't acknowledged them yet, confirm rather than launch into questions.
        if known_required and not state.context_confirmed:
            question = known_required[0]
            return NextAction(
                stage=Stage.CONTEXT_CONFIRMATION,
                action=Action.ASK_REQUIRED_DISCOVERY,
                reason="confirming known lead context before discovery (LM-3)",
                confidence=0.8,
                missing_fields=missing_keys,
                question_key=question.key,
                prompt=question.confirm_prompt(collected[question.key]),
            )

        # 2. Fill the highest-priority missing required field (DF-1).
        if missing_required:
            question = missing_required[0]
            return NextAction(
                stage=Stage.DISCOVERY,
                action=Action.ASK_REQUIRED_DISCOVERY,
                reason=f"required field '{question.key}' still unknown",
                confidence=0.7,
                missing_fields=missing_keys,
                question_key=question.key,
                prompt=question.prompt,
            )

        # 3. Required complete — explore the next leading question (DF-2).
        next_leading = self._playbook.next_question(collected)
        if next_leading is not None:
            return NextAction(
                stage=Stage.NEED_DEVELOPMENT,
                action=Action.ASK_LEADING_DISCOVERY,
                reason=f"exploring leading info '{next_leading.key}'",
                confidence=0.6,
                question_key=next_leading.key,
                prompt=next_leading.prompt,
            )

        # 4. Nothing left to ask — summarize fit (close criteria detection is P3-T4).
        return NextAction(
            stage=Stage.FIT_SUMMARY,
            action=Action.SUMMARIZE_FIT,
            reason="required and leading discovery complete",
            confidence=0.6,
        )
