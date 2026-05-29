# Voice-enabled backend image: API + dashboard + intent-router brain + benchmark, PLUS the realtime
# voice extra (Pipecat: Deepgram STT + Cartesia TTS + WebRTC/Twilio Media Streams) so the in-dashboard
# Test Call and Twilio phone path work on the deployed container. Run with --max-instances 1 on
# Cloud Run (in-process event bus + per-instance SQLite). See docs/DEPLOY.md.
FROM python:3.11-slim

WORKDIR /app

# System libs the voice extra needs: build tools for any sdists (purged below), libsndfile1 for
# soundfile, and the OpenGL/XCB runtime libs OpenCV needs (pulled in by Pipecat's WebRTC transport).
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libsndfile1 \
      libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# App reads data/ via REPO_ROOT = <file>.parents[3], i.e. /app — so backend/ and data/ sit here.
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
COPY data /app/data

# Install with the voice extra, then drop the compiler to keep the image smaller (wheels are built).
RUN pip install --no-cache-dir -e "/app/backend[voice]" \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y

ENV PORT=8080
WORKDIR /app/backend
# Create the schema on boot, then serve. SQLite file lives in the container (ephemeral on Cloud
# Run); point DATABASE_URL at a managed DB for persistence.
CMD ["sh", "-c", "python -m app.db.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
