"""Tests for lead profile loading & cross-call memory (P3-T1)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.seed import seed_leads
from app.memory.lead_store import (
    INFO_FULL,
    INFO_NONE,
    INFO_PARTIAL,
    LeadStore,
    all_known_fields,
    info_level,
    known_fields,
    missing_required,
)

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "leads" / "seed_leads.json"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_leads(s, json.loads(SEED_PATH.read_text()))
        yield s


def test_info_level_matches_use_cases_1_to_3(session):
    store = LeadStore(session)
    full = store.load("seed-full-001")
    partial = store.load("seed-partial-002")
    none = store.load("seed-none-003")

    assert info_level(full) == INFO_FULL
    assert info_level(partial) == INFO_PARTIAL
    assert info_level(none) == INFO_NONE

    # Full lead: nothing required is missing; partial lead: still missing "who".
    assert missing_required(full) == []
    assert missing_required(partial) == ["relationship_to_student"]
    assert set(missing_required(none)) == {"relationship_to_student", "subject", "grade_level"}

    assert known_fields(partial) == {"subject": "SAT prep", "grade_level": "11th grade"}


def test_load_unknown_lead_returns_none(session):
    assert LeadStore(session).load("does-not-exist") is None


def test_get_or_create_makes_a_fresh_lead_for_no_info_session(session):
    store = LeadStore(session)
    lead = store.get_or_create()  # no id -> brand new lead
    assert lead.lead_id  # generated
    assert info_level(lead) == INFO_NONE


def test_apply_call_outcome_carries_forward_to_the_next_call(session):
    store = LeadStore(session)

    # First call learns the missing "who" and raises a new objection.
    partial = store.load("seed-partial-002")
    store.apply_call_outcome(
        partial,
        collected={"relationship_to_student": "parent", "goal": "raise SAT score"},
        objections=["worried about cost"],
        summary="Parent of an 11th grader prepping for the SAT; cost-sensitive.",
        status="qualified",
    )

    # A later call reloads the lead and sees everything carried forward.
    reloaded = LeadStore(session).load("seed-partial-002")
    assert reloaded.relationship_to_student == "parent"
    assert reloaded.goal == "raise SAT score"
    assert reloaded.prior_objections == ["worried about cost"]
    assert reloaded.prior_summary.startswith("Parent of an 11th grader")
    assert reloaded.status == "qualified"
    # Now nothing required is missing — it became a full-info lead.
    assert info_level(reloaded) == INFO_FULL


def test_apply_call_outcome_dedupes_objections_and_skips_empty(session):
    store = LeadStore(session)
    full = store.load("seed-full-001")
    before = list(full.prior_objections)

    store.apply_call_outcome(
        full,
        collected={"subject": ""},  # empty -> must not overwrite existing
        objections=["worried about cost", "needs to discuss with spouse"],  # first is a dup
    )
    assert full.subject == "Algebra I"  # unchanged
    # Only the genuinely new objection is appended.
    assert full.prior_objections == before + ["needs to discuss with spouse"]


def test_non_profile_slots_persist_and_all_known_fields_merges(session):
    # P10-T3: slots without a typed column (challenge, readiness, …) must survive the call so the
    # next one doesn't re-ask them. Profile fields still update their typed columns.
    store = LeadStore(session)
    none = store.load("seed-none-003")
    store.apply_call_outcome(
        none,
        collected={
            "subject": "Algebra II",        # typed profile column
            "challenge": "word problems",   # no column -> collected_fields JSON
            "readiness": "ready to start",  # no column -> collected_fields JSON
            "blank": "",                    # empty -> skipped entirely
        },
    )
    reloaded = LeadStore(session).load("seed-none-003")
    assert reloaded.subject == "Algebra II"
    assert reloaded.collected_fields["challenge"] == "word problems"
    assert reloaded.collected_fields["readiness"] == "ready to start"
    assert "blank" not in reloaded.collected_fields
    # all_known_fields surfaces both the typed columns and the JSON slots for re-seeding.
    merged = all_known_fields(reloaded)
    assert merged["subject"] == "Algebra II"
    assert merged["challenge"] == "word problems"
