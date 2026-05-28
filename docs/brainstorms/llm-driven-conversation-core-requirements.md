---
date: 2026-05-28
topic: llm-driven-conversation-core
status: superseded
superseded_by: docs/brainstorms/intent-router-agent-requirements.md
---

> **Superseded (2026-05-28):** the LLM-brain architecture here is retained, but the qualification
> target narrowed from full discovery-to-close to a 2-option intent classifier (test prep vs.
> tutoring) that quotes a price at the leaf. See `intent-router-agent-requirements.md`.

# LLM-Driven Conversation Core (Voice Sales Agent Re-Architecture)

## Summary

Replace the gagged deterministic state machine at the heart of the voice sales agent with an
**LLM-driven conversation core**: STT feeds the full transcript to an LLM that decides each turn
and composes the reply, with the existing deterministic pieces (qualification slots, KB grounding,
guardrails, KPI traces, close logic) demoted from *controllers* to *tools/rails* the LLM calls.
The agent becomes a fluent "sales filter" — it converses naturally while continuously qualifying
the prospect and slotting captured facts into structured state. Voice stays a **composed**
pipeline (STT → LLM brain → TTS) with the brain kept transport-agnostic so a speech-to-speech
swap remains a future option, not a prerequisite.

---

## Problem Frame

The current build implements every functional requirement in `docs/challenge.md` but fails the
one thing a conversation cannot live without: it does not respond to what the caller says. Tracing
one default ("progress") turn through `backend/app/agent/engine.py`:

1. `router.classify_turn(text)` buckets the turn into one branch via **keyword/cue detectors**
   (`escalate > stop_selling > objection > knowledge > progress`).
2. `extraction` files the utterance into a slot (coarse — stores the cleaned utterance as the
   field value).
3. `DiscoveryDecider.decide(state, user_text)` **ignores `user_text` entirely** — it returns "ask
   the next unfilled playbook slot" based only on which fields are empty.
4. `render` calls the LLM, but for discovery lines instructs it to *"add no new information, just
   rephrase"* — so the model literally cannot react to what was said.

The lived result, in the user's words: *"I say something and it's like what I say is not being
heard."* The LLM is present but gagged — used for phrasing, banned from comprehension and
decision-making. The repo's own `docs/failure-modes.md` already documents the symptoms: the
identical fallback firing 3× in one call (mode 4), and a clear buying signal — *"what would next
steps look like?"* — met with a deflection because it mis-routed to KNOWLEDGE → KB miss → verbatim
fallback (mode 6). Two secondary contributors compound it: keyword routing mis-classifies anything
its detectors miss, and `STTMuteFilter(ALWAYS)` in `backend/app/voice/bot.py` drops the caller's
speech entirely whenever the agent is talking.

This is a design-level miscast, not a tuning problem: no threshold makes a checklist listen.
Separately, the stack the build chose (Anthropic Claude, Pipecat, SQLite, static HTML) diverges
from the technology list the work is being evaluated against (OpenAI, FastAPI, React, Docker,
AWS/GCP, plus STT/TTS, KB, synthetic data, PII transcript DB), so the re-architecture is also the
moment to reconcile the stack on defensible grounds.

---

## Actors

- A1. **Prospect (parent/student):** the caller the agent converses with; the agent must qualify
  them honestly and fluidly, react to what they actually say, and never feel scripted.
- A2. **Sales operator/manager (primary buyer):** runs and improves the autonomous agent; needs to
  see per-turn decisions, KPIs, and improvement-loop evidence through a dashboard.
- A3. **LLM brain (pipeline agent):** the new decision-maker — reads the transcript + lead memory
  each turn, calls tools (slot-fill, KB lookup, escalate, close), and composes the reply.
- A4. **Synthetic prospect (pipeline agent):** persona-driven self-play caller that drives the
  *same* brain in text mode to power the recursive-improvement loop.

---

## Key Flows

- F1. **Live qualifying turn (the "sales filter")**
  - **Trigger:** STT emits a final transcript for a caller utterance.
  - **Actors:** A1, A3
  - **Steps:** transcript + running history + known lead fields → LLM brain → brain decides:
    respond/ask/answer/escalate/close and emits any `slot_fill` calls for facts the caller
    volunteered → guardrail check on the composed text → TTS speaks it → recorder persists
    transcript turn, decision (with reason + confidence), captured slots, and KPI events.
  - **Outcome:** the caller is answered in context, new facts are slotted into qualification
    state, and a clean decision trace is recorded.
  - **Covered by:** R1, R2, R3, R5, R7, R8

- F2. **Grounded knowledge / objection answer**
  - **Trigger:** the caller asks a policy/pricing/competitive question or raises an objection.
  - **Actors:** A1, A3
  - **Steps:** brain calls `kb_lookup` → retrieval returns scored snippets with source IDs → brain
    composes an answer **only** from returned snippets → if retrieval is insufficient, brain gives
    the honest fallback and/or escalates → text passes the §18 output guard before TTS.
  - **Outcome:** grounded answer with source attribution, or an honest deferral — never a
    hallucinated price/policy/guarantee.
  - **Covered by:** R4, R7

- F3. **Recursive improvement loop (shared brain)**
  - **Trigger:** an experiment run is started against a chosen dimension (e.g., a price rebuttal).
  - **Actors:** A4, A3, A2
  - **Steps:** synthetic personas drive the **same** brain in text mode → calls are scored on the
    KPIs → variants are compared against a documented baseline → promote/retire decision surfaced
    to the operator.
  - **Outcome:** a measurable KPI movement with before/after evidence, using the real decision
    logic (not a separate code path).
  - **Covered by:** R6, R9

---

## Requirements

**Conversation core (the rebuild)**
- R1. The LLM brain receives the full running transcript (plus known lead fields and qualification
  state) each turn and decides the turn — what to say, what to ask next, whether to answer,
  escalate, or move toward close. It is not constrained to a pre-chosen line.
- R2. Turn routing is driven by the brain's understanding of the utterance, not by standalone
  keyword/cue classifiers. Legacy detectors may remain only as advisory signals, never as the
  sole router.
- R3. The reply is composed from the actual caller turn in context; the "add no new information,
  just rephrase" rendering constraint is removed for conversational turns.
- R7. Deterministic capabilities are exposed to the brain as **tools/rails**, not controllers:
  `slot_fill(field, value)`, `kb_lookup(query)`, `escalate(reason)`, `attempt_close(next_step)`.
  The brain must call `kb_lookup` before stating any policy/pricing/competitive fact.

**Sales-filter qualification**
- R5. As the conversation flows, the brain captures prospect facts into structured qualification
  slots via `slot_fill`, so qualification state is deterministic and observable even though the
  dialogue is free-form. Known fields are skipped/confirmed rather than re-asked.
- R8. The agent decides in real time when to keep qualifying, when to pivot toward close, and when
  to escalate (low-confidence turns, pricing concessions, explicit human-handoff requests).

**Guardrails & honesty (preserved from current design)**
- R4. The agent never states an unapproved price, policy, or guarantee as fact, and never claims
  to be human. Grounded answers cite source IDs; insufficient retrieval yields an honest fallback.
- R7b. The §18 output guard runs on the **composed text before TTS**, substituting a safe handoff
  on a hard violation (claims-human / guarantee). (Preserving the text-boundary guard is a stated
  reason for choosing composed voice over speech-to-speech.)

**Observability & improvement (graded deliverables)**
- R6. The same brain drives both live calls (STT-fed) and synthetic self-play (text-fed); the
  recursive-improvement loop tests the real decision logic, not a parallel path.
- R9. Every turn persists a decision trace (chosen action, reason, confidence), captured slots, and
  KPI events, surfaced through the dashboard for per-call review and KPI tracking.

**Voice transport & "not heard" fixes**
- R10. Voice stays a composed pipeline (STT → brain → TTS); the brain is implemented as a
  transport-agnostic decision layer so a speech-to-speech (OpenAI Realtime) swap is a documented
  future option, not required now.
- R11. The mic-mute behavior (`STTMuteFilter`) is corrected so genuine caller speech during agent
  output is not silently dropped (preserve echo suppression without discarding real barge-in).

**Stack reconciliation**
- R12. Adopt the evaluated stack where it earns its place: **OpenAI** as the brain + embeddings,
  **FastAPI** (already), **React** for the dashboard, **Docker** for one-command run, deploy target
  on **GCP** (e.g., Cloud Run). STT/TTS via Deepgram/Cartesia (or OpenAI pieces).
- R13. **LangChain** and **TensorFlow** are deliberately omitted from the core agent, with the
  rationale recorded in `docs/decision-log.md`. Optional, clearly-bounded placements (LangChain
  for the KB retrieval chain; a TensorFlow/scikit transcript-derived classifier in the improvement
  loop) may be added only to demonstrate the skill — never on the conversation hot path.

---

## Acceptance Examples

- AE1. **Covers R1, R2, R3, R5.** Given the agent just asked about the student's grade level, when
  the caller answers *and* volunteers "and honestly we're worried about the SAT in the fall," the
  agent acknowledges the SAT concern in its next reply and slot-fills both grade level and the SAT
  goal — it does not ignore the concern and ask the next checklist item.
- AE2. **Covers R7, R8.** Given discovery is sufficiently complete, when the caller says "what
  would next steps look like?", the agent treats it as a buying signal and calls
  `attempt_close` — it does not mis-route to a KB lookup and defer.
- AE3. **Covers R4, R7, R7b.** Given the KB has no approved figure for a discount, when the caller
  demands "just give me 20% off," the agent does not invent a number — it gives the honest
  deferral and/or escalates, and the output guard confirms no guarantee/price was asserted.
- AE4. **Covers R6.** Given a new price-rebuttal variant, when it is run against synthetic personas
  in text mode, the exact same decision code path executes as on a live call.
- AE5. **Covers R11.** Given the agent is mid-sentence, when the caller interrupts with a real
  utterance, that utterance reaches STT and is processed (barge-in honored) rather than being
  dropped by the mute filter.

---

## Success Criteria

- A human tester holds a discovery-to-close voice call and reports the agent *responded to what
  they said* every turn — the "not heard" symptom is gone.
- The agent completes a full discovery-to-close conversation live, qualifying the prospect into
  structured slots while sounding like a real call, not a script reader.
- Per-call decision traces, captured slots, and KPIs are visible in the dashboard; an operator can
  review *why* the agent did what it did each turn.
- At least one recursive-improvement loop moves a real KPI (e.g., objection-recovery) from a
  documented baseline, using the shared brain — with before/after evidence.
- A downstream planner can read this doc and the decision log and implement without re-deciding the
  architecture, the stack, or what "qualification" means.

---

## Scope Boundaries

- Speech-to-speech (OpenAI Realtime) is **out of scope for this iteration** — kept as a documented
  future swap enabled by the transport-agnostic brain (R10). Not a v1 deliverable.
- LangChain and TensorFlow on the conversation hot path are out of scope (R13).
- Telephony / WhatsApp channels remain out of scope; web/WebRTC is the demo channel.
- Replacing SQLite with Postgres and full cloud auto-deploy are out of scope beyond a single
  documented deploy; production data-store hardening is deferred.
- Approved/legal Nerdy pricing & policy KB content is still owed (placeholder today) — not produced
  by this work, but the grounding rails (R4) must behave correctly once it lands.
- Auto-promotion of variants without human review remains out of scope; promotion stays
  human-approved.

---

## Key Decisions

- **LLM drives, rails constrain** (chosen over hybrid/patch): the root cause is a gagged LLM, so
  the brain must own the turn decision; deterministic pieces become tools. A patch within the FSM
  would raise the ceiling but not remove the "not heard" feeling.
- **Composed voice over speech-to-speech:** "not heard" is a brain problem, not a transport
  problem. Composed preserves the text-boundary output guard (R7b), a clean per-turn decision trace
  (graded observability), and one shared brain across live + self-play (graded improvement loop) —
  all of which STS works against. STS's naturalness edge does not outweigh these for how the brief
  is judged.
- **Stack: capabilities over brand-matching, with documented choices:** adopt OpenAI/FastAPI/
  React/Docker/one-cloud where they add value; omit LangChain (direct SDK = lower latency, clearer
  traces) and TensorFlow (no honest hot-path home) with rationale in the decision log. Showing this
  judgment is a stronger review signal than ticking every box.

---

## Dependencies / Assumptions

- Assumes an OpenAI API key and acceptable per-minute cost for the live demo.
- Assumes the existing recorder, KPI vocabulary, persona simulator, and KB retriever are reusable
  under the new brain (they are transport-agnostic today); verify during planning.
- Assumes the provided PII-substituted transcript dataset is available to feed persona generation
  (and any optional classifier).
- Assumes Deepgram/Cartesia (or OpenAI STT/TTS) remain available via the Pipecat transport.

---

## Outstanding Questions

### Resolve Before Planning

- _(resolved)_ Cloud target: **GCP** (Cloud Run for the containerized demo deploy).

### Deferred to Planning

- [Affects R1, R7][Technical] Exact tool-calling contract and system-prompt structure for the
  brain (one call/turn vs. streaming with tool interleaving); how barge-in interacts with an
  in-flight tool call.
- [Affects R6][Technical] How the shared brain is fed text in self-play vs. audio-derived text
  live without divergence in behavior.
- [Affects R9][Technical] What structured rationale the brain must emit so the decision trace stays
  as rich as today's deterministic trace.
- [Affects R11][Needs research] Correct STTMuteFilter / VAD configuration to suppress agent echo
  while honoring genuine barge-in, validated against real audio.
- [Affects R8][Technical] Close-readiness and escalation thresholds — how much stays deterministic
  (tool-gated) vs. delegated to the brain's judgment.
