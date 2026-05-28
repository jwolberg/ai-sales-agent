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
- **Current phase:** Phase 4.5 — Conversation Integration & Latency (entering)
- **Current ticket:** P4.5-T1 (next) — turn router
- **Blockers:** None
- **DESIGN:** Phase 4.5 inserted per `docs/AGENT_INTEGRATION.md` — the Phases 2–4 agent layer
  is built but NOT wired into the live pipeline (which still runs raw Claude). This phase makes
  the decider-led runtime real (router → extraction → render → engine → live wiring → latency
  tiers). It precedes Phase 5/6/8 work that depends on the engine.
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
  - Status: Todo
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
  - Status: Todo
- P4.5-T2 — Field & intent extraction
  - Objective: turn the caller's utterance into `collected_fields` updates + signals (answer to
    the pending question, `buying_intent`); confidence + "didn't catch that → clarify" path.
    Rule-based first, then LLM structured extraction. (The missing NLU.)
  - Files likely involved: `backend/app/agent/extraction.py`
  - Depends on: P4.5-T1
  - Acceptance criteria covered: LM-2 (detect missing), DF inputs; enabler for live progress
  - Status: Todo
- P4.5-T3 — Directive + render step
  - Objective: replace the overloaded `NextAction.prompt` with a structured **Directive**
    (intent + content + style) and a single pure `render(directive, state) → utterance`
    (persona-consistent, DF-4). Makes render cacheable for the latency tiers.
  - Files likely involved: `backend/app/agent/render.py`, `backend/app/agent/orchestrator.py`
  - Depends on: P4.5-T1
  - Acceptance criteria covered: VC-4 (consistent persona), DF-4; enabler for latency tiers
  - Status: Todo
- P4.5-T4 — Conversation engine (transport-agnostic)
  - Objective: `run_turn` loop tying router → extraction → capability/decider → render →
    recorder + decision trace; independent of voice. Used by the simulator and live pipeline.
  - Files likely involved: `backend/app/agent/engine.py`
  - Depends on: P4.5-T1, P4.5-T2, P4.5-T3, P2-T4
  - Acceptance criteria covered: §21 (discovery-to-close runs end-to-end); enabler for P5/P6
  - Status: Todo
- P4.5-T5 — Live voice wiring
  - Objective: replace the raw-Claude path in `run_bot` with the engine (STT final →
    `run_turn` → render → TTS); persist turns/decisions; enforce `check_agent_output` (§18) on
    rendered output (and demote/scope the price flag now that approved prices exist).
  - Files likely involved: `backend/app/voice/pipeline.py`, `backend/app/voice/bot.py`
  - Depends on: P4.5-T4, P4-T4
  - Acceptance criteria covered: §18 (output guardrails enforced live); VC-1/VC-4
  - Status: Todo
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
  - Status: Todo

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
  - Status: Todo
- P5-T2 — Version attribution
  - Objective: Tag each call with agent prompt version, playbook version, KB version, model version, variant, and voice config (§10.4).
  - Files likely involved: `backend/app/agent/versioning.py`
  - Depends on: P2-T4
  - Acceptance criteria covered: §10.4; §21 (tagged by version & variant)
  - Status: Todo
- P5-T3 — KPI event capture & metric computation
  - Objective: Emit KPI events and compute the strategy metrics — Close Success, Objection Recovery, Unsupported-Claim, Discovery Completion, Escalation, Latency, Frustration (§16).
  - Files likely involved: `backend/app/kpis/events.py`, `backend/app/kpis/metrics.py`
  - Depends on: P3-T4, P4-T3, P5-T1
  - Acceptance criteria covered: §16; §10.2 (dashboard data)
  - Status: Todo
- P5-T4 — Dashboard (KPIs + transcript/decision review)
  - Objective: Web dashboard showing §10.2 KPIs sliced by version/variant, plus per-call review of transcript, decision trace, and retrieved snippets (§10.3).
  - Files likely involved: `dashboard/app.py` (assumed) , `backend/app/main.py` (API endpoints)
  - Depends on: P5-T1, P5-T2, P5-T3
  - Acceptance criteria covered: §10.2, §10.3; §21 (dashboard displays core KPIs)
  - Status: Todo

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
  - Status: Todo
- P6-T2 — Simulated call runner (LLM self-play)
  - Objective: Run agent vs. synthetic prospect as text-mode self-play, writing the same records as live calls and labeling them synthetic.
  - Files likely involved: `backend/app/simulator/runner.py`
  - Depends on: P6-T1, P5-T3
  - Acceptance criteria covered: §12.1; powers §21 Recursive Improvement (synthetic test)
  - Status: Todo
- P6-T3 — Agent performance scoring
  - Objective: Score each simulated call on KPIs including frustration, unsupported-claim, and objection recovery (LLM-as-judge where qualitative).
  - Files likely involved: `backend/app/simulator/scoring.py`
  - Depends on: P6-T2
  - Acceptance criteria covered: §11.2 Step 1 metrics, §16
  - Status: Todo

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
  - Status: Todo
- P7-T2 — Establish documented baseline
  - Objective: Run the baseline price-objection rebuttal against a fixed synthetic set; record objection recovery, close success, escalation, frustration, unsupported-claim (§11.2 Step 1).
  - Files likely involved: `backend/app/experiments/engine.py`, `docs/recursive-improvement.md`
  - Depends on: P7-T1, P6-T3, P4-T3
  - Acceptance criteria covered: §8 baseline, §11.2 Step 1; §21 (baseline documented)
  - Status: Todo
- P7-T3 — Generate & test variants (≥2)
  - Objective: Generate ≥2 price-rebuttal variants (§8 candidates) each with use/avoid/escalation/compliance specs; run controlled experiment with randomized ordering across personas (§11.2 Steps 2–3).
  - Files likely involved: `backend/app/experiments/variants.py`, `data/playbooks/objections.yaml`
  - Depends on: P7-T2
  - Acceptance criteria covered: §11.2 Steps 2–3; §21 (≥2 variants + synthetic test)
  - Status: Todo
- P7-T4 — Evaluate, promote/retire & before/after report
  - Objective: Compare variants vs. baseline on the primary KPI + guardrail KPIs (§8 promotion rule, §11.2 Steps 4–6); promote or retire one; surface results in the dashboard and write before/after evidence.
  - Files likely involved: `backend/app/experiments/engine.py`, `docs/recursive-improvement.md`, dashboard experiment view
  - Depends on: P7-T3, P5-T4
  - Acceptance criteria covered: §11.2 Steps 4–6; §21 (KPI comparison, promote/retire, before/after)
  - Status: Todo

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
  - Status: Todo
- P8-T3 — Demo scenario rehearsal
  - Objective: Verify the §26 demo flow end-to-end — partial-info lead → context confirm → discovery → price objection → KB answer → fit summary → close → dashboard + before/after view.
  - Files likely involved: `docs/demo-script.md`
  - Depends on: P8-T2
  - Acceptance criteria covered: §26
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
