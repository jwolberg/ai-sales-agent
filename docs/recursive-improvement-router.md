# Recursive improvement — router classification accuracy

_Dimension: disambiguation sequencing rule (`disambiguation-rule-v1`). Primary KPI: Classification Accuracy vs. synthetic ground truth. Guardrails: mis-quote, price-correct. Agent brain: `gpt-4o-mini`; adversarial self-play prospect: `gpt-4o`. 10 router personas x 5 reps = 50 self-play calls/variant._

**Decision: no variant beat the baseline — baseline held.**

## Results

| Variant | Accuracy | Median turns | Quote | Mis-quote | Escalation |
|---|---|---|---|---|---|
| baseline (no delta) | 0.96 | 1.0 | 1.0 | 0.0 | 0.02 |
| disambiguation-rule-v1 | 0.88 | 1.0 | 0.94 | 0.02 | 0.12 |

## Promotion rationale

- **disambiguation-rule-v1** — reject: no accuracy gain (0.96 -> 0.88); mis-quote rate regressed; price-correctness regressed

## The variant

Appended to the brain's system prompt (`OpenAIBrain.prompt_delta`):

> DISAMBIGUATION RULE (follow strictly): The caller's need is only specific enough to act on once they have named an exact test (SAT, ACT, or PSAT) or an exact subject (algebra, geometry, chemistry, biology, or physics). Until then — including vague openers like 'college entrance exams', 'struggling in school', or 'science help' — ask exactly ONE short clarifying question that narrows toward the specific test or subject, and do NOT call quote_price or settle on a leaf yet. Never map a broad phrase to a specific test or subject on the caller's behalf; make the caller confirm the specific one.

## Limitations

- Metrics come from LLM-driven self-play scored against each persona's ground-truth leaf, not live human calls — they indicate direction, not production ground truth.
- Self-play is stochastic; a single run is a small sample (one call per persona). Re-run and widen the persona set before trusting a borderline promotion.
- The promotion rule is accuracy-gated and conservative: it promotes only on a strict accuracy gain with no mis-quote / price-correctness regression, and never flips anything live — a human approves the promotion.
