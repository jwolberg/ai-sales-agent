"""Conversation vocabulary: stages, sales actions, and human-layer modifiers.

These three enums are the logging contract described in docs/AGENT_FLOW.md §4:

- ``Stage``     — where the call is on the sales arc (PRD §17, 11 values). Logged
                  as ``Decision.stage``.
- ``Action``    — the sales action chosen this turn (PRD §9.5 DE-1, 10 values).
                  Logged as ``Decision.selected_action``.
- ``Modifier``  — an optional human-layer move used only during ambiguous /
                  non-progressing moments. Does NOT change the active stage.

All three subclass ``str`` so their members serialize directly into the
``Decision`` string columns (``stage.value`` / ``action.value`` are plain text).
"""

from enum import Enum


class Stage(str, Enum):
    """The 11 canonical conversation stages (PRD §17)."""

    GREETING = "greeting"
    CONTEXT_CONFIRMATION = "context_confirmation"
    DISCOVERY = "discovery"
    NEED_DEVELOPMENT = "need_development"
    KNOWLEDGE_ANSWER = "knowledge_answer"
    OBJECTION_HANDLING = "objection_handling"
    FIT_SUMMARY = "fit_summary"
    CLOSE = "close"
    ESCALATION = "escalation"
    WRAP_UP = "wrap_up"
    DISQUALIFIED = "disqualified"


class Action(str, Enum):
    """The 10 next-actions the agent may choose (PRD §9.5 DE-1)."""

    ASK_REQUIRED_DISCOVERY = "ask_required_discovery"
    ASK_LEADING_DISCOVERY = "ask_leading_discovery"
    ANSWER_KNOWLEDGE = "answer_knowledge"
    HANDLE_OBJECTION = "handle_objection"
    SUMMARIZE_FIT = "summarize_fit"
    PIVOT_TOWARD_CLOSE = "pivot_toward_close"
    ATTEMPT_CLOSE = "attempt_close"
    ESCALATE = "escalate"
    DISQUALIFY = "disqualify"
    END_CALL = "end_call"


class Modifier(str, Enum):
    """Optional human-layer moves (docs/AGENT_FLOW.md §4.4), used during ambiguity."""

    RAPPORT = "rapport"
    CLARIFY = "clarify"
    REASSURE = "reassure"
    BANTER = "banter"
    BRIDGE_BACK = "bridge_back"
    TIME_FILLER = "time_filler"
