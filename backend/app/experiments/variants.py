"""Price-objection rebuttal variants for the improvement loop (PRD §8).

The baseline is the generic value statement from §8; the candidates are the §8 rebuttal styles.
Each variant defines its rebuttal language plus when to use / not use it, its escalation trigger,
and compliance constraints (PRD §11.2 Step 2). All rebuttals stay within §18 guardrails — never
quote a discount/price or promise a guarantee; defer specifics to a specialist.
"""

from __future__ import annotations

from dataclasses import dataclass

_COMPLIANCE = (
    "Never quote a discount or a specific price, and never promise a guarantee; defer exact "
    "pricing and any concession to a human specialist."
)
_ESCALATE = "If the caller demands a discount or an exact price, hand off to a specialist."
_WHEN_NOT = "Don't repeat it if the caller has already said cost isn't the real issue."


@dataclass(frozen=True)
class PriceVariant:
    """One price-objection rebuttal strategy (PRD §8 / §11.2 Step 2)."""

    key: str
    name: str
    rebuttal: str
    when_to_use: str
    when_not_to_use: str = _WHEN_NOT
    escalation_trigger: str = _ESCALATE
    compliance: str = _COMPLIANCE


# The documented baseline (PRD §8): a generic value statement.
BASELINE = PriceVariant(
    key="baseline",
    name="Generic value statement",
    rebuttal=(
        "I understand price is important. Varsity Tutors offers personalized support from expert "
        "tutors, and many families find the investment worthwhile."
    ),
    when_to_use="Any time the caller raises cost.",
)

# Candidate alternative styles (PRD §8 "Variant Candidates").
CANDIDATES: list[PriceVariant] = [
    PriceVariant(
        key="empathy_first",
        name="Empathy-first value framing",
        rebuttal=(
            "That's completely fair — cost matters, especially when you're not yet sure exactly "
            "what your child needs. My job is to make sure that if you do invest, it's in the "
            "right kind of support. Can I ask what would make this feel worth it to you?"
        ),
        when_to_use="The caller sounds hesitant or anxious about money, not adversarial.",
    ),
    PriceVariant(
        key="outcome_cost",
        name="Outcome-cost framing",
        rebuttal=(
            "Totally hear you. It helps to weigh it against the cost of things staying the same — "
            "a slipping grade or a retake. The goal is targeted help so the time and money go "
            "exactly where they'll move the needle. What outcome would make it clearly worth it?"
        ),
        when_to_use="The caller has a concrete academic goal or deadline.",
    ),
    PriceVariant(
        key="risk_reversal",
        name="Risk-reversal framing",
        rebuttal=(
            "I get it — no one wants to pay for something that might not work. The way we lower "
            "that risk is matching the right tutor and adjusting if it isn't clicking, so you're "
            "not locked into a bad fit. Want me to walk through how the matching works?"
        ),
        when_to_use="The caller's worry is wasting money on something that won't work.",
    ),
    PriceVariant(
        key="comparison",
        name="Comparison-to-alternatives framing",
        rebuttal=(
            "Smart to compare. Cheaper options exist, but the difference usually shows up in the "
            "match — a tutor suited to your child's goals and style, with sessions built around "
            "where they're actually stuck. What matters most to you as you weigh the options?"
        ),
        when_to_use="The caller mentions a cheaper alternative they're considering.",
    ),
    PriceVariant(
        key="diagnostic",
        name="Diagnostic reframing",
        rebuttal=(
            "Fair question. Before we even talk numbers — what would have to be true for tutoring "
            "to feel clearly worth it for your family? Once I understand that, I can point you to "
            "the option that fits, rather than the most expensive one."
        ),
        when_to_use="Early in the call, before the need is well understood.",
    ),
]


def all_variants() -> list[PriceVariant]:
    """Baseline first, then candidates."""
    return [BASELINE, *CANDIDATES]
