# PII-Substituted Sales Transcripts

This directory holds the small database of **PII-substituted** historical sales
transcripts referenced in the PRD (Recursive Improvement Requirement, §13.1). They are
used to refine likely prospect personas and ground the agent — they are **not** real
customer data and must never contain real PII.

These transcripts have not been provided yet. The loader stub in
`backend/app/db/seed.py` (`load_transcripts`) scans this directory for `*.json` files and
returns an empty list when none are present, so the rest of the pipeline runs regardless.

## Expected format

One JSON file per transcript (or a JSON array of transcript objects):

```json
{
  "transcript_id": "t-0001",
  "channel": "phone",
  "is_synthetic": false,
  "pii_substituted": true,
  "turns": [
    { "speaker": "agent", "text": "Thanks for calling — who am I speaking with today?" },
    { "speaker": "prospect", "text": "Hi, I'm looking for help with my son's algebra." }
  ]
}
```

`pii_substituted: true` is required — the loader will refuse files that are not marked as
substituted, to avoid ingesting raw PII.
