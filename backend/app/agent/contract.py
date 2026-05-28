"""Brain tool contract + per-turn decision schema (IR2-T1, R1/R7/R9).

The intent-router brain decides each turn by calling tools and composing a reply. This module is
the shared contract between the brain (`agent/brain.py`), the engine (`agent/engine.py`), and the
decision trace (`db.models.Decision`):

- :data:`TOOLS` — the OpenAI function-calling schemas the brain may invoke:
  ``slot_fill`` / ``kb_lookup`` / ``quote_price`` / ``escalate``.
- :class:`RouterAction` — the chosen action vocabulary for the turn (logged as ``selected_action``).
- :class:`BrainDecision` — the structured outcome of one turn (action, reply, slots, leaf,
  confidence, grounding sources, quoted amount) so the trace stays as rich as the old deterministic
  one (R9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.agent.taxonomy import SLOT_FIELDS

# --- tool names (shared so brain + engine can't drift) ---------------------------------

TOOL_SLOT_FILL = "slot_fill"
TOOL_KB_LOOKUP = "kb_lookup"
TOOL_QUOTE_PRICE = "quote_price"
TOOL_ESCALATE = "escalate"

# OpenAI function-calling schemas. The slot_fill field is enumerated from the taxonomy so the brain
# can only ever name a real slot.
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": TOOL_SLOT_FILL,
            "description": (
                "Record a fact the caller has told you (or clearly implied) into the "
                "classification slots. Call once per fact. Children imply parents — filling "
                "subject=chemistry is enough; you don't also need subject_area or category."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(SLOT_FIELDS)},
                    "value": {"type": "string", "description": "The slot value, e.g. 'SAT'."},
                },
                "required": ["field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_KB_LOOKUP,
            "description": (
                "Look up approved knowledge-base content to answer an informational question "
                "(e.g. 'what's the difference between the SAT and ACT?'). You must call this "
                "before stating any policy/program fact; answer only from what it returns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The caller's question."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_QUOTE_PRICE,
            "description": (
                "Get the authoritative price for the caller's need. Only call this once you know "
                "the exact leaf (which test, or which subject). You may ONLY state a price this "
                "tool returns — never invent or estimate one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "leaf": {
                        "type": "string",
                        "description": (
                            "The leaf id, e.g. 'test_prep/SAT' or 'tutoring/science/chemistry'. "
                            "Optional — if omitted, the current slots are used."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_ESCALATE,
            "description": (
                "Hand off to a human specialist when you can't help safely (discount/payment "
                "requests, complaints, repeated confusion, or an explicit request for a person)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
]

TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)


class RouterAction(str, Enum):
    """The action the brain took this turn (logged as Decision.selected_action)."""

    GREET = "greet"          # opening line
    ASK = "ask"              # ask the next disambiguating question (R8)
    ANSWER = "answer"        # answer an informational question from the KB
    QUOTE = "quote"          # state the authoritative price for the confirmed leaf
    ESCALATE = "escalate"    # hand off to a human
    END = "end"              # caller declined / wrap up


@dataclass
class BrainDecision:
    """The structured outcome of one brain turn."""

    action: RouterAction
    utterance: str
    reason: str = ""
    confidence: float = 0.5
    slots: dict[str, str] = field(default_factory=dict)
    leaf: str | None = None
    kb_sources: list[str] = field(default_factory=list)
    quoted_amount: float | None = None  # the price stated this turn, for the mis-quote guard

    def trace(self) -> dict:
        """Flatten to the fields the Decision row / decision trace records (R9)."""
        return {
            "selected_action": self.action.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "slots": dict(self.slots),
            "leaf": self.leaf,
            "kb_sources_used": list(self.kb_sources),
            "quoted_amount": self.quoted_amount,
        }
