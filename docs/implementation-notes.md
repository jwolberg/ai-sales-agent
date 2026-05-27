# Implementation Notes

Running log of decisions, deviations, and tradeoffs during implementation.
Newest entries at the bottom of each ticket. Dates are ISO (YYYY-MM-DD).

---

## P1-T1 — Backend scaffold & config (2026-05-26)

- **Stack chosen** (PRD §14 left architecture "suggested," not locked): Python 3.10 +
  FastAPI + Uvicorn, `pydantic-settings` for config, `ruff` for lint, `pytest` for tests.
  Matches the assumptions documented in `docs/BUILD_PLAN.md`. Rationale: smallest
  reasonable path to a working backend; all are mainstream and dependency-light.
- **Single dependency manifest:** `backend/pyproject.toml` (PEP 621) with a `dev` extra
  (`pytest`, `httpx`, `ruff`). SQLAlchemy is intentionally *not* here yet — it lands with
  P1-T2 where it is first used, to keep each ticket's footprint honest.
- **Settings** are cached via `lru_cache` (`get_settings()`), read from env / optional
  `.env`. Default `DATABASE_URL` is a local SQLite file; documented in `.env.example`.
- **Bugfix during build:** initial `/health` handler took `config: Settings = get_settings()`
  as a parameter — FastAPI would treat a Pydantic model default as a request body. Changed
  to resolve settings inside the function body instead.
- **Env:** virtualenv at `backend/.venv` (already covered by `.venv/` in `.gitignore`).
- **Validation:** `ruff check .` clean; `pytest` 1 passed (`/health` returns ok + version).

---

## P1-T2 — Data model & persistence (2026-05-26)

- Implemented all seven PRD §15 entities (`Lead`, `Call`, `Turn`, `Decision`, `KPIEvent`,
  `Experiment`, `Variant`) with SQLAlchemy 2.0 declarative style in `app/db/models.py`.
- **Decisions not specified in the PRD:**
  - **PKs are UUID hex strings** (not autoincrement ints) so `call_id`/`lead_id` are stable
    references across transcripts, dashboards, and exports.
  - **JSON columns** for list/dict fields (`prior_objections`, `missing_fields`,
    `kb_sources_used`, `guardrail_kpis`, KPI metadata) — SQLite-friendly, no extra tables.
  - `KPIEvent.metadata` column is exposed as the attribute **`event_metadata`** because
    `metadata` is reserved on the SQLAlchemy declarative `Base`.
  - `Experiment.baseline_variant_id` kept as a **plain string**, not an FK, to avoid a
    circular FK between `experiments` and `variants`.
  - Parent→child relationships use `cascade="all, delete-orphan"` so deleting a Call/Lead
    removes its Turns/Decisions/KPI events (verified by test).
- **Schema bootstrap** via `app/db/session.py::init_db()` (idempotent `create_all`), plus
  `get_db()` session dependency and SQLite `check_same_thread=False`.
- **Deferred to P1-T3 (intentional):** the synthetic-vs-real label (§13.3) is a labeling
  concern, so it lands with the seed ticket rather than the bare §15 schema.
- **Lint note:** ruff `UP045` auto-rewrote `Optional[X]` → `X | None` (py310 target).
- **Validation:** `ruff check .` clean; `pytest` 4 passed (full call graph round-trip, JSON
  round-trip, experiment/variant relationship, cascade delete); `init_db()` smoke ok.

---

## P1-T3 — Seed data & synthetic/real labeling (2026-05-26)

- Added `is_synthetic` boolean to `Lead` and `Call` (PRD §13.3) so synthetic/seed/self-play
  data is cleanly separable from real production data downstream.
- **Seed leads** in `data/leads/seed_leads.json` cover the three PRD use cases:
  `seed-full-001` (full prior info, returning), `seed-partial-002` (subject/grade only),
  `seed-none-003` (effectively empty inbound). All flagged `is_synthetic: true`.
- **Decisions not specified in the PRD:**
  - Seed leads use **fixed `lead_id`s**, and `seed_leads()` upserts by id, so re-seeding is
    idempotent (verified by test).
  - **`data/` lives at the repo root** (not under `backend/`), matching the BUILD_PLAN file
    map (`data/leads`, `data/kb`, `data/personas`, `data/playbooks`). `seed.py` resolves it
    via `Path(__file__).parents[3]`.
  - **Transcript loader is a guarded stub** (`load_transcripts`): scans `data/transcripts/*.json`,
    skips any file not marked `pii_substituted: true`, returns `[]` when none present. Real
    transcripts "will be provided" per the PRD; format documented in
    `data/transcripts/README.md`.
- **Validation:** `ruff check .` clean; `pytest` 7 passed; `python -m app.db.seed` ran
  end-to-end ("Seeded 3 leads. Loaded 0 PII-substituted transcripts.").

---

### Phase 1 — Foundation & Data Layer: COMPLETE (2026-05-26)
All exit criteria met: app boots with `/health` + tests/lint; all §15 entities persist and
round-trip; seed leads (full/partial/none) loaded and labeled synthetic vs. real.
