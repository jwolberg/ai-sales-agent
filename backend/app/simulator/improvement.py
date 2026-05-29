"""Router improvement loop (IR5-T3, R10).

Compares a baseline brain against candidate variants on the classification-accuracy benchmark and
recommends promotion — promote only when a candidate raises Classification Accuracy **without
regressing** the guardrail rates (mis-quote, price-correctness). Promotion stays human-approved:
this produces a decision + report; it does not flip anything live.

A variant is a brain configuration (e.g. an `OpenAIBrain` with a `prompt_delta`). Callers pass the
brains directly, so the loop is testable offline with deterministic stand-ins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.brain import Brain
from app.config import Settings
from app.simulator.benchmark import run_benchmark
from app.simulator.personas import Persona

BASELINE_KEY = "baseline"


@dataclass
class VariantMetrics:
    key: str
    metrics: dict


@dataclass
class PromotionDecision:
    candidate_key: str
    promote: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class ImprovementReport:
    baseline: VariantMetrics
    candidates: list[VariantMetrics]
    decisions: list[PromotionDecision]
    promoted_key: str | None

    def render(self) -> str:
        lines = [
            "# Router improvement report",
            "",
            f"Baseline accuracy: {self.baseline.metrics.get('classification_accuracy')}",
            "",
        ]
        for d in self.decisions:
            cand = next(c for c in self.candidates if c.key == d.candidate_key)
            verdict = "PROMOTE" if d.promote else "keep baseline"
            acc = cand.metrics.get("classification_accuracy")
            why = "; ".join(d.reasons)
            lines.append(f"- {d.candidate_key}: accuracy {acc} — {verdict} ({why})")
        lines += ["", f"Promoted: {self.promoted_key or 'none — baseline holds'}"]
        return "\n".join(lines)


def decide_promotion(baseline: dict, candidate: dict) -> PromotionDecision:
    """Promote iff accuracy strictly improves and no guardrail rate regresses."""
    reasons: list[str] = []
    promote = True

    base_acc = baseline.get("classification_accuracy", 0.0)
    cand_acc = candidate.get("classification_accuracy", 0.0)
    if cand_acc > base_acc:
        reasons.append(f"accuracy {base_acc} -> {cand_acc}")
    else:
        promote = False
        reasons.append(f"no accuracy gain ({base_acc} -> {cand_acc})")

    if candidate.get("mis_quote_rate", 0.0) > baseline.get("mis_quote_rate", 0.0):
        promote = False
        reasons.append("mis-quote rate regressed")
    if candidate.get("price_correct_rate", 1.0) < baseline.get("price_correct_rate", 1.0):
        promote = False
        reasons.append("price-correctness regressed")

    return PromotionDecision(candidate_key="", promote=promote, reasons=reasons)


def run_improvement(
    session,
    *,
    baseline_brain: Brain,
    candidate_brains: dict[str, Brain],
    personas: list[Persona] | None = None,
    settings: Settings | None = None,
    max_turns: int = 8,
) -> ImprovementReport:
    settings = settings or Settings(_env_file=None)

    def bench(brain: Brain) -> dict:
        return run_benchmark(
            session, brain=brain, personas=personas, settings=settings, max_turns=max_turns
        )["metrics"]

    baseline = VariantMetrics(BASELINE_KEY, bench(baseline_brain))
    candidates: list[VariantMetrics] = []
    decisions: list[PromotionDecision] = []
    promoted: str | None = None
    for key, brain in candidate_brains.items():
        m = bench(brain)
        candidates.append(VariantMetrics(key, m))
        decision = decide_promotion(baseline.metrics, m)
        decision.candidate_key = key
        decisions.append(decision)
        if decision.promote and promoted is None:
            promoted = key
    return ImprovementReport(baseline, candidates, decisions, promoted)
