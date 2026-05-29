# Deploy

The backend (API + dashboard + intent-router brain + benchmark **+ the realtime voice extra**)
ships as a single container, so the Test Call and Twilio phone path run on the deployed image.
Stack reconciliation rationale is in `docs/decision-log.md` (R13 / D-16).

## One-command local run (Docker)

```bash
# from repo root
docker build -t nerdy-router .
docker run --rm -p 8080:8080 -e OPENAI_API_KEY=sk-... nerdy-router
# open http://localhost:8080/dashboard  (health: /health)
```

Without `OPENAI_API_KEY` the offline rule-based brain + TF-IDF retriever run, so the app still boots.

## GCP Cloud Run (project `nerdy-1`)

Builds the repo `Dockerfile` and deploys in one step (Cloud Build pushes the image to Artifact
Registry automatically — no manual `docker build`/`push`).

```bash
PROJECT=nerdy-1
REGION=us-central1
gcloud config set project "$PROJECT"

# one-time: enable the APIs the deploy uses
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# build from the Dockerfile + deploy (run from the repo root)
gcloud run deploy nerdy-router \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --max-instances 1 \
  --timeout 3600 \
  --set-env-vars OPENAI_API_KEY=sk-...,DEEPGRAM_API_KEY=...,ANTHROPIC_API_KEY=...,CARTESIA_API_KEY=...
# -> prints the service URL; open <service-url>/dashboard   (health: <service-url>/health)
```

The image bundles the voice extra (Pipecat + OpenCV/WebRTC native libs), so the build is heavier and
the image larger than a core-only one — the first `--source` build takes a few minutes.

Notes:
- **Pin to one instance for the live dashboard.** The dashboard streams over an **in-process**
  event bus (`app/events.py`) and reads per-instance SQLite, so a call/sim and the watching
  dashboard must be on the **same** instance. `--max-instances 1` (optionally `--min-instances 1`
  to avoid cold starts) keeps the demo coherent. True multi-instance would need a shared pub/sub +
  shared DB — not built.
- **Secrets.** `--set-env-vars` is fine for a quick demo. For real keys use Secret Manager:
  `gcloud run deploy … --set-secrets OPENAI_API_KEY=openai-key:latest`.
- **Database is ephemeral.** The image runs `python -m app.db.seed` on boot, which `create_all`s
  the schema fresh — so new tables/columns (e.g. `payments`, `Turn.latency_breakdown`) appear
  automatically on a fresh container. The SQLite file resets per instance/redeploy. For persistence,
  set `DATABASE_URL` to a managed DB (e.g. Cloud SQL Postgres); there's no migration tool, so create
  the schema once against it.
- Without `OPENAI_API_KEY` the offline rule brain + TF-IDF retriever run, so it still boots.
- **sqlite-vec** loads on the slim image's Python (loadable-extension support — D-17), so the
  production KB can use a sqlite-vec index over the same `kb_embeddings` rows.

### Voice / Twilio on Cloud Run

The image **includes the voice extra**, so `/voice/*` is served on Cloud Run. Verified at the
container level: the image builds, the full voice path imports (`pipecat`, `aiortc`, `onnxruntime`,
`cv2`), all voice routes register, and `/voice/twilio/ws` is reachable (it rejects with the
missing-keys guard until the STT/TTS keys are set). To run voice for real:

1. Set the voice keys (above): `DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY` (use
   Secret Manager for real values). `/voice/status` should then report `ready: true`.
2. `--timeout 3600` and `--max-instances 1` matter here: a phone call holds the Media Streams
   WebSocket open for the whole call, and the dashboard must be the same instance (in-process bus).
3. Point Twilio's **Voice → A call comes in** webhook at `https://<service-url>/voice/twilio`, and
   set `PUBLIC_BASE_URL=https://<service-url>` so the `<Stream>` wss URL is correct.

> **Still needs a real inbound call to fully validate** — the container build + imports + route
> wiring are confirmed, but the live telephony audio loop (μ-law 8 kHz resampling, echo/latency
> tuning) can only be checked end-to-end on an actual call (see RUNBOOK).

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
   (For a local run, use the ngrok tunnel above. On Cloud Run the image already serves voice — set
   `PUBLIC_BASE_URL` to the service URL instead, and point Twilio's webhook at it.)
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

> **Note:** the webhook must reach the same DB that recorded the `Payment`. With `--max-instances 1`
> on Cloud Run the call and the webhook share one instance + DB, so it just works; if you run the
> voice path locally instead, point the Stripe webhook at that local tunnel (or use one shared
> `DATABASE_URL`). `PAYMENTS_FAKE=true` gives a keyless end-to-end demo (fake links, no real charge).

### Out of scope (a specialist handles these)

Refunds, tax, discounts/coupons, and contract terms are **not** automated — the agent escalates
discount/refund asks. Booking quantity (e.g. hour packages) isn't modeled yet: a link charges one
unit of the leaf's price. Card numbers are never accepted in-call.
