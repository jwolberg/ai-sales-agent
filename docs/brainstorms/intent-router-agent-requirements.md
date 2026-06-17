---
date: 2026-05-28
topic: intent-router-agent
supersedes: docs/brainstorms/llm-driven-conversation-core-requirements.md
---

# Voice Intent-Router Agent (Narrowed Direction)

## Summary

Narrow the voice agent from a full discovery-to-close sales agent to a **two-option intent
router**: through natural conversation the agent figures out whether the caller wants **test prep**
or **tutoring**, drills down to the specific test/subject, **quotes the price for that program**,
and answers informational questions from a grounded KB along the way. The LLM-driven conversation
core from the prior brainstorm is kept — the LLM owns each turn and the deterministic pieces are
tools/rails — but the qualification target shrinks to a small, gradeable classification tree. This
deletes the hardest unsolved problems of the old design (when to close, objection recovery) and
buys a crisp, objective success metric: did the agent reach the correct leaf, and how efficiently.

The infrastructure is **modified, not rebuilt**: voice pipeline, transcript/decision-trace/KPI
persistence, dashboard, and the synthetic self-play simulator are reused; the discovery-to-close
playbook, objection/close logic, and the "rephrase only, add no info" rendering gag are removed.

---

## The Taxonomy (classification target)

```
Caller intent
├── Test Prep        ← option 1
│   ├── SAT
│   ├── ACT
│   └── PSAT
└── Tutoring         ← option 2
    ├── Math
    │   ├── Algebra
    │   └── Geometry
    └── Science
        ├── Chemistry
        ├── Biology
        └── Physics
```

A **leaf** is a fully-specified need (e.g. `test_prep/SAT`, `tutoring/science/chemistry`). The
agent's job is to converse until it can name the leaf with confidence, then quote that leaf's price.

---

## Problem Frame

The current build implements the product requirements but the conversation core does not respond to what
the caller says — the LLM is "gagged" (used only to rephrase a pre-chosen checklist line; see the
prior brainstorm's trace through `engine.py`). Two paths out existed: rebuild a fluent
discovery-to-close brain, or **narrow the job to something a fluent brain can do reliably and we can
grade objectively.** This doc takes the second path. Classifying into a fixed 8-leaf tree and
quoting a price is a job an LLM brain does well, is honest about (price is a lookup, not a
generation), and yields a hard accuracy benchmark for the recursive-improvement loop.

---

## Actors

- **A1. Prospect (parent/student):** the caller; volunteers needs in natural language ("my kid is
  failing chemistry", "we're worried about the SAT in the fall"), sometimes ambiguous ("she's
  struggling in school").
- **A2. Sales operator/manager (primary buyer):** runs and improves the router; needs per-turn
  decisions, the running slot state, KPIs, and improvement-loop evidence via the dashboard.
- **A3. LLM brain (pipeline agent):** the decision-maker — reads transcript + known lead fields +
  current slot state each turn, calls tools (`slot_fill`, `kb_lookup`, `quote_price`, `escalate`),
  and composes the reply.
- **A4. Synthetic prospect (pipeline agent):** persona with a **known ground-truth leaf**; drives
  the same brain in text mode to power the accuracy benchmark and improvement loop.

---

## Key Flows

- **F1. Classifying turn (the core loop).** STT emits a final transcript → brain reads it in context
  with current slot state → brain decides: acknowledge + ask the next disambiguating question, or
  answer a question, or (if the leaf is now confident) move to quote → emits `slot_fill` calls for
  any facts volunteered → guardrail check on composed text → TTS → recorder persists the turn,
  decision (action + reason + confidence), updated slots, and KPI events. *(R1, R2, R3, R5, R8)*
- **F2. Price quote at the leaf.** When the brain is confident in a leaf, it calls
  `quote_price(leaf)` → **deterministic exact lookup** in a price table keyed by the leaf → brain
  states the price grounded in that record. If confidence is low, the brain asks one more question
  instead of quoting. *(R6, R4)*
- **F3. Grounded informational answer.** Caller asks an explainer ("what's the difference between
  SAT and ACT?", "what does a tutoring session involve?") → brain calls `kb_lookup(query)` →
  semantic retrieval over the KB returns scored snippets with source IDs → brain answers **only**
  from snippets, or gives the honest fallback if retrieval is insufficient → output guard before
  TTS. *(R7, R4)*
- **F4. Recursive-improvement loop (shared brain).** Synthetic personas with known leaves drive the
  same brain in text mode → each call scored on classification accuracy, turns-to-classify,
  over-asking, and mis-quote rate → variants (e.g. system-prompt or question-ordering changes)
  compared against a documented baseline → promote/retire surfaced to the operator. *(R9, R10)*

---

## Requirements

**Conversation core (reused from prior brainstorm)**
- R1. The brain receives the full running transcript + known lead fields + current slot state each
  turn and decides the turn; it is not constrained to a pre-chosen line.
- R2. Turn routing is driven by the brain's understanding, not standalone keyword classifiers.
  Legacy detectors may remain only as advisory signals.
- R3. The reply is composed from the actual caller turn in context; the "add no new information"
  rendering gag is removed.

**Classification (the narrowed target)**
- R5. Slots are the tree path: `category ∈ {test_prep, tutoring}`, then `test ∈ {SAT, ACT, PSAT}`
  (test prep) **or** `subject_area ∈ {math, science}` → `subject ∈ {algebra, geometry | chemistry,
  biology, physics}` (tutoring). The brain fills these via `slot_fill` as facts surface; known/
  implied values are not re-asked.
- R8. When the leaf is not yet determined, the brain asks the **next single most disambiguating
  question** rather than interrogating a checklist; ambiguous answers ("struggling in school")
  trigger a clarifying question, not a guess.
- R5b. The brain reaches a leaf with an explicit confidence; it only proceeds to `quote_price` above
  a confidence threshold, otherwise it asks one more question or escalates.

**Pricing (the endpoint) — correctness-critical**
- R6. Price is a **deterministic table keyed by leaf**, never produced by retrieval or generation.
  `quote_price(leaf)` does an exact lookup and returns the authoritative record; the brain may only
  state a price that came from this tool. No leaf → no price.
- R6b. If no approved price exists for a leaf, the agent gives the honest fallback / escalates — it
  never invents or estimates a number.

**Knowledge base (informational Q&A)**
- R7. Explanatory/policy content is grounded via semantic retrieval. **Stack: OpenAI
  `text-embedding-3-small` for embeddings, stored and searched with `sqlite-vec` in the existing
  SQLite DB.** Answers cite source IDs; insufficient retrieval yields the honest fallback. The KB is
  *not* the source of prices (R6).

**Guardrails & honesty (preserved)**
- R4. The agent never states an unapproved price, policy, or guarantee as fact and never claims to
  be human. Grounded answers cite sources; insufficient retrieval → honest fallback.
- R4b. The output guard runs on composed text **before TTS**, substituting a safe handoff on a hard
  violation (claims-human / unapproved guarantee / off-table price).

**Observability & improvement (graded deliverables)**
- R9. Every turn persists a decision trace (chosen action, reason, confidence, current slot state),
  captured slots, and KPI events, surfaced in the dashboard for per-call review.
- R10. The same brain drives live calls (STT-fed) and synthetic self-play (text-fed); the
  improvement loop tests the real decision path. Synthetic personas carry a ground-truth leaf so
  classification accuracy is measurable.

**Voice transport & "not heard" fixes (preserved)**
- R11. Voice stays a composed pipeline (STT → brain → TTS) with a transport-agnostic brain; STS
  swap remains a documented future option.
- R12. The `STTMuteFilter` behavior is corrected so genuine caller speech during agent output is not
  silently dropped (preserve echo suppression without discarding real barge-in).

**Stack reconciliation (preserved from prior brainstorm)**
- R13. Adopt the evaluated stack where it earns its place: OpenAI (brain + embeddings), FastAPI,
  React dashboard, Docker for one-command run, GCP (Cloud Run) deploy. LangChain/TensorFlow stay
  off the conversation hot path with rationale in `docs/decision-log.md`.

---

## New KPIs (replacing close/objection metrics)

- **Classification Accuracy** — % of calls that reach the correct leaf (vs. synthetic ground truth).
  The headline outcome metric and the improvement loop's target.
- **Turns-to-Classification** — median caller turns to a confident leaf; efficiency / "doesn't
  interrogate."
- **Over-Ask Rate** — % of questions that re-asked something the caller already stated or implied.
- **Mis-Quote Rate** — % of calls where a price was stated that didn't match the leaf's table record
  (target: 0; guardrail on R6).
- **Escalation Rate** — two-sided health: too high = can't classify, too low = guessing past
  ambiguity it should clarify or hand off.
- **Unsupported-Claim Rate** — preserved guardrail KPI for informational answers (R4).

---

## Acceptance Examples

- **AE1 (R1,R2,R3,R5,R8).** Caller: "she's struggling in school." The agent does not guess a leaf —
  it asks one disambiguating question ("is this for a specific class, or prep for a test like the
  SAT?") and slot-fills nothing premature.
- **AE2 (R5,R6).** Caller: "we need help with chemistry." Brain fills `category=tutoring`,
  `subject_area=science`, `subject=chemistry`, reaches the leaf with high confidence, calls
  `quote_price(tutoring/science/chemistry)`, and states exactly the table price.
- **AE3 (R6,R6b,R4b).** No approved price exists for a leaf. The agent does not estimate — it gives
  the honest deferral / escalates, and the output guard confirms no off-table price was asserted.
- **AE4 (R7).** Caller: "what's the difference between the SAT and ACT?" Brain calls `kb_lookup`,
  answers only from returned snippets with source IDs, and uses the answer to help the caller pick a
  test (which then slot-fills the leaf).
- **AE5 (R10).** A synthetic persona whose ground-truth need is `test_prep/ACT` drives the brain in
  text mode through the exact same code path as a live call; the run is scored as correct/incorrect
  against that ground truth.
- **AE6 (R12).** The caller interrupts mid-sentence with a real utterance; it reaches STT and is
  processed (barge-in honored) rather than dropped by the mute filter.

---

## Success Criteria

- A human tester holds a voice call, is routed to the correct leaf without feeling interrogated, and
  hears the correct price for that leaf — the "not heard" symptom is gone.
- The synthetic benchmark reports a **Classification Accuracy** number over a persona set with known
  leaves, from a documented baseline; Mis-Quote Rate is 0.
- Per-call decision traces, slot state, and the new KPIs are visible in the dashboard.
- At least one improvement-loop iteration moves Classification Accuracy (or Turns-to-Classification)
  off the baseline using the shared brain, with before/after evidence.
- A downstream planner can implement from this doc + the decision log without re-deciding the
  architecture, stack, taxonomy, or pricing mechanism.

---

## Scope Boundaries

- Full discovery-to-close, objection recovery, and negotiation are **out** — the agent classifies
  and quotes, then hands off.
- The taxonomy is fixed at these 8 leaves for v1; adding programs is a data change, not new flows.
- Speech-to-speech (OpenAI Realtime), telephony/WhatsApp, and Postgres are out (documented future).
- Approved/legal Nerdy pricing & KB content is still owed (placeholder today); the rails (R4, R6)
  must behave correctly once real content lands.
- Auto-promotion of variants without human review stays out; promotion is human-approved.

---

## Key Decisions

- **Narrow to a 2-option router (chosen over rebuilding discovery-to-close):** a fixed classification
  tree is something a fluent LLM brain does reliably and we can grade objectively; it removes the
  old design's unsolved close/objection problems while still exercising voice, listening, slot-fill,
  disambiguation, KB grounding, and the improvement loop.
- **Price = deterministic table keyed by leaf, never retrieval (correctness-critical):** fuzzy
  retrieval of a price = quoting the wrong number, the one guardrail the build promises never to
  break. Retrieval stays for explanatory Q&A where fuzzy is fine; prices are exact lookups gated on
  a confident leaf.
- **KB on OpenAI `text-embedding-3-small` + `sqlite-vec`:** semantic retrieval for paraphrased
  questions, embeddings stored next to transcripts/KPIs in the existing SQLite file — no new service.
  Accepts an OpenAI dependency (aligns with the evaluated stack) over staying TF-IDF/offline.
- **Modify, not rebuild:** reuse voice/persistence/dashboard/simulator; delete the discovery-to-close
  brain and rendering gag; the change is concentrated in the conversation core + a small price table.

---

## Dependencies / Assumptions

- OpenAI API key for brain + embeddings; acceptable per-minute cost for the live demo.
- Existing recorder, KPI vocabulary, persona simulator, and KB ingestion are reusable under the new
  brain (verify during planning).
- `sqlite-vec` loads against the project's SQLite build (verify the extension loads in the runtime).
- A small authoritative price table (8 leaves) is authorable as placeholder now, real content later.
- Deepgram/Cartesia (or OpenAI STT/TTS) remain available via the Pipecat transport.

---

## Outstanding Questions (deferred to planning)

- [R1,R6] Tool-calling contract + system-prompt structure for the brain; how `quote_price` and
  barge-in interact with an in-flight tool call.
- [R5b] Where the confidence threshold for quoting lives — brain-judged vs. a deterministic gate on
  slot completeness.
- [R7] KB chunking + how `sqlite-vec` retrieval coexists with / replaces the current TF-IDF
  retriever; whether to keep TF-IDF as a fallback.
- [R10] Persona set design: how many personas per leaf, how ground-truth ambiguity is modeled.
- [R12] Correct STTMuteFilter / VAD config to suppress echo while honoring barge-in, validated on
  real audio.
