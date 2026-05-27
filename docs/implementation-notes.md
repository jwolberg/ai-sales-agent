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

---

## P2-T1 — Realtime voice pipeline (2026-05-27)

- **Stack chosen (user decision):** Pipecat orchestrating Deepgram STT → Claude →
  Cartesia TTS over WebRTC, Silero VAD for turn-taking. Keeps reasoning in Claude, which
  matches the strategy (we own decisioning/observability). User supplies real keys.
- **Optional `voice` extra:** the realtime deps are heavy and native-build-prone, so they
  live in `pyproject.toml [voice]`, not core `dev`. Core app + tests stay light.
- **Verified the exact 0.0.108 import paths by introspection** before writing wiring
  (transport moved to `pipecat.transports.smallwebrtc.*`; greeting via `LLMRunFrame`;
  `get_answer()` returns `{sdp,type,pc_id}`).
- **Decisions not specified in the PRD:**
  - Default model `claude-sonnet-4-6` (override `ANTHROPIC_MODEL`; note `claude-haiku-4-5`
    for lower latency). Default Cartesia voice id is a sample, overridable.
  - **Lazy Pipecat import:** `app.main`/`app.voice.server` do not import Pipecat at module
    load (verified: not in `sys.modules` after importing `app.main`). It's imported inside
    the `/voice/offer` handler, so the core app runs without the `voice` extra.
  - **Key-gating:** `/voice/offer` returns `503` listing missing keys; `/voice/status`
    reports readiness for the demo client.
  - First-turn greeting: seed a single user cue + `LLMRunFrame` so the agent speaks first
    (Anthropic requires a user turn to respond to).
  - Placeholder persona in `pipeline.py`; full persona/decisioning deferred to P2-T3/T4.
  - `allow_interruptions=True` set now as the **barge-in foundation**; formal barge-in
    tuning/verification is P2-T2.
- **Install gotcha (documented in RUNBOOK):** pip resolved an old `llvmlite` with no wheel
  and tried to build from source (no LLVM here). Fix: `pip install --only-binary=:all:
  "llvmlite>=0.43" numba` first, then the extra. Installed clean as 0.0.108.
- **TODO / follow-up:** Pipecat deprecation warnings — `model=`/`voice_id=` kwargs and
  `AnthropicLLMContext`/`create_context_aggregator` are deprecated for a universal
  `LLMContext`. Kept the working (deprecated) API for now and **pinned `pipecat-ai<0.1`**
  so a future release can't remove it unexpectedly. Migrate to `LLMContext` during a
  live-validated ticket (P2-T2/T4), since the new message format can't be verified here.
- **Validation:** `ruff` clean; `pytest` 9 passed (incl. real Pipecat construction smoke
  via `importorskip`); TestClient smoke confirms `/health`, `/voice/status` (3 missing
  keys), `/voice/offer` 503, and no eager Pipecat import.
- **NOT validated here (environment limits):** an end-to-end live call needs a browser +
  microphone + real keys. Wiring/construction is validated; live audio + barge-in must be
  run from the RUNBOOK on a provisioned machine.

---

## Config split: secrets vs. tunables (2026-05-27)

- Moved non-secret tunables (`anthropic_model`, `cartesia_voice_id`) out of `.env` into a
  committed **`backend/config.toml`**. Secrets (API keys) stay in `.env` (gitignored).
- Wired via pydantic-settings `TomlConfigSettingsSource`; precedence high→low:
  init args > env vars > `.env` > `config.toml` > code defaults. So an env var still
  overrides the TOML for one-off changes.
- Declared `tomli>=2.0; python_version < "3.11"` as a core dep (stdlib `tomllib` is 3.11+;
  core config now parses TOML).
- **Incident note:** while updating the voice id earlier, a `sed -i ''` on `backend/.env`
  (BSD sed) truncated the file to 0 bytes in this sandbox and the keys were lost (re-added
  by the user). Lesson: never edit the secrets file with in-place `sed` here — use
  filter-to-temp-then-`mv`, or the Edit tool, and re-verify keys after.
- **Validation:** `ruff` clean; `pytest` 9 passed; `Settings()` loads all three keys plus
  model/voice from `config.toml`.

---

## docs/AGENT_FLOW.md — conversation flow mockup (2026-05-27)

- Added `docs/AGENT_FLOW.md` as a discussion artifact ahead of the orchestrator. Captures
  the two-layer model (sales progression vs. human conversation) and the logging contract
  agreed in discussion, which then drove the P2-T3 enums:
  - **Stages** = PRD §17's 11 values → logged `Decision.stage`.
  - **`selected_action`** = PRD §9.5 DE-1's 10 sales actions only.
  - **Modifiers** = a *separate, optional* dimension (rapport/clarify/reassure/banter/
    bridge_back/time_filler), used during ambiguous/non-progressing turns; does not change
    the stage. **Open:** `Decision` has no `modifier` column yet — proposed nullable String.
- **Open gap (deferred):** DE-1 has no "greet"/"confirm context" action; `context_confirmation`
  currently borrows `ask_required_discovery`. Decide whether to add `confirm_context` later.

---

## P2-T3 — Orchestrator skeleton + consistent persona (2026-05-27)

- **Deviation from plan order:** built P2-T3 before P2-T2 (barge-in). Rationale: per the
  BUILD_PLAN note, barge-in can only be *validated* with a live browser/mic/keys run
  (`allow_interruptions=True` is already set), so there is nothing build-and-test-able there
  right now. P2-T3 is pure, unit-testable logic and unblocks P2-T4/P3. P2-T2 remains Todo,
  to be exercised during a live-validation pass.
- **New `app/agent/` layer**, transport-agnostic so the voice pipeline (Phase 2) and the
  simulator (Phase 6) share it:
  - `stages.py` — `Stage`/`Action`/`Modifier` as `str` enums (values match AGENT_FLOW), so
    they serialize straight into the `Decision` string columns.
  - `persona.py` — moved `build_system_prompt`/`build_greeting_cue` here from
    `voice/pipeline.py` (single source of truth; pipeline now re-exports them for backward
    compatibility). Added `stage_directive(stage)` for per-stage guidance, surfaced into
    generation in a later ticket.
  - `orchestrator.py` — `NextAction` (mirrors the DE-2 trace fields exactly), mutable
    `ConversationState`, a `NextActionDecider` Protocol (the pluggable interface), a trivial
    `StubDecider` (linear happy-path off turn count), and `Orchestrator` (builds the persona
    **once** for consistency = VC-4; `open()` → greeting, `on_user_turn()` → next action).
- **Stub is deliberately dumb:** no real intent/objection/KB detection — those are P3-T3/P4.
  It advances on a turn count (`_STUB_DISCOVERY_TURNS = 3`) purely so the loop and trace are
  demonstrable. To be replaced wholesale, not extended.
- **Modifier demo:** the stub attaches `Modifier.RAPPORT` to the first discovery turn to
  exercise the (stage-independent) modifier channel.
- **Validation:** `ruff` clean; `pytest` 13 passed (7 new orchestrator tests + existing
  health/models/voice-construction tests still green, confirming the persona move is
  non-breaking).

---

## P2-T1 follow-up — live-audio fix + voice debug instrumentation (2026-05-27)

- Committing in-flight pipeline work that predated the P2-T3 session (had been sitting
  uncommitted in the working tree).
- **Root fix (live audio):** Deepgram with `linear16` needs an explicit sample rate. Relying
  on Pipecat pipeline propagation left it `None`, which serializes to the string `"None"` and
  Deepgram rejects with HTTP 400. Now set explicitly (`AUDIO_IN_SAMPLE_RATE = 16000`) on the
  STT service, the transport params, and `PipelineParams.audio_in_sample_rate`; the transport
  resamples the browser's 48 kHz WebRTC audio down to it.
- **Debug instrumentation (gated):** new `voice_debug` setting (`config.py` default `False`,
  `config.toml`). When on: `DebugTurnLogger` traces the inbound path (audio arrival → VAD →
  interim/final transcript) at two pipeline points, `configure_debug_logging()` quiets
  Pipecat's INFO flood to warnings + our `app` markers, and `client.js` logs WebRTC
  connection/ICE state + mic track status. **Default committed `voice_debug = false`** (per
  user) so logging is off unless explicitly enabled.
- **Persona move rode along:** `pipeline.py` also picks up the P2-T3 change (imports
  `build_system_prompt`/`build_greeting_cue` from `app.agent.persona`, re-exported via
  `__all__`) since the two edits were entangled in the same file.
- **Persona identity:** committed `agent_name = "Jay"`, `company_name = "Nerdy"` as-is
  (per user).
- **NOT validated here:** the sample-rate fix targets a real live-audio bug; construction
  tests pass, but confirming audio actually flows still needs a browser/mic/keys run (RUNBOOK).
- **Validation:** `ruff` clean on `app`; `pytest` 16 passed (incl. Pipecat construction smoke).

---

## P2-T1 follow-up #2 — Deepgram language serialization fix (2026-05-27)

- **Symptom (live run):** agent greeted fine but never responded to speech. Debug log showed
  audio arriving + VAD firing, then a flood of `DeepgramSTTService: Connection lost ...
  status_code: 400, body: Unexpected error when initializing websocket connection` — no STT
  output, so Claude had nothing to answer.
- **Diagnosis (live, against Deepgram):** key valid (REST 200) and a *raw* websocket handshake
  with our params was accepted, so it wasn't auth, the key, or the sample-rate fix. Dumping
  pipecat's actual `_build_connect_kwargs()` revealed two bad params:
  1. `language='Language.EN'` — pipecat 0.0.108 serializes the default `Language` *enum* with
     `str()` (giving "Language.EN") instead of `.value` ("en"). Deepgram 400s on it. Settings
     coerces any string back to the enum, so passing `language="en-US"` doesn't help.
  2. `sample_rate='0'` — the connect reads the pipeline-negotiated rate, which can be 0 if not
     yet propagated.
  Bisecting via the Deepgram SDK proved **both** must be valid; with `language='en'` +
  `sample_rate='16000'` the handshake connects.
- **Fix:** thin `_DeepgramSTTService` subclass in `voice/pipeline.py` overriding
  `_build_connect_kwargs()` to (a) re-serialize the language enum's `.value` and (b) pin
  `sample_rate` to `AUDIO_IN_SAMPLE_RATE` when it's 0/None. Contained workaround for a pipecat
  0.0.108 bug; tied to that pinned version (`pipecat-ai>=0.0.108,<0.1`).
- **Validated LIVE (browser + mic + keys):** debug log now shows `✅ STT final: '...'`
  transcripts and **zero** Deepgram 400s; the agent responds to speech.
- **Security:** pipecat's retry warning logs the full `Authorization: Token <key>` header on
  every failure — the earlier debug log captured the Deepgram key in plaintext. That log was
  scrubbed; consider rotating the key. (`voice_debug` stays off by default partly for this.)
- **Validation:** `ruff` clean on `app`; `pytest` 16 passed.

---

## P2-T4 — transcript & call-record capture (2026-05-27)

- **`app/agent/recorder.py` `CallRecorder`:** owns one `Call` row (created + flushed on
  construction for an immediate `call_id`), appends `Turn` rows via `record_agent` /
  `record_prospect` / `record_turn`, and finalizes with `end(outcome=, summary=)` (stamps
  `ended_at`). Speaker and outcome constants live here so KPI rollups (P5) can rely on them.
- **Commit-per-turn:** turns are committed as they happen (not batched) so a transcript
  survives a mid-call crash — observability is the point. Negligible cost at call cadence.
- **Kept the Orchestrator pure:** the recorder is a *separate* object; the Orchestrator
  takes it as an **optional** collaborator (`recorder=None` default). With it set,
  `on_user_turn` records the prospect turn and `record_agent_turn` / `end` persist the rest;
  without it, the orchestrator does zero DB work (existing decider tests untouched). This is
  the same seam the live pipeline and the simulator (P6) will use.
- **Deviation / scope note:** the ticket's stated files were `orchestrator.py` + the test, so
  this delivers the *capture capability* + integration, validated in text mode. Wiring it
  into the **live Pipecat frame path** (taps `TranscriptionFrame` for prospect turns and the
  TTS/LLM output for agent turns, with a DB session per `run_bot` call) is **not done** —
  tracked as a follow-up for when the orchestrator is wired into `run_bot`. Chose not to
  expand into the live frame layer here (can't unit-validate; overlaps P3 wiring).
- **Validation:** `ruff` clean; `pytest` 20 passed (4 new transcript tests: ordered
  transcript round-trip, synthetic flag, orchestrator-driven recording, and no-recorder =
  no DB writes).

---

## P3-T1 — lead profile loading & cross-call memory (2026-05-27)

- **`app/memory/lead_store.py`:** `LeadStore(session)` with `load` / `get_or_create` and
  `apply_call_outcome` (the LM-4 cross-call write: merges newly collected profile fields,
  de-dupes appended objections, sets `prior_summary` and `status`). Plus pure field-state
  helpers — `known_fields`, `missing_required`, `info_level` — that accept a Lead *or* a dict
  so the DB-free orchestrator can reuse them.
- **Field sets:** `PROFILE_FIELDS` = the LM-1 discoverable profile; `REQUIRED_FIELDS` =
  the DF-1 minimum (who / subject / grade) that gates discovery. `info_level` →
  full/partial/none maps exactly onto Use Cases 1–3 (verified against the three seed leads).
- **Orchestrator:** now accepts `known_fields` + `lead_id`, seeds `state.collected_fields`,
  and exposes `missing_required_fields()` (skip-known foundation for P3-T2/T3). Stays DB-free.
- **Decision — no schema change:** LM-4 lists "buying signals" and "disqualification signals"
  to persist, but `Lead` has no columns for them and there's no migration framework (SQLite
  `create_all`). Mapped them onto the existing `status` (next-step/lifecycle) + `prior_summary`
  rather than alter the schema mid-project. Agent version / variant (also in LM-4) already
  live on `Call` and are P5-T2's job. Dedicated signal columns can come with a future
  migration ticket if needed.
- **Validation:** `ruff` clean; `pytest` 26 passed (6 new: info-level vs use cases, unknown
  lead, get_or_create, carry-forward across calls, objection de-dup / empty-skip, orchestrator
  seeding).
