# Kosmo

**Implementation Status:** Phase 1 (Foundations) and Phase 2 (Provider Configuration & Visual Editor) have been implemented and verified. The system is currently in a local development state (not deployed).

Kosmo is a platform for building, validating, and running workflows in a visual
way. Workflows can be deterministic or AI-assisted: nodes can delegate their
work to AI agents backed by different model providers. The project is in its
early stage; this document describes the intended product and the currently
agreed technical direction, not shipped functionality.

## Product overview

A workflow is a sequence of sequential or parallel steps. Each node in a
workflow performs an action: it receives a set of input artifacts, produces
output artifacts, and those outputs can feed other nodes. The editor is built
around a visual add-and-connect component model that is designed to be
extensible with new node types, including Python scripts, HTTP, AI, decisions,
and nested workflows. Feedback loops are supported in the product design and
must have a configured execution limit.

When a workflow is launched, the platform creates a **task**: a concrete,
materialized execution of that workflow. For example, given a workflow that
performs a security analysis of a repository, a task would be the execution of
that workflow for one specific repository.

## Core concepts

- **Workflow**: a versioned graph with exactly one start and one end node; the
  start node defines a dynamic input form. Only one version is *active* at a
  time, and activation is manual. Drafts can be saved in any state, but only
  error-free drafts can be tested or published. Tasks bind to the version
  selected at submission and keep it. The full versioning, concurrency, and
  publication rules live in the [product vision](docs/product-vision.md).
- **Node**: one step of a workflow. Nodes run sequentially or in parallel,
  exchange data through artifacts, and complete only after their declared
  outputs pass validation.
- **Phase**: a container grouping steps (nodes). Phases execute sequentially;
  steps inside them can run sequentially or in parallel according to the graph.
  Phases also simplify the editor and are distinct from Docker containers.
- **Artifact**: the input or output data of a node. Outputs of one node can be
  consumed by other nodes.
- **Task**: a concrete execution of a workflow, including its state and
  results.
- **Agent**: the executor of an AI-assisted node. An agent groups:
  1. Instructions describing its specialization and main assignment.
  2. The model and reasoning effort to use, selected from the AI providers
     configured in the platform.
  3. The list of MCP servers available to it.
  4. The list of skills available to it.

## Users, roles, and sharing

The platform will support English and Spanish from the first release, using
nested JSON translation catalogs for its interface and user-facing messages.

Kosmo targets both solo users and teams. The platform provides local
authentication with users, groups, and five roles: **viewers** (see permitted
tasks), **runners** (execute and view tasks), **builders** (CRUD on workflows,
agents, MCPs, skills, and extensions within their scope), **group managers**
(team-scoped platform configuration), and **admins**
(full control). A workflow can be public or restricted to specific users
and/or groups. Federated login (OIDC/OAuth) is a possible future extension,
not part of the initial scope.

## MVP scope

The first milestone is the workflow engine: create workflows visually,
validate them, and run the first execution end to end, including versioning
with a single active version per workflow. This includes deterministic and
AI-assisted nodes. The full product vision is being documented before its
implementation is phased; individual feature boundaries are not all settled.
The detailed feature breakdown will be specified in `docs/specs/` as
implementation work is planned.

## Broader product vision

- Platform-managed agents, MCP servers, skills, and configurable extensions
  such as Atlassian integrations, reusable from scripts and agents.
- GitHub/GitLab access through verified SSH/PAT configurations, with node-scoped
  repository permissions shared by Python operations and MCP tools.
- Applications grouping one or more repositories, with workflow-specific
  requirements for application/repository assignment.
- Artifacts validated by file format, applicable schemas, and Python business
  rules; scripts receive variables and agents receive mounts plus metadata.
- Interactive agent sessions and tasks that can wait for input, stop, resume,
  fail/retry, or finish and be cloned into an unsubmitted configuration.
- Sandboxed Python execution for scripts and validators, FIFO admission, and
  global limits for main tasks and live agents. Child workflows share their
  main task's admission slot; their agents still consume global agent capacity.
- Auditing of user-initiated create/modify/delete and lifecycle actions, context at
  general/workflow/application levels, and a system
  workflow that refreshes application documentation and selects relevant context.

See the [product vision](docs/product-vision.md) for detailed requirements,
open questions, and proposed phases. Temporal is the approved baseline for durable
execution, subject to a recovery proof of concept. Task checkpoint files will
retain completed node executions and validated artifact references for recovery.

## Technology stack

Agreed direction as of 2026-10-02:

- **Frontend** (`frontend/`): Vite, React, TypeScript, Tailwind CSS with
  shadcn/ui, React Flow for the graph editor, `material-symbols` (self-hosted Material Symbols Rounded for general UI icons) plus `@lobehub/icons` for AI/provider brand marks, TanStack Query, Zod, React
  Router, and an OpenAPI-generated API client (openapi-typescript +
  openapi-fetch), managed with pnpm. Includes Radix UI primitives for
  dropdowns, tooltips, and dialogs. Tests: Vitest with React Testing Library,
  Playwright for E2E. openapi-typescript generates types; openapi-fetch uses
  them for typed requests. Runtime validation remains a separate concern.
- **Backend** (`backend/`): FastAPI with uv, SQLAlchemy 2.0 (async) with
  Alembic on PostgreSQL, Pydantic v2 as the API contract, pytest for tests.
  AI-assisted nodes run through a provider integration layer: **OpenCode and
  Claude Code via the Agent Client Protocol (ACP)**, **Codex via its app
  server** — all adapted to a common internal model for events, responses, and
  sessions. Agents execute in **isolated Docker containers** with host access
  only through explicitly mounted volumes.
- **Infrastructure**: the whole application (frontend, backend, and
  PostgreSQL) runs under Docker Compose, including in development.
- **Layout**: a plain monorepo with `frontend/` and `backend/`; no additional
  monorepo tooling unless the project outgrows it.

Libraries beyond this stack (form helpers, mocking, component workshops, and
similar) are intentionally excluded for now and can be added when a concrete
need appears.

## Repository layout

```
frontend/   React SPA and visual workflow editor
backend/    FastAPI service, workflow engine, and persistence
docs/       Official project documentation and persistent agent context
AGENTS.md   Development workflow and agent responsibilities
```

## Quick start (Windows / Docker Desktop)

The whole stack — frontend, backend, worker, PostgreSQL, and Temporal — runs
under Docker Compose. Prerequisites on Windows:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with the
  WSL2 backend, running (allocate at least 4 GB RAM: PostgreSQL + Temporal +
  the app services need it).
- [`just`](https://github.com/casey/just) — `winget install Casey.Just`.
- [`uv`](https://docs.astral.sh/uv/) — `winget install astral-sh.uv` (runs
  backend tests on the host; the containers install their own dependencies).
- [pnpm](https://pnpm.io/) — for frontend management.
- [Git for Windows](https://git-scm.com/) — provides the `sh` that `just`
  uses on Windows (recipes avoid shell-only syntax, so PowerShell works too).

From the repository root:

```bash
just up            # boots frontend, backend, worker, postgres, temporal
just migrate       # apply Alembic migrations
just seed          # seed initial data
just test-backend  # run backend tests on host
just test-frontend # run frontend tests on host
just e2e           # run Playwright E2E tests
just build-sandbox  # build sandbox images
just build-opencode # build opencode images
just up-prod       # start production stack
just down          # stop the stack
```

**Critical Dependency (External):**
To enable real-agent execution, the following owner actions are required:
1. Upload `opencode.json` and (if necessary) `auth.json` via the `provider-config` API once the UI is available.
2. Alternatively, set the `OPENCODE_API_KEY` and associated configuration in the environment for the container.

Verify:

```bash
curl http://localhost:8000/healthz   # -> {"status":"ok"}
curl http://localhost:5173           # -> the SPA index page
```

Stop the stack with:

```bash
just down
```

`just down` removes containers but keeps named volumes (database data,
dependency caches). To reset everything, run `docker compose down -v`.

No `.env` file is required for `just up`: the compose file carries local
development defaults. Copy `.env.example` to `.env` only when running backend
processes directly on the host (tests, IDE debugging); `.env` is ignored by
git. Compose port mapping: 5173 (SPA), 8000 (API), 5432 (PostgreSQL),
7233 (Temporal frontend).

| Recipe | Purpose |
| --- | --- |
| `just up` | Start the full stack and wait for health checks. |
| `just down` | Stop the stack and remove containers. |
| `just logs [service...]` | Follow container logs, e.g. `just logs backend worker`. |
| `just migrate` | Run Alembic migrations in the backend container. |
| `just test-backend` | Run backend tests on the host with `uv`. |
| `just test-frontend` | Run frontend tests on the host with `pnpm`. |
| `just gen-client` | Regenerate the typed API client (placeholder until WP-06). |
| `just seed` | Seed initial data (placeholder until WP-05/WP-08). |

## Quick start (development)

Prerequisites: Docker Desktop, [just](https://github.com/casey/just), uv
(backend tests), pnpm (frontend tests). Windows-first, cross-platform commands.

```sh
just up            # boots frontend, backend, worker, postgres, temporal
just migrate       # apply Alembic migrations
just test-backend  # pytest via uv
just test-frontend # Vitest via pnpm
just down
```

In dev mode the backend runs with `--reload` and the frontend with the Vite dev
server (HMR): source changes are reflected live without recreating containers.

## Production mode

Built images, no bind mounts, no reload:

```sh
just down          # dev and prod share the kosmo-* container names
just build         # build production images
just up-prod       # start the stack in production mode
```

The frontend is served by nginx (static build) proxying `/api` to the backend
(SSE-safe: buffering off). Dev and prod keep the same `kosmo-*` container names
and the same volume data.

## Documentation

- [Product vision](docs/product-vision.md): full intended scope, unresolved
  semantics, and proposed implementation phases.
- [Architecture](docs/architecture.md): technical structure, execution design,
  and open architecture decisions (draft).
- [Phase 1 spec](docs/specs/phase-1-foundations.md): foundations and execution
  proof — stack, execution PoC, and acceptance criteria (approved 2026-09-30).
- [Execution orchestration assessment](docs/research/execution-orchestration.md):
  Temporal versus a custom engine, pending a decision.
- [Initial project context](docs/context/project.md): direction, confirmed
  decisions, and open questions.
- [Agent development instructions](AGENTS.md): coordinator workflow, work
  packages, specification-driven development, and test-driven development.

Official documentation lives in `docs/`, with persistent agent context in
`docs/context/`. Setup and usage instructions will be added when the
application scaffolding exists.
