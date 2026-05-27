# Dev Runbook

Setup and run instructions for the Autonomous AI Sales Agent backend on a local
development machine. Commands assume macOS/Linux with `zsh`/`bash`.

> Status: this covers what exists today (Phase 1 — backend scaffold, data layer, seed
> data). Later phases (voice, KB, dashboard, experiments) will extend this file. See
> `docs/BUILD_PLAN.md` for the current phase.

---

## 1. Prerequisites

- **Python 3.10+** (`python3 --version`)
- **git** with SSH access to the repo (`ssh://git@git.example.com:22022/jwolberg/nerdy-sales.git`)

No database server is required — the dev setup uses a local **SQLite** file.

## 2. Repo layout

```
nerdy-sales/
├── backend/            # FastAPI app + data layer (the runnable service)
│   ├── app/
│   │   ├── main.py     # FastAPI app factory + /health
│   │   ├── config.py   # settings (env / .env)
│   │   └── db/         # models, session, seed
│   ├── tests/          # pytest suite
│   ├── pyproject.toml  # deps + ruff + pytest config
│   └── .env.example
├── data/               # seed leads, transcripts (and later: kb, personas, playbooks)
└── docs/               # PRD, build plan, strategy, runbook, implementation notes
```

All backend commands below are run **from the `backend/` directory** (the SQLite file
and `.env` are resolved relative to the current working directory).

## 3. One-time setup

```bash
cd backend

# Create an isolated virtualenv (lives at backend/.venv, gitignored)
python3 -m venv .venv

# Install the app plus dev tools (pytest, httpx, ruff) in editable mode
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

Optionally activate the venv so you can drop the `.venv/bin/` prefix:

```bash
source .venv/bin/activate   # then use: python, pytest, ruff, uvicorn directly
```

The examples below use the explicit `.venv/bin/...` form so they work with or without
activation.

## 4. Configuration

Settings load from the environment, with safe development defaults — a `.env` file is
**optional**. To customize:

```bash
cp .env.example .env        # then edit values
```

| Variable        | Default                        | Purpose                          |
| --------------- | ------------------------------ | -------------------------------- |
| `APP_NAME`      | `Autonomous AI Sales Agent`    | Display name in `/health`, docs  |
| `ENVIRONMENT`   | `development`                  | Environment label                |
| `DATABASE_URL`  | `sqlite:///./nerdy_sales.db`   | DB connection (swap for Postgres)|
| `LOG_LEVEL`     | `INFO`                         | Log verbosity                    |

## 5. Initialize and seed the database

Creates the SQLite schema and loads the sample leads (full / partial / no-info cases),
then reports any PII-substituted transcripts found in `data/transcripts/`:

```bash
.venv/bin/python -m app.db.seed
# -> Seeded 3 leads. Loaded 0 PII-substituted transcripts.
```

Seeding is **idempotent** — re-running updates the existing seed leads rather than
duplicating them. The DB file (`backend/nerdy_sales.db`) is gitignored; delete it to
reset from scratch.

## 6. Run the server

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- `--reload` restarts on code changes (dev only).
- API docs (Swagger UI): http://localhost:8000/docs

## 7. Verify it's up

```bash
curl -s http://localhost:8000/health
# {"status":"ok","app":"Autonomous AI Sales Agent","version":"0.1.0","environment":"development"}
```

## 8. Validation (run before every commit)

Per project rules (`.claude/CLAUDE.md`), run lint and tests before committing:

```bash
cd backend
.venv/bin/ruff check .          # lint  (add --fix to auto-fix)
.venv/bin/python -m pytest -q   # tests
```

## 9. Git workflow

- **Commit per ticket**, referencing the ticket id (e.g. `P1-T2: ...`); don't batch tickets.
- Run lint + tests **before** each commit.
- Append a dated entry to `docs/implementation-notes.md` for any decision, deviation, or
  tradeoff.
- **Do not push** unless asked. `main` is protected.

```bash
git add -A
git commit -m "P<phase>-T<ticket>: <summary>"
# push only when explicitly requested:
git push origin main
```

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: app` | Run from `backend/`, and ensure `pip install -e ".[dev]"` completed. |
| `no such table` errors | Run `python -m app.db.seed` (or `init_db()`) to create the schema. |
| Want a clean DB | `rm backend/nerdy_sales.db` then re-seed. |
| `zsh: no matches found: .[dev]` | Quote the extras: `pip install -e ".[dev]"`. |
| Port already in use | Run uvicorn with a different `--port`. |

## 11. Not yet wired (coming in later phases)

The realtime voice pipeline (Phase 2) will require a voice stack and API keys
(e.g. STT/TTS providers and an LLM key). Those env vars will be added to `.env.example`
and documented here when that ticket lands.
