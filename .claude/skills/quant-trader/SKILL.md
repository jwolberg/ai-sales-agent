---
name: trade-setup-interpreter
description: >
  Design and implement a deterministic backend interpretation layer that converts a
  TickerSnapshot's market-state fields (trend, momentum, extension, vol, alignment, S/R)
  into a compact, agent-friendly TradeSetup object stored as a JsonProperty on the same
  snapshot. The interpreter also projects query-critical scalars (opportunity_score,
  regime_label, opportunity_tier, recommended_direction, recommended_trade_type) into
  indexed ndb properties for fast ranking across a 1,000-ticker universe. Use this skill
  whenever the user wants to: build or refine the interpretation logic that sits between
  raw quant signals and actionable trade objects; generate deterministic Python code that
  classifies regime, scores opportunity, selects trade type, and emits a TradeSetup;
  create or modify the TradeSetup schema; unit-test the interpretation layer against known
  payload fixtures; integrate the interpreter into a Cloud Function / FastAPI / Express
  pipeline; or wire the interpreter into the TickerSnapshot write path. Also trigger when
  the user mentions "trade setup object", "interpretation layer", "payload interpreter",
  "setup emitter", "regime classifier function", "trade_setup JsonProperty", or asks to
  make the quant-trade-analysis logic deterministic and code-level rather than prompt-level.
---

# Trade Setup Interpreter Skill

## Purpose

The quant-trade-analysis skill defines a *prompt-level* framework: Claude reads a
`market_state_payload` and produces a Markdown analysis. That works well for
human-in-the-loop review, but breaks down when the consumer is another piece of
software — a dashboard tile, an alert pipeline, a trade-sizing module, or an LLM
agent that needs structured context to reason further.

This skill closes that gap. It specifies a **deterministic interpretation layer** —
pure functions, no LLM in the loop — that reads market-state fields directly from
a `TickerSnapshot` entity and writes back a typed `TradeSetup` JSON blob plus a
small set of indexed scalar projections. The interpreter is the single source of
truth for regime classification, opportunity scoring, trade-type selection, and
risk parameterization. Downstream consumers never touch raw scores directly.

---

## Architecture Overview

```
TickerSnapshot (ndb entity, per ticker per day)
  ├── market-state fields   (trend_*, momentum_*, extension_*, realized_vol_*, etc.)
  ├── options/vol fields    (iv_rank, GEX, PCR_*, skew, etc.)
  ├── DailyGexFull          (linked via snapshot_key — gamma by strike)
  └── DailySkewFull         (linked via snapshot_key — advanced skew surface)
        │
        ▼
┌──────────────────────────┐
│   Interpretation Layer   │  ← THIS SKILL
│                          │
│  1. Extract + validate   │
│  2. Classify regime      │
│  3. Score opportunity    │
│  4. Select trade type    │
│  5. Derive risk params   │
│  6. Attach caution flags │
│  7. Emit TradeSetup      │
└──────────────────────────┘
        │
        ▼
  TickerSnapshot (write-back)
  ├── trade_setup           ← JsonProperty  (full TradeSetup blob)
  ├── opportunity_score     ← FloatProperty (indexed, for ranking)
  ├── opportunity_tier      ← StringProperty(indexed, for filtering)
  ├── regime_label          ← StringProperty(indexed, for filtering)
  ├── recommended_direction ← StringProperty(indexed, for filtering)
  ├── recommended_trade_type← StringProperty(indexed, for filtering)
  ├── trade_bias            ← StringProperty(indexed, for filtering)
  └── trade_recommender_version ← StringProperty (interpreter version)
        │
   ┌────┼──────────┬───────────────┐
   ▼    ▼          ▼               ▼
 Agent  Dashboard  Alert Engine   Ranking API
 prompt  renderer  (webhooks)     (1000 tickers)
```

The interpreter is a **pure function**: same input → same output, no side effects,
no network calls, no LLM inference. This makes it testable, auditable, and fast
enough to run inline during the snapshot write path for 1,000 tickers.

---

## TickerSnapshot Storage Strategy

The `TickerSnapshot` model serves two roles: it stores the raw signals *and*
the interpreted result. The storage design follows a **dual-write pattern** —
indexed scalars for queries, plus a single JSON blob for full detail.

### What stays as indexed ndb properties (for ranking/filtering)

These fields are the ones you'll query across 1,000 tickers — "show me all
tickers with opportunity_score >= 7 sorted descending" or "filter by
regime_label == trending_low_vol". They must remain as top-level indexed
properties:

```python
# ── Queryable projections (indexed) ──
regime_label = ndb.StringProperty(indexed=True)
trade_bias = ndb.StringProperty(indexed=True)
opportunity_score = ndb.FloatProperty(indexed=True)
opportunity_tier = ndb.StringProperty(indexed=True)
recommended_trade_type = ndb.StringProperty(indexed=True)
recommended_direction = ndb.StringProperty(indexed=True)
trade_recommender_version = ndb.StringProperty()
```

### What moves into the `trade_setup` JSON blob

Everything consumed *after* you've already selected a ticker — structures,
entry/stop/target descriptions, risk params, caution flags, signal snapshot,
agent summary. Nobody runs datastore queries against these. Storing them as
flat scalars creates migration friction and schema bloat with no query benefit:

```python
# ── Full interpreted result (not queryable, not needed for ranking) ──
trade_setup = ndb.JsonProperty()
# Contains the complete TradeSetup dict — see schema below
```

### Fields to remove from TickerSnapshot (now redundant)

These flat scalars are fully contained inside `trade_setup` and are never
used in datastore queries. Drop them to avoid dual-maintenance:

```python
# REMOVE — now inside trade_setup JsonProperty:
# recommended_structure
# recommended_entry_trigger
# recommended_stop
# recommended_target
# recommended_size_unit_fraction
# recommended_size_notes
# caution_flags  (the flat string version)
```

### Why not `candidate_trades` (plural)?

The interpreter emits **one setup per ticker per snapshot**. This is intentional.
A ranking system needs a single score per row. If the rule cascade falls through
to "pass," that *is* the recommendation — storing hypothetical alternatives
("what you'd do if momentum improved") adds complexity without helping the
ranking query and muddies the signal for agents.

If you later want multi-timeframe setups (intraday vs. swing), run separate
interpreter calls with different payload configurations rather than stuffing
multiple objects into one snapshot row.

---

## TradeSetup Output Schema

This is the canonical schema for the `trade_setup` JsonProperty. Implement it
as a Python dataclass or TypedDict for the backend; the same shape can be
expressed as a TypeScript interface for frontend consumers.

```python
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

class RegimeLabel(str, Enum):
    TRENDING_LOW_VOL = "trending_low_vol"
    TRENDING_HIGH_VOL = "trending_high_vol"
    RANGE_BOUND = "range_bound"
    CHOPPY_VOLATILE = "choppy_volatile"
    TRENDING_DOWN_LOW_VOL = "trending_down_low_vol"
    TRENDING_DOWN_HIGH_VOL = "trending_down_high_vol"
    FLUSH_PANIC = "flush_panic"

class TradeType(str, Enum):
    DIRECTIONAL = "directional"
    MEAN_REVERSION = "mean_reversion"
    VOL_PREMIUM = "vol_premium"
    PASS = "pass"

class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"

class OpportunityTier(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    PASS = "pass"

@dataclass
class SignalSnapshot:
    trend_score: Optional[float] = None
    trend_state: Optional[str] = None
    momentum_score: Optional[float] = None
    momentum_state: Optional[str] = None
    extension_score: Optional[float] = None
    extension_state: Optional[str] = None
    realized_vol_20d: Optional[float] = None
    realized_vol_state: Optional[str] = None
    trend_alignment_score: Optional[float] = None
    trend_alignment_state: Optional[str] = None
    # S/R context carried through for agent use
    distance_to_support_pct: Optional[float] = None
    distance_to_resistance_pct: Optional[float] = None
    key_level_context: Optional[str] = None

@dataclass
class TradeSetup:
    # ── Identity ──
    ticker: str
    timestamp: str                         # ISO-8601, time of interpretation
    interpreter_version: str               # e.g. "1.0.0"

    # ── Regime ──
    regime: str                            # RegimeLabel value
    regime_confidence: float               # 0–1

    # ── Opportunity ──
    opportunity_score: float               # 0–10
    opportunity_tier: str                  # OpportunityTier value

    # ── Trade Recommendation ──
    trade_type: str                        # TradeType value
    trade_bias: str                        # human-readable bias label
    direction: str                         # Direction value
    structures: list[str] = field(default_factory=list)
    entry_trigger: str = ""
    stop_description: str = ""
    target_description: str = ""

    # ── Risk Parameters ──
    size_fraction: float = 0.5             # 0.25 | 0.5 | 0.75 | 1.0
    max_risk_pct: float = 1.5
    prefer_defined_risk: bool = True

    # ── Caution & Metadata ──
    caution_flags: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    signal_snapshot: Optional[SignalSnapshot] = None

    # ── Agent Hint ──
    agent_summary: str = ""                # ≤ 120 chars

    def to_dict(self) -> dict:
        """Serialize for ndb.JsonProperty storage."""
        return asdict(self)
```

The `signal_snapshot` preserves raw scores so downstream agents can reference
values without needing the full TickerSnapshot entity. The `agent_summary` is a
pre-formatted one-liner like `"AAPL: trending_low_vol | 7.5/10 | long
directional | full size"` designed for injection into an LLM system prompt.

The `interpreter_version` field inside the blob matches
`trade_recommender_version` on the TickerSnapshot. This makes the blob
self-describing even when read in isolation — you can always tell which rule
set generated a given setup, which matters when comparing historical results
across interpreter upgrades.

---

## Interpretation Logic — Step by Step

Each step below is a pure function. Compose them in sequence to produce the
final `TradeSetup`.

### Step 1: Extract & Validate from TickerSnapshot

The interpreter reads directly from a `TickerSnapshot` entity (or a dict with
the same field names). Guard every field. If a field is `None` or outside its
valid range, replace it with a conservative default and push the field name
into `missing_fields`.

```python
FIELD_DEFAULTS = {
    "trend_score":            0.0,
    "trend_state":            "sideways",
    "momentum_score":         0.0,
    "momentum_state":         "fading",
    "extension_score":        0.0,
    "extension_state":        "neutral",
    "realized_vol_20d":       None,       # carry as None, skip vol-sizing
    "realized_vol_state":     "elevated", # conservative
    "realized_vol_score":     0.0,
    "trend_alignment_score":  0.0,
    "trend_alignment_state":  "conflicting",  # conservative
    "distance_to_support_pct":    None,
    "distance_to_resistance_pct": None,
    "key_level_context":          None,
}

SCORE_CLAMPS = {
    "trend_score":           (-5.0, 5.0),
    "momentum_score":        (-5.0, 5.0),
    "extension_score":       (-5.0, 5.0),
    "realized_vol_score":    (-5.0, 5.0),
    "trend_alignment_score": (-1.0, 1.0),
}
```

Implementation: iterate `FIELD_DEFAULTS`, read each from the snapshot, apply
clamp if in `SCORE_CLAMPS`, fall back to default if missing, and accumulate
`missing_fields`. Return a `ValidatedPayload` dataclass (or plain dict).

### Step 2: Classify Regime

Use the following lookup. Match `trend_state` first, then `realized_vol_state`.

```python
REGIME_MAP = {
    ("up",       "subdued"):      "trending_low_vol",
    ("up",       "contracting"):  "trending_low_vol",
    ("up",       "expanding"):    "trending_high_vol",
    ("up",       "elevated"):     "trending_high_vol",
    ("sideways", "subdued"):      "range_bound",
    ("sideways", "contracting"):  "range_bound",
    ("sideways", "expanding"):    "choppy_volatile",
    ("sideways", "elevated"):     "choppy_volatile",
    ("down",     "subdued"):      "trending_down_low_vol",
    ("down",     "contracting"):  "trending_down_low_vol",
    ("down",     "expanding"):    "flush_panic",
    ("down",     "elevated"):     "flush_panic",
}
# Fallback if trend_state or vol_state is unexpected: "choppy_volatile"
```

Derive `regime_confidence`:

```python
def classify_regime(p):
    regime = REGIME_MAP.get(
        (p.trend_state, p.realized_vol_state), "choppy_volatile"
    )

    base = abs(p.trend_alignment_score)                     # 0–1
    strength_bonus = min(abs(p.trend_score) / 5.0, 1.0) * 0.3
    confidence = clamp(base * 0.7 + strength_bonus, 0.0, 1.0)

    if p.trend_alignment_state == "conflicting":
        confidence = min(confidence, 0.4)

    return regime, round(confidence, 2)
```

Derive `trade_bias` from the regime (human-readable label for the indexed field):

```python
TRADE_BIAS_MAP = {
    "trending_low_vol":      "Long breakouts, buy dips to MA",
    "trending_high_vol":     "Smaller size; wait for vol flush",
    "range_bound":           "Fade extensions, sell premium",
    "choppy_volatile":       "Reduce size or pass",
    "trending_down_low_vol": "Short rallies, bear spreads",
    "trending_down_high_vol":"Short with caution, defined risk only",
    "flush_panic":           "Potential reversal, high caution",
}
```

### Step 3: Score Opportunity

Deterministic composite — mirrors the quant-trade-analysis formula:

```python
def score_opportunity(p) -> tuple[float, str]:
    direction   = abs(p.trend_score)                                    # 0–5
    mom_bonus   = 1.0 if p.momentum_state in ("strong", "improving") else 0.0
    align_bonus = 1.5 if p.trend_alignment_state == "aligned" else 0.0
    vol_penalty = -1.0 if (
        p.realized_vol_state in ("expanding", "elevated")
        and p.trend_state == "sideways"
    ) else 0.0
    mr_bonus    = 1.0 if (
        p.extension_state in ("extended", "oversold")
        and p.trend_alignment_state == "conflicting"
    ) else 0.0

    raw = direction + mom_bonus + align_bonus + vol_penalty + mr_bonus
    score = round(clamp(raw, 0.0, 10.0), 2)

    if score >= 8.0:    tier = "high"
    elif score >= 5.0:  tier = "moderate"
    elif score >= 3.0:  tier = "low"
    else:               tier = "pass"

    return score, tier
```

### Step 4: Select Trade Type & Direction

Apply the first matching rule top-to-bottom:

**Rule 1 — Directional Momentum**
```
IF trend_state != "sideways"
   AND momentum_state in ("strong", "improving")
   AND trend_alignment_state == "aligned"
THEN
   trade_type = "directional"
   direction  = "long" if trend_state == "up" else "short"
   structures = ["long_equity", "long_calls"] if long
                else ["short_equity", "long_puts", "bear_call_spread"]
   entry_trigger    = "pullback to MA20 with extension_score < 1.5"
   stop_description = "below nearest support level from S/R context"
   target_description = "next resistance level or 2:1 reward-to-risk"
```

**Rule 2 — Mean Reversion**
```
IF extension_state in ("extended", "oversold")
   AND trend_alignment_state == "conflicting"
   AND realized_vol_state != "expanding"
THEN
   trade_type = "mean_reversion"
   direction  = "short" if extension_state == "extended" else "long"
   structures = ["bear_call_spread"] if short else ["bull_put_spread"]
   entry_trigger    = "momentum_score crossing toward 0"
   stop_description = "new extension extreme beyond current level"
   target_description = "MA20 reversion (extension_score ≈ 0)"
```

**Rule 3 — Volatility / Premium Selling**
```
IF trend_state == "sideways"
   AND extension_state == "neutral"
THEN
   trade_type = "vol_premium"
   direction  = "neutral"
   IF realized_vol_state in ("elevated", "expanding"):
       structures = ["short_strangle", "iron_condor"]
   ELSE:
       structures = ["calendar_spread", "diagonal_spread"]
   entry_trigger    = "range-bound confirmation over 3+ sessions"
   stop_description = "delta breach of short strikes"
   target_description = "theta decay to 50% of max profit"
```

**Rule 4 — Pass (fallthrough)**
```
ELSE
   trade_type = "pass"
   direction  = "neutral"
   structures = []
   entry_trigger    = "re-evaluate next session"
   stop_description = "N/A"
   target_description = "N/A"
```

### Step 5: Derive Risk Parameters

```python
def derive_risk(p, trade_type: str) -> dict:
    rv = p.realized_vol_20d
    if rv is None:
        size_fraction = 0.5
    elif rv < 0.20:
        size_fraction = 1.0
    elif rv < 0.40:
        size_fraction = 0.75
    elif rv < 0.60:
        size_fraction = 0.5
    else:
        size_fraction = 0.25

    max_risk_pct = 1.0 if (rv and rv > 0.40) else 1.5

    prefer_defined = (
        p.realized_vol_state in ("expanding", "elevated")
        or trade_type == "pass"
    )

    return {
        "size_fraction": size_fraction,
        "max_risk_pct": max_risk_pct,
        "prefer_defined_risk": prefer_defined,
    }
```

### Step 6: Attach Caution Flags

Scan for conditions that warrant human attention:

| Condition | Flag |
|---|---|
| `trend_alignment_state == "conflicting"` | `"conflicting_alignment"` |
| `momentum_state == "fading"` and `trend_state == "up"` | `"fading_momentum_in_uptrend"` |
| `realized_vol_state == "expanding"` and `trend_state == "sideways"` | `"expanding_vol_sideways"` |
| `len(missing_fields) > 2` | `"degraded_data_quality"` |
| all `abs(score) < 0.5` for trend, momentum, extension | `"flat_signals_transition"` |
| `opportunity_tier == "pass"` | `"no_trade_recommended"` |
| `regime_confidence < 0.3` | `"low_regime_confidence"` |
| `realized_vol_20d is None` | `"missing_realized_vol"` |

### Step 7: Compose `agent_summary`

Build a ≤ 120-char one-liner:

```
"{ticker}: {regime} | {opportunity_score}/10 | {direction} {trade_type} | {size_label}"
```

Where `size_label` maps `size_fraction` to `"full" | "3/4" | "half" | "quarter"`.

If `trade_type == "pass"`, use: `"{ticker}: {regime} | pass — re-evaluate next session"`.

---

## Write Path: TickerSnapshot Integration

The interpreter runs inline during the snapshot write path. It is called
*after* `compute_market_state_payload()` has populated the trend/momentum/
extension/vol fields on the entity, and *before* `put()`.

```python
from interpreter import interpret_snapshot

INTERPRETER_VERSION = "1.0.0"

def save_ticker_snapshot(snapshot: TickerSnapshot):
    # 1. Market state fields already populated by compute_market_state_payload()

    # 2. Run interpreter — pure function, no I/O
    setup = interpret_snapshot(snapshot, version=INTERPRETER_VERSION)

    # 3. Write indexed projections (for ranking queries)
    snapshot.regime_label = setup.regime
    snapshot.trade_bias = setup.trade_bias
    snapshot.opportunity_score = setup.opportunity_score
    snapshot.opportunity_tier = setup.opportunity_tier
    snapshot.recommended_trade_type = setup.trade_type
    snapshot.recommended_direction = setup.direction
    snapshot.trade_recommender_version = INTERPRETER_VERSION

    # 4. Write full blob (for detail consumption)
    snapshot.trade_setup = setup.to_dict()

    # 5. Persist
    snapshot.put()
```

The interpreter reads field values from the snapshot entity itself — no
separate "payload" dict needed. The function signature:

```python
def interpret_snapshot(
    snapshot: TickerSnapshot,
    version: str = "1.0.0",
) -> TradeSetup:
    """
    Pure function. Reads market-state fields from snapshot,
    returns a TradeSetup. Does not mutate the snapshot.
    """
```

For 1,000 tickers this adds negligible latency — the interpreter is just
arithmetic and dict lookups, no I/O.

---

## Ranking API: Querying Across the Universe

The indexed projections exist specifically so you can rank and filter at the
datastore level without deserializing 1,000 JSON blobs.

### Common queries

```python
# Top 20 opportunities today
q = TickerSnapshot.query(
    TickerSnapshot.opportunity_tier.IN(["high", "moderate"]),
).order(-TickerSnapshot.opportunity_score).fetch(20)

# All directional longs in low-vol regimes
q = TickerSnapshot.query(
    TickerSnapshot.regime_label == "trending_low_vol",
    TickerSnapshot.recommended_direction == "long",
).order(-TickerSnapshot.opportunity_score)

# Filter by trade type for a vol-selling dashboard
q = TickerSnapshot.query(
    TickerSnapshot.recommended_trade_type == "vol_premium",
).order(-TickerSnapshot.opportunity_score)
```

### Serving the full setup

Once you have the ranked list, serve `trade_setup` JSON directly to
dashboards or agents — no re-interpretation needed:

```python
# FastAPI / Flask endpoint
@app.get("/api/top-setups")
def top_setups(limit: int = 20, min_score: float = 5.0):
    snapshots = TickerSnapshot.query(
        TickerSnapshot.opportunity_score >= min_score,
    ).order(-TickerSnapshot.opportunity_score).fetch(limit)

    return [snap.trade_setup for snap in snapshots]
```

### Agent context injection

```python
setups = top_setups(limit=30, min_score=5.0)
context_lines = [s["agent_summary"] for s in setups if s["agent_summary"]]
agent_context = "Active trade setups:\n" + "\n".join(context_lines)

# Inject into Claude system prompt alongside the user's question
```

---

## Batch Interpreter & Correlation Check

For end-of-day batch runs across the full universe, use a thin wrapper that
adds cross-ticker awareness:

```python
def interpret_batch(
    snapshots: list[TickerSnapshot],
    version: str = "1.0.0",
) -> list[TradeSetup]:
    setups = [interpret_snapshot(s, version) for s in snapshots]

    # Correlation check: flag regime concentration
    from collections import Counter
    regime_counts = Counter(s.regime for s in setups if s.trade_type != "pass")
    concentrated = {r for r, c in regime_counts.items() if c >= 3}

    for s in setups:
        if s.regime in concentrated:
            s.caution_flags.append("concentrated_regime")

    # Sort by opportunity score descending
    setups.sort(key=lambda s: s.opportunity_score, reverse=True)
    return setups
```

---

## Relationship to DailyGexFull & DailySkewFull

The interpreter currently operates on market-state fields only (trend, momentum,
extension, vol, alignment, S/R). It does **not** read from `DailyGexFull` or
`DailySkewFull` directly.

However, several `TickerSnapshot` fields *derived from* GEX/skew data are
relevant inputs. These fields are already on `TickerSnapshot` and are available
to the interpreter without joining:

- `GEX`, `GexValue`, `gexFlipPrice` — could inform S/R context or caution flags
- `iv_rank`, `PCIVSpread`, `PC_25d_ratio` — could enrich vol regime classification
- `call_regime`, `call_spec_score` — could add flow-based caution flags
- `gex_structure` — could inform structure recommendations

**Planned extension path:** When you're ready to incorporate GEX/skew into the
interpreter, do it by adding *derived scalar signals* to `TickerSnapshot` during
the upstream compute step (e.g., `gex_regime: str`, `skew_z_score: float`), then
referencing those in the interpreter's validation and rule cascade. Do not have
the interpreter query `DailyGexFull` or `DailySkewFull` directly — that would
break the pure-function contract and add I/O to the hot path.

---

## Implementation Guidelines

### File Structure (Python backend)

```
interpreter/
    __init__.py           # Re-exports interpret_snapshot, interpret_batch
    types.py              # TradeSetup, SignalSnapshot, ValidatedPayload, enums
    validate.py           # Step 1 — null guards, clamping, defaults
    regime.py             # Step 2 — regime lookup + confidence + trade_bias
    scoring.py            # Step 3 — opportunity score + tier
    trade_select.py       # Step 4 — rule cascade for trade type
    risk.py               # Step 5 — sizing + risk params
    caution.py            # Step 6 — flag scanner
    summary.py            # Step 7 — agent_summary composer
    interpret.py          # Orchestrator — composes steps 1–7
tests/
    test_interpret.py     # Fixture-driven tests
    fixtures/
        trending_low_vol.json
        flush_panic.json
        choppy_pass.json
        degraded_data.json
        mean_reversion.json
        all_nulls.json
```

If you also need a TypeScript version (for VOLSCAN frontend or Express proxy),
mirror the same module structure under `src/interpreter/` with `.ts` files.

### The Orchestrator Function

```python
def interpret_snapshot(
    snapshot: TickerSnapshot,
    version: str = "1.0.0",
) -> TradeSetup:
    validated, missing = validate(snapshot)
    regime, confidence = classify_regime(validated)
    trade_bias = TRADE_BIAS_MAP[regime]
    score, tier = score_opportunity(validated)
    trade = select_trade(validated)
    risk = derive_risk(validated, trade["trade_type"])
    flags = scan_caution(validated, missing, tier, confidence)
    summary = compose_summary(
        snapshot.ticker, regime, score, trade["direction"],
        trade["trade_type"], risk["size_fraction"]
    )
    signal_snap = build_signal_snapshot(validated)

    return TradeSetup(
        ticker=snapshot.ticker,
        timestamp=snapshot.retrieved.isoformat(),
        interpreter_version=version,
        regime=regime,
        regime_confidence=confidence,
        opportunity_score=score,
        opportunity_tier=tier,
        trade_bias=trade_bias,
        **trade,
        **risk,
        caution_flags=flags,
        missing_fields=missing,
        signal_snapshot=signal_snap,
        agent_summary=summary,
    )
```

### Testing Strategy

Write fixture-driven unit tests. Each fixture is a `{ input, expected }` pair
where `input` is a dict of TickerSnapshot field values and `expected` is a
partial `TradeSetup` that the output must match on key fields.

**Minimum fixture set:**

| Fixture | Key assertion |
|---|---|
| Strong uptrend, low vol, aligned | `regime == "trending_low_vol"`, `trade_type == "directional"`, `direction == "long"`, `tier == "high"` |
| Down trend, vol expanding | `regime == "flush_panic"`, `prefer_defined_risk == true`, `size_fraction <= 0.5` |
| Sideways, elevated vol, extended | `trade_type != "directional"`, `caution_flags` includes `"expanding_vol_sideways"` |
| All nulls | `missing_fields` has 8+ entries, `trade_type == "pass"`, `caution_flags` includes `"degraded_data_quality"` |
| Scores near zero | `caution_flags` includes `"flat_signals_transition"`, `opportunity_tier == "pass"` |
| Mean reversion candidate | `trade_type == "mean_reversion"`, `structures` includes a spread |
| Indexed projection consistency | `snapshot.opportunity_score == setup.opportunity_score`, `snapshot.regime_label == setup.regime` |

Run tests with `pytest`. Aim for 100% branch coverage on the rule cascade in
Step 4.

---

## Versioning

The `interpreter_version` string (e.g., `"1.0.0"`) tracks the **logic version**,
not just the schema version. When you change the scoring formula, rule cascade
thresholds, or caution flag conditions, bump this version.

- **Patch** (1.0.x): Bug fixes, no behavior change on valid inputs.
- **Minor** (1.x.0): New caution flags, adjusted thresholds, new fields added
  to TradeSetup with defaults that preserve backward compatibility.
- **Major** (x.0.0): Breaking changes to scoring formula, regime map, or rule
  cascade that would produce different `opportunity_score` or `trade_type`
  for the same input.

The version is stored in two places:
1. `trade_recommender_version` on `TickerSnapshot` (for datastore queries like
   "which snapshots were scored under v1 vs v2").
2. `interpreter_version` inside the `trade_setup` JSON blob (so the blob is
   self-describing when read in isolation, e.g., from a cache or export).

---

## Edge Cases & Guardrails

- Never override a `"pass"` result programmatically. If the interpreter says
  pass, downstream systems should respect it. Human override is fine but must
  be logged.
- If `realized_vol_20d` is null, do not attempt vol-based sizing — use the
  0.5 default and flag `"missing_realized_vol"`.
- If the user flags an earnings or event catalyst, the *caller* should set
  `realized_vol_state = "elevated"` before passing the snapshot to the
  interpreter. The interpreter itself has no event calendar awareness.
- The interpreter does not fetch prices, compute scores, or call any API. It
  only transforms already-computed fields on the TickerSnapshot. Keep this
  boundary strict.
- All numeric outputs should be rounded to 2 decimal places for display
  consistency.
- The `trade_setup` blob and indexed projections must always agree. The
  write-path code is the single point that ensures this — never write one
  without the other.

---

## Extending the Schema

When adding new fields to `TradeSetup`:

1. Add the field to the dataclass with a sensible default.
2. Add the derivation logic to the appropriate step function.
3. Add at least one fixture that exercises the new field.
4. Decide: does this field need to be queryable across 1,000 tickers?
   - **Yes** → add an indexed ndb property to TickerSnapshot and update the
     write-path projection.
   - **No** → it lives only inside the `trade_setup` blob.
5. Update the `agent_summary` template only if the new field is critical for
   LLM context (keep it ≤ 120 chars).
6. Bump `interpreter_version` per the versioning rules above.
