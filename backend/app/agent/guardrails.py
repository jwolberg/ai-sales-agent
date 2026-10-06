"""Guardrails and escalation criteria (PRD §18 guardrails; §9.5 DE-4 escalation).

Three jobs:

1. `detect_escalation` — spot the DE-4 situations where the agent must hand off to a human
   (human request, unauthorized price concession, anger/confusion, legal/safety/privacy,
   payment, or low confidence).
2. `should_stop_selling` — detect a clear refusal so the agent stops pushing (§18).
3. `check_agent_output` — a last-line safety net that flags prohibited agent speech (claiming
   to be human, quoting an unapproved price, or promising a guarantee).

All detection is cue-based and deterministic. These are guardrails, so they err toward
catching too much rather than too little.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Below this confidence, escalate rather than guess (ties KB-4 fallbacks to a human).
DEFAULT_CONFIDENCE_THRESHOLD = 0.35

ESCALATION_MESSAGE = (
    "That's exactly the kind of thing I want to get right for you — let me connect you with "
    "a specialist who can help with that directly."
)

# Escalation trigger codes (DE-4).
HUMAN_REQUEST = "human_request"
PRICE_CONCESSION = "price_concession"
LEGAL_SAFETY_PRIVACY = "legal_safety_privacy"
PAYMENT = "payment_handling"
ANGER_CONFUSION = "anger_or_confusion"
LOW_CONFIDENCE = "low_confidence"

# Output-guardrail violation codes (§18).
CLAIMS_HUMAN = "claims_to_be_human"
QUOTES_PRICE = "quotes_unapproved_price"
PROMISES_GUARANTEE = "promises_guarantee"
# Intent-router (IR1-T2): the agent stated a price that doesn't match an authorized price-table
# record for the turn. Unlike QUOTES_PRICE (advisory), this is a HARD violation — a wrong number
# is exactly the guardrail we promise never to break (R6).
MIS_QUOTE = "states_off_table_price"

# Cue lists, checked in this priority order.
_ESCALATION_CUES: list[tuple[str, tuple[str, ...]]] = [
    (
        HUMAN_REQUEST,
        (
            "a human",
            "real person",
            "speak to someone",
            "talk to a person",
            "representative",
            "speak to a manager",
            "human being",
            "customer service",
        ),
    ),
    (
        LEGAL_SAFETY_PRIVACY,
        (
            "lawyer",
            "sue",
            "lawsuit",
            "gdpr",
            "ccpa",
            "privacy",
            "delete my data",
            "report you",
            "legal action",
            "unsafe",
            "safety concern",
        ),
    ),
    # Card-data handling ALWAYS escalates — we never take a card number in-call (PCI; PAY3-T3).
    # Pay-now / invoice *intent* is handled separately below so it can route to the payment flow.
    (
        PAYMENT,
        (
            "credit card",
            "card number",
            "charge my card",
            "debit card",
            "bank account",
            "routing number",
            "billing information",
        ),
    ),
    (
        PRICE_CONCESSION,
        (
            "discount",
            "coupon",
            "promo code",
            "lower the price",
            "price match",
            "waive the fee",
        ),
    ),
    (
        ANGER_CONFUSION,
        (
            "this is ridiculous",
            "i'm frustrated",
            "so frustrated",
            "i'm angry",
            "wasting my time",
            "i'm confused",
            "i don't understand",
            "makes no sense",
            "you're not listening",
            # Hostility / abuse. STT often masks profanity (e.g. "shut the **** up"), so match the
            # surrounding phrase and unmasked insults rather than relying on the swear word itself.
            "shut up",
            "shut the",
            "shut your",
            "stop talking",
            "be quiet",
            "you suck",
            "you're useless",
            "you're stupid",
            "idiot",
            "moron",
            "i hate",
            "fuck",
            "shit",
            "asshole",
            "bullshit",
            "piss off",
        ),
    ),
]

_REFUSAL_CUES = (
    "not interested",
    "stop calling",
    "stop contacting",
    "leave me alone",
    "no thank you",
    "no thanks",
    "please stop",
    "remove me",
    "don't call",
)

# Pay/invoice *intent* (PAY3-T3) — distinct from card-data handling above. When payments are
# enabled these route to the payment flow; when disabled they escalate (unchanged behavior).
_PAY_NOW_CUES = (
    "pay now",
    "pay for it",
    "make a payment",
    "i want to pay",
    "i'd like to pay",
    "ready to pay",
    "can i pay",
    "let me pay",
    "take my payment",
    "i'll pay",
)
_INVOICE_CUES = ("invoice", "send me a bill", "send a bill", "bill me")


def detect_payment_intent(text: str) -> str | None:
    """Classify a caller's pay/invoice intent: 'invoice', 'link' (pay-now), or None (PAY3-T3).

    Card-data phrases ('card number', etc.) are deliberately NOT here — those always escalate via
    :func:`detect_escalation`, which callers run first."""
    lowered = text.lower()
    if any(cue in lowered for cue in _INVOICE_CUES):
        return "invoice"
    if any(cue in lowered for cue in _PAY_NOW_CUES):
        return "link"
    return None


@dataclass(frozen=True)
class EscalationTrigger:
    """Why the agent should escalate (DE-4)."""

    code: str
    reason: str


def detect_escalation(
    text: str,
    *,
    confidence: float | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    payments_enabled: bool = False,
) -> EscalationTrigger | None:
    """Return the first DE-4 escalation trigger for this turn, or ``None``.

    Card-data handling always escalates. Pay/invoice *intent* escalates only when payments are
    disabled (PAY3-T3); when enabled the engine routes it to the payment flow instead, so it isn't
    treated as an escalation here."""
    lowered = text.lower()
    for code, cues in _ESCALATION_CUES:
        if any(cue in lowered for cue in cues):
            return EscalationTrigger(code=code, reason=f"DE-4 trigger: {code}")
    if not payments_enabled and detect_payment_intent(lowered) is not None:
        return EscalationTrigger(code=PAYMENT, reason=f"DE-4 trigger: {PAYMENT}")
    if confidence is not None and confidence < confidence_threshold:
        return EscalationTrigger(
            code=LOW_CONFIDENCE,
            reason=f"confidence {confidence:.2f} below threshold {confidence_threshold:.2f}",
        )
    return None


def should_stop_selling(text: str) -> bool:
    """True if the caller has clearly refused — the agent must not keep pushing (§18)."""
    lowered = text.lower()
    return any(cue in lowered for cue in _REFUSAL_CUES)


_PRICE_RE = re.compile(r"\$\s?\d|\b\d+\s?(?:dollars|usd)\b|\bper (?:hour|session|month)\b")
_HUMAN_CLAIM_RE = re.compile(
    r"\b(i am|i'm) (?:a )?(?:real )?(?:human|person)\b|\bnot (?:a|an) (?:bot|ai|robot)\b"
)
_GUARANTEE_RE = re.compile(r"\bguarantee[ds]?\b")


def check_agent_output(text: str) -> list[str]:
    """Flag prohibited content in proposed agent speech (§18). Empty list = clean."""
    lowered = text.lower()
    violations: list[str] = []
    if _HUMAN_CLAIM_RE.search(lowered):
        violations.append(CLAIMS_HUMAN)
    if _PRICE_RE.search(lowered):
        violations.append(QUOTES_PRICE)
    if _GUARANTEE_RE.search(lowered):
        violations.append(PROMISES_GUARANTEE)
    return violations


# A dollar amount in agent speech: "$85", "$85.50", "85 dollars", "85 usd".
_PRICE_AMOUNT_RE = re.compile(
    r"\$\s?(\d+(?:\.\d{1,2})?)|\b(\d+(?:\.\d{1,2})?)\s?(?:dollars|usd)\b", re.IGNORECASE
)


def extract_price_amounts(text: str) -> list[float]:
    """Pull every explicit dollar amount out of agent speech (for the mis-quote guard)."""
    amounts: list[float] = []
    for m in _PRICE_AMOUNT_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw is not None:
            amounts.append(float(raw))
    return amounts


def check_mis_quote(text: str, *, allowed_amount: float | None) -> bool:
    """True if the agent stated a price it isn't authorized to (IR1-T2, R6).

    ``allowed_amount`` is the authoritative price-table figure for the turn's confirmed leaf, or
    ``None`` when no leaf/price is authorized yet. Any stated dollar amount with no authorization,
    or any amount that doesn't match the authorized figure, is a hard violation. A reply with no
    dollar amount is always clean (the agent may *talk about* price without quoting one).
    """
    amounts = extract_price_amounts(text)
    if not amounts:
        return False
    if allowed_amount is None:
        return True
    return any(abs(a - allowed_amount) > 0.001 for a in amounts)
