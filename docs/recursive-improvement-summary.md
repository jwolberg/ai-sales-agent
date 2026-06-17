---
title: Recursive Improvement — Summary
last_updated: 2026-05-30
detail_docs:
  - docs/recursive-improvement.md          # loop #1, price-objection rebuttal
  - docs/recursive-improvement-router.md   # loop #2, router classification accuracy
---

# Recursive Improvement — Summary

This is the overview of the recursive-improvement requirement: at least one meaningful loop that
moves a sales KPI from a documented baseline through **variant generation → controlled experiment →
a promote/retire decision**. We ran the loop on two dimensions. Both produced honest **negative**
results — no variant beat the baseline — and in both cases the loop did its job: it *retired* a
plausible change instead of shipping a flattering one.

## The loop (how it works)

Same shape both times; the second is the current, live-aligned implementation.

1. **Synthetic data via self-play.** Personas with a *known* ground truth drive the **real agent
   brain** in text mode — the same engine + brain a live call uses, so the benchmark measures the
   production path, not a toy. The router loop adds an **LLM-driven prospect**
   (`backend/app/simulator/llm_prospect.py`) that hesitates, withholds, and only names its exact
   need when asked — built to expose weakness, not flatter the agent.
2. **Variant generation.** A variant is the brain's system prompt plus a `prompt_delta` override
   (`OpenAIBrain.prompt_delta`). One dimension changes per experiment.
3. **Controlled experiment + scoring.** `run_benchmark` scores the primary KPI against ground truth
   plus guardrails (`backend/app/simulator/benchmark.py`).
4. **Promote/retire decision.** `decide_promotion` promotes **iff** the primary KPI strictly
   improves **and no guardrail regresses** (`backend/app/simulator/improvement.py`). It emits a
   report and a decision; it never flips anything live — **promotion stays human-approved.**

## Loop #1 — price-objection rebuttal

_Detail: `docs/recursive-improvement.md`. Dimension: rebuttal phrasing. KPI: objection-recovery
rate. Guardrails: frustration, unsupported claims. Discovery-to-close build (since narrowed in the
intent-router pivot)._

- Baseline ("generic value statement") vs. 5 generated framings (empathy-first, outcome-cost,
  risk-reversal, comparison, diagnostic), 5 personas each, Claude self-play scored by an LLM judge.
- **Decision: baseline held — all 5 rejected.** Recovery floored at 0% across every arm; several
  framings *regressed* frustration. The honest read: the agent rarely reaches a close in self-play,
  so this KPI had no signal to move — a finding about the agent, surfaced by the loop.

## Loop #2 — router classification accuracy (current)

_Detail: `docs/recursive-improvement-router.md`. Dimension: a disambiguation sequencing rule. KPI:
Classification Accuracy vs. synthetic ground truth. Guardrails: mis-quote rate, price-correctness.
Run it: `python -m app.experiments_router --agent-model gpt-4o-mini --reps 5`._

The variant under test: *"never settle on a leaf or quote until the caller names an exact test or
subject; if vague, ask one clarifying question."*

| Config | Baseline accuracy | Variant accuracy | Decision |
|---|---|---|---|
| `gpt-4o`, 1 rep | 1.00 | 1.00 | hold — no headroom (already saturated) |
| `gpt-4o-mini`, 3 reps | 0.93 | **1.00** | *looked* like a win |
| `gpt-4o-mini`, 5 reps (50 calls) | 0.96 | **0.88** | **reject** — regressed; mis-quote + price guardrails tripped |

**Decision: baseline held — variant retired.** Under the 8-turn budget the disambiguation rule
*over-asks*, runs out of turns, and escalates instead of quoting (escalation 0.02 → 0.12).

## The key lesson (why this is the point, not a failure)

The reps=3 sample showed the variant winning **1.0**. At reps=5 it **reversed** to a regression. A
naive operator would have promoted the reps=3 result and shipped a worse agent. The loop's value is
exactly this: **a guardrail-gated, adequately-sampled decision that retires plausible-but-wrong
changes** — the classic trap ("reports a rising win rate, but fails when trialed").

Corollary: on this 8-leaf task both models are at/near ceiling, so **measurement noise exceeds the
available headroom**. The correct loop output is "baseline holds," not a manufactured promotion.

## Limitations & next steps

- Metrics are LLM-judged self-play, not live human calls — direction, not production ground truth.
- Accuracy is near ceiling; to find real movement, target a non-saturated KPI (Turns-to-Class.,
  Over-Ask Rate) or harder/edge-case personas (off-taxonomy asks, multi-subject callers, mid-call
  switches), and raise reps further to shrink the noise band below the headroom.
- The promotion gate is conservative by design: strict KPI gain, no guardrail regression, human in
  the loop before anything goes live.
