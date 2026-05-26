---
name: refactor-architecture
description: Refactor large, mixed-responsibility Python/Flask files into clean, scalable architecture without changing behavior
---

Refactor the provided code to improve structure, separation of concerns, and extensibility while preserving all existing behavior.

This skill is optimized for codebases like Trading Volatility where:
- Flask handlers contain business logic
- Data retrieval, computation, and rendering are mixed
- Complexity is growing and needs structure

---

## Core Principles

1. **Do NOT change behavior**
   - No logic changes unless explicitly required
   - Output, API responses, and calculations must remain identical

2. **Refactor incrementally**
   - Do NOT rewrite entire systems
   - Extract and reorganize in small, verifiable steps

3. **Separate concerns strictly**
   Every piece of logic must belong to ONE of the following:

   - **Handler (routes/)**
     - HTTP only
     - request parsing
     - auth
     - calling services
     - returning responses

   - **Service (services/<feature>/)**
     - orchestration of a feature
     - coordinates data retrieval + computation
     - no Flask objects

   - **Domain / Logic (services/<feature>/logic/)**
     - pure computation
     - no I/O, no DB, no request context

   - **Repository (repositories/)**
     - all datastore access
     - queries and writes only
     - no business logic

   - **Presenter / ViewModel (services/<feature>/presenter/)**
     - formatting for templates / charts
     - strings, labels, annotations

4. **Prefer pure functions**
   - Input → Output only
   - No hidden dependencies
   - No global state

5. **Eliminate duplication aggressively**
   - If logic appears more than once → extract it

---

## Target Architecture Pattern

- routes/
   Flask request handlers only

   - providers/
   For quote retrieval

   - services/
   charm & vanna calculations
   gex calculations
   flow forecasting
   regime interpretation

   - helpers
   strike ranking
   hedge direction strings

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

---

### Step 3: Extract Repositories

Replace direct model queries with functions:

Instead of:

TickerSnapshot.query(...)


Create:

get_latest_ticker_snapshot(ticker)


Rules:
- Only DB logic here
- No transformations
- Return raw or lightly structured data

---

### Step 4: Create Service Layer

Move orchestration into a service:


CharmPageService.build_page_data(...)


Responsibilities:
- call repositories
- call logic functions
- assemble result

Must NOT:
- access request directly
- render templates
- write responses

---

### Step 5: Simplify Handler

Refactor handler to:


parse request
authenticate
call service
render template


Nothing else.

---

### Step 6: Extract Forecasting Separately

Large, complex logic (like IV forecasting, flow simulation) must go into:


logic/forecast.py


This is critical for future extensibility.

---

### Step 7: Replace Dicts with Structured Objects

If large dicts exist (e.g. gex_data), convert to:


@dataclass
class GexContext:
...


Rules:
- No magic keys
- Explicit fields
- Safe defaults

---

### Step 8: Preserve Interfaces

Do NOT break:
- template variable names
- API responses
- existing routes

Adapters may be used if needed.

---

## Anti-Patterns to Eliminate

❌ Handler doing calculations  
❌ Handler querying database directly  
❌ Same logic duplicated in multiple places  
❌ Large mutable dictionaries passed everywhere  
❌ Hidden dependencies (memcache, globals inside logic)  
❌ Mixing real-time retrieval with stored data logic  
❌ Combining page rendering and cron/job behavior  

---

## Output Requirements

When applying this skill:

1. Provide a **refactor plan**
2. Show **new file structure**
3. Provide **extracted functions/modules**
4. Show **before → after flow**
5. Ensure **no behavior change**

---

## Optional Enhancements (only if safe)

- Introduce dataclasses for structured data
- Add type hints
- Add small helper utilities
- Improve naming clarity

DO NOT:
- Introduce new frameworks
- Change business logic
- Optimize prematurely

---

## Success Criteria

Refactor is successful if:

- Handler is < 100 lines and readable
- Logic is reusable across features
- New features can be added without touching handler
- Data retrieval is centralized
- Calculations are testable in isolation

---

## Mental Model

Treat the system like a trading pipeline:

- **Repositories** = data feeds  
- **Services** = strategy engine  
- **Logic** = math/model layer  
- **Presenter** = chart output  
- **Handler** = UI adapter  

---

## Example Invocation

"Refactor this file using the refactor-architecture skill. Extract pure logic, create service + repository layers, and preserve behavior exactly. Output the new structure and code."

---