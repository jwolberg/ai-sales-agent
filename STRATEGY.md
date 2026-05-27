---
name: Autonomous AI Sales Agent
last_updated: 2026-05-26
---

# Autonomous AI Sales Agent Strategy

## Target problem

Nerdy's sales depend on live phone agents whose hours are limited (leads arrive 24/7, agents don't), whose results vary by who picks up, and whose tactics improve slowly because every change means retraining people — which caps conversion.

## Our approach

Treat the sales agent as a measurable, self-improving system: every call is observed, versioned, and fed into a recursive experiment loop against honest synthetic prospects — so the agent compounds toward human-level selling instead of staying a static script.

## Who it's for

**Primary:** Nerdy sales operator/manager — they're hiring this product to run and continuously improve an autonomous sales force they can trust: see what it's doing, why, and prove it's getting measurably better.

**Secondary:** the prospect (parent/student) the agent talks to — the product still has to sell to them honestly, fast, and without pressure.

## Key metrics

- **Close Success Rate** — % of close attempts that get an accepted next step; the lagging outcome that "improved conversions" actually means.
- **Objection Recovery Rate** — % of objection calls where the prospect still advances; the recursive loop's primary KPI and the honest test against pushback.
- **Unsupported Claim Rate** — % of responses with ungrounded facts; guardrail that keeps a rising win rate from being bought with hallucinated promises.
- **Discovery Completion Rate** — % of calls collecting the required fields; leading signal that moves call-to-call.
- **Escalation Rate** — % of calls handed to a human; two-sided health metric (too high = can't carry calls, too low = bulldozing past moments it should hand off).

## Tracks

### The agent

Realtime voice (STT/TTS or STS) with barge-in and a consistent persona, lead memory across calls, dynamic discovery (skip-known / next-best-question), and KB-grounded answers with no hallucinated facts.

_Why it serves the approach:_ a self-improving system is worthless if the thing being improved can't hold a real, honest call — this is what the loop optimizes.

### Observability & decisioning

Full transcripts, per-turn decision traces (next question / pivot / escalate, with reason and confidence), version attribution, and KPI dashboards.

_Why it serves the approach:_ "every call observed and versioned" is the substrate; it's also exactly what the primary operator persona buys.

### Recursive improvement loop

Synthetic prospect simulator plus an experiment engine: variant generation, controlled tests against honest personas, and promote/retire decisions from a documented baseline.

_Why it serves the approach:_ this is the approach made concrete — without it you have a voice bot, not a system that compounds.
