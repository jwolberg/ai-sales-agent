"""Discovery question set and skip-known logic (PRD §9.3: DF-1, DF-2; LM-2, LM-3).

Loads the discovery playbook (required + leading questions) and, given what's already
been collected, decides which question to ask next — skipping fields we already know and
offering a confirmation prompt for them instead of re-asking (LM-3). Dynamic, signal-aware
ordering (DF-3) is layered on in P3-T3; this module provides the priority-ordered default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

# backend/app/agent/discovery.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLAYBOOK = REPO_ROOT / "data" / "playbooks" / "discovery.yaml"

KIND_REQUIRED = "required"
KIND_LEADING = "leading"


@dataclass(frozen=True)
class Question:
    """One discovery question: the slot it fills, what to say, and how to confirm it."""

    key: str
    prompt: str
    kind: str  # KIND_REQUIRED | KIND_LEADING
    confirm: str | None = None

    def confirm_prompt(self, value: object) -> str:
        """Phrase a confirmation of an already-known value (LM-3)."""
        template = self.confirm or "I've got {value} — is that still right?"
        return template.format(value=value)


class DiscoveryPlaybook:
    """The ordered set of discovery questions, with skip-known selection."""

    def __init__(self, required: list[Question], leading: list[Question]) -> None:
        self.required = required
        self.leading = leading

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PLAYBOOK) -> DiscoveryPlaybook:
        data = yaml.safe_load(Path(path).read_text()) or {}
        required = [Question(kind=KIND_REQUIRED, **q) for q in data.get("required", [])]
        leading = [Question(kind=KIND_LEADING, **q) for q in data.get("leading", [])]
        return cls(required, leading)

    @staticmethod
    def _is_known(collected: Mapping[str, object], key: str) -> bool:
        return bool(collected.get(key))

    def missing_required(self, collected: Mapping[str, object]) -> list[Question]:
        """Required questions whose field we still don't know (LM-2)."""
        return [q for q in self.required if not self._is_known(collected, q.key)]

    def known_required(self, collected: Mapping[str, object]) -> list[Question]:
        """Required questions whose field is already known (skip or confirm — LM-3)."""
        return [q for q in self.required if self._is_known(collected, q.key)]

    def next_question(self, collected: Mapping[str, object]) -> Question | None:
        """The next best question by default priority: fill required gaps first, then
        explore leading questions; ``None`` once everything has been covered."""
        for question in self.required:
            if not self._is_known(collected, question.key):
                return question
        for question in self.leading:
            if not self._is_known(collected, question.key):
                return question
        return None


@lru_cache
def get_discovery_playbook() -> DiscoveryPlaybook:
    """Return the process-wide discovery playbook (parsed once)."""
    return DiscoveryPlaybook.load()
