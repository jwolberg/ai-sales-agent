# Research Notes

Background and rationale behind the agent's design choices (PRD §24). These notes explain
*why* the playbooks, personas, KPIs, and grounding strategy are shaped the way they are.

> Scope note: this is a take-home MVP. The "references" below are the established sales and
> conversational-design principles the playbooks were modeled on, not a literature review.
> No proprietary company methodology was used; approved content is still pending
> (see `docs/QandA_opens.md`).

---

## 1. Sales methodology references used

The discovery and closing flows follow consultative / needs-based selling rather than
pitch-first selling:

- **Discovery before pitch (SPIN-style).** `data/playbooks/discovery.yaml` separates
  *required* fields (DF-1: student grade, subject, goal, timeline, etc.) from *leading*
  questions (DF-2) that surface pain and desired outcomes before any price or plan is
  discussed. The decider (`app/agent/decisioning.py`) only advances to a fit summary and
  close once enough is known.
- **Consultative close.** The close flow (`app/agent/closing.py`) produces a fit summary
  (CF-1) tied to what the prospect said, then recommends a single next step (CF-2) — a
  consultation or plan — rather than pushing for an immediate yes.
- **Earn the right to close.** A close is gated on close criteria (DE-3); an open high-risk
  objection holds the gate. This encodes "don't close over an unresolved concern."

## 2. Objection-handling principles

`data/playbooks/objections.yaml` encodes six objection types, with the price objection as the
baseline improvement target (§8). Principles applied:

- **Acknowledge → reframe → advance**, not deny. Each rebuttal validates the concern before
  reframing value, and ends by offering a concrete next step.
- **Never concede price or invent discounts.** Discount/contract asks are treated as
  high-risk and route to escalation (DE-4), not negotiation — this is a guardrail, not a
  rebuttal style.
- **Match rebuttal to objection type.** The five candidate price rebuttals (empathy-first,
  outcome-cost, risk-reversal, comparison, diagnostic) each carry an explicit
  when-to-use / when-to-avoid + escalation trigger + compliance note in
  `app/experiments/variants.py`, so a style isn't applied where it would backfire.
- **Diagnostic over scripted.** The diagnostic variant ("what outcome would make tutoring
  worth it?") embodies the consultative principle that the prospect should define value.

## 3. Competitive answer constraints

- Competitive questions are answered **only from approved KB content** via the grounded-answer
  flow (KB-1/3); when content is insufficient the agent says so and offers to follow up
  (KB-4) rather than improvising a comparison.
- Guardrails (`app/agent/guardrails.py`) flag any output that disparages a competitor or
  states an unapproved policy/price as fact, so competitive replies stay factual and bounded.
- **Current limitation:** the competitive KB doc is a placeholder, so the agent currently
  defers most competitor specifics to a human. Real approved copy is tracked in
  `docs/QandA_opens.md`.

## 4. Synthetic prospect design rationale

The six personas (`data/personas/personas.yaml`, PRD §12.2) are designed to be *honest and
hard*, not easy wins:

- Each persona has **ground-truth `facts`** keyed to the discovery field names, so scoring can
  check whether the agent actually extracted the right information (no credit for guessing).
- Behaviors (§12.3) require personas to hesitate, give partial answers, push back on price,
  and **disqualify themselves** when they're a poor fit — and to *resist* pushiness and reward
  consultative selling. This is what makes the simulator a real test of D-4's guardrails.
- `converts` / `disqualifies` flags drive the `appropriate_for_persona` score: a convertible
  persona should progress toward a close; a poor-fit persona should *not* be force-closed.
  This directly penalizes the "obedient AI closing easy customers" failure the PRD warns about.

## 5. Prompt / playbook iteration notes

- **Persona built once** for consistency (VC-4) rather than re-derived per turn.
- **Render is the single place words are produced** (`app/agent/render.py`): deterministic for
  fixed SPEAK lines, LLM-synthesized (or KB-4 fallback) for grounded answers. This made the
  output cacheable for latency tiers and gave one chokepoint for the §18 output guardrail
  (`check_agent_output`).
- **Extraction upgraded rule-based → LLM.** The first extractor was deterministic slot-filling;
  the `LLMExtractor` (Claude structured output) additionally captures fields the caller
  volunteers in one turn, so the agent doesn't re-ask (LM-2/LM-3).
- **Variant deltas applied at runtime**, keyed by variant, via `Orchestrator.objection_overrides`
  — experiments change the rebuttal without forking the agent.

## 6. KPI selection rationale

- **Primary KPI = objection recovery rate** because it is the most direct measure of the chosen
  improvement dimension and is conversion-linked (see `docs/decision-log.md` D-4).
- **Guardrail KPIs = frustration + unsupported-claim rate.** These exist so the promotion rule
  can't reward a rebuttal that wins by being pushy or by inventing policy — a variant must
  improve recovery *without* regressing either (§8 promotion rule).
- **Deterministic vs. judged split.** Structural facts (escalated? close attempted? objection
  raised+recovered? appropriate-for-persona?) are read straight off the recorded call;
  qualitative signals (frustration, unsupported claim, 1–5 consultative quality) come from an
  LLM-as-judge with an explicitly *strict, non-flattering* system prompt
  (`app/simulator/scoring.py`). The judge client is injectable so tests run without an API.
- **Latency and live frustration KPIs are not yet captured** (per-turn timing / live sentiment);
  documented as a gap.

## 7. Known limitations of synthetic evaluation

- Synthetic prospects are Claude role-playing personas; they may be **systematically easier or
  harder** than real humans and can share blind spots with the agent (both are Claude).
- Recovery is measured only over calls where a price objection actually arose, so per-persona
  samples are small — directional signal, not production ground truth.
- The LLM judge can be miscalibrated; its scores should be spot-checked against transcripts.
- The first real run (`docs/recursive-improvement.md`) showed 0% recovery across all variants —
  a real result driven by placeholder rebuttal/KB content and a 12-turn cap, not a measurement
  bug (verified: KPI events fire but objections never co-occur with a close in self-play).
- Full caveats are in `docs/limitations.md`.
