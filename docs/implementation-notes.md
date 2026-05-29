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
