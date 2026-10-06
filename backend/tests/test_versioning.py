"""Tests for version attribution (P5-T2; PRD §10.4)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.recorder import CallRecorder
from app.agent.versioning import compute_versions
from app.config import Settings
from app.db.models import Base, Call


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_compute_versions_is_stable_and_well_formed():
    settings = Settings(_env_file=None, anthropic_model="claude-sonnet-4-6")
    v1 = compute_versions(settings)
    v2 = compute_versions(settings)
    assert v1 == v2  # deterministic for the same content/config
    assert v1.agent_version.startswith("persona-")
    assert v1.playbook_version.startswith("pb-")  # hashed the discovery/objection playbooks
    assert v1.kb_version.startswith("kb-")  # hashed the KB docs
    assert v1.model_version == "claude-sonnet-4-6"


def test_agent_version_tracks_persona_changes():
    a = compute_versions(Settings(_env_file=None, agent_name="Ava", company_name="VT"))
    b = compute_versions(Settings(_env_file=None, agent_name="Jay", company_name="Nerdy"))
    assert a.agent_version != b.agent_version  # persona text changed -> version changed


def test_recorder_stamps_versions_on_the_call(session):
    versions = compute_versions(Settings(_env_file=None))
    rec = CallRecorder(session, channel="web", **versions.as_dict())
    loaded = session.scalar(select(Call).where(Call.call_id == rec.call_id))
    assert loaded.agent_version == versions.agent_version
    assert loaded.playbook_version == versions.playbook_version
    assert loaded.kb_version == versions.kb_version
    assert loaded.model_version == versions.model_version
