# Kosmo — Initial Project Context

## Purpose of this document

This is the initial persistent context for Kosmo. It records the owner's stated
intent and confirmed decisions so future agents can resume work without relying
on earlier conversations. Update it as the product and implementation evolve.

## Current state

Kosmo has successfully completed the Phase 1 — Foundations and Execution Proof milestone. The implementation is verified and stable on local development environments (Windows/Docker Desktop).

### Implemented and Verified (Phase 1 Foundations)
- **Full Compose Stack:** integrated orchestration of `frontend`, `backend`, `worker`, `postgres`, and `temporal` services.
- **Identity & Access:** JWT-based authentication with rotating refresh tokens and full family-based revocation.
- **Workflow Engine:** versioned schema v1 with server-side validation (Pydantic), publication, and activation mechanisms.
- **Task Lifecycle:** robust state machine (`queued`, `running`, `waiting_for_input`, `stopping`, `stopped`, `failed`, `success`, `allocating`).
- **Temporal Interpreter:** deterministic graph walking with a real Temporal-backed runtime, including task-scoped checkpointing (single-writer/reconciliation).
- **Execution Sandbox:** isolated Docker container execution for script nodes with defined artifact mounting/lifecycle.
- **Agent Adapter:** OpenCode ACP adapter implementation providing a bridge for agent interaction.
- **Validator MCP:** server-side and agent-side validation services for workflow integrity and artifact contracts.
- **Human Interaction:** secure, durable Signal/Update-based human input and task-stop semantics.
- **Observability & Real-time:** SSE-based task/node state streaming with safe-DTO filtering for visibility control.
- **Configuration & Storage:** encrypted `provider-config` store with personal/group/global scoping; artifact persistence on filesystem with PostgreSQL metadata.
- **Localization:** i18n support for English (`en`) and Spanish (`es`) using nested JSON catalogs.
- **Continuous Integration:** GitHub Actions pipeline covering backend, frontend, client-regen, and compose-config, using a dedicated PostgreSQL service for boundary testing.

### Implemented and Verified (Phase 2)

- **Provider Configuration UI & Visual Workflow Editor (Blocks A + C)**:
  - Implemented and verified in the local compose environment.
  - Key constraints:
    - Providers store no model (selection is for verification only).
    - Mandatory user-entered display name.
    - Mandatory connection verification via real container test.
    - Per-user workflow drafts with optimistic revisions.
    - Publication without auto-activation + explicit activation.
    - 5-minute recent-publication confirmation.
    - Scoped provider visibility (personal, group, or global).
    - Credential and configuration contents are hidden from non-owners.
- **Workflow Editor Round-2 Validation & AR3 Remediation**:
  - **Per-output Validation Contract**: Discriminated by `format` (`text`/`markdown` parse-only; `json` with JSON Schema Draft 2020-12 + optional Python rules; `yaml` with standard YAML + optional Python rules). No "automatic" validation.
  - **Python Rules**: Run as function bodies in an isolated sandbox (non-root, no network, read-only rootfs, resource limits); failures fail closed; blocking semantics (a failed configured check blocks persistence/checkpoints).
  - **Start Inputs**: Validated at submission and at execution; typed numeric/boolean values validated.
  - **Validation Infrastructure**: Shared async validation gateway with a worker probe; API has no Docker-socket access.
  - **Legacy `levels` Compatibility**: Isolated and non-destructive (no rewriting of published versions/task snapshots/checkpoints); reference seed uses the canonical contract.
  - **AR3 Remediation**: Canonical `rules_code` dispatch; rule sandbox staged on the shared task-storage volume (works from the Compose worker); boolean JSON schemas honored/preserved; new error `workflow.agent.model_default_unavailable` and runtime default-model resolution.
  - **Verification State**: Backend 412 passed / 49 skipped; frontend 350 passed; build green; E2E 14 passed / 2 skipped (the credential-gated real-model journey and an AI-failure journey whose premise did not materialize are documented skips).
  - **AR3 Sign-off**: architecture review APPROVED; AR3-01/02/03/04/06 resolved and AR3-05 (Temporal input secrecy) proven with its behavioral test. A Linux-only latent flake in `backend/tests/worker/test_script_runner.py` (the symlink-rejection test used an undefined `result`) was fixed; the symlink branch passes in the Linux container.
- **Provider Instance Management (P2-09)**:
  - Implemented and verified in the local compose environment.
  - Key constraints:
    - Providers store no model (selection is for verification only).
    - Mandatory user-entered display name.
    - Mandatory connection verification via real container test.
    - Per-user workflow drafts with optimistic revisions.
    - Publication without auto-activation + explicit activation.
    - 5-minute recent-publication confirmation.
    - Scoped provider visibility (personal, group, or global).
    - Credential and configuration contents are hidden from non-owners.

### UI conventions
- **Modals/dialogs never render a "Cancel" button.** Dismissal is the shared top-right close "X" (localized `common.close`). Confirmation and destructive dialogs show only their primary action (e.g. the styled `ConfirmDialog`). This applies to all existing and future modals.

### Agent, MCP server, and Skill Catalogs & OpenCode 2 Runtime (2026-10-04)
- **Feature:** First-class, scoped Agent, MCP server, and Skill catalogs with visibility mirroring provider configurations (personal/group/global).
- **AI Node:** Reference-only AI node that selects an agent and inherits its model, reasoning effort, MCP servers, and skills, with node-level overrides allowed.
- **Runtime:** OpenCode 2 runtime upgrade (`@opencode/cli@2.0.22`) with provider v2 auth bootstrap (the v2 `Credential.Value` API-key discriminator is `type:"key"`).
- **Capability:** Reasoning effort (`effort`) support (D5).
- **Migrations:** `0022_agent_catalogs`, `0023_provider_runtime_format`, `0024_provider_runtime_v2`, `0025_agent_reference_reset`.
- **Verification State (Reported):**
  - Backend: 482 passed / 62 skipped / 0 failed.
  - Frontend: 507 passed; build green.
  - v2 runtime auth + reasoning proven end-to-end.
  - D9: 12 passed.
  - Visibility: 9 passed (in-container).
- **Accepted Residuals:**
  - **WP-R2: RESOLVED** — `backend/tests/worker/test_secret_boundary_temporal.py` (opt-in) runs the production resolver + real v2 bootstrap under a Temporal workflow with a fixture MCP receiver; the sentinel reaches the runtime but is absent from the recorded history, the activity result and the safe DTO.
  - **WP-R3:** Partial coverage for central-edit/live-execution and long-name browser interaction.

### UI Refresh Implementation (2026-10-02)
- Local Material Symbols Rounded for general UI icons; bundle size optimization remains a future consideration.
- Pill-shaped action buttons, medium-rounded surfaces, and consistent pointers;
  user-initial dropdown in the shell.
- Generic Add actions (`common.add` shared key) for providers, workflows, and
  tasks; shared `RowActions` for workflow/task rows.
- Loading state support for shared Buttons.
- Styled confirmation dialogs and tooltips.
- Spanish (`es`) catalog repaired and synchronized.
- **DONE:** Provider instance management (P2-09) is now implemented.

### Implementation Caveats & Residuals

- **AR3-05 (Temporal Integration): PROVEN and signed off.** Task inputs are resolved opaquely inside activities under the `opaque-task-inputs-v1` Temporal patch gate; the starter no longer carries input values and schema diagnostics no longer echo candidate values. The behavioral proof (`backend/tests/worker/test_task_input_secrecy.py`) passes in the in-process Temporal test server inside the backend container: the sentinel is absent from workflow/activity arguments and the recorded history, and a recorded history replays. The tests are opt-in (`KOSMO_TEMPORAL_INTEGRATION=1`) because the test server can hang on a bare Windows host. **Accepted residuals:** the explicit pre-patch legacy branch is not crafted by a test (only newly recorded history is replayed); substitute activities are not a full production database/executor secrecy test; existing histories are not retroactively sanitized.

### Outstanding Live Proofs & Phase 2 Roadmap

The following items are part of the next development cycle:
- **Agent & Provider Evolution:** Claude and Codex implementation/adapters.
- **Agent Egress Filtering:** Implementing destination-level egress filtering for agent nodes.
- **Frontend Evolution:** TanStack Query migration.
- **Interaction Depth:** Human-input restart/replay, delivery idempotency evidence, and scheduling/start-retry reconciliation.
- **Platform Features:** Notes/audit UI, Applications, and production deployment.
- **Open Decision #11:** Workflow visibility and ownership model.

## Operational Constraints

- **Worker Reloading:** The worker does not hot-reload; a restart is required after changes to worker modules.
- **Dependency Management:**
  - New backend dependencies require `uv sync` within the container.
  - New frontend dependencies require `pnpm install` within the container.

## Confirmed direction

- Use a single monorepo for frontend and backend.
- Build the frontend with React and the backend with Python.
- Keep official project documentation in `docs/` and durable agent context in
  `docs/context/`.
- Use English for all project files, filenames, documentation, code identifiers,
  comments, and agent deliverables; communicate with the owner in Spanish.
- Product localization (2026-09-30): support English (`en`) and Spanish (`es`)
  from the start through nested JSON translation catalogs, for example
  `{ "common": { "cancel": "Cancel" } }` in English and the same structure
  with `Cancelar` in Spanish. The lookup path is `common.cancel`, not a literal
  dotted JSON key. Platform UI and user-facing errors
  must be localizable; stable message identifiers and parameters remain separate
  from rendered text. Locale selection/fallback and the i18n library are pending.
  Translated catalog values are an intentional exception to English-only file
  content; user and agent content is not automatically translated.
- Let the user work through a main coordinator agent.
- Have the coordinator execute simple tasks directly and delegate substantial
  or complex tasks through an architect.
- Use specification-driven development (SDD) and test-driven development (TDD).
- For high-complexity work, have the coordinator agree on a spec with the user
  before the architect plans implementation.
- Have the architect create small development, design, and test packages that
  lighter execution models can handle reliably.
- Require the architect to review the integrated result against the spec, good
  practices, and project design before the documentator updates documentation.
- Product (2026-09-30): workflow platform as described in `README.md` — visual
  workflow editor with extensible nodes, artifact-based data flow, tasks as
  materialized executions, AI-assisted nodes backed by agents (instructions,
  model and reasoning effort, MCP servers, skills), and versioned workflows
  with one active version.
- Stack (2026-09-30): frontend with Vite + React + TypeScript, Tailwind CSS +
  shadcn/ui, React Flow, `material-symbols` (self-hosted Material Symbols Rounded for general UI icons) plus `@lobehub/icons` for AI/provider brand marks, TanStack Query,
  Zod, React Router, and openapi-typescript + openapi-fetch; backend with
  FastAPI + uv, SQLAlchemy 2.0 async + Alembic on PostgreSQL, Pydantic v2,
  pytest; pnpm manages frontend dependencies. The whole app runs under Docker Compose in a `frontend/` + `backend/`
  monorepo. Frontend tests: Vitest + React Testing Library, Playwright for E2E.
- Provider integration (2026-09-30): agents integrate through a common
  internal model that homogenizes events, responses, and session interaction;
  each provider has its own parser/adapter to that model. **OpenCode** speaks
  ACP natively (`opencode acp`), **Claude Code** connects through an ACP
  adapter, and **Codex** connects through the **Codex app server** (not ACP).
  Sessions support user-initiated messages and agent-initiated requests for
  user input; an agent input request puts the task into a "needs human
  attention" state until the user responds.
- Agent isolation (2026-09-30): AI agents execute inside **Docker containers**
  to restrict access to the host. Containers get access only to what a node
  explicitly needs, mounted as volumes. This is a security requirement, not a
  convenience; agent-container configuration (images, mounts, limits, network)
  is part of the architecture.
- MVP scope (2026-09-30): the first milestone includes both deterministic and
  AI-assisted nodes — the workflow engine, the visual editor, validation, task
  execution, and agent-backed nodes via the three provider adapters above
  (ACP for OpenCode/Claude, app server for Codex).
- Provider configuration (2026-09-30): agent runtime credentials are NOT
  managed via platform env vars (e.g., no OPENCODE_API_KEY). Per provider, the
  user uploads runtime configuration files (OpenCode: `opencode.json`, and
  optionally `auth.json` when credentials are separate) through the platform;
  they are stored encrypted and injected into the agent container at session
  creation. One provider at a time will be onboarded. This is the first
  instance of the extensions/instances configuration pattern. UI upload may
  land with the configuration catalog; the minimum viable path is an
  authenticated encrypted store + injection at container creation.
- Deliberately excluded for now: React Hook Form, MSW, Storybook, pre-commit,
  Biome, structlog, and Turborepo/Nx. Temporal is approved as the execution
  architecture baseline, subject to a recovery/agent-interaction proof of concept.
- Recovery checkpoints (2026-09-30): atomically update a task checkpoint file
  recording completed executions after output validation and durable artifact
  persistence. Resume/retry preserve those completions. Exactly one writer per
  task serializes queued node completion records and atomically updates the file.
  Durable queue replay, deduplication, writer replacement, and Temporal/checkpoint
  reconciliation remain architecture work.
- External effects (2026-09-30): out of scope. Nodes and agents may perform
  external operations without platform recording, interception, or recovery
  mechanisms; failures or repeats are resolved outside the platform. Revisit
  only if recovery requirements change. See `docs/product-vision.md`.
- Expanded vision (2026-09-30): configuration and extensions, scoped repository
  operations shared between Python and MCP, CRUD audit, bounded graph cycles,
  three-level artifact validation, agent inheritance/overrides, task lifecycle,
  nested workflows, applications, and context curation/refresh are captured in
  `docs/product-vision.md`. Proposed phases there are not yet approved.
- Workflow publication (2026-09-30): `draft` saves do not increment published
  versions; publishing changes creates a new version automatically. Tasks bind
  to a workflow/version at submission and retain it in the queue and during
  execution. Saves are atomic. A publication by another user less than five
  minutes earlier requires confirmation before overwriting authoring state;
  historical versions used by tasks are preserved. Optimistic revision checks
  are approved, including outside the five-minute window. Multiple users may
  keep independent drafts based on the same or different published versions.
  Draft saves protect their own revision; publication checks protect shared
  publication state. Detailed open semantics are in `docs/product-vision.md`.
- Workflow activation (2026-09-30): activation is manual. The save/publication
  flow offers an explicit activation option; publishing alone does not change
  the active version. Task creation defaults to the selected workflow's active
  version and allows choosing another published version. Later activation
  changes do not alter queued or running tasks.
  Activating a version based on an older version than the current active one
  also requires the confirmed stale-base warning and confirmation.
- Draft testing (2026-09-30): drafts can be saved in any state, including with
  validation errors; only error-free drafts can be tested or published. Users
  can execute valid saved drafts for testing, with explicit `Draft`
  identification in selection and execution. Each test task retains its
  selected saved draft revision despite subsequent edits; no publication,
  activation, or published version increment is needed.
- Task lifecycle (2026-09-30): stop moves the task to `stopping` and waits
  for the active node to finish naturally. Exception: a node waiting for human
  input is stopped immediately; resume relaunches that unfinished node in a new
  container without restoring its old wait/session. Otherwise resume continues
  from the next pending node. Retry relaunches the failed node
  from the last available state. Any user with task access can answer agent
  input requests, and waits have no expiry by default. Script containers die
  on timeout and their node fails.
- Capacity (2026-09-30): global limits only for active main tasks and agents;
  per-team limits are removed. User launches and future scheduled top-level
  launches count as main tasks; child/internal workflows do not add task slots,
  but their agents count toward the global agent limit. Tasks wait in
  queued/pending and nodes in allocating when capacity is unavailable, with
  FIFO admission. Script execution retains its timeout requirement.
- Roles (2026-09-30): viewers, runners, builders, group managers (team-level
  platform configuration, excluding global capacity), and admins. Builders grant
  MCP visibility only to themselves or groups they belong to; global visibility
  is admin-only. Per-team configuration of shared workflows is an open design
  problem.
- Sandboxing (2026-09-30): user Python scripts and artifact validators require
  isolation from host resources beyond their assigned scope. AI nodes request
  completion; the platform coordinates sandboxed validation and reports errors to
  the agent through the adapter layer, with a maximum of three validation
  cycles before the node fails. Agents get a validator MCP.
- Editor (2026-09-30): the properties panel appears only when a node is
  selected; clicking the canvas closes it, and selecting another node swaps
  its content.
- Workflow phases (2026-09-30): the editor groups nodes into visual phase
  containers; their nodes are called steps. Phases execute sequentially: the
  preceding phase must complete before the next starts. Steps within a phase
  can run in parallel or sequentially according to the graph. Phase-level loops
  re-execute the target phase with an iteration identifier. Explicit phases are
  optional; flat workflows can be represented as one implicit phase.
  Collapse/expand and detailed loop accounting remain open.
- Task data (2026-09-30): preserve the effective execution configuration at
  submission, with special protection for MCP credentials and task prompts.
  Reference-based authoring remains unchanged. User-supplied information must
  be shared with all AI steps of the root task, including later loop iterations and dynamic
  workers, independently of the originating container. Authorized agents must
  obtain real credentials when required. Task notes/shared data and protected
  secret retrieval are approved directions. Notes span all phases and nested,
  system, and generated workflows in that root execution, with no recipient IDs
  or per-step read lists. Authorized agents receive the full unmasked content;
  storage, UI, logs, and audit protect sensitive values. Other tasks are isolated.
  Artifact handoff alone is insufficient.
- Dynamic workers (2026-09-30): both work-package execution and system context
  documentation refresh require the same dynamic child-workflow mechanism.
  Packages have dependencies and consume other packages' artifacts, for example
  DAST verification of SAST findings. The independent-item Map proposal was
  rejected as insufficient. Reusing the normal workflow engine for a validated,
  persisted generated graph is proposed in `docs/product-vision.md`; dependency
  support is required from the outset, not postponed.
- Generated-definition simplification (2026-09-30): the Workflow node's builder
  configures AI-equivalent settings (agent, model, MCPs, skills, artifact
  validation). The generator must not author those settings for each package.
  Each agent instance receives the full expected-artifact and validation contract
  from the platform. A minimal package list with IDs, instructions, and dependencies is proposed,
  expanded by Kosmo using that configuration. Note visibility is now root-task-wide,
  superseding the proposed per-Workflow-node scope; agents do not supply recipient
  step IDs.
- Dynamic input/output contracts (2026-09-30): the owner requires explicit
  predecessor-artifact selection per package, independent of ordering-only
  dependencies. Confirmed fields are `depends_on` and `inputs_from`; input sources
  imply dependencies. A stable artifact-collection output with a variable-size
  manifest is confirmed for invoked dynamic workflows, so parent definitions do
  not need to know output cardinality in advance. Include intermediate validated
  outputs; preserve iteration history while prioritizing the latest valid result
  per logical artifact/producer. See `docs/product-vision.md`.
- Workflow failure and errors (2026-09-30): a final child-node failure fails the
  invoking Workflow node, for predefined, system, and dynamic workflows. Partial
  outputs do not constitute success. User-facing errors include an understandable
  title/cause and useful detail, including all three failed validation attempts
  where relevant, rather than generic errors or raw stack traces. Propagated
  failures retain the actual failing step and underlying cause.
- DAST inputs (2026-09-30): target information comes from the initial prompt or
  an earlier AI node that asks the user. Automatic target environment deployment
  is not part of the agreed requirement.
- Extensions (2026-09-30): configuration stores for tools usable from scripts,
  optionally contributing MCP servers and/or skills, with multiple instances at
  personal, group, or global (admin-only) visibility.
- Audit (2026-09-30): user-initiated CRUD actions only (tasks, workflows and
  versions, agents, MCPs, skills, extensions, config changes); runtime task
  activity and reads are not audited. A shared CRUD service wrapper records
  action, user, entity, and changed values, with PII handling to define.
  Task deletion removes everything associated with it.
- Context selection (2026-09-30): the system workflow gathers registered
  context at general/workflow/application levels via a platform query, mounts
  it into the agent container with a metadata file, then refreshes and selects.
  Freshness is tracked per repository: the default branch is the standard
  version; other branches get sections with their particularities.
- Workflow stability and integrity (2026-09-30): any task execution must
  independently ensure its inputs and artifacts are valid and the state is
  recoverable. Workflow execution is durable, with checkpointing for
  intermediate progress.

## Initial agent availability

The initial OpenCode environment exposes global custom agents named `architect`,
`developer`, `designer`, `tester`, and `documentator`. Their definitions were
reviewed and broadly match the requested roles:

- The architect supports planning and final review with remediation packages.
- Development and design agents implement focused packages.
- The tester derives behavioral tests from requirements and supports test-first
  work.
- The documentator maintains `docs/context/` and normally runs after approval.

Those definitions live outside the repository and are not project-portable
configuration. They currently require English deliverables; the documentator
also requires English documentation. The coordinator can communicate with the
owner in Spanish.

`AGENTS.md` adds project-specific expectations for interactive specs, small work
packages, TDD ordering, integration verification, and final review. It does not
create or modify those agent definitions. Availability, model selection, and
any future project-local overrides should be checked when configuring a new
environment. The curated project-specific skill policy is documented below
and in `AGENTS.md`.

## Approved skill choices and local tooling

The project's curated skill policy has been approved. Local discovery and
runtime behavior must be verified separately from the policy itself.

### Local skills (created, NOT tracked in Git)

| Skill ID | Assigned role | Status | Scope |
| --- | --- | --- | --- |
| `kosmo-specification` | Coordinator | Created | Clarification and approved spec under `docs/specs/<feature>.md`. Never chains into Superpowers orchestration or auto-commits. |
| `kosmo-work-packages` | Architect | Created | Package planning and integrated-result review. Never delegates itself. |

Local skills live at `.agents/skills/<skill-name>/SKILL.md` and are excluded from Git via `.gitignore`.

The third-party `skill-creator` from `anthropics/skills` is installed globally
to author and validate these skills. Third-party skills belong in the global
environment; only skills developed specifically for Kosmo belong in the local
`.agents/skills/` directory. Any local `skills-lock.json` is excluded from Git.

### Global skills — approved usage

| Skill ID | Assigned role | Usage in Kosmo |
| --- | --- | --- |
| `impeccable` | Designer | **Primary** design skill for UI/UX, visual design, UX review, and design-system work. |
| `web-design-guidelines` | Designer / Coordinator | **Optional** targeted review for accessibility and web interface guidelines. Not the primary design skill. |
| `test-driven-development` | Tester / Developer / Designer | Test-first cycles within implementation packages. |
| `systematic-debugging` | Any worker | Bug, test failure, or unexpected behavior investigation. |
| `verification-before-completion` | Any worker | Evidence before assertions — runs verification before claiming work is done, before commits, or before PRs. |
| `receiving-code-review` | Any worker | Structured review feedback before blind implementation. |
| `python-design-patterns` | Developer (backend) | Python service and component design, SRP, composition over inheritance. |
| `python-testing-patterns` | Tester / Developer (backend) | Python test strategy, pytest fixtures, mocking, TDD. |
| `vercel-react-best-practices` | Developer (frontend) | React performance and patterns; apply the parts compatible with Vite + React. |
| `vercel-composition-patterns` | Developer (frontend) | **Selected but not yet available/installed** in the current environment. |
| `shadcn/ui` (reference) | Developer / Designer | Component reference implied by the shadcn/ui + Tailwind choice. |

> **Framework-conditional skills:** `fastapi-python` is now **active** because
> FastAPI was chosen on 2026-09-30. `python-performance-optimization` remains
> on-measured-need only.

### Not used

Superpowers orchestration skills — `brainstorming`, `writing-plans`, `executing-plans`, and
`subagent-driven-development` — are **not** imported into the Kosmo workflow.
The coordinator owns orchestration; skills provide domain-specific instructions
within their bounded scope.

Existing global agent definitions have not been rewritten. Some still request
Superpowers skills, so a conflict must be surfaced to the coordinator and the
local agent setup aligned before relying on an end-to-end workflow guarantee.

## Pending decisions

1. **Workflow engine design:** how tasks execute in the background, how task
   state is persisted and recovered, and how parallel nodes are scheduled.
   Temporal is the approved baseline, replacing the earlier minimal-asyncio
   recommendation. Specify checkpoint integration and verify recovery through
   the agreed proof of concept. See
   [Execution orchestration assessment](../research/execution-orchestration.md).
2. **Live task progress in the UI:** SSE versus polling for the MVP.
3. **Human-in-the-loop mapping:** verify how ACP permission/input requests and
   Codex app-server equivalents map to the "needs human attention" task state
   and how the user's reply is routed back into the paused node session.
4. **Agent container management:** base images per agent provider, how the
   backend drives Docker (for example docker-py), resource limits, network
   policy for agent containers, and what gets mounted per node.
5. **Auth implementation details:** session/token strategy, password hashing
   library, and roles/groups data model. New libraries will be required when
   this is implemented; the earlier "excluded libraries" list does not cover
   auth-specific needs.
6. **Architecture:** module boundaries, artifact storage model, and detailed
   backend/frontend structure; to be recorded in a dedicated architecture
   document.
7. **Shared configuration and versions:** workflow/version binding is
   confirmed; agent instruction changes follow the same inheritance/override
   rule as MCP/skill changes. Effective configuration is preserved at submission.
   Still open: secure credential resolution, where inheritance updates land
   (draft vs automatic publication), and how revocation affects execution. See
   `docs/product-vision.md`.
8. **Graph semantics:** start/end nodes, dynamic start forms, decision-branch
   joins, and iteration metadata are confirmed. A child failure fails its Workflow
   invocation; sibling cleanup and blocked-join presentation remain open. The
   detailed dynamic fan-out construct (plan artifact to N
   agent nodes), and loop-count details.
9. **Typed MCP requirements:** how an agent declares a needed capability type
   (for example an Atlassian MCP) and how per-team configurations resolve for
   shared workflows; design open, extensions are one candidate.
10. **Storage and audit details:** artifact storage backend (database versus
    disk), audit retention on task deletion, accounting for voluntary validator
    MCP checks, and task-stop permissions beyond the launcher. The limit of
    three failed completion validations is confirmed.
11. **Workflow visibility and model details (gap):** there is no per-workflow
    visibility or ownership today. `workflows` has no owner/scope column;
    `GET /workflows` and `GET /workflows/{id}` require only authentication, so
    any role (including `runner`) can read any workflow's active definition;
    and any `admin`/`builder` can create a draft on any existing workflow,
    seeded from its latest published version. Existence and draft privacy are
    handled (nonexistent ids and other users' drafts return 404; role-gated
    mutations return 403), but a workflow the caller "cannot access" is not
    representable. Resolve with a scope/owner model like provider configs
    (personal/group/global). Also pending: meaning of public workflow
    visibility and the "Jev" decision technology (future). Editor panel
    behavior is confirmed.
12. **Development-agent configuration:** local setup remains outside version
    control; this is distinct from product-managed agents and integrations.

## Local tooling and version control

The owner has chosen to keep project-local skills and agent configuration out
of Git. Custom skill files live at
`.agents/skills/<skill-name>/SKILL.md`. The `.agents/`, `.opencode/`, `.superpowers/`, and `.impeccable/` directories are ignored, including any local
state those tools create. The first two local skills (`kosmo-specification` and
`kosmo-work-packages`) have been created as documented above.

`AGENTS.md` and official documentation in `docs/` remain versioned project
knowledge. A fresh clone requires separate local tooling setup; the coordinator
must check agent and skill availability rather than assume it from documentation.

## Next documentation milestones

The architecture draft now exists at `docs/architecture.md`; review it with the
owner, resolve its open decisions, and confirm phase boundaries. Then create the
phase-1 feature spec and hand it to the architect for work packages. Keep
proposed decisions separate from approved decisions and implemented capabilities
throughout.

## Phase 2 Roadmap

The following items represent the next logical steps for Kosmo implementation, moving from the core execution foundation towards a usable, feature-rich platform.

### Agent & Provider Evolution
- **Adapter Expansion:** Full implementation of Claude and Codex adapters.
- **Agent Egress Filtering:** Implementing destination-level egress filtering for agent nodes to control outbound connectivity more granularly.

### Workflow & Interaction Depth
- **Interactive Session UX:** Developing the UI and API for live, bidirectional interaction with a running agent session (chatting with an agent from the task detail page).
- **Human-Input Refinement:** Improving the reliability and experience of human-input requests, including restart/replay capabilities and delivery idempotency evidence.
- **Scheduling & Reconciliation:** Advanced scheduling, start-retry reconciliation, and capacity management.

### Platform Features
- **TanStack Query Migration:** Migrating the frontend state management from local state/refetch patterns to a robust TanStack Query implementation.
- **Integrated UI Components:** Developing a unified user interface for task notes, audit logs, and workflow history.
- **Application Management:** Implementation of the concept of "Applications" to group repositories and define workflow-specific requirements.
- **Deployment & Operations:** Transitioning from local Docker Compose development to hosted CI observation and managed production deployments.
