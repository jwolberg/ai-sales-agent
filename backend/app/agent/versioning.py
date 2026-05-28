"""Version attribution for calls (PRD §10.4).

Every call is tagged with the versions of the things that shaped it — the agent persona prompt,
the playbooks, the knowledge base, and the model — so behavior is traceable and experiments
(Phase 7) can attribute outcomes to a configuration. Content-derived versions are short content
hashes that change whenever the underlying content changes; the model version is the configured
model id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.agent.persona import build_system_prompt
from app.config import Settings, get_settings

# backend/app/agent/versioning.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
_PLAYBOOK_DIR = REPO_ROOT / "data" / "playbooks"
_KB_DIR = REPO_ROOT / "data" / "kb"


def _short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _hash_dir(directory: Path, glob: str) -> str:
    """Stable content hash of the matching files in a directory (name + bytes, sorted)."""
    if not directory.exists():
        return "none"
    parts: list[str] = []
    for path in sorted(directory.glob(glob)):
        parts.append(path.name)
        parts.append(path.read_text())
    return _short("".join(parts)) if parts else "none"


@dataclass(frozen=True)
class Versions:
    """The version stamp for one call (maps to the Call version columns)."""

    agent_version: str
    playbook_version: str
    kb_version: str
    model_version: str

    def as_dict(self) -> dict[str, str]:
        return {
            "agent_version": self.agent_version,
            "playbook_version": self.playbook_version,
            "kb_version": self.kb_version,
            "model_version": self.model_version,
        }


def compute_versions(settings: Settings | None = None) -> Versions:
    """Compute the current version stamp from the persona, playbooks, KB, and configured model."""
    settings = settings or get_settings()
    return Versions(
        agent_version="persona-" + _short(build_system_prompt(settings)),
        playbook_version="pb-" + _hash_dir(_PLAYBOOK_DIR, "*.yaml"),
        kb_version="kb-" + _hash_dir(_KB_DIR, "*.md"),
        model_version=settings.anthropic_model,
    )
