"""Tests for experiment & variant infrastructure (P7-T1/T2/T3/T4; PRD §8, §11)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.orchestrator import Orchestrator
from app.agent.recorder import CallRecorder
from app.config import Settings
from app.db.models import Base, Call, Variant
from app.experiments.engine import create_experiment, run_experiment, run_variant
from app.experiments.evaluation import (
    aggregate,
    decide_promotion,
    evaluate_experiment,
    render_report,
)
from app.experiments.variants import BASELINE, CANDIDATES, all_variants
from app.kpis import events as kpi
from app.simulator.personas import get_personas
from app.simulator.scoring import CallScore, JudgeScores


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_variant_catalog_has_baseline_plus_candidates():
    assert BASELINE.key == "baseline"
    assert len(CANDIDATES) >= 2  # PRD wants >= 2 variants tested
    keys = {v.key for v in all_variants()}
    assert {"empathy_first", "outcome_cost", "diagnostic"} <= keys
    # All rebuttals avoid quoting a discount/price (guardrail).
    assert all("discount" not in v.rebuttal.lower() for v in all_variants())


def test_objection_override_seam():
    orch = Orchestrator(
        settings=Settings(_env_file=None),
        objection_overrides={"price": "VARIANT REBUTTAL"},
    )
    action = orch.handle_objection("honestly it's too expensive")
    assert action.question_key == "price"
    assert action.prompt == "VARIANT REBUTTAL"  # override applied


def test_create_experiment_persists_records(session):
    exp, specs, records = create_experiment(session, name="price-rebuttal-v1")
    assert exp.primary_kpi == "objection_recovery_rate"
    assert exp.baseline_variant_id == records["baseline"].variant_id

    rows = session.scalars(select(Variant).where(Variant.experiment_id == exp.experiment_id)).all()
    assert len(rows) == 1 + len(CANDIDATES)
    assert records["empathy_first"].playbook_delta == specs["empathy_first"].rebuttal
    assert records["baseline"].status == "baseline"


def test_run_variant_offline_applies_override_and_tags_call(session):
    exp, specs, records = create_experiment(session, name="exp")
    persona = get_personas().get("price_sensitive_parent")

    def prospect(_agent_line):
        return "honestly this is too expensive"

    result = run_variant(
        session, exp, records["empathy_first"], specs["empathy_first"], persona,
        settings=Settings(_env_file=None), prospect=prospect, offline=True, max_turns=2,
    )

    call = session.scalar(select(Call).where(Call.call_id == result.call_id))
    assert call.experiment_id == exp.experiment_id
    assert call.variant_id == records["empathy_first"].variant_id
    assert call.is_synthetic is True and call.channel == "sim:price_sensitive_parent"
    # The variant's rebuttal (not the baseline) was what the agent said to the price objection.
    agent_lines = " ".join(t for who, t in result.transcript if who == "agent")
    assert specs["empathy_first"].rebuttal in agent_lines


# --- P7-T4: evaluation, promotion rule, report --------------------------------------------------


def _score(*, objection, recovered, frustration=False, unsupported=False) -> CallScore:
    return CallScore(
        call_id="c",
        persona_key="p",
        outcome=None,
        escalated=False,
        close_attempted=recovered,
        discovery_completed=False,
        objection_raised=objection,
        objection_recovered=recovered,
        appropriate_for_persona=True,
        judge=JudgeScores(
            frustration=frustration, unsupported_claim=unsupported, consultative_score=4
        ),
    )


def test_aggregate_computes_rates_over_objection_calls():
    scores = [
        _score(objection=True, recovered=True),
        _score(objection=True, recovered=False, frustration=True),
        _score(objection=False, recovered=False),  # no objection -> excluded from recovery
    ]
    m = aggregate("v", scores)
    assert m.n_calls == 3 and m.n_objection_calls == 2
    assert m.objection_recovery_rate == 0.5  # 1 of 2 objection calls recovered
    assert m.frustration_rate == pytest.approx(1 / 3)


def test_decide_promotion_rule():
    baseline = aggregate("baseline", [_score(objection=True, recovered=False)])  # recovery 0%
    better = aggregate("v", [_score(objection=True, recovered=True)])  # recovery 100%
    assert decide_promotion(baseline, better).promote is True

    # Improves recovery but the prospect got frustrated -> guardrail blocks it.
    frustrating = aggregate("v", [_score(objection=True, recovered=True, frustration=True)])
    assert decide_promotion(baseline, frustrating).promote is False

    # No improvement over baseline -> not promoted.
    same = aggregate("v", [_score(objection=True, recovered=False)])
    assert decide_promotion(baseline, same).promote is False


def _tagged_call(session, exp, variant_id, *, events) -> str:
    rec = CallRecorder(
        session,
        channel="sim:price_sensitive_parent",
        is_synthetic=True,
        experiment_id=exp.experiment_id,
        variant_id=variant_id,
    )
    for e in events:
        rec.record_event(e)
    return rec.call_id


def test_evaluate_experiment_promotes_best_candidate(tmp_path, session):
    winner = next(c for c in CANDIDATES if c.key == "empathy_first")
    exp, specs, records = create_experiment(session, name="eval", candidates=[winner])

    # Baseline took a price objection and never recovered; the variant recovered (reached a close).
    _tagged_call(session, exp, records["baseline"].variant_id, events=[kpi.OBJECTION_RAISED])
    _tagged_call(
        session, exp, records["empathy_first"].variant_id,
        events=[kpi.OBJECTION_RAISED, kpi.CLOSE_ATTEMPT],
    )

    report = evaluate_experiment(session, exp, specs, records, judge=False)

    assert report.promoted_key == "empathy_first"
    assert report.baseline.objection_recovery_rate == 0.0
    assert report.variants["empathy_first"].objection_recovery_rate == 1.0
    assert records["empathy_first"].status == "promoted"
    assert records["empathy_first"].promoted_at is not None
    assert exp.status == "completed" and exp.decision == "promoted:empathy_first"

    md = render_report(report, specs)
    assert "promoted" in md.lower() and winner.name in md


def test_run_experiment_offline_runs_all_variants(session):
    winner = next(c for c in CANDIDATES if c.key == "empathy_first")
    exp, specs, records = create_experiment(session, name="run", candidates=[winner])
    persona = get_personas().get("price_sensitive_parent")

    def factory(_persona):
        return lambda _line: "honestly this is too expensive"

    results = run_experiment(
        session, exp, specs, records,
        personas=[persona], settings=Settings(_env_file=None),
        offline=True, prospect_factory=factory, max_turns=2,
    )

    assert set(results) == {"baseline", "empathy_first"}
    assert all(len(runs) == 1 for runs in results.values())
    tagged = session.scalars(
        select(Call).where(Call.experiment_id == exp.experiment_id)
    ).all()
    assert len(tagged) == 2  # one call per variant
