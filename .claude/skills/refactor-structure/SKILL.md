---
name: refactor-structure
description: Reorganize Python files into clearer subfolders by responsibility, move modules safely, and update imports without changing underlying behavior
---

# Refactor Structure

Reorganize a Python codebase by grouping related functions and modules into logical subfolders, then update imports and references so behavior remains unchanged.

## Goal

Improve codebase organization and maintainability by:
- identifying logical groupings of Python files and functions
- proposing a clearer folder/module structure
- moving files into appropriate subfolders
- updating imports and module references
- preserving behavior exactly

This is a **structural refactor only**.

Do **not** change:
- business logic
- algorithms
- function behavior
- API contracts
- database behavior
- templates/frontend behavior
unless required only to preserve import correctness after moving files.

---

## Core Rules

1. **Behavior must not change**
   - No logic rewrites
   - No renaming unless explicitly required for import/path consistency
   - No opportunistic cleanup mixed into this task

2. **Prefer smallest safe moves**
   - Move only files that clearly belong together
   - Avoid broad reshuffles when a narrow structural improvement is sufficient

3. **Group by responsibility, not by vague preference**

   - routes/
   Flask request handlers only

   - providers/
   For quote retrieval

   - services/
   charm&vanna calculations
   gex calculations
   flow forecasting
   regime interpretation

   - repositories/
   datastore reads/writes

   - presenters/
   template payload building
   annotation arrays
   formatting for charts

   - utils/
   small pure helpers only

   - admin/

   - auth/

   The rule should be:
   services compute, repositories persist, presenters format, providers provide, 


4. **Update all imports**
   After any move:
   - update absolute imports
   - update relative imports
   - update dynamic imports if present
   - update references in entrypoints, tests, scripts, task runners, and config where needed

5. **Preserve public entrypoints**
   If external imports are likely to depend on current module paths, prefer one of:
   - moving only internals first
   - adding compatibility re-export shims if explicitly requested
   - documenting migration risk clearly

6. **Do not assume**
   Inspect actual usage before moving modules.

---

## When to Use

Use this skill when the task is to:
- reorganize a growing Python codebase
- split flat directories into subfolders
- group related files by purpose
- move modules without changing functionality
- clean up import structure safely

Do not use this skill for:
- major architecture rewrites
- converting sync to async
- redesigning APIs
- changing business logic
- broad class/function rewrites

---

## Required Workflow

### 1. Inspect the current structure
Read the relevant Python files and identify:
- major responsibility areas
- files that are tightly related
- files with mixed concerns
- import relationships
- likely shared utility modules
- entrypoints and modules with many dependents

### 2. Build a dependency-aware grouping plan
Before moving anything, define:
- current folders and problem areas
- proposed target structure
- which files will move
- why each move is justified
- which imports will need updates
- any risky/high-dependency modules

Write the plan to:
- `/docs/refactor_structure_plan.md`

### 3. Classify files by responsibility
For each candidate file, assign a primary responsibility such as:
- route/handler
- service/business logic
- repository/data access
- provider/integration
- calculations/domain logic
- utility/shared helper
- admin/internal tooling
- background task/cron
- model/schema/form

If a file contains multiple concerns:
- note it
- do not split it unless explicitly requested
- prefer moving the whole file first if safe

### 4. Propose the target structure
Prefer a structure that reflects actual responsibilities. Example:

project/
  app.py
  routes/
  services/
  repositories/
  providers/
  calculations/
  models/
  tasks/
  admin/
  utils/

  This is only an example. Reuse existing folders when possible.

### 5. Move files safely

For each approved move:

move the file to the new location
preserve file contents unless import/path edits are required
add __init__.py files where necessary


### 6. Update imports comprehensively

Update:

direct imports
from x import y
import x
relative imports
references from scripts and entrypoints
any string-based import paths if present

Be careful with:

circular imports
package-relative imports
Flask app imports
task/cron entrypoints
test imports


### 7. Validate

After moving files and updating imports:

search for stale import paths
run tests if present
run lint/type checks if already configured
perform at least basic import validation on changed modules


### 8. Summarize

Write a concise summary to:

/docs/refactor_structure_result.md

Include:

what moved
what imports changed
any compatibility risks
any files that should be split later but were intentionally left unchanged
Decision Rules for Grouping

Group files based on what they do most of the time.

Good grouping signals
imported together often
same external system or domain
same layer in architecture
same deployment/runtime purpose
similar naming and dependency patterns

## Warning signs
file imports from too many layers
file used everywhere
file contains unrelated helpers plus business logic
module acts as a dumping ground

## When uncertain:

prefer documenting ambiguity over making aggressive moves
Import Update Rules

## When updating imports:

Prefer the import style already dominant in the project
Keep imports explicit and readable
Avoid introducing new abstraction layers unless required
Do not rename imported symbols unless necessary
After edits, search globally for old module paths

## Checklist:

entrypoints still import correctly
Flask routes still register
background jobs still load
scripts still run
tests still discover modules
no stale paths remain
Output Files
/docs/refactor_structure_plan.md


# Refactor Structure Plan

## Objective
## Current Structure
## Pain Points
## Proposed Structure
## File Move Plan
## Import Update Plan
## Risks
## Validation Plan
## write output



# Refactor Structure Result
 
## Summary
## Files Moved
## Imports Updated
## Validation Performed
## Risks / Follow-ups

# Constraints
No logic changes
No behavior changes
No renaming for style only
No splitting files unless explicitly requested
No unrelated cleanup
No new patterns unless required for import/package correctness

# Preferred Working Style
Inspect first
Plan second
Move in small batches
Validate after each batch if practical
Keep changes minimal and traceable
Be explicit about uncertainty