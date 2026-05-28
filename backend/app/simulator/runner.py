"""Simulated call runner — agent vs. synthetic prospect self-play (P6-T2; PRD §12.1).

Drives the same ConversationEngine used live, in text mode, against a Claude self-play prospect.
It writes the same Call/Turn/Decision/KPIEvent records — labeled ``is_synthetic=True`` and tagged
with the persona on the call's channel — so simulated runs feed the dashboard and the Phase 7
experiment loop exactly like real calls.

`run_call` (the loop) is LLM-agnostic: it alternates `engine.run_turn` with a prospect responder,
so tests inject a scripted prospect + a no-LLM engine. `simulate` wires the real Claude prospect
and a full engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent.decisioning import DiscoveryDecider
from app.agent.engine import ConversationEngine
from app.agent.extraction import LLMExtractor
from app.agent.orchestrator import Orchestrator
from app.agent.recorder import (
    OUTCOME_ABANDONED,
    OUTCOME_COMPLETED,
    OUTCOME_DISQUALIFIED,
    OUTCOME_ESCALATED,
    CallRecorder,
)
from app.agent.stages import Action, Stage
from app.agent.synthesis import make_synthesizer
from app.agent.versioning import compute_versions
from app.config import Settings, get_settings
from app.simulator.personas import Persona, persona_system_prompt

# Given the agent's last line, return the prospect's next line.
Prospect = Callable[[str], str]

# Sentinel so callers can pass synthesize=None (no LLM phrasing) distinctly from "use the default".
_DEFAULT_SYNTH = object()

_TERMINAL_STAGES = {Stage.WRAP_UP, Stage.ESCALATION, Stage.DISQUALIFIED}
_GOODBYE = ("bye", "goodbye", "take care", "talk later", "that's all", "have a good")


@dataclass
class SimResult:
    """Outcome of one simulated call."""

    call_id: str
    persona_key: str
    final_stage: Stage
    outcome: str | None
    transcript: list[tuple[str, str]] = field(default_factory=list)

    @property
    def num_turns(self) -> int:
        return len(self.transcript)


def _is_goodbye(text: str) -> bool:
    lowered = text.lower()
    return any(g in lowered for g in _GOODBYE)


def _outcome_for(stage: Stage) -> str | None:
    return {
        Stage.ESCALATION: OUTCOME_ESCALATED,
        Stage.DISQUALIFIED: OUTCOME_DISQUALIFIED,
        Stage.WRAP_UP: OUTCOME_COMPLETED,
        Stage.CLOSE: OUTCOME_COMPLETED,  # reached an explicit close attempt
    }.get(stage, OUTCOME_ABANDONED)


def run_call(
    engine: ConversationEngine, prospect: Prospect, persona_key: str, *, max_turns: int = 12
) -> SimResult:
    """Drive one self-play call: greet, then alternate prospect ↔ agent until a terminal stage,
    a goodbye, or the turn cap. The prospect callable owns its own memory."""
    transcript: list[tuple[str, str]] = [("agent", engine.open())]
    agent_line = transcript[0][1]
    final_stage = engine.state.stage

    for _ in range(max_turns):
        prospect_text = prospect(agent_line)
        transcript.append(("prospect", prospect_text))
        if _is_goodbye(prospect_text):
            break
        result = engine.run_turn(prospect_text)
        agent_line = result.utterance
        final_stage = result.action.stage
        transcript.append(("agent", agent_line))
        if result.action.stage in _TERMINAL_STAGES or result.action.action is Action.END_CALL:
            break

    outcome = _outcome_for(final_stage)
    engine.end(outcome=outcome)
    return SimResult(
        call_id=engine.orch.recorder.call_id if engine.orch.recorder is not None else "",
        persona_key=persona_key,
        final_stage=final_stage,
        outcome=outcome,
        transcript=transcript,
    )


def make_prospect(
    persona: Persona, settings: Settings, *, client: object | None = None
) -> Prospect:
    """Claude self-play prospect. Keeps its own history; the agent's lines are 'user' turns and
    the prospect's replies are 'assistant' turns (role reversal from the agent's view)."""
    system = persona_system_prompt(persona)
    history: list[dict] = []

    def respond(agent_line: str) -> str:
        nonlocal client
        history.append({"role": "user", "content": agent_line})
        if client is None:
            import anthropic  # lazy

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key or "")
        response = client.messages.create(
            model=settings.anthropic_model, max_tokens=200, system=system, messages=history
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        history.append({"role": "assistant", "content": text})
        return text

    return respond


def build_simulation_engine(
    session: Session,
    persona: Persona,
    settings: Settings,
    *,
    experiment_id: str | None = None,
    variant_id: str | None = None,
    objection_overrides: dict[str, str] | None = None,
    extractor=None,
    synthesize=_DEFAULT_SYNTH,
) -> ConversationEngine:
    """A full engine for self-play: synthetic recorder (tagged with the persona, and the
    experiment/variant when running an experiment) + LLM extraction + Claude phrasing.
    ``objection_overrides`` applies a variant's rebuttal (P7). ``extractor``/``synthesize`` can be
    overridden (e.g. rule-based + None) to run fully offline in tests."""
    recorder = CallRecorder(
        session,
        channel=f"sim:{persona.key}",
        is_synthetic=True,
        experiment_id=experiment_id,
        variant_id=variant_id,
        **compute_versions(settings).as_dict(),
    )
    orch = Orchestrator(
        settings=settings,
        decider=DiscoveryDecider(),
        recorder=recorder,
        objection_overrides=objection_overrides,
    )
    return ConversationEngine(
        orch,
        extractor=extractor or LLMExtractor(settings=settings),
        synthesize=make_synthesizer(settings) if synthesize is _DEFAULT_SYNTH else synthesize,
    )


def simulate(
    session: Session, persona: Persona, *, settings: Settings | None = None, max_turns: int = 12
) -> SimResult:
    """Wire the real Claude prospect + engine and run one simulated call end-to-end."""
    settings = settings or get_settings()
    engine = build_simulation_engine(session, persona, settings)
    prospect = make_prospect(persona, settings)
    return run_call(engine, prospect, persona.key, max_turns=max_turns)
