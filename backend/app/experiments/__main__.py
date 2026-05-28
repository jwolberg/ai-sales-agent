"""Run + evaluate a price-rebuttal experiment end-to-end and write the report (P7-T2/T3/T4).

This is the "fire-it" step for the recursive-improvement loop: it makes many Claude self-play
calls (every variant against every persona), scores them with the LLM judge, applies the §8
promotion rule, and writes the before/after report.

    python -m app.experiments --name price-rebuttal-v1 \
        --report ../docs/recursive-improvement.md

Use --offline for a no-LLM smoke run (rule-based extraction, no judge) to exercise the wiring
without spending tokens.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.config import get_settings
from app.db.session import SessionLocal, init_db
from app.experiments.engine import create_experiment, run_experiment
from app.experiments.evaluation import evaluate_experiment, render_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run + evaluate a price-rebuttal experiment.")
    parser.add_argument("--name", default="price-rebuttal-v1")
    parser.add_argument("--report", default="../docs/recursive-improvement.md")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument(
        "--offline", action="store_true", help="no-LLM smoke run (no prospect/judge)"
    )
    args = parser.parse_args()

    init_db()
    settings = get_settings()
    with SessionLocal() as session:
        experiment, specs, records = create_experiment(session, name=args.name)
        print(f"experiment {experiment.experiment_id} — {len(specs)} variants")

        run_experiment(
            session, experiment, specs, records,
            settings=settings, offline=args.offline, max_turns=args.max_turns,
        )
        report = evaluate_experiment(
            session, experiment, specs, records, judge=not args.offline, settings=settings
        )

    print(report.decision_line())
    out = Path(args.report)
    out.write_text(render_report(report, specs))
    print(f"report written to {out}")


if __name__ == "__main__":
    main()
