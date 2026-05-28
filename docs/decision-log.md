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
