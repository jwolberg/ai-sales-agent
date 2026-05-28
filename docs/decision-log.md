# Decision Log

Major product and technical decisions for the Autonomous AI Sales Agent, in the
§23 template (Decision / Context / Options / Chosen / Reason / Tradeoffs / Date / Owner).
This log is the human-readable companion to `docs/implementation-notes.md` (which is the
running, ticket-level record). Where a decision is also captured in the build plan's
Planning Assumptions or Architecture Notes, it is cross-referenced.

---

## D-1 — STT+TTS pipeline vs. speech-to-speech

- **Context:** The agent needs real-time bidirectional voice (VC-1) but also a fully
  inspectable per-turn decision trace (DE-2) and grounded answers (KB-1).
- **Options Considered:** (a) a single speech-to-speech model; (b) a composed pipeline
  STT → Claude (reasoning/decisioning) → TTS.
- **Chosen Approach:** Composed pipeline — Deepgram (STT) → Claude (decisioning) →
  Cartesia (TTS), wired with Pipecat over WebRTC, Silero VAD for turn-taking.
- **Reason:** The decisioning layer must be Claude so every turn produces a structured
  decision (route, action, reason, confidence, KB sources) we can log and improve. A
  speech-to-speech black box would hide that trace and make grounding/guardrails harder.
  STT/TTS vendors stay pluggable.
- **Tradeoffs:** More moving parts and added pipeline latency vs. a single model; mitigated
  by the latency strategy (fillers, ambient bed; deferred caching/speculation — see D-9).
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-2 — Web (WebRTC) demo vs. phone/WhatsApp channel

- **Context:** The PRD allows phone, WhatsApp, or web for the demo.
- **Options Considered:** Twilio phone, WhatsApp voice, browser WebRTC.
- **Chosen Approach:** Browser WebRTC demo (`/demo`).
- **Reason:** Smallest viable channel — no telephony account, number provisioning, or
  carrier setup; runs locally with a mic. Telephony adds nothing to the core thesis.
- **Tradeoffs:** Not representative of real phone audio conditions (codec, jitter, noise);
  Twilio/WhatsApp deferred as nice-to-haves.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-3 — Human-approved variant promotion vs. auto-promotion

- **Context:** The improvement loop must promote or retire variants on evidence (§11.2).
- **Options Considered:** Auto-promote on the promotion rule; human-reviewed promotion.
- **Chosen Approach:** Human-reviewed for the MVP. The experiment run computes the §8 rule
  and recommends promote/retire; a human confirms before anything ships.
- **Reason:** Smallest safe option — keeps a person in the loop on customer-facing sales
  language and guardrail regressions. Auto-promotion is a later enhancement.
- **Tradeoffs:** Slower iteration; requires an operator to review the report.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-4 — Primary KPI: Objection Recovery Rate

- **Context:** The improvement loop needs one primary KPI to optimize.
- **Options Considered:** Close success rate, objection recovery rate, sentiment, discovery
  completion (PRD §16 candidates).
- **Chosen Approach:** Objection Recovery Rate (PRD-selected) — % of calls where a price
  objection occurs and the prospect still agrees to a next step.
- **Reason:** Directly measures the chosen improvement dimension (price rebuttal) and ties
  to conversion. Implemented as `objection_raised AND (close_attempt OR discovery_complete)`.
- **Tradeoffs:** Measured only over calls where an objection actually arose, so per-persona
  samples are small (see `docs/limitations.md`). Frustration and unsupported-claim rates are
  tracked as guardrails so the loop can't "win" by being pushy.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-5 — Improvement dimension: price-objection rebuttal

- **Context:** One meaningful recursive-improvement loop must be demonstrated.
- **Chosen Approach:** Price-objection rebuttal strategy (PRD §8 pre-selection): a baseline
  generic value statement vs. five candidate styles (empathy-first, outcome-cost,
  risk-reversal, comparison, diagnostic).
- **Reason:** Price sensitivity is common, high-impact, conversion-linked, and a strong test
  of "sounds like a salesperson, not a script."
- **Tradeoffs:** Other dimensions (discovery quality, escalation tuning) left for later loops.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-6 — Escalation threshold (DE-4)

- **Context:** The agent must escalate to a human when required and never oversell.
- **Chosen Approach:** Rule-based triggers in `app/agent/guardrails.py`: explicit human
  request, repeated dissatisfaction, high-risk objection (discount/contract), out-of-scope
  asks, plus a low-confidence fallback. Discount asks escalate; "too expensive" routes to
  objection handling (the split falls out of the router cleanly).
- **Reason:** Deterministic and auditable; high-risk objections hold the close gate.
- **Tradeoffs:** Conservative — may escalate borderline cases a tuned model wouldn't. Live
  human-trial tuning (P8-T1) is still pending.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-7 — KB grounding strategy: lexical TF-IDF retriever vs. vector store

- **Context:** Answers must be grounded in approved content with source IDs (KB-1/3) and
  fall back honestly when content is insufficient (KB-4).
- **Options Considered:** An embedding vector store (Chroma/`sqlite-vec`); a dependency-free
  lexical TF-IDF retriever.
- **Chosen Approach:** Lexical TF-IDF retriever (`app/kb/retriever.py`) over a markdown
  chunker with source IDs; answers gated by a tuned minimum score, else honest fallback.
- **Reason:** No new heavy dependency or embedding API; deterministic and easy to test for
  the small placeholder KB. A vector store is a drop-in upgrade if recall needs it.
- **Tradeoffs:** Lexical recall is weaker on paraphrase than embeddings; acceptable at the
  current KB size, revisit when real approved content lands.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-8 — Persistence: SQLite vs. Postgres

- **Context:** The PRD §15 data model must persist and round-trip.
- **Chosen Approach:** SQLite single-file via SQLAlchemy.
- **Reason:** Zero-setup local dev; the schema is portable to Postgres later without code
  changes of substance.
- **Tradeoffs:** Not suited to concurrent production load; a deliberate later swap.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-9 — Decider-led runtime (Phase 4.5 insertion)

- **Context:** The structured agent layer (router/decider/KB/objections/guardrails) was
  built but the live pipeline still ran raw Claude on the persona prompt and ignored it.
- **Chosen Approach:** Insert a transport-agnostic conversation engine (`app/agent/engine.py`):
  extract → route → dispatch → render → record, driving both the live voice path and the
  synthetic simulator. Replaced the overloaded `NextAction.prompt` with a structured
  Directive + a single pure `render` step.
- **Reason:** Without this, the agent layer had zero influence on what was said, and there
  was no meaningful decision trace or shared engine for self-play. The engine is a hard
  dependency for Phases 5–7.
- **Tradeoffs:** Added a phase (renumbered 4.5 to avoid shuffling 5–8); some latency tiers
  (FAQ cache, speculative prefetch, true pre-synthesized filler audio) deferred pending live
  measurement.
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-10 — Synthetic calls in text-mode self-play vs. real-time voice per run

- **Context:** Experiments need many calls (every variant × every persona) — too costly to
  run over real-time voice each time.
- **Chosen Approach:** Synthetic prospects run as Claude text-mode self-play through the same
  engine, writing the same Call/Turn/Decision/KPI records (labeled `is_synthetic=True`,
  channel `sim:<persona>`). Live voice is reserved for human trials and the demo.
- **Reason:** Same decision/scoring path as live, far cheaper and faster, fully reproducible.
- **Tradeoffs:** Text mode omits voice-specific failure modes (latency, barge-in, ASR
  errors) and carries synthetic-prospect bias (see `docs/limitations.md`).
- **Date:** 2026-05 · **Owner:** Jay Wolberg

## D-11 — Offline experiment mode must be truly no-LLM

- **Context:** `python -m app.experiments --offline` is meant as a free wiring smoke test.
- **Chosen Approach:** A scripted price-objection prospect used only offline (no Claude),
  so the smoke run spends zero tokens and is deterministic.
- **Reason:** An earlier offline path quietly built a Claude prospect and spent tokens.
- **Tradeoffs:** Offline recovery always shows 0% (rule-based extraction never closes) — it
  is a wiring check, not real numbers; real evidence requires the funded Claude run + judge.
- **Date:** 2026-05-27 · **Owner:** Jay Wolberg

## D-12 — Synthetic-only evidence for the first improvement loop; baseline held

- **Context:** The first real recursive-improvement run was fired on 2026-05-28.
- **Chosen Approach:** Accept the measured synthetic result as-is — **baseline held, no
  variant promoted** (all variants 0% objection-recovery; 3 regressed frustration) — rather
  than tuning the run to manufacture a "win."
- **Reason:** The 0% is a real result (verified: KPI events fire, but the agent rarely
  reaches a close in self-play and never recovers a price objection within the 12-turn cap),
  driven by placeholder rebuttal/KB content. The loop *mechanism* is what's proven; honest
  flat numbers are more valuable than a gamed promotion. See `docs/recursive-improvement.md`.
- **Tradeoffs:** No promoted variant to demo yet. Lifting the numbers needs approved
  rebuttal/KB copy (`docs/QandA_opens.md`) and/or a larger turn budget, then a re-fire.
- **Date:** 2026-05-28 · **Owner:** Jay Wolberg

## D-13 — Narrow scope to a two-option intent router

- **Context:** The discovery-to-close build implemented every requirement but the
  conversation core didn't respond to what the caller said (gagged LLM; see
  `docs/brainstorms/llm-driven-conversation-core-requirements.md`), and "did the agent sell
  well?" had no objective metric. A new direction was needed.
- **Options Considered:** (a) rebuild a fluent discovery-to-close brain; (b) narrow the job
  to a fixed classification the brain can do reliably and we can grade objectively.
- **Chosen Approach:** (b) — a voice **intent router**: classify the caller into test prep
  (SAT/ACT/PSAT) vs. tutoring (math/science → subject), then quote that leaf's price.
  Modify, not rebuild: reuse voice/persistence/dashboard/simulator; delete the
  discovery-to-close machinery. Driven by `docs/brainstorms/intent-router-agent-requirements.md`,
  planned in `docs/BUILD_PLAN_INTENT_ROUTER.md`.
- **Reason:** A fixed 8-leaf tree is something a fluent LLM brain does reliably, removes the
  old design's unsolved problems (when to close, objection recovery), and yields a hard
  **Classification Accuracy** benchmark that turns the recursive-improvement loop into a real
  number instead of fuzzy scoring.
- **Tradeoffs:** Drops the broader "carry a whole sale" ambition; the agent classifies and
  quotes, then hands off. Accepted for reliability + demo-ability + a gradeable metric.
- **Date:** 2026-05-28 · **Owner:** Jay Wolberg

## D-14 — Price = deterministic table keyed by leaf, never retrieval

- **Context:** The router's endpoint is quoting a price. Retrieval (TF-IDF or vector) is
  fuzzy by design; the build promises it never invents/misstates a price (§18 guardrail).
- **Options Considered:** (a) retrieve price from the KB like any other content; (b) exact
  lookup in a structured table keyed by the classification leaf.
- **Chosen Approach:** (b) — `quote_price(leaf)` does an exact lookup; the agent may only
  state a price returned by that tool, and only once the leaf is confident. The KB/vector
  store is for explanatory Q&A only.
- **Reason:** Fuzzy retrieval of a price = quoting the wrong number, the one guardrail we
  promise never to break. An exact table keeps prices correct while retrieval stays fuzzy
  where fuzzy is fine. A `MIS_QUOTE_BLOCKED` guardrail enforces it at the output boundary.
- **Tradeoffs:** Prices must be authored as structured data per leaf (placeholder until
  approved content lands); no "smart" price synthesis. Accepted — correctness is the point.
- **Date:** 2026-05-28 · **Owner:** Jay Wolberg

## D-15 — KB on OpenAI text-embedding-3-small + sqlite-vec

- **Context:** Informational Q&A ("SAT vs ACT?") needs semantic retrieval over a small
  corpus; the current retriever is dependency-free TF-IDF. The work is also evaluated
  against a stack that expects OpenAI.
- **Options Considered:** (a) keep TF-IDF; (b) local sentence-transformers + FAISS/Chroma;
  (c) OpenAI `text-embedding-3-small` + `sqlite-vec` in the existing SQLite DB.
- **Chosen Approach:** (c) — OpenAI embeddings stored/searched via `sqlite-vec` next to the
  transcripts/KPIs; TF-IDF kept as the offline/no-key fallback so tests run without OpenAI.
- **Reason:** Semantic match for paraphrased questions, no new datastore/service, aligns
  with the evaluated stack. Corpus is tiny so cost/latency are negligible.
- **Tradeoffs:** Adds an OpenAI dependency + key; `sqlite-vec` extension must load in the
  runtime (verified early in IR3-T1). Accepted.
- **Date:** 2026-05-28 · **Owner:** Jay Wolberg

## D-16 — Live call-center dashboard: observe-only, React, SSE

- **Context:** The front end becomes the focus — a call-center dashboard where an operator
  watches calls arrive, reads the live agent/prospect transcript, and sees turn latency +
  insights. The current frontend is static HTML/JS that polls REST; there's no live push and
  turn latency is never measured (`metrics.py` returns `average_latency_seconds = None`).
- **Options Considered:** (a) observe-only vs. full console with operator takeover;
  (b) React (per R13) vs. extend the vanilla dashboard; (c) SSE vs. WebSocket for live push.
- **Chosen Approach:** **Observe-only v1**, **React** (Vite SPA per R13), live updates over
  **SSE**. Simulated calls drive it first (`POST /api/sim/start`); Twilio Media Streams inbound
  is a deferred sub-ticket (IR7-T7). Planned as Phase IR-7 in `docs/BUILD_PLAN_INTENT_ROUTER.md`.
- **Reason:** Observe-only is the smallest thing that delivers the demo and avoids bidirectional
  control + barge-into-engine complexity. SSE (one-way, auto-reconnect, plain HTTP) is the
  textbook fit for a read-only board; React aligns with the evaluated stack and the real-time UI.
  A simulated live feed makes the whole dashboard demoable with no audio hardware or Twilio.
- **Tradeoffs:** No operator takeover yet (deferred); WebSocket is the documented upgrade path
  when takeover lands. Adds React build tooling and turn-latency instrumentation work.
- **Date:** 2026-05-28 · **Owner:** Jay Wolberg
