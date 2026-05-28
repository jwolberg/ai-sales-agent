# Build Plan — Voice Intent-Router Agent

## Project
- **Name:** Voice Intent-Router Agent (narrowed direction)
- **Summary:** Re-purpose the existing voice sales-agent stack into a **two-option intent router**:
  converse to determine **test prep vs. tutoring**, drill to the specific test/subject leaf, **quote
  that leaf's price** from a deterministic table, and answer informational questions from a
  `sqlite-vec` KB — while keeping per-turn decision traces, KPIs, and a synthetic self-play
  benchmark that grades **classification accuracy**.
- **Source of truth:** `docs/brainstorms/intent-router-agent-requirements.md` (R1–R13).
- **Supersedes:** the discovery-to-close scope in `docs/BUILD_PLAN.md` (kept as history).

## Strategy: modify, not rebuild
Keep the boring infrastructure; replace the broken brain. The change is concentrated in the
conversation core + a small price table + a vector retriever.

### Reused as-is (or with tiny edits)
- `agent/recorder.py`, `db/models.py` (+ small additive columns), `agent/versioning.py`
- `memory/lead_store.py`, `kpis/events.py` (+ new event types)
- `voice/pipeline.py` (STT/TTS/transport), `dashboard/router.py` (point at new metrics)
- `kb/ingest.py` (markdown chunker — reused to feed the embedder)
- `simulator/runner.py` harness shape, `experiments/*` scaffold (Experiment/Variant records)

### Deleted / replaced (the discovery-to-close brain)
| File | Fate |
|---|---|
| `agent/decisioning.py` (`DiscoveryDecider`) | **delete** — replaced by `agent/brain.py` |
| `agent/discovery.py` + `data/playbooks/discovery.yaml` | **delete** — no checklist; slots are the taxonomy |
| `agent/closing.py` | **delete** — no close/fit-summary endpoint |
| `agent/objections.py` + `data/playbooks/objections.yaml` | **delete** — no objection handling |
| `experiments/variants.py` (price-rebuttal variants) | **replace** — variants become brain-prompt deltas |
| `agent/router.py` (`classify_turn` as controller) | **demote/delete** — brain routes; detectors advisory only (R2) |
| `agent/render.py` "rephrase only, add no info" path | **delete** — brain composes the reply (R3) |
| `agent/extraction.py` (`RuleBasedExtractor`/`LLMExtractor`) | **delete** — brain slot-fills via tools (R5) |
| `kb/retriever.py` (TF-IDF) | **keep as offline fallback**, default to vector retriever (R7) |

> **Sequencing rule:** build the new path first (Phases IR-1..IR-4), switch live + simulator onto
> it (IR-5), then delete the dead machinery and its tests last (IR-6) so the suite stays green
> step-to-step. Per `.claude/CLAUDE.md`: one commit per ticket, lint + relevant tests before each,
> dated `docs/implementation-notes.md` entry on any decision/deviation.

---

## Phase IR-0 — Reconcile & scaffold
- **IR0-T1 — Reconcile direction docs.** Update `STRATEGY.md` to the router scope; banner the old
  `BUILD_PLAN.md`/`PRD.md` as superseded-scope; add a `docs/decision-log.md` entry for the pivot +
  stack choices (OpenAI brain + embeddings, `sqlite-vec`). *(R13)*
- **IR0-T2 — OpenAI config + dependency.** Add `openai_api_key`, `openai_chat_model`,
  `openai_embedding_model` (default `text-embedding-3-small`) to `config.py`; add `openai` to
  deps; extend `missing_keys()`. App still boots without keys (offline path falls back). *(R13)*
- **IR0-T3 — Taxonomy module.** New `agent/taxonomy.py`: the 8-leaf tree as data + a typed slot
  schema (`category ∈ {test_prep, tutoring}`, `test`, `subject_area`, `subject`), `resolve_leaf(slots)
  → Leaf | None`, `next_unfilled(slots)`, and a `Leaf` id format (`test_prep/SAT`,
  `tutoring/science/chemistry`). Pure, fully unit-tested. *(R5)*

## Phase IR-1 — Price table (the endpoint, correctness-critical)
- **IR1-T1 — Price data + loader.** `data/pricing/pricing.yaml` keyed by leaf (placeholder,
  clearly labeled un-approved); `agent/pricing.py` with `quote_price(leaf) → PriceRecord | None`
  (exact lookup only — never fuzzy). No leaf → returns None (caller asks one more question); leaf
  with no record → honest fallback. Unit-tested for every leaf. *(R6, R6b)*
- **IR1-T2 — Mis-quote guardrail.** Extend `agent/guardrails.py` so a stated price is allowed
  **only** when it matches a `quote_price` record passed for that turn; any off-table number is a
  hard violation → safe handoff substitution before TTS. Emits a `MIS_QUOTE_BLOCKED` KPI. *(R4b, R6)*

## Phase IR-2 — Classifier brain (LLM-driven core + tool contract)
- **IR2-T1 — Tool contract + decision schema.** Define the brain's tools — `slot_fill(field, value)`,
  `kb_lookup(query)`, `quote_price(leaf)`, `escalate(reason)` — and a structured per-turn decision
  (`action`, `reason`, `confidence`, `slots`, `leaf?`, `utterance`) so the `Decision` trace stays as
  rich as today's (R9). Document the contract in the requirements doc's deferred-questions section.
  *(R1, R9)*
- **IR2-T2 — `agent/brain.py`.** OpenAI tool-calling brain: input = running transcript + known lead
  fields + current slot state; output = the decision + composed reply + any `slot_fill`/`quote_price`
  calls. System prompt: persona + taxonomy + rules ("ask the single most disambiguating question;
  only `quote_price` once the leaf is confident; ground prices via the tool; never invent;
  clarify ambiguous answers"). *(R1, R2, R3, R5, R5b, R8)*
- **IR2-T3 — New engine turn loop.** Refactor `ConversationEngine.run_turn` to drive the brain:
  brain decides → execute tool calls (slot_fill→state, kb_lookup→retriever, quote_price→table,
  escalate) → guardrail composed text → record decision + slots + KPI events → return `TurnResult`.
  Keep transport-agnostic (same loop for live + self-play). Delete the keyword-router dispatch and
  the `_clarify`/`_bridge_back` discovery scaffolding. *(R1, R2, R3, R10)*

## Phase IR-3 — sqlite-vec KB swap
- **IR3-T1 — Embedding + vector store setup.** `kb/embeddings.py` (OpenAI `text-embedding-3-small`)
  and `sqlite-vec` wiring: load the extension against the project DB, create the vector table.
  Verify the extension loads in the runtime **early** (assumption flagged in requirements). *(R7, R13)*
- **IR3-T2 — Vector ingest + retriever.** Reuse `kb/ingest.py` chunker; embed chunks and store
  vectors + source IDs (`kb/index.py` build script). New `kb/vector_retriever.py` (knn/cosine via
  `sqlite-vec`) returning scored chunks with source IDs; wire `knowledge.answer_question` to it,
  preserving the honest fallback. Keep TF-IDF as the no-key/offline fallback so tests run without
  OpenAI. *(R7, R4)*
- **IR3-T3 — Explainer KB content.** Author `data/kb/*.md` explainers (SAT vs ACT vs PSAT, what a
  tutoring session involves, per-subject blurbs) as clearly-labeled placeholder content. **Prices
  do not live here** (R6). *(R7)*

## Phase IR-4 — Voice + simulator on the new brain
- **IR4-T1 — Voice bot on the brain.** Point `voice/bot.py` `EngineProcessor` at the new engine;
  keep `guard_output` (now mis-quote-aware). Fix `STTMuteFilter` so genuine barge-in isn't dropped
  while preserving echo suppression (R12) — validate on real audio. *(R11, R12)*
- **IR4-T2 — Simulator on the brain.** Point `simulator/runner.py` at the new engine/brain; drop
  the price-objection override path. Same brain drives live + text-mode self-play. *(R10)*

## Phase IR-5 — Synthetic-accuracy benchmark + new KPIs
- **IR5-T1 — Ground-truth personas.** Extend `simulator/personas.py` `Persona` with `target_leaf`;
  author a persona set covering all 8 leaves plus ambiguous openers ("struggling in school") whose
  ground truth is a specific leaf. `data/personas/personas.yaml` updated. *(R10)*
- **IR5-T2 — New KPIs + scoring.** Add event types to `kpis/events.py`
  (`LEAF_REACHED`, `MIS_QUOTE_BLOCKED`, `CLARIFY_ASKED`); rewrite `simulator/scoring.py` +
  `kpis/metrics.py` for **Classification Accuracy, Turns-to-Classification, Over-Ask Rate,
  Mis-Quote Rate, Escalation Rate, Unsupported-Claim Rate**. Benchmark runner reports accuracy vs.
  `target_leaf`. *(R9, R10)*
- **IR5-T3 — Improvement loop repurpose.** `experiments/*`: variants become brain system-prompt /
  question-ordering deltas; `evaluation.py` compares **Classification Accuracy** against a
  documented baseline (replacing objection-recovery). Promotion stays human-approved. *(R10)*

## Phase IR-6 — Teardown, dashboard, docs
- **IR6-T1 — Delete dead machinery + tests.** Remove `decisioning.py`, `discovery.py`, `closing.py`,
  `objections.py`, the two playbook YAMLs, `extraction.py`, the old `variants.py`, and `router.py`
  as a controller; delete/rewrite their tests. Confirm `ruff` + `pytest` green. *(cleanup)*
- **IR6-T2 — Dashboard API fields.** Extend `dashboard/router.py` to expose the new metrics and the
  per-call **slot state + reached leaf + quoted price** + decision trace as JSON. The **UI** for
  these lands in **Phase IR-7** (the live call-center dashboard) — this ticket is the read API only.
  *(R9)*
- **IR6-T3 — Docs + deploy.** Reconcile `PRD.md`/`README.md`/`RUNBOOK.md` to the router scope;
  finalize `docs/decision-log.md`; (optional, R13) Dockerfile for one-command run + GCP Cloud Run
  note. *(R13)*

## Phase IR-7 — Live call-center dashboard (observe-only, React)
The headline front end: an operator watches calls **arrive and stream in real time** — live
transcript (prospect + agent), per-turn decision trace, and turn-latency + insight panels.
**Observe-only for v1** (one-way push; operator takeover/escalation is a documented later phase).
**Simulated calls first**, then a real inbound channel via Twilio. New code lives in
`frontend/dashboard-app/` (Vite + React, per R13); FastAPI serves the production build at
`/dashboard` and gains a streaming endpoint.

- **IR7-T1 — Turn-latency instrumentation.** Measure each turn end-to-end: in the engine, wall-time
  of the brain decision + tool calls; in `voice/bot.py`, STT-final → first TTS audio frame. Persist
  on `Turn` (additive `latency_ms`, plus an optional `latency_breakdown` JSON: stt / brain / tts)
  and compute **p50/p95** turn latency in `kpis/metrics.py` (replaces the current
  `average_latency_seconds = None`). Closes the VC-3 measurement gap. *(VC-3, R9)*
- **IR7-T2 — Live event bus + stream endpoint.** In-process asyncio pub/sub; `agent/recorder.py`
  publishes events on **call_started, turn (prospect/agent), decision, kpi, call_ended**. Serve
  them over **SSE** — `GET /api/stream` (all active calls) and `GET /api/calls/{id}/stream` (one
  call) via `sse-starlette`. SSE (one-way, auto-reconnecting) is the right fit for an observe-only
  board; WebSocket is the documented upgrade when operator-takeover lands. *(R9)*
- **IR7-T3 — Simulated live feed ("calls come in").** `POST /api/sim/start {persona}` runs a
  `simulator/runner.py` call in the background through the **real brain**, pacing turns so the
  dashboard shows the call appear and the transcript stream in live. This is the "simulated at
  first" path and the primary demo driver before Twilio. *(R10)*
- **IR7-T4 — React app scaffold.** Vite + React in `frontend/dashboard-app/`; dev proxy to FastAPI;
  production build served static at `/dashboard`. An `EventSource` client for the SSE stream + the
  existing REST endpoints for history. Replaces the static `frontend/dashboard/`. *(R13)*
- **IR7-T5 — Live call board + transcript.** Active-call cards (caller/channel, current stage →
  reached slot/leaf, elapsed clock, rolling latency); click-through to a live view: streaming
  prospect/agent transcript bubbles, the per-turn decision trace (action, reason, confidence, leaf),
  the **reached leaf + quoted price**, and guardrail/mis-quote flags. *(R9)*
- **IR7-T6 — Insights panel.** Live + historical **turn-latency p50/p95**; tiles for
  Classification Accuracy, Mis-Quote, Over-Ask, Escalation (from IR-5 metrics); active-call count;
  per-call **slot-fill progress** (which taxonomy slots are filled), per-turn **confidence trend**,
  and **KB-lookup hit/miss**. *(R9, R10)*
- **IR7-T7 — Twilio inbound (deferred / stretch).** Twilio Voice + **Media Streams** webhook bridges
  inbound PSTN audio into the existing Pipecat STT path; inbound calls surface on the same live
  stream tagged `channel=twilio`. Needs a Twilio number/account — documented as the "then hooked in"
  follow-on, not a v1 blocker. *(channel)*

> **Ordering:** IR7-T1/T2/T4 can start as soon as the new engine (IR-2) exists; the insight tiles
> (T6) light up as IR-5 metrics land; T7 is the deferred real-channel step. The simulated feed (T3)
> makes the whole dashboard demoable with **no audio hardware and no Twilio**.

---

## Data-model notes
- `db/models.py` is largely reusable. Additive columns likely needed on `Call`: `reached_leaf`,
  `quoted_price`; slot state can ride in `Lead.collected_fields` (JSON) + the `Decision` trace.
- IR-7 adds `Turn.latency_ms` (+ optional `Turn.latency_breakdown` JSON) for the latency panels.
- **Migration caution:** the project has no migration tool (per `BUILD_PLAN.md` P10-T3 note) — any
  new column means recreating the dev DB before the next run. Flag in the ticket that adds columns
  (IR-1/IR-5 `Call` columns; IR-7 `Turn` columns).

## Validation strategy
- Pure modules (`taxonomy`, `pricing`, guardrail mis-quote) get unit tests first — they're the
  correctness anchors.
- The brain is tested in **text mode** through the real engine (no audio) against ground-truth
  personas → the benchmark *is* a test artifact, not just a demo.
- Offline path (no OpenAI key) must keep `pytest` green via the TF-IDF fallback + a scripted brain
  stub, mirroring the existing offline experiment smoke path.

## Open questions (carried from requirements, resolve in-phase)
- IR2: one brain call/turn vs. streaming with tool interleaving; barge-in vs. in-flight tool call.
- IR2-T2/R5b: confidence threshold for `quote_price` — brain-judged vs. deterministic slot-complete gate.
- IR3: keep TF-IDF as permanent fallback or remove once vector path is proven?
- IR5-T1: personas per leaf and how ambiguity is modeled.
- IR4-T1: exact `STTMuteFilter`/VAD config that suppresses echo but honors barge-in.
