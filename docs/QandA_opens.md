# Q&A Content — Open Items (Needs Your Input)

The agent answers caller questions **only** from approved knowledge-base content (PRD
KB-1, KB-4): it must never invent prices, guarantees, tutor credentials, or policies. The
RAG pipeline (ingest + retrieval) is built and working, but the documents under
`data/kb/*.md` are **PLACEHOLDERS** I wrote — safe and non-committal, with all specifics
deliberately deferred to "a specialist." They are functional for the demo but are **not
approved Nerdy/Varsity Tutors content**.

**What I need from you:** approved copy for the items below. Drop it in the matching
`data/kb/*.md` file (or hand me the text and I'll place it), then remove that file's
`PLACEHOLDER` comment. Anything left as a placeholder, the agent will keep deferring to a
human rather than stating as fact.

## Priority 1 — caller will ask on most calls

| Topic | KB file | What's needed | Current behavior |
| --- | --- | --- | --- |
| ~~**Pricing**~~ ✅ PROVIDED | `pricing.md` | Operator-provided 2026-05-27: live tutoring is custom-quoted; Nerd AI app tiers quote exact figures. **Re-verify app figures periodically** (prices change); unrelated companies (NerdyData/Nerdio/Nerdy Form) excluded as non-VT products | Quotes Nerd AI app prices; live tutoring stays custom → specialist; refuses discounts |
| **Plans / commitment** | `pricing.md` | Whether live tutoring has a commitment, month-to-month, trial, etc. (Nerd AI tiers covered) | Defers commitment terms to specialist |
| **Refund / satisfaction policy** | `policies_and_compliance.md` | Exact refund or satisfaction-guarantee terms, if any | States nothing specific; defers |
| **Tutor matching & re-match** | `tutoring_formats_and_matching.md` | How matching works; can a student switch tutors, and any guarantee | General description; defers re-match specifics |
| **Scheduling / cancellation** | `scheduling.md` | Reschedule/cancellation deadlines and any fees | Says flexible; defers exact rules |

## Priority 2 — helpful for stronger calls

| Topic | KB file | What's needed |
| --- | --- | --- |
| **Offering / formats** | `offering_overview.md`, `tutoring_formats_and_matching.md` | Confirm subjects/tests covered, online vs in-person, group vs 1:1 |
| **Competitive comparison** | _(none yet)_ | Approved guidance on how to talk about Wyzant / local tutors / school support (KB-2 lists this; no doc yet) |
| **Tutor credentials/quality** | _(none yet)_ | Approved language on tutor vetting/qualifications (callers ask "how do I know the tutor is good?") |

## Objection rebuttals (P4-T3) — placeholders seeded, need approval

`data/playbooks/objections.yaml` now exists with **PLACEHOLDER** rebuttals for: `price`
(the §8 baseline), `discount` (high-risk → defers, no concession), `spouse`, `comparison`,
`tutor_quality`, and `tried_before`. They're consultative and avoid inventing prices/guarantees,
but the **wording needs your approval** — especially the **price baseline**, since Phase 7's
recursive-improvement loop will A/B-test variants against it. Please review/replace the
`rebuttal:` text in that file.

## Escalation / compliance

`policies_and_compliance.md` encodes the escalation triggers and prohibited-claims rules
(DE-4, §18). Please confirm these match Nerdy's actual policy — especially **what the agent
must never say** and **when it must hand off to a human**.

## How to verify after you provide content

1. Put approved text in the relevant `data/kb/*.md`, remove its `PLACEHOLDER` comment.
2. Re-run the retrieval tests: `cd backend && .venv/bin/python -m pytest tests/test_kb.py`.
3. Ask a sample question against the live agent and confirm the answer cites the right source
   and stays within approved bounds.
