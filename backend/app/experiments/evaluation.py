"""Evaluate an experiment and decide promotion (P7-T4; PRD §8, §11.2).

Aggregates each variant's scored calls into KPI rates, applies the §8 promotion rule (improve the
primary KPI without regressing the guardrails), promotes the best passing candidate (or none),
retires the rest, and writes a before/after report. The aggregation and the promotion rule are
pure functions so they can be unit-tested without any LLM or DB; only `score_variant_calls` and
`evaluate_experiment` touch the database / judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Call, Experiment, Variant
from app.simulator.personas import get_personas
from app.simulator.scoring import CallScore, score_call

# How much the prospect-frustration rate may rise vs. baseline before a variant is disqualified.
# A winning rebuttal must not make prospects noticeably more frustrated (§8 "doesn't increase
# escalations / frustration"). 0.0 = no tolerance for an increase.
FRUSTRATION_TOLERANCE = 0.0


def _rate(flags: list[bool]) -> float | None:
    return (sum(1 for f in flags if f) / len(flags)) if flags else None


@dataclass
class VariantMetrics:
    """KPI rates for one variant, aggregated across its scored calls."""

    variant_key: str
    n_calls: int
    n_objection_calls: int
    objection_recovery_rate: float | None  # primary KPI (over calls where a price objection arose)
    close_attempt_rate: float | None
    escalation_rate: float | None
    appropriate_rate: float | None
    frustration_rate: float | None  # judge-derived; None when the judge was skipped
    unsupported_claim_rate: float | None  # judge-derived

    def as_dict(self) -> dict:
        return {
            "variant_key": self.variant_key,
            "n_calls": self.n_calls,
            "n_objection_calls": self.n_objection_calls,
            "objection_recovery_rate": self.objection_recovery_rate,
            "close_attempt_rate": self.close_attempt_rate,
            "escalation_rate": self.escalation_rate,
            "appropriate_rate": self.appropriate_rate,
            "frustration_rate": self.frustration_rate,
            "unsupported_claim_rate": self.unsupported_claim_rate,
        }


def aggregate(variant_key: str, scores: list[CallScore]) -> VariantMetrics:
    """Roll a variant's per-call scores into KPI rates (pure)."""
    objection_calls = [s for s in scores if s.objection_raised]
    judged = [s for s in scores if s.judge is not None]
    return VariantMetrics(
        variant_key=variant_key,
        n_calls=len(scores),
        n_objection_calls=len(objection_calls),
        objection_recovery_rate=_rate([s.objection_recovered for s in objection_calls]),
        close_attempt_rate=_rate([s.close_attempted for s in scores]),
        escalation_rate=_rate([s.escalated for s in scores]),
        appropriate_rate=_rate([s.appropriate_for_persona for s in scores]),
        frustration_rate=_rate([s.judge.frustration for s in judged]),
        unsupported_claim_rate=_rate([s.judge.unsupported_claim for s in judged]),
    )


@dataclass
class PromotionDecision:
    """Whether a candidate beats the baseline under the §8 promotion rule."""

    variant_key: str
    promote: bool
    reasons: list[str]


def decide_promotion(
    baseline: VariantMetrics,
    variant: VariantMetrics,
    *,
    frustration_tolerance: float = FRUSTRATION_TOLERANCE,
) -> PromotionDecision:
    """Apply the §8 rule: promote a candidate only if it improves the primary KPI
    (objection-recovery) without increasing prospect frustration or unsupported claims. Missing
    (None) rates are treated as 0.0 — the conservative reading, so an unmeasured guardrail never
    silently passes a variant on its own."""
    b_recovery = baseline.objection_recovery_rate or 0.0
    v_recovery = variant.objection_recovery_rate or 0.0
    b_frustration = baseline.frustration_rate or 0.0
    v_frustration = variant.frustration_rate or 0.0
    b_unsupported = baseline.unsupported_claim_rate or 0.0
    v_unsupported = variant.unsupported_claim_rate or 0.0

    improves = v_recovery > b_recovery
    frustration_ok = v_frustration <= b_frustration + frustration_tolerance
    claims_ok = v_unsupported <= b_unsupported

    reasons = [
        f"objection-recovery {v_recovery:.0%} vs baseline {b_recovery:.0%} "
        f"({'+' if improves else 'no'} improvement)",
        f"frustration {v_frustration:.0%} vs baseline {b_frustration:.0%} "
        f"({'ok' if frustration_ok else 'REGRESSED'})",
        f"unsupported-claims {v_unsupported:.0%} vs baseline {b_unsupported:.0%} "
        f"({'ok' if claims_ok else 'REGRESSED'})",
    ]
    return PromotionDecision(
        variant_key=variant.variant_key,
        promote=improves and frustration_ok and claims_ok,
        reasons=reasons,
    )


def score_variant_calls(
    session: Session,
    experiment_id: str,
    variant_id: str,
    *,
    judge: bool = True,
    judge_client: object | None = None,
    settings: Settings | None = None,
) -> list[CallScore]:
    """Score every recorded call tagged with this experiment+variant. The persona is recovered
    from the call's channel (``sim:<persona_key>``)."""
    lib = get_personas()
    calls = session.scalars(
        select(Call).where(
            Call.experiment_id == experiment_id, Call.variant_id == variant_id
        )
    ).all()
    scores: list[CallScore] = []
    for call in calls:
        persona_key = (call.channel or "").removeprefix("sim:")
        scores.append(
            score_call(
                session,
                call.call_id,
                lib.get(persona_key),
                judge=judge,
                judge_client=judge_client,
                settings=settings,
            )
        )
    return scores


@dataclass
class ExperimentReport:
    experiment_id: str
    name: str
    baseline: VariantMetrics
    variants: dict[str, VariantMetrics]  # candidate_key -> metrics
    decisions: dict[str, PromotionDecision]  # candidate_key -> decision
    promoted_key: str | None

    def decision_line(self) -> str:
        if self.promoted_key is None:
            return "No variant beat the baseline — baseline held."
        m = self.variants[self.promoted_key]
        return (
            f"Promoted `{self.promoted_key}` — objection-recovery "
            f"{_fmt(m.objection_recovery_rate)} vs baseline "
            f"{_fmt(self.baseline.objection_recovery_rate)}."
        )


def evaluate_experiment(
    session: Session,
    experiment: Experiment,
    specs: dict,
    records: dict[str, Variant],
    *,
    judge: bool = True,
    judge_client: object | None = None,
    settings: Settings | None = None,
    frustration_tolerance: float = FRUSTRATION_TOLERANCE,
) -> ExperimentReport:
    """Score every variant, decide promotion vs. the baseline, promote the best passing candidate
    (highest objection-recovery), retire the rest, and mark the experiment completed."""
    baseline_key = next(k for k, r in records.items() if r.status == "baseline")

    def metrics_for(key: str) -> VariantMetrics:
        scores = score_variant_calls(
            session,
            experiment.experiment_id,
            records[key].variant_id,
            judge=judge,
            judge_client=judge_client,
            settings=settings,
        )
        return aggregate(key, scores)

    baseline_metrics = metrics_for(baseline_key)
    variant_metrics: dict[str, VariantMetrics] = {}
    decisions: dict[str, PromotionDecision] = {}
    for key in records:
        if key == baseline_key:
            continue
        m = metrics_for(key)
        variant_metrics[key] = m
        decisions[key] = decide_promotion(
            baseline_metrics, m, frustration_tolerance=frustration_tolerance
        )

    # Promote the passing candidate with the best primary KPI; retire the rest.
    passing = [k for k, d in decisions.items() if d.promote]
    promoted_key = (
        max(passing, key=lambda k: variant_metrics[k].objection_recovery_rate or 0.0)
        if passing
        else None
    )
    now = datetime.now(timezone.utc)
    for key in variant_metrics:
        record = records[key]
        if key == promoted_key:
            record.status = "promoted"
            record.promoted_at = now
        else:
            record.status = "retired"
            record.retired_at = now

    experiment.status = "completed"
    experiment.end_date = now
    experiment.decision = (
        f"promoted:{promoted_key}" if promoted_key else "no_promotion:baseline_held"
    )
    session.commit()

    return ExperimentReport(
        experiment_id=experiment.experiment_id,
        name=experiment.name,
        baseline=baseline_metrics,
        variants=variant_metrics,
        decisions=decisions,
        promoted_key=promoted_key,
    )


def _fmt(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


def render_report(report: ExperimentReport, specs: dict) -> str:
    """Render a human-readable before/after Markdown report (PRD §11.2 step 6)."""
    baseline_name = specs[report.baseline.variant_key].name
    lines = [
        f"# Recursive improvement — {report.name}",
        "",
        f"_Experiment `{report.experiment_id}`. Dimension: price-objection rebuttal. "
        f"Primary KPI: objection-recovery rate. Guardrails: frustration, unsupported claims._",
        "",
        f"**Decision: {report.decision_line()}**",
        "",
        "## Results by variant",
        "",
        "| Variant | Calls | Objection calls | Recovery | Frustration | Unsupported | Appropriate |",  # noqa: E501
        "|---|---|---|---|---|---|---|",
    ]

    def row(m: VariantMetrics, label: str) -> str:
        return (
            f"| {label} | {m.n_calls} | {m.n_objection_calls} | {_fmt(m.objection_recovery_rate)} "
            f"| {_fmt(m.frustration_rate)} | {_fmt(m.unsupported_claim_rate)} "
            f"| {_fmt(m.appropriate_rate)} |"
        )

    lines.append(row(report.baseline, f"{baseline_name} (baseline)"))
    for key, m in report.variants.items():
        tag = " ✅ promoted" if key == report.promoted_key else ""
        lines.append(row(m, f"{specs[key].name}{tag}"))

    lines += ["", "## Promotion rationale", ""]
    for key, decision in report.decisions.items():
        verdict = "PROMOTE" if decision.promote else "reject"
        lines.append(f"- **{specs[key].name}** — {verdict}")
        for reason in decision.reasons:
            lines.append(f"  - {reason}")

    lines += [
        "",
        "## Limitations",
        "",
        "- Metrics come from synthetic self-play scored by an LLM judge, not live calls — they",
        "  indicate direction, not production ground truth.",
        "- Recovery rate is measured only over calls where the prospect actually raised a price",
        "  objection; small samples per persona mean a real rollout should widen the prospect set.",
        "- The promotion rule treats unmeasured guardrails conservatively (as 0%); always confirm",
        "  the judge ran before trusting a promotion.",
        "",
    ]
    return "\n".join(lines)
