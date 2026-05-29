"""Simulated live call feed (IR7-T3).

Runs a router persona through the real :class:`IntentRouterEngine` in the background, **paced** so
the dashboard sees the call appear and the transcript stream in over the SSE bus — the "calls come
in" demo driver that needs no mic and no Twilio. Uses the deterministic prospect by default; with an
OpenAI key the brain makes real decisions.
"""

from __future__ import annotations

import asyncio

from app.agent.brain import Brain, get_brain
from app.agent.contract import RouterAction
from app.agent.intent_engine import IntentRouterEngine
from app.agent.recorder import CallRecorder
from app.config import get_settings
from app.db.session import SessionLocal
from app.simulator.benchmark import RouterProspect
from app.simulator.personas import Persona

DEFAULT_TURN_DELAY = 1.2  # seconds between turns, so the stream reads like a live call
_TERMINAL = (RouterAction.QUOTE, RouterAction.ESCALATE, RouterAction.END)


async def run_sim_call_paced(
    persona: Persona,
    *,
    session_factory=SessionLocal,
    brain: Brain | None = None,
    turn_delay: float = DEFAULT_TURN_DELAY,
    max_turns: int = 8,
) -> str:
    """Drive one paced simulated call; returns the call_id. Sync engine work runs in threads so the
    event loop (and the SSE stream) stays responsive."""
    settings = get_settings()
    brain = brain or get_brain(settings)

    def _open():
        session = session_factory()
        recorder = CallRecorder(session, channel="sim", is_synthetic=True)
        engine = IntentRouterEngine(brain=brain, recorder=recorder, settings=settings)
        engine.open()
        return session, engine, recorder.call_id

    session, engine, call_id = await asyncio.to_thread(_open)
    try:
        prospect = RouterProspect(persona)
        user_text = prospect.opening()
        for _ in range(max_turns):
            if turn_delay:
                await asyncio.sleep(turn_delay)
            result = await asyncio.to_thread(engine.run_turn, user_text)
            if result.action in _TERMINAL:
                break
            user_text = prospect.next()
        await asyncio.to_thread(engine.end, outcome="completed")
        return call_id
    finally:
        await asyncio.to_thread(session.close)
