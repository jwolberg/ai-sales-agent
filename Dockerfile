# Core backend image (no voice extra — the live voice path needs WebRTC + a browser/mic and is
# run locally; the container serves the API, dashboard, benchmark, and intent-router brain).
# One-command run target for the GCP Cloud Run deploy (R13).
FROM python:3.11-slim

WORKDIR /app

# App reads data/ via REPO_ROOT = <file>.parents[3], i.e. /app — so backend/ and data/ sit here.
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
COPY data /app/data

RUN pip install --no-cache-dir -e /app/backend

ENV PORT=8080
WORKDIR /app/backend
# Create the schema on boot, then serve. SQLite file lives in the container (ephemeral on Cloud
# Run); point DATABASE_URL at a managed DB for persistence.
CMD ["sh", "-c", "python -m app.db.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
