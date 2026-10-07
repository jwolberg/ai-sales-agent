# Dev Runbook

Setup and run instructions for the Autonomous AI Sales Agent backend on a local
development machine. Commands assume macOS/Linux with `zsh`/`bash`.

> Status: this covers what exists today (Phase 1 — backend scaffold, data layer, seed
> data). Later phases (voice, KB, dashboard, experiments) will extend this file. See
> `docs/BUILD_PLAN.md` for the current phase.

---

## 1. Prerequisites

- **Python 3.12** (pinned in `.python-version`; `python3.12 --version`). 3.13 is not supported:
  Pipecat's audio utils import `audioop`, which 3.13 removed.
- **git** with access to the repo (clone it, then run the steps below from the repo root)

No database server is required — the dev setup uses a local **SQLite** file.

## 2. Repo layout

```
ai-sales-agent/
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
python3.12 -m venv .venv

# Install the pinned dependency set, then the app itself in editable mode (no re-resolve).
# requirements/dev.txt = core + dev tools; use requirements/dev-voice.txt to include the voice extra.
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python -m pip install --no-deps -e .
```

Dependencies are pinned in `backend/requirements/*.txt` (pip-tools lockfiles compiled from
`pyproject.toml`). To add or bump a dependency, edit `pyproject.toml` and regenerate — see
`backend/requirements/README.md`.

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
| `ENVIRONMENT`   | `development`                  | Environment label; anything other than `development` makes auth fail closed |
| `DATABASE_URL`  | `sqlite:///./nerdy_sales.db`   | DB connection (swap for Postgres)|
| `LOG_LEVEL`     | `INFO`                         | Log verbosity                    |
| `DASHBOARD_USERNAME` | `operator`                | HTTP Basic user for the dashboard, `/api`, `/demo`, `/voice/offer` |
| `DASHBOARD_PASSWORD` | unset                     | HTTP Basic password. Unset = open in `development`, 503 everywhere else |
| `SMS_MAX_PER_CALL` | `3`                         | Payment-link texts per call (bot + dashboard combined); over → not texted / 429 |
| `SMS_MAX_PER_NUMBER_PER_HOUR` | `5`              | Texts to one destination number per rolling hour |
| `MAX_CONCURRENT_SESSIONS` | `3`                  | Live voice / Twilio / simulated calls at once; over → 429 (Twilio: socket closed 1013) |

**Operator auth.** Every route except `/health`, `/voice/twilio`, `/voice/twilio/ws`, and
`/payments/webhook` requires HTTP Basic credentials once `DASHBOARD_PASSWORD` is set (those four
authenticate by provider signature instead). Open `/dashboard` and the browser prompts once; its
API calls reuse the cached credentials. The Docker image sets `ENVIRONMENT=production`, so a
deployed container with no password refuses operator routes rather than serving them openly.

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
# {"status":"ok","version":"0.1.0"}
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

## 11. Voice demo (Phase 2 — P2-T1)

Realtime voice uses **Pipecat**: Deepgram (STT) → Claude (LLM) → Cartesia (TTS) over
WebRTC, with Silero VAD for turn-taking. These deps are heavy and live in an optional
`voice` extra, separate from the core dev setup.

### 11.1 Install the voice extra

```bash
cd backend
.venv/bin/python -m pip install -r requirements/dev-voice.txt
.venv/bin/python -m pip install --no-deps -e .
```

> `numba` is capped below 0.63 in `pyproject.toml`: newer numba needs llvmlite 0.46+, which ships
> no Intel-macOS wheels, so the install would try (and fail) to build llvmlite from source.

### 11.2 Add provider keys

Set these in `backend/.env` (see `.env.example`). Until all three are present,
`/voice/offer` returns `503` and the demo page tells you which keys are missing.

| Variable            | Provider | Notes                                   |
| ------------------- | -------- | --------------------------------------- |
| `DEEPGRAM_API_KEY`  | Deepgram | Speech-to-text                          |
| `ANTHROPIC_API_KEY` | Anthropic| Claude (the agent's reasoning/replies)  |
| `CARTESIA_API_KEY`  | Cartesia | Text-to-speech                          |

Non-secret tunables (`anthropic_model`, `cartesia_voice_id`) live in committed
**`backend/config.toml`**, not `.env`. Edit that file to change the model or voice; an
env var of the same name still overrides it if you need a one-off.

### 11.3 Run the demo

```bash
.venv/bin/uvicorn app.main:app --reload --port 8001
```

Open **http://localhost:8000/demo**, click **Call**, allow the microphone, and talk —
the agent greets you first. Check readiness any time at
`GET http://localhost:8000/voice/status`.

> A browser + microphone are required; the voice path can't be exercised headlessly.
> Construction/wiring is covered by `tests/test_voice_pipeline.py` (skips automatically
> when the `voice` extra isn't installed).

### 11.4 Tune turn-taking — "the agent jumps in too soon" (VAD-T1/T2)

When the caller turn ends is decided by Silero VAD, not the brain. The lever is
`vad_stop_secs` (config.toml / `Settings`): the trailing silence before the turn is
declared over. It defaults to **0.6s** (pipecat's own default is an aggressive 0.2s,
which trips on a normal mid-sentence breath). Raise it (0.8–1.2) if the agent still
interrupts; lower it (toward 0.3) for snappier turns.

Tune it offline first — no phone needed. Committed fixtures let you try it immediately
(`data/audio/vad_fixtures/`, see that dir's README), or record your own short clips of
yourself speaking *with natural pauses* (mid-sentence "um…", trailing "so…") as 16-bit WAV:

```bash
# canonical fixture (one utterance with a mid-sentence pause):
.venv/bin/python -m app.simulator.vad_replay \
  ../data/audio/vad_fixtures/midsentence_pause.wav --sweep 0.2,0.4,0.6,0.8,1.0
# or your own clip:
.venv/bin/python -m app.simulator.vad_replay path/to/clip.wav --sweep 0.2,0.4,0.6,0.8,1.0
```

On `midsentence_pause.wav` you'll see one caller turn shredded into ~6 turns at the aggressive
0.2 default (the agent would jump in repeatedly) and merge down to a single turn by 1.0 — the
dial doing its job. `disfluent_ums.wav` is even starker (10 → 1). See
`data/audio/vad_fixtures/` (README) for the full table and what each clip targets.

Each row prints how many turns that `stop_secs` produced. A clip that is *one* utterance
with pauses should yield **1 turn** — pick the smallest `stop_secs` that does, then set it
as `vad_stop_secs`. Too-low values split the utterance (the agent jumps in mid-thought);
too-high only adds latency. Confirm the final value with one live call.

> The harness runs the real Silero VAD but no STT/LLM/network. The timing logic is covered
> by `tests/test_vad_replay.py`; the speech-detection accuracy needs a real recorded clip.
> Tip: while tuning, set `fillers=false` so a premature endpoint isn't masked by the instant
> "Sure,…" filler — it makes early jump-ins easier to hear.
