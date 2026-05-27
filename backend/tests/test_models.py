import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    Call,
    Decision,
    Experiment,
    KPIEvent,
    Lead,
    Turn,
    Variant,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_full_call_graph_round_trips(session):
    lead = Lead(
        contact_name="Test Parent",
        subject="Algebra",
        grade_level="8th",
        prior_objections=["too expensive", "tried before"],
    )
    call = Call(lead=lead, channel="web", agent_version="v1")
    turn = Turn(call=call, speaker="prospect", text="It's too expensive.", confidence=0.9)
    call.decisions.append(
        Decision(
            selected_action="handle_objection",
            stage="objection_handling",
            missing_fields=["budget_sensitivity"],
            kb_sources_used=["pricing.md"],
        )
    )
    call.kpi_events.append(
        KPIEvent(event_type="objection_raised", event_value=1.0, event_metadata={"type": "price"})
    )
    session.add(call)
    session.commit()

    loaded = session.scalar(select(Lead).where(Lead.lead_id == lead.lead_id))
    assert loaded.prior_objections == ["too expensive", "tried before"]
    assert len(loaded.calls) == 1

    saved_call = loaded.calls[0]
    assert saved_call.turns[0].text == "It's too expensive."
    assert saved_call.decisions[0].missing_fields == ["budget_sensitivity"]
    assert saved_call.kpi_events[0].event_metadata == {"type": "price"}
    # Defaults applied.
    assert loaded.status == "new"
    assert saved_call.started_at is not None
    assert turn.timestamp is not None


def test_experiment_variant_relationship(session):
    exp = Experiment(name="price-objection", primary_kpi="objection_recovery_rate")
    exp.variants.append(Variant(name="empathy-first"))
    exp.variants.append(Variant(name="risk-reversal"))
    session.add(exp)
    session.commit()

    loaded = session.scalar(select(Experiment).where(Experiment.experiment_id == exp.experiment_id))
    assert {v.name for v in loaded.variants} == {"empathy-first", "risk-reversal"}
    assert all(v.status == "candidate" for v in loaded.variants)


def test_cascade_delete_removes_children(session):
    call = Call(channel="web")
    call.turns.append(Turn(speaker="agent", text="Hi there."))
    session.add(call)
    session.commit()

    session.delete(call)
    session.commit()

    assert session.scalar(select(Turn)) is None
