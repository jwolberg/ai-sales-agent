"""Router recursive-improvement experiment runner (IR5-T4).

Fires the real classification-accuracy loop end-to-end against **LLM-driven self-play prospects**:

    baseline brain  vs.  one prompt variant
        x the router personas (each with a ground-truth leaf)
        x an LLMProspect that hesitates / withholds like a real caller
    -> run_improvement scores both, decides promotion (accuracy up, no guardrail regression),
       and this script writes the before/after to docs/recursive-improvement-router.md.

The single dimension under test is a **disambiguation sequencing rule**: when the caller is vague,
ask one clarifying question and never resolve/quote a leaf until they name the exact test/subject.

Usage (needs an OpenAI key in the environment / .env):

    python -m app.experiments_router            # full run, writes the doc
    python -m app.experiments_router --dry-run  # print the plan + variant, make no API calls

This is deliberately a script, not a library entry point: it costs real API calls and writes a doc.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.brain import OpenAIBrain
from app.config import get_settings
from app.db.models import Base
from app.simulator.improvement import ImprovementReport, run_improvement
from app.simulator.llm_prospect import LLMProspect
from app.simulator.personas import get_personas

# backend/app/experiments_router.py -> repo root is three levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "recursive-improvement-router.md"

VARIANT_KEY = "disambiguation-rule-v1"

# The one change under test: a sequencing rule appended to the brain's system prompt. It targets the
# ambiguous personas ("college entrance exams", "struggling in school", "science help") where the
# baseline may silently map a broad phrase to a specific leaf instead of asking.
VARIANT_DELTA = (
    "DISAMBIGUATION RULE (follow strictly): The caller's need is only specific enough to act on "
    "once they have named an exact test (SAT, ACT, or PSAT) or an exact subject (algebra, "
    "geometry, chemistry, biology, or physics). Until then — including vague openers like 'college "
    "entrance "
    "exams', 'struggling in school', or 'science help' — ask exactly ONE short clarifying question "
    "that narrows toward the specific test or subject, and do NOT call quote_price or settle on a "
    "leaf yet. Never map a broad phrase to a specific test or subject on the caller's behalf; make "
    "the caller confirm the specific one."
)

_METRIC_COLS = [
    ("classification_accuracy", "Accuracy"),
    ("median_turns_to_classification", "Median turns"),
    ("quote_rate", "Quote"),
    ("mis_quote_rate", "Mis-quote"),
    ("escalation_rate", "Escalation"),
]


def _row(label: str, m: dict) -> str:
    cells = [label] + [str(m.get(key)) for key, _ in _METRIC_COLS]
    return "| " + " | ".join(cells) + " |"


def render_report(
    report: ImprovementReport,
    *,
    agent_model: str,
    prospect_model: str,
    n_personas: int,
    reps: int,
) -> str:
    header = "| Variant | " + " | ".join(name for _, name in _METRIC_COLS) + " |"
    sep = "|" + "---|" * (len(_METRIC_COLS) + 1)
    decision = (
        f"promoted {report.promoted_key}"
        if report.promoted_key
        else "no variant beat the baseline — baseline held"
    )
    lines = [
        "# Recursive improvement — router classification accuracy",
        "",
        f"_Dimension: disambiguation sequencing rule (`{VARIANT_KEY}`). Primary KPI: "
        "Classification Accuracy vs. synthetic ground truth. Guardrails: mis-quote, price-correct. "
        f"Agent brain: `{agent_model}`; adversarial self-play prospect: `{prospect_model}`. "
        f"{n_personas} personas x {reps} reps = {n_personas * reps} self-play calls per variant._",
        "",
        f"**Decision: {decision}.**",
        "",
        "## Results",
        "",
        header,
        sep,
        _row("baseline (no delta)", report.baseline.metrics),
    ]
    for cand in report.candidates:
        lines.append(_row(cand.key, cand.metrics))
    lines += ["", "## Promotion rationale", ""]
    for d in report.decisions:
        verdict = "PROMOTE" if d.promote else "reject"
        lines.append(f"- **{d.candidate_key}** — {verdict}: {'; '.join(d.reasons)}")
    lines += [
        "",
        "## The variant",
        "",
        "Appended to the brain's system prompt (`OpenAIBrain.prompt_delta`):",
        "",
        "> " + VARIANT_DELTA,
        "",
        "## Limitations",
        "",
        "- Metrics come from LLM-driven self-play scored against each persona's ground-truth leaf, "
        "not live human calls — they indicate direction, not production ground truth.",
        "- Self-play is stochastic; a single run is a small sample (one call per persona). Re-run "
        "and widen the persona set before trusting a borderline promotion.",
        "- The promotion rule is accuracy-gated and conservative: it promotes only on a strict "
        "accuracy gain with no mis-quote / price-correctness regression, and never flips anything "
        "live — a human approves the promotion.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan + variant; make no API calls"
    )
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument(
        "--agent-model",
        default=None,
        help="override the model the AGENT brain uses (the thing under test); the self-play "
        "prospect stays on the configured model as a fixed adversary. Default: openai_chat_model.",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=1,
        help="calls per persona. Self-play is stochastic; >1 averages out the noise so the "
        "accuracy estimate (and any promotion) is stable, not a single coin flip.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    base_personas = get_personas().router_personas()
    personas = base_personas * args.reps
    prospect_model = settings.openai_chat_model
    agent_model = args.agent_model or prospect_model
    # Run the agent brain on its own model without weakening the adversary prospect.
    agent_settings = (
        settings
        if agent_model == prospect_model
        else settings.model_copy(update={"openai_chat_model": agent_model})
    )

    print(f"Router improvement loop: baseline vs '{VARIANT_KEY}'")
    print(f"  agent_model={agent_model}  prospect_model={prospect_model}  "
          f"personas={len(base_personas)}x{args.reps}reps={len(personas)} calls  "
          f"max_turns={args.max_turns}")
    print(f"  variant delta:\n    {VARIANT_DELTA}\n")

    if args.dry_run:
        print("[dry-run] no API calls made; no doc written.")
        return 0

    if not settings.openai_enabled:
        print("ERROR: no OpenAI key configured — set OPENAI_API_KEY (the variant only affects the "
              "live OpenAIBrain).")
        return 1

    baseline = OpenAIBrain(agent_settings)
    candidate = OpenAIBrain(agent_settings, prompt_delta=VARIANT_DELTA)

    # Isolated in-memory DB so the experiment's synthetic calls never touch the app database.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        report = run_improvement(
            session,
            baseline_brain=baseline,
            candidate_brains={VARIANT_KEY: candidate},
            personas=personas,
            settings=agent_settings,
            max_turns=args.max_turns,
            prospect_factory=lambda persona: LLMProspect(persona, settings),
        )

    print(report.render())
    REPORT_PATH.write_text(
        render_report(
            report,
            agent_model=agent_model,
            prospect_model=prospect_model,
            n_personas=len(base_personas),
            reps=args.reps,
        )
    )
    print(f"\nWrote {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
