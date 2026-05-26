# SKILL: score-opportunity

## PURPOSE
Assign a 0–10 opportunity score to each ticker.

---

## INPUT

- trend_score
- momentum_state
- trend_alignment_state
- extension_state
- realized_vol_state

---

## CALCULATION

direction_score  = abs(trend_score)
momentum_bonus   = 1 if improving/strong
alignment_bonus  = 1.5 if aligned
vol_penalty      = -1 if sideways + elevated vol
mean_rev_bonus   = 1 if extension + conflicting

raw = sum
score = clamp(raw, 0–10)

---

## OUTPUT

- opportunity_score
- tier:
  - 8–10: High
  - 5–7: Medium
  - 3–4: Low
  - 0–2: Pass

---

## ADJUSTMENTS

- conflicting signals → -1
- high volatility → reduce conviction

---

## CONSTRAINTS

- No trade logic
- Pure scoring only