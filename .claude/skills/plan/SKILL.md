---
name: plan
description: Convert /docs/spec.md into an execution-ready build plan with phases, tickets, dependencies, and status tracking
---

Plan this product strictly from the spec.

Input:
- /docs/spec.md (REQUIRED)
- /docs/ux.md (OPTIONAL, clarification only)

Write output to:
- /docs/BUILD_PLAN.md

Goal:
Translate the product spec into a durable, execution-ready build plan that can survive session resets and guide implementation one phase/ticket at a time.

---

## Task

1. Read /docs/spec.md carefully
2. Incorporate /docs/ux.md if present (ONLY for clarification, not scope expansion)
3. Extract:
   - core problem
   - scoped solution
   - acceptance criteria
   - non-goals
   - architecture constraints
4. Break the work into sequential phases
5. Break each phase into concrete tickets
6. Order tickets by dependency
7. Mark the recommended starting point
8. Write a durable status-tracking plan

---

## Required Output Format (/docs/BUILD_PLAN.md)

# Build Plan

## Project
- Name:
- Summary:

## Source of Truth
- Spec: /docs/spec.md
- UX: /docs/ux.md (if used)

## Planning Assumptions
- Minimal assumptions only
- Any ambiguities from spec

## Architecture Notes
- Stack assumptions from spec
- Important constraints
- Explicit non-goals that affect implementation

## Current Status
- Overall status: Not Started
- Current phase:
- Current ticket:
- Blockers: None

---

## Phase Breakdown

### Phase 1 — <name>
**Goal**
- What this phase delivers

**Exit Criteria**
- What must be true for this phase to be considered complete

**Tickets**
- P1-T1 — <ticket name>
  - Objective:
  - Files likely involved:
  - Depends on:
  - Acceptance criteria covered:
  - Status: Todo

- P1-T2 — <ticket name>
  - Objective:
  - Files likely involved:
  - Depends on:
  - Acceptance criteria covered:
  - Status: Todo

### Phase 2 — <name>
(same structure)

### Phase N — <name>
(same structure)

---

## Dependency Order
1. P1-T1
2. P1-T2
3. P2-T1
...

## Recommended Next Step
- Start with: <ticket id + name>
- Why this is first:

## Deferred / Out of Scope
- Items explicitly not included from spec non-goals
- Nice-to-haves not needed for MVP

## Update Rules
After each implementation pass:
- Update ticket status only as Todo / In Progress / Complete / Blocked
- Update Current Status
- Record blockers briefly
- Set the next recommended ticket
- Do NOT add new scope unless spec changes

---

## Rules

- Plan ONLY from /docs/spec.md
- Use /docs/ux.md only for clarification
- Do NOT expand product scope
- Keep phases incremental and independently testable
- Keep tickets small and implementation-ready
- Prefer the smallest viable sequence to a working product
- Do NOT rely on prior conversation
- Be explicit about dependencies
- Preserve traceability back to spec acceptance criteria

---

## Behavior

- If the spec already includes phases, refine them into execution-ready tickets
- If a build plan already exists, update it only if explicitly asked; otherwise create from scratch
- If the spec is unclear, make minimal assumptions and state them
- If the architecture is unspecified, choose the simplest reasonable path and label it as an assumption

---

After writing:
- Confirm file created: /docs/BUILD_PLAN.md
- STOP