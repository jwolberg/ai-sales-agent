"""Experiment & variant infrastructure for the improvement loop (P7-T1; PRD §11).

Creates the persisted Experiment + Variant records (storing each rebuttal as the variant's
playbook delta) and runs a variant against a persona — a tagged synthetic self-play call whose
only behavioral change is the price-objection rebuttal (applied via the orchestrator's objection
override). Calls are tagged with `experiment_id`/`variant_id` so metrics/scoring slice by variant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent.extraction import RuleBasedExtractor
from app.config import Settings, get_settings
from app.db.models import Experiment, Variant
from app.experiments.variants import BASELINE, CANDIDATES, PriceVariant
from app.simulator.personas import Persona
from app.simulator.runner import (
    _DEFAULT_SYNTH,
    Prospect,
    SimResult,
    build_simulation_engine,
    make_prospect,
    run_call,
)

_GUARDRAIL_KPIS = ["frustration_rate", "unsupported_claim_rate", "escalation_rate"]


def create_experiment(
    session: Session,
    *,
    name: str,
    baseline: PriceVariant = BASELINE,
    candidates: list[PriceVariant] | None = None,
    dimension: str = "price_objection_rebuttal",
    primary_kpi: str = "objection_recovery_rate",
) -> tuple[Experiment, dict[str, PriceVariant], dict[str, Variant]]:
    """Persist an Experiment + a Variant row per rebuttal. Returns the experiment, the
    PriceVariant specs keyed by key, and the Variant records keyed by the same key."""
    candidates = candidates if candidates is not None else CANDIDATES
    specs = {pv.key: pv for pv in [baseline, *candidates]}

    experiment = Experiment(
        name=name,
        dimension=dimension,
        primary_kpi=primary_kpi,
        guardrail_kpis=_GUARDRAIL_KPIS,
        status="running",
        start_date=datetime.now(timezone.utc),
    )
    session.add(experiment)
    session.flush()

    records: dict[str, Variant] = {}
    for key, pv in specs.items():
        record = Variant(
            experiment_id=experiment.experiment_id,
            name=pv.name,
            description=f"{pv.name} — use when: {pv.when_to_use}",
            playbook_delta=pv.rebuttal,  # the price-objection rebuttal this variant applies
            status="baseline" if key == baseline.key else "candidate",
        )
        session.add(record)
        session.flush()
        records[key] = record
        if key == baseline.key:
            experiment.baseline_variant_id = record.variant_id
    session.commit()
    return experiment, specs, records


def run_variant(
    session: Session,
    experiment: Experiment,
    variant_record: Variant,
    price_variant: PriceVariant,
    persona: Persona,
    *,
    settings: Settings | None = None,
    prospect: Prospect | None = None,
    offline: bool = False,
    max_turns: int = 12,
) -> SimResult:
    """Run one persona against one variant — a tagged self-play call applying the variant's
    price rebuttal. ``offline=True`` uses a no-LLM engine (rule-based extraction, no phrasing)
    for tests; otherwise the full Claude engine + prospect are used."""
    settings = settings or get_settings()
    engine = build_simulation_engine(
        session,
        persona,
        settings,
        experiment_id=experiment.experiment_id,
        variant_id=variant_record.variant_id,
        objection_overrides={"price": price_variant.rebuttal},
        extractor=RuleBasedExtractor() if offline else None,
        synthesize=None if offline else _DEFAULT_SYNTH,
    )
    prospect = prospect or make_prospect(persona, settings)
    return run_call(engine, prospect, persona.key, max_turns=max_turns)
