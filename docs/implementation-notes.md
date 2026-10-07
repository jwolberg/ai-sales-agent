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

---

## P3-T2 — discovery question set & skip-known (2026-05-27)

- **`data/playbooks/discovery.yaml`:** 10 required questions (DF-1) + 8 leading (DF-2), each
  with a `key` (collected-fields slot), spoken `prompt`, and optional `confirm` template
  (LM-3: confirm a known value instead of re-asking). List order = default ask priority.
- **`app/agent/discovery.py`:** `DiscoveryPlaybook` with `next_question` (fills required gaps
  first, then leading; `None` when done), `missing_required` (LM-2), `known_required` (LM-3),
  and `Question.confirm_prompt`. `get_discovery_playbook()` parses the YAML once (`lru_cache`).
- **New dep:** declared `pyyaml>=6.0` as a **core** dependency (was only transitively present
  via the voice extra). Playbooks are YAML per the build plan and reused by P4-T3 (objections)
  and P6 (personas), so the format earns the dep. Already installed — no reinstall needed.
- **Two field vocabularies, intentionally distinct:** lead_store's `REQUIRED_FIELDS` (3, for
  `info_level` gating) vs. the playbook's 10 required questions (for question selection). Some
  playbook keys (`challenge`, `prior_tutoring`, `readiness`, all leading keys) have no `Lead`
  column — they live in `collected_fields` and only the `PROFILE_FIELDS` subset is persisted by
  `apply_call_outcome`. Kept separate rather than forcing one list to serve both jobs.
- **Scope:** playbook + selection primitives only; wiring into the orchestrator's `next_action`
  with signal-aware dynamic ordering (DF-3) is P3-T3.
- **Validation:** `ruff` clean; `pytest` 33 passed (7 new).

---

## P3-T3 — dynamic next-question selection (2026-05-27)

- **`app/agent/decisioning.py` `DiscoveryDecider`** (a `NextActionDecider`): confirm known
  context once (LM-3) → fill the highest-priority missing required field → explore leading
  questions → `SUMMARIZE_FIT` when discovery is exhausted. Drives Use Cases 1–3 from the lead's
  seeded `collected_fields`.
- **Extended `NextAction`** with `question_key` + `prompt` (the chosen question's words) and
  added `ConversationState.context_confirmed`; the orchestrator flips that flag the first time
  it returns a `CONTEXT_CONFIRMATION` stage, so confirmation happens once, not every turn.
- **Avoided a circular import:** kept `NextAction`/`ConversationState`/`NextActionDecider` in
  `orchestrator.py`; `decisioning.py` imports them one-way. So the **orchestrator default stays
  `StubDecider`** and `DiscoveryDecider` is opt-in via the pluggable interface (drivers/sim pass
  it). Avoided changing the default to dodge both the cycle and churn to the P2-T3 stub tests.
- **DF-3 partial by design:** emotional state / buying signals / objections are listed inputs
  but their detection is Phase 4, so they're not yet weighted. **DF-4** (non-checklist phrasing)
  is the LLM layer's job — this module picks *what* to ask via the playbook prompt, not the
  exact wording. **Field extraction** (turning a user's answer into `collected_fields` values)
  is also not here — it's LLM/NLU work for later; tests update `collected_fields` directly.
- **Validation:** `ruff` clean; `pytest` 39 passed (6 new: no-info start, confirm-known,
  post-confirm probing, skip-known advance, leading→fit, orchestrator confirm-once).

---

## P3-T4 — fit summary, close attempt & close logging (2026-05-27) — Phase 3 complete

- **`app/agent/closing.py`** (pure): `assess_close_criteria` (DE-3 → ready + unmet reasons),
  `build_fit_summary` (CF-1 templated from known fields), `choose_close` + `next_step_prompt`
  (CF-2: close type matched to readiness → one of 5 next steps), and the `CloseAttempt` record.
- **DiscoveryDecider close flow:** once required discovery is complete it assesses DE-3 — if
  ready, `SUMMARIZE_FIT` then `ATTEMPT_CLOSE` (carrying the recommended next step); if not, it
  keeps developing need via leading questions, then summarizes, then `PIVOT_TOWARD_CLOSE`.
  Added `ConversationState.fit_summarized` (orchestrator flips it on `FIT_SUMMARY`, mirroring
  `context_confirmed`) plus `buying_intent` / `open_high_risk_objection` signal flags.
- **CF-3 logging via KPIEvent:** `CallRecorder.record_close_attempt` writes a
  `close_attempt` KPIEvent with close_type / next_step / objection_state / user_response /
  outcome; `created_at` is the timing. Chose KPIEvent (vs. extending Decision) because it
  already has a JSON metadata column and seeds P5-T3's KPI work — noted the slight overlap.
- **Signals are flags, not detection:** `buying_intent` / `open_high_risk_objection` are set by
  a driver/test for now; real intent & objection detection is Phase 4 (then DiscoveryDecider's
  close gate becomes fully signal-driven). The earlier P3-T3 leading→fit test still passes
  because with `buying_intent=False` the decider develops need before summarizing.
- **Validation:** `ruff` clean; `pytest` 46 passed (7 new: criteria ready/unmet, fit summary,
  close-type selection, summarize→close flow, pivot-when-unmet, CF-3 KPIEvent logging).
- **Phase 3 exit criteria met:** follow-up calls continue from prior context (lead_store),
  required fields collected when missing / known skipped or confirmed (discovery + decisioning),
  and a fit summary + close attempt are produced and logged (closing + recorder).

---

## P4-T1 — KB ingestion & retrieval (2026-05-27)

- **`app/kb/ingest.py`:** loads `data/kb/*.md`, strips HTML comments, and chunks at `##`
  headings into `KBChunk`s tagged with source file + section title (KB-3 source attribution).
- **`app/kb/retriever.py`:** `KBRetriever` — a dependency-free **TF-IDF** lexical retriever
  with stopword filtering and length normalization; `retrieve(query, k, min_score)` returns
  scored `RetrievedChunk`s, best first. `get_retriever()` builds it once (`lru_cache`).
- **Tradeoff — lexical, not vector:** the PRD *suggests* a vector store but doesn't mandate
  one. Chose TF-IDF to avoid an embedding model/API (cost, latency, a heavy dep like
  torch/sentence-transformers) and to keep retrieval deterministic for tests. Fine for a small
  approved-doc set; documented as swappable if recall needs it.
- **Content gap flagged (per user request):** the 5 KB docs are **safe PLACEHOLDERS**, not
  approved Nerdy content — they describe offerings generally and defer all specifics (pricing,
  refunds, guarantees, re-match) to a human, which also enforces §18. Created
  `docs/QandA_opens.md` listing exactly what approved copy the user must provide, by file and
  priority. `min_score` is the hook P4-T2 uses for the KB-4 no-hallucination fallback.
- **Validation:** `ruff` clean; `pytest` 51 passed (5 new: chunking+sources, relevant-source
  retrieval, topic ranking, empty-on-no-signal, min_score filtering).

---

## P4-T2 — grounded answer action + no-hallucination fallback (2026-05-27)

- **`app/agent/knowledge.py`:** `answer_question` retrieves with a `min_score` gate; above it
  returns a `GroundedAnswer` (snippets + unique sources, best-first), below it returns an honest
  fallback offering to clarify/escalate (KB-4). `grounding_prompt` builds the phrasing-layer
  instruction that says to answer from the retrieved material ONLY. `is_knowledge_question` is a
  cheap routing heuristic.
- **`min_score = 0.45`:** calibrated against the placeholder corpus — relevant queries scored
  ~0.53–1.34, nonsense ~0.37, off-topic none. Documented as corpus-tuned; revisit with real KB.
- **Wired as an orchestrator action:** `Orchestrator.answer_knowledge(question)` →
  `ANSWER_KNOWLEDGE` NextAction. Added `NextAction.kb_sources` (maps to `Decision.kb_sources_used`,
  KB-3); grounded answers carry the retrieved material in `prompt` for the LLM, fallback carries
  the honest deferral and claims no sources.
- **Scope:** routing (deciding a turn is a question vs a discovery answer) is provided as a
  heuristic but not yet wired into `on_user_turn`'s main loop — that integration rides with the
  larger orchestrator/live-pipeline wiring. Kept the loop stable.
- **Validation:** `ruff` clean; `pytest` 57 passed (6 new: grounded snippets+sources, honest
  fallback, grounding-prompt material-only, question heuristic, orchestrator grounded + fallback).

---

## P4-T3 — objection handling (≥3 types) via playbook + KB (2026-05-27)

- **`data/playbooks/objections.yaml`:** 6 objection types (price [§8 BASELINE], discount,
  spouse, comparison, tutor_quality, tried_before), each with detection `cues`, a `high_risk`
  flag, an approved `rebuttal`, and optional `kb_query`. Rebuttals are PLACEHOLDER and avoid
  inventing prices/guarantees.
- **`app/agent/objections.py`:** `ObjectionPlaybook.detect` (first cue match in playbook order),
  `baseline_price`, and `respond_to_objection` which returns the rebuttal + KB sources (grounds
  supporting detail by reusing P4-T2's `answer_question`). YAML-folded rebuttal whitespace is
  normalized on load.
- **Wired:** `Orchestrator.handle_objection(text)` → HANDLE_OBJECTION NextAction; a high-risk
  objection (discount = unauthorized concession, DE-4) sets `open_high_risk_objection`, which
  the close gate already respects — so a discount request now *holds the close* until resolved.
  Nice cross-ticket integration (P3-T4 gate + P4-T3 detection).
- **Scope:** objection *detection* is cue-based (deterministic, testable); richer intent
  detection and clearing the high-risk flag once resolved are future. Buying-intent detection
  is still external. Routing into the live loop rides with the larger orchestrator wiring.
- **Validation:** `ruff` clean; `pytest` 64 passed (7 new: coverage+baseline, phrase detection,
  high-risk flagging, KB-grounded rebuttal, orchestrator handling, close-held-by-objection,
  folded-whitespace load).

---

## P4-T4 — guardrails & escalation criteria (2026-05-27) — Phase 4 complete

- **`app/agent/guardrails.py`** (deterministic, cue-based): `detect_escalation` covers the DE-4
  triggers (human request, price concession, legal/safety/privacy, payment, anger/confusion) in
  priority order, plus a low-confidence trigger that ties KB-4 fallbacks (confidence 0.3) to a
  handoff via `DEFAULT_CONFIDENCE_THRESHOLD = 0.35`. `should_stop_selling` detects a clear
  refusal (§18 stop-pushing). `check_agent_output` is a last-line net flagging claims-to-be-human,
  unapproved price figures, and guarantee promises.
- **Wired:** `Orchestrator.check_escalation(text, confidence=)` → ESCALATE NextAction with
  `escalation_risk="high"` (new `NextAction.escalation_risk`, maps to `Decision.escalation_risk`);
  `Orchestrator.should_stop_selling`; `CallRecorder.record_escalation` logs an `escalation`
  KPIEvent (mirrors close-attempt logging).
- **Cue-tuning note:** human-request detection uses `"a human"` (not bare `"human"`, which would
  false-positive on "humanities"); the space-bearing cue stays safe. Guardrails err toward
  catching too much.
- **Scope:** `check_agent_output` is a tested utility; enforcing it on live LLM output (a
  post-generation filter in the pipeline) rides with the live-wiring work. Escalation/refusal
  checks are exposed as orchestrator methods a driver calls each turn.
- **Validation:** `ruff` clean; `pytest` 72 passed (8 new: each trigger, low-confidence,
  priority, stop-on-refusal, output flags, orchestrator escalate, escalation logging).
- **Phase 4 exit criteria met:** grounded answers with source tracking; honest fallback when KB
  is insufficient; 6 objection types incl. the price baseline; guardrails + escalation enforced.

---

## P4.5-T1 — turn router (2026-05-27)

- **`app/agent/router.py` `classify_turn(text) → RouteDecision`:** strict-priority pure classifier
  — escalate (DE-4) > stop-selling (refusal, §18) > objection > knowledge question > progress —
  reusing the existing detectors (`detect_escalation`, `should_stop_selling`,
  `ObjectionPlaybook.detect`, `is_knowledge_question`). Returns the route + reason + a `detail`
  (escalation code / objection key) the engine will dispatch on. No DB, no capability execution.
- **Deliberate routing decisions (documented in the module):**
  - **Discount vs "too expensive":** a concession demand ("discount", "lower the price") trips the
    DE-4 escalation cue → ESCALATE; a value objection ("it's too expensive") → OBJECTION → the §8
    price-baseline rebuttal. Falls out of the existing cue sets and matches the spec. (Trade-off:
    the discount *objection* rebuttal is now unreachable via the router — escalation wins; a
    stateful "rebut once, escalate on repeat" version could revisit this later.)
  - **Objection > knowledge:** "how do I know the tutor will be good?" is both a question and the
    tutor_quality objection → handled as the objection.
  - **Confidence escalation is NOT here:** escalating because a downstream step was low-confidence
    is the engine's post-decision job (P4.5-T4), so a clear turn never escalates spuriously.
- **Validation:** `ruff` clean; `pytest` 80 passed (8 new: escalation priority, discount/expensive
  split, refusal, objection keys, objection>question, plain question, discovery→progress, strict
  priority).

---

## P4.5-T2 — field & intent extraction (2026-05-27)

- **`app/agent/extraction.py`:** `Extractor` protocol + `RuleBasedExtractor` returning an
  `Extraction(fields, buying_intent, disqualified, understood)`. Slot-fills the **pending**
  question with the (lightly cleaned) utterance, detects committal buying cues and
  disqualification cues, and sets `understood=False` for non-answers / questions-back so the
  engine can clarify (LM-2). `get_extractor()` returns the default.
- **Deliberately deterministic v1 (no LLM):** keeps it cheap and unit-testable. Two known
  coarsenesses, documented: (1) the slot value is the stored utterance, not a parsed token
  ("She's in 8th grade" rather than "8th grade") — fine for skip-known truthiness and for weaving
  into confirmations; (2) buying cues are *committal phrases* only, so "how do I get started?"
  (a question) doesn't false-trigger. The `Extractor` protocol lets an LLM structured extractor
  replace it later without touching the engine.
- **Not wired yet:** the engine (P4.5-T4) merges `Extraction.fields` into `state.collected_fields`
  and sets `state.buying_intent`; routing decides when extraction applies (PROGRESS turns).
- **Validation:** `ruff` clean; `pytest` 89 passed (9 new: protocol, slot-fill, short answer,
  non-answer→clarify, question-back, no-pending, buying intent (and not-on-question),
  disqualification, answer+intent combined).

---

## P4.5-T3 — directive + render step (2026-05-27)

- **Insight that simplified it:** the `NextAction.prompt` overload is narrow — every capability
  already emits *final words* in `prompt` **except** a grounded KB answer, where `prompt` is an
  LLM *instruction*. So `Directive` only needs two kinds: **SPEAK** (final words) and **GROUND**
  (LLM-synthesize-or-fallback).
- **`app/agent/render.py`:** `Directive(intent, kind, text|instruction|fallback, sources, style)`,
  `to_directive(NextAction)` (grounded ANSWER_KNOWLEDGE → GROUND; everything else incl. the KB-4
  fallback → SPEAK), and `render(directive, synthesize=None)` — returns SPEAK text directly;
  for GROUND calls the injected `synthesize` (the LLM, present live) or degrades to the honest
  KB-4 fallback rather than guessing. `render` is the single place words are produced → pure for
  SPEAK, deterministic-fallback for GROUND-without-LLM, which is what makes it cacheable (P4.5-T6).
- **Didn't refactor the capabilities** to emit Directives directly (kept `prompt`); `to_directive`
  adapts at the boundary. The grounded GROUND instruction reuses the already-built `grounding_prompt`
  (snippets baked in) via `prompt`, so no re-retrieval. A future cleanup could have capabilities
  emit Directives natively.
- **Deferred:** LLM *smoothing* of SPEAK text (rendering an authored question more naturally with
  context, DF-4) — render returns SPEAK verbatim for now; smoothing is an opt-in enhancement.
- **Validation:** `ruff` clean; `pytest` 94 passed (5 new: discovery SPEAK, grounded GROUND
  synth+fallback, KB fallback is SPEAK, objection/escalation render, render purity).

---

## P4.5-T4 — conversation engine (2026-05-27)

- **`app/agent/engine.py` `ConversationEngine`** wraps an `Orchestrator` (state + persona +
  recorder + capabilities) and owns the per-turn loop: `run_turn(text)` → record prospect →
  extract & fold into state → `classify_turn` → dispatch (escalate→`check_escalation`,
  stop→graceful end, objection→`handle_objection`, knowledge→`answer_knowledge`, unclear PROGRESS→
  `_clarify`, else→decider) → advance state (stage/flags/`pending_field`) → `render` → record
  decision + agent turn. `open()` greets. `synthesize` (the LLM) is injected for GROUND; omitted
  in text mode (GROUND → KB-4 fallback). Returns a `TurnResult`.
- **Added** `recorder.record_decision(NextAction)` (DE-2 trace row; TYPE_CHECKING import to dodge
  the cycle) and `ConversationState.pending_field` / `disqualified`.
- **Known limitations (rule-based v1, to revisit with the LLM extractor / live wiring):**
  - **Only the pending slot is filled** — info volunteered before the agent asks (e.g. "it's for
    my son" right after the greeting) is *not* captured, so the decider may re-ask. The LLM
    extractor (P4.5-T2 successor) fixes this by extracting all fields from any utterance.
  - **Context-confirm after first field:** once the first field is learned the decider does a
    one-time CONTEXT_CONFIRMATION (it sees a "known" field) — a minor UX wrinkle, fires once.
  - Engine duplicates a little flag-flipping that `Orchestrator.on_user_turn` also does; the
    engine is the real loop now (on_user_turn kept for the older P2-T3 tests).
- **Validation:** `ruff` clean; `pytest` 101 passed (7 new: greet, progress+extract, clarify,
  objection, escalation, knowledge synth, full discovery→close with persisted turns + decisions).

---

## P4.5-T2 upgrade — LLM structured extractor (2026-05-27)

- **Chosen before live wiring** (per user) so a real call doesn't re-ask volunteered info.
  Added `LLMExtractor` in `extraction.py` (built via the `claude-api` skill): one Claude call per
  turn using **structured output** (`client.messages.parse(output_format=ExtractionPayload)`).
  Returns the pending answer + a list of *other* fields the caller volunteered + buying/
  disqualification signals + `understood`. Same `Extractor` protocol → drop-in for the engine.
- **Model = configured `anthropic_model` (sonnet-4-6), not the skill's opus-4-7 default.**
  Deliberate: extraction runs in the latency-critical per-turn voice loop, and the project
  explicitly configured sonnet for that reason. Documented the deviation; overridable via param.
- **Prompt caching** on the system prompt (`cache_control: ephemeral`); it lists the allowed
  field keys. (The prompt is currently short so caching may not engage until it grows — correct
  practice regardless.) Unknown field keys returned by the model are dropped against
  `allowed_fields()` (discovery playbook keys + lead profile fields).
- **Offline-testable:** the Anthropic client is injected (tests use a fake; 7 tests, no API).
  `anthropic` is lazy-imported so core stays light. **Live smoke test passed** (anthropic 0.104.1,
  sonnet-4-6): "it's for my daughter Mia, she's in 8th grade, struggling with algebra" →
  `{relationship_to_student: parent, student_name: Mia, grade_level: 8th grade, subject: algebra,
  challenge: ...}` from a single turn — the capability rule-based lacked.
- **`get_extractor()` default stays rule-based** (offline/deterministic for sim + tests); the
  live pipeline (P4.5-T5) opts into `LLMExtractor` explicitly.
- **Validation:** `ruff` clean; `pytest` 108 passed (7 new) + a live smoke call.

---

## P4.5-T5 — live voice wiring (decider-led runtime) (2026-05-27)

- **`app/voice/bot.py`** replaces the raw-Claude pipeline path. `EngineProcessor` (a Pipecat
  `FrameProcessor`) sits where the LLM was: on each final `TranscriptionFrame` it runs
  `engine.run_turn` and speaks the result via `TTSSpeakFrame`; it greets first via `engine.open()`.
  The engine's per-turn LLM work (extraction + render synthesis) is sync, so it runs in
  `asyncio.to_thread` to avoid blocking the pipeline loop. New pipeline:
  `transport.input → STT → EngineProcessor → TTS → transport.output` (no in-pipeline LLM/context
  aggregators).
- **Hybrid rendering** (the chosen architecture): `render` now LLM-smooths *smoothable* SPEAK
  directives (discovery questions, fit summaries, pivots) and synthesizes GROUND from approved
  snippets, while fixed lines (objection rebuttals, escalation, KB-4 fallback, wrap-up) stay
  verbatim. `make_synthesizer` is one Claude call (configured model, persona system prompt,
  cached) that returns `None` on any error so render falls back to verbatim/KB-4 — a phrasing
  failure never drops the call.
- **§18 enforced on output:** `guard_output` runs `check_agent_output` on every rendered line;
  claims-to-be-human / guarantee → substitute the handoff line; **price figures are now advisory
  only** (logged, not blocked) since approved pricing is in the KB — resolving the guardrail
  tension flagged earlier.
- **Wiring/refactor:** `run_bot` moved `pipeline.py → bot.py`; `server.py` imports it from `bot`.
  `pipeline.py` keeps the shared service/transport builders + the legacy `build_pipeline_task`
  (still construction-tested). Persists turns + decision trace via `CallRecorder` (per-call DB
  session; `init_db()` ensures tables). On disconnect, stamps `ended_at` and closes the session.
- **Threading/DB caveat:** one SQLite session per call, written from the worker thread; turns are
  sequential so it's safe for the demo (noted for hardening). Barge-in mid-turn may push a late
  line (the in-flight `to_thread` completes) — acceptable for MVP.
- **NOT live-validated here:** construction only (imports/wiring/`PipelineTask`). The real
  decider-led conversation needs a browser/mic/keys run.
- **Validation:** `ruff` clean; `pytest` 115 passed (7 new: render smoothing ×2; guard, synth
  ×2, construction).

---

## P4.5-T6 — latency tiers + ambient bed (2026-05-27) — Phase 4.5 complete

- **Filler-masking:** `app/voice/fillers.py` `FillerBank.pick(text)` returns a rotating short ack
  ("Sure.", "Got it.") for statements and a "working" filler ("Let me check on that…") for
  questions (slow KB path). `EngineProcessor` speaks the filler immediately, *then* computes the
  real reply in the worker thread and speaks it after — so the call never falls silent. Gated by
  the `fillers` config (default on). Neutral by design so a filler can't contradict the reply.
- **Ambient comfort-noise bed:** `build_transport` attaches Pipecat `SoundfileMixer`
  (`data/audio/ambient.wav`, `loop`, `volume=ambient_volume`) as the transport **output** mixer
  when `ambient_noise` is on — output-only, so no STT/VAD impact. Output rate pinned to
  `audio_out_sample_rate=24000` to match the asset (the mixer doesn't resample). `SoundfileMixer`
  is lazy-imported so `soundfile` is only needed when the bed is enabled; added `soundfile` to the
  voice extra and installed it. Verified the asset reads at 24 kHz mono.
- **Config:** `audio_out_sample_rate=24000`, `fillers=True`, `ambient_noise=False`,
  `ambient_volume=0.15` (in `config.py` + `config.toml`).
- **Deferred (need live measurement to tune, documented in the plan):** Tier-1 FAQ answer cache,
  Tier-2 speculative prefetch, and true Tier-0 pre-synthesized filler *audio* (current fillers
  still go through TTS — fast, but not instant). The design (`AGENT_INTEGRATION.md` §5) is the
  spec when we pick these up after a live latency baseline.
- **Validation:** `ruff` clean; `pytest` 122 passed (7 new: filler selection/rotation, latency
  config defaults, EngineProcessor filler flag, ambient-off transport construction).

### Phase 4.5 complete

All six tickets built: turn router, extraction (rule-based + LLM upgrade), directive+render,
conversation engine, live voice wiring, latency tiers + ambient bed. The structured agent layer
(Phases 2–4) now drives what the live agent says. **Remaining real-world step:** a browser/mic/
keys run to validate the live decider-led conversation and measure latency vs VC-3 — that gates
turning on/tuning the deferred Tier-1/Tier-2 latency work.

---

## P5-T1 — decision-trace enrichment (2026-05-27)

- The engine already wrote a `Decision` per turn (`recorder.record_decision`); P5-T1 completes
  DE-2. `engine.run_turn` now classifies first, records the prospect `Turn` tagged with
  `detected_intent` (the router route — objection/knowledge/escalate/stop/progress) and
  `detected_objection` (objection key when applicable), and links `Decision.turn_id` to that turn
  — so the decision trace joins to the transcript. Stage/action/reason/confidence/missing_fields/
  escalation_risk/kb_sources were already captured.
- `sentiment` (Turn) left for §16/P5-T3 (frustration KPI), not DE-2.
- **Validation:** `ruff` clean; `pytest` 123 passed (1 new: intent/objection on prospect turns,
  decisions linked to turns, escalation risk recorded).

---

## P5-T2 — version attribution (2026-05-27)

- **`app/agent/versioning.py` `compute_versions(settings)`** → `Versions(agent_version,
  playbook_version, kb_version, model_version)`: content hashes of the persona prompt, the
  `data/playbooks/*.yaml`, and the `data/kb/*.md` (so a version changes iff the content changes),
  plus the configured model id. `CallRecorder` accepts these and stamps them on the `Call` (§10.4);
  `run_bot` applies `compute_versions(settings).as_dict()`.
- **Gaps (noted):** `experiment_id`/`variant_id` are Phase 7; the PRD lists "voice config" but
  `Call` has no column for it — skipped rather than alter the schema.
- **Validation:** `ruff` clean; `pytest` 126 passed (3 new: stable/well-formed versions, persona
  change bumps agent_version, recorder stamps the Call).

---

## P5-T3 — KPI events & metrics (2026-05-27)

- **Found the gap:** the recorder had `KPIEvent` plumbing but nothing emitted events. Added the
  vocabulary (`app/kpis/events.py`) + a generic `CallRecorder.record_event`, and the **engine now
  emits** per turn: `objection_raised`, `escalation`, `close_attempt`, `discovery_complete` (first
  fit summary), and `call_completed` on `engine.end(outcome=)`. `run_bot` now calls `engine.end()`.
- **`app/kpis/metrics.py` `compute_metrics(session, agent_version=, variant_id=, include_synthetic=)`**
  rolls up §16: close attempt/success, objection recovery (of objection calls, share that
  progressed to a close/summary), escalation, discovery completion, unsupported-claim — sliceable
  for the experiment loop. Zero calls → all rates `None` (not div-by-zero).
- **Honest gaps:** `average_latency_seconds` and `frustration_rate` return `None` — they need
  per-turn timing and sentiment, which aren't captured yet (P4.5-T6 latency measurement / a future
  sentiment signal). `unsupported_claim_rate` computes from events that aren't emitted yet (the
  output guard substitutes rather than logging) → currently 0; emission is a small follow-up.
- **Validation:** `ruff` clean; `pytest` 131 passed (5 new: objection/escalation events,
  close/discovery events, rollup math, empty-db safety, version slicing).

---

## P5-T4 — observability dashboard (2026-05-27) — Phase 5 complete

- **`app/dashboard/router.py`** (`/api` read-only): `GET /api/metrics` (compute_metrics, sliceable
  by `agent_version`/`variant_id`), `GET /api/calls` (newest-first summaries), `GET /api/calls/{id}`
  (transcript + decision trace + KPI events, §10.3). Uses `Annotated[Session, Depends(get_db)]`.
- **Static UI** at `/dashboard` (`frontend/dashboard/index.html`, vanilla JS, mounted like `/demo`)
  — KPI cards (null KPIs render "not measured"), a calls table, and per-call drill-down to the
  transcript + decision trace. **No new dependency** (chose static-over-Streamlit to match the
  existing frontend pattern).
- **Validation:** `ruff` clean; `pytest` 135 passed (4 new: metrics endpoint + version slice,
  calls list/detail with intent/decision/events, 404). Real-app smoke: `/api/metrics`, `/api/calls`,
  `/dashboard/` all 200.

### Phase 5 complete

Decision trace (DE-2, linked to turns) + version attribution (§10.4) + KPI events/metrics (§16) +
a dashboard (§10.2/§10.3). Every call is now observable and version/variant-tagged — the substrate
the Phase 6 simulator and Phase 7 experiment loop build on. (Latency/frustration KPIs still report
"not measured" pending per-turn timing + sentiment.)

---

## P6-T1 — synthetic persona definitions (2026-05-27)

- **`data/personas/personas.yaml`:** the 6 §12.2 personas (motivated, skeptical, price-sensitive,
  busy, competitive-shopper, poor-fit). Each carries ground-truth `facts` (keyed by the discovery
  field names so P6-T3 can score what the agent extracted), behavior `traits`, `objections` (in
  natural language the agent's cue detector should catch), and `converts`/`disqualifies` flags.
- **`app/simulator/personas.py`:** `PersonaLibrary` loader + `persona_system_prompt(persona)` that
  composes the persona with the universal §12.3 behavior rules (hesitate, partial answers, raise
  objections, resist pushiness, occasionally disqualify, reward consultative selling, stay in
  character). The runner (P6-T2) feeds this to a Claude self-play prospect.
- **Designed to reveal weaknesses, not flatter** (§12.1): the poor-fit persona explicitly tests
  that the agent won't force a close; the skeptical/price personas push proof/discounts.
- **Validation:** `ruff` clean; `pytest` 141 passed (6 new: ≥6 personas + required types, facts/
  flags, objection personas, prompt content, disqualified prompt resists close, custom load).

---

## P6-T2 — simulated call runner (2026-05-27)

- **`app/simulator/runner.py`:** `run_call(engine, prospect, persona_key, max_turns)` — the
  LLM-agnostic self-play loop (greet → prospect↔agent until a terminal stage / goodbye / cap),
  returning a `SimResult` (call_id, final stage, outcome, transcript). `make_prospect` is a Claude
  self-play prospect (role-reversed history; agent lines are 'user'). `simulate` wires the real
  engine (synthetic recorder, LLM extractor, Claude phrasing) + prospect. Records the same
  Call/Turn/Decision/KPIEvent rows, `is_synthetic=True`, `channel="sim:<persona>"` (so synthetic
  calls are identifiable on the dashboard and excludable from real-call metrics).
- **Refactor:** moved `make_synthesizer` from `app/voice/bot.py` (which imports pipecat) to
  pipecat-free `app/agent/synthesis.py` (stdlib logging) so the simulator reuses it without
  pulling voice deps; `bot.py` re-imports it (test_bot unaffected).
- **Live-validated:** a real Claude self-play (price-sensitive persona) ran end-to-end — agent
  greeted, confirmed context, ran skip-known discovery with LLM-smoothed phrasing; prospect
  answered consistently from its facts; all turns/decisions persisted. (Hit the turn cap
  mid-discovery → outcome `abandoned`; the default `max_turns=12` reaches close.)
- **Validation:** `ruff` clean; `pytest` 145 passed (4 new: records a synthetic call, goodbye
  ends, escalation→escalated outcome, prospect persona/history) + a live self-play smoke.

---

## P6-T3 — agent performance scoring (2026-05-27) — Phase 6 complete

- **`app/simulator/scoring.py` `score_call`** combines: **deterministic** flags off the recorded
  call (escalated / close_attempted / discovery_completed / objection raised+recovered, and
  `appropriate_for_persona` — a converts persona should progress toward a close, a poor-fit persona
  should NOT be force-closed) + an **LLM-as-judge** (`judge_transcript`, structured output via
  `messages.parse`) for the qualitative §16 signals: frustration, unsupported-claim, consultative
  1–5. Judge client injected (tests fake it; no API). Cross-persona aggregation is Phase 7.
- **Validation:** `ruff` clean; `pytest` 150 passed (5 new: objection-recovery/escalation flags,
  poor-fit-not-force-closed appropriate, converts-without-progress inappropriate, judge mapping,
  judge prompt content).

### Phase 6 complete

≥6 honest personas, a self-play runner producing the same traced/versioned records (labeled
synthetic), and per-call scoring (deterministic + LLM judge). The agent can now be tested at
volume against adversarial prospects without a human — the substrate the Phase 7 experiment loop
runs on.

---

## P7-T1 — experiment & variant infrastructure (2026-05-27)

- **Variant-application seam:** `Orchestrator.objection_overrides` ({objection_key: rebuttal}) —
  `handle_objection` uses the override for the matched objection. This is how a variant changes
  behavior with no other difference. `CallRecorder` now stamps `experiment_id`/`variant_id`;
  `build_simulation_engine` threads both + the overrides (and accepts injectable extractor/
  synthesize so experiment runs are offline-testable).
- **`app/experiments/variants.py`:** the §8 BASELINE (generic value statement) + 5 candidate
  styles (empathy-first, outcome-cost, risk-reversal, comparison, diagnostic) as `PriceVariant`
  (rebuttal + when-to-use/not + escalation trigger + compliance, all §18-safe).
- **`app/experiments/engine.py`:** `create_experiment` (Experiment + a Variant row per rebuttal,
  rebuttal stored in `playbook_delta`, `baseline_variant_id` set) and `run_variant` (a tagged
  synthetic self-play applying the variant's price rebuttal; `offline=True` → no-LLM engine).
- **Validation:** `ruff` clean; `pytest` 154 passed (4 new: catalog ≥2 + guardrail-safe, override
  seam, records persisted, offline run applies override + tags the call).

---

## KB content: pricing provided by operator (2026-05-27)

- Operator supplied pricing copy; loaded into `data/kb/pricing.md` (no longer a placeholder).
  After review (with the operator, via decision prompts):
  - **Included:** Varsity Tutors live tutoring = custom-quoted (subject / tutor experience /
    hours), and Nerd AI homework-app freemium tiers with **exact figures** (free ~3/day;
    $6.99–9.99/wk; ~$39.99/yr; $39.99–49.99 lifetime).
  - **Excluded:** NerdyData (SEO), Nerdio (Azure/IT), Nerdy Form (lead forms) — the source
    conflated unrelated companies with Nerdy/VT; quoting them would be actively wrong.
  - Provenance + "re-verify figures" recorded as an HTML comment (stripped from chunks).
  - Pricing queries now retrieve `pricing.md` strongly (1.3–1.9).
- **Guardrail tension to revisit (not changed here):** `check_agent_output` (P4-T4) flags ANY
  price figure as `QUOTES_PRICE`. Now that approved Nerd AI prices exist, that blunt check would
  false-positive on legitimate prices. It's a tested *utility*, not yet enforced on live output,
  so no functional impact today — but when the live post-generation filter is wired, demote it to
  advisory or scope it to *live-tutoring* prices (which must always be custom/deferred). The real
  no-hallucination protection remains the KB-grounding flow (answer from retrieved snippets only).
- **Validation:** `ruff` clean; `pytest` 72 passed (retrieval probe confirms pricing grounding).

---

## P7-T2/T3/T4 — run, evaluate, promote, report (2026-05-27)

- **`engine.run_experiment` + `experiment_personas`:** runs every variant (baseline + candidates)
  across a fixed 5-persona set (price-sensitive, competitive-shopper, skeptical, motivated,
  poor-fit) so a winner must hold up beyond the easy lead (§8). Calls are tagged for slicing.
- **`evaluation.py`:** `aggregate` rolls per-call scores into KPI rates; `decide_promotion`
  applies the §8 rule — promote only if objection-recovery improves **and** frustration +
  unsupported-claim rates don't regress (None rates read as 0, the conservative reading);
  `evaluate_experiment` promotes the best passing candidate, retires the rest, stamps the
  Experiment (status/decision/end_date); `render_report` writes the before/after Markdown.
- **Decision — offline must be truly no-LLM:** `run_variant`'s fallback built a *Claude* prospect
  even when `offline=True` (the first smoke quietly spent tokens, ~30s). Added a scripted
  price-objection prospect used only offline, so `python -m app.experiments --offline` is free
  (~7s) and deterministic. Offline is a wiring smoke (recovery shows 0% — rule-based extraction
  never closes); real numbers require the Claude run + judge.
- **`app/experiments/__main__.py`:** `python -m app.experiments [--offline] --name … --report …`
  runs create → run → evaluate → write report end-to-end.
- **Deferred (deliberate):** the real measured run (~60 LLM calls: self-play + judge) and the
  committed `docs/recursive-improvement.md` are a fire-it step, not auto-run. Dashboard experiment
  view (P7-T4's "surface in dashboard") still TODO — the report is the primary before/after evidence.
- **Validation:** `ruff` clean; `pytest` 158 passed (4 new: aggregate rates, promotion rule 3
  scenarios, evaluate_experiment promotes best candidate + writes report, offline run_experiment
  runs all variants). Offline CLI smoke green.

---

## P7-T4 — real measured run fired (2026-05-28)

- **Fired the real run:** `python -m app.experiments --name price-rebuttal-v1` (baseline + 5
  candidates × 5 personas self-play + LLM judge). Wrote `docs/recursive-improvement.md`.
  (One earlier attempt failed on an out-of-credit API key; re-run after the user topped up.)
- **Outcome — baseline held (no promotion).** Every variant scored **0% objection-recovery**;
  three candidates *regressed* frustration (80% → 100%), so the §8 rule correctly promoted none.
- **Why 0% recovery is real, not a broken metric (verified):** recovery =
  `objection_raised AND (close_attempt OR discovery_complete)`. DB check across the experiment
  calls: `objection_raised` fires in 50 calls but `close_attempt` in only 3 and
  `discovery_complete` in 7, and **zero** calls had an objection co-occur with a close/discovery.
  The agent rarely reaches a close at all in self-play and never recovers a price objection
  within the 12-turn cap. KPI events fire correctly — the absolute numbers are genuinely poor.
- **Root cause = placeholder content + short budget (known).** Rebuttals/KB are PLACEHOLDERS
  (see `docs/QandA_opens.md`); with no real rebuttal substance and `--max-turns 12`, conversations
  end before a close. **Follow-up to lift the numbers:** supply approved rebuttal/KB copy and/or
  raise the turn budget, then re-fire. The *loop mechanism* (variant gen → self-play → judge →
  §8 promotion rule → before/after report) is proven end-to-end regardless of the flat scores.
- **Validation:** report generated; `ruff` clean; `pytest` 158 passed (unchanged — fire-it run,
  no code change).

---

## P8-T2 — credit-free documentation set (2026-05-28)

- **Wrote the docs that don't need live LLM calls:** `docs/decision-log.md` (§23, 12 decisions),
  `docs/research-notes.md` (§24), `docs/limitations.md` (§25), and top-level `README.md`
  (overview + architecture + setup/demo, pointing at `docs/RUNBOOK.md`).
- **Failure-mode report = draft from real synthetic evidence.** `docs/failure-modes.md` covers
  all 14 §19 modes. Modes OBSERVED in the 2026-05-28 run use **real transcript excerpts pulled
  from the DB** (not fabricated) — notably the thrice-repeated KB fallback (rigid script),
  a deflected buying signal (failure to close), and an objection mis-extracted as a discovery
  answer (incorrect carryover). Modes needing live trials (latency, barge-in, skeptical humans)
  are marked **PENDING LIVE** with excerpts deliberately omitted rather than invented.
- **Decision — don't fabricate evidence.** Where a §19 mode had no real transcript, left the
  example as "pending live trial." Honest gaps over plausible-looking fiction.
- **Cross-cutting finding (recorded in failure-modes):** the dominant root cause behind weak
  objection handling / failure-to-close / competitive mishandling / rigid script is the
  **placeholder KB+rebuttal content + 12-turn cap**, not broken logic — same story as the P7 run.
- **P8-T2 status: In Progress.** Remaining work depends on P8-T1 (live human trials): finalize
  the PENDING-LIVE failure modes and refresh `docs/limitations.md` once humans test.
- **Validation:** docs-only change — no lint/tests to run (no code touched). `README.md`/limitations
  cite `docs/failure-modes.md`, which now exists (no dangling links).

---

## P9-T1 — relabel CTA + audio-asset scaffolding (2026-05-28)

- **New phase (9) for demo polish:** make `/demo` feel like a phone call. Relabeled the button
  to "Call 1-800-Nerdy-4-u" and updated the intro copy in `frontend/index.html`.
- **Decision — two audio assets, not one.** The user chose "loop ring until the agent answers,"
  which can't cleanly loop a single combined mp3. Split into `frontend/audio/dial.mp3` (one-shot
  dial+digits) and `frontend/audio/ring.mp3` (loop-safe ring) — a deviation from the original
  "an mp3" ask, required by the chosen behavior.
- **Decision — assets live under `frontend/`, not `data/audio/`.** `data/audio/` is server-side
  comfort noise mixed into the agent stream and is *not* web-served; these are browser-played
  effects, so they must be under the `/demo` static mount. Added `frontend/audio/README.md`
  documenting the contract (mirrors `data/audio/README.md` style).
- **Placeholders are silent stubs** (ffmpeg `anullsrc`, dial 3 s / ring 2 s) so playback wiring
  is testable now; user drops in real audio later with no code change. The user owns the final
  audio (their choice).
- **Validation:** static frontend assets — no lint/tests apply (no Python touched). Browser
  behavior is wired in P9-T2; full manual verification (RUNBOOK §11) after T2.

---

## P9-T2 — phone-call intro playback + connect-on-answer (2026-05-28)

- **Sequencing in `client.js`:** on Call click (after the `/voice/status` ready-check),
  `startDialingSound` plays `dial.mp3` once and, on its `ended` event, loops `ring.mp3`; the
  WebRTC connect runs in parallel so ringing covers setup latency. `onAnswered` (fired on
  connectionState `connected`, with `ontrack` as a fallback) stops the ring and shows
  "Connected — the agent will greet you." `stopDialingSound` resets both clips on hang up,
  connection failure, and mic-permission denial. An `answered` flag guards the race where the
  call connects *during* the dial intro (don't start the ring after the fact).
- **Decision — drop the transient "Requesting microphone…/Connecting…" statuses.** They stomped
  the "Dialing…/Ringing…" phone narrative; the browser's own mic prompt is enough signal and the
  intro copy already tells the caller to allow the mic.
- **Decision — don't claim "Connected" until the connection actually answers.** The old code set
  "Connected — start talking" right after `setRemoteDescription` (before ICE completes); now
  `onAnswered` owns that message so the status matches the real pickup moment.
- **User copy change mid-build:** intro line is now "Click below to call 1-800-Nerdy-4-u
  (1-800-637-3948)…".
- **Validation:** `node --check` clean. Browser-verified (agent-browser, server on :8099):
  click → "Dialing…" → after the dial clip → "Ringing…" (loops; getUserMedia stubbed to hang to
  avoid a real credit-spending call); mic-deny path → graceful "Call ended." with the button
  re-enabled and audio stopped; no console errors. Screenshot confirms the relabeled CTA + copy.
  The answer-stops-ring path wasn't exercised live (needs a real connection / API credits) but is
  straightforward reviewed code. No Python touched — `ruff`/`pytest` unaffected.

### P9-T2 fix — ring until the agent actually speaks (2026-05-28)

- **Bug:** with real audio added, pressing Call "just launched into the script" — almost no
  dialing was heard. Cause: `onAnswered` fired on `pc.ontrack` and connectionState `connected`,
  which both happen during WebRTC negotiation *before the agent speaks*, so the ring was cut
  immediately.
- **Fix:** treat "answered" = the agent's audio actually starts. `detectAnswerFromStream` taps
  the inbound stream via a Web Audio `AnalyserNode` and calls `onAnswered` on the first real audio
  energy (threshold 400 summed over 256 bins), with a 30s hard-cap deadline so it never rings
  forever. `ontrack` now starts detection instead of answering; connectionState only handles
  failure. The `AudioContext` is primed in the click handler (`ensureAnswerCtx`) so the autoplay
  policy doesn't leave it suspended (it's created after `await`s otherwise).
- **Tradeoff:** the energy threshold (400) is untuned against a live agent stream; if WebRTC
  comfort noise trips it early or the greeting is too quiet, it needs adjusting. The onset path
  itself can't be exercised headlessly (needs the real bot) — verified instead that the connection
  no longer answers early (ring persists with `getUserMedia` stubbed to hang; no console errors).
- **Validation:** `node --check` clean; browser smoke (server :8099) — Dialing… → Ringing… with
  no early answer. No Python touched.

### Live voice fix — agent was listening to itself (2026-05-28)

- **Symptom (from call `58d32393` logs):** the agent fired 3 questions in ~8s, never advancing
  past `relationship_to_student`; the "prospect" turns were short fragments ("Alright. Bye.",
  "Some things.") timestamped 3–143ms after each agent turn — i.e. the agent's own TTS / echo was
  being transcribed and fed back as new user turns. Root cause: `EngineProcessor` ran the engine
  on every STT final with no gating, and STT stayed live while the agent spoke.
- **Fix:** insert a Pipecat `STTMuteFilter(STTMuteStrategy.ALWAYS)` right after `transport.input()`
  in `build_engine_pipeline_task` (before STT). It mutes the mic input (suppresses inbound audio +
  VAD + transcripts) whenever the agent is speaking, driven by Bot{Started,Stopped}SpeakingFrame —
  so Deepgram never transcribes the agent's own voice. Goal: "listen to the user, not itself."
- **Defense in depth:** `client.js` now requests `getUserMedia({audio:{echoCancellation,
  noiseSuppression, autoGainControl}})` (browser default is on, but explicit) so the speaker's
  audio isn't captured back into the mic.
- **Trade-off:** with STT muted during agent speech, mid-sentence barge-in is effectively off
  while the agent talks (turn-taking resumes the instant it stops). That's the desired behavior
  for a sales call and matches the goal. `STTMuteFilter` is deprecated in pipecat 0.0.108 (favoring
  `LLMUserAggregator.user_mute_strategies`) but we use a custom `EngineProcessor`, not that
  aggregator, so the filter remains the right tool; deprecation is a one-time warning.
- **Validation:** `ruff` clean; `pytest` 158 passed; `test_engine_pipeline_constructs` strengthened
  to assert `STTMuteFilter` is wired **before** `_DeepgramSTTService`. The actual mute behavior
  needs a live mic call to confirm (can't be exercised headlessly).

### Call-log review fixes — routing/turn-taking hardening (2026-05-28)

Driven by reviewing real call `8b72f75c` (web, ~45s): the agent asked
`relationship_to_student` 3× in 30s, never escalated despite profanity, acted on
misheard transcripts, recorded a phantom turn *before* the greeting, and dropped the
discovery thread after a KB answer. Five small, mostly pure-logic tickets:

- **T1 — hostility/abuse escalation (`guardrails.py`).** Added hostility cues to the
  `ANGER_CONFUSION` set so "shut up / shut the **** up / you're useless / bullshit" route to
  ESCALATE. Decision: match the *surrounding phrase* + unmasked insults, because Deepgram masks
  profanity (`****`) so the swear word itself is unreliable.
- **T2 — discovery re-ask cap (`orchestrator.py`/`decisioning.py`/`engine.py`).** Added
  `ConversationState.ask_attempts`; the engine counts each ask, the decider rephrases on retry
  (`Modifier.CLARIFY`) and **abandons** a field after `MAX_ASK_ATTEMPTS=2`, moving on instead of
  looping. The clarify path respects the same cap. Pattern: ask → rephrase → move on.
- **T3 — pre-greeting transcript gate (`voice/bot.py`).** `EngineProcessor._ready` is set only
  after `greet()` dispatches; transcripts before that are dropped as connect-time noise/echo
  (the phantom "Good early." turn). **Needs a live mic re-test** (construction-tested only).
- **T4 — STT-confidence gate (`engine.py`/`voice/bot.py`).** Pull Deepgram word confidence off
  `TranscriptionFrame.result`; below `STT_CONFIDENCE_THRESHOLD=0.6` on a progress/knowledge turn
  the agent asks the caller to repeat and does **not** extract/advance. Decision: this is an
  *STT-quality* gate (did we hear it), distinct from DE-4 decision-confidence — so it does not
  hand off to a human, and escalations/refusals/objections are still honored at low confidence.
  Confidence is now persisted on the turn (previously always null). Threshold 0.6 is untuned —
  revisit against live Deepgram scores.
- **T5 — KB-answer bridge-back (`engine.py`).** When a KNOWLEDGE turn arrives while a discovery
  question is pending, append "Anyway — back to what I asked: <question>" and keep the field
  pending so the next answer fills it. Re-uses the discovery prompt via a shared `_question_prompt`
  helper (also now used by `_clarify`).
- **Validation:** `ruff` clean; `pytest` 168 passed. T3's gate and T4's live confidence values
  can only be fully confirmed on a browser/mic/keys run (RUNBOOK §11).

## 2026-05-28 — Phase 10: Conversation Memory & Context Continuity

Surfaced by a Retell.ai architecture review of the "agent re-asks questions" problem. The
structured layer existed but three seams were disconnected. Implementing each as its own ticket.

- **P10-T1 — wire cross-call memory into the live voice path (`voice/bot.py`, `config.py`,
  `agent/orchestrator.py` already supported it).** `run_bot` now loads a `Lead` and seeds the
  engine with its `known_fields` (and ties the `Call` to the lead). Decision (not in spec): for the
  web demo, the lead is chosen by a new optional `demo_lead_id` setting rather than a per-call
  frontend selector — smallest change that makes returning-caller memory real without a UI/offer
  change. Unset/unknown id ⇒ anonymous cold start, exactly as before. `build_engine` gained
  `known_fields`/`lead_id` params. A frontend/offer-driven lead picker is a later enhancement.
- **P10-T3 — persist all discovery slots & auto-write on call end (`db/models.py`,
  `memory/lead_store.py`, `agent/orchestrator.py`, `voice/bot.py`).** Added a `collected_fields`
  JSON column on `Lead`; `apply_call_outcome` now merges *all* non-empty slots into it (typed
  profile columns still update too), and `all_known_fields()` re-seeds the union (typed columns
  canonical). The write fires automatically from `engine.end()` → `Orchestrator.end()` via two new
  optional collaborators (`lead_store`, `lead`) — same pattern as the optional `recorder`, so the
  decision layer stays DB-free in tests. Decisions/tradeoffs:
  - No migration tool in the project (SQLite + `create_all`); **existing dev DBs must be recreated**
    to get the new column. Fresh/in-memory/test DBs are fine.
  - Only `collected` + `summary` are written back at end, not objections/status — `ConversationState`
    has no raised-objection list (objections live in KPIEvents/Turns) and outcome→status mapping is
    out of scope. Revisit if cross-call objection memory is needed.
- **P10-T2 — feed the running transcript into the synthesizer (`agent/synthesis.py`,
  `agent/render.py`, `agent/engine.py`).** The phrasing call was stateless (one `user` message +
  cached persona); now `make_synthesizer`'s callable takes an optional `history`, replayed as prior
  `messages` so the LLM phrases the next line with the whole conversation in view (won't re-ask,
  can smooth a correction). `_history_messages` maps turns → user/assistant, coalesces consecutive
  same-role turns, drops a leading assistant turn (Anthropic needs a user-first list), and appends
  the instruction as the final user turn. Decisions/tradeoffs:
  - Kept the `Synthesize` contract backward-compatible: `render` forwards `history` only when present
    (`synthesize(instruction, history)` vs `synthesize(instruction)`), so the deterministic SPEAK
    paths and all 1-arg test/text-mode callables are unchanged. Updated the 3 `test_engine` lambdas
    to accept the optional arg.
  - Capped replay at `MAX_HISTORY_TURNS = 20` (latency/token bound); untuned.
- **Validation (Phase 10):** `ruff` clean; `pytest` **174 passed**. The live conversational effect
  (no re-asking across/within calls) still needs a browser/mic/keys run per RUNBOOK §11; the unit
  tests prove the wiring (memory seeded, slots persisted/round-tripped, transcript replayed as a
  valid message list).

## 2026-05-28 — Live-voice hardening T6: greetings/pleasantries aren't KB questions

Real call `ea6c68d9`: the opening "Hey. How's it going?" was classified `knowledge` (because
`is_knowledge_question` returned True for any `?`), the KB had nothing, so the agent gave the §18
"let me connect you with a specialist" deferral on turn one — a terrible open. Two bugs: (1) the
heuristic over-fired on punctuation, (2) a pleasantry had no route other than KNOWLEDGE.

- **Fix (`agent/knowledge.py`).** Added `is_social_pleasantry()` (greeting/pleasantry/connectivity
  cues — "how's it going", "how are you", "can you hear me", bare "hi/hey/hello/thanks", "you still
  there"). `is_knowledge_question` now returns False for those. Real questions ("how much does it
  cost?", "do you offer SAT prep?") still route to KNOWLEDGE.
- **Router (`agent/router.py`).** No logic change — excluding pleasantries from
  `is_knowledge_question` lets them fall through to the default `PROGRESS` route (acknowledge +
  advance discovery), which is the correct home. Added a comment + tests.
- **Extraction (`agent/extraction.py`).** `_is_substantive_answer` also rejects pleasantries, so a
  greeting offered where an answer was expected triggers a clarify instead of being stored as a
  bogus slot value (prevents a regression from the looser `is_knowledge_question`).
- **Known remaining edge:** non-social rhetorical questions ("Right?") still route to KNOWLEDGE;
  out of scope for this fix. **Validation:** `ruff` clean; `pytest` **178 passed**. Live re-test of
  the opening turn still pending (RUNBOOK §11).

## 2026-05-28 — Direction change: narrow to a 2-option voice intent-router

Strategic pivot (user-driven). The agent is being narrowed from a full discovery-to-close sales
agent to a **two-option intent router**: converse to determine **test prep vs. tutoring**, drill to
the specific test/subject leaf, **quote that leaf's price**, and answer informational questions from
a grounded KB. Rationale: it removes the old design's unsolved problems (when to close, objection
recovery) and buys an objective, gradeable metric (classification accuracy vs. synthetic
ground-truth leaves).

- **Decision — modify, not rebuild.** Reuse voice pipeline, transcript/decision-trace/KPI
  persistence, dashboard, and the synthetic self-play simulator. Delete the discovery-to-close
  playbook, objection/close logic, and the "rephrase only" rendering gag. Change is concentrated in
  the conversation core + a small price table.
- **Decision — price is a deterministic table keyed by the classification leaf, never retrieval.**
  Fuzzy retrieval of a price = wrong number = the one guardrail we promise never to break. The
  `quote_price(leaf)` tool does an exact lookup, gated on a confident leaf.
- **Decision — KB on OpenAI `text-embedding-3-small` + `sqlite-vec`** (in the existing SQLite file)
  for explanatory Q&A only. Accepts an OpenAI dependency (aligns with the evaluated stack) over the
  current TF-IDF/offline retriever.
- **Artifacts.** New requirements doc `docs/brainstorms/intent-router-agent-requirements.md`;
  prior `llm-driven-conversation-core-requirements.md` marked superseded. Build plan not yet
  written; STRATEGY.md / PRD / BUILD_PLAN still describe the old scope and need reconciling.

## 2026-05-28 — Added Phase IR-7: live call-center dashboard

The front end becomes a focus. Added **Phase IR-7** to `docs/BUILD_PLAN_INTENT_ROUTER.md`: an
observe-only **React** call-center dashboard where the operator watches calls arrive and stream
live (transcript, decision trace, turn latency, insights).

- **Decisions (D-16).** Observe-only v1 (no operator takeover yet); React/Vite per R13; live push
  over **SSE** (one-way, fits a read-only board; WebSocket is the upgrade path for takeover).
  Simulated calls drive it first (`POST /api/sim/start`); **Twilio Media Streams inbound is a
  deferred sub-ticket (IR7-T7)**.
- **Two gaps the phase must close.** (1) No live push today — the dashboard polls REST; IR7-T2 adds
  a recorder-fed event bus + SSE stream. (2) Turn latency is never measured (`metrics.py` returns
  `average_latency_seconds = None`); IR7-T1 instruments it (STT-final → first TTS audio; brain/tool
  time) and adds `Turn.latency_ms` (+ migration-recreate caution).
- **Scope reconciliation.** The old IR6-T2 was "update the dashboard UI"; it's now **API-only** (read
  endpoints), with all UI moved into IR-7. STRATEGY.md observability track updated to make the live
  dashboard the operator's primary surface.

## 2026-05-28 — IR0-T2: OpenAI config + dependency

Added `openai_api_key`, `openai_chat_model` (default `gpt-4o`), `openai_embedding_model` (default
`text-embedding-3-small`) to `app/config.py`, plus an `openai_enabled` property. Declared
`openai>=1.40` in `pyproject.toml` core deps. **Decision:** OpenAI key stays optional so the core
app + test suite boot without it — the brain (IR-2) and KB retriever (IR-3) fall back to an offline
path when unset. `missing_voice_keys()` left unchanged (OpenAI isn't a voice key). Tests:
`tests/test_config.py`. `ruff` clean; 3 passed.

## 2026-05-28 — IR0-T3: taxonomy module

`app/agent/taxonomy.py` — the pure classification target: the 8-leaf tree as data, slot fields
(`category`/`test`/`subject_area`/`subject`), light value normalization, and leaf resolution.
**Decision:** children imply parents — `test=SAT` ⇒ `category=test_prep`; `subject=chemistry` ⇒
`subject_area=science` ⇒ `category=tutoring` — so the brain can slot whatever the caller volunteers
and `resolve_leaf` completes the path. Contradictions (a `test` under tutoring, a subject that
doesn't match its area) are dropped rather than erroring. `next_unfilled` encodes the
disambiguation order (R8). Leaf ids (`test_prep/SAT`, `tutoring/science/chemistry`) are the price
keys for IR-1. Tests: `tests/test_taxonomy.py` (9). `ruff` clean.

## 2026-05-28 — IR1-T1: price table + loader

`data/pricing/pricing.yaml` (keyed by leaf id) + `app/agent/pricing.py`. `quote_price(leaf|id)`
does an **exact** lookup and returns a `PriceRecord` or `None` (R6) — no record means honest
fallback, never an invented number (R6b). **Decisions:** (1) prices are clearly-labeled
PLACEHOLDER (`approved: false`) — not approved Nerdy figures; the loaded value is the source of
truth the mis-quote guardrail (IR1-T2) will check against. (2) The loader rejects a price keyed to
a leaf the taxonomy doesn't define, so the table can't drift from `taxonomy.py`. Tests:
`tests/test_pricing.py` (6). `ruff` clean.

## 2026-05-28 — IR1-T2: mis-quote guardrail

Added `check_mis_quote(text, allowed_amount)` + `extract_price_amounts` to `agent/guardrails.py`
and a `MIS_QUOTE` violation code; added `MIS_QUOTE_BLOCKED` / `LEAF_REACHED` / `CLARIFY_ASKED` to
`kpis/events.py`. **Decision:** unlike the legacy advisory `QUOTES_PRICE` flag (left intact for the
old voice guard), a mis-quote is a HARD violation — any dollar amount stated with no authorized
leaf/price, or one that doesn't match the price-table figure for the turn, is caught. A reply with
no dollar amount is always clean (the agent may discuss price without quoting). The engine (IR2-T3)
will substitute a safe handoff and emit `MIS_QUOTE_BLOCKED` on a hit. Tests:
`tests/test_guardrails_misquote.py` (5); existing guardrail/KPI tests unaffected. `ruff` clean.

## 2026-05-28 — IR2-T1: brain tool contract + decision schema

`app/agent/contract.py` — the shared contract between brain, engine, and the decision trace:
`TOOLS` (OpenAI function schemas for slot_fill/kb_lookup/quote_price/escalate; slot_fill's `field`
is enumerated from `taxonomy.SLOT_FIELDS` so the brain can't name a fake slot), a `RouterAction`
enum (greet/ask/answer/quote/escalate/end), and `BrainDecision` (action, utterance, reason,
confidence, slots, leaf, kb_sources, quoted_amount) with a `.trace()` that flattens to the
`Decision` row fields (R9). `quote_price.leaf` is optional — the engine will authoritatively
resolve the leaf from slots. Tests: `tests/test_contract.py` (3). `ruff` clean.

## 2026-05-28 — IR2-T2: the classifier brain (agent/brain.py)

Two brains behind a `Brain` protocol; `get_brain()` picks by `settings.openai_enabled`:
- **OpenAIBrain** — bounded tool-calling loop (MAX_TOOL_ROUNDS=5). The model calls
  slot_fill/kb_lookup/quote_price/escalate; engine-side executors enforce rails.
- **RuleBrain** — deterministic keyword slot-fill + next-question; no network. Drives tests +
  offline self-play so the suite runs without an OpenAI key.

**Decisions:**
- **Quote gate is deterministic (R5b/R6), not model-confidence.** `quote_price` only returns a
  price when `resolve_leaf(slots)` is non-None; a premature call returns `NOT_READY` so the model
  asks instead. This makes "never quote before the leaf is known" a server-side guarantee
  independent of model behavior.
- **kb_lookup goes through `knowledge.answer_question`** (TF-IDF today) so IR-3 can swap the
  retriever underneath without touching the brain. Returns `NO_APPROVED_CONTENT` to the model when
  ungrounded, so it gives the honest fallback rather than inventing.
- RuleBrain folds caller-volunteered subjects/tests directly to a leaf (e.g. "chemistry" ->
  tutoring/science/chemistry -> quote), and asks the next disambiguating question otherwise;
  ambiguous input ("struggling in school") -> category question (no guess).
Tests: `tests/test_brain.py` (8), incl. a fake-client OpenAIBrain tool loop + the premature-quote
gate. `ruff` clean.

## 2026-05-28 — IR2-T3: intent-router engine

New `app/agent/intent_engine.py` (`IntentRouterEngine`) drives the brain through the per-turn loop:
record prospect turn -> `brain.decide` -> mis-quote guard -> advance slots/leaf/price -> emit KPI
events -> record decision trace -> record agent turn. **Decision:** added a NEW engine alongside the
legacy `ConversationEngine` rather than mutating it in place, so the old machinery + its tests stay
green until the IR-6 teardown (per the build plan sequencing rule). IR-4 points voice + simulator at
this engine.
- **Schema (migration-recreate caution):** added `Decision.slots`/`Decision.leaf` and
  `Call.reached_leaf`/`Call.quoted_price` (additive, nullable). Existing dev DB must be recreated;
  tests create tables fresh so unaffected.
- **Recorder:** added `record_brain_decision()` and `record_result()`.
- **Mis-quote enforcement (R6):** if `check_mis_quote` fires (a price with no authorized amount, or
  a mismatch), the engine substitutes the safe handoff, flips the action to ESCALATE, and emits
  `MIS_QUOTE_BLOCKED`. `LEAF_REACHED` fires once per call; `CLARIFY_ASKED` on ASK turns.
- Low-confidence STT turns ask the caller to repeat without invoking the brain (parity w/ old engine).
Tests: `tests/test_intent_engine.py` (4). Full suite **216 passed**; `ruff` clean.

## 2026-05-28 — IR3-T1: embeddings + SQLite store (sqlite-vec blocked locally; see D-17)

Verifying IR3-T1 early surfaced the flagged risk for real: the dev Python has no
`enable_load_extension`, and `pysqlite3-binary` has no wheel here, so `sqlite-vec` can't load
locally. Per D-17 we build the dev path now and keep sqlite-vec for the GCP/Docker prod build.
- `app/kb/embeddings.py`: pure-Python float32 (de)serialize (little-endian, sqlite-vec-compatible
  bytes), `cosine`, `Embedder` protocol, `OpenAIEmbedder` (batched), `get_embedder` (None offline).
  No numpy dependency added (corpus is tiny — pure-Python cosine is instant).
- `db/models.py`: new `KBEmbedding` table (chunk_id, source, title, text, model, dim, embedding
  BLOB) — the vector store lives in the same SQLite DB so prod sqlite-vec can read the same rows.
Tests: `tests/test_embeddings.py` (4). `ruff` clean.

## 2026-05-28 — IR3-T2: vector ingest + retriever

`kb/vector_retriever.py`: `build_index(session, embedder, chunks=None)` reuses the markdown chunker,
embeds chunks, and (re)persists `KBEmbedding` rows (wipes+reinserts, so rebuild is idempotent).
`VectorRetriever` loads the rows into memory and ranks by cosine — a drop-in for `KBRetriever`
(same `retrieve(query, *, k, min_score) -> list[RetrievedChunk]`). Wired `knowledge`:
`get_default_retriever()` prefers the vector retriever when an embedder + populated index exist,
else TF-IDF; `answer_question`'s `min_score` now defaults to the retriever's own
`default_min_score` (TF-IDF 0.45, vector 0.30) so the two score scales don't collide. Offline /
no-key / empty-index / any-error -> TF-IDF (existing knowledge+kb tests unchanged). Tests:
`tests/test_vector_retriever.py` (6) with a deterministic fake embedder. Full suite **225 passed**.

## 2026-05-28 — IR3-T3: explainer KB content

Added `data/kb/test_prep_overview.md` (SAT vs ACT, what the PSAT is) and
`data/kb/subjects_overview.md` (math/science tutoring, what a session involves) — clearly-labeled
PLACEHOLDER copy for the router's informational Q&A. Prices intentionally stay in
`data/pricing/pricing.yaml`, not the KB (R6). Existing TF-IDF ranking tests (`test_kb`) still pass
with the two new docs (pricing/scheduling/formats queries still rank their own doc top). KB now 22
chunks. Phase IR-3 complete.

## 2026-05-28 — IR5-T1: ground-truth router personas

Added `target_leaf` + `opening_line` to `Persona` (additive; legacy discovery personas untouched)
and `PersonaLibrary.router_personas()`. Appended 10 router personas to `personas.yaml` covering all
8 leaves, mixing explicit openers ("get my daughter ready for the SAT") with deliberately vague
ones ("struggling in school" -> algebra; "science help" -> chemistry; "do you offer tutoring?" ->
geometry) so the benchmark exercises disambiguation. Tests: `tests/test_router_personas.py` (3),
incl. full-leaf coverage. `ruff` clean.

## 2026-05-28 — IR5-T2: accuracy benchmark + router KPIs

`simulator/benchmark.py`: runs router personas through the real `IntentRouterEngine` in text mode
with a deterministic `RouterProspect` (opens with `opening_line`, reveals the leaf's components as
asked — fully offline), then scores **Classification Accuracy**, median **Turns-to-Classification**,
quote/price-correct/mis-quote/escalation rates. `kpis/metrics.py` gains `compute_router_metrics()`
for the DB-derivable rates the dashboard can show on any call (accuracy needs ground truth, so it
lives in the benchmark report, not the DB query). Added a `mis_quote_count` to the engine for the
per-call result. **Offline result: 100% accuracy / 0% mis-quote across all 10 personas** — proves
the harness + metric end-to-end (a meaningful score needs the OpenAIBrain). Created the new module
rather than rewriting the old scoring.py/metrics.compute_metrics (those go in IR-6). Tests:
`tests/test_benchmark.py` (5). Full suite **233 passed**; `ruff` clean.

## 2026-05-28 — IR5-T3: router improvement loop

`simulator/improvement.py`: `run_improvement(baseline_brain, candidate_brains)` runs each over the
accuracy benchmark and `decide_promotion` promotes a candidate only when **Classification Accuracy
strictly improves AND neither mis-quote nor price-correctness regresses**; promotion stays
human-approved (returns a report/decision, flips nothing). A variant is a brain config — `OpenAIBrain`
gained a `prompt_delta` so live variants are real prompt tweaks; offline tests inject deterministic
stand-in brains. Built fresh rather than refactoring the old objection-recovery `experiments/*`
(removed in IR-6). Tests: `tests/test_improvement.py` (3). Phase IR-5 complete. `ruff` clean.

## 2026-05-28 — IR4-T1: voice bot on the intent-router engine

Rewired `voice/bot.py` to build an `IntentRouterEngine` (brain = OpenAI when keyed, else offline
RuleBrain) instead of the old Orchestrator + DiscoveryDecider + LLMExtractor + synthesizer.
`EngineProcessor`/pipeline construction unchanged (open/run_turn/end + result.utterance are
drop-in). `guard_output` keeps the §18 human-claim/guarantee block; the engine already makes the
utterance mis-quote-safe. `build_engine` simplified (brain + recorder + known_fields seeding); the
lead write-back-on-end was dropped (the router doesn't produce lead-profile fields) — known-field
seeding at call start still gives skip-known. Rewrote `tests/test_bot.py` for the new wiring (the
synthesizer tests move out — `synthesis.py` is removed in IR-6).
- **Deferred (R12, needs live audio):** the `STTMuteFilter(ALWAYS)` that fixed self-listening is
  kept as-is; refining it to honor genuine barge-in while suppressing echo requires a real
  mic/keys call to tune and is left as a live-validation follow-up.
Full suite **232 passed**; `ruff` clean.

## 2026-05-28 — IR4-T2: simulator on the brain

Brain-driven self-play is delivered by `simulator/benchmark.py` — `RouterProspect` drives the same
`IntentRouterEngine` + brain as a live call (R10), so the improvement loop tests the real path.
Made the prospect **injectable** (`run_router_call(prospect=...)`, `run_benchmark(prospect_factory=...)`)
so a live LLM-driven caller can plug in for a realistic score while the deterministic prospect keeps
the offline benchmark/tests hermetic. No new runner needed; the old `simulator/runner.py` (Claude
self-play through the discovery-to-close engine) retires in IR-6. Test: pluggable-prospect case.
Phase IR-4 complete.

## 2026-05-28 — IR6-T1: delete the discovery-to-close machinery

Removed the old brain + its tests now that voice + self-play run on the router engine (IR-4).
**Reordered IR-4 before IR-6** (the plan's own sequencing rule): the teardown is only safe once
nothing imports the old modules.
- **Deleted (app):** `agent/{decisioning,discovery,closing,objections,extraction,orchestrator,
  engine,router,render,synthesis}.py`, `simulator/{runner,scoring}.py`, the whole `experiments/`
  package, and `data/playbooks/{discovery,objections}.yaml`.
- **Deleted (tests):** 13 files covering the above.
- **Kept (vestigial, on purpose):** `agent/persona.py` + `agent/stages.py` — still imported by the
  reused `versioning.py` (version hash) and `voice/pipeline.py` (legacy raw-Claude builder); deleting
  them forces needless surgery. `versioning` handles the now-empty playbook dir gracefully
  (`pb-none`). The `Experiment`/`Variant` ORM models are retained (schema) though no longer driven —
  removing them is a migration, deferred.
- **Edited survivors:** `recorder.py` lost `record_decision(NextAction)` + `record_close_attempt` +
  the closing/orchestrator imports. Trimmed/rewrote `test_{lead_store,transcript,guardrails,
  knowledge,kpis,dashboard}.py` to drop old-engine setup and exercise the router engine instead.
Full suite **127 passed**; `ruff` clean across app + tests.

## 2026-05-28 — IR6-T2: dashboard API fields

Extended `dashboard/router.py`: call summaries now include `reached_leaf` + `quoted_price`; the
decision trace serializes `slots` + `leaf`; added `GET /api/router-metrics` (compute_router_metrics).
This is the read API the IR-7 React dashboard consumes — classification accuracy still comes from the
benchmark report (needs ground truth), not this endpoint. Tests extended in `test_dashboard.py`
(router fields + new endpoint). `ruff` clean.

## 2026-05-28 — IR6-T3: docs + deploy reconcile

Rewrote `README.md` to the intent-router scope (what it does, architecture, quick start with
`OPENAI_API_KEY`, benchmark instead of the old experiments command, docs table). Bannered
`docs/PRD.md` as superseded scope (pointing at the requirements doc + new build plan), matching the
earlier `BUILD_PLAN.md` banner. Added a core-backend `Dockerfile` (one-command run, no voice extra)
and `docs/DEPLOY.md` (local Docker + GCP Cloud Run, with the SQLite-ephemeral + sqlite-vec-in-prod
notes). Phase IR-6 complete.

## 2026-05-28 — IR7-T1: turn-latency instrumentation

Added `Turn.latency_ms` (additive nullable; migration-recreate caution). The engine times the brain
decision + its tool calls (`time.perf_counter` around `brain.decide`) and stamps the agent reply
turn. `compute_router_metrics` now returns `turn_latency_ms_p50/p95` (nearest-rank percentile helper).
This closes the long-standing "latency never measured" gap (old `average_latency_seconds=None`) for
the brain/tool cost. **Deferred (needs live audio):** the STT-final → first-TTS-audio span in the
voice path. Tests: latency recorded + rolled up. `ruff` clean.

## 2026-05-28 — IR7-T2: live event bus + SSE stream

`app/events.py` — a neutral in-process pub/sub (`bus`). Each `Subscription` captures its event loop;
`publish` is thread-safe (`call_soon_threadsafe`), so the recorder can emit from a voice worker
thread and FastAPI's loop receives it. With no subscribers, publish is a no-op (zero cost in
tests/offline). The recorder now publishes **call_started / turn / decision / kpi / call_ended**.
Dashboard gains dependency-free SSE endpoints `GET /api/stream` and `GET /api/calls/{id}/stream`
(StreamingResponse + manual `data:` framing, keepalive every 15s, unsubscribe on disconnect) — no
sse-starlette dependency. Tests: bus pub/sub + call-id filter + recorder-publishes-lifecycle
(async). Full suite **132 passed**; `ruff` clean.

## 2026-05-28 — IR7-T3: simulated live feed

`simulator/live_feed.py` `run_sim_call_paced(persona)` drives a router persona through the real
engine in the background, **paced** (default 1.2s/turn) with sync engine work in `asyncio.to_thread`
so the SSE stream stays live. Dashboard: `POST /api/sim/start {persona?}` launches it via
`asyncio.create_task` (defaults to the first persona); `GET /api/sim/personas` lists the 10
ground-truth personas. This is the "calls come in" demo driver — no mic, no Twilio; offline it uses
the RuleBrain, with a key the OpenAIBrain. Tested the paced runner directly (StaticPool session) +
the personas endpoint; `/sim/start`'s background task isn't exercised via TestClient (it would hit
the real DB + sleep). `ruff` clean; 7 passed.

## 2026-05-28 — IR7-T4: React dashboard scaffold

Vite + React app in `frontend/dashboard-app/` (`base: /dashboard/`, dev proxy to :8000). `src/api.js`
wraps the REST endpoints + an `EventSource` SSE subscription; the App shell shows a persona picker +
"Start simulated call" (POST /api/sim/start) and a live event feed. Built to `dist/`; `main.py` now
serves the built app at `/dashboard` (falls back to the legacy static page if no build). `dist` is
committed so `/dashboard` works from a clone without npm; `node_modules` gitignored. `npm run build`
succeeds (Vite 5). Backend tests unaffected (7 passed).

## 2026-05-28 — IR7-T5: live call board + transcript

`useLiveCalls` hook reduces the SSE stream (+ initial /api/calls load) into a live map of calls
(turns, decisions, reached leaf, quoted price, last latency, mis-quote count). `CallBoard` renders
active/recent call cards (channel, live/ended, leaf, price, latency, mis-quote flag); `CallDetail`
shows streaming prospect/agent transcript bubbles + the per-turn decision trace (action, confidence,
slots, leaf), fetching the snapshot for historical calls and streaming live ones. App is now a
two-pane board+detail layout. `npm run build` succeeds.

## 2026-05-28 — IR7-T6: insights panel + end-to-end smoke

`InsightsPanel` polls `/api/router-metrics` (every 4s) and shows tiles: active calls (live),
total calls, leaf-reached / quoted / escalation / mis-quote rates (mis-quote red when >0), and
turn-latency p50/p95. Classification accuracy stays a benchmark artifact (needs ground truth), not
a live tile. **End-to-end smoke (offline RuleBrain, real uvicorn):** `/health` ok, `/dashboard/`
serves the built app (200), `POST /api/sim/start` → call classified `tutoring/science/chemistry`,
quoted $80, `/api/router-metrics` reported leaf_reached 1.0 / mis_quote 0.0 / latency p50 6.7ms.
Phase IR-7 dashboard (T4–T6) complete; T7 (Twilio) remains deferred.

## 2026-05-28 — IR7-T7: Twilio inbound (deferred, as planned)

Left as a documented follow-on per the build plan (stretch / not a v1 blocker). It needs a real
Twilio account + number and a Media Streams ↔ Pipecat-STT bridge that can only be validated against
live telephony, so it isn't built here. **Design when picked up:** a Twilio Voice webhook returns
TwiML that opens a Media Stream to a WS endpoint; the inbound audio feeds the existing Pipecat STT
path (same `IntentRouterEngine`), and the call surfaces on the live SSE stream tagged
`channel="twilio"` — no dashboard changes needed (it already renders any channel). Everything else in
the plan (IR-0 … IR-7 T1–T6) is implemented, tested, and committed.

### Build complete — summary
25 of 26 tickets done (IR7-T7 intentionally deferred). Backend: `ruff` clean, **134 passed**.
Frontend: Vite build succeeds; full-stack smoke verified (sim call → classify → quote → metrics).

## 2026-05-28 — IR7-T7: Twilio inbound bridge (implemented)

Built now that keys are available. `voice/twilio_bot.py`: `run_twilio_bot` accepts the Media Streams
WebSocket, reads Twilio's start frame (streamSid/callSid), and bridges audio via
`TwilioFrameSerializer` + `FastAPIWebsocketTransport` into the **same** STT → `IntentRouterEngine`
→ TTS pipeline as the web demo (STTMuteFilter + guard_output reused). Calls record with
`channel="twilio"`, so they appear on the dashboard with no UI change. Routes in `voice/server.py`:
`POST /voice/twilio` returns `<Connect><Stream>` TwiML (wss URL from `PUBLIC_BASE_URL` or the request
host); `WEBSOCKET /voice/twilio/ws` runs the bridge. Config: `twilio_account_sid`/`twilio_auth_token`
(optional) + `public_base_url`. No `twilio` SDK dependency — TwiML is hand-written and auto-hangup is
off (call ends on caller hangup). Setup steps in `docs/DEPLOY.md`.
- **Validated:** construction tests (TwiML, ws-url derivation, webhook XML) + a live-server smoke of
  the configured webhook returning the correct `<Stream>` TwiML. **Still needs a real inbound call**
  to validate the audio loop + telephony sample-rate/echo tuning (can't be done without a phone).
Full suite **139 passed**; `ruff` clean. All 26 tickets now implemented.

## 2026-05-29 — KB vector index build CLI + built

The KB lookup was wired (brain kb_lookup -> answer_question -> retriever) and content present (22
chunks), but `kb_embeddings` was empty so it ran on the TF-IDF fallback. Added `app/kb/index.py`
(`python -m app.kb.index`) to embed the docs with `text-embedding-3-small` and persist to SQLite,
and built it (22 chunks). `get_default_retriever()` now returns `VectorRetriever`; verified semantic
matches on paraphrases ("my kid keeps failing chem tests" -> subjects_overview). The index lives in
the gitignored DB, so it must be rebuilt per-environment (after DB recreate / KB edits); documented
in the README quick start. No OpenAI key -> clean TF-IDF fallback.

## 2026-05-29 — Dashboard catalog/explainer panel

Added "What the agent offers" to /dashboard: `GET /api/catalog` returns the taxonomy (Test Prep:
SAT/ACT/PSAT vs Tutoring: math/science → subjects), each leaf with its authoritative price + the
KB-sourced summary; tutoring grouped by subject area. Frontend `Catalog.jsx` renders it as a
two-column reference panel. Also fixed `test_get_default_retriever_falls_back_to_tfidf` to be
hermetic (monkeypatch the embedder) — it had assumed no-key/empty-index, which broke once the dev
env had an OpenAI key + a built KB index. ruff clean; 140 passed.

## 2026-05-29 — IR-8 Test Call (your voice → routing → speaker, in-dashboard)

Added a **"Start Test Call"** control to /dashboard so an operator can drive the real voice path
with their own mic instead of scripted personas. **Backend was already built** — the standalone
`/demo` client + `POST /voice/offer` → `run_bot` (Deepgram STT → IntentRouterEngine → Cartesia TTS)
do the whole loop. So IR-8 is frontend-only: ported the WebRTC signaling from `frontend/client.js`
into a React hook (`useTestCall.js`) + a `TestCall.jsx` control beside "Start simulated call".

- **Reuse over rebuild:** no backend changes. `run_bot` records `channel="web"`, so a test call
  auto-appears on the IR7 call board with its live transcript + decision trace (App.jsx already
  auto-focuses the newest active call). The component deliberately shows only start/stop + status.
- **Plain connect (per product decision):** dropped the dial/ring SFX and energy-based "pickup"
  detection from client.js; status goes `idle → checking → connecting → connected` (the moment the
  agent track arrives) → `ended/error`. Simpler for an internal test tool.
- **Config gating:** `start()` calls `/voice/status` first; if not ready it shows "Voice not
  configured — missing: …" and stays idle (needs the `voice` extra + DEEPGRAM/CARTESIA/LLM keys).
  Mic-permission denial (NotAllowedError) surfaces a clear inline message.
- **Bug caught in review:** detach `ontrack`/`onconnectionstatechange` before `pc.close()` in
  teardown — otherwise the resulting `closed` state change was misread as an unexpected drop and
  overwrote a clean hang-up with an error.
- **Dev proxy:** added `/voice` to the Vite proxy (was `/api`-only); prod is same-origin under
  FastAPI so no prod change.
- **Constraints / follow-ups:** `getUserMedia` needs a secure context (localhost or HTTPS). Client
  allows one active test call at a time (button disables while live); no server-side concurrency cap
  added. No automated voice tests exist — validated via `npm run build`; needs a manual smoke
  (speak, hear the agent, confirm the call + decision trace on the board).

## 2026-05-29 — IR-8 fix: Test Call "addTrack on a closed RTCPeerConnection"

`start()` does two awaits (`/voice/status`, `getUserMedia`) before `addTrack`. Under React
StrictMode (dev mounts → cleanup → remounts), HMR, or a fast unmount, the effect cleanup calls
`stop()` and closes the pc *during* an await, so `addTrack` then ran on a closed connection.
Fix: a generation token (`genRef`) bumped by every start/stop; `start()` captures its value and
bails after each await if superseded — releasing the mic and closing the orphaned pc instead of
touching it. Also guards the `catch` so a superseded attempt can't overwrite state with an error.
Root cause was async setup not tolerating teardown, not the WebRTC logic itself.

## 2026-05-29 — Fix: inflated turn-latency p95/p50 (percentile bug)

`_percentile` used `round((pct/100)*N + 0.5) - 1` as a nearest-rank ceil, but Python's `round()` is
banker's rounding, so it biased the index high — p95 of 20 turns returned the max, p50 of 2 returned
the larger value. That's why p95 looked wrong (it tracked the single slowest turn, usually the
cold-start first turn). Replaced with `math.ceil((pct/100)*N) - 1` and pinned it with a unit test.
Caveats noted but NOT changed: the dashboard's latency tiles pool **all calls** (synthetic included,
no time window) and `latency_ms` times only `brain.decide()`, not end-to-end STT→TTS (the IR7-T1
stt/brain/tts breakdown in voice/bot.py was never added). Flag for a follow-up if we want per-call
or end-to-end latency.

## 2026-05-29 — PAY-0: payments config + feature flag

Starting BUILD_PLAN_PAYMENTS. PAY0-T1: added `stripe>=9.0` to **core** deps (pure-Python, no
native build — unlike the heavy `voice` extra, so no separate extra needed) and config fields
`stripe_api_key`, `stripe_webhook_secret`, `payments_currency="usd"`, plus `twilio_from_number`
(E.164 SMS sender, needed in PAY-1). Added `payments_enabled` (= `bool(stripe_api_key)`) and
`sms_enabled` (Twilio SID+token+from-number) properties. Decision: stripe in core deps, not an
optional extra, so the PAY-1 service + its fake-client tests are importable everywhere; the flag is
the KEY, not the package. Flag off by default → behavior unchanged (payment asks still escalate).
Full suite 141 passed; ruff clean.

## 2026-05-29 — PAY1-T1: Stripe service

`app/payments/stripe_service.py`: `StripeService.create_payment_link/create_invoice` behind a
`StripeGateway` seam (real `_StripeApiGateway` wraps the SDK; tests inject a fake — no network).
**Deviation from the plan signature:** dropped the `amount`/`currency` params and derive the amount
from the leaf's approved `PriceRecord` instead. Rationale: the price table is already the single
source of truth the mis-quote guard enforces, so no code path can request an arbitrary charge — a
stronger approved-price gate. Currency comes from `payments_currency`, lowercased for Stripe.
- Approved-price gate refuses unapproved (all current placeholders) and unpriced leaves with
  `PaymentError` before any Stripe call. Since pricing.yaml is `approved: false`, **every leaf is
  refused today** — intended; real charges need approved prices (PAY-6 verifies this).
- Idempotency keys are passed on every write; the invoice/link flows derive per-step keys
  (`:price`, `:link`, `:customer`, `:item`, `:invoice`) so multi-call flows stay idempotent.
- Payment Links need a Price object, so the link flow creates an ad-hoc one-off Price then the link;
  quantity is fixed at 1 (packages/booking-quantity out of scope for this slice).
5 tests (fake gateway); ruff clean.

## 2026-05-29 — PAY1-T2: Twilio SMS sender

`app/payments/sms.py`: `TwilioSmsSender.send(to, body) -> sid` via the Twilio Messages REST API
(HTTP basic auth). Used **stdlib urllib** rather than httpx/requests — httpx is only a dev/transitive
dep, and stdlib keeps this zero-new-dependency and matches the voice bridge's "raw REST, no SDK"
choice. HTTP POST sits behind an injectable `post` seam so tests run offline. `get_sms_sender`
raises `SmsError` when `sms_enabled` is false (needs SID + token + from-number). SMS failures are
defined as **non-fatal** (the link still exists / shows on the dashboard; the caller just isn't
texted) — the engine will treat them that way in PAY-3. 5 unit tests; ruff clean.

## 2026-05-29 — PAY2-T1: Payment model + recorder

Added the `Payment` table (`payment_id`, `call_id`, `leaf`, `amount`, `currency`, `provider`,
`kind` link|invoice, `provider_ref` [indexed], `url`, `status` created|sent|paid|failed,
`created_at`, `paid_at`) + a `Call.payments` relationship. `CallRecorder.record_payment(...)`
persists + publishes `payment_sent`; `mark_payment_paid(session, provider_ref)` flips to paid +
publishes `payment_paid`.
- **Deviation:** `mark_payment_paid` is a **module-level function**, not a recorder method — the
  Stripe webhook (PAY-4) resolves payments globally by `provider_ref` with no call recorder in
  scope. Made it **idempotent** (a row already `paid` is returned unchanged) so a duplicate webhook
  can't re-fire `payment_paid`; unknown ref → None (webhook no-op).
- **Migration:** this is a NEW table, so `init_db()`/`create_all` adds it additively on next boot —
  no destructive dev-DB recreate needed (that caution applies to added *columns*, not new tables).
Full suite 155 passed (+14 payment tests); ruff clean.

## 2026-05-29 — PAY3-T1: send_payment_link tool contract

contract.py: added `TOOL_SEND_PAYMENT_LINK` + `PAYMENT_TOOL` schema (`kind` link|invoice, optional
`phone`), `RouterAction.PAY`, a `PaymentRequest` dataclass, and `BrainDecision.payment_request`.
**Design:** the payment tool is kept OUT of the base `TOOLS`; `tools_for(payments_enabled)` adds it
only when enabled, so with the flag off the model never even sees the tool (flag-off path
unchanged). The brain stays DB/IO-free — it only sets `payment_request`; the engine (PAY3-T2)
executes the side effects. Updated test_contract to validate the full set + that the tool is gated.

## 2026-05-29 — PAY3-T3: guardrail reconcile + payment KPIs (done before T2)

Did the guardrail reconcile before the engine executor since the brain/engine depend on it.
Split the PAYMENT escalation cues: **card-data** ("card number", "credit card", "bank account", …)
ALWAYS escalates (PCI — never take a card number in-call), while pay/invoice **intent** is now a
separate `detect_payment_intent(text) -> 'link'|'invoice'|None`. `detect_escalation` gained a
`payments_enabled` flag: when off, pay-intent still escalates (flag-off behavior unchanged); when
on, pay-intent is left for the engine to route to the payment flow, but card-data still escalates.
Added KPI constants `PAYMENT_LINK_SENT`, `PAYMENT_COMPLETED`.
- Minor: when multiple cues co-occur and payments are off, the attributed escalation *code* may
  differ from before (pay-intent now checked after the cue loop), but the outcome (escalate) is
  unchanged. Cosmetic only.
4 new guardrail tests; full guardrail suite 11 passed; ruff clean.

## 2026-05-29 — PAY3-T2: brain + engine payment executor

Wired the live flow. Brain (both impls): after a leaf is confirmed and the caller wants to pay,
the brain sets `BrainDecision.payment_request` and returns `action=PAY` (RuleBrain via
`detect_payment_intent`; OpenAIBrain via the `send_payment_link` tool, gated on a resolved leaf).
The brain stays IO-free — no Stripe/DB/SMS in it. The OpenAI system prompt only mentions the payment
tool when `payments_enabled`, and `tools_for()` only exposes it then.
Engine (`_maybe_execute_payment`): creates the link/invoice via `StripeService`, best-effort texts
it (`get_sms_sender`), records the `Payment`, emits `PAYMENT_LINK_SENT`, and composes the spoken
confirmation. Design choices:
- **Failure = safe escalation:** a `PaymentError` (e.g. unapproved/placeholder price) turns the turn
  into `ESCALATE` with the standard handoff — the agent never states/charges an unauthorized price.
- **SMS is non-fatal:** no phone or SMS failure → status `created` (link still recorded + shown on
  the board) rather than erroring the call.
- **Confirmation states no dollar amount**, so the mis-quote guard stays clean on the PAY turn.
- **Idempotency key** = `{call_id}:pay:{turn_id}` so a retried turn can't double-charge.
- Phone: `payment_request.phone` else `engine.caller_number` (Twilio `From`, plumbed later).
- Injectable `stripe_service` / `sms_sender` on the engine for offline tests.
2 e2e tests (RuleBrain + fake Stripe + fake SMS): pay-after-quote records+texts+emits KPI;
unapproved price escalates and charges nothing. Full suite 162 passed; ruff clean.

## 2026-05-29 — PAY4-T1: Stripe webhook (source of truth for "paid")

`app/payments/webhook.py` — `POST /payments/webhook`, mounted in main.py. Verifies the Stripe
signature with `STRIPE_WEBHOOK_SECRET` (503 if unconfigured, 400 on a bad signature), then on
`checkout.session.completed` (provider_ref = `payment_link`) or `invoice.paid` (provider_ref = `id`)
calls `mark_payment_paid` → publishes `payment_paid` to the SSE bus. Other event types → `ignored`;
unknown ref → `unknown_ref`.
- **Idempotency:** leaned on `mark_payment_paid`'s already-paid no-op rather than persisting event
  ids in a new table — a duplicate webhook for a paid row is a harmless no-op. Documented as a
  deliberate simplification.
- **Testability:** signature verification is a module function `_verify_event` that tests
  monkeypatch with a constructed event (no payload signing). 4 tests (checkout/invoice paid, unknown
  ref, unhandled type). Full suite 166 passed; ruff clean.

## 2026-05-29 — PAY5-T1: dashboard payment surface

Backend: `/api/calls` summary now carries the latest `payment` (status badge), `/api/calls/{id}`
carries the full `payments` list, and `/api/router-metrics` rolls up `payments_sent`,
`payments_paid`, `paid_rate`, and `revenue` (paid amounts). Frontend: a 💳 badge on the call card
(amber link/invoice sent → green paid), a Payments section in the call detail (status + clickable
hosted URL), two insights tiles (paid %, revenue), and live `payment_sent`/`payment_paid` SSE
handling in useLiveCalls so the board updates without a refresh. Build passes; backend 167 passed;
ruff clean. Completes the PAY-3→PAY-5 slice; PAY-6 (safety re-verify + DEPLOY docs) remains.

## 2026-05-29 — PAY6-T1: safety re-verify + deploy docs (payments complete)

Safety: added `test_shipped_pricebook_blocks_every_leaf_until_prices_are_approved` — loads the real
`data/pricing/pricing.yaml` (ships `approved: false`) and asserts the gate refuses a charge for
EVERY leaf and never calls Stripe. This pins the "placeholder prices are never chargeable" anchor.
Docs: added a Payments section to `docs/DEPLOY.md` — the two gates (STRIPE_API_KEY + approved
price), the placeholder-price warning, `.env` setup (Stripe test keys, Twilio SMS), local webhook
via `stripe listen --forward-to localhost:8000/payments/webhook`, and out-of-scope items
(refunds/tax/discounts/booking-quantity → specialist; card numbers never taken in-call).
Full suite 168 passed; ruff clean. BUILD_PLAN_PAYMENTS PAY-0..PAY-6 all implemented.

## 2026-05-29 — PAY7-T1: dev fake payments mode

Added `PAYMENTS_FAKE` (dev-only) so the billing flow works with NO Stripe/Twilio keys and no real
charge — needed to demo the link from a web Test Call. `payments_enabled` is now
`bool(stripe_api_key) or payments_fake`. `app/payments/fakes.py`: `FakeStripeGateway` (deterministic
`https://…example.test/fake/…` links, no network) + `FakeSmsSender` (no-op). `get_stripe_service`
returns the fake with `allow_unapproved=True` in fake mode; `get_sms_sender` returns the fake when
fake mode is on and Twilio isn't configured.
- **Safety preserved:** `allow_unapproved` defaults False; only the fake-mode factory sets it, so
  the REAL Stripe path keeps the strict approved-price gate (the PAY-6 test still holds). Fake links
  are obviously non-real (`example.test`).
3 tests; full suite 171 passed; ruff clean.

## 2026-05-29 — PAY7-T2: in-call billing link + text-it endpoint

Backend: `POST /api/calls/{id}/send-payment-sms {phone}` texts the call's latest payment link (uses
the fake SMS sender in dev fake mode, else Twilio); flips the payment to `sent` and re-publishes
`payment_sent` so the board updates. Frontend: `App` finds the Test Call's own web call (newest web
call that's live or has a payment) and passes it to `TestCall`, which now renders a **Billing link**
panel — click-to-open URL + a phone field/“Text link” button (and a paid ✓ state). A browser mic
call has no caller ID, hence the explicit phone entry. `api.sendPaymentSms` surfaces error detail.
Caller-ID auto-text on real Twilio calls is still a follow-on (From not yet plumbed via TwiML).
Backend 172 passed; frontend builds; ruff clean.

To try it end-to-end with no keys: set `PAYMENTS_FAKE=true` in backend/.env, start a Test Call, say
"I'll pay now" after the quote → a fake link appears in the panel (and on the board).

## 2026-05-29 — LAT-T1: end-to-end latency breakdown core

Closes the IR7-T1 gap (latency was brain-decision-only). Added `Turn.latency_breakdown` JSON
(stt/brain/tts) and made `latency_ms` the END-TO-END turnaround on voice turns. Pieces:
- `app/agent/latency.py` `compose_turn_latency(...)` — pure helper turning the four turn boundaries
  (user-stopped / transcript / brain-done / bot-started) into total + {stt,brain,tts}. Unit-tested.
- Engine: `RouterTurnResult` now carries `brain_ms` + `agent_turn_id`; `_emit_agent` returns the Turn.
- Recorder: `update_turn_latency(turn_id, latency_ms, breakdown)` — the voice path overwrites the
  brain-only timing with end-to-end once the agent's audio goes out.
- Metrics: `turn_latency_breakdown_ms` = mean stt/brain/tts across voice turns (null in text mode);
  p50/p95 now reflect end-to-end on voice.
- **Migration caution:** `latency_breakdown` is a NEW COLUMN on an existing table — `create_all`
  won't add it to an existing dev DB. Recreate `nerdy_sales.db` (and rebuild the KB index) before
  the next live run. Tests use fresh in-memory DBs.
Full suite 176 passed; ruff clean. Frame wiring that feeds the helper lands in LAT-T2.

## 2026-05-29 — LAT-T2: wire STT/brain/TTS boundaries into the voice pipeline

`EngineProcessor` (shared by web + Twilio, so one change covers both) now stamps monotonic
boundaries as frames flow: `UserStoppedSpeakingFrame` starts the clock, the transcript + brain
finish mark the middle, and the first `BotStartedSpeakingFrame` (agent audio out) closes it →
`compose_turn_latency` → `recorder.update_turn_latency`. The DB write runs via `asyncio.to_thread`
so it doesn't block the pipeline loop.
- **Needs real-call validation** (consistent with the rest of the voice path): the exact frame
  arrival timing can only be confirmed on a live call. The math (`compose_turn_latency`) and the DB
  path are unit-tested; this ticket is the frame plumbing that feeds them.
- With fillers on, the first agent audio may be the *filler*, so the measured tts/total reflects
  perceived time-to-first-audio — arguably the right thing for "low-latency voice interaction."
Pipeline still builds (test_voice_pipeline green); full suite 176 passed; ruff clean.

## 2026-05-29 — LAT-T3: surface latency breakdown on dashboard

InsightsPanel adds a "latency split (ms)" tile rendering the mean stt · brain · tts from
`router-metrics.turn_latency_breakdown_ms` (shows — until a voice call records a breakdown). The
p50/p95 tiles now reflect end-to-end voice turnaround. Completes the LAT slice: the latency
benchmark now measures the caller-perceived end-to-end turn, not just brain time. Build passes.

## 2026-05-29 — Voice in the container image + WebSocket path verified

Added `[voice]` to the Dockerfile so the Test Call + Twilio path run on the deployed image (was
core-only). Needed system libs: `build-essential` (purged after pip), `libsndfile1` (soundfile),
and — discovered during the build — the OpenCV runtime libs `libgl1 libglib2.0-0 libxcb1 libsm6
libxext6 libxrender1` (Pipecat's WebRTC transport pulls in cv2; first run failed on
`libxcb.so.1`).
Verified end-to-end at the container level:
- `docker build` succeeds (~7 min; image is large due to onnxruntime/aiortc/opencv).
- In-container import of `pipecat, aiortc, onnxruntime, cv2` + the full `app.voice.*` path + all
  voice routes register (`/voice/offer`, `/voice/status`, `/voice/twilio`, `/voice/twilio/ws`).
- Ran the container: `/health` ok, `/voice/status` serves (ready:false w/o keys).
- Real WS connect to `/voice/twilio/ws` → HTTP 403 (Starlette close-before-accept = the missing-keys
  guard fired), proving the route is live on the voice image.
Added `test_twilio_ws_route_rejects_when_voice_unconfigured` (TestClient WS, settings stubbed so
it's deterministic regardless of the dev env's real .env keys). Updated DEPLOY.md: image is
voice-enabled, deploy with `--max-instances 1 --timeout 3600` + voice keys, point Twilio webhook at
the service URL. **Still needs a real inbound call to validate the live audio loop.** Suite 177.

## 2026-05-29 — Cloud Run deploy fixes + Twilio caller-ID auto-text

Deployed to Cloud Run. Issues found + fixes on the live service:
- **Dashboard 404:** Dockerfile didn't COPY the built frontend → fixed (copies dashboard-app/dist +
  demo page).
- **Simulated call didn't stream live:** Cloud Run's default CPU throttling starved the background
  sim task + SSE. Fixed with `--no-cpu-throttling` (rev 00004); verified the full event sequence
  (call_started/turn/decision/kpi) now streams over /api/stream.
- **Browser Test Call (WebRTC) can't work on Cloud Run:** SmallWebRTC needs inbound UDP for media;
  Cloud Run only exposes one HTTP/WS port (logs showed ICE timeout). Architectural — the mic Test
  Call is local-only; the Twilio WebSocket path is the cloud voice path. Documented.
- **Twilio:** pointed the number's Voice webhook at `…/voice/twilio` (via the Twilio API).
- **Caller-ID auto-text:** `build_twiml` now passes the caller's `From` as a Stream `<Parameter>`;
  `server.twilio_voice` reads `From` from the urlencoded webhook body (stdlib parse_qs — no
  python-multipart dep); `_read_start` extracts `customParameters.from`; `build_engine` gains
  `caller_number`, so a phone caller who asks to pay gets the link texted to their number with no
  prompting. 178 tests; ruff clean. (Live audio loop still needs a real inbound call to validate.)

### 2026-05-29 — docs: AGENT_FLOW.md rewritten to as-built
- Replaced the pre-build mockup (11-stage state machine; `stage`×`selected_action`×`modifier`
  trace) with the shipped **intent-router** model: one bounded OpenAI tool-calling loop per turn
  (`brain.decide`), deterministic rails, and slot-filling against a fixed taxonomy → leaf. Added
  three as-built sections the build produced: how the call **decides** (RouterAction's 7 values,
  guardrails, payment path), how it **stores data** (SQLite tables, the Decision row, cross-call
  lead memory, version stamps, payment lifecycle), and how it **grounds answers in the KB
  vectorstore** (OpenAI `text-embedding-3-small` → `kb_embeddings` table, cosine top-k=3 @ 0.30,
  TF-IDF fallback, no-hallucination grounding; prices come from `pricing.yaml`, never the model).
- **Discrepancies recorded in the doc (not fixed here — docs-only change):**
  (1) `Call.model_version` stamps `settings.anthropic_model` (`claude-sonnet-4-6`) but the live
  brain runs OpenAI `gpt-4o` — leftover from the pre-pivot Claude design, mis-attributes the model.
  (2) `Decision.escalation_risk` column is defined but never written. (3) `Decision.stage` just
  mirrors `selected_action`; the legacy 11-stage enum is not populated. Logged as follow-ups in
  AGENT_FLOW.md §8.

### 2026-05-29 — VAD-T1: expose turn-taking (VAD) dials
- **Why:** the live agent "jumps in too soon." Root cause: both live paths built
  `SileroVADAnalyzer()` with no params, so endpointing used pipecat's default
  `VAD_STOP_SECS = 0.2` — only 0.2s of silence ends the caller's turn, which a normal
  mid-sentence breath trips. The brain never decided this; it's pure VAD timing.
- Added four dials to `Settings` (`vad_stop_secs`, `vad_start_secs`, `vad_confidence`,
  `vad_min_volume`) and a shared `build_vad_analyzer(settings)` in `voice/pipeline.py`, used by
  both `build_transport` (WebRTC) and `twilio_bot.py` so the two paths can't drift.
- **Deliberate deviation from pipecat default:** `vad_stop_secs` defaults to **0.6** (not 0.2).
  This is a behavior change — the agent now waits ~3× longer before treating a pause as
  end-of-turn. Trade-off: slightly less snappy, far fewer premature interruptions. Tune per the
  VAD-T2 replay harness; raise to 0.8–1.2 if it still interrupts, lower toward 0.3 for snappier.
- Tests: `test_vad_config_defaults`, `test_build_vad_analyzer_applies_settings`. 180 tests pass;
  ruff clean. (Perceived improvement still needs a real call to confirm — VAD-T2 makes the
  timing measurable offline first.)

### 2026-05-29 — VAD-T2: offline VAD replay harness
- **Why:** the text simulator (`simulator/benchmark.py`) feeds `engine.run_turn` strings and never
  runs audio/VAD, so it is structurally blind to "jumps in too soon." Endpointing can only be
  measured where the audio runs. The harness fills that gap without needing a phone.
- `app/simulator/vad_replay.py`: loads a WAV (stdlib `wave`+`audioop` handle width/stereo/rate so
  any clip works → 512-sample 16 kHz frames), feeds it one frame at a time into the **real**
  `SileroVADAnalyzer`, and collapses the per-frame `VADState` stream into caller turns. A turn ends
  when VAD returns to `QUIET` — the same signal the live agent acts on. `sweep_stop_secs` reuses
  the decoded frames across several `stop_secs` values and reports the turn count for each. CLI:
  `python -m app.simulator.vad_replay clip.wav --sweep 0.2,0.4,0.6,0.8,1.0`.
- **Decision — testing seam:** Silero confidence can't be driven from synthetic audio, so the
  segment/sweep logic is tested with a scripted fake VAD (`tests/test_vad_replay.py`), and the WAV
  loader with generated clips. The real Silero path is smoke-run manually (correctly reports 0
  turns on silence) and documented in RUNBOOK §11.4 — speech-detection accuracy needs a real clip.
- **Follow-up:** check in 2–3 recorded pause-heavy fixtures under `data/audio/` so the sweep has a
  canonical input, and consider asserting the real path against one in CI. 186 tests; ruff clean.

### 2026-05-29 — VAD-T3: revert tuning default + record per-call VAD params
- **Why (user decision):** the VAD-T1 default bump (`vad_stop_secs` 0.2→0.6) changed live
  turn-taking behavior, which the user did not want shipped before measuring. Reverted the value to
  **0.2** (= pipecat's default), so the live agent behaves exactly as before VAD-T1. Kept the dials
  and `build_vad_analyzer` — they're needed to record what each call used.
- **Record per-call params (for the dashboard evaluator):** added a `vad_params` JSON column to
  `Call`, a `Settings.vad_params()` helper, and stamped it via `CallRecorder` in both live paths
  (`run_bot`, `run_twilio_bot`). Text/synthetic calls leave it null (no audio/VAD).
- **Decision — schema self-heal:** this project has no migration tool (schema = `create_all`), and
  `create_all` never ALTERs existing tables, so an additive `_backfill_columns()` in `init_db`
  adds missing columns on SQLite (driven by `_ADDED_COLUMNS`). Idempotent; healed the committed
  dev DB. This is the migration-free pattern to reuse for future additive columns.
- Tests: `test_vad_params_shape`, `test_recorder_stamps_vad_params`, `test_db_backfill.py`. Updated
  `test_vad_config_defaults` (now 0.2). 190 tests; ruff clean.

### 2026-05-29 — VAD-T4: dashboard "Turn-taking (VAD)" evaluator panel
- **Decision (per user):** the "evaluate a call" button is the *light* path — no call-audio storage
  (audio still isn't captured; that was the rejected heavier option). The panel surfaces the VAD
  dials the call ran under and a ready-to-run `vad_replay` command + sweep, prefilled with them;
  the operator records their own clip (a `<your-clip.wav>` placeholder marks where it goes).
- Backend: `call_detail` now returns a `vad_eval` block (`_vad_eval` in `dashboard/router.py`):
  `params` (from `call.vad_params`, or the current config flagged `from_call: false` for pre-VAD-T3
  calls), a `command`, and a `sweep_command` whose values always include the call's own `stop_secs`.
- Frontend: `CallDetail.jsx` renders the panel on the fetched historical snapshot (a live call
  isn't over yet) with a small `CopyCommand` (clipboard + "Copied" feedback). Reuses existing CSS.
- Validation: 192 backend tests + `vite build` clean. **Manual check still useful:** open the
  dashboard, pick an ended voice call, confirm the panel shows the dials and Copy works (clipboard
  needs a secure/localhost origin).

### 2026-05-29 — VAD-T5: canonical VAD replay fixtures
- Closed the VAD-T2 follow-up: committed 3 fixtures under `data/audio/vad_fixtures/` so the
  evaluator has a stable input and the real audio→VAD path is tested end-to-end.
- **Decision — synthesized, not recorded:** I can't record a human voice, and Silero needs *real*
  speech (tones won't trip it), so fixtures are macOS `say` output (offline, no API keys) with
  `[[slnc ms]]` pauses, converted to 16 kHz mono PCM s16 via ffmpeg. Reproducible via
  `generate.sh`. Trade-off: synthetic prosody isn't identical to a real caller, but the pause
  structure — the thing that drives endpointing — is exactly controllable, which is what we need.
- Verified behavior through the real harness: `midsentence_pause` and `trailing_filler` split into
  2 turns at stop_secs ≤ 0.6 and merge to 1 at ≥ 0.8 (the "jumps in too soon" bug + its fix);
  `two_utterances` (control) stays 2 turns when relaxed.
- `tests/test_vad_replay.py` now asserts the **real Silero path** against the fixtures (on
  relationships, not exact counts, so a model bump won't be brittle; skips if fixtures absent).
  194 tests; ruff clean.

### 2026-05-29 — fix: generalize the schema self-heal (dashboard 500 on drifted DBs)
- **Bug found while reviewing VAD-T4 in the live dashboard:** `/api/calls` 500'd with
  `no such column: turns.latency_breakdown`. That column was added in LAT-T1 with no migration, so
  the committed dev DB (and any DB predating it) lacked it — unrelated to the VAD work, but it
  blocks the whole dashboard.
- **Fix:** generalized VAD-T3's `_backfill_columns` from a hardcoded one-column list to a
  model-driven heal — for every existing table, ADD COLUMN any column the SQLAlchemy model defines
  but the table lacks (type only, nullable; no FK/PK/constraints, all SQLite's ALTER reliably
  supports). Self-maintaining: future columns added without a migration heal automatically.
- **Trade-off:** healed columns lack FK/constraints on an old DB (SQLite has FKs off by default, so
  harmless); fresh DBs still get full schemas from `create_all`. Healed the committed dev DB.
- Tests: generic multi-column heal + a `turns.latency_breakdown` regression. Verified end-to-end by
  loading `/dashboard`, opening a call, and confirming the "Turn-taking (VAD)" panel renders with
  the dials + copyable commands. 195 tests; ruff clean.

### 2026-05-29 — VAD-T6: extend fixtures (longer, disfluencies, domain, edge cases)
- The VAD-T5 fixtures were minimal one-liners. Extended `generate.sh` to 7 realistically-long,
  domain-relevant clips (Nerdy tutoring sales) so the evaluator exercises real caller behavior:
  multi-sentence `midsentence_pause`, `trailing_filler`, `two_utterances` (control), plus new
  `disfluent_ums` (heavy um/uh + restarts), `chem_vs_bio` (long "chemistry or biology?" question),
  `payment` (incl. a spoken card/phone number), and `edge_short_turns` (one-word turns, long gaps).
- Measured turn counts through the real VAD (0.2→1.0): the aggressive 0.2 default shreds a single
  thought into many turns (`disfluent_ums` 10→1; `midsentence_pause` 6→1), while a larger
  `stop_secs` merges fillers/hesitations. `edge_short_turns` stays 3 at every value — its ~1.4s
  gaps exceed all `stop_secs`, proving the dial merges hesitation pauses, not deliberate turns.
- Tests: added real-VAD assertions for `disfluent_ums` (shred-then-ride-through) and
  `edge_short_turns` (deliberate turns survive); kept the midsentence/two-utterance ones (still
  hold). README has the full per-fixture table. 197 tests; ruff clean.

### 2026-05-29 — VAD-T7: make the evaluator panel channel-aware
- **Reported confusion:** running calls from the "Start simulated call" dropdown didn't change the
  Turn-taking panel. Root cause: those are *text* simulations (`run_sim_call_paced`, channel `sim`)
  — they drive the brain with strings and never run audio/Silero VAD, so there are no per-call VAD
  params. The panel's "predates per-call recording" fallback was misleading for them.
- Only the **voice** paths record VAD params: "Start Test Call" (browser mic → `run_bot`, channel
  `web`) and Twilio (`run_twilio_bot`). The sim dropdown is text-only by design.
- Fix: `_vad_eval` now returns `applicable` (True only for channels `web`/`twilio`) + `channel`.
  `CallDetail.jsx` shows a plain explanation for text sims ("no turn-taking to evaluate — use Start
  Test Call") instead of the dials/commands. Verified live: a `sim` call now renders the note.
- Tests: `test_vad_eval_not_applicable_for_text_sim_calls`; existing voice-call assertions gained an
  `applicable` check. 198 tests; ruff clean; `vite build` clean.

### 2026-10-06 — Build-quality audit, ticket 0004: real CI + formatting
- The untracked `.github/workflows/ci.yml` was a bun template (bun install/typecheck/test) that never
  applied to this Python repo — effectively no CI. Replaced with three jobs: `backend` (ruff check,
  ruff format --check, pytest; voice tests skip via `importorskip`), `backend-voice` (installs the
  heavy `[voice]` extra in its own job so a native-build break doesn't mask core failures), and
  `dashboard` (npm ci + vite build + `git diff --exit-code dist` — verified locally the build is
  byte-identical to the committed dist).
- Ran `ruff format` over the backend: 36 files, formatting only. 201 tests still pass.
- Not verified on GitHub Actions itself (branch not pushed).

### 2026-10-06 — Ticket 0005: pinned lockfiles + one Python version
- **Lockfiles via pip-tools** (user choice over uv): `backend/requirements/{prod,dev,dev-voice}.txt`
  compiled from `pyproject.toml`. `dev-voice` is the superset; the other two are compiled with it as
  a constraint so shared packages always match. Regenerate with `backend/scripts/lock.sh`.
  pip-tools added to the `dev` extra so the lock tool is itself pinned.
- **Python 3.12 everywhere** (`.python-version`, `requires-python>=3.12`, ruff `py312`, Dockerfile,
  CI). Chose 3.12 over the Dockerfile's 3.11 because 3.12 is what's installed locally — no
  interpreter download needed — and nothing in the deps blocks it. 3.13 is out: Pipecat 0.0.108
  imports `audioop`, removed in 3.13.
- **Surprise: the lock moved past the tested versions** (SQLAlchemy 2.1.3, stripe 16, fastapi
  0.142, openai 2.54). Full suite passes on fresh venvs built only from the locks (core: 174 passed
  + 5 voice modules skipped; voice: 201 passed). Raised floors to tested majors (`openai>=2.0`,
  `stripe>=15.0`, `fastapi>=0.115`). Dropped the unused `tomli` dependency (nothing imports it).
- **Transitive cap `numba<0.63`**: numba 0.63+ needs llvmlite 0.46+, which has no Intel-macOS wheel
  (verified: 0.46/0.47/0.50 have none; 0.45.1 does), so the voice extra failed to install on this
  machine. Cap replaces the RUNBOOK's manual llvmlite workaround.
- ruff `py312` target turned on new pyupgrade fixes: applied the safe ones (`datetime.UTC`,
  builtin `TimeoutError`); **ignored UP042** (str+Enum → StrEnum) because StrEnum changes
  `str()`/format output of members that flow into stored fields.
- Follow-up: the existing local `backend/.venv` is still Python 3.10 — recreate it with
  `python3.12 -m venv .venv` + the RUNBOOK steps. I validated in scratch venvs and left it alone.

### 2026-10-06 — Ticket 0001: HTTP Basic auth on operator surfaces
- **HTTP Basic** (user choice over a shared bearer token). Implemented as pure ASGI middleware
  (`app/auth.py`) rather than a FastAPI dependency so it also covers the StaticFiles mounts
  (`/dashboard`, `/demo`) and doesn't buffer SSE. No frontend change: browsers reuse cached Basic
  credentials for same-origin fetch/EventSource (all dashboard/demo calls are relative URLs).
- **Secure by default:** everything is protected except an exact-match allowlist — `/health`,
  `/voice/twilio`, `/voice/twilio/ws`, `/payments/webhook` (signature-authenticated). `/docs` and
  `/openapi.json` are now protected too.
- **Fail-closed rule:** password unset → open only when `ENVIRONMENT=development` (the default, so
  local dev + the existing suite are unaffected); any other environment → 503. The Dockerfile now
  sets `ENVIRONMENT=production`, so a deploy without `DASHBOARD_PASSWORD` refuses operator routes.
- Verified live (uvicorn + curl): 401 without / 200 with creds on /api, /dashboard, /demo,
  /openapi.json; /health 200; SSE streams through with creds. Browser login prompt not
  exercised in a real browser yet.
- **Couldn't edit `backend/.env.example`** — it's blocked by permission settings. Add
  `DASHBOARD_USERNAME=operator` / `DASHBOARD_PASSWORD=` there by hand; documented in RUNBOOK §4.
- Single shared credential: fine for a one-operator demo; per-user auth would replace this module.

### 2026-10-06 — Ticket 0002: Twilio webhook signature + Media Streams token
- `/voice/twilio` now verifies `X-Twilio-Signature` (HMAC-SHA1 over the public URL + sorted params)
  when `TWILIO_AUTH_TOKEN` is set; 403 otherwise. **Implemented inline** (`app/voice/twilio_security.py`,
  stdlib hmac) rather than adding the `twilio` SDK for one function. Cross-checked against the
  official `twilio.request_validator.RequestValidator` in a throwaway venv: identical output on
  Twilio's documented example, a unicode/empty-param case, and a GET-with-query case.
- Public URL: `PUBLIC_BASE_URL` if set, else `X-Forwarded-Proto` + Host (Cloud Run terminates TLS,
  so the app itself sees http).
- **WebSocket:** the handshake carries nothing verifiable, so the signed webhook issues a per-call
  token (HMAC-SHA256 over CallSid + caller id) as a TwiML `<Parameter>`; `run_twilio_bot` checks it
  from the `start` frame and closes (1008) **before** `init_db` or any STT/TTS service is built.
  Binding the caller id stops a captured token being replayed with a different `From`.
- **Also fixed (found while in here):** `build_twiml` interpolated the caller-controlled `From` into
  XML unescaped (TwiML injection). Now `quoteattr`-escaped; test parses hostile input as XML.
- Fail-closed rule mirrors 0001: no auth token → open in `development`, 503 elsewhere.
- `test_webhook_returns_twiml_xml` previously read the real `backend/.env` (which has a Twilio
  token); pinned its settings. Not exercised with a real inbound call.

### 2026-10-06 — Ticket 0003: SMS budget + concurrent-session cap
- `app/limits.py`: `SmsBudget` (per call + per destination per rolling hour) checked at the moment
  of sending on **both** paths — engine caller-ID auto-text (over → not texted, link still recorded)
  and dashboard manual send (over → 429, no `payment_sent` event). Refused attempts don't consume
  budget; a send that then fails at Twilio does (conservative).
- `SessionSlots` caps concurrent paid sessions across `/voice/offer`, `/api/sim/start`, and the
  Twilio media socket (closed with 1013 "try again later"). Released on task completion; on
  `/voice/offer` also released if WebRTC setup throws.
- **In-memory, per process** — fine because Cloud Run runs `--max-instances 1` (already required by
  the in-process event bus). Scaling out needs a shared store.
- Defaults (3 per call, 5 per number/hour, 3 sessions) are my picks; all env-configurable.
- Dashboard: "Start simulated call" used to swallow non-2xx responses; it now shows the server's
  detail (e.g. the 429). Voice offer + SMS already surfaced errors. Rebuilt `dist/`.
- Added `tests/conftest.py` (autouse reset of the global limiter state between tests).
