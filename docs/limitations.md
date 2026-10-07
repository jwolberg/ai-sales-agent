# Limitations Memo

What this MVP did and did not validate, and what production deployment would require
(PRD §25). Read alongside `docs/recursive-improvement.md` (evidence) and
`docs/failure-modes.md` (failure catalog, pending live trials).

---

## Which lead types were tested

- **Synthetic, via self-play (tested):** all six personas in `data/personas/personas.yaml` —
  motivated parent, skeptical parent, price-sensitive parent, busy parent, competitive
  shopper, and poor-fit lead — covering hesitation, partial answers, price pushback,
  competitive comparison, and self-disqualification (PRD §12.2/§12.3).
- **Lead-info levels (tested in data, partially in flow):** the seed set
  (`data/leads/seed_leads.json`) covers full / partial / no prior-info leads (Use Cases 1–3).
  The skip-known and cross-call memory logic is unit-tested; end-to-end discovery-to-close
  runs through the engine in text mode.

## Which lead types were NOT tested

- **Real human prospects:** no live human trial calls have been run yet (P8-T1 is open).
- **Phone / WhatsApp audio conditions:** only browser WebRTC; no telephony codec/noise/jitter.
- **Non-English or accented speech at scale:** STT language/sample-rate was fixed for the demo
  but not stress-tested across accents or noisy environments.
- **Multi-call longitudinal journeys:** cross-call memory is implemented and unit-tested, but a
  real multi-session prospect arc was not exercised live.
- **Adversarial / abusive callers and prompt-injection attempts:** guardrails exist but were
  not red-teamed.

## Whether real humans tested the agent

- **No.** All evaluation evidence to date is synthetic LLM self-play scored by an LLM judge.
  The live voice path is construction- and unit-validated; a browser/mic/keys run (RUNBOOK
  §11) is still needed to confirm the live conversation and to measure latency vs. VC-3.

## Whether pricing was real, simulated, or restricted

- **Restricted / placeholder.** The agent does **not** state specific prices, discounts, or
  guarantees as fact. KB pricing content under `data/kb/` is a safe PLACEHOLDER, not approved
  business content. Discount and contract asks are routed to human escalation
  rather than negotiated (guardrail, not a feature gap). Approved pricing/refund/matching/
  scheduling copy is still owed — see `docs/QandA_opens.md`.

## What knowledge-base content was incomplete

- KB docs under `data/kb/` are placeholders for: **pricing, refunds, tutor matching,
  scheduling, and competitive comparison.** Until approved copy is supplied, the agent
  honestly defers those specifics to a human (KB-4). This is the primary reason the first
  improvement loop showed flat (0%) objection-recovery numbers — the agent has no real
  rebuttal substance to recover an objection with.

## How synthetic prospects may bias results

- **Shared-model blind spots:** both the agent and the synthetic prospects are Claude, so they
  may share assumptions a real human wouldn't, inflating apparent rapport.
- **Calibration:** synthetic personas may be systematically easier or harder than real
  prospects; the LLM judge may be miscalibrated and should be spot-checked against transcripts.
- **Small per-persona samples:** recovery is measured only over calls where a price objection
  actually arose, so the per-persona denominator is small — directional signal, not ground
  truth. A real rollout should widen the prospect set and add live human trials.
- **Text-mode omissions:** self-play runs in text, so it cannot surface voice-specific failure
  modes (latency, barge-in, ASR errors).

## What would be required for production deployment

- **Approved content:** real, legal/compliance-approved KB copy for pricing, refunds, matching,
  scheduling, and competitive answers (`docs/QandA_opens.md`).
- **Live validation:** human trial calls (P8-T1), latency measurement against VC-3, and tuning
  of escalation thresholds and barge-in against real audio.
- **Scale & storage:** swap SQLite → Postgres; durable transcript/recording storage with
  retention controls.
- **Retrieval quality:** likely upgrade the lexical TF-IDF retriever to an embedding vector
  store once the real (larger, paraphrase-heavy) KB lands.
- **Telephony:** Twilio/WhatsApp channels if phone delivery is required.
- **Monitoring & rollback:** live KPI dashboards, alerting on guardrail breaches, and a fast
  variant rollback path; promotion stays human-approved until auto-promotion is proven safe.
- **Latency tiers:** the deferred Tier-1 FAQ cache, Tier-2 speculative prefetch, and true
  pre-synthesized filler audio need live measurement to tune.

## What compliance, privacy, or sales-policy review is still needed

- **Sales-policy sign-off** on every rebuttal and the escalation thresholds before customer use.
- **Pricing/discount authority:** confirmation that the agent never quotes or negotiates price
  outside approved bounds (currently enforced by guardrails + escalation).
- **PII handling:** the data model labels synthetic vs. real and uses PII-substituted
  transcripts in dev (§13.3); a real deployment needs a full privacy review of stored
  transcripts/recordings, consent capture, and "you're speaking with an AI" disclosure.
- **Recording consent** and jurisdiction-specific call-recording law if audio is persisted.
- **Honesty guardrail:** the agent must always disclose it is an AI and honor human-handoff
  requests; this is implemented but should be policy-reviewed and live-verified.
