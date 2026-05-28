"""Tests for experiment & variant infrastructure (P7-T1; PRD §8, §11)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.orchestrator import Orchestrator
from app.config import Settings
from app.db.models import Base, Call, Variant
from app.experiments.engine import create_experiment, run_variant
from app.experiments.variants import BASELINE, CANDIDATES, all_variants
from app.simulator.personas import get_personas


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
