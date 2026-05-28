# Recursive improvement — price-rebuttal-v1

_Experiment `d8381c4187714246b13005bca25e1a79`. Dimension: price-objection rebuttal. Primary KPI: objection-recovery rate. Guardrails: frustration, unsupported claims._

**Decision: No variant beat the baseline — baseline held.**

## Results by variant

| Variant | Calls | Objection calls | Recovery | Frustration | Unsupported | Appropriate |
|---|---|---|---|---|---|---|
| Generic value statement (baseline) | 5 | 3 | 0% | 80% | 0% | 40% |
| Empathy-first value framing | 5 | 2 | 0% | 100% | 0% | 40% |
| Outcome-cost framing | 5 | 2 | 0% | 100% | 0% | 20% |
| Risk-reversal framing | 5 | 1 | 0% | 80% | 0% | 40% |
| Comparison-to-alternatives framing | 5 | 3 | 0% | 100% | 0% | 40% |
| Diagnostic reframing | 5 | 2 | 0% | 100% | 0% | 60% |

## Promotion rationale

- **Empathy-first value framing** — reject
  - objection-recovery 0% vs baseline 0% (no improvement)
  - frustration 100% vs baseline 80% (REGRESSED)
  - unsupported-claims 0% vs baseline 0% (ok)
- **Outcome-cost framing** — reject
  - objection-recovery 0% vs baseline 0% (no improvement)
  - frustration 100% vs baseline 80% (REGRESSED)
  - unsupported-claims 0% vs baseline 0% (ok)
- **Risk-reversal framing** — reject
  - objection-recovery 0% vs baseline 0% (no improvement)
  - frustration 80% vs baseline 80% (ok)
  - unsupported-claims 0% vs baseline 0% (ok)
- **Comparison-to-alternatives framing** — reject
  - objection-recovery 0% vs baseline 0% (no improvement)
  - frustration 100% vs baseline 80% (REGRESSED)
  - unsupported-claims 0% vs baseline 0% (ok)
- **Diagnostic reframing** — reject
  - objection-recovery 0% vs baseline 0% (no improvement)
  - frustration 100% vs baseline 80% (REGRESSED)
  - unsupported-claims 0% vs baseline 0% (ok)

## Limitations

- Metrics come from synthetic self-play scored by an LLM judge, not live calls — they
  indicate direction, not production ground truth.
- Recovery rate is measured only over calls where the prospect actually raised a price
  objection; small samples per persona mean a real rollout should widen the prospect set.
- The promotion rule treats unmeasured guardrails conservatively (as 0%); always confirm
  the judge ran before trusting a promotion.
