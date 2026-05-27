"""Ingest approved knowledge-base documents into retrievable chunks (PRD KB-2, KB-3).

Markdown docs in ``data/kb/`` are split into chunks at ``##`` section headings, each
tagged with its source file and section title so retrieval can report where an answer
came from (KB-3). HTML comments (e.g. PLACEHOLDER notes) are stripped from chunk text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# backend/app/kb/ingest.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KB_DIR = REPO_ROOT / "data" / "kb"

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_H1 = re.compile(r"^#\s+(.*)$")
_H2 = re.compile(r"^##\s+(.*)$")


@dataclass(frozen=True)
class KBChunk:
    """One retrievable section of a KB doc."""

    chunk_id: str  # "<source>#<n>"
    source: str    # doc filename — the citable KB source id (KB-3)
    title: str     # doc title + section heading
    text: str


def _chunk_markdown(source: str, raw: str) -> list[KBChunk]:
    text = _COMMENT.sub("", raw)
    lines = text.splitlines()

    doc_title = source
    for line in lines:
        m = _H1.match(line)
        if m:
            doc_title = m.group(1).strip()
            break

    # Walk lines, opening a new chunk at each "## " heading.
    chunks: list[KBChunk] = []
    current_heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if not body:
            return
        heading = current_heading or doc_title
        title = heading if heading == doc_title else f"{doc_title} — {heading}"
        chunks.append(
            KBChunk(chunk_id=f"{source}#{len(chunks)}", source=source, title=title, text=body)
        )

    for line in lines:
        if _H1.match(line):
            continue  # doc title already captured
        h2 = _H2.match(line)
        if h2:
            flush()
            current_heading = h2.group(1).strip()
            buffer = []
        else:
            buffer.append(line)
    flush()
    return chunks


def load_documents(kb_dir: Path | str = DEFAULT_KB_DIR) -> list[KBChunk]:
    """Load and chunk every ``*.md`` doc under ``kb_dir`` (sorted for determinism)."""
    directory = Path(kb_dir)
    if not directory.exists():
        return []
    chunks: list[KBChunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(_chunk_markdown(path.name, path.read_text()))
    return chunks
