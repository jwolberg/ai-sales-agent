"""Objection detection and handling (PRD Use Case 4; §8 price baseline).

Loads the objection playbook, detects which objection (if any) a caller's turn raises via
its cues, and assembles an approved rebuttal — optionally grounded with supporting KB
snippets. High-risk objections (e.g. discount requests) are flagged so the orchestrator can
gate the close and route to escalation (DE-4 / §18); the LLM phrasing layer delivers the
rebuttal naturally rather than reading it verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.agent.knowledge import answer_question
from app.kb.retriever import KBRetriever

# backend/app/agent/objections.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLAYBOOK = REPO_ROOT / "data" / "playbooks" / "objections.yaml"


@dataclass(frozen=True)
class Objection:
    """One objection type: how to spot it and the approved rebuttal."""

    key: str
    cues: tuple[str, ...]
    rebuttal: str
    high_risk: bool = False
    baseline: bool = False
    kb_query: str | None = None


@dataclass
class ObjectionResponse:
    """The handled objection: rebuttal text, risk flag, and any KB sources used."""

    objection_key: str
    rebuttal: str
    high_risk: bool
    kb_sources: list[str] = field(default_factory=list)


class ObjectionPlaybook:
    """Detects objections from caller text and supplies approved rebuttals."""

    def __init__(self, objections: list[Objection]) -> None:
        self.objections = objections

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PLAYBOOK) -> ObjectionPlaybook:
        data = yaml.safe_load(Path(path).read_text()) or {}
        objections = [
            Objection(
                key=o["key"],
                cues=tuple(o.get("cues", [])),
                rebuttal=" ".join(o["rebuttal"].split()),  # normalize folded YAML whitespace
                high_risk=bool(o.get("high_risk", False)),
                baseline=bool(o.get("baseline", False)),
                kb_query=o.get("kb_query"),
            )
            for o in data.get("objections", [])
        ]
        return cls(objections)

    def detect(self, text: str) -> Objection | None:
        """Return the first objection whose cues appear in ``text`` (playbook order)."""
        lowered = text.lower()
        for objection in self.objections:
            if any(cue in lowered for cue in objection.cues):
                return objection
        return None

    def baseline_price(self) -> Objection:
        """The documented baseline price objection (Phase 7 improvement target)."""
        return next(o for o in self.objections if o.baseline)


@lru_cache
def get_objection_playbook() -> ObjectionPlaybook:
    """Return the process-wide objection playbook (parsed once)."""
    return ObjectionPlaybook.load()


def respond_to_objection(
    objection: Objection, *, retriever: KBRetriever | None = None
) -> ObjectionResponse:
    """Build the rebuttal for an objection, grounding supporting detail from the KB if any."""
    sources: list[str] = []
    if objection.kb_query:
        answer = answer_question(objection.kb_query, retriever=retriever)
        if answer.grounded:
            sources = answer.sources
    return ObjectionResponse(
        objection_key=objection.key,
        rebuttal=objection.rebuttal,
        high_risk=objection.high_risk,
        kb_sources=sources,
    )
