"""The intent-router brain (IR2-T2, R1/R2/R3/R5/R8).

The brain owns each turn: it reads the running transcript + known lead fields + current slot state
and decides what to say, what to ask next, when to answer from the KB, and when to quote a price —
emitting a :class:`~app.agent.contract.BrainDecision`.

Two implementations behind one :class:`Brain` protocol:

- :class:`OpenAIBrain` — a bounded tool-calling loop against OpenAI (the live path). The model
  calls ``slot_fill`` / ``kb_lookup`` / ``quote_price`` / ``escalate``; the engine-side executors
  enforce the rails (quoting only fires when the slots resolve to a real leaf — R5b/R6).
- :class:`RuleBrain` — a deterministic, no-network brain used for tests and offline self-play, so
  the suite and the simulator run without an OpenAI key.

:func:`get_brain` returns the live brain when an OpenAI key is configured, else the rule brain.
"""

from __future__ import annotations

from typing import Protocol

from app.agent import taxonomy as tx
from app.agent.contract import (
    TOOL_ESCALATE,
    TOOL_KB_LOOKUP,
    TOOL_QUOTE_PRICE,
    TOOL_SEND_PAYMENT_LINK,
    TOOL_SLOT_FILL,
    BrainDecision,
    PaymentRequest,
    RouterAction,
    tools_for,
)
from app.agent.guardrails import ESCALATION_MESSAGE, detect_escalation, detect_payment_intent
from app.agent.knowledge import FALLBACK_MESSAGE, answer_question
from app.agent.pricing import quote_price
from app.config import Settings, get_settings

History = list[tuple[str, str]]  # (speaker, text); speaker in {"agent","prospect"}

MAX_TOOL_ROUNDS = 5


# --- KB helper (both brains use it; IR-3 swaps the retriever underneath) ----------------


def _kb_answer(query: str) -> tuple[str, list[str], bool]:
    """Return (grounded_snippets_or_empty, source_ids, grounded?) for a KB query."""
    ans = answer_question(query)
    if ans.grounded and ans.snippets:
        return ("\n\n".join(ans.snippets), list(ans.sources), True)
    return ("", [], False)


# --- protocol + factory -----------------------------------------------------------------


class Brain(Protocol):
    def decide(
        self, *, history: History, lead_fields: dict | None = None, slots: dict | None = None
    ) -> BrainDecision: ...


def get_brain(settings: Settings | None = None) -> Brain:
    settings = settings or get_settings()
    if settings.openai_enabled:
        return OpenAIBrain(settings)
    return RuleBrain(settings)


# --- shared question phrasing -----------------------------------------------------------

_QUESTIONS = {
    "category": (
        "Are you looking for test prep — like the SAT or ACT — or tutoring in a specific subject?"
    ),
    "test": "Which test are you preparing for — the SAT, the ACT, or the PSAT?",
    "subject_area": "Got it. Is that a math subject or a science subject?",
    "subject_math": "Which one — algebra or geometry?",
    "subject_science": "Which science is it — chemistry, biology, or physics?",
}


def _question_for(slots: dict) -> str:
    field = tx.next_unfilled(slots)
    if field == "subject":
        area = tx.canonicalize(slots).get("subject_area")
        return _QUESTIONS["subject_science" if area == "science" else "subject_math"]
    return _QUESTIONS.get(field or "category", _QUESTIONS["category"])


def _quote_utterance(leaf: tx.Leaf, spoken: str) -> str:
    return (
        f"Got it — {leaf.label}. {spoken} "
        "Would you like me to connect you with a specialist to get started?"
    )


# --- deterministic rule brain (offline / tests) -----------------------------------------

# Keyword cues for slot extraction without an LLM. Order matters only within a field.
_CATEGORY_CUES = {
    "tutoring": ("tutor", "tutoring", "help with", "struggling with", "homework"),
    "test_prep": ("test prep", "prep for", "exam", "standardized test"),
}


class RuleBrain:
    """A deterministic brain: keyword slot-fill + next-question, no network."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def decide(
        self, *, history: History, lead_fields: dict | None = None, slots: dict | None = None
    ) -> BrainDecision:
        slots = dict(slots or {})
        slots.update({k: v for k, v in (lead_fields or {}).items() if k in tx.SLOT_FIELDS})
        last_user = next((t for spk, t in reversed(history) if spk == "prospect"), "")

        # Escalation cues short-circuit everything (DE-4). With payments on, pay-intent is NOT an
        # escalation (handled below); card-data still escalates (PAY3-T3).
        trigger = detect_escalation(last_user, payments_enabled=self.settings.payments_enabled)
        if trigger is not None:
            return BrainDecision(
                action=RouterAction.ESCALATE,
                utterance=ESCALATION_MESSAGE,
                reason=trigger.reason,
                confidence=0.9,
                slots=slots,
            )

        # Fold any slot facts the caller just volunteered.
        slots.update(self._extract_slots(last_user))

        leaf = tx.resolve_leaf(slots)
        if leaf is not None:
            # Caller wants to pay/be invoiced for a confirmed need -> hand the engine a payment
            # request (it creates + texts the hosted link; the brain stays IO-free). PAY3-T2.
            kind = detect_payment_intent(last_user) if self.settings.payments_enabled else None
            if kind is not None:
                return BrainDecision(
                    action=RouterAction.PAY,
                    utterance="",  # the engine composes the spoken confirmation after sending
                    reason=f"caller asked to pay ({kind}) for leaf {leaf.id}",
                    confidence=1.0,
                    slots=slots,
                    leaf=leaf.id,
                    payment_request=PaymentRequest(kind=kind),
                )
            rec = quote_price(leaf)
            if rec is not None:
                return BrainDecision(
                    action=RouterAction.QUOTE,
                    utterance=_quote_utterance(leaf, rec.spoken()),
                    reason=f"leaf {leaf.id} resolved; quoted from price table",
                    confidence=1.0,
                    slots=slots,
                    leaf=leaf.id,
                    quoted_amount=rec.amount,
                )
            # leaf with no price -> honest fallback (R6b)
            return BrainDecision(
                action=RouterAction.ANSWER,
                utterance=FALLBACK_MESSAGE,
                reason=f"leaf {leaf.id} has no priced record; honest fallback",
                confidence=0.6,
                slots=slots,
                leaf=leaf.id,
            )

        # Otherwise ask the next disambiguating question (R8).
        return BrainDecision(
            action=RouterAction.ASK,
            utterance=_question_for(slots),
            reason=f"disambiguate: next slot '{tx.next_unfilled(slots)}'",
            confidence=0.5,
            slots=slots,
        )

    @staticmethod
    def _extract_slots(text: str) -> dict:
        """Best-effort keyword extraction of taxonomy slots from one utterance."""
        lowered = text.lower()
        found: dict[str, str] = {}
        # subjects / tests first (most specific; they imply parents)
        for test in tx.TESTS:
            if test.lower() in lowered:
                found["test"] = test
        for subjects in tx.SUBJECTS.values():
            for subject in subjects:
                if subject in lowered:
                    found["subject"] = subject
        if "subject" not in found:
            for area in tx.SUBJECT_AREAS:
                if area in lowered:
                    found["subject_area"] = area
        if "test" not in found and "subject" not in found and "subject_area" not in found:
            for category, cues in _CATEGORY_CUES.items():
                if any(cue in lowered for cue in cues):
                    found["category"] = category
                    break
        return found


# --- live OpenAI brain ------------------------------------------------------------------


class OpenAIBrain:
    """A bounded tool-calling loop against OpenAI (the live conversation path)."""

    def __init__(
        self, settings: Settings | None = None, *, client=None, prompt_delta: str = ""
    ) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.openai_chat_model
        self._client = client  # injectable for tests
        self.prompt_delta = prompt_delta  # improvement-loop variant override (IR5-T3)

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def _system_prompt(self, slots: dict, lead_fields: dict | None) -> str:
        s = self.settings
        known = {**(lead_fields or {}), **slots}
        known_line = (
            f"Already known: {known}." if known else "Nothing is known about the caller yet."
        )
        return (
            f"You are {s.agent_name}, a warm, concise voice assistant for {s.company_name}, "
            "which offers live tutoring and standardized-test prep.\n"
            "Your ONE job on this call is to figure out what the caller needs, then tell them the "
            "price. There are two paths:\n"
            "  - Test prep: the SAT, ACT, or PSAT.\n"
            "  - Tutoring: math (algebra, geometry) or science (chemistry, biology, physics).\n\n"
            "Rules:\n"
            "- Sound human and natural; respond to what they actually say. Never interrogate.\n"
            "- As you learn facts, call slot_fill (children imply parents).\n"
            "- Ask only the single most useful next question to narrow things down. If the caller "
            "is vague (e.g. 'struggling in school'), ask one clarifying question — don't guess.\n"
            "- Only once you know the exact test or subject, call quote_price, then state the "
            "price it returns. You may ONLY state a price quote_price returns — never invent, "
            "estimate, or negotiate a price or discount.\n"
            "- For factual questions (e.g. SAT vs ACT), call kb_lookup and answer ONLY from what "
            "it returns; if it returns nothing, offer to connect them with a specialist.\n"
            "- Never claim to be human; if asked, say you're an AI assistant for the company.\n"
            "- Keep replies short and spoken-friendly (1-3 sentences).\n"
            + (
                "- If, after you've quoted, the caller wants to pay or be invoiced, call "
                "send_payment_link (kind='link' to pay now, 'invoice' to be invoiced) — we text a "
                "secure hosted link. NEVER take a card number over the phone; if they try to read "
                "one out, call escalate instead.\n"
                if s.payments_enabled
                else ""
            )
            + "\n"
            f"{known_line}"
            + (f"\n\n{self.prompt_delta}" if self.prompt_delta else "")
        )

    def decide(
        self, *, history: History, lead_fields: dict | None = None, slots: dict | None = None
    ) -> BrainDecision:
        working = dict(slots or {})
        working.update({k: v for k, v in (lead_fields or {}).items() if k in tx.SLOT_FIELDS})

        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt(working, lead_fields)}
        ]
        for speaker, text in history:
            messages.append(
                {"role": "assistant" if speaker == "agent" else "user", "content": text}
            )

        kb_sources: list[str] = []
        quoted_amount: float | None = None
        escalate_reason: str | None = None
        payment_request: PaymentRequest | None = None
        used_kb = False
        used_quote = False

        tools = tools_for(self.settings.payments_enabled)
        utterance = ""
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=tools, tool_choice="auto"
            )
            msg = resp.choices[0].message
            if not getattr(msg, "tool_calls", None):
                utterance = (msg.content or "").strip()
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                name = tc.function.name
                args = _parse_args(tc.function.arguments)
                result = "ok"
                if name == TOOL_SLOT_FILL and "field" in args and "value" in args:
                    working[args["field"]] = args["value"]
                elif name == TOOL_KB_LOOKUP:
                    used_kb = True
                    text, sources, grounded = _kb_answer(args.get("query", ""))
                    kb_sources += sources
                    result = text if grounded else "NO_APPROVED_CONTENT"
                elif name == TOOL_QUOTE_PRICE:
                    leaf = tx.resolve_leaf(working)
                    if args.get("leaf") and tx.is_valid_leaf_id(args["leaf"]):
                        leaf = tx.leaf_from_id(args["leaf"])
                    if leaf is None:
                        result = "NOT_READY: ask which test or subject first."
                    else:
                        rec = quote_price(leaf)
                        if rec is None:
                            result = "NO_PRICE: no approved price; offer a specialist."
                        else:
                            quoted_amount = rec.amount
                            used_quote = True
                            result = f"{rec.spoken()} (leaf {leaf.id})"
                elif name == TOOL_SEND_PAYMENT_LINK:
                    # Gate on a confirmed leaf (same bar as quoting); the engine creates + texts the
                    # link and enforces the approved-price gate. The brain only records the request.
                    leaf = tx.resolve_leaf(working)
                    if leaf is None:
                        result = "NOT_READY: confirm what they need and quote the price first."
                    else:
                        kind = args.get("kind", "link")
                        kind = kind if kind in ("link", "invoice") else "link"
                        payment_request = PaymentRequest(kind=kind, phone=args.get("phone"))
                        result = "OK: a secure payment link will be texted to the caller."
                elif name == TOOL_ESCALATE:
                    escalate_reason = args.get("reason", "escalation requested")
                    result = ESCALATION_MESSAGE
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        leaf = tx.resolve_leaf(working)
        action = self._infer_action(
            escalate=escalate_reason is not None,
            pay=payment_request is not None,
            used_quote=used_quote,
            used_kb=used_kb,
            leaf=leaf,
        )
        if not utterance and action is not RouterAction.PAY:
            # Model exhausted tool rounds without composing a reply: fall back to a question.
            # (PAY needs no model utterance — the engine composes the confirmation after sending.)
            utterance = _question_for(working)
            action = RouterAction.ASK
        return BrainDecision(
            action=action,
            utterance=utterance,
            reason=escalate_reason or f"action={action.value}; leaf={leaf.id if leaf else None}",
            confidence=1.0 if leaf is not None else 0.5,
            slots=working,
            leaf=leaf.id if leaf is not None else None,
            kb_sources=kb_sources,
            quoted_amount=quoted_amount,
            payment_request=payment_request,
        )

    @staticmethod
    def _infer_action(
        *, escalate: bool, pay: bool, used_quote: bool, used_kb: bool, leaf
    ) -> RouterAction:
        if escalate:
            return RouterAction.ESCALATE
        if pay and leaf is not None:
            return RouterAction.PAY
        if used_quote and leaf is not None:
            return RouterAction.QUOTE
        if used_kb:
            return RouterAction.ANSWER
        return RouterAction.ASK


def _parse_args(raw: str) -> dict:
    import json

    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}
