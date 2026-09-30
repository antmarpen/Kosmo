# Kosmo Architecture

Status: Draft — intended architecture for the agreed product vision. Nothing here
is implemented yet; this document guides the first implementation packages.
Updated: 2026-09-30.

Requirements live in `docs/product-vision.md` (source of record). This document
defines the technical structure that satisfies them and records open architecture
decisions. Keep decided/proposed labels explicit.

## 1. Overview and principles

Kosmo is a monorepo with a React SPA frontend and a Python/FastAPI backend.
Users author workflow graphs visually, publish and activate versions, and launch
tasks that execute deterministic nodes and AI agents in isolated containers.

Principles:

- **The engine interprets graphs; users never author code.** A stable,
  code-defined interpreter executes validated graph definitions under Temporal.
- **Authoring references; execution snapshots.** Definitions (agents, MCPs,
  skills, extensions, repositories) are referenced by nodes; each task resolves
  and preserves an effective execution configuration at submission.
- **Isolation by default.** Agent runtimes and user Python run in containers;
  host access is only via explicitly mounted, task-scoped resources.
- **Explicit completion.** A node finishes only after its outputs pass
  validation; completion is recorded through a single checkpoint writer.
- **Localize from the start.** Platform-owned user-facing strings use namespaced
  translation keys with nested JSON catalogs (en/es) from the first release.

## 2. Repository and deployment layout

```
frontend/            Vite + React + TypeScript SPA
backend/
  app/               FastAPI service (API, domain services)
  worker/            Temporal worker process (workflow interpreter + activities)
  shared/            Pydantic models/contracts shared by app and worker
docs/                Official documentation (vision, architecture, research)
docker-compose.yml   Local orchestration of all services
```

Compose services (local development and the reference deployment):

| Service | Image/purpose |
| --- | --- |
| `frontend` | Built SPA served by a static server or Vite dev server. |
| `backend` | FastAPI API service. |
| `worker` | Temporal worker running workflow interpretation and activities. |
| `postgres` | Application database. |
| `temporal` | Temporal server (self-hosted) with its own schema/DB. |

The agent runtime containers (OpenCode/Claude/Codex) and sandbox containers are
created dynamically by the backend/worker through the Docker Engine API — they
are not compose services. All inter-service traffic for the core app stays on a
private compose network; agent/sandbox containers get a separate restricted
network policy per node.

## 3. Backend structure (modular monolith + worker)

One deployable API service plus Temporal workers. No microservice split until a
measured need appears.

Layering: **routers → application services (facades where useful) → domain
services → repositories (persistence)**. Dependencies point downward only:
routers never query the database directly, repositories never call routers.
Each layer is an implementation detail of its domain area; a facade exists only
where a router would otherwise orchestrate several services to complete one
use case. This layering keeps units small, testable, and replaceable without
monolithic manager classes.

```
backend/app/
  api/
    routes/        one module per API area; each exports `router`
    deps.py        shared FastAPI dependencies (auth, DB session)
    errors.py      KosmoError hierarchy + global exception handlers
  core/            config, settings, security (JWT/refresh), DB session setup
  domain/          one package per area (below)
    <area>/
      router.py    -> re-exported by api/routes/<area>.py (thin)
      service.py   application service / facade (use-case orchestration)
      models.py    SQLAlchemy models of the area
      repository.py persistence only (SQLAlchemy queries)
      schemas.py   Pydantic request/response contracts
  shared/          cross-area domain helpers (approval-checked)
backend/worker/
  workflows/       TaskWorkflow interpreter (Temporal workflow definitions)
  activities/      node execution, container ops, validation, checkpoint writer
  contracts.py     worker-side interfaces to domain services via shared/
backend/shared/    Pydantic contracts used by both processes (graph defs,
                   task state, artifact refs, error codes)
```

Convention details:

- **Dynamic router registration:** `api/routes/__init__.py` discovers sibling
  modules via `pkgutil`/`importlib` and registers any `router` attribute.
  Adding an API area = adding one route module; a convention test asserts every
  route module exports a router so discovery cannot fail silently.
- **Repositories own all persistence.** Domain services never build SQL inline.
  In-memory/fake repositories back unit tests of services.
- **Facades are optional and earned:** only when a use case needs multi-service
  orchestration. Do not create 1:1 pass-through facades.
- **No god classes:** services stay small and single-purpose; prefer functions
  and small classes over manager objects.

Domain areas (each maps to a `domain/<area>/` package):

| Area | Responsibility |
| --- | --- |
| Identity & access | Local users, groups, roles (viewer/runner/builder/group manager/admin), session auth. |
| Workflow authoring | Drafts, publication, versions, activation, revision checks, validation. |
| Task management | Submission, state machine, cloning, stop/resume/retry commands. |
| Scheduling & capacity | Global task/agent limits, FIFO admission, allocating states. |
| Execution orchestration | Temporal workflows/activities; graph interpretation; checkpoint writer. |
| Node execution | Script sandbox runner, HTTP runner, AI runtime adapters, dynamic child workflows. |
| Artifacts | Storage, manifests, iteration metadata, validation results, download/view endpoints. |
| Shared notes | Task-scoped note store with MCP exposure. |
| Repository service | Authorization-aware Git operations shared by Python bindings and MCP tools. |
| Configuration catalog | Agents, MCPs, skills, extensions/instances, repositories, applications. |
| Context | Context registry (general/workflow/application scopes); system workflow defs. |
| Audit | User-initiated CRUD/lifecycle recording via a shared service wrapper. |
| Localization | Message catalogs (en/es); key-based API error/message references. |

## 4. Data model (core entities)

PostgreSQL via SQLAlchemy 2.0 (async) with Alembic migrations. Indicative
entities, not a full schema:

- **Identity:** `users`, `groups`, `memberships`, `roles`, `sessions`.
- **Workflows:** `workflows`, `workflow_versions` (immutable published graphs),
  `workflow_drafts` (per-user, base_version, internal revision counter),
  `activations` (one active version per workflow).
- **Definitions:** `agents` (instructions, runtime, model+effort, MCP/skill lists),
  `mcp_servers`, `skills`, `extensions` + `extension_instances`
  (visibility personal/group/global), `repositories` (+verified credentials),
  `applications` (+ repository members).
- **Tasks:** `tasks` (state, workflow+version binding, resolved configuration
  snapshot, prompt/inputs), `task_checkpoint` metadata, `task_notes`
  (task-scoped, revisioned), `node_executions` (node, child invocation,
  iteration, attempt, state), `artifacts` (metadata + storage refs, iteration).
- **Execution:** `audit_log` (actor, action, entity, value delta), context
  registry tables (`context_items` with scope bindings).

Artifact content is stored on a persistent volume (filesystem) with metadata and
integrity hashes in PostgreSQL; the checkpoint file lives in the same task-owned
storage. **Proposal:** start with filesystem artifact storage; add object storage
only if a deployment target requires it. Credentials in integration/MCP/extension
configurations are stored encrypted with references (never in snapshots, notes,
artifacts, audit values, or logs); rotation/revocation semantics are open.

## 5. Execution architecture (Temporal)

Confirmed baseline: Temporal (self-hosted) with Python workers. Mapping:

- **One Kosmo task = one root Temporal workflow execution.** The root workflow
  runs the graph interpreter over the pinned workflow definition (published
  version or draft revision). Retry/resume create new runs of the same workflow
  ID family (run ID chain recorded in `node_executions`/task state).
- **The interpreter is deterministic code** that walks the graph: phases as
  sequential barriers, steps via graph dependencies, decision branches,
  joins, bounded feedback loops (phase loops re-execute the target phase with a
  new iteration), dynamic child workflows from generated definitions.
- **All side effects run in Activities:** container create/exec, script execution,
  validation, artifact persistence, checkpoint publication, MCP/adapter calls.
- **Human interaction** uses Signals/Updates: agent input requests surface as
  task `waiting for input`; responses are recorded durably (notes + event) before
  delivery. Voluntary stop is a Signal; the interpreter stops admitting new nodes
  and waits for the active node — except a node waiting for input, which is
  stopped immediately.
- **Nested/dynamic workflows** use Temporal Child Workflows (parent-close policy
  defined) executed by the same interpreter. Children share the root task's
  admission slot; their agent containers consume global agent capacity.
- **Checkpoint:** one writer Activity queue per task consumes completion records
  sequentially and publishes the checkpoint file atomically (temp file +
  atomic replace on the task storage volume). Completion records are emitted by
  the interpreter only after artifact validation and durable artifact persistence.
  Reconciliation rules with Temporal history are defined in
  `docs/research/execution-orchestration.md`; external side effects are out of
  scope per the vision.
- **Long agent sessions** stream events to the platform via runtime adapters;
  event persistence is bounded (state transitions and summaries, not full token
  streams) to keep execution histories manageable.

### Node execution services

| Node type | Execution |
| --- | --- |
| Script | Fresh sandbox container; artifacts mounted; integration/repo bindings injected as Python objects; timeout kills container → node failed. |
| HTTP | Backend Activity performs the request; outputs become artifacts. |
| AI | Agent container per execution; runtime adapter (ACP for OpenCode/Claude, Codex app server) bridges to the common internal model; validator MCP + notes MCP mounted; up to 3 failed completion validations → node failed. |
| Workflow | Invokes a predefined/system workflow or a generated definition (built from the work-package artifact); builder-configured agent/model/MCP/skills/validation apply to generated steps. |
| Decision | Runs in-process (deterministic or AI-backed per configuration); selects outgoing branch. |

Dynamic generated definitions: packages carry `id`, `instructions`, `depends_on`,
`inputs_from`. The parent Workflow node's configured output contract and
validation apply to all generated steps. Each agent execution receives the full
expected-artifact contract. The `artifacts` collection output (manifest with
source package/node, logical name, iteration, attempt, media type) is the stable
interface for parent graphs; latest valid output per logical artifact/producer
takes priority while history is preserved.

## 6. Containers, sandboxing, and secrets

- Agent runtime images per provider (OpenCode, Claude adapter, Codex) maintained
  in the repository; volumes limited to task workspace + declared artifacts.
- Script/validator sandboxes: one sandbox image with a curated Python
  environment. Network access is **per-node configuration** (`local` by default;
  `internet` enables outbound access for scripts/agents that need it), with
  read-only mounts except the node's output directory, CPU/memory limits, and
  timeout. Library allowlist/lockdown is decided during implementation.
- Agent containers likewise declare network scope per node: runtime API egress
  plus platform MCP endpoints always allowed; broad internet only when the
  node/workflow requests it.
- Containers run under per-node network policies: local-only by default, with
  internet egress as an explicit node/workflow configuration option; approved
  platform endpoints (runtime APIs, MCP endpoints) are always permitted.
- Secrets: encrypted at rest in PostgreSQL; resolved by the platform at
  container/Activity invocation; agents receive values only through their
  authorized integration bindings and notes retrieval.

## 7. Frontend architecture

- Vite + React + TypeScript; React Router for app routes.
- **Editor:** React Flow canvas; left catalog panel, center canvas, right
  properties panel (open on selection, closes on canvas click). Phases render as
  collapsible groups with visible cross-phase connections.
- **State:** TanStack Query for all server data; no global client store until a
  concrete need appears. Zod schemas validate API responses at the boundary.
- **API client:** generated by openapi-typescript from the FastAPI OpenAPI
  schema; openapi-fetch for typed calls. Regeneration is a build-time step.
- **Live updates:** SSE (Server-Sent Events). The backend pushes task and node
  state changes over a long-lived HTTP connection; the SPA applies them to
  detail views and task lists in real time (TanStack Query cache updates from
  the event stream). Auto-reconnect with polling fallback covers connection
  gaps. Final wire format defined in the first vertical slice.
- **Client-agnostic API contract:** the API serves browser and non-browser
  clients (a future CLI) identically. SSE endpoints must accept header-based
  JWT auth (not cookie-only) and honor `Last-Event-ID` reconnection; error and
  state contracts are already transport-agnostic.
- **WebSocket scope:** reserved exclusively for live bidirectional interaction
  with an agent session (chat with a running agent from its detail view).
  Task progress and lists use SSE; do not introduce WebSocket for them. The
  agent-session interaction contract, the task detail page, and the agent
  session detail page (UI + API) are not yet designed — deferred to a later
  spec, before phase 2's interactive session features.
- **Localization:** nested JSON catalogs per locale (en/es) with namespaced keys
  (`common.cancel`); a lightweight i18n runtime (e.g. i18next) selected during
  implementation. Backend returns stable message codes + parameters; the SPA
  renders localized text. User-authored content is never machine-translated.
- **Auth:** JWT-based. Short-lived access token + refresh token with automatic
  renewal; refresh tokens are rotated and persisted server-side (allowing
  revocation). Transport details (cookie vs. header) decided in the auth spec.
- **Testing:** Vitest + React Testing Library (unit/component), Playwright
  (E2E: authoring → publish → launch → execute → inspect results).
- **Frontend organization:** feature folders (`src/features/<area>/`) hold that
  area's components and hooks together; shared UI lives in `src/components/`
  (shadcn/ui base); the generated API client lives in `src/api/`. Lift code to
  shared folders only on second real use — no speculative abstraction.
- **Responsive/mobile-first:** all screens must be usable on small viewports
  (owner requirement); layout and components are built responsive from the
  start, not adapted later.

## 8. API and contracts

- REST over HTTP, OpenAPI-first from FastAPI. Resource families mirror domain
  areas: `/workflows`, `/tasks`, `/agents`, `/mcps`, `/skills`, `/extensions`,
  `/repositories`, `/applications`, `/notes`, `/context`, `/audit`.
- **Error model:** every platform error is a `KosmoError` carrying
  `message_key` + `params` (localizable short title), `details[]`
  (structured per-attempt causes, also keyed), and `internal`
  (stacktrace/technical context) that is **logged only, never returned** — in
  any environment. The global FastAPI exception handler maps `KosmoError` to
  the structured response `{ code, message_key, params, details[] }`; unexpected
  exceptions are wrapped into a generic internal error whose internals stay in
  logs. Small exception subclasses only set HTTP status/default code; no deep
  hierarchy.
- Error responses: stable machine-readable code + parameters + optional detail
  trail (e.g., three validation attempts with per-attempt causes). Localizable
  rendering happens client-side; server stores codes, not prose.
- State enums (`queued/pending`, `running`, `waiting_for_input`, `stopping`,
  `stopped`, `failed`, `success`, `allocating`) are language-independent
  identifiers; labels are translation keys.

## 9. Cross-cutting decisions

| Decision | Status |
| --- | --- |
| Execution engine | **Decided:** Temporal (self-hosted) + Python workers. PoC gate passed. |
| Artifact storage | **Decided:** filesystem volume + PostgreSQL metadata. |
| Live updates | **Decided:** Server-Sent Events (SSE) with polling fallback. |
| i18n runtime | **Decided:** i18next + react-i18next over nested JSON catalogs. |
| Checkpoint storage | **Decided:** task-owned persistent volume file, single writer, atomic replace. |
| External side effects | **Decided:** out of scope. |
| Auth mechanism | **Decided:** JWT (short-lived access + rotating refresh) + Argon2 hashing. |
| Sandbox network | **Decided:** Docker sandbox with per-node network scope. |
| CI/CD | **Decided:** GitHub Actions pipeline (backend+frontend+client-regen+compose-config) with PostgreSQL service for boundary tests. |
| Root task runner | **Decided:** `just` (cross-platform, no native shell dependency). |
| Version policy | **Decided:** latest stable major. Lockfiles committed. |
| TanStack Query | **Deferred:** using local state + refetch for MVP. |
| Human-answer delivery | **Deferred:** at-least-once delivery semantics. |
| Admission retry | **Deferred:** event-triggered admission retry only. |
| Temporal versioning | **Decided:** `temporalio/auto-setup` 1.29.7 is end-of-line; migration planned. |
| Agent egress filtering | **Deferred:** destination-level filtering is Phase 2. |
| Real-agent execution | **Blocked:** Requires `OPENCODE_API_KEY` and config upload (Owner action). |
| Workflow restart/replay | **Deferred:** restart-replay evidence deferred. |
| Hosted CI | **Pending:** first hosted CI run pending. |
| Drain/cancel semantics after child failure | **Open:** how running siblings behave when one branch fails. |
| Generated-graph promotion to reusable workflows | **Open** (future). |

## 10. Proof of concept (before full engine implementation)

Bound to the vision's phasing (phase 1: foundations and execution proof):

1. Temporal PoC in compose: worker restart recovery, human wait via
   Signal/Update, stop/resume, bounded loop, child workflow.
2. Checkpoint writer under concurrent completions; crash between artifact
   persistence and checkpoint publication converges without lost work.
3. One agent interaction end-to-end: container launch → adapter (ACP) →
   validator MCP → completion recording → checkpoint update.
4. Dynamic child workflow from a generated package list with `inputs_from`
   artifact handoff and collection output to the parent.

Exit criteria: recovery preserves committed work; no duplicated completions;
the adapter bridge handles a real OpenCode session round-trip.

## 11. Phase mapping (proposed, pending approval)

Matches `docs/product-vision.md` phasing:

1. **Foundations & execution proof:** compose stack, identity/auth skeleton,
   Temporal PoC above, artifact store + checkpoint writer, one deterministic
   node + one AI node. Output: reference security-analysis workflow skeleton
   executing end-to-end with a stub planner.
2. **First usable workflow path:** editor MVP (catalog/canvas/properties,
   drafts/publish/activate), validation, versioning, task lifecycle commands,
   notes, audit wrapper, localization scaffold, adapters for the three runtimes.
3. **Integration & lifecycle depth:** extensions/instances, repository service
   parity (Python + MCP), applications, dynamic child workflows with
   dependencies, capacity admission, full stop/resume/retry/clone.
4. **Context workflows:** context registry, refresh/select system workflows,
   documentation update workers via dynamic child workflows.
