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
