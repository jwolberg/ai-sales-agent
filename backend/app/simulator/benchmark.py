"""Classification-accuracy benchmark (IR5-T2, R10).

Runs the intent-router personas (each carrying a ground-truth `target_leaf`) through the *real*
:class:`IntentRouterEngine` in text mode, then scores the leaf the agent reached against the
persona's true leaf. This is the headline metric — Classification Accuracy — plus
Turns-to-Classification, quote/mis-quote/escalation rates.

The synthetic prospect is deterministic (no network): it opens with the persona's `opening_line`,
then reveals the leaf's components progressively as the agent asks. So the benchmark — and its
tests — run offline against the RuleBrain; point it at the OpenAIBrain for a meaningful live score.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from app.agent import taxonomy as tx
from app.agent.brain import Brain, get_brain
from app.agent.contract import RouterAction
from app.agent.intent_engine import IntentRouterEngine
from app.agent.pricing import quote_price
from app.agent.recorder import CallRecorder
from app.config import Settings
from app.simulator.personas import Persona, get_personas

_TERMINAL = (RouterAction.QUOTE, RouterAction.ESCALATE, RouterAction.END)


class RouterProspect:
    """A deterministic caller that reveals its target leaf step by step as asked."""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona
        self._reveals = _reveal_sequence(persona.target_leaf)
        self._i = 0

    def opening(self) -> str:
        return self.persona.opening_line or "Hi, I have a question."

    def next(self) -> str:
        if self._i < len(self._reveals):
            phrase = self._reveals[self._i]
            self._i += 1
            return phrase
        return "Yes, that sounds good. Thank you!"


def _reveal_sequence(leaf_id: str) -> list[str]:
    leaf = tx.leaf_from_id(leaf_id)
    if leaf.category is tx.Category.TEST_PREP:
        return [f"I'm preparing for the {leaf.test}."]
    return [f"It's a {leaf.subject_area} subject.", f"It's {leaf.subject}."]


@dataclass
class RouterCallResult:
    persona_key: str
    target_leaf: str
    reached_leaf: str | None
    correct: bool
    turns: int
    quoted_price: float | None
    price_correct: bool
    escalated: bool
    mis_quoted: bool


def run_router_call(
    engine: IntentRouterEngine, persona: Persona, *, max_turns: int = 8
) -> RouterCallResult:
    engine.open()
    prospect = RouterProspect(persona)
    user_text = prospect.opening()
    turns = 0
    last_action = RouterAction.ASK
    while turns < max_turns:
        turns += 1
        result = engine.run_turn(user_text)
        last_action = result.action
        if result.action in _TERMINAL:
            break
        user_text = prospect.next()

    target = persona.target_leaf
    reached = engine.reached_leaf
    expected = quote_price(target)
    engine.end(outcome="completed")
    return RouterCallResult(
        persona_key=persona.key,
        target_leaf=target,
        reached_leaf=reached,
        correct=(reached == target),
        turns=turns,
        quoted_price=engine.quoted_price,
        price_correct=(
            engine.quoted_price is not None
            and expected is not None
            and abs(engine.quoted_price - expected.amount) < 0.001
        ),
        escalated=(last_action is RouterAction.ESCALATE),
        mis_quoted=engine.mis_quote_count > 0,
    )


def score_benchmark(results: list[RouterCallResult]) -> dict:
    total = len(results)
    if not total:
        return {"total_calls": 0}
    correct = [r for r in results if r.correct]
    turns_correct = [r.turns for r in correct]
    return {
        "total_calls": total,
        "classification_accuracy": round(len(correct) / total, 3),
        "median_turns_to_classification": (
            statistics.median(turns_correct) if turns_correct else None
        ),
        "quote_rate": round(sum(r.quoted_price is not None for r in results) / total, 3),
        "price_correct_rate": round(sum(r.price_correct for r in results) / total, 3),
        "mis_quote_rate": round(sum(r.mis_quoted for r in results) / total, 3),
        "escalation_rate": round(sum(r.escalated for r in results) / total, 3),
    }


def run_benchmark(
    session,
    *,
    personas: list[Persona] | None = None,
    brain: Brain | None = None,
    settings: Settings | None = None,
    max_turns: int = 8,
) -> dict:
    """Run the full router persona set through the engine and score it. Returns
    ``{"results": [...], "metrics": {...}}``."""
    settings = settings or Settings(_env_file=None)
    personas = personas if personas is not None else get_personas().router_personas()
    brain = brain or get_brain(settings)
    results: list[RouterCallResult] = []
    for persona in personas:
        recorder = CallRecorder(session, channel="benchmark", is_synthetic=True)
        engine = IntentRouterEngine(brain=brain, recorder=recorder, settings=settings)
        results.append(run_router_call(engine, persona, max_turns=max_turns))
    return {"results": results, "metrics": score_benchmark(results)}
