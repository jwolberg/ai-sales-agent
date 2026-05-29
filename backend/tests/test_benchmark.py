"""Benchmark tests (IR5-T2) — offline accuracy harness over router personas."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.config import Settings
from app.db.models import Base
from app.kpis.metrics import compute_router_metrics
from app.simulator.benchmark import run_benchmark, score_benchmark


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_offline_benchmark_classifies_all_personas(session):
    out = run_benchmark(session, brain=RuleBrain(Settings(_env_file=None)))
    metrics = out["metrics"]
    # The cooperative deterministic prospect + RuleBrain should reach every persona's true leaf.
    assert metrics["classification_accuracy"] == 1.0
    assert metrics["mis_quote_rate"] == 0.0
    assert metrics["price_correct_rate"] == 1.0
    assert metrics["median_turns_to_classification"] is not None


def test_per_call_results_have_ground_truth(session):
    out = run_benchmark(session, brain=RuleBrain(Settings(_env_file=None)))
    for r in out["results"]:
        assert r.reached_leaf == r.target_leaf
        assert r.correct


def test_ambiguous_persona_takes_more_turns_than_explicit(session):
    out = run_benchmark(session, brain=RuleBrain(Settings(_env_file=None)))
    by_key = {r.persona_key: r for r in out["results"]}
    # explicit SAT opener resolves on turn 1; "science help" needs follow-ups
    assert by_key["router_sat_explicit"].turns < by_key["router_science_ambiguous"].turns


def test_router_metrics_from_db(session):
    run_benchmark(session, brain=RuleBrain(Settings(_env_file=None)))
    m = compute_router_metrics(session)
    assert m["total_calls"] == 10
    assert m["leaf_reached_rate"] == 1.0
    assert m["mis_quote_rate"] == 0.0


def test_score_benchmark_empty():
    assert score_benchmark([]) == {"total_calls": 0}
