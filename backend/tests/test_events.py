"""Live event bus tests (IR7-T2) — pub/sub + recorder publishing."""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.brain import RuleBrain
from app.agent.intent_engine import IntentRouterEngine
from app.agent.recorder import CallRecorder
from app.config import Settings
from app.db.models import Base
from app.events import EventBus


def test_bus_delivers_to_subscriber():
    async def go():
        bus = EventBus()
        sub = bus.subscribe()
        bus.publish(call_id="c1", type="turn", text="hi")
        await asyncio.sleep(0)  # let call_soon_threadsafe run
        event = await asyncio.wait_for(sub.queue.get(), timeout=1)
        assert event == {"call_id": "c1", "type": "turn", "text": "hi"}

    asyncio.run(go())


def test_bus_filters_by_call_id():
    async def go():
        bus = EventBus()
        sub = bus.subscribe(call_id="want")
        bus.publish(call_id="other", type="turn")
        bus.publish(call_id="want", type="turn")
        await asyncio.sleep(0)
        event = await asyncio.wait_for(sub.queue.get(), timeout=1)
        assert event["call_id"] == "want"
        assert sub.queue.empty()  # the "other" event was filtered out

    asyncio.run(go())


def test_recorder_engine_publishes_call_lifecycle():
    async def go():
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        from app.events import bus  # the singleton the recorder publishes to

        sub = bus.subscribe()
        try:
            with Session(engine) as s:
                rec = CallRecorder(s, channel="text", is_synthetic=True)
                eng = IntentRouterEngine(
                    brain=RuleBrain(Settings(_env_file=None)),
                    recorder=rec,
                    settings=Settings(_env_file=None),
                )
                eng.open()
                eng.run_turn("I need chemistry tutoring")
                eng.end(outcome="completed")
            await asyncio.sleep(0)
            types = []
            while not sub.queue.empty():
                types.append(sub.queue.get_nowait()["type"])
            assert "call_started" in types
            assert "turn" in types
            assert "decision" in types
            assert "call_ended" in types
        finally:
            bus.unsubscribe(sub)

    asyncio.run(go())
