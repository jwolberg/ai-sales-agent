# Autonomous AI Sales Agent

A real-time voice AI sales agent for tutoring sales (Nerdy / Varsity Tutors). It runs a full
discovery-to-close conversation — using known lead data and prior-call memory, asking only for
what's missing, answering policy/competitive questions from a grounded knowledge base, handling
objections, and deciding when to close or escalate — while capturing transcripts, per-turn
decision traces, and KPIs, and improving itself through a recursive experiment loop against
synthetic prospects.

> **Status:** MVP. Phases 1–7 complete; Phase 8 (hardening & docs) in progress. All evaluation
> evidence to date is synthetic self-play — no live human trials yet. KB pricing/policy content
> is placeholder, not approved Nerdy content. See `docs/limitations.md`.

## What it does

- **Live voice** (browser/WebRTC): Deepgram STT → Claude decisioning → Cartesia TTS, with VAD
  turn-taking and barge-in.
- **Decider-led runtime:** a transport-agnostic conversation engine routes each turn
  (escalation → objection → knowledge question → discovery/close), extracts fields, and renders
  a persona-consistent reply — the same engine drives both live calls and synthetic self-play.
- **Grounded answers:** retrieval over approved KB docs with source IDs; honest fallback when
  content is insufficient (no hallucinated policy/pricing).
- **Guardrails & escalation:** never invents pricing/guarantees, never claims to be human, always
  honors a human handoff, escalates high-risk asks.
- **Observability:** every call persists transcript, per-turn decision trace, KPI events, and
  version/variant attribution; a dashboard surfaces KPIs and per-call review.
- **Recursive improvement:** generate ≥2 price-rebuttal variants, test them against synthetic
  personas, score on objection-recovery + guardrail KPIs, and promote/retire on evidence.

## Architecture at a glance

- **Backend:** Python + FastAPI, SQLAlchemy ORM, SQLite (single file). `pytest` + `ruff`.
- **Voice:** Pipecat pipeline (Deepgram / Claude / Cartesia) over WebRTC; optional `voice` extra.
- **Knowledge base:** markdown chunker + dependency-free TF-IDF retriever with source IDs.
- **Simulator:** Claude-driven persona self-play through the real engine, writing the same
  records as live calls (labeled synthetic), scored deterministically + by an LLM-as-judge.
- **Dashboard:** static UI at `/dashboard` reading the backend API.

```
nerdy-sales/
├── backend/app/
│   ├── voice/        # Pipecat pipeline + bot (live voice path)
│   ├── agent/        # engine, router, extraction, render, decisioning, KB, objections, guardrails
│   ├── kb/           # ingestion + retriever
│   ├── memory/       # lead store + cross-call memory
│   ├── simulator/    # personas, self-play runner, scoring
│   ├── experiments/  # variants, experiment engine, evaluation/promotion
│   ├── kpis/         # event vocab + metric computation
│   ├── dashboard/    # API router
│   └── db/           # models, session, seed
├── data/             # leads, kb (placeholder), personas, playbooks, audio
├── frontend/         # demo + dashboard static clients
└── docs/             # PRD, build plan, decision log, research notes, limitations, runbook
```

## Quick start

Full instructions (prerequisites, voice extra, troubleshooting) are in **`docs/RUNBOOK.md`**.
Short version, from the repo root:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"   # core
.venv/bin/python -m app.db.seed               # create schema + seed sample leads
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Verify: `curl -s http://localhost:8000/health` and open the dashboard at
http://localhost:8000/dashboard.

### Voice demo (needs API keys)

```bash
.venv/bin/python -m pip install -e ".[voice]"
# add DEEPGRAM_API_KEY, ANTHROPIC_API_KEY, CARTESIA_API_KEY to backend/.env
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/demo, click **Call**, allow the mic, and talk — the agent greets you
first. A browser + microphone are required; the voice path can't be exercised headlessly.

### Run the recursive-improvement loop

```bash
cd backend
.venv/bin/python -m app.experiments --offline        # free no-LLM wiring smoke (fake 0% numbers)
.venv/bin/python -m app.experiments --name price-rebuttal-v1 \
    --report ../docs/recursive-improvement.md         # real run: ~60 Claude calls, needs a funded key
```

The real run tests the baseline + 5 price-rebuttal variants across 5 personas, scores them with
an LLM judge, applies the §8 promotion rule, and writes the before/after report.

## Validation

```bash
cd backend
.venv/bin/ruff check .          # lint
.venv/bin/python -m pytest -q   # tests (158 passing)
```

## Documentation

| Doc | What it covers |
| --- | --- |
| `docs/PRD.md` | Product requirements (the spec / source of truth) |
| `docs/BUILD_PLAN.md` | Phased build plan, ticket status, resume pointer |
| `docs/decision-log.md` | Major product/technical decisions and tradeoffs |
| `docs/research-notes.md` | Methodology, persona/KPI rationale, synthetic-eval caveats |
| `docs/limitations.md` | What was/wasn't tested; production requirements |
| `docs/recursive-improvement.md` | Measured before/after evidence from the improvement loop |
| `docs/failure-modes.md` | Failure catalog (pending live human trials) |
| `docs/RUNBOOK.md` | Detailed setup, voice extra, troubleshooting |
| `docs/implementation-notes.md` | Running, ticket-level decision/deviation log |
| `docs/QandA_opens.md` | Approved KB content still owed (pricing/refund/matching/etc.) |
