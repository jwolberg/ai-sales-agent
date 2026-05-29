"""Simulated live feed tests (IR7-T3)."""

import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.brain import RuleBrain
from app.config import Settings
from app.db.models import Base, Call
from app.simulator.live_feed import run_sim_call_paced
from app.simulator.personas import get_personas


def test_paced_sim_call_persists_a_synthetic_call():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    persona = next(p for p in get_personas().router_personas() if p.key == "router_chemistry")

    async def go():
        return await run_sim_call_paced(
            persona,
            session_factory=factory,
            brain=RuleBrain(Settings(_env_file=None)),
            turn_delay=0,  # no real-time pacing in the test
        )

    call_id = asyncio.run(go())
    with factory() as s:
        call = s.scalar(select(Call).where(Call.call_id == call_id))
        assert call is not None
        assert call.is_synthetic is True
        assert call.channel == "sim"
        assert call.reached_leaf == "tutoring/science/chemistry"
        assert call.ended_at is not None
