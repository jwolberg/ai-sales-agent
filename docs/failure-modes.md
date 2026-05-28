# Failure Mode Report

The §19 failure modes, each with description, example, severity, root-cause hypothesis,
mitigation, and remaining limitation.

> **Status: draft from synthetic evidence.** Modes marked **OBSERVED** are evidenced by real
> transcripts from the 2026-05-28 synthetic self-play run (`docs/recursive-improvement.md`).
> Modes marked **PENDING LIVE** require live human voice trials (P8-T1) and/or latency
> measurement that have not been run yet — excerpts are deliberately omitted rather than
> fabricated. Severity is the expected production impact.

---

## 1. Latency problems — PENDING LIVE

- **Description:** First response > 2s, barge-in stop > 1s, or KB answer > 4s (VC-3).
- **Example:** Pending live measurement (synthetic self-play is text-mode, no real timing).
- **Severity:** High (latency is the most common "feels robotic" complaint).
- **Root cause hypothesis:** Composed STT→Claude→TTS pipeline adds hops; LLM synthesis on the
  hot path.
- **Mitigation:** Filler-masking + ambient comfort-noise bed are in place; render is a single
  cacheable step. Tier-1 FAQ cache and Tier-2 speculative prefetch are designed but deferred.
- **Remaining limitation:** Unmeasured against VC-3 until a browser/mic/keys run.

## 2. Barge-in failures — PENDING LIVE

- **Description:** Agent fails to stop within 1s when the caller interrupts (VC-2).
- **Example:** Pending live trial.
- **Severity:** High (talking over a prospect is a hard UX failure).
- **Root cause hypothesis:** VAD sensitivity / output-flush timing under real audio.
- **Mitigation:** `allow_interruptions=True` set; ambient bed is output-only so it doesn't
  affect VAD.
- **Remaining limitation:** Barge-in is unvalidated live (P2-T2 deferred to live-validation).

## 3. Hallucinated policy answers — LOW (not observed)

- **Description:** Agent states an unapproved price/policy/guarantee as fact.
- **Example:** Not observed — the agent instead *over-defers* (see mode 13).
- **Severity:** High if it occurred; currently low likelihood.
- **Root cause hypothesis:** N/A — grounding + guardrails prevent it by design.
- **Mitigation:** KB-grounded answers only above a min score, else honest fallback (KB-4);
  `check_agent_output` flags claims-human / unapproved price / guarantee.
- **Remaining limitation:** Only tested against the placeholder KB; needs re-test with real
  approved content.

## 4. Overly rigid script behavior — OBSERVED

- **Description:** Agent repeats the same canned line instead of adapting.
- **Example** (`sim:competitive_shopper`):
  > prospect: …I'd expect you to know at least the basics of what your company offers…
  > agent: I want to make sure I give you accurate information on that, and I don't have it in
  > front of me right now. I can connect you with a specialist…
  > prospect: I mean, that's the same answer you just gave me.
  (The identical fallback fired three times in one call.)
- **Severity:** High (drove prospect frustration → abandonment).
- **Root cause hypothesis:** Placeholder KB returns nothing for these queries, so the
  knowledge fallback fires verbatim each time with no "I already said this" awareness.
- **Mitigation:** Render LLM-smooths questions; fallback should vary phrasing and, after one
  miss, pivot or escalate rather than repeat.
- **Remaining limitation:** No repetition-guard yet; most acute while the KB is placeholder.

## 5. Premature close attempts — LOW (not observed)

- **Description:** Agent pushes for a close before discovery/criteria are met.
- **Example:** Not observed — if anything the agent under-closes (mode 6).
- **Severity:** Medium.
- **Root cause hypothesis:** N/A — close is gated on close criteria (DE-3) and held by open
  high-risk objections.
- **Mitigation:** `assess_close_criteria` gate; `appropriate_for_persona` penalizes
  force-closing poor-fit personas.
- **Remaining limitation:** Gate thresholds untuned against live humans.

## 6. Failure to close when buying intent is present — OBSERVED

- **Description:** Prospect signals readiness but the agent doesn't attempt a close.
- **Example** (`sim:price_sensitive_parent`):
  > prospect: okay, that makes sense — what would next steps look like?
  > agent: I want to make sure I give you accurate information on that… I can connect you with
  > a specialist…
  (A clear buying signal — "what would next steps look like?" — met with a deflection instead
  of a close attempt.)
- **Severity:** High (directly lost conversions; this is the core 0%-recovery story).
- **Root cause hypothesis:** Next-step/pricing content is placeholder, so the agent defers the
  exact moment it should advance; the router doesn't treat "what are next steps?" as a
  close trigger.
- **Mitigation:** Supply approved next-step/plan copy; add a buying-intent → close route.
- **Remaining limitation:** Until then, recovery stays near 0% even when intent is present.

## 7. Failure to escalate when required — MEDIUM (partially tested)

- **Description:** Agent fails to hand off on a human request or high-risk ask.
- **Example:** Escalation fired in 9 of the run's calls; no missed-escalation case isolated yet.
- **Severity:** High if it occurs.
- **Root cause hypothesis:** Rule-based triggers may miss paraphrased human requests.
- **Mitigation:** DE-4 triggers + low-confidence fallback; discount/contract asks force escalate.
- **Remaining limitation:** Recall of escalation triggers unvalidated against live phrasing.

## 8. Weak objection handling — OBSERVED

- **Description:** Agent acknowledges an objection but fails to recover it.
- **Example:** Across the run, **0% objection-recovery** for every variant — objections were
  raised in 50 calls; none co-occurred with a close/discovery.
- **Severity:** High (this is the very dimension the improvement loop targets).
- **Root cause hypothesis:** Rebuttals are placeholders with no real value substance; the agent
  validates the concern but has nothing concrete to advance with, and the 12-turn cap ends the
  call first.
- **Mitigation:** Real approved rebuttal/KB copy; larger turn budget; then re-fire the loop.
- **Remaining limitation:** Numbers will stay flat until approved content lands.

## 9. Synthetic prospect bias — OBSERVED (methodological)

- **Description:** Synthetic personas may be systematically easier/harder than humans and share
  blind spots with the agent (both are Claude).
- **Example:** All evidence to date is Claude-vs-Claude self-play.
- **Severity:** Medium (affects how much the numbers can be trusted).
- **Root cause hypothesis:** Shared model; small per-persona samples.
- **Mitigation:** Strict non-flattering judge; ground-truth persona facts; six diverse personas.
- **Remaining limitation:** No human baseline yet; see `docs/limitations.md`.

## 10. Poor performance against skeptical humans — PENDING LIVE

- **Description:** Real skeptical callers expose brittleness the synthetic skeptic doesn't.
- **Example:** Synthetic `skeptical_parent` is tested; no live human equivalent yet.
- **Severity:** High.
- **Root cause hypothesis:** Synthetic skepticism is milder/more predictable than real humans.
- **Mitigation:** P8-T1 human trials with adversarial callers.
- **Remaining limitation:** Untested live.

## 11. Incorrect memory carryover / extraction — OBSERVED

- **Description:** Agent stores the wrong value for a field.
- **Example** (`sim:price_sensitive_parent`, final turn):
  > agent: So this is for honestly the main thing is it sounds expensive — is that right?
  (The objection text was mis-captured as the answer to "who is the tutoring for?")
- **Severity:** Medium-High (confirming garbage erodes trust).
- **Root cause hypothesis:** Extractor slotted a non-answer into the pending question instead of
  flagging it as a non-answer to clarify.
- **Mitigation:** Tighten non-answer detection in extraction; confirm low-confidence captures
  before storing.
- **Remaining limitation:** Confidence gating on extraction not fully tuned.

## 12. Repeated questions — OBSERVED

- **Description:** Agent re-asks something already answered, or repeats a line.
- **Example:** Both above excerpts (the thrice-repeated fallback in mode 4; the re-confirm of a
  mis-extracted field in mode 11).
- **Severity:** Medium-High.
- **Root cause hypothesis:** No turn-level "already said / already asked" memory; mis-extraction
  causes re-confirmation.
- **Mitigation:** Repetition guard on rendered output; skip-known relies on correct extraction.
- **Remaining limitation:** Coupled to the extraction fix (mode 11).

## 13. Competitive question mishandling — OBSERVED

- **Description:** Agent can't give a useful competitive answer.
- **Example** (`sim:competitive_shopper`): repeated specialist-deferral when asked what sets the
  company apart; it eventually gives one generic differentiator, then defers again.
- **Severity:** Medium-High (competitive shoppers churn fast).
- **Root cause hypothesis:** The competitive KB doc is a placeholder.
- **Mitigation:** Supply approved competitive copy (`docs/QandA_opens.md`).
- **Remaining limitation:** Until then the agent honestly defers, which frustrates shoppers.

## 14. Price concession errors — LOW (not observed)

- **Description:** Agent offers an unauthorized discount or negotiates price.
- **Example:** Not observed — discount/contract asks route to escalation, not negotiation.
- **Severity:** High if it occurred.
- **Root cause hypothesis:** N/A — guardrail by design.
- **Mitigation:** High-risk objection → escalate; `check_agent_output` flags unapproved price.
- **Remaining limitation:** Needs live confirmation that paraphrased discount asks are caught.

---

## Cross-cutting takeaway

The dominant root cause behind modes 4, 6, 8, and 13 is the **placeholder KB / rebuttal
content** plus the **short turn budget** — not broken logic. The engine routes, extracts,
gates, and escalates correctly; it has nothing substantive to *say* at the moments that
convert. Supplying approved content (`docs/QandA_opens.md`) and re-firing the loop is the
highest-leverage next step. Modes 1, 2, and 10 require live human trials to evidence.
