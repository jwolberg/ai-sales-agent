# Build Plan

## Project
- **Name:** Autonomous AI Sales Agent
- **Summary:** A real-time voice AI sales agent for Nerdy / Varsity Tutors that runs a full discovery-to-close tutoring sales conversation — gathering missing info, using prior call memory, answering from a grounded knowledge base, handling objections, deciding when to close or escalate — while capturing transcripts, decisions, and KPIs, and improving itself through a recursive experiment loop against synthetic prospects.

## Source of Truth
- **Spec:** `/docs/PRD.md` (no `/docs/spec.md` exists; the PRD is the spec-equivalent and is used as the sole source of truth, per invocation argument)
- **UX:** none (`/docs/ux.md` not present)
- Supporting context: `/docs/challenge.md` (challenge brief), `/STRATEGY.md` (strategic anchor)

## Planning Assumptions
- **PRD substitutes for spec.** Planning is scoped to the PRD's **MVP Scope (§7)** and **MVP Acceptance Criteria (§21)**, refining the PRD's own 7-phase recommendation (§22) into execution-ready tickets.
- **Architecture is "suggested," not locked (PRD §14).** Where the PRD leaves stack open, the simplest reasonable path is chosen and labeled as an assumption (see Architecture Notes). These can change without changing scope.
- **Demo channel = web (WebRTC).** PRD allows "phone, WhatsApp, or web for demo purposes"; web is the smallest viable channel. Twilio/WhatsApp are deferred.
- **Recursive-improvement dimension = price-objection rebuttal**, as the PRD pre-selects (§8). The improvement loop runs against synthetic prospects (PRD §11–§12).
- **Synthetic-prospect calls run in text mode** (LLM self-play) producing the same records as live calls, so experiments don't require real-time voice for every run. Live voice is reserved for human trials and the demo.
- **Variant promotion is human-reviewed** for the MVP (PRD allows a choice; human-approved is the smallest safe option). Auto-promotion is deferred.

## Architecture Notes
Assumed stack (simplest reasonable path; not mandated by the PRD):
- **Backend:** Python + FastAPI; `pytest` for tests; SQLAlchemy ORM.
- **Persistence:** SQLite (single-file) for the PRD §15 data model — Lead, Call, Turn, Decision, KPI Event, Experiment, Variant. Postgres is a later swap if needed.
- **Realtime voice:** a voice-pipeline framework (e.g., Pipecat/LiveKit-style) wiring **STT → Claude (reasoning/decisioning) → TTS** with VAD-based turn-taking and barge-in, over **WebRTC** to a browser demo client. STT/TTS vendors are pluggable; the LLM/decisioning layer is **Claude** (latest capable model).
- **Knowledge base:** approved docs embedded into a lightweight vector store (e.g., `sqlite-vec`/Chroma); retriever returns grounded snippets with source IDs.
- **Dashboard:** a thin web app (assumed Streamlit or a small React view) reading the backend API.
- **Synthetic simulator & experiment engine:** Claude-driven persona self-play; experiments apply prompt/playbook *deltas* at runtime keyed by variant.

Important constraints (from PRD):
- **Grounding / no hallucinated facts** (KB-1, KB-4) and **guardrails** (§18) are hard requirements, not polish.
- **Latency targets** (VC-3): first response < 2s; stop-on-barge-in < 1s; KB-grounded answer < 4s.
- **Version attribution** (§10.4): every call traceable to prompt/playbook/KB/model versions + variant.
- **Synthetic vs. real data must be clearly labeled** and PII handled per §13.3.

Explicit non-goals affecting implementation (PRD §4): no replacing all human agents, no unrestricted pricing negotiation / unauthorized discounts, no guaranteed sale, no foundation-model fine-tuning (unless time permits), no full CRM integration, no full outbound dialer, no regulated payment processing.

**Process note (project rules, `.claude/CLAUDE.md`):** commit per ticket (scoped, referencing the ticket ID), run lint/relevant tests before each commit, and append a dated entry to `docs/implementation-notes.md` on any decision/deviation/tradeoff. Do not push without explicit instruction.

## Current Status
- **Overall status:** In Progress
- **Current phase:** Phase 9 complete (demo phone-call intro); Phase 8 still open; live-voice
  hardening underway
- **Current ticket:** Phase 9 done. Live voice now being exercised on real browser/mic calls —
  this surfaced (and fixed) two real bugs (see "Live-voice hardening" note). Remaining: P8-T1
  (live human trials), P8-T2 finalize failure-modes, P8-T3 demo rehearsal — all need a
  browser/mic + funded keys.

### ▶ Live-voice hardening (2026-05-28)
Real demo calls (web/mic) are now being run, surfacing issues the construction tests couldn't:
- **Agent was listening to itself (FIXED, needs live re-test).** From call `58d32393`: the agent's
  own TTS/echo was being transcribed as new user turns, so it fired 3 questions in ~8s and never
  advanced. Fix: a Pipecat `STTMuteFilter(ALWAYS)` before STT mutes the mic while the agent speaks
  (only the user is ever transcribed); `getUserMedia` now also requests echo cancellation/noise
  suppression. Commit `c186ba9`. Trade-off: mid-utterance barge-in is off while the agent talks.
- **Phone-call intro answered too early (FIXED, needs live re-test).** The demo dialing illusion
  cut to the agent on WebRTC connect instead of on actual pickup; now answers on first real agent
  audio (Web Audio onset detection, 30s cap). Commit `1e15286`.
- **Still to confirm live:** that the agent now waits for full user turns and that latency meets
  VC-3. The real `dial.mp3` is in place; `ring.mp3` is still a silent placeholder.

### ▶ RESUME HERE (next session)
Phases 1–7 are complete. The real Phase 7 run was fired on 2026-05-28 (`docs/recursive-improvement.md`
committed): **baseline held — no variant beat it** (all variants 0% objection-recovery; 3 regressed
frustration). The 0% is a *real* result, not a broken metric (verified: KPI events fire, but the
agent rarely reaches a close in self-play and never recovers a price objection within the 12-turn
cap) — a known consequence of PLACEHOLDER rebuttal/KB content + short turn budget. The loop
machinery itself is proven end-to-end. **To lift the numbers later:** supply approved rebuttal/KB
copy (`docs/QandA_opens.md`) and/or raise `--max-turns`, then re-fire.

**Phase 8 in progress.** The credit-free P8-T2 docs are written and committed:
`docs/decision-log.md` (§23), `docs/research-notes.md` (§24), `docs/limitations.md` (§25),
top-level `README.md` (setup/demo), and a **draft** `docs/failure-modes.md` (§19) evidenced from
the synthetic run. Pick up with the parts that need a browser/mic + funded keys: **P8-T1** live
human-trial calls & escalation tuning, then finalize `docs/failure-modes.md` (modes 1/2/10 are
PENDING LIVE) and refresh `docs/limitations.md`, then **P8-T3** demo rehearsal (§26 flow).
Also still open (non-blocking): live latency measurement + deferred Tier-1/Tier-2 latency tiers;
KB content gaps (refund/matching/scheduling/competitive still placeholder — see `docs/QandA_opens.md`);
latency/frustration KPIs not yet captured live; dashboard experiment view (P7-T4 "surface in
dashboard") not built — the report is the before/after evidence.
- **LIVE-VALIDATE (Phase 4.5):** the decider-led voice path (`app/voice/bot.py`) + latency layer
  (fillers, ambient bed) now have had **initial live calls** (2026-05-28), which exposed the
  self-listening + early-answer bugs now fixed (see "Live-voice hardening"). A clean browser/mic/
  keys run (RUNBOOK §11) is still needed to confirm the post-fix conversation and measure latency
  vs VC-3.
- **Deferred latency tiers (documented):** speculative prefetch (Tier-2) and the FAQ answer cache
  (Tier-1) need live measurement to tune; not built yet.
- **Blockers:** None
- **DESIGN:** Phase 4.5 (per `docs/AGENT_INTEGRATION.md`) is complete — the Phases 2–4 agent
  layer is now wired into the live pipeline (decider-led runtime: router → extraction → render →
  engine → live wiring → latency). Phase 5/6/8 build on the engine.
- **ACTION NEEDED (user):** KB docs under `data/kb/` are safe PLACEHOLDERS, not approved
  Nerdy content. See `docs/QandA_opens.md` for the pricing/refund/matching/scheduling copy to
  provide; until then the agent defers those specifics to a human.
- **Note:** P2-T4 transcript/call-record capture complete as a capability (`CallRecorder`
  + optional Orchestrator integration, unit-tested). **Follow-up:** wiring it into the live
  Pipecat frame path (recording real STT/TTS turns during a voice call) is not yet done —
  tracked for when the orchestrator is wired into `run_bot`. P2-T3 orchestrator skeleton +
  persona complete. Live STT→Claude→TTS validated end-to-end (browser+mic) after the
  Deepgram language/sample-rate fixes. P2-T2 (barge-in) still deferred to a live-validation
  pass (`allow_interruptions=True` set).

---

## Phase Breakdown

### Phase 1 — Foundation & Data Layer
**Goal**
- Establish the backend skeleton and the persistence layer every later phase writes to.

**Exit Criteria**
- App boots with a health endpoint; tests + lint run.
- All PRD §15 entities persist and round-trip; sample leads (full/partial/none info) seeded and labeled synthetic vs. real.

**Tickets**
- P1-T1 — Backend scaffold & config
  - Objective: FastAPI app skeleton, settings/env loading, health endpoint, `pytest` harness, lint config, dependency manifest.
  - Files likely involved: `backend/app/main.py`, `backend/app/config.py`, `backend/pyproject.toml` (or `requirements.txt`), `backend/tests/test_health.py`, `.env.example`
  - Depends on: none
  - Acceptance criteria covered: Enabler for all (no direct §21 criterion)
  - Status: Complete
- P1-T2 — Data model & persistence
  - Objective: Implement the §15 schema (Lead, Call, Turn, Decision, KPIEvent, Experiment, Variant) with SQLAlchemy + SQLite; create-all; repository helpers.
  - Files likely involved: `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/tests/test_models.py`
  - Depends on: P1-T1
  - Acceptance criteria covered: Observability data substrate (§10.1); Memory storage (LM-4)
  - Status: Complete
- P1-T3 — Seed data & synthetic/real labeling
  - Objective: Seed sample leads covering Use Cases 1–3 (full/partial/no info); PII-substituted transcript loader stub; synthetic-vs-real label on calls/leads (§13.3).
  - Files likely involved: `backend/app/db/seed.py`, `data/leads/*.json`
  - Depends on: P1-T2
  - Acceptance criteria covered: Use Cases 1–3 data; §13 data requirements
  - Status: Complete

### Phase 2 — Core Voice Agent
**Goal**
- A person can talk to the agent live in the browser, it replies in voice with natural turn-taking and barge-in, in a consistent persona, and the call transcript is captured.

**Exit Criteria**
- Live bidirectional voice in the web demo; user can interrupt; persona is consistent; full transcript + a Call record persisted.

**Tickets**
- P2-T1 — Realtime voice pipeline (STT→LLM→TTS) with VAD
  - Objective: Wire STT + Claude + TTS into a streaming pipeline with VAD turn-taking; WebRTC transport + minimal browser client.
  - Files likely involved: `backend/app/voice/pipeline.py`, `backend/app/voice/server.py`, `frontend/` (demo client)
  - Depends on: P1-T1
  - Acceptance criteria covered: VC-1, VC-3; §21 Voice (live channel, voice response, turn-taking)
  - Status: Complete (wiring + construction validated; live audio pending a browser/mic/keys run)
- P2-T2 — Barge-in / interruption handling
  - Objective: Stop playback on detected user speech (< 1s), flush output, resume from updated context.
  - Files likely involved: `backend/app/voice/pipeline.py`
  - Depends on: P2-T1
  - Acceptance criteria covered: VC-2; §21 Voice (user can interrupt)
  - Status: Todo (revisit). The live-voice fix on 2026-05-28 added `STTMuteFilter(ALWAYS)` so the
    agent stops transcribing its own speech — a deliberate trade-off that disables mid-utterance
    barge-in *while the agent is speaking* (turn-taking resumes the instant it stops). If true
    barge-in is wanted later, replace ALWAYS muting with an echo-robust approach (e.g. only mute
    inbound that matches the agent's output) so the user can still cut in.
- P2-T3 — Orchestrator skeleton + consistent persona
  - Objective: Conversation loop (greeting → listen → respond), persona system prompt, conversation-stage scaffold (§17), and a pluggable `next_action` interface (stubbed).
  - Files likely involved: `backend/app/agent/orchestrator.py`, `backend/app/agent/persona.py`
  - Depends on: P2-T1
  - Acceptance criteria covered: VC-4; enabler for DE-1
  - Status: Complete (added `app/agent/{stages,persona,orchestrator}.py`: 11-stage/10-action/
    6-modifier vocab, pluggable `NextActionDecider` + `StubDecider`, persona built once for
    consistency. Decisioning logic itself is stubbed pending P3-T3.)
- P2-T4 — Transcript & call-record capture
  - Objective: Persist Turns (speaker/text/timestamp) and a Call record per session, including final outcome field and optional recording link.
  - Files likely involved: `backend/app/agent/orchestrator.py`, `backend/tests/test_transcript.py`
  - Depends on: P1-T2, P2-T3
  - Acceptance criteria covered: §10.1; §21 Observability (transcript captured)
  - Status: Complete (added `app/agent/recorder.py` `CallRecorder`: creates a Call row,
    appends Turn rows committed per turn, finalizes with outcome/summary; wired as an
    optional Orchestrator collaborator. Live Pipecat-frame capture is a tracked follow-up.)

### Phase 3 — Lead Memory & Discovery
**Goal**
- The agent uses known lead data and prior-call history, asks for what's missing without re-asking what's known, orders questions dynamically, and can summarize fit and attempt a close.

**Exit Criteria**
- Follow-up calls continue from prior context (no restart); required fields collected when missing, known fields skipped/confirmed; a fit summary + close attempt is produced and logged.

**Tickets**
- P3-T1 — Lead profile loading & cross-call memory
  - Objective: Load lead at call start (full/partial/none); persist call summary, collected fields, objections, buying/disqualification signals, next-step status; carry forward into later calls.
  - Files likely involved: `backend/app/memory/lead_store.py`, `backend/app/agent/orchestrator.py`
  - Depends on: P1-T2, P2-T4
  - Acceptance criteria covered: LM-1, LM-4; §21 Memory; Use Cases 1–3
  - Status: Complete (added `app/memory/lead_store.py`: `LeadStore` load/get_or_create +
    `apply_call_outcome` cross-call write, plus pure `info_level`/`known_fields`/
    `missing_required` helpers. Orchestrator seeded with known lead context. Buying/disqual
    signals folded into status+summary — no schema change; see notes.)
- P3-T2 — Discovery question set (required + leading) & skip-known
  - Objective: Encode required fields (DF-1) and leading questions (DF-2) as a prioritized playbook; detect missing fields; skip or confirm known fields (LM-2, LM-3).
  - Files likely involved: `backend/app/agent/discovery.py`, `data/playbooks/discovery.yaml`
  - Depends on: P3-T1
  - Acceptance criteria covered: DF-1, DF-2, LM-2, LM-3; §21 (gathers required / skips known)
  - Status: Complete (added `data/playbooks/discovery.yaml` — 10 required (DF-1) + 8 leading
    (DF-2) questions with confirm templates — and `app/agent/discovery.py` `DiscoveryPlaybook`
    with skip-known `next_question`/`missing_required`/`known_required`. Added `pyyaml` core
    dep. Dynamic ordering is P3-T3.)
- P3-T3 — Dynamic next-question selection
  - Objective: Decisioning to pick the next-best question from known data, missing fields, stage, and signals, grouped conversationally (DF-3, DF-4); extend orchestrator `next_action`.
  - Files likely involved: `backend/app/agent/decisioning.py`, `backend/app/agent/orchestrator.py`
  - Depends on: P3-T2
  - Acceptance criteria covered: DF-3, DF-4, DE-1 (discovery actions)
  - Status: Complete (added `app/agent/decisioning.py` `DiscoveryDecider`: confirm-known →
    fill required → leading → fit summary; extended `NextAction` with `question_key`/`prompt`
    and `ConversationState.context_confirmed`. DF-3 signal inputs accepted but not yet
    weighted pending P4 detection; opt-in decider — orchestrator default stays `StubDecider`.)
- P3-T4 — Fit summary, close attempt & close logging
  - Objective: Detect close criteria (DE-3), produce a fit summary (CF-1), recommend one next step (CF-2), log every close attempt (CF-3).
  - Files likely involved: `backend/app/agent/closing.py`, `backend/app/agent/decisioning.py`
  - Depends on: P3-T3
  - Acceptance criteria covered: CF-1, CF-2, CF-3, DE-3; §21 (attempts a close; discovery-to-close)
  - Status: Complete (added `app/agent/closing.py`: `assess_close_criteria` (DE-3),
    `build_fit_summary` (CF-1), `choose_close`/`next_step_prompt` (CF-2), `CloseAttempt`.
    DiscoveryDecider now flows discovery → fit summary → attempt close (or develop need /
    pivot when criteria unmet). Close attempts logged as KPIEvents via
    `CallRecorder.record_close_attempt` (CF-3). Buying-intent/objection signals are state
    flags pending Phase 4 detection.)

### Phase 4 — Knowledge Base & Guardrails
**Goal**
- The agent answers policy/competitive/objection questions only from approved content, falls back honestly when it can't, handles common objections, and escalates or refuses per guardrails.

**Exit Criteria**
- Grounded answers with source tracking; honest fallback when KB is insufficient; ≥3 objection types handled (incl. baseline price rebuttal); guardrails + escalation triggers enforced.

**Tickets**
- P4-T1 — KB ingestion & retrieval (RAG)
  - Objective: Index approved KB docs (§9.4 KB-2) into a vector store; retriever returns grounded snippets with source IDs (KB-3).
  - Files likely involved: `backend/app/kb/ingest.py`, `backend/app/kb/retriever.py`, `data/kb/*.md`
  - Depends on: P1-T1
  - Acceptance criteria covered: KB-1, KB-2, KB-3
  - Status: Complete (added `app/kb/ingest.py` markdown chunker w/ source ids and
    `app/kb/retriever.py` dependency-free TF-IDF `KBRetriever` returning scored snippets.
    5 PLACEHOLDER KB docs seeded; real approved content tracked in `docs/QandA_opens.md`.
    Lexical retriever chosen over a vector store — see notes.)
- P4-T2 — Grounded answer action + no-hallucination fallback
  - Objective: Answer only from retrieved content; when insufficient, say so and clarify or escalate (KB-4); wire as an orchestrator action.
  - Files likely involved: `backend/app/agent/orchestrator.py`, `backend/app/agent/decisioning.py`
  - Depends on: P4-T1, P3-T3
  - Acceptance criteria covered: KB-1, KB-4; §21 (answers KB-grounded questions)
  - Status: Complete (added `app/agent/knowledge.py`: `answer_question` grounds in retrieved
    snippets above a tuned min_score or returns an honest fallback (KB-4); `grounding_prompt`
    confines phrasing to retrieved material. Wired `Orchestrator.answer_knowledge` →
    ANSWER_KNOWLEDGE with `kb_sources` (KB-3). Routing heuristic `is_knowledge_question`.)
- P4-T3 — Objection handling (≥3 types) via playbook + KB
  - Objective: Detect objections; respond from approved rebuttals/playbook + KB; cover ≥3 common objections including the **baseline** price rebuttal (sets up Phase 7).
  - Files likely involved: `backend/app/agent/objections.py`, `data/playbooks/objections.yaml`
  - Depends on: P4-T2
  - Acceptance criteria covered: Use Case 4; §21 (≥3 objections); §8 baseline
  - Status: Complete (added `data/playbooks/objections.yaml` — 6 objection types incl. the
    §8 price baseline — and `app/agent/objections.py` cue-based detection + KB-grounded
    rebuttals. `Orchestrator.handle_objection` → HANDLE_OBJECTION; high-risk (discount) sets
    `open_high_risk_objection`, which holds the close gate. Rebuttals are placeholders.)
- P4-T4 — Guardrails & escalation criteria
  - Objective: Enforce §18 guardrails (no invented pricing/guarantees, never claim to be human, always honor human requests, stop after refusal, etc.); implement escalation triggers (DE-4) and escalation records.
  - Files likely involved: `backend/app/agent/guardrails.py`, `backend/app/agent/decisioning.py`
  - Depends on: P4-T2
  - Acceptance criteria covered: DE-4, §18; §21 (can escalate)
  - Status: Complete (added `app/agent/guardrails.py`: `detect_escalation` (DE-4 triggers +
    low-confidence), `should_stop_selling` (stop after refusal), `check_agent_output` (§18 —
    flags claims-human / unapproved price / guarantee). Wired `Orchestrator.check_escalation`
    → ESCALATE with `escalation_risk`; `CallRecorder.record_escalation` logs a KPIEvent.)

### Phase 4.5 — Conversation Integration & Latency (inserted; decider-led runtime)
**Goal**
- Make the structured agent layer (Phases 2–4) actually drive what the agent *says*. Today the
  live pipeline runs raw Claude on the persona prompt and ignores the orchestrator/decider/KB/
  objections/guardrails. This phase builds the decider-led runtime per `docs/AGENT_INTEGRATION.md`:
  a turn router + extraction + a pure render step, tied into a transport-agnostic conversation
  engine, wired into the live voice pipeline, with a layered latency strategy.

**Why inserted here:** the engine is a hard dependency for a meaningful decision trace (Phase 5),
the synthetic simulator (Phase 6 self-play drives the same engine), and a real demo (Phase 8).
Numbered 4.5 to avoid renumbering existing Phases 5–8.

**Exit Criteria**
- A full discovery → KB answer → objection → close → escalation conversation runs end-to-end
  through the engine in text mode, producing turns + decision traces.
- The live voice demo uses the engine (not raw Claude); rendered output passes guardrail checks.
- Latency masking in place (pre-synthesized fillers); measured against VC-3.

**Tickets**
- P4.5-T1 — Turn router
  - Objective: per-turn classify + priority dispatch (escalation DE-4 → refusal/disqualify →
    objection → knowledge question → discovery/close); deterministic, unit-tested.
  - Files likely involved: `backend/app/agent/router.py`
  - Depends on: P3-T3, P4-T2, P4-T3, P4-T4
  - Acceptance criteria covered: DF-3 (routing inputs); enabler for the engine
  - Status: Complete (added `app/agent/router.py` `classify_turn` → `RouteDecision`: strict
    priority escalate > stop-selling > objection > knowledge > progress, reusing the existing
    detectors. Pure/deterministic. Confidence escalation deferred to the engine. The
    discount→escalate vs too-expensive→objection split falls out cleanly.)
- P4.5-T2 — Field & intent extraction
  - Objective: turn the caller's utterance into `collected_fields` updates + signals (answer to
    the pending question, `buying_intent`); confidence + "didn't catch that → clarify" path.
    Rule-based first, then LLM structured extraction. (The missing NLU.)
  - Files likely involved: `backend/app/agent/extraction.py`
  - Depends on: P4.5-T1
  - Acceptance criteria covered: LM-2 (detect missing), DF inputs; enabler for live progress
  - Status: Complete (added `app/agent/extraction.py`: `Extractor` protocol + deterministic
    `RuleBasedExtractor` — slot-fills the pending question, detects buying/disqualification
    signals, flags non-answers for clarify (LM-2). **LLM upgrade also landed**: `LLMExtractor`
    (Claude structured output via `messages.parse`) captures the pending answer *plus any fields
    the caller volunteers in one turn* — no re-asking. Live-smoke-validated. Used by P4.5-T5.)
- P4.5-T3 — Directive + render step
  - Objective: replace the overloaded `NextAction.prompt` with a structured **Directive**
    (intent + content + style) and a single pure `render(directive, state) → utterance`
    (persona-consistent, DF-4). Makes render cacheable for the latency tiers.
  - Files likely involved: `backend/app/agent/render.py`, `backend/app/agent/orchestrator.py`
  - Depends on: P4.5-T1
  - Acceptance criteria covered: VC-4 (consistent persona), DF-4; enabler for latency tiers
  - Status: Complete (added `app/agent/render.py`: `Directive` (SPEAK vs GROUND), `to_directive`
    adapter from NextAction, and pure `render(directive, synthesize=)` — deterministic for SPEAK,
    LLM-synthesize-or-KB-4-fallback for GROUND. Resolves the prompt overload; render is the one
    place words are produced. LLM smoothing of SPEAK is a later enhancement.)
- P4.5-T4 — Conversation engine (transport-agnostic)
  - Objective: `run_turn` loop tying router → extraction → capability/decider → render →
    recorder + decision trace; independent of voice. Used by the simulator and live pipeline.
  - Files likely involved: `backend/app/agent/engine.py`
  - Depends on: P4.5-T1, P4.5-T2, P4.5-T3, P2-T4
  - Acceptance criteria covered: §21 (discovery-to-close runs end-to-end); enabler for P5/P6
  - Status: Complete (added `app/agent/engine.py` `ConversationEngine.run_turn`: extract → route
    → dispatch (escalate/stop/objection/knowledge/clarify/progress) → advance state → render →
    record transcript + decision trace (`recorder.record_decision`). Verified end-to-end
    discovery→close with persisted Turns + Decisions. Transport-agnostic; drives P4.5-T5 & P6.)
- P4.5-T5 — Live voice wiring
  - Objective: replace the raw-Claude path in `run_bot` with the engine (STT final →
    `run_turn` → render → TTS); persist turns/decisions; enforce `check_agent_output` (§18) on
    rendered output (and demote/scope the price flag now that approved prices exist).
  - Files likely involved: `backend/app/voice/pipeline.py`, `backend/app/voice/bot.py`
  - Depends on: P4.5-T4, P4-T4
  - Acceptance criteria covered: §18 (output guardrails enforced live); VC-1/VC-4
  - Status: Complete (construction-validated; needs live run). Added `app/voice/bot.py`:
    `EngineProcessor` drives the engine on each STT-final transcript and speaks the rendered line
    via `TTSSpeakFrame`; Hybrid rendering (verbatim fixed lines / LLM-smoothed questions /
    GROUND-synthesized KB) via `make_synthesizer`; `guard_output` enforces §18 (blocks
    claims-human/guarantee → handoff; price advisory). `run_bot` moved here, wires LLMExtractor +
    DiscoveryDecider + CallRecorder; greets first; persists turns/decisions. `run_bot` removed
    from `pipeline.py` (legacy `build_pipeline_task` kept for the construction test).
- P4.5-T6 — Latency tiers + audio realism (fillers, caching, speculation, ambient bed)
  - Objective: Tier-0 pre-synthesized static + filler audio; cached FAQ answers; filler-masking
    on slow/cache-miss paths; speculative prefetch of the predicted next directive (verify
    action-signature before speaking). **Looping ambient "comfort noise"** mixed under the agent's
    voice via Pipecat `SoundfileMixer` on the transport output (output-only → no STT/VAD impact),
    gated by an `ambient_noise` config flag (off by default), low volume, WAV asset. Measure vs VC-3.
    NOTE: `SoundfileMixer` doesn't resample/downmix — pin `audio_out_sample_rate=24000` to match the
    asset (`data/audio/ambient.wav`, mono 24 kHz, ready) and add the `soundfile` dep to the voice extra.
  - Files likely involved: `backend/app/voice/latency.py`, `backend/app/voice/pipeline.py`,
    `backend/app/config.py`, `backend/config.toml`, `data/audio/ambient.wav`
  - Depends on: P4.5-T5
  - Acceptance criteria covered: VC-3 (latency targets); call-realism polish
  - Status: Complete (shippable parts; needs live latency measurement). Added filler-masking
    (`app/voice/fillers.py` `FillerBank` + EngineProcessor speaks a filler while computing,
    gated by `fillers`), ambient comfort-noise bed (`SoundfileMixer` on transport output, gated
    by `ambient_noise`, output rate pinned to 24 kHz to match `data/audio/ambient.wav`), and the
    `soundfile` dep. **Deferred** (need live tuning): Tier-1 FAQ answer cache, Tier-2 speculative
    prefetch, and true Tier-0 pre-synthesized filler *audio* (current fillers go through TTS).

### Phase 5 — Decisioning Trace & Observability Dashboard
**Goal**
- Every decision is logged with rationale, every call is version/variant-tagged, KPIs are computed, and an operator can review it all in a dashboard.

**Exit Criteria**
- Per-turn decision trace persisted; calls carry full version attribution; KPI events emitted and metrics computed; dashboard shows core KPIs and per-call transcript/decision review.

**Tickets**
- P5-T1 — Decision-trace logging
  - Objective: Log each turn's decision — stage, selected action, reason, confidence, missing fields, detected intent, detected objection, escalation risk (DE-2).
  - Files likely involved: `backend/app/agent/decisioning.py`
  - Depends on: P3-T3, P4-T2
  - Acceptance criteria covered: DE-2, §10.1; §21 Observability (decision trace)
  - Status: Complete (the engine logs a Decision per turn via `recorder.record_decision`;
    enriched in `engine.run_turn` to tag the prospect `Turn` with `detected_intent` (route) +
    `detected_objection` and link `Decision.turn_id` to it. Stage/action/reason/confidence/
    missing_fields/escalation_risk/kb_sources already captured.)
- P5-T2 — Version attribution
  - Objective: Tag each call with agent prompt version, playbook version, KB version, model version, variant, and voice config (§10.4).
  - Files likely involved: `backend/app/agent/versioning.py`
  - Depends on: P2-T4
  - Acceptance criteria covered: §10.4; §21 (tagged by version & variant)
  - Status: Complete (added `app/agent/versioning.py` `compute_versions` → content-hash versions
    for persona/playbooks/KB + configured model; `CallRecorder` stamps them on the Call; `run_bot`
    applies them. Variant/experiment id are Phase 7; voice config has no Call column (noted).)
- P5-T3 — KPI event capture & metric computation
  - Objective: Emit KPI events and compute the strategy metrics — Close Success, Objection Recovery, Unsupported-Claim, Discovery Completion, Escalation, Latency, Frustration (§16).
  - Files likely involved: `backend/app/kpis/events.py`, `backend/app/kpis/metrics.py`
  - Depends on: P3-T4, P4-T3, P5-T1
  - Acceptance criteria covered: §16; §10.2 (dashboard data)
  - Status: Complete (added `app/kpis/events.py` (event vocab) + `recorder.record_event`; the
    engine emits objection_raised / escalation / close_attempt / discovery_complete / call_completed.
    `app/kpis/metrics.py` `compute_metrics` rolls up the §16 KPIs (close success/attempt, objection
    recovery, escalation, discovery completion, unsupported-claim), sliceable by version/variant.
    Latency + frustration return None — not captured yet (per-turn timing / sentiment), documented.)
- P5-T4 — Dashboard (KPIs + transcript/decision review)
  - Objective: Web dashboard showing §10.2 KPIs sliced by version/variant, plus per-call review of transcript, decision trace, and retrieved snippets (§10.3).
  - Files likely involved: `dashboard/app.py` (assumed) , `backend/app/main.py` (API endpoints)
  - Depends on: P5-T1, P5-T2, P5-T3
  - Acceptance criteria covered: §10.2, §10.3; §21 (dashboard displays core KPIs)
  - Status: Complete (added `app/dashboard/router.py` — `/api/metrics` (sliceable by version/
    variant), `/api/calls`, `/api/calls/{id}` (transcript + decision trace + KPI events) — and a
    static dashboard UI at `/dashboard` (`frontend/dashboard/index.html`, vanilla JS, no new dep).
    Phase 5 exit criteria met.)

### Phase 6 — Synthetic Prospect Simulator
**Goal**
- Honest synthetic prospects that hesitate, push back, and disqualify themselves can run simulated calls against the agent and be scored on the same KPIs.

**Exit Criteria**
- ≥6 personas defined with realistic behaviors; simulated calls produce the same Call/Turn/Decision/KPI records (labeled synthetic) as live calls; each call is scored.

**Tickets**
- P6-T1 — Synthetic persona definitions (≥6)
  - Objective: Define the 6 personas (§12.2) with behaviors per §12.3 (hesitate, interrupt, partial answers, disqualify, resist pushiness, reward consultative selling).
  - Files likely involved: `backend/app/simulator/personas.py`, `data/personas/*.yaml`
  - Depends on: P1-T1
  - Acceptance criteria covered: §12.2, §12.3
  - Status: Complete (added `data/personas/personas.yaml` — the 6 §12.2 personas with ground-truth
    `facts`, traits, objections, and converts/disqualifies flags — and `app/simulator/personas.py`
    `PersonaLibrary` + `persona_system_prompt` (composes §12.3 behavior rules + persona for the
    self-play prospect). Facts use the discovery field keys so P6-T3 can score extraction.)
- P6-T2 — Simulated call runner (LLM self-play)
  - Objective: Run agent vs. synthetic prospect as text-mode self-play, writing the same records as live calls and labeling them synthetic.
  - Files likely involved: `backend/app/simulator/runner.py`
  - Depends on: P6-T1, P5-T3
  - Acceptance criteria covered: §12.1; powers §21 Recursive Improvement (synthetic test)
  - Status: Complete (added `app/simulator/runner.py`: `run_call` (LLM-agnostic self-play loop:
    greet → prospect↔agent until terminal stage/goodbye/cap), `make_prospect` (Claude self-play
    prospect from the persona prompt), `simulate` (wires the real engine + prospect). Writes the
    same Call/Turn/Decision/KPIEvent records, `is_synthetic=True`, channel `sim:<persona>`. Moved
    `make_synthesizer` to pipecat-free `app/agent/synthesis.py`. Live-validated end-to-end.)
- P6-T3 — Agent performance scoring
  - Objective: Score each simulated call on KPIs including frustration, unsupported-claim, and objection recovery (LLM-as-judge where qualitative).
  - Files likely involved: `backend/app/simulator/scoring.py`
  - Depends on: P6-T2
  - Acceptance criteria covered: §11.2 Step 1 metrics, §16
  - Status: Complete (added `app/simulator/scoring.py` `score_call`: deterministic flags from the
    recorded call (escalated / close-attempted / discovery-completed / objection raised+recovered /
    `appropriate_for_persona` — converts→progressed, poor-fit→not force-closed) + an LLM-as-judge
    (`judge_transcript`, structured output) for frustration / unsupported-claim / consultative 1–5.
    Judge client injected for tests.)

### Phase 7 — Recursive Improvement Loop (Price Objection)
**Goal**
- Demonstrate one meaningful improvement loop: document a baseline, generate and test ≥2 price-rebuttal variants against synthetic prospects, and promote or retire one on evidence.

**Exit Criteria**
- Baseline documented; ≥2 variants tested under controlled conditions; KPI comparison shown in the dashboard; one variant promoted or retired per the promotion rule; before/after evidence written.

**Tickets**
- P7-T1 — Experiment & variant infrastructure
  - Objective: Experiment/Variant records, variant assignment, and runtime application of prompt/playbook deltas keyed by variant (§14 Experiment Engine, §15).
  - Files likely involved: `backend/app/experiments/engine.py`, `backend/app/experiments/variants.py`
  - Depends on: P5-T2, P6-T2
  - Acceptance criteria covered: §11; §10.4 (variant attribution)
  - Status: Complete (added `app/experiments/variants.py` — the §8 baseline + 5 candidate price
    rebuttals (PriceVariant: rebuttal/when/escalation/compliance, all guardrail-safe) — and
    `app/experiments/engine.py` `create_experiment` (Experiment + Variant records, rebuttal in
    playbook_delta) + `run_variant` (tagged self-play applying the variant's rebuttal). Variant
    application seam: `Orchestrator.objection_overrides`. Offline mode for tests.)
- P7-T2 — Establish documented baseline
  - Objective: Run the baseline price-objection rebuttal against a fixed synthetic set; record objection recovery, close success, escalation, frustration, unsupported-claim (§11.2 Step 1).
  - Files likely involved: `backend/app/experiments/engine.py`, `docs/recursive-improvement.md`
  - Depends on: P7-T1, P6-T3, P4-T3
  - Acceptance criteria covered: §8 baseline, §11.2 Step 1; §21 (baseline documented)
  - Status: Complete (real run fired 2026-05-28; `docs/recursive-improvement.md` committed). The
    baseline ran against the fixed 5-persona set; measured baseline KPIs recorded (objection-recovery
    0%, frustration 80%, unsupported-claim 0%). `run_experiment` + `experiment_personas` +
    `evaluation.score_variant_calls`/`aggregate` produced the numbers.
- P7-T3 — Generate & test variants (≥2)
  - Objective: Generate ≥2 price-rebuttal variants (§8 candidates) each with use/avoid/escalation/compliance specs; run controlled experiment with randomized ordering across personas (§11.2 Steps 2–3).
  - Files likely involved: `backend/app/experiments/variants.py`, `data/playbooks/objections.yaml`
  - Depends on: P7-T2
  - Acceptance criteria covered: §11.2 Steps 2–3; §21 (≥2 variants + synthetic test)
  - Status: Complete (5 candidate rebuttals in `variants.py` — empathy-first, outcome-cost,
    risk-reversal, comparison, diagnostic — each with when-to-use/avoid + escalation trigger +
    compliance note; `run_experiment` runs every variant across the persona set and tags calls.)
- P7-T4 — Evaluate, promote/retire & before/after report
  - Objective: Compare variants vs. baseline on the primary KPI + guardrail KPIs (§8 promotion rule, §11.2 Steps 4–6); promote or retire one; surface results in the dashboard and write before/after evidence.
  - Files likely involved: `backend/app/experiments/engine.py`, `docs/recursive-improvement.md`, dashboard experiment view
  - Depends on: P7-T3, P5-T4
  - Acceptance criteria covered: §11.2 Steps 4–6; §21 (KPI comparison, promote/retire, before/after)
  - Status: Complete (real run fired 2026-05-28; `docs/recursive-improvement.md` committed).
    `evaluation.py`: `aggregate` → KPI rates, `decide_promotion` → §8 rule, `evaluate_experiment`
    promotes/retires + marks the Experiment, `render_report` writes the before/after Markdown.
    **Result: baseline held — no variant promoted** (all 0% objection-recovery; 3 regressed
    frustration). Verified the 0% is real signal, not a dead metric (KPI events fire; agent rarely
    reaches a close in self-play within the 12-turn cap — placeholder rebuttal/KB content). Loop
    proven end-to-end. Dashboard experiment view still TODO — the report is the before/after evidence.

### Phase 8 — Hardening & Documentation
**Goal**
- Survive contact with a real human, then deliver the required documentation set and a rehearsed demo.

**Exit Criteria**
- Human trial calls run and escalation tuned; all required docs written; the §26 demo flow runs end-to-end.

**Tickets**
- P8-T1 — Human trial calls & escalation tuning
  - Objective: Run live human trial calls via the web demo; tune escalation thresholds; capture failures for the report.
  - Files likely involved: `docs/failure-modes.md`, `backend/app/agent/guardrails.py`
  - Depends on: P5-T4, P7-T4
  - Acceptance criteria covered: §19; "What We Are Evaluating" (real human trial)
  - Status: Todo
- P8-T2 — Required documentation set
  - Objective: Write failure-mode report (§19), recursive-improvement description (§11), decision log (§23), research notes (§24), limitations memo (§25), and setup/demo instructions.
  - Files likely involved: `docs/failure-modes.md`, `docs/recursive-improvement.md`, `docs/decision-log.md`, `docs/research-notes.md`, `docs/limitations.md`, `README.md`
  - Depends on: P8-T1
  - Acceptance criteria covered: §21 Documentation
  - Status: In Progress (credit-free docs done 2026-05-28: `docs/decision-log.md` (§23),
    `docs/research-notes.md` (§24), `docs/limitations.md` (§25), top-level `README.md`
    (setup/demo), and a **draft** `docs/failure-modes.md` (§19) evidenced from the synthetic
    run with live-trial-dependent modes marked PENDING. `docs/recursive-improvement.md` (§11)
    already committed. **Remaining:** finalize failure-modes (modes 1/2/10 need P8-T1 live
    trials) and refresh limitations once humans test.)
- P8-T3 — Demo scenario rehearsal
  - Objective: Verify the §26 demo flow end-to-end — partial-info lead → context confirm → discovery → price objection → KB answer → fit summary → close → dashboard + before/after view.
  - Files likely involved: `docs/demo-script.md`
  - Depends on: P8-T2
  - Acceptance criteria covered: §26
  - Status: Todo

### Phase 9 — "Phone Call" Demo Intro
**Goal**
- Make the `/demo` CTA feel like placing a real phone call — relabel it "Call 1-800-Nerdy-4-u"
  and play dial tone → digits → ringing that loops until the agent answers — as demo polish for
  the §26 walkthrough. Frontend-only; no backend change. The phone number is cosmetic (no real
  telephony).

**Exit Criteria**
- Button reads "Call 1-800-Nerdy-4-u"; clicking plays dial+digits then a looping ring; the ring
  stops and the agent greets the moment the WebRTC call connects; hang up / errors / denied mic
  stop all audio. Works with placeholder stubs and with user-supplied audio, no code change.

**Tickets**
- P9-T1 — Relabel CTA + audio-asset scaffolding
  - Objective: Change the demo button text to "Call 1-800-Nerdy-4-u"; add the browser-served
    audio assets (one-shot `dial.mp3` + loop-safe `ring.mp3`) as silent placeholder stubs the
    user replaces; document the asset contract.
  - Files likely involved: `frontend/index.html`, `frontend/audio/dial.mp3`,
    `frontend/audio/ring.mp3`, `frontend/audio/README.md`
  - Depends on: P2-T1 (demo client)
  - Acceptance criteria covered: §26 (demo polish)
  - Status: Complete (button relabeled + copy updated; `frontend/audio/` added with silent
    placeholder `dial.mp3`/`ring.mp3` (ffmpeg `anullsrc`) and a README documenting the
    user-provided asset contract. Assets served via the existing `/demo` static mount.)
- P9-T2 — Phone-call intro playback + connect-on-answer wiring
  - Objective: In `client.js`, after the `/voice/status` ready-check, play `dial.mp3` once then
    loop `ring.mp3` while connecting in parallel; stop the ring and let the agent greet the
    moment the connection reaches `connected`; stop all audio on hang up / failure / mic denial;
    add "Dialing…/Ringing…" status; guard the answer-during-intro race.
  - Files likely involved: `frontend/client.js`
  - Depends on: P9-T1
  - Acceptance criteria covered: §26 (demo polish)
  - Status: Complete (`client.js`: `startDialingSound` plays `dial.mp3` once then loops
    `ring.mp3` on its `ended` event; connect runs in parallel; `onAnswered` (connectionState
    `connected`, `ontrack` fallback) stops the ring and greets; `stopDialingSound` runs on
    hang up / failure / mic denial; `answered` flag guards the answer-during-intro race.
    Intro copy updated to "Click below to call 1-800-Nerdy-4-u (1-800-637-3948)". Browser-
    verified: Dialing… → Ringing… loop, and graceful teardown on mic-deny — no console errors.)

### Phase 10 — Conversation Memory & Context Continuity
**Goal**
- Close the three seams surfaced by a Retell.ai architecture review: the live agent re-asks
  questions it should already know the answers to. The structured layer exists (slot-filling,
  `LeadStore`, transcript capture) but three connections are missing — cross-call memory isn't
  injected into the live voice path, the LLM phrasing layer never sees the running transcript, and
  most discovery slots are dropped at call end. This phase wires those seams so the agent stops
  re-asking, both within a call and across calls.

**Why inserted here:** these are integration fixes against existing acceptance criteria (LM-1,
LM-4, LM-2/3, DF-4), not new scope — the capabilities were built in Phases 3 and 4.5 but are not
connected in the live path (`app/voice/bot.py`). Numbered 10 to follow Phase 9 without renumbering.

**Exit Criteria**
- A live follow-up call starts from prior-call context (known fields seeded, not re-asked).
- The LLM phrasing layer receives the running transcript, so it can avoid repetition and smooth
  over corrections within a call.
- All discovery slots collected in a call (not just the 9 `PROFILE_FIELDS`) survive to the next
  call, and the lead profile is updated automatically when the call ends.

**Tickets**
- P10-T1 — Wire cross-call memory into the live voice path
  - Objective: In `run_bot`/`build_engine`, load the `Lead` at call start and pass its known
    profile as `known_fields` to the `Orchestrator` (the seam already exists — `orchestrator.py`
    accepts `known_fields` and seeds `state.collected_fields`; `bot.py` currently constructs the
    orchestrator without it). Result: a returning caller's known fields are skipped/confirmed, not
    re-asked. Resolve which lead to load for a web demo call (config/query param) and document it.
  - Files likely involved: `backend/app/voice/bot.py`, `backend/app/memory/lead_store.py`,
    `backend/app/agent/orchestrator.py`, `backend/tests/test_bot.py`, `backend/tests/test_lead_store.py`
  - Depends on: P3-T1, P4.5-T5
  - Acceptance criteria covered: LM-1, LM-3 (skip/confirm known); §21 Memory (follow-up continues from context)
  - Status: Todo
- P10-T2 — Feed running transcript into the synthesizer
  - Objective: Pass `state.history` (prior turns) as prior `messages` into the Claude phrasing call
    so the LLM phrases with conversational context instead of a single isolated instruction.
    Currently `make_synthesizer` sends only `messages=[{"role":"user","content": instruction}]` plus
    the cached persona system prompt, so the model has zero in-call memory and cannot avoid repeats
    or smooth over a caller's correction. Thread history through `render()` → `synthesize`; keep the
    persona system prompt cached; bound history length for latency.
  - Files likely involved: `backend/app/agent/synthesis.py`, `backend/app/agent/render.py`,
    `backend/app/agent/engine.py`, `backend/tests/test_render.py`
  - Depends on: P4.5-T3, P4.5-T4
  - Acceptance criteria covered: DF-4 (conversational, persona-consistent phrasing); VC-4
  - Status: Todo
- P10-T3 — Persist all discovery slots & auto-write on call end
  - Objective: Stop dropping slots at call end. `apply_call_outcome` only persists the 9
    `PROFILE_FIELDS`, but `discovery.yaml` defines 15 required slots (`challenge`, `goal`,
    `prior_tutoring`, `readiness`, …) — the rest are lost, so the next call re-asks them. Add a JSON
    column on `Lead` (or a key/value side table) to store the full `collected_fields`, and call
    `apply_call_outcome` automatically from `engine.end()` (currently it must be invoked manually
    and isn't in the live path). Re-seed the full object on the next call (pairs with P10-T1).
  - Files likely involved: `backend/app/db/models.py`, `backend/app/memory/lead_store.py`,
    `backend/app/agent/engine.py`, `backend/tests/test_lead_store.py`, `backend/tests/test_models.py`
  - Depends on: P3-T1, P10-T1
  - Acceptance criteria covered: LM-1, LM-4 (memory storage across calls); §21 Memory
  - Status: Todo

---

## Dependency Order
1. P1-T1 — Backend scaffold & config
2. P1-T2 — Data model & persistence
3. P1-T3 — Seed data & synthetic/real labeling
4. P2-T1 — Realtime voice pipeline
5. P2-T2 — Barge-in handling
6. P2-T3 — Orchestrator skeleton + persona
7. P2-T4 — Transcript & call-record capture
8. P3-T1 — Lead profile loading & cross-call memory
9. P3-T2 — Discovery question set & skip-known
10. P3-T3 — Dynamic next-question selection
11. P4-T1 — KB ingestion & retrieval *(parallelizable with Phase 3; only needs P1-T1)*
12. P3-T4 — Fit summary, close attempt & logging
13. P4-T2 — Grounded answer action + fallback
14. P4-T3 — Objection handling (≥3 types)
15. P4-T4 — Guardrails & escalation criteria
16. P4.5-T1 — Turn router
17. P4.5-T2 — Field & intent extraction
18. P4.5-T3 — Directive + render step
19. P4.5-T4 — Conversation engine (transport-agnostic)
20. P4.5-T5 — Live voice wiring
21. P4.5-T6 — Latency tiers (fillers + caching + speculation)
22. P5-T1 — Decision-trace logging *(now logged from the engine's per-turn decisions)*
23. P5-T2 — Version attribution
24. P5-T3 — KPI event capture & metrics
25. P5-T4 — Dashboard
26. P6-T1 — Synthetic persona definitions
27. P6-T2 — Simulated call runner *(drives the Phase 4.5 engine in text mode)*
28. P6-T3 — Agent performance scoring
29. P7-T1 — Experiment & variant infrastructure
30. P7-T2 — Establish documented baseline
31. P7-T3 — Generate & test variants
32. P7-T4 — Evaluate, promote/retire & report
33. P8-T1 — Human trial calls & escalation tuning
34. P8-T2 — Required documentation set
35. P8-T3 — Demo scenario rehearsal
36. P10-T1 — Wire cross-call memory into the live voice path
37. P10-T2 — Feed running transcript into the synthesizer
38. P10-T3 — Persist all discovery slots & auto-write on call end *(pairs with P10-T1)*

## Recommended Next Step
- **Start with:** P4.5-T1 — Turn router (Phases 1–4 complete; the agent layer is built but not
  wired into the live pipeline).
- **Why this is next:** the structured agent layer currently has zero influence on what the live
  agent says — it runs raw Claude on the persona prompt. The turn router is the first piece of the
  decider-led runtime (`docs/AGENT_INTEGRATION.md`): it classifies each turn and dispatches to the
  right capability, and is the foundation the extraction, render, and engine tickets build on.
  Getting the engine real also unblocks a meaningful decision trace (Phase 5) and the synthetic
  simulator (Phase 6), which both drive it.

## Deferred / Out of Scope
From PRD §4 non-goals:
- Replacing all human agents across every lead type.
- Unrestricted pricing negotiation / unauthorized discounts.
- Guaranteeing sale completion.
- Fine-tuning a foundation model (only "if time permits" — not in MVP path).
- Full production CRM integration.
- Full outbound dialer system beyond demo/testing needs.
- Regulated payment processing (only a safe demo path if any).

Nice-to-haves not needed for MVP:
- Phone (Twilio) and WhatsApp voice channels — web/WebRTC demo suffices.
- Persisted audio recordings — transcript + optional link only.
- Auto-promotion of variants — human-reviewed promotion for MVP.
- Multi-flow support beyond the single parent/student tutoring flow (PRD §7).

## Update Rules
After each implementation pass:
- Update ticket **Status** only as Todo / In Progress / Complete / Blocked.
- Update **Current Status** (phase, ticket, blockers).
- Record blockers briefly.
- Set the next recommended ticket.
- Do **NOT** add new scope unless the spec (`/docs/PRD.md`) changes.
- Per project rules: commit per ticket (reference the ticket ID), run lint + relevant tests before committing, and append a dated entry to `docs/implementation-notes.md` for any decision, deviation, or tradeoff.
