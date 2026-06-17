---
name: Voice Intent-Router Agent
last_updated: 2026-05-28
supersedes_scope: docs/BUILD_PLAN.md (discovery-to-close)
---

# Voice Intent-Router Agent Strategy

## Target problem

Nerdy's inbound callers arrive 24/7 wanting different things — test prep or subject tutoring — but
live agents are limited in hours and consistency, and the first job on every call (figure out what
the caller actually needs, then tell them what it costs) is exactly the part that's mechanical,
high-volume, and easy to get wrong or slow. A static phone tree can't hold a real conversation; a
human is overkill for routing-and-quoting.

## Our approach

Build a **narrow, reliable voice agent that does one job well**: converse naturally to determine
whether the caller wants **test prep** (SAT / ACT / PSAT) or **tutoring** (math: algebra, geometry;
science: chemistry, biology, physics), drill to the specific leaf, and **quote that leaf's price**
from an authoritative table — answering informational questions from a grounded KB along the way.
Because the job is a fixed classification into 8 leaves, success is **objectively gradeable**: every
call is observed, versioned, and replayed against synthetic prospects whose true need is known, so
the agent compounds toward accuracy instead of staying a static script.

## Who it's for

**Primary:** Nerdy sales operator/manager — hiring this to run an always-on front door that routes
and quotes correctly, and to *prove* it's getting more accurate over time (see what it decided, why,
and the trend).

**Secondary:** the prospect (parent/student) — the agent must classify them honestly and fast,
without interrogating them or quoting a wrong number.

## Key metrics

- **Classification Accuracy** — % of calls that reach the correct leaf vs. synthetic ground truth;
  the headline outcome and the improvement loop's target.
- **Turns-to-Classification** — median caller turns to a confident leaf; efficiency / "doesn't
  interrogate."
- **Over-Ask Rate** — % of questions that re-asked something the caller already stated or implied.
- **Mis-Quote Rate** — % of calls stating a price that didn't match the leaf's table record
  (target: 0; the core honesty guardrail).
- **Escalation Rate** — two-sided health: too high = can't classify; too low = guessing past
  ambiguity it should clarify or hand off.
- **Unsupported-Claim Rate** — guardrail for informational answers (grounded, sourced, or honest
  fallback — never invented).

## Tracks

### The agent (classify + quote)

Realtime composed voice (STT → LLM brain → TTS) with barge-in and a consistent persona. An
LLM-driven core owns each turn, fills the taxonomy slots from what the caller says, asks the next
most disambiguating question when uncertain, answers explainer questions from a `sqlite-vec` KB
(OpenAI `text-embedding-3-small`), and quotes a price by **exact table lookup keyed by the leaf** —
never by retrieval, never invented.

_Why it serves the approach:_ a gradeable system is worthless if the thing being graded can't hold
a real, honest call — this is what the loop optimizes, now scoped to a job it can do reliably.

### Observability & the call-center dashboard

A **live call-center dashboard** is the operator's primary surface: calls appear as they come in
(simulated first, then Twilio inbound), with the agent/prospect transcript streaming in real time,
per-turn decision traces (chosen action, reason, confidence, current slot state, reached leaf,
quoted price), turn-latency p50/p95, and insight panels (slot-fill progress, confidence trend,
guardrail/mis-quote flags). Backed by full transcripts and version attribution for historical
review.

_Why it serves the approach:_ "every call observed and versioned" is the substrate, and the live
board is exactly what the operator buys — watching the autonomous force work, with the slot/leaf
trace making any misclassification debuggable on the spot.

### Recursive improvement loop

Synthetic personas with a **known target leaf** drive the same brain in text mode; the experiment
engine varies the brain's prompt / question ordering and promotes only what raises Classification
Accuracy off a documented baseline without regressing the guardrail KPIs (Mis-Quote, Unsupported
Claim). Promotion stays human-approved.

_Why it serves the approach:_ this is the approach made concrete — an objective accuracy benchmark
turns "self-improving" from a story into a number that moves.
