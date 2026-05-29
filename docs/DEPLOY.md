# Deploy

The core backend (API + dashboard + intent-router brain + benchmark) ships as a container; the
live voice path is run locally (it needs WebRTC + a browser/mic). Stack reconciliation rationale is
in `docs/decision-log.md` (R13 / D-16).

## One-command local run (Docker)

```bash
# from repo root
docker build -t nerdy-router .
docker run --rm -p 8080:8080 -e OPENAI_API_KEY=sk-... nerdy-router
# open http://localhost:8080/dashboard  (health: /health)
```

Without `OPENAI_API_KEY` the offline rule-based brain + TF-IDF retriever run, so the app still boots.

## GCP Cloud Run (target)

```bash
gcloud builds submit --tag gcr.io/$PROJECT/nerdy-router
gcloud run deploy nerdy-router \
  --image gcr.io/$PROJECT/nerdy-router \
  --region us-central1 --allow-unauthenticated \
  --set-env-vars OPENAI_API_KEY=sk-...
```

Notes:
- Cloud Run's filesystem is ephemeral — the bundled SQLite resets per instance. For persistence,
  point `DATABASE_URL` at a managed DB (e.g. Cloud SQL).
- **sqlite-vec** loads on a Python build with loadable-extension support (the slim image qualifies
  where the local macOS framework Python did not — D-17), so the production KB can move from the
  dev Python-cosine retriever to a sqlite-vec index over the same `kb_embeddings` rows.

## Twilio inbound phone line (IR7-T7)

Route a real phone number into the same intent-router brain. The call appears on the dashboard
tagged `channel="twilio"` and streams live like a simulated one.

1. Install the voice extra and set keys in `backend/.env`:
   ```bash
   .venv/bin/python -m pip install -e ".[voice]"
   # OPENAI_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY  (the brain + STT + TTS)
   # optional: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
   ```
2. Expose the server publicly (Twilio must reach it over TLS). Locally, use a tunnel:
   ```bash
   .venv/bin/uvicorn app.main:app --port 8000
   ngrok http 8000        # -> https://<id>.ngrok.app
   # set PUBLIC_BASE_URL=https://<id>.ngrok.app in backend/.env (so the <Stream> wss URL is correct)
   ```
   (On Cloud Run the service URL is already public; set `PUBLIC_BASE_URL` to it.)
3. In the Twilio console, set the phone number's **Voice → A call comes in** webhook to:
   ```
   POST  https://<public-host>/voice/twilio
   ```
4. Call the number. Twilio fetches the TwiML (`<Connect><Stream>`), opens a Media Stream WebSocket
   to `/voice/twilio/ws`, and the agent answers — classify → quote, observable live at `/dashboard`.

Notes:
- No `twilio` Python SDK needed; TwiML is generated directly and auto-hangup is off (the call ends
  when the caller hangs up).
- Telephony is μ-law 8 kHz; Pipecat's `TwilioFrameSerializer` resamples to/from the STT/TTS rates.
  Sample-rate / echo tuning may need adjustment on the first real call — see RUNBOOK.

## Payments — Stripe payment link / invoice (BUILD_PLAN_PAYMENTS)

After the agent quotes a confirmed leaf, the caller can pay without a human: the backend creates a
**Stripe-hosted** Payment Link or Invoice, **texts the URL via Twilio SMS**, and a **Stripe webhook**
confirms payment — surfaced live on the dashboard. Our server never touches card data (hosted
checkout → PCI stays SAQ-A; in-call card numbers still escalate to a human).

**Default: OFF.** Payments are gated on `STRIPE_API_KEY`. With no key, behavior is exactly as today
(payment asks escalate). **Two independent gates must both pass before any charge is created:**

1. `STRIPE_API_KEY` is set (`payments_enabled`), and
2. the leaf's price is `approved: true` in `data/pricing/pricing.yaml`.

> ⚠️ **The committed `pricing.yaml` ships `approved: false` (placeholder prices).** Until an operator
> replaces them with approved figures and flips the flag, every charge is refused and the turn
> escalates instead — verified by `test_shipped_pricebook_blocks_every_leaf_until_prices_are_approved`.

### Setup

1. Config in `backend/.env` (Stripe **test** keys to start — `sk_test_…`):
   ```bash
   STRIPE_API_KEY=sk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_...     # from `stripe listen` (below) or the dashboard
   PAYMENTS_CURRENCY=usd               # optional (default usd)
   # SMS delivery (optional — without it the link is still recorded + shown on the dashboard):
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+1...            # E.164 sender
   ```
2. Approve real prices: edit `data/pricing/pricing.yaml`, set `approved: true` and the operator
   figures. (This is also the authoritative table the mis-quote guardrail checks against.)
3. Run the webhook locally with the Stripe CLI (gives you the `whsec_…` signing secret):
   ```bash
   stripe listen --forward-to localhost:8000/payments/webhook
   # paste the printed "whsec_..." into STRIPE_WEBHOOK_SECRET, then restart uvicorn
   ```
   In production (or for a real card on Stripe-hosted pages), point a Stripe **Dashboard → Webhooks**
   endpoint at `https://<public-host>/payments/webhook` for `checkout.session.completed` and
   `invoice.paid`. (`ngrok http 8000` works for a public URL during local testing — same tunnel as
   the Twilio section.)

### Out of scope (a specialist handles these)

Refunds, tax, discounts/coupons, and contract terms are **not** automated — the agent escalates
discount/refund asks. Booking quantity (e.g. hour packages) isn't modeled yet: a link charges one
unit of the leaf's price. Card numbers are never accepted in-call.
