# Phase 1 — Foundations and Execution Proof

Status: Approved (2026-09-30)
Date: 2026-09-30

Implements phase 1 of `docs/product-vision.md` (§13) and the proof of concept
defined in `docs/architecture.md` (§10). Requirements source: product vision;
technical structure: architecture draft. Both are prerequisite reading.

## Problem and intended users

Kosmo has no implementation yet. Before any user-facing feature can be built,
the project needs a runnable skeleton that proves the riskiest technical
decisions: Temporal-based durable execution, isolated agent execution through
its runtime adapter, and recovery of committed work. This phase creates that
foundation for the builder (the owner and builders in phase 2).

## Goals

1. Run the full stack locally with Docker Compose: frontend, backend API,
   Temporal worker, PostgreSQL, Temporal server.
2. Execute one workflow end to end: submit → schedule → run one script node and
   one AI node → validate outputs → persist artifacts → complete.
3. Prove recovery: worker restart and crash between artifact persistence and
   checkpoint publication preserve committed work without duplicating it.
4. Prove one agent interaction round-trip through the adapter layer with a real
   runtime (OpenCode via ACP).
5. Stand up the conventions everything else builds on: layered backend
   (routes/services/repositories), dynamic router registration, `KosmoError`
   error model, JWT auth skeleton, localization scaffold (en/es), base CI.

## Non-goals

- Visual workflow editor (phase 2).
- Full workflow authoring/versioning UI and publication rules (phase 2;
  phase 1 uses seeded/published definitions created programmatically).
- Extensions, repository integrations, applications, shared notes UI, context
  system (later phases).
- Stop/resume/retry/clone UX beyond what the PoC requires.
- Claude/Codex adapters (validated in phase 2; the adapter interface is built
  and exercised with OpenCode here).
- Production deployment, monitoring, multi-host concerns.

## Expected behavior

### Stack and scaffolding

- Monorepo with `frontend/` (Vite + React + TypeScript, pnpm) and `backend/`
  (FastAPI app + Temporal worker, uv; Python 3.14 line; latest stable majors
  per the architecture version policy).
- Root task runner (`justfile`, cross-platform) wraps: compose up/down,
  migrations, backend tests, frontend tests, API client generation.
- `docker-compose.yml` runs: frontend, backend, worker, postgres, temporal.
  `just up` produces a working system from a clean clone (README documents it).
- Frontend ships a minimal shell: app frame, i18n en/es catalogs with nested
  keys, language switcher, login page. No workflow editor in this phase.

### Identity and access (skeleton)

- Local auth: register is seeded/admin-created; login issues JWT access token
  (short-lived) + rotating refresh token with automatic renewal; logout revokes.
- Roles exist in the data model (viewer/runner/builder/group manager/admin),
  enforced on API endpoints; phase 1 seeds one admin user and one test runner.
- Session/JWT details follow the architecture: transport finalized in this
  phase's implementation and recorded in the architecture decisions table.

### Workflow definition (programmatic, minimal)

- Graph definition schema implemented as versioned Pydantic contracts in
  `backend/shared/`: nodes (start/end/script/http/ai minimal shapes), edges,
  input form on the start node, phase grouping optional (flat graph = one
  implicit phase), bounded-loop fields (max iterations) present in schema.
- A seed script publishes a "reference" workflow: start → (script: compute
  artifact) → (ai: transform artifact) → end, with declared artifacts and
  three-level validation metadata on the AI node's output.
- Validation on save/publish (server-side): graph references, start/end
  presence, artifact contract references. Errors surface as structured
  `KosmoError` responses (message_key + details).

### Task execution

- Submitting a task (via API for this phase) binds it to the seeded published
  workflow version, stores the prompt/input-form values, and creates the task
  in `queued` state.
- Temporal root workflow interprets the graph: start node passes its resolved
  input to downstream nodes; script node runs in a Docker sandbox container
  (local network scope) with declared artifacts mounted and results written to
  its output directory; AI node launches the configured agent runtime in its
  container, with the complete expected-artifact contract and platform MCP
  endpoints (validator) available.
- Node completion requires validation; deterministic nodes failing validation
  fail immediately; AI nodes get up to 3 completion-validation cycles with
  errors reported back through the adapter (title/detail structure).
- Artifacts persist to the task storage volume; metadata lands in PostgreSQL
  with provenance (node, iteration, attempt) and integrity hashes.
- Task checkpoint: single writer per task consumes queued completion records
  and atomically updates the checkpoint file after validation + artifact
  persistence. Completed nodes are never re-executed on recovery/retry.
- Task states implemented: `queued`, `running`, `allocating` (agent capacity
  FIFO), `failed`, `success` — plus stop semantics for the PoC path
  (`stopping`/`stopped` including the waiting-for-input exception).
- Global capacity limits (max main tasks, max agents) enforced as configured
  settings; defaults small.

### Agent interaction proof

- Adapter interface + OpenCode ACP adapter: container launch, session start,
  prompt delivery, event normalization to the internal model, completion
  request, validation feedback loop, artifact retrieval from mounted output.
- One human-input round trip is exercised in the PoC scenario: the AI node's
  agent asks for input via the adapter; the task enters `waiting for input`;
  an API response resumes it (proves Signal/Update wiring + durable wait).
- Live updates: SSE stream pushes task/node state changes; the task detail and
  list views update in real time (polling fallback on reconnect).

### Observability and errors

- Structured logging (JSON) in backend/worker; stacktraces logged server-side,
  never returned. User-facing errors follow the `KosmoError` contract
  (code/message_key/params/details); localized via frontend catalogs.

## Constraints

- Latest stable majors per architecture policy; lockfiles committed.
- No external side-effect interception (out of scope per vision).
- No secrets in code, logs, or documentation; sandbox has no internet egress
  in this phase unless a node requests it (agent runtime needs API egress).
- Windows-first development (Docker Desktop); deployment stays Compose.
- **Responsive UI:** the frontend is designed responsive with mobile support
  as a first-class constraint. All screens (shell, login, task views) must be
  usable on small viewports; Playwright/component checks include a mobile
  viewport where relevant.
- Conventions per architecture §3: layered backend, repositories own
  persistence, facades only for multi-service use cases, feature-folder
  frontend.

## Acceptance criteria

- AC-01: From a clean clone, `just up` starts the whole stack; the README quick
  start works on Windows with Docker Desktop; the SPA loads and shows the login
  page in English and Spanish (language switcher works).
- AC-02: Logging in with the seeded admin returns access+refresh tokens;
  the SPA silently refreshes an expired access token; logout revokes the
  refresh token so the next refresh attempt fails.
- AC-03: A runner can submit a task for the seeded workflow via the API with
  input-form values; the task passes `queued` → `running` and executes the
  script node in an isolated sandbox container (no internet by default).
- AC-04: The AI node launches an OpenCode agent via ACP; the agent produces the
  declared output artifact inside its container; the artifact is validated
  (three levels), persisted with provenance, and viewable/downloadable through
  the API subject to task permissions.
- AC-05: When the agent's output fails validation, the task notes show up to 3
  correction cycles; after the third failed validation the node and task fail
  with a structured error: short cause + per-attempt detail trail, no stacktrace.
- AC-06: An agent input request flips the task to `waiting_for_input`; after
  answering via the API, execution resumes and the answer is durably recorded
  (survives a worker restart before delivery).
- AC-07: Killing the worker mid-execution and restarting it (or retrying a
  failed task) does not re-execute nodes recorded in the checkpoint; concurrent
  completions do not lose checkpoint entries; a crash between artifact
  persistence and checkpoint publication converges on recovery.
- AC-08: Task detail and task list views update in real time via SSE without
  manual refresh; state changes render localized labels in en/es.
- AC-09: Exceeding the global max-task limit queues the task (`queued`); an
  agent node without agent capacity stays `allocating`; admission is FIFO.
- AC-10: Adding a new route module to `api/routes/` is automatically registered;
  a convention test fails if a module lacks its `router` export. Backend test
  suite covers services with fake repositories; CI runs backend tests, frontend
  tests, and client regeneration check on push.

## Open questions (non-blocking; resolved during implementation and recorded)

- Exact SSE event wire format and React integration pattern (first slice).
- JWT transport final choice (cookie vs Authorization header) — recorded in the
  architecture decisions table when implemented.
- Sandbox image contents and Python library set (curated minimal set).
- Temporal namespace/task-queue naming and compose resource sizes.

## Decisions and approval

- **Approved by the owner on 2026-09-30** with the goals and acceptance
  criteria above; all non-goals excluded. The scope approved is exactly this
  spec; the architecture draft (`docs/architecture.md`) is the technical
  reference for implementation.
- On approval, the coordinator hands this spec to the `architect` for work
  packages (phase ordering: scaffolding → auth skeleton → graph schema/seed →
  script node E2E → checkpoint/recovery → AI node + adapter → SSE + UI shell).
- Rejected earlier alternatives remain documented in the vision and research
  docs; this spec does not reopen decided items.
