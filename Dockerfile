# Voice-enabled backend image: API + dashboard + intent-router brain + benchmark, PLUS the realtime
# voice extra (Pipecat: Deepgram STT + Cartesia TTS + WebRTC/Twilio Media Streams) so the in-dashboard
# Test Call and Twilio phone path work on the deployed container. Run with --max-instances 1 on
# Cloud Run (in-process event bus, in-memory rate limits, per-instance SQLite). See docs/DEPLOY.md.

# --- Stage 1: build the pinned dependency set into a venv (the compiler stays in this stage) -----
FROM python:3.12-slim AS deps
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY backend/requirements/prod.txt /tmp/prod.txt
RUN pip install --no-cache-dir -r /tmp/prod.txt
# Pipecat downloads NLTK's punkt_tab tokenizer at import time; bake it in so a non-root container
# doesn't fail writing to $HOME and cold starts don't hit the network.
RUN python -c "import nltk; nltk.download('punkt_tab', download_dir='/opt/nltk_data', quiet=True)"

# --- Stage 2: runtime --------------------------------------------------------------------------
FROM python:3.12-slim

# Runtime libs only: libsndfile1 for soundfile, and the OpenGL/XCB libs OpenCV needs (pulled in by
# Pipecat's WebRTC transport).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libsndfile1 \
      libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY --from=deps /opt/venv /opt/venv
COPY --from=deps /opt/nltk_data /opt/nltk_data
ENV PATH=/opt/venv/bin:$PATH \
    NLTK_DATA=/opt/nltk_data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The app runs from source (not pip-installed): modules resolve data/ and frontend/ relative to their
# own file (REPO_ROOT = <file>.parents[3] = /app), so the repo layout is reproduced under /app.
COPY backend/app /app/backend/app
COPY backend/config.toml /app/backend/config.toml
COPY data /app/data
# Frontend assets main.py serves: the built React dashboard (/dashboard) and the voice demo (/demo).
COPY frontend/dashboard-app/dist /app/frontend/dashboard-app/dist
COPY frontend/index.html frontend/client.js /app/frontend/
COPY frontend/audio /app/frontend/audio

# The only writable path: the SQLite file. Ephemeral on Cloud Run — point DATABASE_URL at a managed
# DB (or mount a volume here) for persistence.
RUN mkdir -p /app/var && chown app:app /app/var

# ENVIRONMENT != development => operator routes fail closed (503) until DASHBOARD_PASSWORD is set.
ENV PORT=8080 \
    ENVIRONMENT=production \
    DATABASE_URL=sqlite:////app/var/sales_agent.db

USER app
WORKDIR /app/backend
# Create/heal the schema and upsert the fixed seed leads (idempotent: it only touches the seed
# lead_ids, never call data), then exec uvicorn so it receives SIGTERM directly.
CMD ["sh", "-c", "python -m app.db.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
