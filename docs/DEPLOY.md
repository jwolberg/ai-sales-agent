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
