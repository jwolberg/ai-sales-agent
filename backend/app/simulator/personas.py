"""Synthetic prospect personas (PRD §12.2, §12.3).

Loads the persona definitions and builds the system prompt that makes a Claude self-play
prospect behave like that persona — answering consistently from its ground-truth `facts`,
raising its objections in natural language, and following the §12.3 behavior rules (hesitate,
give partial answers, resist pushiness, occasionally disqualify, reward consultative selling).
The runner (P6-T2) uses `persona_system_prompt`; scoring (P6-T3) uses `facts`/flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

# backend/app/simulator/personas.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PERSONAS = REPO_ROOT / "data" / "personas" / "personas.yaml"

# Universal behavior rules every synthetic prospect follows (PRD §12.3) — designed to reveal
# weaknesses, not flatter the agent.
_BEHAVIOR_RULES = (
    "Stay in character as a prospective tutoring customer on a phone call. Speak only the words "
    "you would say out loud — short, natural, one thought at a time. Don't volunteer everything "
    "at once; give partial answers and make the agent ask. Hesitate, ask your own follow-up "
    "questions, and raise your objections naturally when they fit. Resist pushy or premature "
    "closing. Reward a helpful, consultative agent by warming up; punish a scripted or pushy one "
    "by staying guarded. Never break character or mention that you are an AI or a simulation. "
    "When the conversation has reached a natural end, say a brief goodbye."
)


@dataclass(frozen=True)
class Persona:
    """A synthetic prospect: who they are, what they know, and how they behave."""

    key: str
    name: str
    summary: str
    converts: bool
    disqualifies: bool
    traits: tuple[str, ...] = ()
    facts: dict[str, str] = field(default_factory=dict)
    objections: tuple[str, ...] = ()
    # Intent-router ground truth (IR5-T1): the leaf this caller actually needs, and the line they
    # open with. The benchmark scores the agent's reached leaf against `target_leaf`.
    target_leaf: str | None = None
    opening_line: str | None = None


class PersonaLibrary:
    """The set of synthetic personas."""

    def __init__(self, personas: list[Persona]) -> None:
        self.personas = personas
        self._by_key = {p.key: p for p in personas}

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PERSONAS) -> PersonaLibrary:
        data = yaml.safe_load(Path(path).read_text()) or {}
        personas = [
            Persona(
                key=p["key"],
                name=p["name"],
                summary=p["summary"],
                converts=bool(p.get("converts", False)),
                disqualifies=bool(p.get("disqualifies", False)),
                traits=tuple(p.get("traits", [])),
                facts=dict(p.get("facts", {})),
                objections=tuple(p.get("objections", [])),
                target_leaf=p.get("target_leaf"),
                opening_line=p.get("opening_line"),
            )
            for p in data.get("personas", [])
        ]
        return cls(personas)

    def get(self, key: str) -> Persona:
        return self._by_key[key]

    def keys(self) -> list[str]:
        return [p.key for p in self.personas]

    def router_personas(self) -> list[Persona]:
        """Personas carrying an intent-router ground-truth leaf (IR5-T1 benchmark set)."""
        return [p for p in self.personas if p.target_leaf]


@lru_cache
def get_personas() -> PersonaLibrary:
    """Return the process-wide persona library (parsed once)."""
    return PersonaLibrary.load()


def persona_system_prompt(persona: Persona) -> str:
    """Build the system prompt that drives a Claude self-play prospect for this persona."""
    facts = "\n".join(f"- {k}: {v}" for k, v in persona.facts.items()) or "- (little is settled)"
    traits = "\n".join(f"- {t}" for t in persona.traits)
    objections = (
        "\n".join(f'- "{o}"' for o in persona.objections)
        if persona.objections
        else "- (no strong objections unless provoked)"
    )
    disq = (
        "You are NOT a good fit and are not ready to buy — do not let the agent talk you into a "
        "close; if pressed, stay noncommittal."
        if persona.disqualifies
        else "If the agent earns it (clear value, addresses your concerns), you can warm toward a "
        "next step."
    )
    return (
        f"You are role-playing a prospective tutoring customer: {persona.name}. "
        f"{persona.summary}\n\n"
        f"Your situation (answer consistently from this; reveal it gradually):\n{facts}\n\n"
        f"How you behave:\n{traits}\n\n"
        f"Objections / pushback you tend to raise:\n{objections}\n\n"
        f"{disq}\n\n{_BEHAVIOR_RULES}"
    )
