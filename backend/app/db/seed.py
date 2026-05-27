"""Seed sample data and load PII-substituted transcripts.

Run as a script to (re)seed the local database:

    python -m app.db.seed

Seeding is idempotent: leads carry fixed ``lead_id`` values, so re-running updates
existing rows instead of creating duplicates.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Lead
from app.db.session import SessionLocal, init_db

# Repo root is four levels up from this file: backend/app/db/seed.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
LEADS_FILE = DATA_DIR / "leads" / "seed_leads.json"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"


def load_seed_leads(path: Path = LEADS_FILE) -> list[dict]:
    """Read the seed lead definitions from JSON."""
    return json.loads(path.read_text())


def seed_leads(session: Session, leads: list[dict] | None = None) -> int:
    """Upsert seed leads by ``lead_id``. Returns the number processed."""
    leads = leads if leads is not None else load_seed_leads()
    for data in leads:
        existing = session.get(Lead, data["lead_id"])
        if existing is None:
            session.add(Lead(**data))
        else:
            for key, value in data.items():
                setattr(existing, key, value)
    session.commit()
    return len(leads)


def load_transcripts(directory: Path = TRANSCRIPTS_DIR) -> list[dict]:
    """Load PII-substituted transcripts from ``directory``.

    Stub for the transcript database the PRD says will be provided later. Scans for
    ``*.json`` files (each a transcript object or an array of them) and returns the
    parsed records. Files not marked ``pii_substituted: true`` are skipped so raw PII is
    never ingested. Returns an empty list when no transcripts are present.
    """
    if not directory.exists():
        return []
    transcripts: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        records = payload if isinstance(payload, list) else [payload]
        transcripts.extend(r for r in records if r.get("pii_substituted") is True)
    return transcripts


def main() -> None:
    init_db()
    with SessionLocal() as session:
        count = seed_leads(session)
    transcripts = load_transcripts()
    print(f"Seeded {count} leads. Loaded {len(transcripts)} PII-substituted transcripts.")


if __name__ == "__main__":
    main()
