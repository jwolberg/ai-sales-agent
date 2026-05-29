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
