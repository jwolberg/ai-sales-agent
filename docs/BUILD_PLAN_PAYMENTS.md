# Build Plan — Stripe Payment Link (text-an-invoice / pay-now)

## Project
- **Name:** Payment capture after the quote (Stripe + Twilio SMS)
- **Summary:** After the intent-router agent quotes a leaf's price, let the caller pay without a
  human: the backend creates a **Stripe Payment Link** (pay-now) or **Stripe Invoice**
  (send-invoice) for that leaf, **texts the hosted URL via Twilio SMS**, and a **Stripe webhook**
  confirms payment — surfaced live on the dashboard. The agent and our server **never touch card
  data** (hosted checkout → PCI scope stays SAQ-A).
- **Source of truth:** this doc. Builds on the intent-router agent
  (`docs/BUILD_PLAN_INTENT_ROUTER.md`).
- **Default:** **off behind a feature flag** (`payments_enabled` = an OpenAI-style key check) until a
  Stripe key + **approved** prices are in. With the flag off, behavior is exactly as today (quote →
  offer a specialist; payment asks escalate).

## Strategy
Reuse what's already wired; add a thin, hosted-payment slice.
- **Reuse:** the brain tool contract (`agent/contract.py`), the engine loop + KPI/event publishing
  (`agent/intent_engine.py`, `agent/recorder.py`, `app/events.py`), the price table
  (`agent/pricing.py`), Twilio creds (`config.py`), the dashboard SSE + call detail.
- **Add:** a Stripe service, a Twilio SMS sender (raw REST — no SDK, matching the Twilio voice
  bridge), a `send_payment_link` brain tool, a webhook, and a `Payment` record.

### Correctness / safety anchors
- **Hosted checkout only** — never accept or transmit card numbers (keep the in-call card-number
  refusal). This is the whole PCI story.
- **Approved-price gate** — only create a charge when the leaf's price is `approved: true` in
  `pricing.yaml`; placeholder prices must NOT be chargeable.
- **Webhook is the source of truth** for "paid" (verify Stripe signature; the client `url` only
  proves a link was sent, not paid).
- **Idempotency** — Stripe idempotency keys so a retried turn can't double-charge.

---

## Phase PAY-0 — Config, dependency, feature flag
- **PAY0-T1 — Stripe config + dep.** Add `stripe` to deps; `STRIPE_API_KEY`,
  `STRIPE_WEBHOOK_SECRET`, `payments_currency` (default `usd`) to `config.py`; a
  `payments_enabled` property (`bool(stripe_api_key)`). App + tests boot without it (flag off).
  Also confirm `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` are present for SMS.

## Phase PAY-1 — Provider services (no agent wiring yet)
- **PAY1-T1 — Stripe service.** `app/payments/stripe_service.py`:
  `create_payment_link(leaf_id, amount, currency, *, idempotency_key) -> {id, url}` (one-off
  `price_data` line item from the price table) and `create_invoice(leaf_id, amount, customer_phone)
  -> {id, url}`. Injectable client for tests (fake Stripe). Refuses unless the leaf's price is
  approved.
- **PAY1-T2 — Twilio SMS sender.** `app/payments/sms.py` `send_sms(to, body) -> sid` via the Twilio
  Messages REST API (basic auth, raw HTTP — no `twilio` SDK, like the voice bridge). Injectable for
  tests; no-op + clear error when creds/`to` are missing.

## Phase PAY-2 — Persistence
- **PAY2-T1 — `Payment` model + recorder.** New `Payment` row (`payment_id`, `call_id`, `leaf`,
  `amount`, `currency`, `provider="stripe"`, `kind` link|invoice, `provider_ref`, `url`,
  `status` created|sent|paid|failed, `created_at`, `paid_at`). `recorder.record_payment(...)` +
  `mark_payment_paid(provider_ref)`; publish `payment_sent` / `payment_paid` on the event bus
  (migration-recreate caution — additive table; rebuild the dev DB).

## Phase PAY-3 — Brain tool + engine wiring
- **PAY3-T1 — `send_payment_link` tool.** Add to `agent/contract.py` (TOOLS): args
  `kind` (`link`|`invoice`), optional `phone`. The brain calls it only **after** a leaf is
  confirmed (same gate as `quote_price`) and the caller asks to pay / wants an invoice.
- **PAY3-T2 — Engine executor.** In `intent_engine.py`, executing the tool: resolve leaf → price
  (must be approved) → `create_payment_link`/`create_invoice` → `send_sms` to the caller's number →
  `record_payment` + emit `payment_sent`. Phone number: from the Twilio call's `From` (caller ID)
  when present; otherwise the brain must collect it via the tool's `phone` arg. Compose a spoken
  confirmation ("I've texted you a secure link to pay…").
- **PAY3-T3 — Guardrail reconcile.** When `payments_enabled`, "I'll pay now / text me an invoice"
  routes to this flow instead of escalating; **card numbers still refuse/escalate** (unchanged).
  Add KPI events `PAYMENT_LINK_SENT`, `PAYMENT_COMPLETED`.

## Phase PAY-4 — Webhook (source of truth for "paid")
- **PAY4-T1 — Stripe webhook.** `POST /payments/webhook`: verify the Stripe signature with
  `STRIPE_WEBHOOK_SECRET`; on `checkout.session.completed` / `invoice.paid` →
  `mark_payment_paid(provider_ref)` → emit `payment_paid` (→ SSE). Idempotent on event id.

## Phase PAY-5 — Dashboard surface
- **PAY5-T1 — Payment status on the dashboard.** Surface per-call payment state (link sent → paid)
  on the call card + detail and an insights tile (paid rate / revenue). Events already stream; add
  the rendering + the `payment` fields to the call detail API.

## Phase PAY-6 — Hardening & docs
- **PAY6-T1 — Safety + docs.** Verify the approved-price gate blocks placeholder prices; document
  setup (Stripe test keys, `stripe listen` for local webhooks, ngrok) in `docs/DEPLOY.md`; note
  refunds/tax/terms remain a specialist's job (out of scope).

## Phase PAY-7 — Test-call billing link (dev fake mode + in-call surface)
Make the billing link demoable from the in-dashboard **Test Call** (IR-8) with no Stripe/Twilio keys
and no real charge — a web mic call has no caller ID, so the link is shown in the panel and can be
texted to a number the operator types.
- **PAY7-T1 — Dev fake payments mode.** A `PAYMENTS_FAKE` flag (dev-only) makes `payments_enabled`
  true without a key: `get_stripe_service` returns a `FakeStripeGateway` (deterministic
  `https://…example.test/fake/…` links, no network) and `get_sms_sender` a no-op fake. In fake mode
  the Stripe service runs with `allow_unapproved=True` so the placeholder `pricing.yaml` is
  chargeable *for the fake only* — **the real path keeps the strict approved-price gate** (PAY-6).
- **PAY7-T2 — In-call link + text it.** The Test Call panel surfaces the active call's payment link
  (click-to-open) by reading the live call's `payment` (already streamed via `payment_sent`), plus a
  phone field that POSTs to `POST /api/calls/{id}/send-payment-sms` to text the hosted URL (uses the
  fake SMS sender in fake mode). Caller-ID auto-text on real Twilio calls remains a follow-on.

---

## Data-model notes
- New `Payment` table (above). Optionally denormalize the latest `payment_status` onto `Call` for
  the board. **Migration caution:** no migration tool — recreate the dev DB after adding the table
  (and rebuild the KB index).

## Validation strategy
- Unit-test the Stripe service + SMS sender with **fake clients** (no network); assert the
  approved-price gate refuses placeholder leaves and that idempotency keys are passed.
- Test the engine executor end-to-end offline with fake Stripe + fake SMS (RuleBrain), asserting a
  `Payment` row + `payment_sent` event.
- Test webhook signature verification + `payment_paid` transition with a signed fake event.
- Everything must stay green with the flag **off** (no Stripe key) — payment asks still escalate.

## Key decisions (to record in decision-log when built)
- **Hosted Stripe checkout, never in-call card capture** — keeps PCI at SAQ-A; the existing
  card-number guardrail stays.
- **Support both Payment Link (pay-now) and Invoice (send-invoice)** — the brain picks from what the
  caller asks; default to Payment Link.
- **Twilio Messages via raw REST (no SDK)** — consistent with the voice bridge; one fewer dep.
- **Webhook is the paid source of truth**, not the SMS send.
- **Feature-flagged off + approved-price gate** — no accidental real charges on placeholder prices.

## Open questions (resolve in-phase)
- One Stripe **Product/Price per leaf** (catalog in Stripe) vs. **one-off `price_data`** per charge?
  (Start with one-off; move to a Stripe catalog if you want reporting there.)
- Customer identity: create a Stripe **Customer** keyed by phone for repeat callers, or anonymous
  per-charge? (Anonymous to start.)
- Web/sim channel: collect the phone via the tool; or skip SMS and just show the link on the
  dashboard for non-phone calls.
- Number to text on a Twilio call: caller ID (`From`) by default — allow the brain to override if
  the caller gives a different number.
