# Twilio Setup — route a phone number into the agent

Wire a real phone number to the intent-router agent. Inbound audio flows through Twilio Media
Streams → Pipecat (STT → `IntentRouterEngine` → TTS), and the call appears live on `/dashboard`
tagged `channel="twilio"`. See `docs/DEPLOY.md` for the broader deploy notes.

## Prerequisites

1. Install the voice extra and set keys in `backend/.env`:
   ```bash
   .venv/bin/python -m pip install -e "./backend[voice]"
   ```
   ```dotenv
   # backend/.env
   OPENAI_API_KEY=sk-...        # the brain
   DEEPGRAM_API_KEY=...         # STT
   CARTESIA_API_KEY=...         # TTS
   ```
2. A Twilio account (you only need the Account SID + Auth Token for the CLI/API options below).

## 1. Run + publicly expose the server

Twilio must reach the server over TLS, so expose it with a tunnel (e.g. ngrok).

```bash
# terminal 1 — the app (pick a free port; 8000 may be taken)
cd backend && .venv/bin/uvicorn app.main:app --port 8001

# terminal 2 — public tunnel
ngrok http 8001               # -> https://<id>.ngrok.app
```

Set the public URL in `backend/.env` and **restart uvicorn** (so the TwiML hands Twilio the correct
`wss://<id>.ngrok.app/voice/twilio/ws`):

```dotenv
PUBLIC_BASE_URL=https://<id>.ngrok.app
```

Verify readiness: `curl -s localhost:8001/voice/status` → `{"ready": true, "missing_keys": []}`.

## 2. Get a number and point it at the webhook

The webhook target is **`POST https://<id>.ngrok.app/voice/twilio`** (path must be exactly
`/voice/twilio`). Pick any option.

### Option A — Twilio Console (simplest)

1. **Buy a number:** Console → **Phone Numbers → Manage → Buy a number** → require **Voice**
   capability → Buy (~$1–2/mo).
2. **Configure it:** **Phone Numbers → Manage → Active numbers → [your number] → Voice
   Configuration**:
   - **"A call comes in"** → **Webhook**
   - URL: `https://<id>.ngrok.app/voice/twilio`
   - Method: **HTTP POST**
   - **Save.**

### Option B — Twilio CLI

```bash
brew install twilio/brew/twilio        # or: npm i -g twilio-cli
twilio login                           # paste Account SID + Auth Token

twilio api:core:available-phone-numbers:local:list --country-code US --voice-enabled --limit 5
twilio phone-numbers:buy:local --country-code US

twilio phone-numbers:update <PHONE_SID> \
  --voice-url "https://<id>.ngrok.app/voice/twilio" --voice-method POST
```

### Option C — curl (no CLI install)

```bash
export TWILIO_ACCOUNT_SID=AC...
export TWILIO_AUTH_TOKEN=...

# find an available number
curl -s -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/AvailablePhoneNumbers/US/Local.json?VoiceEnabled=true&PageSize=5"

# buy it + set the voice webhook in one call (use a PhoneNumber from the search)
curl -s -X POST -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers.json" \
  --data-urlencode "PhoneNumber=+1XXXXXXXXXX" \
  --data-urlencode "VoiceUrl=https://<id>.ngrok.app/voice/twilio" \
  --data-urlencode "VoiceMethod=POST"

# (to update an existing number instead, POST to .../IncomingPhoneNumbers/<PHONE_SID>.json
#  with VoiceUrl + VoiceMethod)
```

## 3. Call it

Dial the number. The agent answers first ("…test prep or tutoring?"), and the call streams live at
`https://<id>.ngrok.app/dashboard` — transcript, slot-filling, and the price quote at the end.

## Notes & troubleshooting

- **Trial accounts** can only call **verified** numbers and play a "trial" preamble before your TwiML
  runs — fine for testing; upgrading removes both.
- **No `twilio` Python SDK is required** — TwiML is generated directly and auto-hangup is off (the
  call ends when the caller hangs up).
- **Request signing is enforced.** With `TWILIO_AUTH_TOKEN` set in `.env`, `/voice/twilio` rejects
  any request without a valid `X-Twilio-Signature` (403), and the Media Streams socket closes unless
  the `start` frame carries the per-call token the webhook issued. The signature covers the exact
  public URL Twilio called, so `PUBLIC_BASE_URL` must match the webhook URL configured on the number
  (scheme + host). Without the auth token the webhook is open only when `ENVIRONMENT=development`
  and returns 503 otherwise.
- If the webhook 403s: the URL/host Twilio called doesn't match what the app reconstructs — set
  `PUBLIC_BASE_URL` to the exact public origin, or check the auth token is the number's account's.
- If the webhook 404s/errors: confirm the path is `/voice/twilio`, the method is **POST**, and
  `PUBLIC_BASE_URL` matches the ngrok URL (and you restarted uvicorn after setting it).
- Telephony audio is μ-law 8 kHz; Pipecat's `TwilioFrameSerializer` resamples to/from the STT/TTS
  rates. The first real call is the live validation point — if the agent is silent, garbled, talks
  over you, or doesn't hear you, set `VOICE_DEBUG=true` in `.env` (logs STT/VAD/audio frames) and
  share what you observe so the sample-rate / VAD / barge-in settings can be tuned.
