# Agent Conversation Flow (As-Built)

> **Status:** As-built reference, updated 2026-05-29 on branch
> `docs/intent-router-pivot`. This document was originally a pre-build *mockup*
> of an 11-stage sales orchestrator (see §9 for what changed). The call agent
> now ships as an **intent router**: a single tool-calling brain per turn,
> wrapped in deterministic rails. This doc describes what the code actually
> does — how the call **decides**, what it **stores**, and how it **grounds
> answers in the KB vectorstore**. File:line references point at the live code.

## 1. Architecture at a Glance

A call is a loop of **turns**. On each turn the caller's audio becomes text, the
**brain** decides one action and an utterance, deterministic **rails** vet that
decision, the result is **persisted**, and the utterance is spoken back.
 
```
                ┌─────────────────────── one turn ───────────────────────┐
  caller audio → STT (Deepgram) → IntentRouterEngine.run_turn()           │
                                    │                                      │
                                    ├─ confidence gate (< 0.6 → re-ask)    │
                                    ├─ brain.decide()  ← OpenAI tool loop   │
                                    │     tools: slot_fill / kb_lookup /    │
                                    │            quote_price / escalate /   │
                                    │            send_payment_link          │
                                    ├─ payment executor (Stripe + SMS)      │
                                    ├─ mis-quote guardrail                  │
                                    ├─ KPI events + Decision row persisted  │
                                    └─ utterance → TTS (Cartesia) → caller  │
                └─────────────────────────────────────────────────────────┘
```

The pivot's key simplification: there is **no staged state machine** driving the
call. The brain re-reads the full transcript + known lead fields + accumulated
slots every turn and picks the next move. "Where we are in the call" is an
emergent property of which **slots** are filled and whether a product **leaf**
has resolved — not a `stage` variable the code advances.

## 2. The Voice Pipeline (STT → Brain → TTS)

Built on the **Pipecat** framework. The frame pipeline
(`backend/app/voice/bot.py:193`):

```
transport.input → STTMuteFilter → DeepgramSTT → EngineProcessor → CartesiaTTS → transport.output
```

| Stage | Provider / SDK | Notes |
| ----- | -------------- | ----- |
| **STT** | Deepgram (`DeepgramSTTService`, `pipeline.py:73`) | 16 kHz PCM; word-level confidence read off the transcript (`bot.py:78`) |
| **Brain** | OpenAI Chat Completions, `gpt-4o` default (`brain.py:290`) | runs in a thread pool — `asyncio.to_thread(engine.run_turn)` (`bot.py:142`) |
| **TTS** | Cartesia (`CartesiaTTSService`) | voice id configurable (`config.py:85`) |
| **VAD** | Silero | turn-taking; fires `UserStoppedSpeakingFrame` |

**Two transports, one brain:**

- **Phone** (`twilio_bot.py`): Twilio POSTs `/voice/twilio`; the TwiML opens a
  `<Stream>` WebSocket to `/voice/twilio/ws` carrying the caller's number as a
  custom parameter. `TwilioFrameSerializer` decodes μ-law 8 kHz. Channel logged
  as `"twilio"`. The caller-ID `From` is threaded into the engine so a payment
  link can be auto-texted (`twilio_bot.py:101`).
- **Web demo** (`bot.py`): `SmallWebRTCTransport` over a browser WebRTC peer.
  Channel logged as `"web"`. Can resume a known lead's prior memory.

**Latency** is measured at four monotonic boundaries per turn (`latency.py`):
`user_stopped → transcript (stt_ms) → brain_done (brain_ms) → bot_started
(tts_ms)`. The end-to-end total and the `{stt_ms, brain_ms, tts_ms}` split are
written back onto the agent's `Turn` row (`bot.py:177`) and shown on the
dashboard.

**Fillers** (`fillers.py`): the moment a final transcript arrives — *before* the
brain is called — a short phrase is spoken to cover latency. A knowledge-style
question ("how does…") gets a "working" filler ("Good question — let me check on
that."); everything else gets a one-word ack ("Sure.", "Got it."). Toggled by
`settings.fillers` (default on).

## 3. How the Call Makes Decisions

### 3.1 Per-turn sequence — `IntentRouterEngine.run_turn()`

`backend/app/agent/intent_engine.py:100`. In order:

1. **Confidence gate** — STT confidence < 0.6 → ask the caller to repeat, skip
   the brain entirely (`intent_engine.py:102`).
2. **Record the prospect turn** to the transcript.
3. **`brain.decide(history, lead_fields, slots)`** — timed; returns a
   `BrainDecision`.
4. **Payment executor** — if the decision is `PAY`, create the Stripe
   link/invoice and text it (§3.6).
5. **Mis-quote guardrail** — scan the utterance for dollar amounts; block any
   the brain wasn't authorized to say (§3.5).
6. **KPI events** — leaf-reached, clarify-asked, escalation.
7. **Persist** the `Decision` row, then record the agent turn.

### 3.2 Two brains behind one protocol

`get_brain()` (`brain.py:64`) returns the live brain when an OpenAI key is set,
else the deterministic one:

- **`OpenAIBrain`** (live, `brain.py:209`) — a bounded **tool-calling loop**
  (`MAX_TOOL_ROUNDS = 5`) against OpenAI Chat Completions with
  `tool_choice="auto"`. The model freely calls `slot_fill`, `kb_lookup`,
  `quote_price`, `escalate`, and (when payments are enabled)
  `send_payment_link`. When it stops calling tools, its text is the utterance.
- **`RuleBrain`** (offline, `brain.py:108`) — deterministic keyword matching, no
  network. Powers the test suite and the self-play simulator so neither needs an
  API key.

Both emit the same `BrainDecision` and obey the same rails, so behavior is
consistent between live calls and offline evaluation.

### 3.3 The decision vocabulary — `RouterAction` (7 values)

This **replaces** the mockup's 11 stages / 10 selected-actions / 6 modifiers.
`backend/app/agent/contract.py:155`:

| `RouterAction` | Meaning |
| -------------- | ------- |
| `GREET`        | Opening line (call open, before any user turn) |
| `ASK`          | Ask the next disambiguating discovery question |
| `ANSWER`       | Answer an informational question from the KB |
| `QUOTE`        | State the authoritative price for a resolved leaf |
| `PAY`          | Send a hosted payment link / invoice |
| `ESCALATE`     | Hand off to a human |
| `END`          | Caller declined / wrap up |

### 3.4 Slots, the taxonomy, and leaf resolution

Discovery is modeled as filling **slots** against a fixed product **taxonomy**
(`backend/app/agent/taxonomy.py`), not as free-form stages:

- **Slot fields, in order:** `category` (`test_prep` | `tutoring`) → then either
  `test` (`SAT` | `ACT` | `PSAT`, test-prep only) or `subject_area`
  (`math` | `science`) → `subject` (`algebra`, `geometry`, `chemistry`,
  `biology`, `physics`, tutoring only).
- Children imply parents (`subject=chemistry` ⇒ `science` ⇒ `tutoring`).
- A fully-specified path resolves to a **leaf** (e.g. `test_prep/SAT`,
  `tutoring/science/chemistry`). The leaf is what unlocks quoting and payment.

`next_unfilled(slots)` decides which question to ask next; once `resolve_leaf()`
returns a leaf, the agent can quote and transact.

**Decision priority** (how the action is chosen, `brain._infer_action`):

| Condition | Action |
| --------- | ------ |
| Escalation trigger detected | `ESCALATE` (short-circuits everything) |
| Payment intent + leaf resolved + payments enabled | `PAY` |
| `quote_price` used + leaf resolved | `QUOTE` |
| `kb_lookup` returned grounded content | `ANSWER` |
| No leaf yet | `ASK` (next disambiguating question) |

### 3.5 Guardrails (deterministic rails)

`backend/app/agent/guardrails.py` — these run *outside* the model so they can't
be talked around:

- **Escalation detection** (`detect_escalation`) — first-match-wins cues:
  human request → legal/safety/privacy → **card data** → price concession →
  anger/confusion. Card-data cues ("credit card", "card number") **always**
  escalate — the agent never takes a card in-call (PCI).
- **Mis-quote guard** (`check_mis_quote`, run in the engine *after* the brain) —
  extracts every `$X` / "X dollars" from the utterance. If the brain stated any
  amount it wasn't authorized to (no `quoted_amount`, or a mismatch), the turn is
  **rewritten to an escalation** and a `MIS_QUOTE_BLOCKED` KPI is emitted. This
  is the backstop against a hallucinated price.
- **Price quotes never come from the KB or the model** — only from an exact
  lookup in `data/pricing/pricing.yaml` keyed by the resolved leaf
  (`pricing.quote_price`). No price → honest "let me get a specialist" fallback.

### 3.6 The payment decision path

When the brain calls `send_payment_link` (live) or `RuleBrain` detects an
explicit pay/invoice intent on a resolved, quoted leaf, the engine
(`intent_engine.py:194`):

1. Creates a Stripe hosted **link** or **invoice** (`create_payment_link` /
   `create_invoice`).
2. **Texts** the URL via Twilio SMS to `req.phone or self.caller_number`
   (best-effort — a send failure doesn't fail the turn).
3. Writes a `Payment` row (`status = sent`, or `created` if the SMS didn't go).
4. Emits a `PAYMENT_LINK_SENT` KPI and speaks a confirmation.

A `dev fake mode` (`payments_fake`) swaps in `FakeStripeGateway` +
`FakeSmsSender` so the whole path runs with no keys and no real charge.

## 4. How the Call Stores Data

**Engine:** SQLite by default (`backend/sales_agent.db`), swappable to Postgres
via `DATABASE_URL`. Tables created by `init_db()`; sessions via `SessionLocal`.
Turns and decisions are **committed as they happen** so a transcript survives a
mid-call crash (`recorder.py`).

The recorder (`backend/app/agent/recorder.py`) owns the DB session for a call
and writes these tables (`backend/app/db/models.py`):

| Table | What it holds |
| ----- | ------------- |
| `leads` | Caller/lead profile + **cross-call memory** (§4.2) |
| `calls` | One row per conversation; channel, outcome, version stamps (§4.3), resolved leaf, quoted price |
| `turns` | Full transcript — one row per utterance + per-turn latency split |
| `decisions` | One row per brain decision (§4.1) |
| `kpi_events` | Escalations and measurable milestones |
| `payments` | Stripe link/invoice lifecycle (§4.4) |
| `experiments` / `variants` | A/B config for the improvement loop |
| `kb_embeddings` | Vectorstore — KB chunks + vectors (§5) |

### 4.1 The `Decision` row (the decision trace)

`models.py:139`. Written by `recorder.record_brain_decision()` each turn:

| Column | Populated | Notes |
| ------ | --------- | ----- |
| `selected_action` | ✓ | the `RouterAction` value (`ask`/`answer`/`quote`/`pay`/`escalate`/`end`) |
| `stage` | ✓ | **as-built, mirrors `selected_action`** — the old 11-stage enum is not populated |
| `reason` | ✓ | brain's rationale |
| `confidence` | ✓ | 1.0 once a leaf resolves, lower while disambiguating |
| `slots` | ✓ | cumulative slot state at this turn |
| `leaf` | ✓ | resolved product leaf, if any |
| `missing_fields` | ✓ | required slots still unknown |
| `kb_sources_used` | ✓ | source filenames cited when answering |
| `turn_id`, `call_id`, `created_at` | ✓ | linkage + ordering |
| `escalation_risk` | ✗ | column exists but is **never written** |

> **Reconciled from the mockup:** the doc once proposed a separate `modifier`
> column for human-layer moves (rapport/clarify/banter/…). The pivot dropped
> that idea — **there is no `modifier` column**, and `stage` simply echoes
> `selected_action`. The 7-value `RouterAction` is the whole decision vocabulary.

### 4.2 Lead profile + cross-call memory

`leads` carries nine typed profile columns (`student_name`,
`relationship_to_student`, `subject`, `grade_level`, `goal`, `urgency`,
`schedule_constraints`, `decision_maker_status`, `budget_sensitivity`) plus:

- `collected_fields` (JSON) — **every** slot learned, including extras beyond the
  nine columns, so a returning caller isn't re-asked.
- `prior_objections` (JSON, de-duped), `prior_summary` (running text), `status`.

`LeadStore.apply_call_outcome()` (`memory/lead_store.py`) folds a finished
call's slots, objections, and summary back onto the lead. `is_synthetic` marks
simulator leads so they're excluded from real-call metrics.

### 4.3 Version stamping (reproducibility)

Every `Call` is stamped with content hashes (`agent_version`,
`playbook_version`, `kb_version`) and a `model_version` so any outcome is
traceable to the exact config that produced it (`versioning.compute_versions`).

> **Known discrepancy / follow-up:** `model_version` records
> `settings.anthropic_model` (`claude-sonnet-4-6`), but the **live brain runs
> OpenAI `gpt-4o`** (`openai_chat_model`). The stamp is a leftover from the
> pre-pivot Claude design and currently mis-attributes the model. Worth fixing
> so the trace reflects the brain that actually ran.

### 4.4 Payment lifecycle

`payments` rows move `created → sent → paid` (or `failed`). `provider_ref`
(indexed Stripe id) is how the Stripe **webhook** finds the row;
`mark_payment_paid()` flips `status=paid` + `paid_at` idempotently.

## 5. How the Call Uses the Corpus (Vectorstore)

The agent answers factual questions **only** from an approved corpus, retrieved
by similarity — never from the model's own knowledge.

### 5.1 The corpus

Seven markdown docs in `data/kb/` (`pricing.md`, `offering_overview.md`,
`subjects_overview.md`, `test_prep_overview.md`,
`tutoring_formats_and_matching.md`, `policies_and_compliance.md`,
`scheduling.md`). `ingest.py` splits each at `##` (H2) headings into
**chunks**, each carrying:

- `chunk_id` (`"<file>#<n>"`), `source` (filename — the **citable id**),
  `title` (doc + section), and `text`. ~10–15 chunks total.

### 5.2 Embeddings + the index

- **Live:** OpenAI `text-embedding-3-small`. Vectors are serialized as
  little-endian float32 and stored in the **`kb_embeddings` SQLite table**
  alongside operational data (`dim` = the vector's length, 1536 for that model).
  No separate vector DB and no on-disk `.npy`/`.faiss` index — the table *is* the
  index. Built/rebuilt with `python -m app.kb.index` (clears prior rows first).
- **Fallback:** with no OpenAI key, a dependency-free **TF-IDF** retriever
  (`retriever.py`) over the same chunks. Tests use a tiny fake embedder. Both
  expose the identical `retrieve(query, *, k, min_score)` interface, so the agent
  never knows which is active.

### 5.3 Retrieval + grounding

- **`VectorRetriever`** scores chunks by **cosine similarity**, returns top
  `k=3` above `min_score=0.30`. TF-IDF fallback uses a `0.45` bar. No category
  filter — the small corpus is searched whole.
- `knowledge.answer_question()` returns a `GroundedAnswer`: if hits clear the
  bar, the unique `sources` + `snippets`; otherwise `grounded=False` with an
  honest deferral ("I want to make sure I give you accurate information… I can
  connect you with a specialist").
- **In the brain:** the model's `kb_lookup` tool returns the grounded snippets or
  the literal `"NO_APPROVED_CONTENT"`. The system prompt forbids inventing
  facts — answer *only* from what `kb_lookup` returns, else offer a specialist.
  `is_knowledge_question()` keeps social pleasantries ("how's it going?") from
  triggering a lookup.

So every spoken fact is either (a) a grounded KB snippet with a recorded source,
(b) an exact price from `pricing.yaml`, or (c) an honest "I'll connect you with a
specialist." There is no path where the model free-associates a factual claim.

## 6. The Flow Is Still Not Linear

The realism goals of the original mockup still hold — the agent loops
(discovery → Q&A → discovery; clarify → answer → close) and handles side topics.
But that non-linearity now comes from the brain re-deciding every turn against
live slot state, **not** from an explicit state machine. The guiding question is
unchanged: not *"what question is next?"* but *"what does this moment require?"* —
answered by the tool the brain reaches for (`slot_fill`, `kb_lookup`,
`quote_price`, `escalate`, `send_payment_link`) or by plain speech.

## 7. Key Files

| Concern | File |
| ------- | ---- |
| Per-turn orchestration | `agent/intent_engine.py` |
| Brain (live + offline) | `agent/brain.py` |
| Tools + `RouterAction` + `BrainDecision` | `agent/contract.py` |
| Taxonomy / leaf resolution | `agent/taxonomy.py` |
| Guardrails (escalation, mis-quote) | `agent/guardrails.py` |
| Pricing lookup | `agent/pricing.py` |
| KB grounding | `agent/knowledge.py` |
| Vectorstore (chunk, embed, retrieve) | `kb/{ingest,index,vector_retriever,retriever,embeddings}.py` |
| Persistence | `agent/recorder.py`, `db/models.py` |
| Cross-call memory | `memory/lead_store.py` |
| Voice pipeline | `voice/{bot,twilio_bot,pipeline,fillers}.py` |
| Latency | `agent/latency.py` |
| Payments | `payments/{stripe_service,webhook,sms,fakes}.py` |

## 8. Known Gaps / Follow-ups

1. `Call.model_version` records the configured Anthropic model, not the OpenAI
   `gpt-4o` brain that actually runs (§4.3).
2. `Decision.escalation_risk` is a defined-but-unused column.
3. `Decision.stage` duplicates `selected_action`; if no consumer needs the
   legacy column it could be dropped.
4. The KB corpus is small (~10–15 chunks); retrieval thresholds (0.30 vector /
   0.45 TF-IDF) are tuned conservatively for that size and will need revisiting
   as the corpus grows.

## 9. What Changed From the Original Mockup

| Mockup (pre-build) | As-built (intent router) |
| ------------------ | ------------------------ |
| 11-stage sales state machine driving the call | No state machine — brain re-decides each turn from slot state |
| `stage` (11) × `selected_action` (10) × `modifier` (6) trace | Single `RouterAction` (7); `stage` mirrors it; no `modifier` |
| Separate orchestrator modules (closing/discovery/objections/router…) | Collapsed into one `brain.decide()` + `intent_engine` (old modules are stale `.pyc`) |
| Open question: one LLM call vs. separate decision call | **Resolved:** one bounded tool-calling loop emits decision + utterance |
| Discovery as a checklist of stages | Discovery as slot-filling against a fixed product taxonomy → leaf |
| Claude as the model | OpenAI `gpt-4o` for the brain; OpenAI embeddings for the KB |
