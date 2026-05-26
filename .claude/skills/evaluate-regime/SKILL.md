# SKILL: evaluate-regime

## PURPOSE
Classify the market regime and extract dominant signals.

---

## INPUT
Ticker payload with trend, momentum, extension, volatility.

---

## OUTPUT

- regime_label
- signal_summary
- confidence_level

---

## LOGIC

### Regime Classification
Use trend_state + realized_vol_state matrix.

---

### Signal Prioritization

Return only top 3 signals:

- Trend strength
- Momentum direction
- Volatility regime

---

### Confidence Rules

High:
- aligned + strong momentum

Medium:
- partial alignment

Low:
- conflicting signals

---

## CONSTRAINTS

- No trade recommendations
- No scoring
- Focus only on classification