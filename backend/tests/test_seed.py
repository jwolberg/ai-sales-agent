import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import Base, Lead
from app.db.seed import load_seed_leads, seed_leads


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_seed_loads_three_info_levels(session):
    count = seed_leads(session)
    assert count == 3

    full = session.get(Lead, "seed-full-001")
    partial = session.get(Lead, "seed-partial-002")
    none = session.get(Lead, "seed-none-003")

    # Use Case 1: full prior info.
    assert full.student_name == "Mia Rivera"
    assert full.budget_sensitivity is not None
    assert full.prior_summary is not None

    # Use Case 2: partial info — subject/grade known, deeper fields missing.
    assert partial.subject == "SAT prep"
    assert partial.urgency is None
    assert partial.decision_maker_status is None

    # Use Case 3: effectively no info.
    assert none.contact_name is None
    assert none.subject is None

    # All seed data is labeled synthetic (PRD §13.3).
    assert all(lead.is_synthetic for lead in session.scalars(select(Lead)))


def test_seed_is_idempotent(session):
    seed_leads(session)
    seed_leads(session)
    assert session.scalar(select(func.count()).select_from(Lead)) == 3


def test_seed_file_is_valid():
    leads = load_seed_leads()
    assert len(leads) == 3
    assert {lead["lead_id"] for lead in leads} == {
        "seed-full-001",
        "seed-partial-002",
        "seed-none-003",
    }
